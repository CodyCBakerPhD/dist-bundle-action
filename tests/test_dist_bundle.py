import gzip
import io
import json
import pathlib
import subprocess
import tarfile

import pytest

import dist_bundle


def _git(*arguments: str, cwd: pathlib.Path) -> str:
    return subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repository(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Create a checkout on `main` with one commit, whose `origin` is a local bare repository."""
    remote = tmp_path / "remote.git"
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "init", "--quiet", "--bare", str(remote)], check=True)
    subprocess.run(["git", "init", "--quiet", "--initial-branch", "main", str(checkout)], check=True)
    _git("config", "user.name", "Test", cwd=checkout)
    _git("config", "user.email", "test@example.com", cwd=checkout)
    _git("remote", "add", "origin", str(remote), cwd=checkout)

    (checkout / "data").mkdir()
    (checkout / "data" / "one.json").write_text('{"a": [1, 2]}', encoding="utf-8")
    (checkout / "data" / "nested").mkdir()
    (checkout / "data" / "nested" / "two.json").write_text('{"b": "two"}', encoding="utf-8")
    (checkout / "data" / "notes.txt").write_text("not json", encoding="utf-8")
    (checkout / "README.md").write_text("# readme\n", encoding="utf-8")
    _git("add", ".", cwd=checkout)
    _git("commit", "--quiet", "--message", "initial", cwd=checkout)

    monkeypatch.chdir(checkout)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return checkout


def _remote_file(repository: pathlib.Path, branch: str, filename: str) -> bytes:
    return subprocess.run(
        ["git", "--git-dir", str(repository.parent / "remote.git"), "show", f"refs/heads/{branch}:{filename}"],
        capture_output=True,
        check=True,
    ).stdout


def _tar_names(content: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        return archive.getnames()


@pytest.mark.ai_generated
def test_directories_contribute_every_file_beneath_them(repository: pathlib.Path) -> None:
    files = dist_bundle.resolve_files("data\nREADME.md", repository, file_format="tar.gz")

    assert files == ["README.md", "data/nested/two.json", "data/notes.txt", "data/one.json"]


@pytest.mark.ai_generated
def test_directories_contribute_only_json_to_a_json_bundle(repository: pathlib.Path) -> None:
    files = dist_bundle.resolve_files("data", repository, file_format="json.gz")

    assert files == ["data/nested/two.json", "data/one.json"]


@pytest.mark.ai_generated
def test_globs_blank_lines_and_duplicates(repository: pathlib.Path) -> None:
    files = dist_bundle.resolve_files("\n  data/*.json\n\ndata/one.json\n", repository, file_format="tar.gz")

    assert files == ["data/one.json"]


@pytest.mark.ai_generated
def test_the_git_directory_is_never_bundled(repository: pathlib.Path) -> None:
    files = dist_bundle.resolve_files(".", repository, file_format="tar.gz")

    assert not any(path.startswith(".git/") for path in files)
    assert "README.md" in files


@pytest.mark.ai_generated
@pytest.mark.parametrize(
    ("paths", "message"),
    [
        pytest.param("missing", "matches no files", id="missing"),
        pytest.param("data/*.csv", "matches no files", id="empty-glob"),
        pytest.param("  \n", "names nothing", id="blank"),
        pytest.param("/etc/hostname", "must be relative", id="absolute"),
        pytest.param("../remote.git/HEAD", "outside the repository", id="escaping"),
    ],
)
def test_paths_that_cannot_be_bundled_are_refused(repository: pathlib.Path, paths: str, message: str) -> None:
    with pytest.raises(dist_bundle.DistBundleError, match=message):
        dist_bundle.resolve_files(paths, repository, file_format="tar.gz")


@pytest.mark.ai_generated
@pytest.mark.parametrize("filename", ["", "a/b.tar.gz", ".", ".."])
def test_the_filename_cannot_name_a_directory(filename: str) -> None:
    with pytest.raises(dist_bundle.DistBundleError):
        dist_bundle.validate_filename(filename)


@pytest.mark.ai_generated
def test_the_tarball_depends_only_on_the_content(repository: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Without this, every run would look like a change and push a fresh commit."""
    files = ["README.md", "data/one.json"]
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    dist_bundle.write_tar_gz(files, repository, first)
    (repository / "README.md").touch()
    dist_bundle.write_tar_gz(files, repository, second)

    assert first.read_bytes() == second.read_bytes()
    assert _tar_names(first.read_bytes()) == files


@pytest.mark.ai_generated
def test_the_json_bundle_is_minified_and_skips_invalid_files(
    repository: pathlib.Path,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "bundle.json.gz"

    count = dist_bundle.write_json_gz(["data/notes.txt", "data/one.json"], repository, output)

    assert count == 1
    assert gzip.decompress(output.read_bytes()).decode("utf-8") == '{"data/one.json":{"a":[1,2]}}'
    assert "::warning file=data/notes.txt::" in capsys.readouterr().out


@pytest.mark.ai_generated
def test_a_json_bundle_with_nothing_valid_fails(repository: pathlib.Path, tmp_path: pathlib.Path) -> None:
    with pytest.raises(dist_bundle.DistBundleError, match="valid JSON"):
        dist_bundle.write_json_gz(["data/notes.txt"], repository, tmp_path / "bundle.json.gz")


@pytest.mark.ai_generated
def test_publishing_pushes_a_single_file_orphan_and_leaves_the_checkout_alone(
    repository: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    head = _git("rev-parse", "HEAD", cwd=repository)
    (repository / "data" / "one.json").write_text('{"a": "uncommitted"}', encoding="utf-8")

    exit_code = dist_bundle.main(["--paths", "data", "--output-directory", str(tmp_path)])

    assert exit_code == 0
    remote = str(repository.parent / "remote.git")
    assert _git("--git-dir", remote, "ls-tree", "--name-only", "refs/heads/dist", cwd=repository) == "content.tar.gz"
    assert _git("--git-dir", remote, "rev-list", "--count", "refs/heads/dist", cwd=repository) == "1"
    assert _git("--git-dir", remote, "log", "-1", "--format=%an <%ae>", "refs/heads/dist", cwd=repository) == (
        "Test <test@example.com>"
    )
    assert _remote_file(repository, "dist", "content.tar.gz") == (tmp_path / "content.tar.gz").read_bytes()
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repository) == "main"
    assert _git("rev-parse", "HEAD", cwd=repository) == head
    assert _git("status", "--porcelain", cwd=repository) == "M data/one.json"


@pytest.mark.ai_generated
def test_an_unchanged_bundle_is_not_pushed_again(repository: pathlib.Path, tmp_path: pathlib.Path) -> None:
    outputs = tmp_path / "outputs"
    remote = str(repository.parent / "remote.git")

    dist_bundle.main(["--paths", "data", "--output-directory", str(tmp_path / "first")])
    first_commit = _git("--git-dir", remote, "rev-parse", "refs/heads/dist", cwd=repository)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GITHUB_OUTPUT", str(outputs))
        dist_bundle.main(["--paths", "data", "--output-directory", str(tmp_path / "second")])

    assert _git("--git-dir", remote, "rev-parse", "refs/heads/dist", cwd=repository) == first_commit
    assert "pushed=false\n" in outputs.read_text(encoding="utf-8")
    assert "commit=\n" in outputs.read_text(encoding="utf-8")


@pytest.mark.ai_generated
def test_a_changed_bundle_replaces_the_branch_rather_than_extending_it(
    repository: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    outputs = tmp_path / "outputs"
    remote = str(repository.parent / "remote.git")

    dist_bundle.main(["--paths", "data", "--output-directory", str(tmp_path / "first")])
    (repository / "data" / "three.json").write_text("{}", encoding="utf-8")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GITHUB_OUTPUT", str(outputs))
        dist_bundle.main(["--paths", "data", "--output-directory", str(tmp_path / "second")])

    pushed = _git("--git-dir", remote, "rev-parse", "refs/heads/dist", cwd=repository)
    assert f"commit={pushed}\n" in outputs.read_text(encoding="utf-8")
    assert "pushed=true\n" in outputs.read_text(encoding="utf-8")
    assert _git("--git-dir", remote, "rev-list", "--count", "refs/heads/dist", cwd=repository) == "1"
    assert "data/three.json" in _tar_names(_remote_file(repository, "dist", "content.tar.gz"))


@pytest.mark.ai_generated
def test_a_json_bundle_publishes_under_its_own_name_and_branch(
    repository: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    arguments = ["--paths", "data", "--format", "json.gz", "--filename", "bundle.json.gz", "--branch", "min"]

    exit_code = dist_bundle.main([*arguments, "--commit-message", "bundle", "--output-directory", str(tmp_path)])

    assert exit_code == 0
    assert json.loads(gzip.decompress(_remote_file(repository, "min", "bundle.json.gz"))) == {
        "data/nested/two.json": {"b": "two"},
        "data/one.json": {"a": [1, 2]},
    }
    remote = str(repository.parent / "remote.git")
    assert _git("--git-dir", remote, "log", "-1", "--format=%s", "refs/heads/min", cwd=repository) == "bundle"


@pytest.mark.ai_generated
def test_no_push_only_builds(repository: pathlib.Path, tmp_path: pathlib.Path) -> None:
    exit_code = dist_bundle.main(["--paths", "data", "--no-push", "--output-directory", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "content.tar.gz").exists()
    remote = str(repository.parent / "remote.git")
    assert _git("--git-dir", remote, "for-each-ref", cwd=repository) == ""


@pytest.mark.ai_generated
def test_the_bot_commits_when_no_identity_is_configured(
    repository: pathlib.Path,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git("config", "--unset", "user.name", cwd=repository)
    _git("config", "--unset", "user.email", cwd=repository)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for variable in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(variable, raising=False)

    dist_bundle.main(["--paths", "data", "--output-directory", str(tmp_path)])

    remote = str(repository.parent / "remote.git")
    assert _git("--git-dir", remote, "log", "-1", "--format=%an <%ae>", "refs/heads/dist", cwd=repository) == (
        f"{dist_bundle.BOT_NAME} <{dist_bundle.BOT_EMAIL}>"
    )


@pytest.mark.ai_generated
def test_a_failed_push_is_reported_as_a_workflow_error(
    repository: pathlib.Path,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _git("remote", "set-url", "origin", str(tmp_path / "nowhere.git"), cwd=repository)

    exit_code = dist_bundle.main(["--paths", "data", "--output-directory", str(tmp_path)])

    assert exit_code == 1
    assert "::error::`git push" in capsys.readouterr().out


@pytest.mark.ai_generated
def test_files_are_published_as_they_are_under_their_paths(repository: pathlib.Path, tmp_path: pathlib.Path) -> None:
    head = _git("rev-parse", "HEAD", cwd=repository)
    outputs = tmp_path / "outputs"

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GITHUB_OUTPUT", str(outputs))
        exit_code = dist_bundle.main(["--paths", "data", "--format", "files"])

    assert exit_code == 0
    remote = str(repository.parent / "remote.git")
    assert _git("--git-dir", remote, "ls-tree", "-r", "--name-only", "refs/heads/dist", cwd=repository).split() == [
        "data/nested/two.json",
        "data/notes.txt",
        "data/one.json",
    ]
    assert _git("--git-dir", remote, "rev-list", "--count", "refs/heads/dist", cwd=repository) == "1"
    assert _remote_file(repository, "dist", "data/nested/two.json") == b'{"b": "two"}'
    assert _remote_file(repository, "dist", "data/notes.txt") == b"not json"
    assert "pushed=true\n" in outputs.read_text(encoding="utf-8")
    # The throwaway index leaves the caller's own index, and its checkout, alone.
    assert _git("rev-parse", "HEAD", cwd=repository) == head
    assert _git("status", "--porcelain", cwd=repository) == ""


@pytest.mark.ai_generated
def test_files_can_come_from_outside_the_repository(repository: pathlib.Path, tmp_path: pathlib.Path) -> None:
    staged = tmp_path / "staged"
    (staged / "derivatives").mkdir(parents=True)
    (staged / "derivatives" / "cache.jsonl.gz").write_bytes(gzip.compress(b'{"a": 1}\n', mtime=0))
    (staged / "dataset_description.json").write_text('{"Name": "cache"}', encoding="utf-8")

    exit_code = dist_bundle.main(["--paths", ".", "--root", str(staged), "--format", "files"])

    assert exit_code == 0
    remote = str(repository.parent / "remote.git")
    assert _git("--git-dir", remote, "ls-tree", "-r", "--name-only", "refs/heads/dist", cwd=repository).split() == [
        "dataset_description.json",
        "derivatives/cache.jsonl.gz",
    ]
    assert gzip.decompress(_remote_file(repository, "dist", "derivatives/cache.jsonl.gz")) == b'{"a": 1}\n'


@pytest.mark.ai_generated
def test_unchanged_files_are_not_pushed_again_and_removed_ones_leave_the_branch(
    repository: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    outputs = tmp_path / "outputs"
    remote = str(repository.parent / "remote.git")

    dist_bundle.main(["--paths", "data", "--format", "files"])
    first_commit = _git("--git-dir", remote, "rev-parse", "refs/heads/dist", cwd=repository)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GITHUB_OUTPUT", str(outputs))
        dist_bundle.main(["--paths", "data", "--format", "files"])
    assert _git("--git-dir", remote, "rev-parse", "refs/heads/dist", cwd=repository) == first_commit
    assert "pushed=false\n" in outputs.read_text(encoding="utf-8")

    (repository / "data" / "notes.txt").unlink()
    dist_bundle.main(["--paths", "data", "--format", "files"])

    published = _git("--git-dir", remote, "ls-tree", "-r", "--name-only", "refs/heads/dist", cwd=repository)
    assert "data/notes.txt" not in published.split()
    assert _git("--git-dir", remote, "rev-list", "--count", "refs/heads/dist", cwd=repository) == "1"
