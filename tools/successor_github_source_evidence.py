"""Read-only GitHub source ancestry and exact-head CI evidence validation.

This is a *necessary* source qualification gate, NOT release authorization.
The static repository/workflow/job policy cannot be changed by a candidate.
A successful workflow wrapper is insufficient: a named test job must have
actually run and completed successfully, rather than being skipped.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Protocol

from successor_release_pairing import ReleaseRefusal
from verify_platform_index import VerificationError, _parse

SHA = re.compile(r"[a-f0-9]{40}\Z")
CORE_REPO = "SickIcarus-Labs/monitorbox"
MODULES_REPO = "SickIcarus-Labs/monitorbox-modules"

# Tests intentionally require the full companion suite; a green
# publication-contract smoke alone cannot qualify a changed modules source.
REQUIRED = {
    "core": (CORE_REPO, ((".github/workflows/ci.yml", "Validate MonitorBox"),)),
    "python": (CORE_REPO, ((".github/workflows/ci.yml", "Validate MonitorBox"),)),
    "modules": (MODULES_REPO, (
        (".github/workflows/successor-integrated-source-contract.yml",
         "Test signer and source policy together (no publication)"),
        (".github/workflows/platform-contract.yml",
         "Validate signed successor index and package contract"),
        (".github/workflows/successor-signed-feed-publication-contract.yml", "contract"),
    )),
}


class GitHubEvidenceAPI(Protocol):
    def compare_main(self, repository: str, source_sha: str) -> Mapping: ...
    def workflow_runs(self, repository: str, source_sha: str, page: int) -> Mapping: ...
    def run_jobs(self, repository: str, run_id: int, page: int) -> Mapping: ...


@dataclass(frozen=True)
class SourceCIProof:
    role: str
    repository: str
    source_sha: str
    checks: tuple[tuple[str, int, str], ...]


def _sha(value: object) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ReleaseRefusal("candidate source must be an exact lowercase Git SHA")
    return value


def _ancestry(api: GitHubEvidenceAPI, repo: str, sha: str) -> None:
    comparison = api.compare_main(repo, sha)
    if not isinstance(comparison, Mapping):
        raise ReleaseRefusal("missing trusted GitHub ancestry evidence")
    # GitHub compare base=source, head=main: ahead/identical with zero
    # behind commits means source is an ancestor of accepted main.
    if (comparison.get("status") not in ("ahead", "identical") or
            comparison.get("behind_by") != 0 or
            not isinstance(comparison.get("base_commit"), Mapping) or
            comparison["base_commit"].get("sha") != sha or
            not isinstance(comparison.get("merge_base_commit"), Mapping) or
            comparison["merge_base_commit"].get("sha") != sha):
        raise ReleaseRefusal("candidate source is not an accepted main ancestor")


def _runs(api: GitHubEvidenceAPI, repo: str, sha: str) -> list[Mapping]:
    gathered = []
    for page in range(1, 6):
        response = api.workflow_runs(repo, sha, page)
        if not isinstance(response, Mapping) or not isinstance(response.get("workflow_runs"), list):
            raise ReleaseRefusal("untrusted GitHub CI workflow response")
        batch = response["workflow_runs"]
        if len(batch) > 100:
            raise ReleaseRefusal("unbounded GitHub CI response")
        gathered.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ReleaseRefusal("GitHub CI history exceeds bounded query window")
    return gathered


def _jobs(api: GitHubEvidenceAPI, repo: str, run_id: int) -> list[Mapping]:
    all_jobs = []
    for page in range(1, 6):
        response = api.run_jobs(repo, run_id, page)
        if not isinstance(response, Mapping) or not isinstance(response.get("jobs"), list):
            raise ReleaseRefusal("untrusted GitHub CI jobs response")
        batch = response["jobs"]
        if len(batch) > 100:
            raise ReleaseRefusal("unbounded GitHub CI jobs response")
        all_jobs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ReleaseRefusal("GitHub CI jobs exceed bounded query window")
    return all_jobs


def _qualified_checks(api: GitHubEvidenceAPI, repo: str, sha: str,
                      required: tuple, *, known_runs: list[Mapping]) -> tuple:
    runs = known_runs
    proofs = []
    for path, required_job in required:
        matches = [
            run for run in runs
            if isinstance(run, Mapping)
            and run.get("path") == path
            and run.get("head_sha") == sha
            and run.get("head_repository", {}).get("full_name") == repo
            and run.get("event") in ("pull_request", "workflow_dispatch", "push")
            and type(run.get("id")) is int and run["id"] > 0
            and type(run.get("run_attempt")) is int
            and run["run_attempt"] > 0
            and isinstance(run.get("created_at"), str)
        ]
        if not matches:
            raise ReleaseRefusal("required exact-source CI workflow missing: " + path)
        # A past successful run cannot mask a subsequent failed rerun/build.
        latest = max(matches, key=lambda r: (r["created_at"], r["run_attempt"], r["id"]))
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise ReleaseRefusal("latest exact-source CI workflow is not successful: " + path)
        jobs = _jobs(api, repo, latest["id"])
        valid = [
            j for j in jobs if isinstance(j, Mapping)
            and j.get("name") == required_job
            and j.get("status") == "completed"
            and j.get("conclusion") == "success"
            and j.get("run_id") == latest["id"]
            and type(j.get("id")) is int and j["id"] > 0
        ]
        if len(valid) != 1:
            raise ReleaseRefusal("required CI validation job was skipped/missing/failed: " + required_job)
        proofs.append((path, latest["id"], required_job))
    return tuple(proofs)


def qualify_source_commits(candidate_raw: bytes, api: GitHubEvidenceAPI) -> tuple[SourceCIProof, ...]:
    """Check fixed source identities and actual GitHub CI/job evidence.

    Result is NOT a protected actor approval, signing authorization, immutable
    package build attestation, release-publisher permission, or registry write.
    """
    try:
        manifest = _parse(candidate_raw)
    except (VerificationError, TypeError, ValueError) as exc:
        raise ReleaseRefusal("invalid release candidate JSON") from exc
    if not isinstance(manifest, Mapping) or manifest.get("schema") != 1 or (
            manifest.get("artifact_class") != "successor-qualified-release-candidate"):
        raise ReleaseRefusal("unexpected candidate release identity")
    sources = manifest.get("sources")
    if not isinstance(sources, Mapping) or set(sources) != set(REQUIRED):
        raise ReleaseRefusal("candidate lacks exact source revision identities")
    proofs = []
    cached = {}
    for role, (repo, required) in REQUIRED.items():
        sha = _sha(sources[role])
        identity = (repo, sha)
        if identity not in cached:
            _ancestry(api, repo, sha)
            cached[identity] = _runs(api, repo, sha)
        # All roles are checked under the static policy, not manifest-declared
        # workflow names. This keeps source-specific review requirements fixed.
        checks = _qualified_checks(api, repo, sha, required, known_runs=cached[identity])
        proofs.append(SourceCIProof(role, repo, sha, checks))
    return tuple(proofs)
