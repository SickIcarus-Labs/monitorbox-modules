#!/usr/bin/env python3
"""Build UniFi Network v1.0.11 build 12 over immutable build-11 dev history."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_unifi as base
import build_first_party_unifi_b11 as previous

MODULE_ID="com.sickicarus.monitorbox.unifi"
MODULE_VERSION="1.0.11"
MODULE_BUILD=12
IMPORT_PACKAGE="monitorbox_unifi_b12"
FILENAME=f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
BUILD12_SOURCE_BLOBS={"recommendation_relationship.py":"4df4c5f0a072d1e5cbf097187e1cd22ad6d1ef46"}


def _git_blob_sha(payload:bytes)->str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii")+payload).hexdigest()


def _source_files(root:Path)->dict[str,bytes]:
    result=dict(previous._source_files(root))
    source_root=root/"sources"/"unifi"/"1.0.11-build12"
    actual={p.name for p in source_root.iterdir() if p.is_file()}
    if actual!=set(BUILD12_SOURCE_BLOBS):
        raise SystemExit(f"UniFi build-12 delta shape changed: {sorted(actual)}")
    for name,expected in BUILD12_SOURCE_BLOBS.items():
        payload=(source_root/name).read_bytes()
        if _git_blob_sha(payload)!=expected:raise SystemExit(f"UniFi build-12 source blob changed for {name}")
        result[name]=payload
    return result


def _rewrite_source(name:str,payload:bytes)->bytes:
    text=previous._rewrite_source(name,payload).decode("utf-8")
    if name in {"__init__.py","runtime.py"}:
        old=f'entrypoints={{"integration": "{previous.IMPORT_PACKAGE}:PLUGIN"}}'
        new=f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'
        if text.count(old)!=1:raise SystemExit(f"UniFi build-12 entrypoint seam changed in {name}")
        text=text.replace(old,new,1)
    if name=="runtime.py":
        old_version=f'MODULE_VERSION = "{previous.MODULE_VERSION}"'
        old_build=f"MODULE_BUILD = {previous.MODULE_BUILD}"
        if text.count(old_version)!=1 or text.count(old_build)!=1:raise SystemExit("UniFi build-12 identity seam changed")
        text=text.replace(old_version,f'MODULE_VERSION = "{MODULE_VERSION}"',1)
        text=text.replace(old_build,f"MODULE_BUILD = {MODULE_BUILD}",1)
    if f"{previous.IMPORT_PACKAGE}:PLUGIN" in text:raise SystemExit(f"UniFi build-12 retained predecessor entrypoint in {name}")
    return text.encode("utf-8")


def _package_files(root:Path)->dict[str,bytes]:
    return {f"{IMPORT_PACKAGE}/{name}":_rewrite_source(name,payload) for name,payload in _source_files(root).items()}


def build(root:Path,output_dir:Path)->Path:
    output_dir.mkdir(parents=True,exist_ok=True)
    payload=base._zip_bytes(_package_files(root))
    target=output_dir/FILENAME;target.write_bytes(payload)
    print(f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} entrypoint={IMPORT_PACKAGE}:PLUGIN")
    return target


def main()->None:
    root=Path(__file__).resolve().parent.parent
    parser=argparse.ArgumentParser();parser.add_argument("--output-dir",type=Path,default=root/"packages")
    args=parser.parse_args();build(root,args.output_dir)

if __name__=="__main__":main()
