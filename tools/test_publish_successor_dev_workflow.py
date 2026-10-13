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
    assert list(parsed["on"]) == ["workflow_dispatch", "issue_comment"]
    assert parsed["on"]["issue_comment"]["types"] == ["created"]
    inputs = parsed["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "confirmation", "core_source_sha", "expected_dev_full", "unsigned_candidate_digest",
    }
    for value in inputs.values():
        assert value["required"] == "true"
    jobs = parsed["jobs"]
    assert set(jobs) == {"resolve", "unsigned", "publish"}
    assert jobs["unsigned"]["needs"] == "resolve"
    assert jobs["publish"]["needs"] == ["resolve", "unsigned"]
    guard = jobs["resolve"]["if"]
    assert "github.ref == 'refs/heads/main'" in guard
    assert "github.actor == 'SickIcarus'" in guard
    assert "publish-v3-dev-core-manager" in guard
    assert "publish-v3-dev-agent" in guard
    assert "concurrency" not in parsed
    assert "pull_request" not in parsed["on"]
    assert "github.event.comment.user.login == 'SickIcarus'" in guard
    assert "github.event.issue.number == 195" in guard
    assert "!github.event.issue.pull_request" in guard
    resolver = jobs["resolve"]["steps"][0]["run"]
    assert 'jq -r ' + "'.comment.body // empty'" + ' "$GITHUB_EVENT_PATH"' in resolver
    assert 'test "$action" = "/publish-v3-dev-core-manager"' in resolver
    assert 'test "$action" = "/publish-v3-dev-agent"' in resolver
    assert '[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]]' in resolver
    assert '[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]' in resolver
    assert '[[ "$unsigned_digest" =~ ^sha256:[0-9a-f]{64}$ ]]' in resolver


def test_unsigned_builder_consumes_only_digest_pinned_oci_without_private_pat():
    unsigned = _parsed()["jobs"]["unsigned"]
    steps = unsigned["steps"]
    raw = PATH.read_text("utf-8")
    assert "MONITORBOX_CORE_SOURCE_READ_TOKEN" not in raw
    assert "repository: SickIcarus-Labs/monitorbox" not in raw
    assert "gh api repos/SickIcarus-Labs/monitorbox" not in raw
    assert "build_successor_dev_delta.py" not in raw
    assert "MONITORBOX_PLATFORM_SIGNING_KEY" not in str(unsigned)
    assert unsigned["permissions"]["packages"] == "read"
    assert unsigned["env"]["UNSIGNED_DIGEST"] == "${{ needs.resolve.outputs.unsigned_digest }}"
    assert any("docker/login-action@v4" == step.get("uses") and
               step["with"]["password"] == "${{ github.token }}" for step in steps)
    read = next(x["run"] for x in steps
                if x.get("name") == "Verify exact public Dev baseline and immutable unsigned OCI digest")
    assert '"$STAGING@$UNSIGNED_DIGEST"' in read
    assert 'docker cp "$cid:/unsigned/." "$RUNNER_TEMP/new-packages/"' in read
    admit = next(x["run"] for x in steps
                 if x.get("name") == "Admit exact native ZIP set and Core source provenance")
    assert 'len(packages)==len(expected)' in admit
    assert 'os.environ["RELEASE_KIND"]=="agent"' in admit
    assert 'meta["git_sha"]==os.environ["CORE_SOURCE_SHA"]' in admit
    assert 'hashlib.sha256(file.read_bytes()).hexdigest()==item["sha256"]' in admit


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
        if step.get("name") == "Admit exact native ZIPs and stage unsigned complete Dev closure"
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
    assert 'tag="dev-$RELEASE_KIND-$CORE_SOURCE_SHA-$GITHUB_RUN_ID"' in immutable
    assert "docker buildx build --platform linux/amd64,linux/arm64" in immutable
    assert "imagetools create" not in immutable
    assert any(step.get("name", "").startswith("Verify immutable full Dev image") for step in steps)


def test_multiarch_immutable_readback_uses_platform_manifest_digests():
    """Avoid Docker's multi-platform index digest overwrite with classic image store."""
    steps = _parsed()["jobs"]["publish"]["steps"]
    step = next(x["run"] for x in steps if
                x.get("name") == "Verify immutable full Dev image byte-for-byte on AMD64 and ARM64")
    assert 'docker buildx imagetools inspect "$FULL@$full" --raw' in step
    assert 'for arch in amd64 arm64; do' in step
    assert '.platform.architecture == $arch' in step
    assert 'if length == 1 then .[0] else error(' in step
    assert 'docker pull --quiet --platform "linux/$arch" "$FULL@$platform_digest"' in step
    assert 'docker create --platform "linux/$arch" "$FULL@$platform_digest"' in step
    assert 'docker pull --quiet --platform "linux/$arch" "$FULL@$full"' not in step
    assert 'diff -rq "$RUNNER_TEMP/signed/full/platform" "$RUNNER_TEMP/readback"' in step


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


def test_source_ci_and_auth_are_delegated_to_private_core():
    """Private source never crosses the public repository checkout boundary."""
    raw = PATH.read_text("utf-8")
    assert "MONITORBOX_CORE_SOURCE_READ_TOKEN" not in raw
    # Qualified public application PRs are checked by the trusted resolver.
    # Never grant the release runner private Core access.
    assert "gh api repos/SickIcarus-Labs/monitorbox/pulls/" not in raw
    assert "SickIcarus-Labs/monitorbox/pulls/782" not in raw
    assert "unsigned_candidate_digest" in raw


def test_module_dev_publisher_never_touches_bootstrap_supervisor_registry():
    """First-stage bootstrap remains on Stable; only FULL:dev is changed."""
    raw = PATH.read_text("utf-8")
    assert "monitorbox-successor-supervisor-feed" not in raw
    assert "expected_dev_supervisor" not in raw
    assert "--tag \"$FULL:dev\"" in raw


def test_real_feed_copy_layout_matches_signer_package_verifier_root():
    """Only protected signer reads baseline signed catalogs; staging supplies four ZIPs."""
    steps = _parsed()["jobs"]
    unsigned_raw = str(steps["unsigned"])
    assert 'prior/platform' not in unsigned_raw
    signer = steps["publish"]["steps"]
    baseline = next(x["run"] for x in signer if x.get("name") ==
                    "Verify exact signed full Dev baseline and reuse its packages")
    assert 'mkdir -p "$RUNNER_TEMP/prior/platform"' in baseline
    assert 'docker cp "$cid:/feed/platform/." "$RUNNER_TEMP/prior/platform/"' in baseline
    signed = next(x["run"] for x in signer if x.get("name") ==
                  "Sign only the admitted complete Dev candidate")
    assert '--prior-platform "$RUNNER_TEMP/prior/platform"' in signed
    admitted = next(x["run"] for x in signer if x.get("name") ==
                    "Admit exact native ZIPs and stage unsigned complete Dev closure")
    assert 'root/"prior/platform/packages"' in admitted
    assert 'root/"prior/platform/channels/dev/index.json"' in admitted


def test_only_eligible_release_jobs_compete_for_shared_feed_lock():
    """An unrelated issue comment must not cancel a queued writer before if guards."""
    for filename, writer in (
        ("publish-successor-dev-core-manager.yml", "publish"),
        ("publish-successor-ui58.yml", "publish"),
        ("resume-successor-ui58.yml", "resume"),
    ):
        workflow = yaml.load(
            (PATH.parent / filename).read_text("utf-8"), Loader=yaml.BaseLoader
        )
        assert "concurrency" not in workflow, filename
        job = workflow["jobs"][writer]
        if filename == "publish-successor-dev-core-manager.yml":
            # The downstream signer runs only if owner-gated resolve succeeds.
            assert "resolve" in job["needs"]
            assert "if" in workflow["jobs"]["resolve"]
        else:
            assert "if" in job, filename
        assert job["concurrency"] == {
            "group": "successor-signed-feed-publication",
            "cancel-in-progress": "false",
        }, filename


def test_owner_only_agent_lane_keeps_signer_protected_and_core_lane_unchanged():
    jobs = _parsed()["jobs"]
    guard = jobs["resolve"]["if"]
    assert "github.actor == 'SickIcarus'" in guard
    assert "github.event.issue.number == 195" in guard
    assert "publish-v3-dev-agent" in guard
    assert "publish-v3-dev-core-manager" in guard
    intent = jobs["resolve"]["steps"][0]["run"]
    assert 'case "$action" in' in intent
    assert '/publish-v3-dev-agent) kind=agent' in intent
    unsigned = jobs["unsigned"]
    assert unsigned["env"]["STAGING"] == "ghcr.io/sickicarus-labs/monitorbox-dev-unsigned-core-manager"
    assert unsigned["permissions"]["packages"] == "read"
    assert "MONITORBOX_MODULE_SIGNING_KEY" not in str(unsigned)
    publish = jobs["publish"]
    assert publish["concurrency"]["group"] == "successor-signed-feed-publication"
    assert "changed_ids=frozenset(expected)" in str(publish)
    assert '"com.sickicarus.monitorbox.agent"' in str(publish)
    assert "$FULL:dev" in str(publish)
    assert 'docker buildx imagetools create --tag "$FULL:stable"' not in str(publish)


def test_owner_gated_exact_backup_restore_app_release_uses_existing_signed_dev_feed():
    jobs = _parsed()["jobs"]
    guard = jobs["resolve"]["if"]
    assert "github.actor == 'SickIcarus'" in guard
    assert "github.event.issue.number == 195" in guard
    assert "publish-v3-dev-backup-restore" in guard
    assert "github.ref == 'refs/heads/main'" in guard
    assert "pull_request" not in str(_parsed()["on"].keys())
    unsigned = jobs["unsigned"]
    app = next(s for s in unsigned["steps"]
               if s.get("name") == "Build exact app from reviewed public modules main (no signing key)")
    assert "needs.resolve.outputs.release_kind == 'backup-restore'" in app["if"]
    assert "needs.resolve.outputs.release_kind == 'ui'" in app["if"]
    assert 'test "$(git rev-parse HEAD)" = "$CORE_SOURCE_SHA"' in app["run"]
    assert '("1.0.6", 8)' in app["run"]
    assert '("1.18.4", 62)' in app["run"]
    assert 'UI_ID if kind == "ui" else BACKUP_RESTORE_ID' in app["run"]
    assert 'build_package(record, root, release_eligible=True)' in app["run"]
    assert '"sha256:" + digest == os.environ["UNSIGNED_DIGEST"]' in app["run"]
    assert "MONITORBOX_PLATFORM_SIGNING_KEY" not in str(unsigned)
    pub = jobs["publish"]
    admission = next(x for x in pub["steps"]
                     if x.get("name") == "Admit exact native ZIPs and stage unsigned complete Dev closure")
    assert '("any",) if kind in ("backup-restore","ui")' in admission["run"]
    assert 'rebuilt.read_bytes()==submitted.read_bytes()' in admission["run"]
    assert "changed_ids=frozenset(expected)" in admission["run"]
    assert 'root/"prior/platform/channels/dev/index.json"' in admission["run"]
    assert pub["concurrency"]["group"] == "successor-signed-feed-publication"
    raw = PATH.read_text()
    assert 'docker buildx imagetools create --tag "$FULL:dev"' in raw
    assert 'docker buildx imagetools create --tag "$FULL:stable"' not in raw
    assert 'docker buildx imagetools create --tag "$FULL:beta"' not in raw

def test_protected_dev_ui59_only_publication_is_isolated():
    jobs = _parsed()["jobs"]
    source = PATH.read_text()
    guard = jobs["resolve"]["if"]
    assert "publish-v3-dev-ui" in guard
    assert "github.actor == 'SickIcarus'" in guard
    assert "github.event.issue.number == 195" in guard
    assert "pull_request" not in str(_parsed()["on"].keys())
    publish = jobs["publish"]
    admitted = next(x["run"] for x in publish["steps"]
                    if x.get("name") == "Admit exact native ZIPs and stage unsigned complete Dev closure")
    assert 'expected=({UI} if kind=="ui"' in admitted
    assert 'arches=("any",) if kind in ("backup-restore","ui")' in admitted
    assert 'artifact_id=UI if kind=="ui" else BACKUP_RESTORE' in admitted
    assert 'rebuilt.read_bytes()==submitted.read_bytes()' in admitted
    assert "changed_ids=frozenset(expected)" in admitted
    verify = next(x["run"] for x in publish["steps"]
                  if x.get("name") == "Sign only the admitted complete Dev candidate")
    assert '"com.sickicarus.monitorbox.ui"' in verify
    assert "MONITORBOX_MODULE_SIGNING_KEY" not in str(jobs["unsigned"])
    assert 'docker buildx imagetools create --tag "$FULL:stable"' not in source
    assert 'docker buildx imagetools create --tag "$FULL:beta"' not in source

def test_reviewed_application_pr_may_be_signed_without_merging_candidate_source():
    jobs = _parsed()["jobs"]
    resolver = jobs["resolve"]
    assert resolver["permissions"]["actions"] == "read"
    assert resolver["permissions"]["pull-requests"] == "read"
    assert resolver["permissions"]["contents"] == "read"
    assert resolver["outputs"]["candidate_source"] == "${{ steps.intent.outputs.candidate_source }}"
    intent = resolver["steps"][0]
    assert intent["env"]["GH_TOKEN"] == "${{ github.token }}"
    gate = intent["run"]
    assert 'github.actor == ' not in gate  # protected job-level guard
    assert 'gh api repos/SickIcarus-Labs/monitorbox-modules/pulls/210' in gate
    assert '.head.sha == $sha' in gate
    assert '.head.repo.full_name == "SickIcarus-Labs/monitorbox-modules"' in gate
    assert '.state == "open"' in gate and '.base.ref == "main"' in gate
    assert 'select(.head_sha == $sha and .status == "completed" and .conclusion == "success")' in gate
    for name in (
        "Successor first-party module packaging",
        "Successor UI-only release delta contract",
        "Successor signed platform contract",
        "Successor integrated source and signer contract",
        "Successor signed-feed publication contract",
    ):
        assert f'"{name}"' in gate
    assert 'candidate_source=false' in gate
    assert 'candidate_source=true' in gate
    assert 'echo "candidate_source=$candidate_source"' in gate

    unsigned = jobs["unsigned"]
    app_checkout = next(step for step in unsigned["steps"] if step.get("uses") == "actions/checkout@v7")
    assert app_checkout["with"]["ref"] == "${{ needs.resolve.outputs.core_source_sha }}"
    assert app_checkout["with"]["persist-credentials"] == "false"
    assert unsigned["permissions"]["packages"] == "read"
    assert "MONITORBOX_MODULE_SIGNING_KEY" not in str(unsigned)
    builder = next(x for x in unsigned["steps"] if x.get("name", "").startswith("Build exact app"))
    assert builder["env"]["CANDIDATE_SOURCE"] == "${{ needs.resolve.outputs.candidate_source }}"
    assert '("1.18.6", 64)' in builder["run"]
    assert '("1.0.7", 9)' in builder["run"]
    assert '"sha256:" + digest == os.environ["UNSIGNED_DIGEST"]' in builder["run"]

    signer = jobs["publish"]
    assert signer["env"]["CANDIDATE_SOURCE"] == "${{ needs.resolve.outputs.candidate_source }}"
    signed_checkout = next(x for x in signer["steps"] if x.get("uses") == "actions/checkout@v7")
    assert "ref" not in signed_checkout.get("with", {})  # trusted main only
    admit = next(x["run"] for x in signer["steps"] if x.get("name") ==
                 "Admit exact native ZIPs and stage unsigned complete Dev closure")
    assert 'os.environ["CANDIDATE_SOURCE"]=="true"' in admit
    assert "z.testzip() is None" in admit
    assert "meta[\"artifact_id\"]==artifact_id" in admit
    assert 'expected_version,expected_build=(("1.18.6",64)' in admit
    assert "rebuilt.read_bytes()==submitted.read_bytes()" in admit  # normal main path unchanged
    assert "stage_unsigned_dev_delta(" in admit
    assert "MONITORBOX_PLATFORM_SIGNING_KEY" not in str(unsigned)

