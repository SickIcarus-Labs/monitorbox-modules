from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "successor-signed-feed-stable-pointer.yml"


def test_successor_stable_feed_pointer_is_exact_verified_and_rebuild_free():
    raw = WORKFLOW.read_text("utf-8")
    for required in (
        "github.event.issue.number == 128",
        "github.event.comment.user.login == 'SickIcarus'",
        "github.event.comment.body == '/point-successor-feed-stable-8'",
        "EXPECTED_DIGEST: sha256:c2b4d3a02cdb528bba4bccc5248fbe4f9d7cd6fe1c974ff311b8c99718db9339",
        'EXPECTED_SEQUENCE: "8"',
        "EXPECTED_CORE_SHA: 31a4c874c717e9e1ab2a6600c7b18d488e1a1abe",
        "EXPECTED_MODULES_SHA: 0fb0a016034a559e2f79300625aaa01d33f754cb",
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
        "github.event.comment.body == '/point-successor-supervisor-feed-stable-8'",
        "SUPERVISOR_IMAGE: ghcr.io/sickicarus-labs/monitorbox-successor-supervisor-feed",
        "SUPERVISOR_EXPECTED_TAG: seq-8-core-31a4c874c717",
        "SUPERVISOR_EXPECTED_DIGEST: sha256:ad15eb4f91e8c47a06d3ccba11657408d90128e7ac1ba623409e32835ec4ee8c",
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
