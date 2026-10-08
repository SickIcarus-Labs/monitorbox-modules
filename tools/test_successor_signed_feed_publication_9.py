from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SIGNER=ROOT/"docs/release-intent-history/successor-signed-feed-publish-seq9.yml"
HISTORICAL=ROOT/"docs/release-intent-history/successor-signed-feed-publish-seq8.yml"

def test_historical_sequence9_signer_was_qualified_before_secret_admission():
    raw=SIGNER.read_text("utf-8")
    before,after=raw.split("  sign-publish:",1)
    assert "github.event.issue.number == 128" in raw
    assert "github.event.comment.user.login == 'SickIcarus'" in raw
    assert "startsWith(github.event.comment.body, '/publish-successor-signed-feed-9 sha256:')" in raw
    assert "CORE_SOURCE_SHA: 595262fd989d7b6aa8d8e986d5a1e6655c8318d5" in raw
    assert "FINAL_TAG: seq-9-core-595262fd989d-mods-0fb0a016034a" in raw
    assert "SUPERVISOR_TAG: seq-9-core-595262fd989d" in raw
    assert "Refuse unsigned handoff with recycled platform version or build" in before
    assert '"3.0.0",3' in before and '"1.0.0",4' in before
    assert 'manifest["git_sha"]==os.environ["CORE_SOURCE_SHA"]' in before
    assert "secrets.MONITORBOX_MODULE_SIGNING_KEY" not in before
    assert "successor-feed-unsigned-handoff" in before
    assert "verify_trusted_successor_signer_snapshot.py" in before
    assert "secrets.MONITORBOX_MODULE_SIGNING_KEY" in after
    assert "official-ed25519-1.pub" in after
    assert "--sequence 9" in raw and "--min-sequence 9" in raw
    assert "com.sickicarus.monitorbox.catalog-sequence=9" in raw
    assert "moving dev/beta/stable/latest tags changed: none" in raw
    for mutable in (":stable",":dev",":beta",":latest"):
        assert mutable not in raw

def test_historical_sequence8_signer_is_unchanged_and_distinct():
    old=HISTORICAL.read_text("utf-8")
    fresh=SIGNER.read_text("utf-8")
    assert "seq-8-core-31a4c874c717" in old
    assert "seq-9-core-595262fd989d" in fresh


def test_obsolete_sequence8_signing_dispatch_is_inert():
    active = ROOT / ".github" / "workflows"
    assert not (active / "successor-signed-feed-publish.yml").exists()
    for workflow in active.glob("*.yml"):
        assert "/publish-successor-signed-feed-8 sha256:" not in workflow.read_text("utf-8"), workflow.name


def test_retired_sequence9_signer_is_never_executable_from_issue_comment():
    active = ROOT / ".github" / "workflows"
    assert not (active / "successor-signed-feed-publish-9.yml").exists()
    for workflow in active.glob("*.yml"):
        contents = workflow.read_text("utf-8")
        assert "/publish-successor-signed-feed-9 sha256:" not in contents, workflow.name
