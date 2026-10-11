"""Safety acceptance for unpublished #757 Backup/Restore module handoff."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent / "dev_backup_restore"
sys.path.insert(0, str(ROOT))
from native_archive_intent import NativeArchiveIntentLedger, ArchiveIntentUnavailable
from native_archive_handoff import NativeArchiveHandoff


class FakeAdmin:
    def require(self, request, csrf=False):
        if not request.logged_in or (csrf and not request.csrf):
            raise PermissionError("current administrator and CSRF required")


class FakeSignedIPC:
    def __init__(self, ledger, payload=b"synthetic signed ZIP fixture", truncated=False):
        self.ledger = ledger
        self.payload = payload
        self.truncated = truncated
        self.phase = "working"
        self.requests = []
        self.begin_count = 0
        self.claim_count = 0

    def begin_for_admin(self, auth, request, request_id):
        auth.require(request, csrf=True)
        assert self.ledger.read().request_id == request_id, (
            "Core attempted the irreversible RPC before durable nonce fsync"
        )
        self.requests.append(request_id)
        self.begin_count += 1
        return request_id

    def status_for_admin(self, auth, request, request_id):
        auth.require(request)
        return SimpleNamespace(
            request_id=request_id, phase=self.phase,
            terminal=self.phase in {"ready", "failed", "claimed"},
        )

    def claim_into_for_admin(self, auth, request, request_id, sink):
        auth.require(request, csrf=True)
        assert request_id == self.ledger.read().request_id
        self.claim_count += 1
        if self.truncated:
            sink.write(self.payload[:5])
            self.phase = "claimed"
            raise OSError("simulated destroyed connection after one-time native claim")
        assert sink.write(self.payload) == len(self.payload)
        self.phase = "claimed"
        return len(self.payload)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mb-native-zip-handoff-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.state = root / "backup-intent"
        self.state.mkdir(mode=0o700)
        self.staging = root / "vault-staging"
        self.staging.mkdir(mode=0o700)
        self.vault = root / "vault"
        self.vault.mkdir(mode=0o700)
        self.ledger = NativeArchiveIntentLedger(self.state)
        self.admin = FakeAdmin()
        self.valid = SimpleNamespace(logged_in=True, csrf=True)
        self.no_csrf = SimpleNamespace(logged_in=True, csrf=False)
        self.invalid = SimpleNamespace(logged_in=False, csrf=False)
        self.ipc = FakeSignedIPC(self.ledger)
        self.verified = []
        self.published = []

    def verify(self, path):
        contents = path.read_bytes()
        if not contents.startswith(b"synthetic signed ZIP"):
            raise ValueError("invalid signed ZIP")
        self.verified.append(contents)

    def publish(self, path, request_id):
        # Synthetic analogue of module-owned transactional vault publication.
        assert self.verified, "unverified archive was published"
        dest = self.vault / (request_id + ".zip")
        os.replace(path, dest)
        with dest.open("rb") as stream:
            os.fsync(stream.fileno())
        fd = os.open(self.vault, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        self.published.append(dest)
        return request_id

    def handoff(self):
        return NativeArchiveHandoff(
            NativeArchiveIntentLedger(self.state),
            self.ipc, self.staging, self.verify, self.publish,
        )

    def test_admin_rejected_before_nonce_or_native_submission(self):
        handoff = self.handoff()
        for request in (self.invalid, self.no_csrf):
            with self.assertRaises(PermissionError):
                handoff.begin_for_admin(self.admin, request)
        self.assertIsNone(self.ledger.read())
        self.assertEqual(self.ipc.begin_count, 0)

    def test_lost_ack_and_signed_core_restart_reuse_exact_durable_id(self):
        first = self.handoff().begin_for_admin(self.admin, self.valid)
        self.assertEqual(self.ledger.read().request_id, first)
        # A restarted Core creates a fresh in-memory adapter and client,
        # never a new request identity for the possibly accepted job.
        second = self.handoff().begin_for_admin(self.admin, self.valid)
        self.assertEqual(first, second)
        self.assertEqual(self.ipc.requests, [first, first])
        self.ipc.phase = "ready"
        self.assertEqual(self.handoff().status_for_admin(self.admin, self.valid).phase, "ready")
        self.assertEqual(self.ledger.read().phase, "ready")

    def test_claim_verified_private_temp_published_then_retired(self):
        first = self.handoff().begin_for_admin(self.admin, self.valid)
        self.ipc.phase = "ready"
        self.handoff().status_for_admin(self.admin, self.valid)
        with self.assertRaises(PermissionError):
            self.handoff().receive_for_admin(self.admin, self.no_csrf)
        self.assertEqual(self.ipc.claim_count, 0)
        archive_id = self.handoff().receive_for_admin(self.admin, self.valid)
        self.assertEqual(archive_id, first)
        self.assertEqual(self.published[0].read_bytes(), self.ipc.payload)
        self.assertEqual(self.verified, [self.ipc.payload])
        self.assertIsNone(self.ledger.read())
        self.assertEqual(self.ipc.claim_count, 1)
        self.assertFalse(list(self.staging.glob("*.partial")))

    def test_interrupted_one_time_claim_never_publishes_and_retains_intent(self):
        first = self.handoff().begin_for_admin(self.admin, self.valid)
        self.ipc.phase = "ready"
        self.handoff().status_for_admin(self.admin, self.valid)
        self.ipc.truncated = True
        with self.assertRaises(OSError):
            self.handoff().receive_for_admin(self.admin, self.valid)
        self.assertEqual(self.ledger.read().request_id, first)
        self.assertEqual(self.ledger.read().phase, "ready")
        self.assertEqual(self.published, [])
        self.assertEqual(list(self.staging.iterdir()), [])
        # After a fresh Core login, Supervisor truth is CLAIMED: operator
        # can explicitly retire the failed delivery before requesting anew.
        self.assertEqual(self.handoff().status_for_admin(self.admin, self.valid).phase, "claimed")
        self.ledger.acknowledge_terminal(first)
        self.assertNotEqual(self.handoff().begin_for_admin(self.admin, self.valid), first)

    def test_verifier_failure_prevents_publication_and_terminal_ack(self):
        first = self.handoff().begin_for_admin(self.admin, self.valid)
        self.ipc.phase = "ready"
        self.handoff().status_for_admin(self.admin, self.valid)
        self.ipc.payload = b"forged invalid zip"
        with self.assertRaises(ValueError):
            self.handoff().receive_for_admin(self.admin, self.valid)
        self.assertEqual(self.ledger.read().request_id, first)
        self.assertFalse(self.published)
        self.assertEqual(list(self.staging.iterdir()), [])

    def test_unsafe_staging_rejected(self):
        self.staging.chmod(0o755)
        with self.assertRaises(ArchiveIntentUnavailable):
            self.handoff()


if __name__ == "__main__":
    unittest.main()
