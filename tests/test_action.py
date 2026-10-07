import pathlib
import re

import pytest
import yaml

_REPOSITORY_ROOT = pathlib.Path(__file__).parent.parent
_ACTION_PATH = _REPOSITORY_ROOT / "action.yml"
_README_PATH = _REPOSITORY_ROOT / "README.md"
_VERSION_PATH = _REPOSITORY_ROOT / "VERSION"
_ANY_SELF_REFERENCE_PATTERN = re.compile(r"CodyCBakerPhD/dist-bundle-action@(v\d+)")

# The tag this tree is meant to be published under. Every reference to this repository must name it, and the release
# workflow checks the tag against it.
_MAJOR_TAG = _VERSION_PATH.read_text(encoding="utf-8").strip()


def _action() -> dict:
    return yaml.safe_load(_ACTION_PATH.read_text(encoding="utf-8"))


@pytest.mark.ai_generated
def test_version_file_names_a_major_tag() -> None:
    """`VERSION` is compared against the release tag, so it has to be shaped like one."""
    assert re.fullmatch(r"v\d+", _MAJOR_TAG) is not None, _MAJOR_TAG


@pytest.mark.ai_generated
def test_every_self_reference_names_the_version_being_published() -> None:
    """
    The README's examples are what a workflow copies, so they must name the tag this tree is published under.

    A reference left on the previous tag still resolves and runs, so nothing else would catch it.
    """
    tags = _ANY_SELF_REFERENCE_PATTERN.findall(_README_PATH.read_text(encoding="utf-8"))

    assert tags != []
    assert set(tags) == {_MAJOR_TAG}


@pytest.mark.ai_generated
def test_marketplace_metadata_is_present() -> None:
    """The Marketplace refuses an action without a name, description and branding."""
    action = _action()

    assert action["name"]
    assert action["description"]
    assert set(action["branding"]) == {"icon", "color"}


@pytest.mark.ai_generated
def test_only_the_paths_are_required() -> None:
    action = _action()

    required = {name for name, spec in action["inputs"].items() if spec.get("required") is True}

    assert required == {"paths"}
    for name, specification in action["inputs"].items():
        assert specification["required"] is True or "default" in specification, name


@pytest.mark.ai_generated
def test_no_input_is_interpolated_into_a_command() -> None:
    """An input expanded into a `run:` body is spliced into the script before bash parses it."""
    for step in _action()["runs"]["steps"]:
        assert "${{" not in step.get("run", ""), step["name"]


@pytest.mark.ai_generated
def test_every_input_reaches_the_script() -> None:
    action = _action()
    forwarded = {value for step in action["runs"]["steps"] for value in step.get("env", {}).values()}

    for name in action["inputs"]:
        assert f"${{{{ inputs.{name} }}}}" in forwarded, name


@pytest.mark.ai_generated
def test_every_output_comes_from_the_script() -> None:
    action = _action()
    step_ids = {step.get("id") for step in action["runs"]["steps"]}

    for name, specification in action["outputs"].items():
        match = re.fullmatch(r"\$\{\{ steps\.([a-z-]+)\.outputs\.([a-z-]+) \}\}", specification["value"])
        assert match is not None, name
        assert match.group(1) in step_ids
        assert match.group(2) == name


@pytest.mark.ai_generated
def test_the_format_default_is_one_the_script_accepts() -> None:
    import dist_bundle  # noqa: PLC0415

    assert _action()["inputs"]["format"]["default"] in dist_bundle.FORMATS
