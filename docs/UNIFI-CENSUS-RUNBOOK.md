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
5. restrict provider-data collection to read-only requests (the legacy authentication handshake may use its existing login POST solely to establish the read-only session);
6. restrict all requests to the configured controller origin;
7. bound response size and request timeout;
8. sanitize output on Monitor before it is copied elsewhere;
9. preserve scalar types and stable synthetic identifiers needed for cross-response joins;
10. remove the disposable census container after collection.

## Required evidence

Collect the exact UniFi OS/Network version, controller-exposed official API schema/description when available, endpoint/status behavior, device/client/WAN/VPN/traffic/port/discovery payload structures, and topology/LLDP/uplink/peer-port evidence for multiple object classes.

For #170 specifically, preserve sanitized evidence for both sides of the known Bonus Room Port 9 <-> Aggregation infrastructure link and adjacent ordinary access/unknown control ports. Stable synthetic aliases are acceptable and preferred over leaking unrelated site identity.

## Handoff artifacts

The sanitized bundle should contain:

- machine-readable response JSON;
- endpoint/status metadata;
- exact relevant Network version;
- controller-exposed API schema/specification if retrievable;
- a capability parity matrix classifying current MonitorBox dependencies as official-equivalent, different-but-sufficient, missing/insufficient, legacy-only, or no-longer-required;
- the #170 topology decision and the exact sanitized evidence supporting it.

Only the minimal sanitized response shapes needed for deterministic regression tests should later be committed as Test Lab fixtures.

## Implementation after the gate

Once the census is available:

1. resolve the #170 topology decision from authoritative provider evidence;
2. implement one normalized UniFi provider with explicit `api_key` and `username_password` backends and no silent fallback;
3. add startup/reconnect Network-version and capability/schema probes with bounded capability-local failure;
4. port only capabilities proven sufficient by the census, with explicit dispositions for gaps;
5. implement #170 only from the proven topology authority;
6. add deterministic sanitized fixtures and targeted regressions;
7. stage the next immutable UniFi semantic/build release under `VERSIONING.md`;
8. require exact-head first-party/module acceptance and then Broad Leaf physical acceptance of that exact candidate.
