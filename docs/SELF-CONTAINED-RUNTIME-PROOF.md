# Self-contained Python/Node runtime proof (#112 / Core #419)

**Status: unreleasable candidate only.** Stacked on signed candidate publisher PR #115, which depends on index contract PR #113. This work does not modify the existing 2.x catalogs or accepted Broad Leaf deployment.

The successor's fixed scaffold is a statically linked native executable in a minimal image: **no Python or Node is bundled into the scaffold image**. A runtime package must therefore contain the interpreter and sufficient OS/ABI dependencies to execute without a distro filesystem. A plain Debian-linked binary copied into scratch is not sufficient.

The packaging prototype uses architecture-native upstream Python 3.13 and Node 24 Bookworm images and collects the Python standard library, ELF loader, executable, dynamically linked shared-library closure and CA trust bundle. A runtime is launched by its **own bundled loader** with the explicit `--library-path` recorded in its manifest. The format uses separate immutable runtime versions and architecture metadata under the signed platform catalog contract.

Both ZIPs are deliberately `release_eligible:false` (`packaging_stage: unpinned-upstream-runtime-proof`). This phase uses upstream image *tags* rather than reviewed immutable digests and has not qualified CVEs, third-party Core wheel closure, signed production feeds, runtime upgrade/rollback or module process integration. A publisher must independently reject unapproved runtime/scaffold-manager ZIPs; a signed catalog alone is not proof of deployment eligibility.

Dedicated CI tests native AMD64 and ARM64 builds. On each architecture, it imports **only the extracted runtime archive into an otherwise empty scratch image** with unprivileged user and read-only root. The Python interpreter must load SSL and CA certificates, SQLite, ctypes, hashlib and zlib. Node 24 must run builtin crypto. Synthetic unit tests check deterministic archive bytes, symlink escape prevention and missing shared-library detection. No production key, credential or signed release is used.

**Not yet satisfied:** pin exact upstream image digests and record provenance; review bundled glibc/OpenSSL/CA updates; preserve exact ELF ABI and safe extraction in the native Go scaffold; package third-party pinned Core/Agent wheels (aiohttp, cryptography, PyYAML and dnspython); qualify per-module interpreter isolation and exact-version selection; stage and activate a real signed software generation with persistent-state rollback. Old source-only Core #429 remains explicitly unreleasable until those gates pass.
