"""Discover immutable Debian-signed snapshot evidence for exact native libatomic1.

Research/proof only: current runtime candidate remains release_eligible:false.
Only untrusted internet bytes are downloaded; an independently pinned OCI
Debian archive keyring verifies the full InRelease before its SHA256 index
records can authorize a Packages.xz and then a single approved .deb.

Archive availability is an external dependency: absence or changed bytes
means FAIL CLOSED; this is not an independently hosted retention guarantee.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import json
import lzma
import os
import pathlib
import re
import subprocess
import urllib.error
import urllib.request
import urllib.parse

HOST = "https://snapshot.debian.org"
STAMP = "20260926T000000Z"
CHECKPOINT = dt.datetime(2026, 9, 26, tzinfo=dt.timezone.utc)
MAX_RELEASE = 512 << 10
MAX_INDEX = 30 << 20
MAX_EXPANDED = 180 << 20
MAX_DEB = 25 << 20
SHA = re.compile(r"[a-f0-9]{64}\Z")
TARGET_VERSION = "12.2.0-14+deb12u1"
APPROVED = {
    "amd64": ("fbd4e154a6b444229ea002cc209df099209c0adc09102e5fd21239a3d2b55e2d", 9376),
    "arm64": ("1693aa13ce2b30d061a519fc28b77b9bab8c8e45804ced5969d99821e1bc2159", 9568),
}
# Search alternate historically signed Debian suites only during discovery.
SUITES = (
    ("debian", "bookworm"),
    ("debian", "bookworm-updates"),
    ("debian-security", "bookworm-security"),
)


class SnapshotError(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str, limit: int) -> bytes:
    if not url.startswith(HOST + "/archive/") or ".." in url:
        raise SnapshotError("unapproved Debian snapshot endpoint")
    for attempt in range(2):
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "MonitorBox-unreleaseable-signed-Debian-proof/1",
                "Accept-Encoding": "identity",
            })
            with urllib.request.urlopen(request, timeout=45) as response:
                final = urllib.parse.urlsplit(response.url)
                # snapshot.debian.org redirects a dated /archive/ URL to
                # immutable /file/<content-digest> objects. Permit exactly
                # those same-origin HTTPS content-addressed objects, never
                # generic redirects/cross-domain hosts or arbitrary paths.
                if (final.scheme != "https" or final.hostname != "snapshot.debian.org" or
                        final.username is not None or final.password is not None or
                        not final.path.startswith(("/archive/", "/file/")) or
                        final.fragment or response.status != 200 or
                        int(response.headers.get("Content-Length", "0")) > limit):
                    raise SnapshotError(
                        "Debian snapshot unsafe redirect or oversized response: " +
                        final.scheme + "://" + str(final.hostname) + final.path[:100]
                    )
                payload = response.read(limit + 1)
            if len(payload) > limit:
                raise SnapshotError("Debian snapshot member exceeds strict byte bound")
            return payload
        except (OSError, urllib.error.HTTPError) as exc:
            if attempt:
                raise SnapshotError("immutable Debian snapshot is unavailable: " + url) from exc
    raise AssertionError("unreachable")


def cleartext(signed: bytes) -> str:
    text = signed.decode("utf-8")
    if not text.startswith("-----BEGIN PGP SIGNED MESSAGE-----\n"):
        raise SnapshotError("snapshot Release lacks inline signature")
    header, separator, body = text.partition("\n\n")
    if not separator or "Hash:" not in header or "-----BEGIN PGP SIGNATURE-----" not in body:
        raise SnapshotError("incomplete signed Debian Release envelope")
    body = body.split("\n-----BEGIN PGP SIGNATURE-----", 1)[0]
    # PGP cleartext dash escaping is explicitly reversed only AFTER gpgv.
    return "\n".join(line[2:] if line.startswith("- ") else line
                     for line in body.splitlines())


def verified_release(raw: bytes, keyring: pathlib.Path, location: pathlib.Path) -> tuple[str, dict]:
    if keyring.is_symlink() or not keyring.is_file():
        raise SnapshotError("missing or linked Debian OCI archive keyring")
    location.write_bytes(raw)
    try:
        result = subprocess.run(
            ["gpgv", "--keyring", str(keyring.resolve()), str(location)],
            text=True, capture_output=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SnapshotError("gpgv cannot verify Debian archive identity") from exc
    if result.returncode != 0:
        raise SnapshotError("Debian InRelease signature FAILED: " + result.stderr[-250:])
    body = cleartext(raw)
    fields: dict[str, str] = {}
    mode = ""
    hashes: dict[str, tuple[str, int]] = {}
    for line in body.splitlines():
        if line == "SHA256:":
            mode = "sha256"
            continue
        if mode == "sha256" and line[:1].isspace():
            parts = line.split()
            if len(parts) != 3 or not SHA.fullmatch(parts[0]) or not parts[1].isdigit():
                raise SnapshotError("invalid signed Debian SHA256 index record")
            if parts[2] in hashes:
                raise SnapshotError("duplicate signed Debian index record")
            hashes[parts[2]] = (parts[0], int(parts[1]))
            continue
        if ":" in line and not line[:1].isspace():
            mode = ""
            key, value = line.split(":", 1)
            if key in fields:
                raise SnapshotError("duplicate signed Debian Release field")
            fields[key] = value.strip()
        elif not line[:1].isspace():
            mode = ""
    date = email.utils.parsedate_to_datetime(fields["Date"])
    if date.tzinfo is None or date > CHECKPOINT:
        raise SnapshotError("signed Debian Release postdates immutable snapshot")
    if fields.get("Valid-Until"):
        valid = email.utils.parsedate_to_datetime(fields["Valid-Until"])
        if valid < CHECKPOINT:
            raise SnapshotError("signed Debian Release already expired when archived")
    return body, {"fields": fields, "hashes": hashes, "signed_at": date.isoformat()}


def selected_paragraph(expanded: bytes, arch: str) -> dict[str, str] | None:
    result = []
    # Packages indexes contain RFC822 continuation records. In this narrow
    # proof the selected package metadata values must be *single-line*.
    for paragraph in expanded.decode("utf-8").split("\n\n"):
        if not paragraph.startswith("Package: libatomic1\n"):
            continue
        fields = {}
        for line in paragraph.splitlines():
            if line[:1].isspace() or ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key in fields:
                raise SnapshotError("duplicate signed Packages field")
            fields[key] = value.strip()
        if (fields.get("Package") == "libatomic1" and
                fields.get("Version") == TARGET_VERSION and
                fields.get("Architecture") == arch):
            result.append(fields)
    if len(result) > 1:
        raise SnapshotError("ambiguous exact Debian-signed ABI package")
    return result[0] if result else None


# Source-reviewed immutable evidence captured independently in native CI run
# 36361576510. A maintainer must deliberately change BOTH code policy
# constants and the committed lock for any future Debian snapshot refresh.
APPROVED_KEYRING = "506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017"
APPROVED_RELEASE = "77737fa4b34f2693e982cc9ee35736816c35a7778fc2d326cc1bbf5b301fe1aa"
APPROVED_PACKAGE_INDEX = {
    "amd64": ("9e0b5aabb2465b3d2e7a7fe27f9913846277833f7a2826e7767acccff5b588c5",
              8790396,
              "515e692f2c4121c6fcec444ef100cc18f79a991910615f3a88c8b7becfc94d2f"),
    "arm64": ("2ddb1737692e8c45c53e8d57c0ce4cd21c78c5703b830c3226b1423566a06c00",
              8689464,
              "c7c883a61f348283050d3a754e7c8119117c4019bf65da804c78fdae315866f1"),
}


def strict_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotError("duplicate snapshot provenance lock key")
        result[key] = value
    return result


def load_approved_snapshot(source: pathlib.Path, arch: str) -> dict:
    if arch not in APPROVED or source.is_symlink() or not source.is_file() or source.stat().st_size > 4096:
        raise SnapshotError("missing/unsafe reviewed native Debian snapshot source lock")
    try:
        actual = json.loads(source.read_text(encoding="utf-8"),
                            object_pairs_hook=strict_pairs)
    except SnapshotError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise SnapshotError("malformed committed Debian snapshot lock") from exc
    index_hash, index_size, uncompressed_hash = APPROVED_PACKAGE_INDEX[arch]
    expected_deb, expected_deb_size = APPROVED[arch]
    expected = {
        "schema": 1, "release_eligible": False,
        "packaging_stage": "snapshot-debian-signed-index-discovery-only",
        "arch": arch, "source": "debian", "suite": "bookworm", "checkpoint": STAMP,
        "keyring_sha256": APPROVED_KEYRING,
        "inrelease": {
            "url": f"{HOST}/archive/debian/{STAMP}/dists/bookworm/InRelease",
            "sha256": APPROVED_RELEASE, "size": 151075,
            "signed_date": "2026-07-11T10:16:37+00:00",
        },
        "packages": {
            "path": f"main/binary-{arch}/Packages.xz",
            "sha256": index_hash, "size": index_size,
            "uncompressed_sha256": uncompressed_hash,
        },
        "deb": {
            "source_path": f"pool/main/g/gcc-12/libatomic1_{TARGET_VERSION}_{arch}.deb",
            "sha256": expected_deb, "size": expected_deb_size,
        },
    }
    if type(actual) is not dict or type(actual.get("schema")) is not int or actual != expected:
        raise SnapshotError("snapshot lock disagrees with independently reviewed native signed-index source")
    return expected


def run_probe(arch: str, keyring: pathlib.Path, out: pathlib.Path, approved: dict | None = None) -> dict:
    if arch not in APPROVED:
        raise SnapshotError("unsupported approved Debian CPU")
    if out.is_symlink() or (out.exists() and list(out.iterdir())):
        raise SnapshotError("refusing reused or linked signed Debian evidence")
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    expected_deb, expected_bytes = APPROVED[arch]
    if approved is not None and (
        approved["arch"] != arch or sha(keyring.read_bytes()) != approved["keyring_sha256"]
    ):
        raise SnapshotError("snapshot signer keyring differs from source-reviewed pinned OCI image")
    suites = ((approved["source"], approved["suite"]),) if approved is not None else SUITES
    for archive, suite in suites:
        base = f"{HOST}/archive/{archive}/{STAMP}"
        release_url = f"{base}/dists/{suite}/InRelease"
        try:
            raw = download(release_url, MAX_RELEASE)
        except SnapshotError as exc:
            print("Unavailable immutable suite:", archive, suite, str(exc)[:150], flush=True)
            continue
        if approved is not None and (
            sha(raw) != approved["inrelease"]["sha256"] or
            len(raw) != approved["inrelease"]["size"] or
            release_url != approved["inrelease"]["url"]
        ):
            raise SnapshotError("immutable Debian InRelease bytes differ from source-reviewed signature")
        source = out / f"{archive}-{suite}-InRelease"
        _, signed = verified_release(raw, keyring, source)
        index_path = f"main/binary-{arch}/Packages.xz"
        entry = signed["hashes"].get(index_path)
        if entry is None:
            print("No signed xz index:", archive, suite, flush=True)
            continue
        index_hash, index_size = entry
        if approved is not None and (
            approved["packages"]["sha256"] != index_hash or
            approved["packages"]["size"] != index_size or
            approved["packages"]["path"] != index_path
        ):
            raise SnapshotError("signed Debian Packages index differs from reviewed native lock")
        if index_size > MAX_INDEX:
            raise SnapshotError("signed Debian index larger than approved budget")
        compressed = download(f"{base}/dists/{suite}/{index_path}", MAX_INDEX)
        if len(compressed) != index_size or sha(compressed) != index_hash:
            raise SnapshotError("immutable Packages index differs from Debian SIGNED Release")
        expanded = lzma.decompress(compressed, memlimit=256 << 20)
        if len(expanded) > MAX_EXPANDED:
            raise SnapshotError("oversized fully authenticated Debian index")
        if approved is not None and sha(expanded) != approved["packages"]["uncompressed_sha256"]:
            raise SnapshotError("authenticated native Debian Packages uncompressed bytes changed")
        record = selected_paragraph(expanded, arch)
        if record is None:
            print("Reviewed Debian ABI package not in immutable suite:", archive, suite, flush=True)
            continue
        if (record.get("SHA256") != expected_deb or
                int(record.get("Size", 0)) != expected_bytes):
            raise SnapshotError("signed historical index disagrees with source-reviewed ABI bytes")
        basename = f"libatomic1_{TARGET_VERSION}_{arch}.deb"
        expected_path = "pool/main/g/gcc-12/" + basename
        if record.get("Filename") != expected_path:
            raise SnapshotError("signed Debian package source path changed")
        deb = download(f"{base}/{expected_path}", MAX_DEB)
        if len(deb) != expected_bytes or sha(deb) != expected_deb:
            raise SnapshotError("immutable archived Debian .deb changed")
        (out / basename).write_bytes(deb)
        (out / f"{archive}-{suite}-Packages.xz").write_bytes(compressed)
        proof = {
            "schema": 1, "release_eligible": False,
            "packaging_stage": "snapshot-debian-signed-index-discovery-only",
            "arch": arch, "source": archive, "suite": suite, "checkpoint": STAMP,
            "keyring_sha256": sha(keyring.read_bytes()),
            "inrelease": {
                "url": release_url, "sha256": sha(raw), "size": len(raw),
                "signed_date": signed["signed_at"],
            },
            "packages": {
                "path": index_path, "sha256": index_hash,
                "size": index_size, "uncompressed_sha256": sha(expanded),
            },
            "deb": {
                "source_path": expected_path,
                "sha256": expected_deb, "size": expected_bytes,
            },
        }
        if approved is not None and proof != approved:
            raise SnapshotError("dated signed Debian Release/index/package proof changed")
        evidence = out / f"snapshot-proof-{arch}.json"
        evidence.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
        print("BEGIN_SIGNED_DEBIAN_SNAPSHOT_" + arch)
        print(evidence.read_text(), end="")
        print("END_SIGNED_DEBIAN_SNAPSHOT_" + arch)
        return proof
    raise SnapshotError("no exact signed immutable Debian snapshot contains approved ABI version")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", required=True, choices=APPROVED)
    parser.add_argument("--keyring", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--approved-lock", type=pathlib.Path,
                        help="require EXACT source-reviewed dated snapshot; never fall back to live apt")
    args = parser.parse_args()
    reviewed = load_approved_snapshot(args.approved_lock, args.arch) if args.approved_lock else None
    run_probe(args.arch, args.keyring, args.output, reviewed)


if __name__ == "__main__":
    main()
