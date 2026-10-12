"""Parse and validate the non-executable Dev publisher safety contract."""
from pathlib import Path

import yaml


PATH = Path(__file__).resolve().parents[1] / ".github/workflows/publish-successor-dev-core-manager.yml"


def _parsed():
    parsed = yaml.load(PATH.read_text("utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    return parsed


def test_protected_publisher_is_manual_trusted_main_and_owner_only():
    parsed = _parsed()
    assert list(parsed["on"]) == ["workflow_dispatch"]
    inputs = parsed["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "confirmation", "core_source_sha", "expected_dev_full",
    }
    for value in inputs.values():
        assert value["required"] == "true"
    jobs = parsed["jobs"]
    assert set(jobs) == {"unsigned", "publish"}
    assert jobs["publish"]["needs"] == "unsigned"
    guard = jobs["unsigned"]["if"]
    assert "github.ref == 'refs/heads/main'" in guard
    assert "github.actor == 'SickIcarus'" in guard
    assert "publish-v3-dev-core-manager" in guard
    assert parsed["concurrency"]["cancel-in-progress"] == "false"
    assert parsed["concurrency"]["group"] == "successor-signed-feed-publication"
    assert "pull_request" not in parsed["on"]
    assert "issue_comment" not in parsed["on"]


def test_candidate_build_receives_no_registry_auth_or_signer_secret():
    unsigned = _parsed()["jobs"]["unsigned"]
    steps = unsigned["steps"]
    assert "MONITORBOX_PLATFORM_SIGNING_KEY" not in str(unsigned)
    assert all("docker/login-action" not in step.get("uses", "") for step in steps)
    build_step = next(step for step in steps if step.get("name") == "Build just the four Core and Supervisor ZIPs")
    assert "build_successor_dev_delta.py" in build_step["run"]
    assert "--core-source-sha" in build_step["run"]
    assert "GH_TOKEN" not in unsigned.get("env", {})
    checkout = next(step for step in steps if step.get("name") == "Check out reviewed private Core source (no signing key)")
    assert checkout["with"]["persist-credentials"] == "false"
    assert checkout["with"]["ref"] == "${{ inputs.core_source_sha }}"
    token_steps = [
        step for step in steps
        if "MONITORBOX_CORE_SOURCE_READ_TOKEN" in str(step)
    ]
    assert len(token_steps) == 2


def test_signing_confined_to_protected_job_and_dev_only_promotion():
    job = _parsed()["jobs"]["publish"]
    steps = job["steps"]
    assert not [
        step for step in steps
        if "SickIcarus-Labs/monitorbox" in str(step.get("with", {}))
    ]
    signing = next(step for step in steps if step.get("name") == "Sign only the admitted complete Dev candidate")
    assert signing["env"]["MONITORBOX_PLATFORM_SIGNING_KEY"] == "${{ secrets.MONITORBOX_MODULE_SIGNING_KEY }}"
    assert "sign_successor_dev_stage.py" in signing["run"]
    assert "stage_unsigned_dev_delta(" in next(
        step["run"] for step in steps
        if step.get("name") == "Admit exact four ZIPs and stage unsigned complete Dev closure"
    )
    promotion = next(
        step["run"] for step in steps
        if step.get("name") == "Guarded full Dev promotion with verified readback and rollback"
    )
    assert "trap rollback_dev ERR" in promotion
    assert 'test "$(resolve "$FULL:dev")" = "$EXPECTED_DEV_FULL"' in promotion
    assert 'docker buildx imagetools create --tag "$FULL:dev"' in promotion
    for channel in ("stable", "beta"):
        assert 'imagetools create --tag "$FULL:' + channel + '"' not in promotion
    assert "supervisor-feed" not in promotion
    assert "SUP:dev" not in promotion
    immutable = next(
        step["run"] for step in steps
        if step.get("name") == "Publish immutable full Dev image; leave Stable and Beta untouched"
    )
    assert 'tag="dev-core-$CORE_SOURCE_SHA-$GITHUB_RUN_ID"' in immutable
    assert "docker buildx build --platform linux/amd64,linux/arm64" in immutable
    assert "imagetools create" not in immutable
    assert any(step.get("name", "").startswith("Verify immutable full Dev image") for step in steps)


def test_current_full_dev_baseline_is_verified_before_signing():
    steps = _parsed()["jobs"]["publish"]["steps"]
    names = [step.get("name") for step in steps]
    baseline = "Verify exact signed full Dev baseline and reuse its packages"
    assert baseline in names
    assert names.index(baseline) < names.index("Sign only the admitted complete Dev candidate")
    proof = next(step["run"] for step in steps if step.get("name") == baseline)
    assert 'test "$(resolve "$FULL:dev")" = "$EXPECTED_DEV_FULL"' in proof
    assert 'test -s "$RUNNER_TEMP/prior/channels/dev/index.json"' not in proof or "for channel in stable beta dev;" in proof
    assert "SUP:dev" not in _parsed()["jobs"]["publish"]["env"]
    assert "supervisor-feed:dev" not in PATH.read_text()


def test_core_ci_admission_shell_has_no_dangling_continuation():
    """Catch syntax errors in the manual publisher that PR YAML parsing misses."""
    steps = _parsed()["jobs"]["unsigned"]["steps"]
    admission = next(step["run"] for step in steps if
                     step.get("name") == "Refuse malformed selection or unavailable private read credential")
    last_command = admission.rstrip().splitlines()[-1]
    assert "all($r[];" in last_command
    assert not last_command.rstrip().endswith("\\")
    assert 'gh api "repos/SickIcarus-Labs/monitorbox/actions/runs?' in admission


def test_module_dev_publisher_never_touches_bootstrap_supervisor_registry():
    """First-stage bootstrap remains on Stable; only FULL:dev is changed."""
    raw = PATH.read_text("utf-8")
    assert "monitorbox-successor-supervisor-feed" not in raw
    assert "expected_dev_supervisor" not in raw
    assert "--tag \"$FULL:dev\"" in raw


def test_real_feed_copy_layout_matches_package_verifier_root():
    """The actual GHCR image must be copied under prior/platform, not prior/."""
    steps = _parsed()["jobs"]
    for job_id, fetch_name in (
        ("unsigned", "Verify current signed Dev digest and obtain baseline packages"),
        ("publish", "Verify exact signed full Dev baseline and reuse its packages"),
    ):
        run = next(x["run"] for x in steps[job_id]["steps"] if x.get("name") == fetch_name)
        assert 'mkdir -p "$RUNNER_TEMP/prior/platform"' in run
        assert 'docker cp "$cid:/feed/platform/." "$RUNNER_TEMP/prior/platform/"' in run
        assert '"$RUNNER_TEMP/prior/"' not in run
    build = next(x["run"] for x in steps["unsigned"]["steps"]
                 if x.get("name") == "Build just the four Core and Supervisor ZIPs")
    assert '--previous-packages "$RUNNER_TEMP/prior/platform/packages"' in build
    assert '--previous-dev-index "$RUNNER_TEMP/prior/platform/channels/dev/index.json"' in build
    signed = next(x["run"] for x in steps["publish"]["steps"]
                  if x.get("name") == "Sign only the admitted complete Dev candidate")
    assert '--prior-platform "$RUNNER_TEMP/prior/platform"' in signed
    admitted = next(x["run"] for x in steps["publish"]["steps"]
                    if x.get("name") == "Admit exact four ZIPs and stage unsigned complete Dev closure")
    assert 'root/"prior/platform/packages"' in admitted
    assert 'root/"prior/platform/channels/dev/index.json"' in admitted
