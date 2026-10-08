"""Read-only OCI digest-chain proof for successor platform image labels.

A trusted transport must fetch the EXACT OCI/Docker index, platform manifests,
and config blobs from GHCR by pinned immutable digest. This verifier checks the
cryptographic linkage and yields digest-bound labels for the existing candidate
manifest validator. It does NOT fetch layers, establish package extraction
integrity, authorize publication or write any registry tags.
"""
from __future__ import annotations

import hashlib
import re
from typing import Mapping

from successor_release_pairing import ARCHES, ReleaseRefusal
from verify_platform_index import _parse, VerificationError

OCI_INDEX_TYPES = frozenset({
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
})
IMAGE_MANIFEST_TYPES = frozenset({
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
})
IMAGE_CONFIG_TYPES = frozenset({
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
})


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _check_blob(data: bytes, descriptor: dict) -> None:
    if not isinstance(data, bytes) or not isinstance(descriptor, dict):
        raise ReleaseRefusal("OCI descriptor/blob format is invalid")
    if descriptor.get("digest") != _digest(data) or descriptor.get("size") != len(data):
        raise ReleaseRefusal("OCI descriptor digest/size is not the actual blob")


def _decode(data: bytes) -> dict:
    try:
        value = _parse(data)
    except (VerificationError, ValueError, TypeError) as exc:
        raise ReleaseRefusal("malformed OCI JSON blob") from exc
    if not isinstance(value, dict):
        raise ReleaseRefusal("OCI JSON root must be an object")
    return value


def verify_immutable_oci_index(index_raw: bytes, *,
                               expected_digest: str,
                               platform_manifests: Mapping[str, bytes],
                               platform_configs: Mapping[str, bytes]) -> dict[str, dict[str, str]]:
    """Validate index -> platform manifest -> image config chain, then labels.

    Source bytes must be obtained by a trusted caller from immutable GHCR refs.
    Caller must separately prove verified layers/package roots correspond to
    these image manifests, and independently verify signed catalog ZIPs.
    """
    if not isinstance(index_raw, bytes) or expected_digest != _digest(index_raw):
        raise ReleaseRefusal("OCI index digest does not match pinned image identity")
    if (not isinstance(platform_manifests, Mapping) or
            not isinstance(platform_configs, Mapping) or
            set(platform_manifests) != ARCHES or
            set(platform_configs) != ARCHES):
        raise ReleaseRefusal("OCI evidence must cover exactly amd64 and arm64")

    index = _decode(index_raw)
    if index.get("schemaVersion") != 2 or index.get("mediaType") not in OCI_INDEX_TYPES:
        raise ReleaseRefusal("unsupported OCI multiarchitecture index")
    descriptors = index.get("manifests")
    if not isinstance(descriptors, list) or len(descriptors) != 2:
        raise ReleaseRefusal("OCI index must declare exactly two image platforms")
    by_arch = {}
    for entry in descriptors:
        if not isinstance(entry, dict) or entry.get("mediaType") not in IMAGE_MANIFEST_TYPES:
            raise ReleaseRefusal("invalid OCI platform manifest descriptor")
        platform = entry.get("platform")
        if not isinstance(platform, dict) or platform.get("os") != "linux":
            raise ReleaseRefusal("invalid OCI platform OS")
        arch = platform.get("architecture")
        if arch not in ARCHES or arch in by_arch:
            raise ReleaseRefusal("unexpected/duplicate OCI platform")
        variant = platform.get("variant")
        if variant is not None and not (arch == "arm64" and variant == "v8"):
            raise ReleaseRefusal("unsupported OCI architecture variant")
        by_arch[arch] = entry
    if set(by_arch) != ARCHES:
        raise ReleaseRefusal("incomplete OCI architecture index")

    labels = {}
    for arch in sorted(ARCHES):
        descriptor = by_arch[arch]
        manifest_raw = platform_manifests[arch]
        _check_blob(manifest_raw, descriptor)
        manifest = _decode(manifest_raw)
        if (manifest.get("schemaVersion") != 2 or
                manifest.get("mediaType") != descriptor["mediaType"]):
            raise ReleaseRefusal("image manifest content/type mismatch")
        config_descriptor = manifest.get("config")
        if (not isinstance(config_descriptor, dict) or
                config_descriptor.get("mediaType") not in IMAGE_CONFIG_TYPES):
            raise ReleaseRefusal("image manifest lacks a supported config descriptor")
        layers = manifest.get("layers")
        if not isinstance(layers, list) or not layers:
            raise ReleaseRefusal("OCI image has no verifiable layers")
        for layer in layers:
            if (not isinstance(layer, dict) or
                    not isinstance(layer.get("digest"), str) or
                    re.fullmatch(r"sha256:[0-9a-f]{64}", layer["digest"]) is None or
                    not isinstance(layer.get("size"), int) or layer["size"] <= 0):
                raise ReleaseRefusal("invalid OCI layer descriptor")
        config_raw = platform_configs[arch]
        _check_blob(config_raw, config_descriptor)
        config = _decode(config_raw)
        if config.get("os") != "linux" or config.get("architecture") != arch:
            raise ReleaseRefusal("OCI image configuration platform mismatch")
        internal = config.get("config")
        if not isinstance(internal, dict) or not isinstance(internal.get("Labels"), dict):
            raise ReleaseRefusal("OCI image lacks source-provenance labels")
        if not all(isinstance(k, str) and isinstance(v, str)
                   for k, v in internal["Labels"].items()):
            raise ReleaseRefusal("invalid OCI image labels")
        labels[arch] = internal["Labels"]
    return labels
