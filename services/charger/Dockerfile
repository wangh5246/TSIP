# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM node:26.5.1-alpine3.23@sha256:2a633e101381371ba148c7c212bf447c00cd267d814b708a9fe52c4984204729 AS node
WORKDIR /opt/waybill-node
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

FROM python:3.12.13-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d
ARG WAYBILL_GIT_COMMIT
ARG WAYBILL_GIT_TREE
ARG WAYBILL_CODE_MANIFEST_SHA256
ARG WAYBILL_PROTOCOL_SHA256
RUN test -n "${WAYBILL_GIT_COMMIT}" \
    && test -n "${WAYBILL_GIT_TREE}" \
    && test -n "${WAYBILL_CODE_MANIFEST_SHA256}" \
    && test -n "${WAYBILL_PROTOCOL_SHA256}"
LABEL org.opencontainers.image.revision="${WAYBILL_GIT_COMMIT}" \
      io.waybill.git.tree="${WAYBILL_GIT_TREE}" \
      io.waybill.code-manifest.sha256="${WAYBILL_CODE_MANIFEST_SHA256}" \
      io.waybill.protocol.sha256="${WAYBILL_PROTOCOL_SHA256}" \
      io.waybill.build.node.version="26.5.1" \
      io.waybill.build.npm.version="11.17.0"
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /opt/waybill-node /opt/waybill-node
WORKDIR /app

RUN apk upgrade --no-cache && apk add --no-cache libgcc libstdc++

COPY services/charger/requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && python -m pip uninstall --yes pip setuptools wheel \
    && ln -s /opt/waybill-node/node_modules/.bin/snarkjs /usr/local/bin/snarkjs

COPY services/charger ./services/charger
COPY common ./common
RUN mkdir -p /app/configs/settlement_policy_profiles /app/zk/settlement_period_v6_k6
COPY configs/settlement_policy_profiles/ruc-demo-v9.json ./configs/settlement_policy_profiles/
COPY configs/settlement_policy_profiles/ruc-demo-tariff-v9-d8.json ./configs/settlement_policy_profiles/
COPY zk/settlement_period_v6_k6/verification_key.json ./zk/settlement_period_v6_k6/

RUN addgroup -S -g 10002 waybill \
    && adduser -S -D -H -u 10002 -G waybill \
      -h /nonexistent -s /sbin/nologin waybill \
    && chown -R waybill:waybill /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app
USER 10002:10002
CMD ["uvicorn", "services.charger.app:app", "--host", "0.0.0.0", "--port", "8020", "--workers", "1", "--ssl-certfile", "/run/waybill-tls/charger-server-chain.pem", "--ssl-keyfile", "/run/waybill-tls/charger-server.key", "--no-proxy-headers", "--no-server-header"]
