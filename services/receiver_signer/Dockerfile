# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM python:3.12.13-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d

ARG WAYBILL_GIT_COMMIT
ARG WAYBILL_GIT_TREE
ARG WAYBILL_CODE_MANIFEST_SHA256
ARG WAYBILL_PROTOCOL_SHA256
RUN test -n "${WAYBILL_GIT_COMMIT}" \
    && test -n "${WAYBILL_GIT_TREE}" \
    && test -n "${WAYBILL_CODE_MANIFEST_SHA256}" \
    && test -n "${WAYBILL_PROTOCOL_SHA256}"

LABEL org.opencontainers.image.title="WayBill Independent Receiver Signer" \
      org.opencontainers.image.description="Fail-closed receiver signer with Charger-anchored V5 attestations" \
      org.opencontainers.image.revision="${WAYBILL_GIT_COMMIT}" \
      io.waybill.git.tree="${WAYBILL_GIT_TREE}" \
      io.waybill.code-manifest.sha256="${WAYBILL_CODE_MANIFEST_SHA256}" \
      io.waybill.protocol.sha256="${WAYBILL_PROTOCOL_SHA256}"

WORKDIR /app
COPY services/receiver_signer/requirements.lock /tmp/receiver-signer.lock
RUN python -m pip install --no-cache-dir --require-hashes \
      -r /tmp/receiver-signer.lock \
    && python -m pip uninstall --yes pip setuptools wheel \
    && rm -f /tmp/receiver-signer.lock

COPY common ./common
COPY services/receiver_signer ./services/receiver_signer
COPY script/init_receiver_signer.py ./script/init_receiver_signer.py
COPY configs/settlement_policy_profiles/ruc-demo-v9.json \
  ./configs/settlement_policy_profiles/ruc-demo-v9.json

RUN addgroup -S -g 10001 waybill-receiver \
    && adduser -S -D -H -u 10001 -G waybill-receiver \
      -h /nonexistent -s /sbin/nologin \
      waybill-receiver \
    && install -d -o waybill-receiver -g waybill-receiver -m 0700 \
      /var/lib/waybill-receiver \
    && install -d -o root -g root -m 0755 /etc/waybill

ENV HOME=/nonexistent \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    WAYBILL_RECEIVER_DB=/var/lib/waybill-receiver/receiver.sqlite3 \
    WAYBILL_RECEIVER_KEY_FILE=/var/lib/waybill-receiver/receiver-ed25519.key \
    WAYBILL_RECEIVER_POLICY_PROFILE=/app/configs/settlement_policy_profiles/ruc-demo-v9.json \
    WAYBILL_RECEIVER_CHARGER_URL=https://127.0.0.1:8443 \
    WAYBILL_RECEIVER_CHARGER_CA_FILE=/etc/waybill/charger-ca.pem \
    WAYBILL_RECEIVER_TEST_MODE=0

VOLUME ["/var/lib/waybill-receiver"]
USER 10001:10001
STOPSIGNAL SIGINT
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import ssl,urllib.request; c=ssl.create_default_context(cafile='/etc/waybill/receiver-api-ca.pem'); c.minimum_version=ssl.TLSVersion.TLSv1_2; urllib.request.urlopen('https://127.0.0.1:8779/health', context=c, timeout=2).read()"]
CMD ["uvicorn", "services.receiver_signer.app:app", "--host", "127.0.0.1", "--port", "8779", "--workers", "1", "--ssl-certfile", "/run/waybill-tls/receiver-server-chain.pem", "--ssl-keyfile", "/run/waybill-tls/receiver-server.key", "--no-proxy-headers", "--no-server-header"]
