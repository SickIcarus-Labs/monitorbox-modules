"""Offline exact source-SHA ancestry, CI run and non-skipped job assurance."""
import copy
import json

import pytest

from successor_github_source_evidence import (
    CORE_REPO, MODULES_REPO, REQUIRED, ReleaseRefusal, qualify_source_commits,
)
from verify_platform_index import canonical
from test_successor_release_manifest import candidate

SOURCES = {"core": "1"*40, "modules": "2"*40, "python": "3"*40}


class FakeGitHub:
    def __init__(self):
        self.comp = {}
        self.runs = {}
        self.jobs = {}
        self.calls = []

    def compare_main(self, repo, sha):
        self.calls.append(("compare", repo, sha))
        return self.comp[(repo, sha)]

    def workflow_runs(self, repo, sha, page):
        self.calls.append(("runs", repo, sha, page))
        return {"workflow_runs": self.runs.get((repo, sha, page), [])}

    def run_jobs(self, repo, run, page):
        self.calls.append(("jobs", repo, run, page))
        return {"jobs": self.jobs.get((repo, run, page), [])}


def fixture_api():
    api = FakeGitHub()
    index = 1000
    for role, (repo, gates) in REQUIRED.items():
        sha = SOURCES[role]
        api.comp[(repo, sha)] = {
            "status": "ahead", "behind_by": 0,
            "base_commit": {"sha": sha},
            "merge_base_commit": {"sha": sha},
        }
        batch = []
        for workflow, job in gates:
            index += 1
            run = {
                "id": index, "path": workflow, "head_sha": sha,
                "head_repository": {"full_name": repo},
                "status": "completed", "conclusion": "success",
                "event": "pull_request", "run_attempt": 1,
                "created_at": "2026-10-08T17:00:00Z",
            }
            batch.append(run)
            api.jobs[(repo, index, 1)] = [{
                "id": index + 4000, "run_id": index,
                "name": job, "status": "completed", "conclusion": "success",
            }]
        api.runs[(repo, sha, 1)] = batch
    return api


def evaluate(api):
    # The caller supplies the manifest, but may not choose policy workflows.
    return qualify_source_commits(canonical({
        "schema": 1, "artifact_class": "successor-qualified-release-candidate",
        "sources": SOURCES,
    }), api)


def test_three_exact_source_shas_need_ancestry_and_real_successful_ci_jobs():
    api = fixture_api()
    proof = evaluate(api)
    assert {p.role for p in proof} == set(REQUIRED)
    assert all(p.checks for p in proof)
    assert all(action in ("compare", "runs", "jobs") for action, *_ in api.calls)
    assert len([c for c in api.calls if c[0] == "jobs"]) == 5


def test_unmerged_diverged_or_wrong_base_source_refused():
    for status, behind in (("diverged", 1), ("behind", 2), ("ahead", 1)):
        api = fixture_api()
        api.comp[(CORE_REPO, SOURCES["core"])]["status"] = status
        api.comp[(CORE_REPO, SOURCES["core"])]["behind_by"] = behind
        with pytest.raises(ReleaseRefusal, match="main ancestor"):
            evaluate(api)


def test_wrong_workflow_source_sha_or_repository_never_qualifies():
    for field, change in [
        ("head_sha", "f" * 40),
        ("head_repository", {"full_name": "Other/Repo"}),
        ("path", ".github/workflows/unrelated.yml"),
    ]:
        api = fixture_api()
        record = api.runs[(CORE_REPO, SOURCES["core"], 1)][0]
        record[field] = change
        with pytest.raises(ReleaseRefusal, match="workflow missing"):
            evaluate(api)


def test_workflow_wrapper_success_cannot_mask_skipped_test_job():
    api = fixture_api()
    run = api.runs[(CORE_REPO, SOURCES["core"], 1)][0]
    api.jobs[(CORE_REPO, run["id"], 1)][0]["conclusion"] = "skipped"
    with pytest.raises(ReleaseRefusal, match="skipped/missing/failed"):
        evaluate(api)


def test_prior_green_run_does_not_mask_newer_failed_attempt():
    api = fixture_api()
    first = api.runs[(MODULES_REPO, SOURCES["modules"], 1)][0]
    latest = dict(first)
    latest.update({
        "id": first["id"] + 100,
        "created_at": "2026-10-08T18:00:00Z",
        "conclusion": "failure",
    })
    api.runs[(MODULES_REPO, SOURCES["modules"], 1)].append(latest)
    with pytest.raises(ReleaseRefusal, match="latest exact-source CI workflow"):
        evaluate(api)


def test_in_progress_latest_run_refused():
    api = fixture_api()
    api.runs[(CORE_REPO, SOURCES["core"], 1)][0]["status"] = "in_progress"
    with pytest.raises(ReleaseRefusal, match="not successful"):
        evaluate(api)


def test_anonymous_or_renamed_test_job_refused():
    api = fixture_api()
    job = next(iter(api.jobs.values()))[0]
    job["name"] = "Setup only"
    with pytest.raises(ReleaseRefusal, match="skipped/missing/failed"):
        evaluate(api)


def test_duplicate_source_roles_or_non_sha_refused():
    api = fixture_api()
    with pytest.raises(ReleaseRefusal, match="exact source revision"):
        qualify_source_commits(canonical({
            "schema": 1, "artifact_class": "successor-qualified-release-candidate",
            "sources": {"core": SOURCES["core"], "modules": SOURCES["modules"]},
        }), api)
    with pytest.raises(ReleaseRefusal, match="lowercase Git SHA"):
        qualify_source_commits(canonical({
            "schema": 1, "artifact_class": "successor-qualified-release-candidate",
            "sources": {**SOURCES, "core": "refs/heads/main"},
        }), api)


def test_manifest_can_never_choose_weaker_ci_workflow():
    api = fixture_api()
    fake_manifest = {
        "schema": 1, "artifact_class": "successor-qualified-release-candidate",
        "sources": SOURCES,
        "ci": {"workflow": "always-passing", "approved": True},
    }
    proof = qualify_source_commits(canonical(fake_manifest), api)
    assert len(proof) == 3
    assert not any("always-passing" in str(x) for x in proof)
