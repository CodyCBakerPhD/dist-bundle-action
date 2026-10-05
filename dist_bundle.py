"""
Compress a set of repository paths into one file and force-push it as the sole content of an orphan branch.

The commit is assembled from git plumbing rather than by checking the branch out, so the caller's checkout, index and
current branch are left exactly as they were and any step may follow this one.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

FORMATS = ("tar.gz", "json.gz")
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
_GLOB_CHARACTERS = frozenset("*?[")


class DistBundleError(Exception):
    """A problem with the inputs or the repository, reported as a workflow error rather than a traceback."""


def resolve_files(paths: str, root: pathlib.Path, *, file_format: str) -> list[str]:
    """
    Expand newline-separated files, directories and glob patterns into sorted, unique, root-relative POSIX paths.

    A directory contributes every file beneath it, or only its `.json` files for the `json.gz` format. A file or glob
    match is always taken as named. Anything inside a `.git` directory is never included.
    """
    resolved_root = root.resolve()
    directory_pattern = "*.json" if file_format == "json.gz" else "*"
    entries = [line.strip() for line in paths.splitlines() if line.strip()]
    if not entries:
        message = "`paths` names nothing to bundle."
        raise DistBundleError(message)

    files: set[str] = set()
    for entry in entries:
        if pathlib.PurePath(entry).is_absolute():
            message = f"`{entry}` must be relative to the repository root."
            raise DistBundleError(message)

        matches = sorted(root.glob(entry)) if _GLOB_CHARACTERS.intersection(entry) else [root / entry]
        candidates = [
            candidate
            for match in matches
            if match.exists()
            for candidate in (sorted(match.rglob(directory_pattern)) if match.is_dir() else [match])
        ]
        found = [
            candidate for candidate in candidates if candidate.is_file() and not _is_in_git_directory(candidate, root)
        ]
        if not found:
            message = f"`{entry}` matches no files."
            raise DistBundleError(message)

        for candidate in found:
            if not candidate.resolve().is_relative_to(resolved_root):
                message = f"`{candidate.relative_to(root).as_posix()}` resolves outside the repository."
                raise DistBundleError(message)
            files.add(candidate.relative_to(root).as_posix())

    return sorted(files)


def _is_in_git_directory(path: pathlib.Path, root: pathlib.Path) -> bool:
    return ".git" in path.relative_to(root).parts


def _normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
    # Checkout times and runner accounts differ on every run. Dropping them makes the archive a function of the
    # content alone, which is what lets an unchanged bundle be recognized and left unpushed.
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o755 if info.mode & 0o111 else 0o644
    return info


def write_tar_gz(files: Iterable[str], root: pathlib.Path, output: pathlib.Path) -> int:
    """Write a reproducible gzipped tarball of `files`, stored under their root-relative paths."""
    count = 0
    with (
        output.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT, dereference=True) as archive,
    ):
        for relative in files:
            archive.add(root / relative, arcname=relative, recursive=False, filter=_normalize)
            count += 1
    return count


def write_json_gz(files: Iterable[str], root: pathlib.Path, output: pathlib.Path) -> int:
    """
    Write one minified, gzipped JSON object mapping each root-relative path to that file's parsed content.

    A file that is not valid UTF-8 JSON is skipped with a warning rather than failing the bundle.
    """
    bundle = {}
    for relative in files:
        parsed, error = _parse_json(root / relative)
        if error is None:
            bundle[relative] = parsed
        else:
            _log(f"::warning file={relative}::Skipped from the bundle because it is not valid JSON: {error}")
    if not bundle:
        message = "None of the matched files are valid JSON."
        raise DistBundleError(message)

    minified = json.dumps(bundle, separators=(",", ":"), ensure_ascii=False)
    with (
        output.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed,
    ):
        compressed.write(minified.encode("utf-8"))
    return len(bundle)


def _parse_json(path: pathlib.Path) -> tuple[object, Exception | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (json.JSONDecodeError, UnicodeDecodeError) as exception:
        return None, exception


def validate_filename(filename: str) -> None:
    """Refuse a filename carrying a directory, since the bundle is the single entry of a git tree."""
    if not filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
        message = f"`filename` must be a plain file name, got `{filename}`."
        raise DistBundleError(message)


def _git(*arguments: str, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603
            ["git", *arguments],  # noqa: S607
            input=stdin,
            capture_output=True,
            text=True,
            check=check,
            env=_identity_environment(),
        )
    except subprocess.CalledProcessError as exception:
        message = f"`git {' '.join(arguments)}` failed: {exception.stderr.strip()}"
        raise DistBundleError(message) from exception


def _identity_environment() -> dict[str, str]:
    """Commit as whoever the repository is configured as, falling back to the Actions bot."""
    environment = dict(os.environ)
    for key, variables, fallback in (
        ("user.name", ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"), BOT_NAME),
        ("user.email", ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"), BOT_EMAIL),
    ):
        configured = subprocess.run(  # noqa: S603
            ["git", "config", "--get", key],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        for variable in variables:
            environment.setdefault(variable, configured or fallback)
    return environment


def publish(bundle: pathlib.Path, *, filename: str, branch: str, commit_message: str, remote: str) -> str | None:
    """
    Force-push `bundle` as the only file on `branch`, returning the new commit, or `None` when it was already there.

    The branch keeps a single commit, so it never accumulates the history of every bundle it has held.
    """
    blob = _git("hash-object", "-w", "--", str(bundle)).stdout.strip()
    tree = _git("mktree", stdin=f"100644 blob {blob}\t{filename}\n").stdout.strip()

    # A failed fetch is a branch that does not exist yet. Anything worse fails the push below, with git's own message.
    fetched = _git("fetch", "--quiet", "--no-tags", remote, f"refs/heads/{branch}", check=False)
    if fetched.returncode == 0 and _git("rev-parse", "FETCH_HEAD^{tree}").stdout.strip() == tree:
        return None

    commit = _git("commit-tree", tree, "-m", commit_message).stdout.strip()
    _git("push", "--force", remote, f"{commit}:refs/heads/{branch}")
    return commit


def _log(line: str) -> None:
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


def _append(variable: str, text: str) -> None:
    destination = os.environ.get(variable)
    if destination:
        with pathlib.Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(text)


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", required=True, help="Newline-separated files, directories or glob patterns.")
    parser.add_argument("--format", dest="file_format", choices=FORMATS, default="tar.gz")
    parser.add_argument("--filename", default="", help="Name of the bundle on the branch. Defaults to content.FORMAT.")
    parser.add_argument("--branch", default="dist")
    parser.add_argument("--commit-message", default="update dist bundle [skip ci]")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path())
    parser.add_argument("--output-directory", type=pathlib.Path, default=None)
    parser.add_argument("--no-push", action="store_true", help="Build the bundle without publishing it.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build the bundle, publish it, and report both to the workflow."""
    arguments = _parse(argv)
    filename = arguments.filename or f"content.{arguments.file_format}"
    output_directory = arguments.output_directory or pathlib.Path(
        tempfile.mkdtemp(prefix="dist-bundle-", dir=os.environ.get("RUNNER_TEMP")),
    )

    try:
        validate_filename(filename)
        files = resolve_files(arguments.paths, arguments.root, file_format=arguments.file_format)
        output_directory.mkdir(parents=True, exist_ok=True)
        output = output_directory / filename
        writer = write_json_gz if arguments.file_format == "json.gz" else write_tar_gz
        count = writer(files, arguments.root, output)
        size = output.stat().st_size
        _log(f"Bundled {count} file(s) into {filename} ({size} bytes).")

        commit = None
        if not arguments.no_push:
            commit = publish(
                output,
                filename=filename,
                branch=arguments.branch,
                commit_message=arguments.commit_message,
                remote=arguments.remote,
            )
    except DistBundleError as exception:
        _log(f"::error::{exception}")
        return 1

    if arguments.no_push:
        outcome = "Not pushed, as asked."
    elif commit is None:
        outcome = f"`{arguments.branch}` already holds this exact bundle, so nothing was pushed."
    else:
        outcome = f"Pushed to `{arguments.branch}` as {commit}."
    _log(outcome)

    _append("GITHUB_OUTPUT", f"path={output}\npushed={'true' if commit else 'false'}\ncommit={commit or ''}\n")
    _append("GITHUB_STEP_SUMMARY", f"Bundled {count} file(s) into `{filename}` ({size} bytes). {outcome}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
