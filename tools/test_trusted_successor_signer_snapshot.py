from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
SNAPSHOT=ROOT/"platform"/"successor-signing"/"trusted-source-v1.json"


def blob_sha(path: Path) -> str:
    payload=path.read_bytes()
    return hashlib.sha1(b"blob "+str(len(payload)).encode("ascii")+b"\0"+payload).hexdigest()


def test_trusted_successor_signer_snapshot_matches_exact_reviewed_source_blobs():
    doc=json.loads(SNAPSHOT.read_text("utf-8"))
    assert doc["schema"]==1
    assert doc["source_commit"]=="50673fd26431bd04036ba74df340e8c14ee9b2b0"
    assert set(doc["files"])=={
        "tools/build_platform_index.py",
        "tools/verify_platform_index.py",
        "tools/portable_contracts.py",
        "platform/schema/index-v1.schema.json",
        "platform/portable/first-party-contracts-v1.json",
        "platform/acceptance-feed.Dockerfile",
        "tools/successor_feed_server.go",
        "trust/official-ed25519-1.pub",
    }
    for name,expected in doc["files"].items():
        assert blob_sha(ROOT/name)==expected


def test_snapshot_verifier_executes_successfully():
    subprocess.run(
        [sys.executable,str(ROOT/"tools"/"verify_trusted_successor_signer_snapshot.py")],
        cwd=ROOT,
        check=True,
    )
