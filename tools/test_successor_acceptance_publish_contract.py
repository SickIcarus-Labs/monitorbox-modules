from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "successor-acceptance-feed.yml"


def test_successor_feed_publication_is_manual_main_only_and_immutable():
    raw = WORKFLOW.read_text("utf-8")
    assert "workflow_dispatch:" in raw
    assert "github.ref == 'refs/heads/main'" in raw
    assert "github.actor == 'SickIcarus'" in raw
    assert "publish-immutable-successor-feed" in raw
    assert "FEED_IMAGE: ghcr.io/sickicarus-labs/monitorbox-successor-feed" in raw
    assert 'tag="mods-$MODULES_SOURCE_SHA-core-$CORE_SOURCE_SHA-seq-$RAW_SEQUENCE"' in raw
    assert "Immutable successor feed tag already exists" in raw
    assert "platforms: linux/amd64,linux/arm64" in raw
    for mutable in (":dev", ":beta", ":stable", ":latest"):
        assert mutable not in raw


def test_successor_feed_signing_is_exact_and_uses_existing_protected_key():
    raw = WORKFLOW.read_text("utf-8")
    assert "MODULES_SOURCE_SHA: 87b164d4b317955210d0b2af5c9e8623cccae197" in raw
    assert "CORE_SOURCE_SHA: 0fdb5572185af7cf7a18fa384d9bedd391cdb4d8" in raw
    assert "REAL_PYTHON_SOURCE_SHA: 3e4cf4ae9072efff941f35a2b0b20b7b493de4cc" in raw
    assert "MONITORBOX_PLATFORM_SIGNING_KEY: ${{ secrets.MONITORBOX_MODULE_SIGNING_KEY }}" in raw
    assert "trust/official-ed25519-1.pub" in raw
    assert '--core-source-sha "$CORE_SOURCE_SHA"' in raw
    assert "--channel stable" in raw
    assert "--valid-hours 168" in raw
    assert "moving public channel tags changed: none" in raw


def test_successor_feed_builds_real_complete_cross_repo_closure_before_signing():
    raw = WORKFLOW.read_text("utf-8")
    for required in (
        "build_successor_wheelhouse.py",
        "discover_archived_debian.py",
        "qualify_successor_runtime_artifacts.py runtime",
        "qualify_successor_runtime_artifacts.py wheelhouse",
        "build_successor_core3_package.py",
        "build_successor_agent3_package.py",
        "build_successor_scaffold_manager_package.py",
        "build_successor_first_party_modules",
        "wc -l)\" = 22",
        "build_successor_acceptance_feed_source.py",
        "verify_platform_index.py",
    ):
        assert required in raw
