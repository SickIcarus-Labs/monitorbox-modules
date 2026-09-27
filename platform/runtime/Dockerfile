# Candidate-only digest-pinned upstream image proof. Debian apt package inputs
# still float, so these runtime ZIPs remain INELIGIBLE for official release.
FROM node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS node-upstream
FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS packer
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 libgcc-s1 libatomic1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node-upstream /usr/local/bin/node /opt/upstream/node
COPY tools/package_self_contained_runtime.py /build/package_self_contained_runtime.py
COPY platform/runtime/upstream-lock.json /build/upstream-lock.json
COPY platform/runtime/Dockerfile /build/runtime.Dockerfile
ENV MONITORBOX_RUNTIME_UPSTREAM_LOCK=/build/upstream-lock.json
ENV MONITORBOX_RUNTIME_DOCKERFILE=/build/runtime.Dockerfile
RUN mkdir -p /artifacts /proof \
    && python /build/package_self_contained_runtime.py --language python \
         --output /artifacts/python-candidate.zip --extract-to /proof/python \
    && python /build/package_self_contained_runtime.py --language node \
         --output /artifacts/node-candidate.zip --extract-to /proof/node
