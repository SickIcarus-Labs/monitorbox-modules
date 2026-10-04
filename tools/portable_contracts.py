#!/usr/bin/env python3
"""Production authority for successor first-party portable-config contracts.

The fixed scaffold/Core validates contracts at import time. This tool owns the
first-party source manifest used to materialize the exact portable-config.json
member embedded in selectable successor module packages and to independently
verify that member before candidate signing.

It contains no Broad Leaf credential values or private migration fixture data.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "platform" / "portable" / "first-party-contracts-v1.json"

PORTABLE_SCHEMA = "monitorbox.portable/v1"
MIGRATION_PROTOCOL = 1
MAX_CONTRACT_BYTES = 64 << 10
MAX_ACCEPTED_SCHEMAS = 32
MAX_MIGRATIONS = 32
MAX_MIGRATION_OPERATIONS = 64
MAX_CREDENTIAL_REFERENCES = 64
MAX_CREDENTIAL_FIELDS = 64

FIRST_PARTY_MODULE_IDS = frozenset(
    {
        "com.sickicarus.monitorbox.core",
        "com.sickicarus.monitorbox.agent",
        "com.sickicarus.monitorbox.backup-restore",
        "com.sickicarus.monitorbox.configuration-bootstrap",
        "com.sickicarus.monitorbox.http",
        "com.sickicarus.monitorbox.nut",
        "com.sickicarus.monitorbox.portainer",
        "com.sickicarus.monitorbox.scrypted",
        "com.sickicarus.monitorbox.snmp",
        "com.sickicarus.monitorbox.ui",
        "com.sickicarus.monitorbox.unifi",
        "com.sickicarus.monitorbox.wol",
    }
)

_ARTIFACT_ID = re.compile(r"^[a-z0-9][a-z0-9.-]+$")
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SCHEMA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_CREDENTIAL_POINTER = re.compile(
    r"^/(?:[A-Za-z0-9_.-]+|\*)(?:/(?:[A-Za-z0-9_.-]+|\*))*$"
)
_SETTINGS_POINTER = re.compile(r"^/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")
_FIELD_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CREDENTIAL_TYPES = frozenset({"string", "boolean", "integer", "number", "object", "array"})


class ContractError(ValueError):
    """Portable contract authority or embedded package contract is invalid."""


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def parse_json(raw: bytes) -> Any:
    if len(raw) > MAX_CONTRACT_BYTES:
        raise ContractError("portable contract JSON exceeds size limit")
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ContractError(f"non-JSON value: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid UTF-8 portable contract JSON: {exc}") from exc


def _expect_keys(
    value: Any,
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        raise ContractError(f"{label} missing required field")
    if unknown:
        raise ContractError(f"{label} contains unknown field")
    return value


def _schema_id(value: Any) -> str:
    if not isinstance(value, str) or not _SCHEMA_ID.fullmatch(value):
        raise ContractError("invalid portable settings schema identity")
    return value


def _safe_pointer(value: Any, *, wildcard: bool) -> str:
    pattern = _CREDENTIAL_POINTER if wildcard else _SETTINGS_POINTER
    if not isinstance(value, str) or len(value) > 256 or not pattern.fullmatch(value):
        raise ContractError("invalid portable settings pointer")
    for segment in value.removeprefix("/").split("/"):
        if segment in {".", ".."}:
            raise ContractError("portable settings pointer contains unsafe segment")
    return value


def _validate_credential_fields(fields: Any) -> list[dict[str, Any]]:
    if fields is None:
        return []
    if not isinstance(fields, list) or len(fields) > MAX_CREDENTIAL_FIELDS:
        raise ContractError("invalid credential-field declaration set")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in fields:
        field = _expect_keys(
            raw,
            required={"name", "type"},
            optional={"required", "non_empty"},
            label="credential field",
        )
        name = field["name"]
        kind = field["type"]
        if not isinstance(name, str) or not _FIELD_NAME.fullmatch(name):
            raise ContractError("invalid credential field name")
        if kind not in _CREDENTIAL_TYPES:
            raise ContractError("invalid credential field type")
        required = field.get("required", False)
        non_empty = field.get("non_empty", False)
        if type(required) is not bool or type(non_empty) is not bool:
            raise ContractError("credential field flags must be boolean")
        if non_empty and kind != "string":
            raise ContractError("credential non_empty is valid only for strings")
        if name in seen:
            raise ContractError("duplicate credential field declaration")
        seen.add(name)
        normalized.append(dict(field))
    return normalized


def _validate_credential_references(references: Any) -> list[dict[str, Any]]:
    if references is None:
        return []
    if not isinstance(references, list) or len(references) > MAX_CREDENTIAL_REFERENCES:
        raise ContractError("invalid credential-reference declaration set")
    seen: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for raw in references:
        reference = _expect_keys(
            raw,
            required={"pointer", "cardinality"},
            optional={"required", "credential_fields"},
            label="credential reference",
        )
        pointer = _safe_pointer(reference["pointer"], wildcard=True)
        cardinality = reference["cardinality"]
        if cardinality not in {"one", "many"}:
            raise ContractError("invalid credential reference cardinality")
        required = reference.get("required", False)
        if type(required) is not bool:
            raise ContractError("credential reference required flag must be boolean")
        _validate_credential_fields(reference.get("credential_fields"))
        key = (pointer, cardinality)
        if key in seen:
            raise ContractError("duplicate credential reference declaration")
        seen.add(key)
        normalized.append(dict(reference))
    return normalized


def _validate_migration_operations(operations: Any) -> list[dict[str, Any]]:
    if not isinstance(operations, list) or len(operations) > MAX_MIGRATION_OPERATIONS:
        raise ContractError("invalid portable migration operation set")
    normalized: list[dict[str, Any]] = []
    for raw in operations:
        operation = _expect_keys(
            raw,
            required={"op", "path"},
            optional={"from", "value"},
            label="migration operation",
        )
        op = operation["op"]
        path = _safe_pointer(operation["path"], wildcard=False)
        has_from = "from" in operation
        has_value = "value" in operation
        if op == "move":
            if not has_from or has_value:
                raise ContractError("move requires from and forbids value")
            source = _safe_pointer(operation["from"], wildcard=False)
            if source == path:
                raise ContractError("move source equals destination")
        elif op == "remove_if_present":
            if has_from or has_value:
                raise ContractError("remove_if_present forbids from/value")
        elif op == "set_default":
            if has_from or not has_value:
                raise ContractError("set_default requires value and forbids from")
        else:
            raise ContractError("unsupported portable settings migration operation")
        normalized.append(dict(operation))
    return normalized


def _validate_migrations(
    current: str,
    accepted: list[str],
    migrations: Any,
) -> list[dict[str, Any]]:
    if migrations is None:
        migrations = []
    if not isinstance(migrations, list) or len(migrations) > MAX_MIGRATIONS:
        raise ContractError("invalid portable settings migration set")
    accepted_set = set(accepted)
    by_source: dict[str, str] = {}
    normalized: list[dict[str, Any]] = []
    for raw in migrations:
        migration = _expect_keys(
            raw,
            required={"from_schema", "to_schema", "operations"},
            label="settings migration",
        )
        source = _schema_id(migration["from_schema"])
        target = _schema_id(migration["to_schema"])
        if source == target or source == current:
            raise ContractError("portable migration has invalid source/target schema")
        if source not in accepted_set or target not in accepted_set:
            raise ContractError("portable migration schema is not accepted")
        if source in by_source:
            raise ContractError("duplicate portable migration source")
        _validate_migration_operations(migration["operations"])
        by_source[source] = target
        normalized.append(dict(migration))

    for source in accepted:
        if source == current:
            continue
        cursor = source
        seen: set[str] = set()
        while cursor != current:
            if cursor in seen:
                raise ContractError("portable settings migration chain contains a cycle")
            seen.add(cursor)
            if cursor not in by_source:
                raise ContractError("accepted settings schema lacks migration to current")
            cursor = by_source[cursor]
            if len(seen) > len(accepted):
                raise ContractError("portable settings migration chain is excessive")
    return normalized


def _validate_template(raw: Any) -> dict[str, Any]:
    module = _expect_keys(
        raw,
        required={"artifact_id", "current_settings_schema", "accepts_settings_schemas"},
        optional={"settings_migrations", "credential_references"},
        label="module portable contract",
    )
    artifact_id = module["artifact_id"]
    if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
        raise ContractError("invalid module artifact identity")
    current = _schema_id(module["current_settings_schema"])
    accepted = module["accepts_settings_schemas"]
    if (
        not isinstance(accepted, list)
        or not 1 <= len(accepted) <= MAX_ACCEPTED_SCHEMAS
        or any(not isinstance(item, str) for item in accepted)
    ):
        raise ContractError("invalid accepted settings-schema set")
    normalized_accepted = [_schema_id(item) for item in accepted]
    if len(set(normalized_accepted)) != len(normalized_accepted):
        raise ContractError("duplicate accepted settings schema")
    if current not in normalized_accepted:
        raise ContractError("module does not accept its current settings schema")
    _validate_migrations(current, normalized_accepted, module.get("settings_migrations"))
    _validate_credential_references(module.get("credential_references"))
    return dict(module)


def load_first_party_contracts(path: Path = AUTHORITY) -> dict[str, dict[str, Any]]:
    document = parse_json(path.read_bytes())
    root = _expect_keys(
        document,
        required={"schema", "portable_schema", "migration_protocol", "modules"},
        label="first-party portable contract authority",
    )
    if root["schema"] != 1:
        raise ContractError("unsupported first-party portable contract authority schema")
    if root["portable_schema"] != PORTABLE_SCHEMA:
        raise ContractError("wrong portable document schema")
    if root["migration_protocol"] != MIGRATION_PROTOCOL:
        raise ContractError("wrong portable migration protocol")
    modules = root["modules"]
    if not isinstance(modules, list):
        raise ContractError("first-party portable modules must be an array")
    result: dict[str, dict[str, Any]] = {}
    for raw in modules:
        module = _validate_template(raw)
        artifact_id = module["artifact_id"]
        if artifact_id in result:
            raise ContractError("duplicate first-party portable module identity")
        result[artifact_id] = module
    if set(result) != FIRST_PARTY_MODULE_IDS:
        raise ContractError("first-party portable contract authority is not the exact required module set")
    return result


def _embedded_document(
    artifact_id: str,
    version: str,
    build: int,
    template: dict[str, Any],
) -> dict[str, Any]:
    if not _ARTIFACT_ID.fullmatch(artifact_id):
        raise ContractError("invalid package artifact identity")
    if not _SEMVER.fullmatch(version):
        raise ContractError("invalid package semantic version")
    if type(build) is not int or build < 1:
        raise ContractError("invalid package build")
    result: dict[str, Any] = {
        "schema": 1,
        "artifact_id": artifact_id,
        "version": version,
        "build": build,
        "portable_schema": PORTABLE_SCHEMA,
        "current_settings_schema": template["current_settings_schema"],
        "accepts_settings_schemas": list(template["accepts_settings_schemas"]),
        "migration_protocol": MIGRATION_PROTOCOL,
    }
    if template.get("settings_migrations"):
        result["settings_migrations"] = template["settings_migrations"]
    if template.get("credential_references"):
        result["credential_references"] = template["credential_references"]
    return result


def materialize_contract(artifact_id: str, version: str, build: int) -> bytes:
    contracts = load_first_party_contracts()
    try:
        template = contracts[artifact_id]
    except KeyError as exc:
        raise ContractError("artifact has no first-party portable contract authority") from exc
    document = _embedded_document(artifact_id, version, build, template)
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _validate_embedded_shape(document: Any) -> dict[str, Any]:
    contract = _expect_keys(
        document,
        required={
            "schema",
            "artifact_id",
            "version",
            "build",
            "portable_schema",
            "current_settings_schema",
            "accepts_settings_schemas",
            "migration_protocol",
        },
        optional={"settings_migrations", "credential_references"},
        label="embedded portable-config contract",
    )
    if contract["schema"] != 1:
        raise ContractError("unsupported embedded portable contract schema")
    if contract["portable_schema"] != PORTABLE_SCHEMA:
        raise ContractError("embedded contract has wrong portable schema")
    if contract["migration_protocol"] != MIGRATION_PROTOCOL:
        raise ContractError("embedded contract has wrong migration protocol")
    artifact_id = contract["artifact_id"]
    version = contract["version"]
    build = contract["build"]
    if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
        raise ContractError("embedded contract has invalid artifact identity")
    if not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise ContractError("embedded contract has invalid semantic version")
    if type(build) is not int or build < 1:
        raise ContractError("embedded contract has invalid build")
    _validate_template(
        {
            key: value
            for key, value in contract.items()
            if key
            in {
                "artifact_id",
                "current_settings_schema",
                "accepts_settings_schemas",
                "settings_migrations",
                "credential_references",
            }
        }
    )
    return contract


def verify_embedded_contract(
    raw: bytes,
    *,
    artifact_id: str,
    version: str,
    build: int,
) -> dict[str, Any]:
    contract = _validate_embedded_shape(parse_json(raw))
    if (
        contract["artifact_id"] != artifact_id
        or contract["version"] != version
        or contract["build"] != build
    ):
        raise ContractError("embedded portable contract disagrees with package identity")

    expected = parse_json(materialize_contract(artifact_id, version, build))
    if contract != expected:
        raise ContractError("embedded portable contract disagrees with first-party authority")

    current = contract["current_settings_schema"]
    accepted_sources = [
        schema for schema in contract["accepts_settings_schemas"] if schema != current
    ]
    return {
        "protocol": MIGRATION_PROTOCOL,
        "current_settings_schema": current,
        "accepted_source_schemas": accepted_sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate/materialize first-party successor portable-config contracts"
    )
    parser.add_argument("--artifact-id")
    parser.add_argument("--version")
    parser.add_argument("--build", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        contracts = load_first_party_contracts()
        if args.artifact_id is None:
            print(f"validated {len(contracts)} first-party portable contracts")
            return 0
        if args.version is None or args.build is None:
            raise ContractError("--artifact-id requires --version and --build")
        raw = materialize_contract(args.artifact_id, args.version, args.build)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(raw)
        else:
            sys.stdout.buffer.write(raw)
    except (ContractError, OSError) as exc:
        print(f"portable contract rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
