# Broad Leaf UniFi provider census outcome — #170/#228

Sanitized physical census captured from Monitor on 2026-09-10 against UniFi Network `10.6.101`. No production credentials or raw site identity are committed here.

## Final decision

**Do not implement the official Integration API backend. Continue using the existing legacy username/password session backend with a dedicated read-only UniFi service account.**

Issue #228 was intentionally an evidence-driven experiment. The census demonstrated that the official API does not add a MonitorBox monitoring capability that the legacy provider lacks, while several capabilities MonitorBox already uses remain richer or legacy-only. A dual-backend implementation would therefore add configuration, code, credentials, testing permutations, and new failure modes without allowing the legacy backend to be retired.

There is also no least-privilege benefit for Broad Leaf. The official API exposes write-capable operations; introducing a credential for that surface would increase credential impact for MonitorBox without a compensating monitoring benefit. The existing UniFi service account can instead remain constrained to read-only access.

Reconsider an official API backend only if a future UniFi release can replace the legacy provider without material capability loss **and** can be granted an equivalently narrow read-only credential scope.

## Capability findings

| MonitorBox dependency | Official API | Legacy provider | Decision |
| --- | --- | --- | --- |
| Network application/version | available | available | keep legacy |
| Device inventory/statistics | available | available, richer current shape | keep legacy |
| Connected clients | available | available | keep legacy |
| Networks | available | available, richer configuration detail | keep legacy |
| WAN state | inventory available | richer health/operational detail | keep legacy |
| VPN state | inventory available | richer configuration/operational detail | keep legacy |
| Switch port state | basic state available | richer `port_table` semantics | keep legacy |
| Physical topology / peer-port identity | **not exposed authoritatively** | `/topology` + `stat/device.uplink` | **legacy-only authority** |
| Detailed traffic flows | no equivalent observed | `/traffic-flows` | **legacy-only capability** |

## #170 authoritative topology evidence

The official API identifies an upstream device but does not expose the authoritative local/remote switch-port pair required for expectation-aware port recommendation.

The legacy API does expose that relationship. The sanitized census proves the known physical fixture as:

- child/edge device: `fixture-edge`;
- child port: `9`;
- parent/core device: `fixture-core`;
- parent port: `15`;
- link type: wired;
- rate: `10000 Mbps`.

The same relationship is independently represented in legacy `stat/device` through the child uplink tuple (`port_idx`, `uplink_mac`, `uplink_remote_port`). Adjacent ordinary/unknown ports do not carry that topology relationship.

Therefore #170 should classify infrastructure ports from authoritative legacy topology identity, not from switch names, port numbers, speed, connector type, or other Broad Leaf-specific heuristics. Ordinary/unknown access ports remain optional.

## Implementation authority

For PR #65 and current MonitorBox UniFi work:

- supported auth/backend remains `username_password` via the existing legacy session path;
- use a dedicated read-only UniFi service account;
- retain existing auth-loss/backoff protections;
- add only the bounded legacy topology normalization needed to solve #170;
- preserve provider-loss truth (`unknown` / `monitor_dependency`);
- do not add official API-key configuration, dual-backend behavior, or API-key secrets;
- do not merge or close #170 until exact-candidate Broad Leaf physical acceptance proves the real infrastructure link is Recommended while ordinary/unknown ports remain Optional.
