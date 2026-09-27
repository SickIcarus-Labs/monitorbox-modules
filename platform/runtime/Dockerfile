# Candidate-only immutable OCI base and SHA256-locked Debian ABI package.
# Official release still requires immutable apt index and qualified signing.
FROM node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS node-upstream
FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS packer
# CI obtains exact .deb bytes using Debian-signed index SHA256, but Docker
# only installs reviewed local bytes. No apt update/install/network in builder.
COPY tools/freeze_runtime_debian_closure.py /build/freeze_runtime_debian_closure.py
COPY platform/runtime/debian/ /build/debian/
RUN python /build/freeze_runtime_debian_closure.py install --lock-dir /build/debian --archives /build/debian/debs
COPY --from=node-upstream /usr/local/bin/node /opt/upstream/node
COPY tools/package_self_contained_runtime.py /build/package_self_contained_runtime.py
COPY platform/runtime/upstream-lock.json /build/upstream-lock.json
COPY platform/runtime/Dockerfile /build/runtime.Dockerfile
ENV MONITORBOX_RUNTIME_UPSTREAM_LOCK=/build/upstream-lock.json
ENV MONITORBOX_RUNTIME_DOCKERFILE=/build/runtime.Dockerfile
ENV MONITORBOX_RUNTIME_DEBIAN_LOCK_DIR=/build/debian
ENV MONITORBOX_RUNTIME_DEBIAN_ARCHIVES=/build/debian/debs
RUN mkdir -p /artifacts /proof \
    && python /build/package_self_contained_runtime.py --language python \
         --output /artifacts/python-candidate.zip --extract-to /proof/python \
    && python /build/package_self_contained_runtime.py --language node \
         --output /artifacts/node-candidate.zip --extract-to /proof/node
