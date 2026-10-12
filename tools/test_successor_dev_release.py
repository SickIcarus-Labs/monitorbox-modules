import copy

import pytest

from tools.successor_dev_release import (
    AGENT, CORE, MANAGER, DevReleaseRefused, qualify_dev_delta,
)

APPLICATIONS = (
    "backup-restore", "configuration-bootstrap", "http", "nut", "portainer",
    "scrypted", "snmp", "ui", "unifi", "wol",
)


def item(module_id, *, arch="any", version="1.0.0", build=1, digest="a"):
    return {
        "artifact_id": module_id,
        "version": version,
        "build": build,
        "kind": "scaffold-manager" if module_id == MANAGER else "module",
        "platform": {"os": "linux", "arch": arch, "abi": "static" if module_id == MANAGER else "any"},
        "dependencies": [],
        "package": {"sha256": digest * 64, "size": 100},
    }


def fixture():
    artifacts = [
        item("com.sickicarus.monitorbox." + module)
        for module in APPLICATIONS
    ]
    for mod in (CORE, AGENT, MANAGER):
        for arch in ("amd64", "arm64"):
            artifacts.append(item(mod, arch=arch, version="3.0.0" if mod != MANAGER else "1.0.0", build=3 if mod != MANAGER else 4))
    for arch in ("amd64", "arm64"):
        for name in ("runtime.python", "runtime.node", "core.wheels"):
            artifacts.append(item("com.sickicarus.monitorbox." + name, arch=arch))
    assert len(artifacts) == 22
    previous = {
        "repository_id": "official-platform", "channel": "dev",
        "sequence": 10, "artifacts": artifacts,
    }
    candidate = copy.deepcopy(previous)
    candidate["sequence"] = 11
    for artifact in candidate["artifacts"]:
        if artifact["artifact_id"] in {CORE, MANAGER}:
            artifact["build"] += 1
            artifact["package"]["sha256"] = "b" * 64
    managers = {
        arch: {
            "repository_id": "official-platform", "channel": "stable",
            "sequence": 11,
            "artifacts": [
                copy.deepcopy(next(
                    x for x in candidate["artifacts"]
                    if x["artifact_id"] == MANAGER and x["platform"]["arch"] == arch
                ))
            ],
        }
        for arch in ("amd64", "arm64")
    }
    return previous, candidate, managers


def test_changed_core_and_manager_keep_22_artifact_dev_closure():
    before, after, managers = fixture()
    result = qualify_dev_delta(before, after)
    assert result == {
        "previous_sequence": 10, "candidate_sequence": 11, "channel": "dev",
        "changed_module_ids": sorted([CORE, MANAGER]),
        "artifact_count": 22, "manager_architectures": ["amd64", "arm64"],
    }


@pytest.mark.parametrize("mutator", [
    lambda p, c, s: c["artifacts"].pop(),
    lambda p, c, s: c["artifacts"][0]["package"].update(sha256="f" * 64),
    lambda p, c, s: c.update(sequence=p["sequence"]),
    lambda p, c, s: c.update(channel="stable"),
    lambda p, c, s: c["artifacts"][10].update(build=1),
])
def test_bad_or_mixed_dev_delta_fails_closed(mutator):
    before, after, sup = fixture()
    mutator(before, after, sup)
    with pytest.raises(DevReleaseRefused):
        qualify_dev_delta(before, after)


def test_declared_core_update_cannot_silently_replace_manager():
    before, after, sup = fixture()
    with pytest.raises(DevReleaseRefused):
        qualify_dev_delta(before, after, changed_ids=frozenset({CORE}))


def test_full_dev_manager_architecture_must_match_baseline():
    before, after, _ = fixture()
    row = next(item for item in after["artifacts"] if
               item["artifact_id"] == MANAGER and item["platform"]["arch"] == "arm64")
    row["platform"]["arch"] = "riscv64"
    with pytest.raises(DevReleaseRefused):
        qualify_dev_delta(before, after)


def test_br_only_signed_dev_delta_advances_one_arch_any_app():
    from tools.successor_dev_release import BACKUP_RESTORE
    before, _, _ = fixture()
    after = copy.deepcopy(before)
    after["sequence"] += 1
    br = next(x for x in after["artifacts"] if x["artifact_id"] == BACKUP_RESTORE)
    br.update(version="1.0.6", build=8)
    br["package"]["sha256"] = "b" * 64
    admitted = qualify_dev_delta(before, after, changed_ids=frozenset({BACKUP_RESTORE}))
    assert admitted["changed_module_ids"] == [BACKUP_RESTORE]
    assert admitted["artifact_count"] == 22
    assert len([x for x in after["artifacts"] if x["artifact_id"] == BACKUP_RESTORE]) == 1
    for invalid in ("wrong-arch", "same-build", "unrelated-change"):
        changed = copy.deepcopy(after)
        row = next(x for x in changed["artifacts"] if x["artifact_id"] == BACKUP_RESTORE)
        if invalid == "wrong-arch":
            row["platform"]["arch"] = "amd64"
        elif invalid == "same-build":
            row.update(version="1.0.0", build=1)
        else:
            next(x for x in changed["artifacts"] if x["artifact_id"] == CORE)["package"]["sha256"] = "c" * 64
        with pytest.raises(DevReleaseRefused):
            qualify_dev_delta(before, changed, changed_ids=frozenset({BACKUP_RESTORE}))

def test_ui_only_signed_dev_delta_preserves_21_unchanged_roles():
    from tools.successor_dev_release import UI
    before, _, _ = fixture()
    after = copy.deepcopy(before)
    after["sequence"] += 1
    ui = next(item for item in after["artifacts"] if item["artifact_id"] == UI)
    ui.update(version="1.18.1", build=59)
    ui["package"]["sha256"] = "b" * 64
    assert qualify_dev_delta(before, after, changed_ids=frozenset({UI}))["changed_module_ids"] == [UI]
    for fault in ("wrong-arch", "unrelated-change", "same-build"):
        changed = copy.deepcopy(after)
        row = next(item for item in changed["artifacts"] if item["artifact_id"] == UI)
        if fault == "wrong-arch":
            row["platform"]["arch"] = "amd64"
        elif fault == "same-build":
            row.update(version="1.0.0", build=1)
        else:
            next(item for item in changed["artifacts"] if item["artifact_id"] == CORE)["package"]["sha256"] = "f" * 64
        with pytest.raises(DevReleaseRefused):
            qualify_dev_delta(before, changed, changed_ids=frozenset({UI}))
