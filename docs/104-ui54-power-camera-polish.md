# UI54 #104 - Power thresholds and Camera columns

UI53 signed dev immutable. Broad Leaf physical test found input.transfer.high under ordinary measurements and Cameras health left/name right. UI54 1.17.1 build54 classifies high/low transfer thresholds Advanced, preserves raw keys and saved legacy selections, gives known battery/output voltage and apparent/real power human-readable labels, and renders camera name left/health right. Core >=2.7.0 <3.0.0. No monitoring, source identity, preferences, snapshot or automatic dashboard Reset changes. CI: exact-package predecessor immutability, UPS semantic tests, real desktop/iPad/phone browser Camera DOM and Power picker, UI52 bootstrap/Reset parity, first-party, release-policy and Phase2/3/6. Await fresh operator backup and physical acceptance before beta/stable/main promotion.

## Release checkpoint

Trusted-main signed dev already contains immutable UI53 1.17.0 build53; UI54 carries only its own 1.17.1 build54 `patch-polish` release intent, plus unmerged UI52/UI53 source/build dependency files. Exact-head first-party and main-target release-policy gates must pass on the same SHA. Their success may sign and publish official-dev only; no merge, beta/stable promotion, appliance installation or dashboard reset is automatic. The operator performs Broad Leaf iPad acceptance against the signed module.

## Stable source materialization

After operator-reported physical acceptance, the trusted publisher re-signed the exact UI54 dev package into cumulative official-beta without rebuilding. The accepted UI54 package SHA-256 remains `c51119fc0615f8d6108d6f6d6b43745209424e0385637c6853201c8b2742fb14`, signer `official-ed25519-1`. Source PR #110 carries UI52/UI53/UI54 cumulative source. Release PR #111 copies the signed beta's complete exact `catalog.source.json` Git blob and exact existing beta UI54 ZIP blob into the canonical main catalog/package paths. Stable publication must verify the main catalog against signed beta and use beta's original immutable bytes; source materialization alone does not move channels.
