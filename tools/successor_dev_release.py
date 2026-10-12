"""Read-only qualification of a signed v3 development-module release delta.

This is NOT a signer, publisher, or registry writer. Inputs must first pass the
trusted Ed25519 catalog verifier and signed ZIP/package admission. Keep the
full 22-artifact closure intact while admitting a deliberately small changed
Core/Agent/Supervisor subset for the existing Dev -> Update All workflow.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

CORE = "com.sickicarus.monitorbox.core"
AGENT = "com.sickicarus.monitorbox.agent"
MANAGER = "com.sickicarus.monitorbox.scaffold-manager"
NATIVE = frozenset({CORE, AGENT, MANAGER})
ARCHES = frozenset({"amd64", "arm64"})
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class DevReleaseRefused(ValueError):
    pass


def _records(index: Mapping, *, channel: str, full: bool) -> dict:
    if not isinstance(index, Mapping):
        raise DevReleaseRefused("expected a previously verified signed catalog")
    if index.get("repository_id") != "official-platform" or index.get("channel") != channel:
        raise DevReleaseRefused("catalog has wrong repository/channel")
    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != (22 if full else 1):
        raise DevReleaseRefused("catalog has incomplete package closure")
    result = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise DevReleaseRefused("invalid artifact")
        try:
            platform = artifact["platform"]
            identity = (artifact["artifact_id"], platform["os"], platform["arch"], platform["abi"])
            sha = artifact["package"]["sha256"]
            version = artifact["version"]
            build = artifact["build"]
        except (KeyError, TypeError):
            raise DevReleaseRefused("incomplete signed artifact") from None
        if (
            not isinstance(identity[0], str)
            or any(not isinstance(v, str) or not v for v in identity[1:])
            or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)
            or not isinstance(version, str) or not SEMVER.fullmatch(version)
            or type(build) is not int or build < 1
            or identity in result
        ):
            raise DevReleaseRefused("ambiguous signed artifact identity")
        result[identity] = artifact
    return result


def _release_key(artifact: dict) -> tuple[int, int, int, int]:
    m = SEMVER.fullmatch(artifact["version"])
    assert m is not None
    return (int(m[1]), int(m[2]), int(m[3]), artifact["build"])


def qualify_dev_delta(
    previous: Mapping,
    proposed: Mapping,
    supervisor_by_arch: Mapping[str, Mapping],
    *,
    changed_ids: frozenset[str] = frozenset({CORE, MANAGER}),
) -> dict:
    """Validate *already authenticated* signed Dev catalogs before publication.

    No stable/beta pointer writes, no module side-loads, no signing private key.
    The caller must independently verify signatures, ZIP bytes, source commits,
    exact current Dev digest, release-channel anti-rollback and OCI readback.
    """
    if not changed_ids or not changed_ids <= NATIVE:
        raise DevReleaseRefused("unsupported Dev platform delta")
    before = _records(previous, channel="dev", full=True)
    after = _records(proposed, channel="dev", full=True)
    if set(before) != set(after):
        raise DevReleaseRefused("Dev release removed or introduced package identities")
    old_sequence = previous.get("sequence")
    new_sequence = proposed.get("sequence")
    if (
        type(old_sequence) is not int or old_sequence < 1
        or type(new_sequence) is not int or new_sequence <= old_sequence
    ):
        raise DevReleaseRefused("Dev catalog release sequence is not monotonic")
    if {key[0] for key in before if key[0] in NATIVE} != NATIVE:
        raise DevReleaseRefused("Core/Agent/Manager role is incomplete")

    actually_changed = set()
    for identity, old in before.items():
        new = after[identity]
        module_id = identity[0]
        if module_id not in changed_ids:
            if new != old:
                raise DevReleaseRefused("unchanged signed module/runtime bytes were modified")
            continue
        if new == old:
            continue
        if _release_key(new) <= _release_key(old):
            raise DevReleaseRefused("Dev module release version/build must increase")
        # Changed packages cannot change their platform, API contract or
        # dependency constraints under an unreviewed version-only update.
        for stable_field in (
            "artifact_id", "kind", "platform", "dependencies",
            "requires_scaffold_api", "requires_core", "requires_runtime_api",
        ):
            if old.get(stable_field) != new.get(stable_field):
                raise DevReleaseRefused("changed module has incompatible contract delta")
        if old["package"]["sha256"] == new["package"]["sha256"]:
            raise DevReleaseRefused("new build has unchanged package bytes")
        actually_changed.add(module_id)

    if actually_changed != set(changed_ids):
        raise DevReleaseRefused("declared Dev modules did not all receive new artifacts")
    for module_id in changed_ids:
        architectures = {key[2] for key in after if key[0] == module_id}
        if module_id in NATIVE and architectures != ARCHES:
            raise DevReleaseRefused("signed platform module lacks an architecture")

    if set(supervisor_by_arch) != ARCHES:
        raise DevReleaseRefused("missing paired signed Supervisor architectures")
    for arch in sorted(ARCHES):
        sup = supervisor_by_arch[arch]
        managers = _records(sup, channel="dev", full=False)
        only = next(iter(managers.values()))
        if only["artifact_id"] != MANAGER or only["platform"]["arch"] != arch:
            raise DevReleaseRefused("Supervisor catalog has wrong manager architecture")
        target = [v for k, v in after.items() if k[0] == MANAGER and k[2] == arch]
        if len(target) != 1 or target[0] != only or sup.get("sequence") != new_sequence:
            raise DevReleaseRefused("signed Dev Supervisor/full manager pair differs")

    return {
        "previous_sequence": old_sequence,
        "candidate_sequence": new_sequence,
        "channel": "dev",
        "changed_module_ids": sorted(actually_changed),
        "artifact_count": len(after),
        "paired_manager_architectures": sorted(ARCHES),
    }
