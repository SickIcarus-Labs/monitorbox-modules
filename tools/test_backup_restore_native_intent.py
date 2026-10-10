"""Unpublished Backup/Restore signed native archive nonce safety tests."""
from __future__ import annotations
import importlib.util
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
import sys

SOURCE = (Path(__file__).resolve().parent.parent / "sources" /
          "backup-restore" / "next" / "native_archive_intent.py")
spec = importlib.util.spec_from_file_location("native_archive_intent_dev", SOURCE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
Ledger = module.NativeArchiveIntentLedger
Invalid = module.ArchiveIntentUnavailable


class NativeIntentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mb-native-intent-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.root.mkdir(mode=0o700)

    def test_lost_ack_restarts_with_exact_durable_nonce(self):
        first = Ledger(self.root).prepare()
        self.assertEqual(len(first.request_id), 32)
        self.assertEqual(first.phase, "submitting")
        self.assertEqual(first, Ledger(self.root).prepare())
        self.assertEqual(
            stat.S_IMODE((self.root / "native-full-archive-intent.json").stat().st_mode),
            0o600,
        )
        self.assertEqual(Ledger(self.root).observe(first.request_id, "working").request_id,
                         first.request_id)
        self.assertEqual(Ledger(self.root).prepare().request_id, first.request_id)
        self.assertEqual(Ledger(self.root).observe(first.request_id, "ready").phase, "ready")
        with self.assertRaises(Invalid):
            Ledger(self.root).acknowledge_terminal(first.request_id)
        self.assertEqual(Ledger(self.root).observe(first.request_id, "claimed").phase,
                         "claimed")
        Ledger(self.root).acknowledge_terminal(first.request_id)
        self.assertNotEqual(Ledger(self.root).prepare().request_id, first.request_id)

    def test_concurrent_core_retries_choose_one_nonce(self):
        barrier = threading.Barrier(8)
        identities, errors = [], []
        def worker():
            try:
                barrier.wait(timeout=5)
                identities.append(Ledger(self.root).prepare().request_id)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker) for _ in range(8)]
        for item in threads: item.start()
        for item in threads: item.join(timeout=8)
        self.assertFalse(errors, errors)
        self.assertEqual(len(identities), 8)
        self.assertEqual(len(set(identities)), 1)

    def test_terminal_replay_wrong_id_and_status_regression_rejected(self):
        intent = Ledger(self.root).prepare()
        with self.assertRaises(Invalid):
            Ledger(self.root).observe("f" * 32, "ready")
        with self.assertRaises(Invalid):
            Ledger(self.root).observe(intent.request_id, "submitting")
        Ledger(self.root).observe(intent.request_id, "ready")
        with self.assertRaises(Invalid):
            Ledger(self.root).observe(intent.request_id, "working")
        Ledger(self.root).observe(intent.request_id, "failed")
        with self.assertRaises(Invalid):
            Ledger(self.root).observe(intent.request_id, "ready")
        with self.assertRaises(Invalid):
            Ledger(self.root).acknowledge_terminal("a" * 32)
        self.assertEqual(Ledger(self.root).prepare().request_id, intent.request_id)

    def test_unsafe_root_corruption_duplicate_keys_and_symlinks_fail_closed(self):
        insecure = self.root / "not-private"
        insecure.mkdir(mode=0o755)
        with self.assertRaises(Invalid): Ledger(insecure)
        linked = self.root / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(Invalid): Ledger(linked)
        ledger = Ledger(self.root)
        path = self.root / "native-full-archive-intent.json"
        path.write_text('{"schema":1,"schema":1,"request_id":"' +
                        "a" * 32 + '","created_ns":1,"phase":"working"}')
        path.chmod(0o600)
        with self.assertRaises(Invalid): ledger.prepare()
        path.write_text("{")
        with self.assertRaises(Invalid): ledger.prepare()
        path.unlink()
        target = self.root / "target"
        target.write_text("private")
        path.symlink_to(target)
        with self.assertRaises(Invalid): ledger.prepare()
        path.unlink()
        self.assertIsNotNone(ledger.prepare())
        path.chmod(0o644)
        with self.assertRaises(Invalid): ledger.read()

    def test_orphaned_partial_temp_file_cannot_change_committed_id(self):
        first = Ledger(self.root).prepare()
        (self.root / ".native-full-archive-intent-orphan.tmp").write_text("partial")
        self.assertEqual(Ledger(self.root).prepare(), first)


if __name__ == "__main__":
    unittest.main()
