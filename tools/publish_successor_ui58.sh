#!/usr/bin/env bash
# Protected GH Actions executor for successor UI58. No local registry overrides.
set -euo pipefail

mode="${1:?expected preflight, publish or promote}"
test "${GITHUB_REPOSITORY:-}" = "SickIcarus-Labs/monitorbox-modules"
test "${GITHUB_REF:-}" = "refs/heads/main"
FULL="ghcr.io/sickicarus-labs/monitorbox-successor-signed-feed"
SUP="ghcr.io/sickicarus-labs/monitorbox-successor-supervisor-feed"
CORE_SHA="595262fd989d7b6aa8d8e986d5a1e6655c8318d5"
PYTHON_SHA="3e4cf4ae9072efff941f35a2b0b20b7b493de4cc"
UI58_SOURCE_SHA="9d4f4eac2bad0a64672a60456737cc5dc306b548"
TAG="ui58-seq10-$UI58_SOURCE_SHA"
OLD_FULL="${EXPECTED_FULL:?expected previous full digest}"
OLD_SUP="${EXPECTED_SUP:?expected previous Supervisor digest}"
ROOT="$RUNNER_TEMP/successor-ui58"
resolve() {
  docker buildx imagetools inspect "$1" | awk '/^Digest:/ {print $2;exit}'
}
assert_stable() {
  test "$(resolve "$FULL:stable")" = "$OLD_FULL"
  test "$(resolve "$SUP:stable")" = "$OLD_SUP"
}
case "$mode" in
  preflight)
    [[ "$OLD_FULL" =~ ^sha256:[a-f0-9]{64}$ ]]
    [[ "$OLD_SUP" =~ ^sha256:[a-f0-9]{64}$ ]]
    assert_stable
    python tools/verify_trusted_successor_signer_snapshot.py
    PYTHONPATH=tools python tools/successor_existing_stable_readonly.py \
      --trust-root trust/official-ed25519-1.pub
    PYTHONPATH=tools python -m unittest -v tools/test_successor_ui_only_release.py
    python -m unittest discover -s tools -p test_successor_first_party_modules.py -v
    # Refuse any unexpected prospective Beta/Dev overwrite *before* signing.
    for channel in beta dev; do
      current="$(resolve "$FULL:$channel" 2>/dev/null || true)"
      if [[ -n "$current" && "$current" != "$OLD_FULL" ]]; then
        echo "::error::Cannot overwrite independent $channel OCI release $current"
        exit 1
      fi
    done
    docker pull --quiet --platform linux/amd64 "$FULL@$OLD_FULL" >/dev/null
    cid="$(docker create --platform linux/amd64 "$FULL@$OLD_FULL")"
    mkdir -p "$ROOT/prior/platform"
    docker cp "$cid:/feed/platform/." "$ROOT/prior/platform/"
    docker rm -f "$cid" >/dev/null
    python - "$ROOT/prior/platform/channels/stable/index.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))["signed"]
assert d["repository_id"]=="official-platform"
assert d["channel"]=="stable" and d["sequence"]==9
assert len(d["artifacts"])==22
ui=[a for a in d["artifacts"] if a["artifact_id"]=="com.sickicarus.monitorbox.ui"]
assert len(ui)==1 and (ui[0]["version"],ui[0]["build"])==("1.17.1",57)
PY
    test "$(find "$ROOT/prior/platform/packages" -maxdepth 1 -type f -name '*.zip' | wc -l)" = 22
    ;;
  publish)
    assert_stable
    test -n "${MONITORBOX_PLATFORM_SIGNING_KEY:-}"
    test -d "$ROOT/prior/platform/packages"
    PYTHONPATH=tools python tools/stage_successor_ui58_release.py \
      --previous "$ROOT/prior/platform/packages" \
      --baseline-index "$ROOT/prior/platform/channels/stable/index.json" \
      --core-source-sha "$CORE_SHA" --output "$ROOT/staged"
    for component in full supervisor-amd64 supervisor-arm64; do
      mkdir -p "$ROOT/staged/$component/tools"
      cp platform/acceptance-feed.Dockerfile "$ROOT/staged/$component/Dockerfile"
      cp tools/successor_feed_server.go "$ROOT/staged/$component/tools/successor_feed_server.go"
    done
    for channel in stable beta dev; do
      python tools/verify_platform_index.py \
        "$ROOT/staged/full/platform/channels/$channel/index.json" \
        --packages-root "$ROOT/staged/full" \
        --trust-root trust/official-ed25519-1.pub \
        --channel "$channel" --min-sequence 10
    done
    # Never overwrite a historical immutable package tag.
    for ref in "$FULL:$TAG" "$SUP:$TAG" "$SUP:$TAG-amd64" "$SUP:$TAG-arm64"; do
      if docker buildx imagetools inspect "$ref" >/dev/null 2>&1; then
        echo "::error::Immutable release already exists: $ref"; exit 1
      fi
    done
    assert_stable
    docker buildx build --platform linux/amd64,linux/arm64 --provenance=false --push \
      --tag "$FULL:$TAG" \
      --label "org.opencontainers.image.source=https://github.com/SickIcarus-Labs/monitorbox-modules" \
      --label "org.opencontainers.image.revision=$GITHUB_SHA" \
      --label "com.sickicarus.monitorbox.core-source=$CORE_SHA" \
      --label "com.sickicarus.monitorbox.python-source=$PYTHON_SHA" \
      --label "com.sickicarus.monitorbox.artifact-class=successor-physical-acceptance-feed" \
      --label "com.sickicarus.monitorbox.catalog-sequence=10" "$ROOT/staged/full"
    for arch in amd64 arm64; do
      docker buildx build --platform "linux/$arch" --provenance=false --push \
        --tag "$SUP:$TAG-$arch" \
        --label "org.opencontainers.image.source=https://github.com/SickIcarus-Labs/monitorbox-modules" \
        --label "org.opencontainers.image.revision=$GITHUB_SHA" \
        --label "com.sickicarus.monitorbox.core-source=$CORE_SHA" \
        --label "com.sickicarus.monitorbox.artifact-class=successor-supervisor-bootstrap-feed" \
        --label "com.sickicarus.monitorbox.catalog-sequence=10" \
        "$ROOT/staged/supervisor-$arch"
    done
    docker buildx imagetools create --tag "$SUP:$TAG" \
      "$SUP:$TAG-amd64" "$SUP:$TAG-arm64"
    NEW_FULL="$(resolve "$FULL:$TAG")"
    NEW_SUP="$(resolve "$SUP:$TAG")"
    [[ "$NEW_FULL" =~ ^sha256:[a-f0-9]{64}$ ]]
    [[ "$NEW_SUP" =~ ^sha256:[a-f0-9]{64}$ ]]
    # Verify BOTH architectures' published contents, not only OCI tag metadata.
    for arch in amd64 arm64; do
      for kind in full supervisor; do
        if [[ "$kind" == full ]]; then
          image="$FULL@$NEW_FULL"; expected="$ROOT/staged/full"
        else
          image="$SUP@$NEW_SUP"; expected="$ROOT/staged/supervisor-$arch"
        fi
        docker pull --quiet --platform "linux/$arch" "$image" >/dev/null
        cid="$(docker create --platform "linux/$arch" "$image")"
        scratch="$ROOT/check-$kind-$arch"
        mkdir -p "$scratch"
        docker cp "$cid:/feed/platform/." "$scratch/"
        docker rm -f "$cid" >/dev/null
        diff -rq "$expected/platform" "$scratch" || {
          echo "::error::OCI published byte mismatch: $kind $arch"; exit 1;
        }
        rm -rf "$scratch"
      done
    done
    export NEW_FULL NEW_SUP
    PYTHONPATH=tools python - <<'PY'
import base64,os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from successor_release_pairing import Feed,SupervisorFeed,verified_pair
root=Path(os.environ["RUNNER_TEMP"])/"successor-ui58/staged"
key=Ed25519PublicKey.from_public_bytes(base64.b64decode(Path("trust/official-ed25519-1.pub").read_text().strip()))
full=(root/"full/platform/channels/stable/index.json").read_bytes()
sup={arch:(root/f"supervisor-{arch}/platform/channels/stable/index.json").read_bytes() for arch in ("amd64","arm64")}
pair=verified_pair(Feed(os.environ["NEW_FULL"], full),SupervisorFeed(os.environ["NEW_SUP"], sup),keys={"official-ed25519-1":key})
assert pair.sequence==10
PY
    # Persist immutable recovery authority BEFORE any moving-tag write.
    python - "$ROOT/promotion-receipt.json" <<'PY'
import json,os,sys
from pathlib import Path
root=Path(os.environ["RUNNER_TEMP"])/"successor-ui58/staged"
intent=json.loads((root/"release-intent.json").read_text())
intent.update({
    "previous_full_digest":os.environ["EXPECTED_FULL"],
    "previous_supervisor_digest":os.environ["EXPECTED_SUP"],
    "target_full_digest":os.environ["NEW_FULL"],
    "target_supervisor_digest":os.environ["NEW_SUP"],
    "source_commit":os.environ["GITHUB_SHA"],
    "status":"immutable-verified-not-promoted"
})
Path(sys.argv[1]).write_text(json.dumps(intent,sort_keys=True,indent=2)+"\n")
PY
    echo "Immutable UI58 pair verified. Stable pointers untouched; promotion receipt ready."
    ;;
  promote)
    test -s "$ROOT/promotion-receipt.json"
    export NEW_FULL="$(python -c 'import json,sys;print(json.load(open(sys.argv[1]))["target_full_digest"])' "$ROOT/promotion-receipt.json")"
    export NEW_SUP="$(python -c 'import json,sys;print(json.load(open(sys.argv[1]))["target_supervisor_digest"])' "$ROOT/promotion-receipt.json")"
    python - "$ROOT/promotion-receipt.json" <<'PY'
import json,os,sys
r=json.load(open(sys.argv[1]))
assert r["status"]=="immutable-verified-not-promoted"
assert r["source_commit"]==os.environ["GITHUB_SHA"]
assert r["old_sequence"]==9 and r["new_sequence"]==10
assert r["previous_full_digest"]==os.environ["EXPECTED_FULL"]
assert r["previous_supervisor_digest"]==os.environ["EXPECTED_SUP"]
PY
    test "$(resolve "$FULL:$TAG")" = "$NEW_FULL"
    test "$(resolve "$SUP:$TAG")" = "$NEW_SUP"
    # Stable pair is a two-pointer transaction. It must retain exact old refs.
    # The other channels contain the identical signed baseline release and may
    # only start absent or at the exact expected previous stable image.
    assert_stable
    for channel in beta dev; do
      prior="$(resolve "$FULL:$channel" 2>/dev/null || true)"
      test -z "$prior" || test "$prior" = "$OLD_FULL"
    done
    restore_stable() {
      local f s
      f="$(resolve "$FULL:stable" 2>/dev/null || true)"
      s="$(resolve "$SUP:stable" 2>/dev/null || true)"
      if [[ "$f" == "$NEW_FULL" ]]; then
        docker buildx imagetools create --tag "$FULL:stable" "$FULL@$OLD_FULL" || true
      elif [[ "$f" != "$OLD_FULL" ]]; then
        echo "::error::Unexpected full feed writer. Manual recovery required."
      fi
      if [[ "$s" == "$NEW_SUP" ]]; then
        docker buildx imagetools create --tag "$SUP:stable" "$SUP@$OLD_SUP" || true
      elif [[ "$s" != "$OLD_SUP" ]]; then
        echo "::error::Unexpected Supervisor writer. Manual recovery required."
      fi
      echo "::error::Interrupted publication; verify prior stable pair and review other channel pointers."
    }
    trap restore_stable ERR
    # Put Beta and Dev on this accepted baseline before making Stable current;
    # later channel-specific releases can then advance independently.
    for channel in beta dev; do
      docker buildx imagetools create --tag "$FULL:$channel" "$FULL@$NEW_FULL"
      test "$(resolve "$FULL:$channel")" = "$NEW_FULL"
    done
    docker buildx imagetools create --tag "$SUP:stable" "$SUP@$NEW_SUP"
    test "$(resolve "$SUP:stable")" = "$NEW_SUP"
    docker buildx imagetools create --tag "$FULL:stable" "$FULL@$NEW_FULL"
    test "$(resolve "$FULL:stable")" = "$NEW_FULL"
    test "$(resolve "$SUP:stable")" = "$NEW_SUP"
    # Independently reobserve both newly selected GHCR stable pointers and
    # re-verify every signed ZIP/manager pair from the published OCI layers.
    PYTHONPATH=tools python tools/successor_existing_stable_readonly.py \
      --trust-root trust/official-ed25519-1.pub
    trap - ERR
    {
      echo "### Signed UI58 release"
      echo "Full signed catalog: $FULL@$NEW_FULL"
      echo "Supervisor signed bootstrap catalog: $SUP@$NEW_SUP"
      echo "Sequence 10; 21 unchanged ZIPs; 1 independently versioned UI58 ZIP."
      echo "Stable/Beta/Dev catalogs now point at the accepted UI58 set."
      echo "Scaffold rebuilt: **no**"
    } >> "$GITHUB_STEP_SUMMARY"
    ;;
  *) echo "::error::Invalid publication mode" >&2; exit 2 ;;
esac
