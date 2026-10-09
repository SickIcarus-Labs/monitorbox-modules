"""Read-only digest-bound OCI layer extraction and signed release admission.

All registry bytes must be fetched through a fixed-repository, GET-only provider.
A verified OCI index -> manifest -> config -> layer digest chain is required
before extracted feed bytes are admitted by the official Ed25519 catalog tools.
No Docker daemon, image execution, signer secret, or tag write is permitted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import io
import re
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Mapping, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator

from successor_oci_evidence import verify_immutable_oci_index
from successor_release_manifest import SCHEMA, admit_candidate_manifest
from successor_release_pairing import ARCHES, Feed, Pair, ReleaseRefusal, SupervisorFeed
from verify_platform_index import VerificationError, _parse

FULL_REPO = "sickicarus-labs/monitorbox-successor-signed-feed"
SUPERVISOR_REPO = "sickicarus-labs/monitorbox-successor-supervisor-feed"
HEX_DIGEST = re.compile(r"sha256:[a-f0-9]{64}\Z")
ZIP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,180}\.zip\Z")
CATALOG = "platform/channels/stable/index.json"
MAX_JSON = 4 * 1024 * 1024
MAX_LAYER_COUNT = 16
MAX_LAYER_BYTES = 2 * 1024 * 1024 * 1024
MAX_SINGLE_FILE = 1024 * 1024 * 1024
MAX_EXTRACTED = 4 * 1024 * 1024 * 1024


class ReadOnlyRegistry(Protocol):
    def manifest(self, repository: str, digest: str) -> bytes: ...
    def blob(self, repository: str, digest: str, destination: Path,
             max_bytes: int) -> None: ...


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _valid_digest(value: object) -> str:
    if not isinstance(value, str) or not HEX_DIGEST.fullmatch(value):
        raise ReleaseRefusal("only immutable sha256 OCI references are admissible")
    return value


def _json(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or len(raw) > MAX_JSON:
        raise ReleaseRefusal("OCI/manifest JSON is missing or oversized")
    try:
        value = _parse(raw)
    except (VerificationError, TypeError, ValueError) as exc:
        raise ReleaseRefusal("invalid registry JSON bytes") from exc
    if not isinstance(value, dict):
        raise ReleaseRefusal("registry JSON must be an object")
    return value


def _manifest_bytes(provider: ReadOnlyRegistry, repo: str, digest: str) -> bytes:
    _valid_digest(digest)
    raw = provider.manifest(repo, digest)
    if not isinstance(raw, bytes) or len(raw) > MAX_JSON or _sha(raw) != digest:
        raise ReleaseRefusal("GHCR manifest did not match pinned digest")
    return raw


def _safe_tar_name(name: str) -> tuple[str, ...]:
    if (not name or name.startswith("/") or "\\" in name or "\x00" in name):
        raise ReleaseRefusal("unsafe image-layer path")
    original = PurePosixPath(name).parts
    if ".." in original:
        raise ReleaseRefusal("image-layer path traversal")
    parts = tuple(x for x in original if x != ".")
    if not parts:
        raise ReleaseRefusal("empty image-layer member path")
    if any(x.startswith(".wh.") for x in parts):
        raise ReleaseRefusal("OCI whiteouts are unsupported in feed image")
    return parts


def _extract_verified_layer(layer_path: Path, root: Path, *,
                            seen: set[str], total: list[int],
                            compression: str) -> None:
    # Feed images are scratch-based. Fail closed on whiteouts and any symlinks,
    # hardlinks, devices or unusual tar object. Never call extractall().
    mode = "r|gz" if compression == "gzip" else "r|"
    try:
        with tarfile.open(layer_path, mode=mode) as tar:
            for member in tar:
                parts = _safe_tar_name(member.name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ReleaseRefusal("OCI layer contains unsafe non-regular member")
                if member.size < 0 or member.size > MAX_SINGLE_FILE:
                    raise ReleaseRefusal("OCI layer entry too large")
                total[0] += member.size
                if total[0] > MAX_EXTRACTED:
                    raise ReleaseRefusal("OCI layer uncompressed size budget exceeded")
                if not (len(parts) >= 2 and parts[0] == "feed"):
                    continue
                relative = "/".join(parts[1:])
                channel_index = (
                    len(parts) == 5 and parts[1:3] == ("platform", "channels")
                    and parts[3] in ("stable", "beta", "dev")
                    and parts[4] == "index.json"
                )
                if not channel_index and not (
                    len(parts) == 4 and parts[1:3] == ("platform", "packages")
                    and ZIP_NAME.fullmatch(parts[-1])
                ):
                    # Ignore application executable and legitimate other files
                    # but do not permit unknown file types under signed authority.
                    if relative.startswith("platform/"):
                        raise ReleaseRefusal("unexpected file inside signed platform authority")
                    continue
                if relative in seen:
                    raise ReleaseRefusal("overlaid or duplicate signed feed file")
                seen.add(relative)
                dst = root.joinpath(*parts[1:])
                dst.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(member)
                if src is None:
                    raise ReleaseRefusal("missing OCI regular file bytes")
                with dst.open("xb") as out:
                    remaining = member.size
                    while remaining:
                        chunk = src.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ReleaseRefusal("truncated OCI layer member")
                        out.write(chunk)
                        remaining -= len(chunk)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ReleaseRefusal("invalid or incomplete OCI layer") from exc


def _verified_platform_image(provider: ReadOnlyRegistry, repo: str,
                             digest: str, destination: Path) -> tuple[dict, dict]:
    index_raw = _manifest_bytes(provider, repo, digest)
    index = _json(index_raw)
    descriptors = index.get("manifests")
    if not isinstance(descriptors, list):
        raise ReleaseRefusal("missing OCI architecture descriptors")
    by_arch = {}
    for item in descriptors:
        if not isinstance(item, dict) or not isinstance(item.get("platform"), dict):
            raise ReleaseRefusal("invalid OCI architecture descriptor")
        arch = item["platform"].get("architecture")
        if arch not in ARCHES or arch in by_arch:
            raise ReleaseRefusal("unexpected/duplicate OCI architecture")
        by_arch[arch] = item
    if set(by_arch) != ARCHES:
        raise ReleaseRefusal("missing OCI architecture")

    manifests, configs, objects = {}, {}, {}
    for arch in sorted(ARCHES):
        manifest_raw = _manifest_bytes(provider, repo, _valid_digest(by_arch[arch].get("digest")))
        manifests[arch] = manifest_raw
        value = _json(manifest_raw)
        config = value.get("config")
        if not isinstance(config, dict):
            raise ReleaseRefusal("missing OCI config descriptor")
        config_digest = _valid_digest(config.get("digest"))
        with tempfile.TemporaryDirectory(prefix="mb-config-") as tmp:
            place = Path(tmp) / "config"
            provider.blob(repo, config_digest, place, MAX_JSON)
            raw = place.read_bytes()
        if len(raw) > MAX_JSON or _sha(raw) != config_digest:
            raise ReleaseRefusal("OCI config bytes fail immutable digest")
        configs[arch] = raw
        objects[arch] = value

    labels = verify_immutable_oci_index(
        index_raw, expected_digest=digest,
        platform_manifests=manifests, platform_configs=configs,
    )
    for arch in sorted(ARCHES):
        root = destination / arch
        root.mkdir(parents=True, exist_ok=False)
        seen: set[str] = set()
        total = [0]
        layers = objects[arch]["layers"]
        if not 1 <= len(layers) <= MAX_LAYER_COUNT:
            raise ReleaseRefusal("unsafe OCI layer count")
        for layer in layers:
            compressed = _valid_digest(layer.get("digest"))
            media = layer.get("mediaType")
            if media in ("application/vnd.oci.image.layer.v1.tar+gzip",
                         "application/vnd.docker.image.rootfs.diff.tar.gzip"):
                compression = "gzip"
            elif media == "application/vnd.oci.image.layer.v1.tar":
                compression = "plain"
            else:
                raise ReleaseRefusal("unsupported OCI layer format")
            size = layer.get("size")
            if type(size) is not int or size <= 0 or size > MAX_LAYER_BYTES:
                raise ReleaseRefusal("OCI layer exceeds compressed size budget")
            with tempfile.TemporaryDirectory(prefix="mb-layer-") as tmp:
                target = Path(tmp) / "layer.tar"
                provider.blob(repo, compressed, target, min(size, MAX_LAYER_BYTES))
                if not target.is_file() or target.stat().st_size != size:
                    raise ReleaseRefusal("OCI layer size differs from signed descriptor")
                h = hashlib.sha256()
                with target.open("rb") as stream:
                    for data in iter(lambda: stream.read(1024 * 1024), b""):
                        h.update(data)
                if "sha256:" + h.hexdigest() != compressed:
                    raise ReleaseRefusal("OCI layer digest differs from immutable descriptor")
                _extract_verified_layer(target, root, seen=seen, total=total,
                                        compression=compression)
        if CATALOG not in seen:
            raise ReleaseRefusal("OCI platform image lacks signed catalog")
    return labels, {arch: destination / arch for arch in ARCHES}


def _compare_full_architectures(roots: Mapping[str, Path]) -> None:
    a = roots["amd64"] / "platform"
    b = roots["arm64"] / "platform"
    if not a.is_dir() or not b.is_dir():
        raise ReleaseRefusal("missing full-feed platform package directories")
    for suffix in ("channels/stable", "packages"):
        left, right = a / suffix, b / suffix
        if not left.is_dir() or not right.is_dir():
            raise ReleaseRefusal("incomplete full-feed package closure across architectures")
        names_a = {p.name for p in left.iterdir()}
        names_b = {p.name for p in right.iterdir()}
        if names_a != names_b:
            raise ReleaseRefusal("full-feed architecture package sets differ")
        for name in names_a:
            l, r = left / name, right / name
            if not l.is_file() or not r.is_file() or l.is_symlink() or r.is_symlink():
                raise ReleaseRefusal("nonregular full-feed architecture package")
            if l.stat().st_size != r.stat().st_size:
                raise ReleaseRefusal("full-feed architecture package sizes differ")
            with l.open("rb") as stream, r.open("rb") as other:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if chunk != other.read(1024 * 1024):
                        raise ReleaseRefusal("full-feed image architectures disagree")
                    if not chunk:
                        break


@dataclass(frozen=True)
class RegistryAdmission:
    pair: Pair
    full_architectures: tuple[str, ...]
    supervisor_architectures: tuple[str, ...]


def admit_digest_pinned_registry_release(
    candidate_raw: bytes, provider: ReadOnlyRegistry, *,
    keys: Mapping[str, Ed25519PublicKey], now: datetime | None = None,
) -> RegistryAdmission:
    """Validate a candidate against actually fetched immutable OCI blobs.

    No GHCR mutable-tag reads or writes; this is candidate qualification only.
    The caller still needs trusted source CI attestations and release approval.
    """
    candidate = _json(candidate_raw)
    try:
        errors = list(Draft202012Validator(_json(SCHEMA.read_bytes())).iter_errors(candidate))
    except (ValueError, TypeError) as exc:
        raise ReleaseRefusal("invalid candidate schema") from exc
    if errors:
        raise ReleaseRefusal("invalid candidate manifest: " +
                             sorted(errors, key=lambda x: str(x.json_path))[0].message)
    with tempfile.TemporaryDirectory(prefix="mb-readonly-registry-") as tmp:
        base = Path(tmp)
        full_labels, full_roots = _verified_platform_image(
            provider, FULL_REPO, candidate["images"]["full"]["digest"], base / "full")
        supervisor_labels, supervisor_roots = _verified_platform_image(
            provider, SUPERVISOR_REPO, candidate["images"]["supervisor"]["digest"],
            base / "supervisor")
        _compare_full_architectures(full_roots)
        full_index = (full_roots["amd64"] / CATALOG).read_bytes()
        if len(full_index) > MAX_JSON:
            raise ReleaseRefusal("oversized full signed catalog")
        sup_indexes = {}
        for arch in ARCHES:
            file = supervisor_roots[arch] / CATALOG
            if file.stat().st_size > MAX_JSON:
                raise ReleaseRefusal("oversized Supervisor signed catalog")
            sup_indexes[arch] = file.read_bytes()
        pair = admit_candidate_manifest(
            candidate_raw,
            full=Feed(candidate["images"]["full"]["digest"], full_index),
            supervisor=SupervisorFeed(candidate["images"]["supervisor"]["digest"],
                                      sup_indexes),
            full_root=full_roots["amd64"], supervisor_roots=supervisor_roots,
            observed_registry_labels={"full": full_labels, "supervisor": supervisor_labels},
            keys=keys, now=now,
        )
        return RegistryAdmission(pair, tuple(sorted(full_roots)),
                                 tuple(sorted(supervisor_roots)))
