"""No-network GET-only GHCR transport, auth and redirect regression tests."""
import io
import json
import hashlib
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from successor_ghcr_readonly import GHCRReadOnly, _SafeRedirect
from successor_registry_extract import FULL_REPO, ReleaseRefusal


def digest(payload):
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}


class FakeOpener:
    def __init__(self, registry, challenge=False):
        self.registry = registry
        self.challenge = challenge
        self.seen = []
        self.token = b'{"token":"fake-pull-only-token"}'

    def open(self, req, timeout=45):
        self.seen.append((req.full_url, req.get_method(),
                          req.get_header("Authorization")))
        if "/token?" in req.full_url:
            assert req.full_url.startswith("https://ghcr.io/token?")
            return Response(self.token, {"Content-Length": str(len(self.token))})
        if self.challenge and req.get_header("Authorization") != "Bearer fake-pull-only-token":
            headers = {
                "WWW-Authenticate": 'Bearer realm="https://ghcr.io/token",service="ghcr.io",'
                                    'scope="repository:' + FULL_REPO + ':pull"'}
            raise urllib.error.HTTPError(req.full_url, 401, "authentication required",
                                         headers, io.BytesIO(b""))
        url = req.full_url
        if url not in self.registry:
            raise AssertionError("unexpected GET: " + url)
        payload = self.registry[url]
        return Response(payload, {"Content-Length": str(len(payload))})


def test_anonymous_immutable_manifest_and_blob_get_only(tmp_path):
    data = b'{"schemaVersion":2,"mediaType":"test"}'
    pkg = b"immutable sample content"
    md, bd = digest(data), digest(pkg)
    manifest = f"https://ghcr.io/v2/{FULL_REPO}/manifests/{md}"
    blob = f"https://ghcr.io/v2/{FULL_REPO}/blobs/{bd}"
    opener = FakeOpener({manifest: data, blob: pkg})
    client = GHCRReadOnly(opener=opener)
    assert client.manifest(FULL_REPO, md) == data
    path = tmp_path / "blob"
    client.blob(FULL_REPO, bd, path, 1000)
    assert path.read_bytes() == pkg
    assert all(method == "GET" for _, method, _ in opener.seen)
    assert all(auth is None for _, _, auth in opener.seen)


def test_bearer_challenge_scope_and_basic_credentials_not_shared_with_registry():
    raw = b"exact OCI manifest"
    sha = digest(raw)
    url = f"https://ghcr.io/v2/{FULL_REPO}/manifests/{sha}"
    opener = FakeOpener({url: raw}, challenge=True)
    client = GHCRReadOnly(username="operator", read_token="read-package-token", opener=opener)
    assert client.manifest(FULL_REPO, sha) == raw
    assert len(opener.seen) == 3
    before, token, after = opener.seen
    assert before[2] is None
    assert token[0].startswith("https://ghcr.io/token?")
    assert token[2].startswith("Basic ")
    assert after[2] == "Bearer fake-pull-only-token"
    assert all(method == "GET" for _, method, _ in opener.seen)


def test_dont_forward_authentication_to_cross_origin_blob_cdn():
    original = urllib.request.Request("https://ghcr.io/v2/name/blobs/sha256:abc",
                                      headers={"Authorization": "Bearer confidential",
                                               "Accept": "application/octet-stream"},
                                      method="GET")
    handler = _SafeRedirect()
    changed = handler.redirect_request(original, None, 307, "redirect", {},
                                       "https://cdn.example.com/content")
    assert changed.get_header("Authorization") is None
    assert changed.get_header("Accept") == "application/octet-stream"
    assert changed.get_method() == "GET"
    with pytest.raises(ReleaseRefusal, match="non-TLS"):
        handler.redirect_request(original, None, 307, "bad", {},
                                 "http://cdn.example.com/unsecured")


def test_reject_unpinned_image_or_unknown_repository():
    c = GHCRReadOnly(opener=FakeOpener({}))
    with pytest.raises(ReleaseRefusal, match="only the two"):
        c.manifest(FULL_REPO, "stable")
    with pytest.raises(ReleaseRefusal, match="only the two"):
        c.manifest("someone-else/other", "sha256:" + "a" * 64)


def test_reject_bearer_authority_mismatch():
    c = GHCRReadOnly(opener=FakeOpener({}))
    with pytest.raises(ReleaseRefusal, match="unexpected registry token authority"):
        c._token_from_challenge(
            FULL_REPO, 'Bearer realm="https://evil.example/token",'
                       'service="ghcr.io",scope="repository:' + FULL_REPO + ':pull"')
    with pytest.raises(ReleaseRefusal, match="unexpected registry token authority"):
        c._token_from_challenge(
            FULL_REPO, 'Bearer realm="https://ghcr.io/token",'
                       'service="ghcr.io",scope="repository:' + FULL_REPO + ':push"')


def test_reject_wrong_returned_blob_digest_and_delete_partial_file(tmp_path):
    expected = digest(b"original")
    url = f"https://ghcr.io/v2/{FULL_REPO}/blobs/{expected}"
    client = GHCRReadOnly(opener=FakeOpener({url: b"tampered"}))
    path = tmp_path / "untrusted"
    with pytest.raises(ReleaseRefusal, match="blob digest"):
        client.blob(FULL_REPO, expected, path, 100)
    assert not path.exists()


def test_bounded_blob_refuses_oversize_and_cleans_up(tmp_path):
    payload = b"x" * 200
    key = digest(payload)
    url = f"https://ghcr.io/v2/{FULL_REPO}/blobs/{key}"
    client = GHCRReadOnly(opener=FakeOpener({url: payload}))
    path = tmp_path / "too-large"
    with pytest.raises(ReleaseRefusal, match="resource budget"):
        client.blob(FULL_REPO, key, path, 100)
    assert not path.exists()


def test_readonly_client_has_no_http_mutation_implementation():
    raw = (Path(__file__).parent / "successor_ghcr_readonly.py").read_text()
    for forbidden in ('method="POST"', 'method="PUT"', 'method="PATCH"',
                      'method="DELETE"', "docker login", "imagetools create",
                      "subprocess"):
        assert forbidden not in raw
