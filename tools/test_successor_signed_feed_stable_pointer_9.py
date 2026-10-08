from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
NEW=ROOT/".github/workflows/successor-signed-feed-stable-pointer-9.yml"
OLD=ROOT/".github/workflows/successor-signed-feed-stable-pointer.yml"

def test_sequence9_paired_stable_promotion_requires_exact_operator_authority():
    s=NEW.read_text("utf-8")
    assert "github.event.issue.number == 128" in s
    assert "github.event.comment.user.login == 'SickIcarus'" in s
    assert s.count("github.event.comment.body == '/point-successor-feeds-stable-9'")==2
    assert "EXPECTED_SEQUENCE: \"9\"" in s
    assert "EXPECTED_CORE_SHA: 595262fd989d7b6aa8d8e986d5a1e6655c8318d5" in s
    assert "EXPECTED_DIGEST: sha256:0cb9957271e371e3bcc3f6b82cdc5f697d282f03fd7b5504b8eeb030a3701e72" in s
    assert "SUPERVISOR_EXPECTED_DIGEST: sha256:222b35c294302623f4dea9697124d6a43aef7f085682115f21399457257eb9ef" in s
    assert "SUPERVISOR_EXPECTED_TAG: seq-9-core-595262fd989d" in s
    assert "needs: repoint-supervisor" in s
    assert "Prove full signed feed is qualified before mutating Supervisor stable" in s
    assert "Move Supervisor stable feed pointer without rebuild" in s
    assert "Move successor stable feed pointer without rebuild" in s
    assert "com.sickicarus.monitorbox.scaffold-manager" in s
    assert "docker buildx imagetools create --tag" in s
    assert "docker buildx build" not in s
    assert "secrets.MONITORBOX_MODULE_SIGNING_KEY" not in s

def test_sequence8_promotion_remains_unmodified_and_distinct():
    historical=OLD.read_text("utf-8")
    assert "EXPECTED_SEQUENCE: \"8\"" in historical
    assert "/point-successor-feed-stable-8" in historical
    assert "/point-successor-feeds-stable-9" not in historical
