# Successor first-party portable configuration contracts

Tracks original modules #120 and [Core #418](https://github.com/SickIcarus-Labs/monitorbox/issues/418). **Status (2026-10-09):** this is the signed first-party *module settings/credential-reference* contract, not the complete installed-generation/ZIP archive manifest. The **12** identities in this early portable-settings manifest comprise **Core + Agent + ten application/integration modules**, and exclude the separately signed **Supervisor**, which is the **thirteenth** first-party appliance module. The **10** families in `platform/modules/first-party-successor-v1.json` are a separate **application/module source requalification plan**, not the complete 13-module installed inventory. Python/Node runtime packages and architecture-specific package artifacts also belong in the exact signed Full ZIP closure but are **not extra module identities**. The administrator password/verifier is **destination-owned**, not module-owned portable authority, under accepted [P0 #691](https://github.com/SickIcarus-Labs/monitorbox/issues/691); legacy verifier-bearing Config JSON compatibility and runtime edits remain in progress. Keep the signed module-owned provider-credential reference contract distinct from export of appliance administrator authentication. Never infer currently working Full ZIP restore solely from this module manifest.

The successor platform treats portable configuration semantics as package-owned authority. Every selectable first-party module package must contain exactly one `portable-config.json` member. Because the complete package ZIP is digest-pinned and Ed25519-verified, this member is covered by the same immutable package signature as the module implementation.

## Production source authority

`platform/portable/first-party-contracts-v1.json` is the checked-in first-party source authority used by module builders and the successor candidate publisher. It contains no operator credentials, administrator verifier, site addresses or private Broad Leaf fixture data.

The initial **portable module-settings** authority contains **12** module identities—Core, Agent, and the ten application/integration modules below. The separately signed **Supervisor is the 13th appliance module**, but does not contribute a portable-config record in this initial manifest:

- Core
- Agent
- Backup/Restore
- Configuration Bootstrap
- HTTP
- NUT
- Portainer
- Scrypted
- SNMP
- UI
- UniFi
- WOL

Each record declares the current module settings schema, every historical settings schema the current release genuinely accepts, any complete declarative migration chain, and module-owned credential-reference rules. Historical settings schemas are not invented merely because an older package version existed.

The current Broad Leaf portable-v1 migration input uses the established `*.settings/v1` schema for all twelve modules, so this first production authority accepts those current v1 schemas directly and declares no fictional old-to-new migration.

## Embedded package member

`tools/portable_contracts.py` deterministically materializes the package member by combining the checked-in semantic authority with the exact outer artifact ID, semantic version and build:

- contract schema 1;
- exact artifact ID/version/build;
- `monitorbox.portable/v1`;
- current and accepted settings schemas;
- migration protocol 1;
- optional bounded `settings_migrations`;
- optional bounded `credential_references`.

The candidate publisher independently opens every module ZIP, requires exactly one bounded `portable-config.json`, validates it against the production source authority and exact outer package identity, and only then signs the candidate artifact.

The signed platform catalog does not accept an unsigned source-inventory assertion of portable capability. Instead, the publisher derives `portable_config` directly from the verified package member and places that capability inside the signed catalog envelope.

## Credential references

Portable credential values remain in the top-level operator-owned credential map. Modules declare only where credential IDs are referenced from their settings and the minimum required payload shape.

For the accepted v1 Broad Leaf configuration:

- Agent consumes values under `/runtime/credential_secret_refs/*` as one credential ID per resolved value.
- Portainer, Scrypted, SNMP and UniFi consume arrays at `/credentialRefs`.
- Referenced records require a non-empty string field named `value`.
- Those reference paths are not globally required: a legitimate new site may configure the module without those credentials until the corresponding provider is configured.

Core validates only these signed declarations; it does not scan arbitrary JSON for password/token-looking field names.

## Migration protocol

Protocol 1 remains deliberately declarative and bounded. Supported settings operations are `move`, `remove_if_present` and `set_default`. Every accepted non-current schema must have one complete acyclic path to the current schema. Arrays, wildcards in settings migration paths, arbitrary code and root replacement are outside protocol 1.

## Separation from 2.x

This authority applies only to independently built successor packages. Existing 2.x signed catalogs and immutable package bytes are not rewritten, relabeled or modified. Adding contract authority is not permission to publish or promote successor artifacts, and it does not mutate Broad Leaf.

The next package-building slice must embed the materialized member in each real successor package. Pristine import acceptance remains gated on those real signed packages plus the Core importer/activation transaction.
