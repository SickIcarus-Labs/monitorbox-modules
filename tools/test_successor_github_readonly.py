"""No-network tests for private GitHub API exact-source qualification transport."""
import io
import json
from pathlib import Path
import urllib.request

import pytest

from successor_github_readonly import GitHubReadOnly, _NoRedirect
from successor_github_source_evidence import CORE_REPO, MODULES_REPO, ReleaseRefusal


class Response(io.BytesIO):
    def __init__(self, payload):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}


class Opener:
    def __init__(self):
        self.calls = []

    def open(self, req, timeout=40):
        self.calls.append((req.full_url, req.get_method(),
                           req.get_header("Authorization")))
        return Response(json.dumps({
            "status": "ahead", "behind_by": 0,
            "base_commit": {"sha": "a" * 40},
            "merge_base_commit": {"sha": "a" * 40},
            "workflow_runs": [], "jobs": [],
        }).encode())


def test_only_get_requests_to_fixed_github_api_repositories():
    opener = Opener()
    client = GitHubReadOnly(token="read-only-test-value", opener=opener)
    sha = "a" * 40
    assert client.compare_main(CORE_REPO, sha)["status"] == "ahead"
    assert client.workflow_runs(MODULES_REPO, sha, 1)["workflow_runs"] == []
    assert client.run_jobs(MODULES_REPO, 123, 1)["jobs"] == []
    assert len(opener.calls) == 3
    assert all(url.startswith("https://api.github.com/repos/SickIcarus-Labs/") for url, _, _ in opener.calls)
    assert all(method == "GET" for _, method, _ in opener.calls)
    assert all(auth == "Bearer read-only-test-value" for _, _, auth in opener.calls)


def test_do_not_forward_private_token_to_untrusted_redirect():
    handler = _NoRedirect()
    req = urllib.request.Request("https://api.github.com/repos/SickIcarus-Labs/monitorbox",
                                 headers={"Authorization": "Bearer private"}, method="GET")
    with pytest.raises(ReleaseRefusal, match="unexpected redirect"):
        handler.redirect_request(req, None, 302, "found", {},
                                 "https://evil.example/leak")


def test_api_disallows_tag_refs_foreign_repos_and_unbounded_pages():
    client = GitHubReadOnly(opener=Opener())
    with pytest.raises(ReleaseRefusal, match="immutable lowercase commit SHA"):
        client.compare_main(CORE_REPO, "main")
    with pytest.raises(ReleaseRefusal, match="unknown"):
        client.compare_main("OtherOrg/other", "a" * 40)
    with pytest.raises(ReleaseRefusal, match="bounded"):
        client.workflow_runs(CORE_REPO, "a" * 40, 6)
    with pytest.raises(ReleaseRefusal, match="bounded"):
        client.run_jobs(CORE_REPO, 0, 1)


def test_client_never_contains_mutating_http_method():
    path = Path(__file__).parent / "successor_github_readonly.py"
    raw = path.read_text("utf-8")
    for string in ('method="POST"', 'method="PATCH"', 'method="PUT"',
                   'method="DELETE"', "subprocess", "GHCR_READ_TOKEN"):
        assert string not in raw
