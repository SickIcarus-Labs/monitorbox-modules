from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github"/"workflows"/"successor-signed-feed-publish.yml"


def test_signed_feed_publication_is_exact_user_and_issue_scoped():
    raw=WORKFLOW.read_text("utf-8")
    for required in (
        "github.event.issue.number == 128",
        "github.event.comment.user.login == 'SickIcarus'",
        "startsWith(github.event.comment.body, '/publish-successor-signed-feed-1 sha256:')",
        "CORE_SOURCE_SHA: edf9eaceeb699069341688060663669cbe640432",
        "MODULES_SOURCE_SHA: 50673fd26431bd04036ba74df340e8c14ee9b2b0",
        "REAL_PYTHON_SOURCE_SHA: 3e4cf4ae9072efff941f35a2b0b20b7b493de4cc",
        "HANDOFF_IMAGE: ghcr.io/sickicarus-labs/monitorbox-successor-feed",
        "FINAL_IMAGE: ghcr.io/sickicarus-labs/monitorbox-successor-signed-feed",
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
        "--sequence 1",
        "--valid-hours 168",
        "Immutable signed successor feed already exists",
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
