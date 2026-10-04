# Immutable #421 successor acceptance feed transport.
# The build context is staged by the protected publisher and contains only:
#   platform/channels/**/index.json
#   platform/packages/*.zip
# plus this repository's feed server source.
FROM --platform=$BUILDPLATFORM golang:1.25-alpine@sha256:1ae0735f00daffa3aaf1363a5184c0d2dc55c78e3db4ec70241cdac97bf84b59 AS build
ARG TARGETOS=linux
ARG TARGETARCH
WORKDIR /src
COPY tools/successor_feed_server.go ./feed_server.go
COPY platform/channels/ /feed/platform/channels/
COPY platform/packages/ /feed/platform/packages/
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags="-s -w" -o /out/feed-server ./feed_server.go \
    && chmod -R a+rX /feed

FROM scratch
COPY --from=build /out/feed-server /usr/local/bin/feed-server
COPY --from=build /feed/ /feed/
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/feed-server"]
CMD ["-root","/feed","-listen","127.0.0.1:18081"]
