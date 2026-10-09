"""Defense-in-depth: keep archived successor publisher/repoint commands non-executable.

This test guards the *currently disabled* full-feed and Supervisor stable-write
surface. A future authorized manifest-driven publisher requires an explicit,
reviewed amendment to this test and the publication contract workflow.
This static guard is not GitHub branch protection or a replacement for runtime
registry/permission checks.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / ".github" / "workflows"
RETIRED = (
    "successor-signed-feed-publish.yml",
    "successor-signed-feed-publish-9.yml",
    "successor-signed-feed-stable-pointer.yml",
    "successor-signed-feed-stable-pointer-9.yml",
)
REGISTRY_IDENTITIES = (
    "ghcr.io/sickicarus-labs/monitorbox-successor-signed-feed",
    "ghcr.io/sickicarus-labs/monitorbox-successor-supervisor-feed",
)
RETIRED_COMMANDS = (
    "/point-successor-feed-stable-",
    "/point-successor-supervisor-feed-stable-",
    "/point-successor-feeds-stable-",
    "/publish-successor-signed-feed-",
)


def test_hardcoded_successor_publisher_and_promotion_paths_cannot_execute():
    for name in RETIRED:
        assert not (ACTIVE / name).exists(), name
    assert any(ACTIVE.glob("*.yml")), "missing active workflows directory"
    for workflow in ACTIVE.glob("*.yml"):
        raw = workflow.read_text("utf-8")
        for command in RETIRED_COMMANDS:
            assert command not in raw, (workflow.name, command)


# Explicitly reviewed, narrowly scoped UI58 release authorities. Future
# publishers require a new code-reviewed policy amendment, not merely a new
# workflow with packages:write. An owner comment only works after PR merge.
REVIEWED_UI58_WRITERS = {
    "publish-successor-ui58.yml": (
        "github.actor == 'SickIcarus'",
        "github.event.issue.number == 184",
        "github.event.comment.body == '/publish-successor-ui58-stable'",
        "publish-ui58-signed-channels",
        "gh api \"repos/$GITHUB_REPOSITORY/pulls/184\"",
        "actions/upload-artifact@v4",
        "bash tools/publish_successor_ui58.sh publish",
        "bash tools/publish_successor_ui58.sh promote",
    ),
    "resume-successor-ui58.yml": (
        "github.actor == 'SickIcarus'",
        "github.event.issue.number == 185",
        "github.event.comment.body == '/resume-successor-ui58-stable'",
        "resume-verified-ui58",
        "gh api \"repos/$GITHUB_REPOSITORY/pulls/185\"",
        "actions/upload-artifact@v4",
        "bash tools/publish_successor_ui58.sh preflight",
        "bash tools/publish_successor_ui58.sh promote",
        "tools/verify_successor_ui58_immutable.py",
    ),
}


def test_no_unreviewed_successor_registry_write_path_is_active():
    for workflow in ACTIVE.glob("*.yml"):
        raw = workflow.read_text("utf-8")
        writes = (
            "packages: write" in raw
            or "docker buildx imagetools create" in raw
            or "docker/build-push-action" in raw
        )
        relevant = any(image in raw for image in REGISTRY_IDENTITIES)
        if workflow.name in REVIEWED_UI58_WRITERS:
            assert writes, workflow.name
            assert "github.ref == 'refs/heads/main'" in raw, workflow.name
            assert "github.actor == 'SickIcarus'" in raw, workflow.name
            assert ".state == \"closed\" and .merged_at != null" in raw, workflow.name
            assert ".base.ref == \"main\"" in raw, workflow.name
            assert "persist-credentials: false" in raw, workflow.name
            assert "pull_request:" not in raw, workflow.name
            assert raw.index("actions/upload-artifact@v4") < raw.index(
                "bash tools/publish_successor_ui58.sh promote"
            ), workflow.name
            for sentinel in REVIEWED_UI58_WRITERS[workflow.name]:
                assert sentinel in raw, (workflow.name, sentinel)
            continue
        if relevant:
            assert not writes, workflow.name


def test_protected_signer_and_regular_module_channel_workflow_still_exist():
    # The successor signing implementation is archived for audit; the official
    # current module-channel signing authority remains in the modules repo.
    assert (ACTIVE / "module-channel-publish.yml").is_file()
    assert (ROOT / "trust/official-ed25519-1.pub").is_file()
    for name in (
        "successor-signed-feed-publish-seq8.yml",
        "successor-signed-feed-publish-seq9.yml",
        "successor-signed-feed-stable-pointer-seq8.yml",
        "successor-signed-feed-stable-pointer-seq9.yml",
    ):
        assert (ROOT / "docs/release-intent-history" / name).is_file(), name
