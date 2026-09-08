#!/usr/bin/env python3
"""Static acceptance for trusted pre-stable module publication topology."""

from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/module-channel-publish.yml")
SIGNER = Path("tools/build_repository.py")


def require(text: str, needle: str) -> None:
    if needle not in text:
        raise SystemExit(f"missing module channel contract marker: {needle}")


def forbid(text: str, needle: str) -> None:
    if needle in text:
        raise SystemExit(f"forbidden module channel contract marker: {needle}")


def main() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    signer = SIGNER.read_text(encoding="utf-8")

    for marker in (
        'workflows: ["First-party module acceptance"]',
        "github.event.workflow_run.conclusion == 'success'",
        "/publish-dev",
        "/promote-beta",
        "/yank-dev",
        '"Module release policy" "First-party module acceptance"',
        "needs.resolve.outputs.candidate_sha",
        "candidate/catalog.source.json",
        "candidate/packages",
        "MONITORBOX_MODULE_SIGNING_KEY",
        "python ../trusted/tools/release_policy.py validate",
        "python trusted/tools/build_repository.py",
        '--repository-id "$repository_id"',
        'repository_id="official-$MODE"',
        'repository_id="official-dev"',
        'target="trusted/channels/$channel"',
        "git -C trusted add channels",
    ):
        require(workflow, marker)

    # The signing job may inspect candidate source and staged bytes, but it must never
    # execute candidate-owned stagers/builders while the signing secret is in scope.
    publish = workflow.split("  publish:\n", 1)[1]
    forbid(publish, "run-intents")
    require(publish, "Revalidate staged candidate without executing candidate code")

    for marker in (
        '"official": "MonitorBox Official"',
        '"official-beta": "MonitorBox Official Beta"',
        '"official-dev": "MonitorBox Official Dev"',
        'parser.add_argument(\n        "--repository-id"',
    ):
        require(signer, marker)

    print("module channel publication topology: PASS")


if __name__ == "__main__":
    main()
