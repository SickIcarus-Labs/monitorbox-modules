# UI49 (#104 primary / #103 dividend): spatial dashboard candidate

Pre-implementation scope declaration (2026-09-26).

- **Primary: #104** — responsive two-dimensional arrangement of variable-height homepage cards; one intentional move between columns with visible preview, undo, non-drag/keyboard fallback, snapshot persistence, deterministic legacy migration.
- **Dividend: #103** — the header's asynchronous Unknown/Healthy mismatch on the *same UI homepage*; reconcile from the canonical authoritative state and guard against out-of-order responses. Dashboard browser tests and source packaging are shared. No Core or provider-module changes.
- Backlog scan: open UI #103, #104, #94, #91, #85 and release-tooling #102; #88 is Backup/Restore-owned. #94/#91's broader composer work is already physically accepted in UI48; #85/#88 are unrelated or cross-module; #102 is release infrastructure, not UI-owned. #103 is the bounded current UI/dashboard bug.

## Candidate interaction and packing contract (physical iPad review required)
- An explicit **Arrange cards** mode inside Configuration → Dashboard → Cards shows a spatial three-lane preview. Card handles alone start touch-pointer drag; regular card inspection remains unchanged outside Arrange mode. Move-left/right/up/down buttons and a source/destination menu are the non-drag and keyboard alternatives.
- Store a stable 0–2 **preferred desktop lane** on individual selected card records, with their order in the existing cards array defining the in-lane order. A three-column landscape viewport honors all three lanes; portrait deterministically combines lanes 1 and 2, keeping lane 0 separate; a narrow viewport concatenates lanes in a documented consistent reading order. No absolute pixel positions, widths or hidden inventories.
- Legacy UI41/42/48 schema v1/v2/v3 reads without rewriting; the default/unarranged UI48 shortest-column behavior remains until an explicit arrangement. A deliberate edit upgrades a compatible saved layout to UI-owned schema v4. Unknown future layouts fail closed. Hidden or currently missing cards keep saved IDs and preferred lane.
- Height changes reflow *within* a lane via natural DOM layout; do not repack live cards on each telemetry sample (which causes placement jumps). Placement preview shows natural-height synthetic content from the same selected display items; no full re-render on drag frame.
- Arrange-mode **Undo, Done, Cancel** operate on local working preferences. The existing authenticated revision/hash Validate → Preview → Apply remains the only persistence path. One Apply makes one retained revision. Snapshot/backup must round-trip contents and placement together.
- #103 fix is a guarded UI-only site-status refresh from current `/api/v2/state`, respecting request sequence and data freshness, never fabricating healthy state.

## Qualification / release gates
- New immutable successor UI **1.13.0 build49** from accepted UI48; preserve UI48 and all historical signed packages and channels.
- Targeted policy, pointer/keyboard geometry, out-of-order header response, 24-row geometry and exact package/staging checks; then full module CI, real managed-loader/paired accepted Core test and deterministic browser acceptance.
- Publish signed **dev only** through the existing authorized pipeline after exact-head green. No beta/stable/latest changes, no automatic merge or issue closure, no remote production mutations.
- **Physical Broad Leaf iPad signoff** on the backed-up populated appliance, including Power below Arrrrr2 one-move check, landscape/portrait, legacy layout migration and A/B snapshot restore, remains mandatory. Validate this interaction/packing model on real iPad before final schema approval.
