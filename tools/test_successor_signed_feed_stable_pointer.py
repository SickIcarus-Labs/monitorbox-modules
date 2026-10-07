from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "successor-signed-feed-stable-pointer.yml"


def test_successor_stable_feed_pointer_is_exact_verified_and_rebuild_free():
    raw = WORKFLOW.read_text("utf-8")
    for required in (
        "github.event.issue.number == 128",
        "github.event.comment.user.login == 'SickIcarus'",
        "github.event.comment.body == '/point-successor-feed-stable-6'",
        "EXPECTED_DIGEST: sha256:8e6c647a5105b769353d39ea994a9de8a19603b64d354472a09502e3d1fe2505",
        'EXPECTED_SEQUENCE: "6"',
        "EXPECTED_CORE_SHA: dea5831a350d28d46a7172602b509f98151838cb",
        "EXPECTED_MODULES_SHA: 5dd8ef0c6183840cdf448a1a720bd1231b86c7c4",
        "successor-physical-acceptance-feed",
        'target="$IMAGE:stable"',
        'docker buildx imagetools create --tag "$target" "$IMAGE@$EXPECTED_DIGEST"',
        'test "$resolved" = "$EXPECTED_DIGEST"',
        "rebuild performed: **no**",
    ):
        assert required in raw
    assert "docker buildx build" not in raw


def test_supervisor_stable_pointer_is_exact_verified_manager_only_and_rebuild_free():
    raw = WORKFLOW.read_text("utf-8")
    for required in (
        "github.event.comment.body == '/point-successor-supervisor-feed-stable-7'",
        "SUPERVISOR_IMAGE: ghcr.io/sickicarus-labs/monitorbox-successor-supervisor-feed",
        "SUPERVISOR_EXPECTED_TAG: seq-7-core-dc4aed2acf34",
        "SUPERVISOR_EXPECTED_DIGEST: sha256:a5f09f075f268e4ee541828f30fb6e9ffd929a7e1f62136e04b58aa915a1709a",
        "successor-supervisor-bootstrap-feed",
        'assert len(artifacts)==1',
        'assert len(packages)==1',
        'item["artifact_id"]=="com.sickicarus.monitorbox.scaffold-manager"',
        'target="$SUPERVISOR_IMAGE:stable"',
        'docker buildx imagetools create --tag "$target" "$SUPERVISOR_IMAGE@$SUPERVISOR_EXPECTED_DIGEST"',
        'test "$resolved" = "$SUPERVISOR_EXPECTED_DIGEST"',
        "rebuild performed: **no**",
    ):
        assert required in raw
    supervisor = raw.split("  repoint-supervisor:", 1)[1]
    assert "docker buildx build" not in supervisor
