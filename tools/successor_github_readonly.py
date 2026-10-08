"""Fixed-host GitHub REST v3 GET-only evidence reader; no release actions."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from successor_github_source_evidence import CORE_REPO, MODULES_REPO
from successor_release_pairing import ReleaseRefusal

BASE = "https://api.github.com"
REPOS = frozenset((CORE_REPO, MODULES_REPO))
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
MAX_RESPONSE = 8 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # An API-origin credential must not travel to any other host.
        raise ReleaseRefusal("unexpected redirect from the GitHub evidence API")


class GitHubReadOnly:
    def __init__(self, token: str | None = None, opener=None):
        self._token = token
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(),
        )

    @staticmethod
    def _repo(repo: str) -> str:
        if repo not in REPOS:
            raise ReleaseRefusal("unknown source repository requested")
        return repo

    @staticmethod
    def _sha(sha: str) -> str:
        if not isinstance(sha, str) or not COMMIT.fullmatch(sha):
            raise ReleaseRefusal("GitHub API requires one immutable lowercase commit SHA")
        return sha

    @staticmethod
    def _number(value: int, maximum: int) -> int:
        if type(value) is not int or not (1 <= value <= maximum):
            raise ReleaseRefusal("invalid bounded GitHub evidence index")
        return value

    def _get(self, path: str, params: dict | None = None) -> dict:
        # Paths are constructed only by fixed helpers, not manifest data.
        query = urllib.parse.urlencode(params or {})
        url = BASE + path + ("?" + query if query else "")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "MonitorBox-read-only-release-evidence",
        }
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self._opener.open(request, timeout=40) as resp:
                declared = resp.headers.get("Content-Length")
                if declared and int(declared) > MAX_RESPONSE:
                    raise ReleaseRefusal("GitHub API response too large")
                raw = resp.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as exc:
            raise ReleaseRefusal("read-only GitHub API evidence request denied") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ReleaseRefusal("read-only GitHub API request failed") from exc
        if len(raw) > MAX_RESPONSE:
            raise ReleaseRefusal("GitHub API evidence exceeds bounded size")
        try:
            decoded = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ReleaseRefusal("invalid GitHub evidence JSON") from exc
        if not isinstance(decoded, dict):
            raise ReleaseRefusal("invalid GitHub evidence response shape")
        return decoded

    def compare_main(self, repository: str, source_sha: str) -> dict:
        repo = self._repo(repository)
        sha = self._sha(source_sha)
        return self._get(f"/repos/{repo}/compare/{sha}...main")

    def workflow_runs(self, repository: str, source_sha: str, page: int) -> dict:
        repo = self._repo(repository)
        sha = self._sha(source_sha)
        page = self._number(page, 5)
        return self._get(f"/repos/{repo}/actions/runs", {
            "head_sha": sha, "per_page": 100, "page": page,
        })

    def run_jobs(self, repository: str, run_id: int, page: int) -> dict:
        repo = self._repo(repository)
        run_id = self._number(run_id, 2**63-1)
        page = self._number(page, 5)
        return self._get(f"/repos/{repo}/actions/runs/{run_id}/jobs", {
            "per_page": 100, "page": page,
        })


def source_api_from_environment() -> GitHubReadOnly:
    """GH_SOURCE_READ_TOKEN must be read-only on both private repositories."""
    return GitHubReadOnly(os.environ.get("GH_SOURCE_READ_TOKEN"))
