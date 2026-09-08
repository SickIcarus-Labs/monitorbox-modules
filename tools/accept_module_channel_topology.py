#!/usr/bin/env python3
"""Static acceptance for trusted module channel/trunk publication topology."""

from __future__ import annotations

from pathlib import Path


CHANNEL = Path(".github/workflows/module-channel-publish.yml")
MATERIALIZE = Path(".github/workflows/publish.yml")
LEGACY = Path(".github/workflows/publish-broadleaf-runtime-repairs.yml")
SIGNER = Path("tools/build_repository.py")


def require(text: str, needle: str) -> None:
    if needle not in text:
        raise SystemExit(f"missing module channel contract marker: {needle}")


def forbid(text: str, needle: str) -> None:
    if needle in text:
        raise SystemExit(f"forbidden module channel contract marker: {needle}")


def main() -> None:
    channel = CHANNEL.read_text(encoding="utf-8")
    materialize = MATERIALIZE.read_text(encoding="utf-8")
    signer = SIGNER.read_text(encoding="utf-8")

    for marker in (
        'workflows: ["First-party module acceptance"]',
        "github.event.workflow_run.conclusion == 'success'",
        "/publish-dev",
        "/promote-beta",
        "/yank-dev",
        "/promote-stable",
        '"Module release policy" "First-party module acceptance"',
        "needs.resolve.outputs.candidate_sha",
        "candidate/catalog.source.json",
        "candidate/packages",
        "MONITORBOX_MODULE_SIGNING_KEY",
        "python ../trusted/tools/release_policy.py validate",
        "python trusted/tools/build_repository.py",
        '--repository-id "$repository_id"',
        'repository_id="official-dev"',
        'repository_id="official-beta"',
        'repository_id="official"',
        "trusted/channels/stable/catalog.source.json",
        "trusted/channels/beta/catalog.source.json",
        'cp "$source_root/catalog.source.json" "$target/catalog.source.json"',
        'cp "$RUNNER_TEMP/channel-index.json" trusted/index.json',
        "channels: promote cumulative beta to stable",
        "module-repository-write",
    ):
        require(channel, marker)

    # Candidate-owned stagers/builders execute only in the unsigned build job. The
    # signing job can inspect candidate source/staged bytes but never executes them.
    publish = channel.split("  publish:\n", 1)[1]
    forbid(publish, "run-intents")
    require(publish, "Revalidate staged candidate without executing candidate code")

    # Main/trunk materialization must never possess the signing key or write the root
    # stable index. It may commit only catalog source and immutable package bytes.
    require(materialize, "name: Materialize module release source")
    require(materialize, "Prove stable signed authority is untouched")
    require(materialize, "git diff --exit-code HEAD -- index.json")
    require(materialize, "git add catalog.source.json packages")
    require(materialize, "module-repository-write")
    forbid(materialize, "MONITORBOX_MODULE_SIGNING_KEY")
    forbid(materialize, "Build signed repository index")
    forbid(materialize, "git add catalog.source.json packages index.json")

    if LEGACY.exists():
        raise SystemExit("legacy Broad Leaf stable-writing publisher must remain retired")

    for marker in (
        '"official": "MonitorBox Official"',
        '"official-beta": "MonitorBox Official Beta"',
        '"official-dev": "MonitorBox Official Dev"',
        'parser.add_argument(\n        "--repository-id"',
    ):
        require(signer, marker)

    print("module channel/trunk publication topology: PASS")


if __name__ == "__main__":
    main()
