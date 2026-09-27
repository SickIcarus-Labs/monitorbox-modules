# Candidate-only packaging proof. Official releases must pin both upstream
# images by immutable digest and pass package/security/runtime qualification.
FROM node:24-bookworm-slim AS node-upstream
FROM python:3.13-slim-bookworm AS packer
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 libgcc-s1 libatomic1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node-upstream /usr/local/bin/node /opt/upstream/node
COPY tools/package_self_contained_runtime.py /build/package_self_contained_runtime.py
RUN mkdir -p /artifacts /proof \
    && python /build/package_self_contained_runtime.py --language python \
         --output /artifacts/python-candidate.zip --extract-to /proof/python \
    && python /build/package_self_contained_runtime.py --language node \
         --output /artifacts/node-candidate.zip --extract-to /proof/node
