# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM postgres:17.10-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193

ARG WAYBILL_GIT_COMMIT
ARG WAYBILL_GIT_TREE
ARG WAYBILL_CODE_MANIFEST_SHA256
ARG WAYBILL_PROTOCOL_SHA256
RUN test -n "${WAYBILL_GIT_COMMIT}" \
    && test -n "${WAYBILL_GIT_TREE}" \
    && test -n "${WAYBILL_CODE_MANIFEST_SHA256}" \
    && test -n "${WAYBILL_PROTOCOL_SHA256}"

LABEL org.opencontainers.image.title="WayBill PostgreSQL" \
      org.opencontainers.image.description="Rootless PostgreSQL without the vulnerable gosu bootstrap binary" \
      org.opencontainers.image.revision="${WAYBILL_GIT_COMMIT}" \
      io.waybill.git.tree="${WAYBILL_GIT_TREE}" \
      io.waybill.code-manifest.sha256="${WAYBILL_CODE_MANIFEST_SHA256}" \
      io.waybill.protocol.sha256="${WAYBILL_PROTOCOL_SHA256}" \
      io.waybill.postgresql.version="17.10"

RUN apk upgrade --no-cache && rm -f /usr/local/bin/gosu

USER 70:70
