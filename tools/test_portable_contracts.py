"""Production first-party portable contract authority tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from portable_contracts import (
    AUTHORITY,
    ContractError,
    FIRST_PARTY_MODULE_IDS,
    load_first_party_contracts,
    materialize_contract,
    parse_json,
    verify_embedded_contract,
)


EXPECTED_SCHEMAS = {
    "com.sickicarus.monitorbox.core": "com.sickicarus.monitorbox.core.settings/v1",
    "com.sickicarus.monitorbox.agent": "com.sickicarus.monitorbox.agent.settings/v1",
    "com.sickicarus.monitorbox.backup-restore": "com.sickicarus.monitorbox.backup-restore.settings/v1",
    "com.sickicarus.monitorbox.configuration-bootstrap": "com.sickicarus.monitorbox.configuration-bootstrap.settings/v1",
    "com.sickicarus.monitorbox.http": "com.sickicarus.monitorbox.http.settings/v1",
    "com.sickicarus.monitorbox.nut": "com.sickicarus.monitorbox.nut.settings/v1",
    "com.sickicarus.monitorbox.portainer": "com.sickicarus.monitorbox.portainer.settings/v1",
    "com.sickicarus.monitorbox.scrypted": "com.sickicarus.monitorbox.scrypted.settings/v1",
    "com.sickicarus.monitorbox.snmp": "com.sickicarus.monitorbox.snmp.settings/v1",
    "com.sickicarus.monitorbox.ui": "com.sickicarus.monitorbox.ui.settings/v1",
    "com.sickicarus.monitorbox.unifi": "com.sickicarus.monitorbox.unifi.settings/v1",
    "com.sickicarus.monitorbox.wol": "com.sickicarus.monitorbox.wol.settings/v1",
}

CREDENTIAL_POINTERS = {
    "com.sickicarus.monitorbox.agent": ("/runtime/credential_secret_refs/*", "one"),
    "com.sickicarus.monitorbox.portainer": ("/credentialRefs", "many"),
    "com.sickicarus.monitorbox.scrypted": ("/credentialRefs", "many"),
    "com.sickicarus.monitorbox.snmp": ("/credentialRefs", "many"),
    "com.sickicarus.monitorbox.unifi": ("/credentialRefs", "many"),
}


class FirstPartyPortableContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = load_first_party_contracts()

    def _write_authority(self, document: dict) -> Path:
        temp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        json.dump(document, temp)
        temp.close()
        return Path(temp.name)

    def test_exact_required_first_party_set_and_schema_provenance(self) -> None:
        self.assertEqual(FIRST_PARTY_MODULE_IDS, frozenset(self.contracts))
        self.assertEqual(EXPECTED_SCHEMAS, {
            artifact_id: contract["current_settings_schema"]
            for artifact_id, contract in self.contracts.items()
        })
        for artifact_id, contract in self.contracts.items():
            self.assertEqual(
                [EXPECTED_SCHEMAS[artifact_id]],
                contract["accepts_settings_schemas"],
            )
            self.assertNotIn("settings_migrations", contract)

    def test_fixture_grounded_credential_reference_contracts(self) -> None:
        with_refs = {
            artifact_id
            for artifact_id, contract in self.contracts.items()
            if contract.get("credential_references")
        }
        self.assertEqual(set(CREDENTIAL_POINTERS), with_refs)
        for artifact_id, expected in CREDENTIAL_POINTERS.items():
            references = self.contracts[artifact_id]["credential_references"]
            self.assertEqual(1, len(references))
            reference = references[0]
            self.assertEqual(expected, (reference["pointer"], reference["cardinality"]))
            self.assertFalse(reference.get("required", False))
            self.assertEqual(
                [{"name": "value", "type": "string", "required": True, "non_empty": True}],
                reference["credential_fields"],
            )

    def test_every_contract_materializes_and_verifies_exact_identity(self) -> None:
        for artifact_id in sorted(FIRST_PARTY_MODULE_IDS):
            raw = materialize_contract(artifact_id, "3.0.0", 17)
            parsed = parse_json(raw)
            self.assertEqual(artifact_id, parsed["artifact_id"])
            self.assertEqual("3.0.0", parsed["version"])
            self.assertEqual(17, parsed["build"])
            capability = verify_embedded_contract(
                raw, artifact_id=artifact_id, version="3.0.0", build=17
            )
            self.assertEqual(1, capability["protocol"])
            self.assertEqual(EXPECTED_SCHEMAS[artifact_id], capability["current_settings_schema"])
            self.assertEqual([], capability["accepted_source_schemas"])

    def test_duplicate_authority_module_is_rejected(self) -> None:
        document = json.loads(AUTHORITY.read_text("utf-8"))
        document["modules"].append(dict(document["modules"][0]))
        with self.assertRaisesRegex(ContractError, "duplicate"):
            load_first_party_contracts(self._write_authority(document))

    def test_unsafe_credential_pointer_is_rejected(self) -> None:
        document = json.loads(AUTHORITY.read_text("utf-8"))
        agent = next(
            module for module in document["modules"]
            if module["artifact_id"] == "com.sickicarus.monitorbox.agent"
        )
        agent["credential_references"][0]["pointer"] = "/runtime/../secret"
        with self.assertRaisesRegex(ContractError, "pointer"):
            load_first_party_contracts(self._write_authority(document))

    def test_accepted_historical_schema_requires_complete_migration(self) -> None:
        document = json.loads(AUTHORITY.read_text("utf-8"))
        core = next(
            module for module in document["modules"]
            if module["artifact_id"] == "com.sickicarus.monitorbox.core"
        )
        core["accepts_settings_schemas"].append("com.sickicarus.monitorbox.core.settings/v0")
        with self.assertRaisesRegex(ContractError, "lacks migration"):
            load_first_party_contracts(self._write_authority(document))

    def test_nonempty_is_string_only(self) -> None:
        document = json.loads(AUTHORITY.read_text("utf-8"))
        agent = next(
            module for module in document["modules"]
            if module["artifact_id"] == "com.sickicarus.monitorbox.agent"
        )
        agent["credential_references"][0]["credential_fields"][0]["type"] = "integer"
        with self.assertRaisesRegex(ContractError, "non_empty"):
            load_first_party_contracts(self._write_authority(document))

    def test_embedded_contract_must_match_outer_identity_and_authority(self) -> None:
        raw = materialize_contract("com.sickicarus.monitorbox.core", "3.0.0", 1)
        document = parse_json(raw)
        document["artifact_id"] = "com.sickicarus.monitorbox.agent"
        altered = json.dumps(document).encode()
        with self.assertRaisesRegex(ContractError, "package identity"):
            verify_embedded_contract(
                altered,
                artifact_id="com.sickicarus.monitorbox.core",
                version="3.0.0",
                build=1,
            )

        document = parse_json(raw)
        document["accepts_settings_schemas"].append(
            "com.sickicarus.monitorbox.core.settings/v0"
        )
        document["settings_migrations"] = [{
            "from_schema": "com.sickicarus.monitorbox.core.settings/v0",
            "to_schema": "com.sickicarus.monitorbox.core.settings/v1",
            "operations": [],
        }]
        altered = json.dumps(document).encode()
        with self.assertRaisesRegex(ContractError, "first-party authority"):
            verify_embedded_contract(
                altered,
                artifact_id="com.sickicarus.monitorbox.core",
                version="3.0.0",
                build=1,
            )


if __name__ == "__main__":
    unittest.main()
