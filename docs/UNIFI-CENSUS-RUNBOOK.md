# UniFi #170 + #228 Broad Leaf census runbook

This runbook is the executable campaign checkpoint for MonitorBox issues #170 and #228. The migration authority remains `SickIcarus-Labs/monitorbox/docs/UNIFI-API-MIGRATION.md`; this file does not supersede it.

## Campaign scope

- Primary: MonitorBox #170.
- Dividend: MonitorBox #228.
- Owner: `owner:unifi-network`.
- Module-only unless a separate provider-blind Core reproducer proves a Core contract gap.
- Do not merge, close either issue, promote a release channel, or claim completion before exact-candidate Broad Leaf physical acceptance.

## Current diagnosis gate

The current repository does not contain an official API-key backend or a committed Broad Leaf API census. The historical legacy topology join is not sufficient evidence for #170, and the original #228 replace-legacy wording is superseded by the dual-backend migration authority.

Before provider implementation, collect a disposable read-only side-by-side census from Monitor against the actual Broad Leaf controller. The result must answer whether the official API exposes authoritative topology evidence for the known infrastructure link without site-name or port-number heuristics.

If authoritative topology evidence is absent, stop #170 implementation rather than guessing. #228 may continue only with explicit capability-gap dispositions under the dual-backend contract.

## Census safety contract

The census runner must:

1. execute on Monitor from the same LAN perspective as MonitorBox;
2. use a disposable container or otherwise leave no credential-bearing state behind;
3. accept secrets only through ephemeral environment/file inputs;
4. never echo or persist API keys, passwords, Authorization headers, cookies, CSRF tokens, or private keys;
5. restrict provider-data collection to read-only requests; the legacy authentication handshake and the existing read-only legacy traffic-flow query are the only POSTs used by the migration census;
6. restrict all requests to the configured controller origin;
7. bound response size, request count, CPU/memory, and request timeout;
8. sanitize output on Monitor before it is copied elsewhere;
9. preserve scalar types and stable synthetic identifiers needed for cross-response joins;
10. remove the disposable census container after collection.

`tools/accept_unifi_api_census.py` is the deterministic safety/coverage regression for this contract and is part of first-party PR CI.

## What the migration census collects

`tools/unifi_api_census_migration.py` requires `preset: "network-api-migration"` and layers migration-specific fan-out over the bounded transport/auth primitives in `tools/unifi_api_census.py`.

For the official API-key path it:

- probes same-origin Integration API `/v1/info` through the configured candidate prefixes and selects only an HTTP-200 JSON response for this census run;
- probes controller-local Integration API schema candidates, including `/proxy/network/api-docs/integration.json`;
- discovers site UUIDs from the API rather than requiring them in the plan;
- captures site device/client/network/WAN/VPN/switch-stack/MC-LAG surfaces;
- fans out bounded device-detail and device-statistics GETs so multiple actual device classes are sampled;
- records both currently observed device-statistics suffix candidates rather than assuming release compatibility.

For the legacy session path it captures the exact provider surfaces MonitorBox currently consumes plus explicit topology evidence:

- `/stat/sysinfo`;
- `/stat/device`;
- `/stat/sta`;
- `/stat/health`;
- `/rest/networkconf`;
- `/vpn/connections`;
- `/topology`;
- the existing read-only `/traffic-flows` query.

It also probes `/api/system` for console-level evidence. HTTP success alone is not treated as capability parity or topology authority.

## Sanitization

Migration-census sanitization is default-deny for arbitrary string values. Provider semantic strings needed to reason about schemas and states, such as application/firmware versions, device model/type/state, connector/media/status, are preserved. Site/user identity strings, IPs, MACs, serials, UUID-style IDs, response secrets, and other arbitrary strings are pseudonymized or redacted.

Cross-response joins remain deterministic:

- equal raw MACs map to equal `<mac:...>` tokens;
- equal provider IDs map to equal `<id:...>` tokens;
- known physical fixture names can be mapped to stable aliases locally before output.

Dynamic UUIDs embedded in request paths are also pseudonymized before the path is written to the artifact. The base collector performs a final exact-secret leak check before `census.json` is written.

## Prepare the local plan on Monitor

Copy the committed example somewhere outside the checkout and edit only local non-secret configuration:

```bash
cp docs/unifi-census-plan.example.json /tmp/unifi-census-plan.json
nano /tmp/unifi-census-plan.json
```

Set `controller.base_url` to the Broad Leaf controller origin. Leave credential **values** out of the file; it contains only the environment-variable names consumed by the disposable runner. Adjust `verify_tls` truthfully for the controller certificate and change the legacy `site` only if Broad Leaf does not use `default`.

The known #170 physical fixture aliases are intentionally present only in this local census plan:

- `Bonus Room` -> `fixture-edge`
- `Aggregation` -> `fixture-core`

Those aliases are evidence labels, not production heuristics and must never be copied into module behavior.

## Run the disposable census on Monitor

From the exact PR #65 checkout:

```bash
bash tools/run_unifi_api_census_container.sh \
  /tmp/unifi-census-plan.json
```

The wrapper silently prompts for:

- Integration API key;
- legacy UniFi username;
- legacy UniFi password.

If those three variables are already exported, the wrapper uses them without printing them. It passes them by environment name to a one-shot `python:3.13-alpine` container, uses host networking for the same LAN perspective as MonitorBox, mounts the repository and plan read-only, mounts only the output directory writable, drops Linux capabilities, enables `no-new-privileges`, bounds CPU/RAM/PIDs, and uses `--rm`.

The wrapper unsets its credential variables on exit and writes only sanitized artifacts:

```text
census.json
CAPABILITY-OBSERVATIONS.md
```

It also creates a `.tar.gz` bundle and prints its SHA-256 when `sha256sum` is available.

## Required evidence review

The sanitized bundle must be reviewed before provider code is changed. Build a capability parity matrix covering:

- exact UniFi Network application version and relevant UniFi OS evidence;
- device inventory/statistics;
- connected clients;
- WAN/network detail;
- VPN/Site Magic-related evidence consumed by MonitorBox;
- traffic/flow/rate evidence;
- switch/port state and metadata;
- LLDP/uplink/topology/peer-port evidence;
- discovery/adoption evidence.

Classify each current MonitorBox dependency as one of:

- official API equivalent;
- official API different but sufficient normalized truth;
- official API missing/insufficient;
- legacy-only;
- no longer required by current MonitorBox architecture.

Do not silently drop a current capability.

## #170 decision gate

For the known physical `fixture-edge Port 9 <-> fixture-core` link, determine whether the official API contains authoritative provider evidence proving the infrastructure relationship without names or port-number heuristics.

Possible dispositions:

1. authoritative equivalent exists: normalize it and implement the existing required/recommended policy contract;
2. authoritative evidence exists in a different shape: adapt provider normalization to that actual schema;
3. no authoritative equivalent exists: stop #170 implementation rather than guessing, and explicitly decide whether topology remains a narrowly bounded legacy read-only capability while other #228 surfaces use the official backend.

Adjacent ordinary access/unknown ports remain negative controls and must not become preselected merely because the known infrastructure link is fixed.

## Fixture handoff

After review, commit only the minimal synthetic/sanitized shapes required for deterministic Test Lab coverage. Do not commit the broad physical census bundle wholesale unless every field has been reviewed and there is a specific durable need.

Tests should pin:

- official and legacy normalized equivalence where both have authority;
- additional unknown fields;
- optional endpoint/field disappearance;
- required schema incompatibility;
- provider/auth loss;
- reconnect/restart;
- Network-version change with successful capability probes;
- authoritative infrastructure classification when supported;
- ordinary access/unknown ports remaining optional;
- ambiguous/missing topology authority failing closed.

## Implementation after the gate

Once the census is reviewed:

1. resolve the #170 topology decision from authoritative provider evidence;
2. implement one normalized UniFi provider with explicit `api_key` and `username_password` backends and no silent fallback;
3. add startup/reconnect Network-version and capability/schema probes with bounded capability-local failure;
4. port only capabilities proven sufficient by the census, with explicit dispositions for gaps;
5. implement #170 only from the proven topology authority;
6. add deterministic sanitized fixtures and targeted regressions;
7. stage the next immutable UniFi semantic/build release under `VERSIONING.md`;
8. require exact-head first-party/module acceptance;
9. publish only through the signed dev path when authorized;
10. perform Broad Leaf physical acceptance against that exact candidate.

Do not merge PR #65, close #170/#228, or promote beta/latest/stable before the final physical gate passes.
