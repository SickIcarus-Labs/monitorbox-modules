from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github"/"workflows"/"successor-signed-feed-publish.yml"
SUPERVISOR_SEQ7=ROOT/".github"/"workflows"/"successor-supervisor-feed-seq7-publish.yml"


def test_signed_feed_publication_is_exact_user_and_issue_scoped():
    raw=WORKFLOW.read_text("utf-8")
    for required in (
        "github.event.issue.number == 128",
        "github.event.comment.user.login == 'SickIcarus'",
        "startsWith(github.event.comment.body, '/publish-successor-signed-feed-7 sha256:')",
        "digest=\"${COMMAND#\'/publish-successor-signed-feed-7 \'}\"",
        "CORE_SOURCE_SHA: dc4aed2acf3465d97476e01ca5d2063e61b9901d",
        "MODULES_SOURCE_SHA: 5dd8ef0c6183840cdf448a1a720bd1231b86c7c4",
        "REAL_PYTHON_SOURCE_SHA: 3e4cf4ae9072efff941f35a2b0b20b7b493de4cc",
        "HANDOFF_IMAGE: ghcr.io/sickicarus-labs/monitorbox-successor-feed",
        "FINAL_IMAGE: ghcr.io/sickicarus-labs/monitorbox-successor-signed-feed",
        "SUPERVISOR_IMAGE: ghcr.io/sickicarus-labs/monitorbox-successor-supervisor-feed",
    ):
        assert required in raw


def test_handoff_is_digest_pinned_and_deeply_admitted_before_secret_is_available():
    raw=WORKFLOW.read_text("utf-8")
    preflight=raw.split("  sign-publish:",1)[0]
    assert "MONITORBOX_MODULE_SIGNING_KEY" not in preflight
    for required in (
        '[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]',
        'pinned="$HANDOFF_IMAGE@$HANDOFF_DIGEST"',
        "successor-feed-unsigned-handoff",
        "com.sickicarus.monitorbox.package-count",
        'wc -l)" = 22',
        "tools/build_platform_index.py",
        "tools/verify_platform_index.py",
        "ephemeral.seed",
        "verify_trusted_successor_signer_snapshot.py",
    ):
        assert required in preflight


def test_protected_signer_matches_official_root_and_publishes_only_immutable_feed():
    raw=WORKFLOW.read_text("utf-8")
    signed=raw.split("  sign-publish:",1)[1]
    for required in (
        "secrets.MONITORBOX_MODULE_SIGNING_KEY",
        "official-ed25519-1.pub",
        "protected signer does not match official-ed25519-1",
        "--channel stable",
        "--sequence 7",
        "--valid-hours 168",
        "Immutable successor publication identity already exists",
        "platforms: linux/amd64,linux/arm64",
        "provenance: false",
        "steps.publish.outputs.digest",
        'docker pull "$PINNED"',
        "--cap-drop ALL --security-opt no-new-privileges:true",
        "urllib.request.ProxyHandler({})",
        "moving dev/beta/stable/latest tags changed: none",
    ):
        assert required in signed
    for mutable in (":dev",":beta",":stable",":latest"):
        assert mutable not in raw


def test_protected_signer_derives_manager_only_supervisor_bootstrap_feed():
    raw=WORKFLOW.read_text("utf-8")
    signed=raw.split("  sign-publish:",1)[1]
    for required in (
        "Build signed per-architecture Supervisor bootstrap authorities",
        'item.get("artifact_id")=="com.sickicarus.monitorbox.scaffold-manager"',
        'item.get("kind")=="scaffold-manager"',
        'and item.get("platform",{}).get("arch")==arch',
        'assert len(matches)==1',
        "Publish architecture-minimal Supervisor bootstrap feed",
        "successor-supervisor-bootstrap-feed",
        "Verify Supervisor feed contains exactly one manager on each architecture",
        'assert len(artifacts)==1',
        'assert len(packages)==1',
        'docker buildx imagetools create',
        "steps.supervisor.outputs.pinned",
    ):
        assert required in signed
    # Bootstrap images must be immutable sequence identities; stable movement
    # remains a separately guarded pointer operation.
    assert "$SUPERVISOR_IMAGE:stable" not in signed




def test_sequence7_signed_publication_owns_both_full_and_supervisor_immutable_feeds():
    raw=WORKFLOW.read_text("utf-8")
    assert "FINAL_TAG: seq-7-core-dc4aed2acf34-mods-5dd8ef0c6183" in raw
    assert "SUPERVISOR_TAG: seq-7-core-dc4aed2acf34" in raw
    assert "com.sickicarus.monitorbox.catalog-sequence=7" in raw
    assert "catalog sequence: 7" in raw
    assert "supervisor-backfill:" not in raw
    assert "/publish-successor-supervisor-feed-6" not in raw


def test_dedicated_supervisor_seq7_signer_consumes_exact_immutable_candidate():
    raw=SUPERVISOR_SEQ7.read_text("utf-8")
    for required in (
        "github.event.issue.number == 128",
        "github.event.comment.user.login == 'SickIcarus'",
        "/publish-successor-supervisor-feed-7 sha256:c4161f57445d4aeb7639e59ae4de505e040867f31e616a7c0407bdc4fa035292",
        "CANDIDATE_DIGEST: sha256:c4161f57445d4aeb7639e59ae4de505e040867f31e616a7c0407bdc4fa035292",
        "MANAGER_SOURCE_SHA: 9132101125c05a3855277d8de3588101ecd55b80",
        "AMD64_PACKAGE_SHA256: 8568640092c20b088e1ebcd244053cd0cab3f458ea705f1ed180eb1454d397ea",
        "ARM64_PACKAGE_SHA256: 2e79fd4c4b942a3ef33f1aab6d8dd6956596d490a867a618028ea6472c9fa58f",
        "FINAL_TAG: seq-7-manager-9132101125c0",
    ):
        assert required in raw


def test_dedicated_supervisor_seq7_signer_preserves_protected_signing_boundary():
    raw=SUPERVISOR_SEQ7.read_text("utf-8")
    presecret=raw.split("- name: Require official protected signer",1)[0]
    assert "MONITORBOX_MODULE_SIGNING_KEY" not in presecret
    for required in (
        "secrets.MONITORBOX_MODULE_SIGNING_KEY",
        "protected signer does not match official-ed25519-1",
        "--sequence \"$CATALOG_SEQUENCE\"",
        "--valid-hours 168",
        "successor-supervisor-bootstrap-feed",
        "assert len(artifacts)==1 and len(packages)==1",
        "stable pointer changed: **no**",
    ):
        assert required in raw
    assert "$FINAL_IMAGE:stable" not in raw
