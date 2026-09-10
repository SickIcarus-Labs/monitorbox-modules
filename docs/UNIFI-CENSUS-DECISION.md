# Broad Leaf UniFi API census decision — #170/#228

Sanitized physical census captured from Monitor on 2026-09-10. No production credentials or raw site identity are committed here.

## Qualified provider version

- UniFi Network application: `10.6.101`
- Official Integration API prefix: `/proxy/network/integration`
- Official schema: `/proxy/network/api-docs/integration.json`

The census sanitizer did not preserve an exact UniFi OS version, so no OS version is asserted here.

## Capability disposition

| MonitorBox dependency | Official API observation | Legacy observation | Disposition |
| --- | --- | --- | --- |
| Network application/version | `/v1/info` | `stat/sysinfo` | Official equivalent |
| Device inventory | `/v1/sites/{siteId}/devices` | `stat/device` | Official equivalent after normalization |
| Device statistics | `/v1/sites/{siteId}/devices/{deviceId}/statistics/latest` | embedded/device statistics | Official different but sufficient for supported device-rate/system telemetry |
| Connected clients | `/v1/sites/{siteId}/clients` | `stat/sta` | Official equivalent after normalization |
| Networks | `/v1/sites/{siteId}/networks` | `rest/networkconf` | Official sufficient for network inventory; legacy retains richer configuration-only fields |
| WAN inventory | `/v1/sites/{siteId}/wans` | `stat/health` + network configuration | Official exposes inventory only; legacy remains authoritative for current health detail |
| Site-to-site VPN inventory | `/v1/sites/{siteId}/vpn/site-to-site-tunnels` | network configuration + `/vpn/connections` | Official exposes identity/type only; legacy remains authoritative for current operational status detail |
| Switch port state | device detail `interfaces.ports` | `stat/device.port_table` | Official different but sufficient for basic per-port link/speed state |
| Physical topology / peer-port identity | **not exposed** | `/topology` + `stat/device.uplink` | **Legacy-only authoritative capability** |
| Detailed traffic flows | no Integration API endpoint | `/traffic-flows` read query | **Legacy-only capability** |

No capability is silently dropped. Backend/capability selection must be explicit and observable.

## #170 decision gate: disposition C

The official API is insufficient to prove the physical port pair required by #170. Its adopted-device detail exposes only the upstream **device** identifier. The controller-exposed OpenAPI defines the device-uplink overview with only `deviceId`, and exposes no topology, LLDP, or neighbor endpoint.

The legacy API does expose authoritative physical topology. The sanitized census contains a provider edge with:

- child/edge device: `<alias:fixture-edge>` / stable synthetic MAC identity;
- child port: `9`;
- parent/core device: `<alias:fixture-core>` / stable synthetic MAC identity;
- parent port: `15`;
- link type: wired;
- rate: `10000 Mbps`.

The same relationship is independently present in legacy `stat/device` as the child uplink tuple (`port_idx`, `uplink_mac`, `uplink_remote_port`). Adjacent ordinary/unknown ports do not have this topology relationship.

Therefore #170 must use a narrowly bounded, explicit legacy topology read path. It must not infer infrastructure role from switch names, port numbers, speed, connector type, link state, or the fact that the official API names an upstream device.

## #228 backend contract from this census

Implement one normalized provider with two explicit primary auth modes:

- `auth_mode: api_key` — official Integration API for supported normalized capabilities;
- `auth_mode: username_password` — existing legacy session backend.

Where `api_key` mode needs a capability proven legacy-only (physical topology/recommendation authority, detailed traffic flows, and current rich WAN/VPN operational detail), it may use a separately configured **explicit legacy-read companion**. That companion is not fallback: failure/unavailability must remain visible and degrade only the dependent capability to provider/dependency unknown/optional truth. The official backend must never silently switch wholesale to legacy session auth.

This decision is the implementation authority for PR #65 unless later physical evidence supersedes it.
