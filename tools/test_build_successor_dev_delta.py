"""Build controller only exercises reviewed commands; no network or signer."""
import json
from pathlib import Path
import pytest

from successor_dev_release import DevReleaseRefused
from tools import build_successor_dev_delta as builder


def test_core_checkout_digest_guard_fails_before_build(tmp_path, monkeypatch):
    module = tmp_path / "modules"
    core = tmp_path / "core"
    module.mkdir()
    core.mkdir()
    monkeypatch.setattr(builder.subprocess, "check_output", lambda *a, **kw: "1" * 40)
    def no_call(*a, **kw):
        raise AssertionError("should not run unreviewed package builder")
    monkeypatch.setattr(builder, "_call", no_call)
    with pytest.raises(DevReleaseRefused, match="approved commit"):
        builder.build_unsigned_dev(
            modules_root=module, core_root=core,
            previous_packages=tmp_path,
            previous_dev_index=tmp_path / "index.json",
            output=tmp_path / "staged", trust_root=tmp_path / "pub",
            core_source_sha="f" * 40,
        )
    assert not (tmp_path / "staged").exists()


def test_builder_requires_full_length_commit_and_refuses_overwrite(tmp_path):
    with pytest.raises(DevReleaseRefused, match="source SHA"):
        builder.build_unsigned_dev(
            modules_root=tmp_path, core_root=tmp_path,
            previous_packages=tmp_path, previous_dev_index=tmp_path / "index",
            output=tmp_path / "staged", trust_root=tmp_path / "pub",
            core_source_sha="main",
        )
