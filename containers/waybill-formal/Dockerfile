# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM node:26.5.1-trixie-slim@sha256:deae974a69e140f44f434ab29cb519fb5f8fe250fd364b8ca446bd0761acdc6a AS node
WORKDIR /opt/waybill
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

FROM alpine:3.23@sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40 AS git-runtime
RUN apk add --no-cache git=2.52.0-r0 \
    && test "$(git --version)" = "git version 2.52.0"

FROM rust:1.79.0-bookworm@sha256:9b2689d6f99ff381f178fa4361db745c8c355faecde73aa5b18b0efa84f03e62 AS circom-builder
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g; s|http://deb.debian.org/debian-security|https://deb.debian.org/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none --branch v2.1.9 --depth 1 https://github.com/iden3/circom.git /src/circom \
    && test "$(git -C /src/circom rev-parse HEAD)" = "2eaaa6dface934356972b34cab64b25d382e59de" \
    && cargo build --manifest-path /src/circom/Cargo.toml --release --locked

FROM python:3.12.13-slim-trixie@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS python-deps
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g; s|http://deb.debian.org/debian-security|https://deb.debian.org/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements/waybill-formal.lock /tmp/waybill-formal.lock
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --require-hashes \
      -r /tmp/waybill-formal.lock \
    && /opt/venv/bin/python -m pip uninstall --yes pip setuptools wheel

FROM python:3.12.13-slim-trixie@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de
ARG DEBIAN_FRONTEND=noninteractive
ARG WAYBILL_GIT_COMMIT
ARG WAYBILL_GIT_TREE
ARG WAYBILL_CODE_MANIFEST_SHA256
ARG WAYBILL_PROTOCOL_SHA256
RUN test -n "${WAYBILL_GIT_COMMIT}" \
    && test -n "${WAYBILL_GIT_TREE}" \
    && test -n "${WAYBILL_CODE_MANIFEST_SHA256}" \
    && test -n "${WAYBILL_PROTOCOL_SHA256}"
RUN install -d -m 0755 /opt/waybill \
    && python -c 'import json,pathlib,sys; pathlib.Path("/opt/waybill/release-bindings.json").write_text(json.dumps({"schema":"waybill.formal.embedded-release-binding/v1","git_commit":sys.argv[1],"git_tree":sys.argv[2],"code_manifest_sha256":sys.argv[3],"protocol_sha256":sys.argv[4]},sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")' \
      "${WAYBILL_GIT_COMMIT}" "${WAYBILL_GIT_TREE}" \
      "${WAYBILL_CODE_MANIFEST_SHA256}" "${WAYBILL_PROTOCOL_SHA256}" \
    && chmod 0444 /opt/waybill/release-bindings.json
LABEL org.opencontainers.image.revision="${WAYBILL_GIT_COMMIT}" \
      io.waybill.git.tree="${WAYBILL_GIT_TREE}" \
      io.waybill.code-manifest.sha256="${WAYBILL_CODE_MANIFEST_SHA256}" \
      io.waybill.protocol.sha256="${WAYBILL_PROTOCOL_SHA256}" \
      io.waybill.build.node.version="26.5.1" \
      io.waybill.build.npm.version="11.17.0" \
      io.waybill.runtime.git.version="2.52.0-r0"
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g; s|http://deb.debian.org/debian-security|https://deb.debian.org/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 upgrade -y \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
       ca-certificates \
       libatomic1 \
       time \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes pip setuptools wheel

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /opt/waybill/node_modules /opt/waybill/node_modules
COPY --from=git-runtime /usr/bin/git /usr/local/bin/git
COPY --from=git-runtime /lib/ld-musl-x86_64.so.1 /lib/ld-musl-x86_64.so.1
COPY --from=git-runtime /usr/lib/libz.so.1* /usr/lib/
COPY --from=git-runtime /usr/lib/libpcre2-8.so.0* /usr/lib/
COPY --from=circom-builder /src/circom/target/release/circom /usr/local/bin/circom
COPY --from=python-deps /opt/venv /opt/venv

WORKDIR /opt/waybill
COPY package.json package-lock.json ./
RUN ln -s /opt/waybill/node_modules/.bin/snarkjs /usr/local/bin/snarkjs

# Formal jobs execute only source bytes embedded in the immutable image/SIF.
# The writable workspace is mounted separately for run inputs and attempt outputs.
COPY common /work/common
COPY configs /work/configs
COPY experiments/waybill_m2 /work/experiments/waybill_m2
COPY experiments-heatmap/circuits /work/experiments-heatmap/circuits
COPY script /work/script
COPY services /work/services
COPY TSIP_heatmap_version/runtime/experiments-heatmap/make_v4_fair_heatmap.py \
     /work/TSIP_heatmap_version/runtime/experiments-heatmap/make_v4_fair_heatmap.py
COPY waybill_formal /work/waybill_formal

ENV PYTHONPATH=/work
ENV PATH=/opt/venv/bin:/opt/waybill/node_modules/.bin:/usr/local/bin:/usr/bin:/bin
ENV HOME=/nonexistent
ENV WAYBILL_CONTAINER=1
WORKDIR /work

USER 10003:10003

CMD ["python", "script/waybill_formal.py", "validate-config"]
