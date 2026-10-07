"""Successor first-party application module requalification tests."""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import build_successor_first_party_modules as subject
from portable_contracts import parse_json, verify_embedded_contract


class SuccessorFirstPartyModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = subject._parse_authority()

    def test_exact_ten_module_authority_and_core3_runtime_contract(self) -> None:
        self.assertEqual(subject.FIRST_PARTY_IDS, frozenset(self.records))
        for artifact_id, record in self.records.items():
            runtime = record["module_runtime"]
            self.assertEqual(artifact_id, runtime["module_id"])
            self.assertEqual(record["version"], runtime["version"])
            self.assertEqual(record["build"], runtime["build"])
            self.assertEqual(">=3.0.0 <4.0.0", runtime["requires_core"])
            self.assertEqual(">=1 <2", runtime["requires_runtime_api"])
            self.assertEqual(
                subject._expected_platform_dependencies(artifact_id),
                record["platform"]["dependencies"],
            )

    def test_successor_ui_advances_for_scaffold_lifecycle_operator_contract(self) -> None:
        ui = self.records[subject.UI_ID]
        self.assertEqual(57, ui["build"])
        self.assertEqual(57, ui["module_runtime"]["build"])

    def test_successor_portainer_advances_for_bounded_parallel_inventory(self) -> None:
        portainer = self.records[subject.PORTAINER_ID]
        self.assertEqual(11, portainer["build"])
        self.assertEqual(11, portainer["module_runtime"]["build"])

    def test_scrypted_requires_node24_but_other_modules_do_not(self) -> None:
        scrypted = self.records[subject.SCRYPTED_ID]
        self.assertEqual(9, scrypted["build"])
        self.assertEqual(
            [
                {
                    "artifact_id": subject.CORE_ID,
                    "version_range": ">=3.0.0 <4.0.0",
                },
                {
                    "artifact_id": subject.NODE_RUNTIME_ID,
                    "version_range": ">=24.0.0 <25.0.0",
                },
            ],
            scrypted["platform"]["dependencies"],
        )
        for artifact_id, record in self.records.items():
            if artifact_id == subject.SCRYPTED_ID:
                continue
            self.assertNotIn(
                subject.NODE_RUNTIME_ID,
                {item["artifact_id"] for item in record["platform"]["dependencies"]},
            )

    def test_authority_pins_exact_accepted_predecessor_digests(self) -> None:
        for record in self.records.values():
            path = subject.PREDECESSOR_ROOT / record["predecessor"]["filename"]
            raw = path.read_bytes()
            self.assertEqual(
                record["predecessor"]["sha256"],
                hashlib.sha256(raw).hexdigest(),
                path.name,
            )

    def test_builds_are_deterministic_and_preserve_predecessor_members(self) -> None:
        with tempfile.TemporaryDirectory(prefix="successor-mod-a-") as a_dir, \
             tempfile.TemporaryDirectory(prefix="successor-mod-b-") as b_dir:
            a = Path(a_dir)
            b = Path(b_dir)
            first = subject.build_all(a)
            second = subject.build_all(b)
            self.assertEqual(10, len(first))
            self.assertEqual(
                {path.name for path in first},
                {path.name for path in second},
            )
            for left in first:
                right = b / left.name
                self.assertEqual(left.read_bytes(), right.read_bytes(), left.name)

                artifact_id = next(
                    key for key, record in self.records.items()
                    if left.name == (
                        f"{key}-{record['version']}-build{record['build']}.zip"
                    )
                )
                record = self.records[artifact_id]
                predecessor = (
                    subject.PREDECESSOR_ROOT / record["predecessor"]["filename"]
                )
                with zipfile.ZipFile(predecessor, "r") as old, \
                     zipfile.ZipFile(left, "r") as new:
                    old_names = old.namelist()
                    new_names = new.namelist()
                    self.assertEqual(
                        sorted(old_names + ["package.json", "portable-config.json"]),
                        sorted(new_names),
                    )
                    for name in old_names:
                        if (
                            artifact_id == subject.PORTAINER_ID
                            and name == subject.PORTAINER_RUNTIME_MEMBER
                        ):
                            predecessor_runtime = old.read(name)
                            successor_runtime = new.read(name)
                            self.assertNotEqual(predecessor_runtime, successor_runtime)
                            decoded = successor_runtime.decode("utf-8")
                            self.assertIn("import asyncio", decoded)
                            self.assertIn("aiohttp.ClientTimeout(total=5)", decoded)
                            self.assertIn("await asyncio.gather(", decoded)
                            self.assertIn("return_exceptions=True", decoded)
                            self.assertIn(
                                "for row, container_result in zip(rows, container_results):",
                                decoded,
                            )
                            self.assertNotIn(
                                "timeout = aiohttp.ClientTimeout(total=15)", decoded
                            )
                        elif (
                            artifact_id == subject.SCRYPTED_ID
                            and name == subject.SCRYPTED_RUNTIME_MEMBER
                        ):
                            predecessor_runtime = old.read(name)
                            successor_runtime = new.read(name)
                            self.assertNotEqual(predecessor_runtime, successor_runtime)
                            decoded = successor_runtime.decode("utf-8")
                            self.assertIn("MONITORBOX_MODULE_NODE_LOADER", decoded)
                            self.assertIn("MONITORBOX_MODULE_NODE_LIBRARY_PATH", decoded)
                            self.assertIn("*node_command", decoded)
                            self.assertIn(
                                '_DEFAULT_SOCKET = "/tmp/monitorbox-scrypted/bridge.sock"',
                                decoded,
                            )
                            self.assertIn(
                                "socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)",
                                decoded,
                            )
                            self.assertNotIn(
                                '_DEFAULT_SOCKET = "/run/monitorbox-scrypted/bridge.sock"',
                                decoded,
                            )
                            self.assertIn(
                                'shutil.which(os.environ.get("MONITORBOX_MODULE_NODE", "node"))',
                                decoded,
                            )
                        elif (
                            artifact_id == subject.UI_ID
                            and name.endswith(subject.UI_MODULES_MEMBER_SUFFIX)
                        ):
                            predecessor_ui = old.read(name)
                            successor_ui = new.read(name)
                            self.assertNotEqual(predecessor_ui, successor_ui)
                            decoded = successor_ui.decode("utf-8")
                            self.assertIn("scaffold_lifecycle", decoded)
                            self.assertIn("platform_update_count", decoded)
                            self.assertIn("scaffold_activation_scheduled", decoded)
                            self.assertIn(
                                "Applying compatible signed MonitorBox updates", decoded
                            )
                            self.assertIn(
                                "updateAll.disabled = !authenticated || !csrfToken || !updatePlane",
                                decoded,
                            )
                            self.assertNotIn(
                                "updateAll.disabled = !authenticated || !csrfToken || !packageInstall || updates === 0 || busy;",
                                decoded,
                            )
                            self.assertIn("RELEASE_CHANNEL_API", decoded)
                            self.assertIn("release_channels", decoded)
                            self.assertIn("preferred_channel", decoded)
                            self.assertIn("changeReleaseChannel", decoded)
                            self.assertIn("modules-release-channel", decoded)
                            self.assertIn(
                                "Bounded by deployment ceiling", decoded
                            )
                        elif (
                            artifact_id == subject.UI_ID
                            and name.endswith(subject.UI_MODULES_CSS_MEMBER_SUFFIX)
                        ):
                            predecessor_css = old.read(name)
                            successor_css = new.read(name)
                            self.assertNotEqual(predecessor_css, successor_css)
                            decoded = successor_css.decode("utf-8")
                            self.assertIn(".modules-release-channel {", decoded)
                            self.assertIn(".modules-release-channel select {", decoded)
                        else:
                            self.assertEqual(old.read(name), new.read(name), name)

                    manifest = json.loads(new.read("package.json"))
                    self.assertFalse(manifest["release_eligible"])
                    self.assertEqual(
                        "successor-module-requalification",
                        manifest["packaging_stage"],
                    )
                    self.assertEqual(artifact_id, manifest["artifact_id"])
                    self.assertEqual(record["version"], manifest["version"])
                    self.assertEqual(record["build"], manifest["build"])
                    self.assertEqual(record["module_runtime"], manifest["module_runtime"])
                    self.assertEqual(
                        record["predecessor"]["sha256"],
                        manifest["provenance"]["predecessor_sha256"],
                    )

                    portable = new.read("portable-config.json")
                    capability = verify_embedded_contract(
                        portable,
                        artifact_id=artifact_id,
                        version=record["version"],
                        build=record["build"],
                    )
                    self.assertEqual(1, capability["protocol"])

    def test_release_eligible_override_changes_only_manifest_gate(self) -> None:
        artifact_id = "com.sickicarus.monitorbox.wol"
        record = self.records[artifact_id]
        with tempfile.TemporaryDirectory(prefix="successor-eligible-") as directory:
            target = subject.build_package(
                record, Path(directory), release_eligible=True
            )
            with zipfile.ZipFile(target, "r") as archive:
                manifest = json.loads(archive.read("package.json"))
                self.assertTrue(manifest["release_eligible"])
                self.assertEqual(
                    record["predecessor"]["sha256"],
                    manifest["provenance"]["predecessor_sha256"],
                )
                portable = parse_json(archive.read("portable-config.json"))
                self.assertEqual(record["build"], portable["build"])

    def test_tampered_predecessor_is_rejected_before_output(self) -> None:
        record = self.records["com.sickicarus.monitorbox.wol"]
        with tempfile.TemporaryDirectory(prefix="successor-tamper-") as root, \
             tempfile.TemporaryDirectory(prefix="successor-output-") as out:
            fake_root = Path(root)
            source = subject.PREDECESSOR_ROOT / record["predecessor"]["filename"]
            (fake_root / source.name).write_bytes(source.read_bytes() + b"tamper")
            with patch.object(subject, "PREDECESSOR_ROOT", fake_root):
                with self.assertRaisesRegex(subject.SuccessorModuleError, "digest"):
                    subject.build_package(
                        record, Path(out), release_eligible=False
                    )
            self.assertEqual([], list(Path(out).iterdir()))

    def test_predecessor_with_existing_successor_metadata_is_rejected(self) -> None:
        record = self.records["com.sickicarus.monitorbox.wol"]
        with tempfile.TemporaryDirectory(prefix="successor-meta-") as root:
            fake_root = Path(root)
            source = subject.PREDECESSOR_ROOT / record["predecessor"]["filename"]
            with zipfile.ZipFile(source, "r") as old:
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as new:
                    for item in old.infolist():
                        new.writestr(item.filename, old.read(item))
                    new.writestr("package.json", "{}")
            payload = buffer.getvalue()
            fake = fake_root / source.name
            fake.write_bytes(payload)
            altered = json.loads(json.dumps(record))
            altered["predecessor"]["sha256"] = hashlib.sha256(payload).hexdigest()
            with patch.object(subject, "PREDECESSOR_ROOT", fake_root):
                with self.assertRaisesRegex(subject.SuccessorModuleError, "unsafe predecessor"):
                    subject._predecessor_members(altered)


if __name__ == "__main__":
    unittest.main()
