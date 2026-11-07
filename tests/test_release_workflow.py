"""Tests for .github/workflows/release.yml: a pushed tag publishes nothing by itself; a maintainer runs the workflow
by hand with the tag, and it checks out and checks that tag."""
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release.yml").read_text()


def triggers() -> str:
    """The workflow's `on:` block, up to the next top-level key."""
    block = WORKFLOW.split("\non:\n", 1)[1]
    return block.split("\n\n", 1)[0]


def test_the_release_runs_only_by_hand():
    on = triggers()
    assert "workflow_dispatch:" in on and "tag:" in on and "required: true" in on
    keys = {line.strip() for line in on.splitlines() if line.startswith("  ") and not line.startswith("   ")}
    assert keys == {"workflow_dispatch:"}  # no push, tag or release trigger beside it


def test_each_job_checks_out_the_tag_it_was_given():
    checkouts = WORKFLOW.count("uses: actions/checkout@")
    assert checkouts == 3 and WORKFLOW.count("ref: refs/tags/${{ inputs.tag }}") == checkouts
    assert "GITHUB_REF_NAME" not in WORKFLOW  # a hand run's ref is the branch, never the tag


def test_the_tag_must_match_every_version():
    assert 'tag="${TAG#v}"' in WORKFLOW
    for source in ("colony/__init__.py", "./npm/package.json", "./.claude-plugin/plugin.json"):
        assert source in WORKFLOW
