"""Fixed-origin, GET-only GHCR v2 reader for immutable successor OCI blobs.

No user-supplied repository URL, tag, registry origin, Docker daemon, mutation
method or credential logging. Authentication uses an optional read-only package
token against the fixed ghcr.io token realm. Cross-host blob redirects never
receive registry Authorization or Basic credentials; all blobs are SHA-pinned
and are validated again by the OCI extraction caller.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from successor_registry_extract import FULL_REPO, SUPERVISOR_REPO
from successor_release_pairing import ReleaseRefusal

BASE = "https://ghcr.io"
ALLOWED = frozenset((FULL_REPO, SUPERVISOR_REPO))
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
TOKEN_REALM = "https://ghcr.io/token"
INDEX_MIME = ", ".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
))
MAX_MANIFEST = 4 * 1024 * 1024
MAX_TOKEN_RESPONSE = 128 * 1024


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        old, new = urllib.parse.urlsplit(request.full_url), urllib.parse.urlsplit(new_url)
        if (new.scheme != "https" or new.username or new.password or
                not new.hostname or new.port not in (None, 443)):
            raise ReleaseRefusal("GHCR redirected to a non-TLS or unsafe endpoint")
        outgoing = dict(request.headers)
        if new.hostname != old.hostname:
            outgoing = {k: v for k, v in outgoing.items()
                        if k.lower() not in ("authorization", "proxy-authorization", "cookie")}
        return urllib.request.Request(new_url, headers=outgoing, method="GET")


class GHCRReadOnly:
    def __init__(self, *, username: str | None = None,
                 read_token: str | None = None, opener=None):
        if bool(username) != bool(read_token):
            raise ReleaseRefusal("GHCR credentials must be username plus read-only token")
        self.username = username
        self.read_token = read_token
        self._bearers: dict[str, str] = {}
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _SafeRedirect())

    @staticmethod
    def _check(repository: str, digest: str):
        if repository not in ALLOWED or not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ReleaseRefusal("only the two approved immutable successor GHCR images may be read")

    def _fetch(self, url: str, *, headers=None):
        try:
            return self._opener.open(urllib.request.Request(
                url, headers=headers or {}, method="GET"), timeout=45)
        except urllib.error.HTTPError:
            raise
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise ReleaseRefusal("secure GHCR GET failed") from exc

    @staticmethod
    def _read_limited(response, maximum: int) -> bytes:
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                if int(declared) > maximum:
                    raise ReleaseRefusal("registry response exceeds size budget")
            except ValueError as exc:
                raise ReleaseRefusal("invalid registry Content-Length") from exc
        data = bytearray()
        while True:
            part = response.read(min(1024 * 1024, maximum + 1 - len(data)))
            if not part:
                break
            data.extend(part)
            if len(data) > maximum:
                raise ReleaseRefusal("registry response exceeds size budget")
        return bytes(data)

    def _token_from_challenge(self, repository: str, value: str | None) -> str:
        if not value or not value.startswith("Bearer "):
            raise ReleaseRefusal("GHCR did not offer Bearer pull authorization")
        parameters = dict(re.findall(r'([A-Za-z_]+)="([^"]*)"', value[7:]))
        if (parameters.get("realm") != TOKEN_REALM or
                parameters.get("service") != "ghcr.io" or
                parameters.get("scope", f"repository:{repository}:pull") !=
                    f"repository:{repository}:pull"):
            raise ReleaseRefusal("unexpected registry token authority or requested scope")
        query = urllib.parse.urlencode({
            "scope": f"repository:{repository}:pull", "service": "ghcr.io"})
        headers = {"Accept": "application/json"}
        if self.username is not None:
            credentials = f"{self.username}:{self.read_token}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode("ascii")
        try:
            with self._fetch(TOKEN_REALM + "?" + query, headers=headers) as response:
                token_response = self._read_limited(response, MAX_TOKEN_RESPONSE)
                payload = json.loads(token_response)
        except (urllib.error.HTTPError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ReleaseRefusal("GHCR pull-token negotiation failed") from exc
        token = payload.get("token") or payload.get("access_token")
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise ReleaseRefusal("GHCR returned no bounded pull token")
        self._bearers[repository] = token
        return token

    def _authorized_get(self, repository: str, url: str, accept: str):
        headers = {"Accept": accept}
        if repository in self._bearers:
            headers["Authorization"] = "Bearer " + self._bearers[repository]
        try:
            return self._fetch(url, headers=headers)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise ReleaseRefusal("GHCR read request rejected") from exc
            challenge = exc.headers.get("WWW-Authenticate")
            exc.close()
            token = self._token_from_challenge(repository, challenge)
            headers["Authorization"] = "Bearer " + token
            try:
                return self._fetch(url, headers=headers)
            except urllib.error.HTTPError as err:
                raise ReleaseRefusal("GHCR authenticated read rejected") from err

    def manifest(self, repository: str, digest: str) -> bytes:
        self._check(repository, digest)
        url = BASE + "/v2/" + repository + "/manifests/" + digest
        with self._authorized_get(repository, url, INDEX_MIME) as response:
            result = self._read_limited(response, MAX_MANIFEST)
            header = response.headers.get("Docker-Content-Digest")
        if header is not None and header != digest:
            raise ReleaseRefusal("registry reported another immutable manifest digest")
        if "sha256:" + hashlib.sha256(result).hexdigest() != digest:
            raise ReleaseRefusal("registry returned bytes different from requested digest")
        return result

    def blob(self, repository: str, digest: str, destination: Path,
             max_bytes: int) -> None:
        self._check(repository, digest)
        if type(max_bytes) is not int or max_bytes <= 0 or max_bytes > 2 * 1024**3:
            raise ReleaseRefusal("invalid registry blob resource budget")
        url = BASE + "/v2/" + repository + "/blobs/" + digest
        h = hashlib.sha256()
        count = 0
        try:
            with self._authorized_get(repository, url, "application/octet-stream") as response:
                with destination.open("xb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > max_bytes:
                            raise ReleaseRefusal("registry blob exceeds resource budget")
                        h.update(chunk)
                        output.write(chunk)
            if "sha256:" + h.hexdigest() != digest:
                raise ReleaseRefusal("registry blob digest mismatch")
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def read_only_ghcr_client_from_environment():
    """Optional GHCR_READ_TOKEN must have read:packages only; never log it."""
    return GHCRReadOnly(
        username=os.environ.get("GHCR_USERNAME"),
        read_token=os.environ.get("GHCR_READ_TOKEN"),
    )
