#!/usr/bin/env bash
# Disposable Monitor-side runner for the #170/#228 UniFi API census.
#
# Usage:
#   tools/run_unifi_api_census_container.sh PLAN.json [OUTPUT_DIR]
#
# The plan contains only endpoint/configuration metadata and environment-variable
# names. Credential values are read silently here, passed to the one-shot
# container by environment, then unset when the command exits.

set -u
set -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLAN="${1:-}"
OUT="${2:-}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 2
}

if [[ -z "$PLAN" ]]; then
  fail "usage: $0 PLAN.json [OUTPUT_DIR]"
fi
if ! command -v docker >/dev/null 2>&1; then
  fail "docker is required on Monitor"
fi
if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 is required on Monitor for plan safety preflight"
fi
if ! PLAN="$(readlink -f "$PLAN" 2>/dev/null)"; then
  fail "cannot resolve plan path"
fi
if [[ ! -f "$PLAN" ]]; then
  fail "plan file does not exist: $PLAN"
fi

# Validate path-bearing local configuration before any credential is requested.
# A site identifier is a provider identifier, not a path. Refuse dot segments,
# slash-like escapes, whitespace, and other path syntax instead of relying on
# URL quoting/normalization around the one permitted read-only traffic POST.
if ! python3 - "$PLAN" <<'PY'
import json
import re
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text())
if not isinstance(plan, dict) or plan.get("preset") != "network-api-migration":
    raise SystemExit("plan preset must be network-api-migration")
legacy = plan.get("legacy")
if legacy is not None:
    if not isinstance(legacy, dict):
        raise SystemExit("legacy plan must be an object")
    site = str(legacy.get("site") or "default")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", site):
        raise SystemExit(
            "legacy.site may contain only letters, digits, underscore, or hyphen"
        )
PY
then
  fail "plan safety preflight failed"
fi

if [[ -z "$OUT" ]]; then
  OUT="/tmp/monitorbox-unifi-census-$(date -u +%Y%m%dT%H%M%SZ)"
fi
mkdir -p "$OUT" || fail "cannot create output directory: $OUT"
if ! OUT="$(readlink -f "$OUT" 2>/dev/null)"; then
  fail "cannot resolve output directory"
fi

prompt_secret() {
  local var_name="$1"
  local label="$2"
  local current="${!var_name-}"
  if [[ -n "$current" ]]; then
    return 0
  fi
  local value
  IFS= read -r -s -p "${label}: " value
  printf '\n' >&2
  if [[ -z "$value" ]]; then
    fail "${label} may not be empty"
  fi
  printf -v "$var_name" '%s' "$value"
  export "$var_name"
}

cleanup() {
  unset UNIFI_CENSUS_API_KEY UNIFI_CENSUS_USERNAME UNIFI_CENSUS_PASSWORD
}
trap cleanup EXIT HUP INT TERM

prompt_secret UNIFI_CENSUS_API_KEY "UniFi Integration API key"
prompt_secret UNIFI_CENSUS_USERNAME "Legacy UniFi username"
prompt_secret UNIFI_CENSUS_PASSWORD "Legacy UniFi password"

printf 'Running disposable read-only census from Monitor...\n' >&2
docker run --rm \
  --name monitorbox-unifi-census \
  --network host \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 64 \
  --memory 256m \
  --cpus 1.0 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --user "$(id -u):$(id -g)" \
  --env UNIFI_CENSUS_API_KEY \
  --env UNIFI_CENSUS_USERNAME \
  --env UNIFI_CENSUS_PASSWORD \
  --mount "type=bind,src=$ROOT,dst=/work,readonly" \
  --mount "type=bind,src=$PLAN,dst=/run/plan.json,readonly" \
  --mount "type=bind,src=$OUT,dst=/out" \
  --workdir /work/tools \
  --pull missing \
  python:3.13-alpine \
  python unifi_api_census_migration.py --plan /run/plan.json --output-dir /out
rc=$?

if [[ $rc -ne 0 ]]; then
  fail "census container exited with status $rc"
fi
if [[ ! -s "$OUT/census.json" || ! -s "$OUT/CAPABILITY-OBSERVATIONS.md" ]]; then
  fail "expected sanitized census artifacts were not produced"
fi

archive="${OUT}.tar.gz"
tar -C "$OUT" -czf "$archive" . || fail "failed to create sanitized bundle"
printf 'Sanitized census: %s\n' "$OUT"
printf 'Bundle: %s\n' "$archive"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$archive"
fi
