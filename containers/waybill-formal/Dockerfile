# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM node:26.0.0-bookworm-slim@sha256:3529ef69feecddd94e9c5ecd3d25a96f2f23ea40661f494f932ae2b12ab1977c AS node

FROM rust:1.79.0-bookworm@sha256:9b2689d6f99ff381f178fa4361db745c8c355faecde73aa5b18b0efa84f03e62 AS circom-builder
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g; s|http://deb.debian.org/debian-security|https://deb.debian.org/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none --branch v2.1.9 --depth 1 https://github.com/iden3/circom.git /src/circom \
    && test "$(git -C /src/circom rev-parse HEAD)" = "2eaaa6dface934356972b34cab64b25d382e59de" \
    && cargo build --manifest-path /src/circom/Cargo.toml --release --locked

FROM python:3.12.7-slim-bookworm@sha256:60d9996b6a8a3689d36db740b49f4327be3be09a21122bd02fb8895abb38b50d
ARG DEBIAN_FRONTEND=noninteractive
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g; s|http://deb.debian.org/debian-security|https://deb.debian.org/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
       ca-certificates \
       build-essential \
       git \
       jq \
       numactl \
       procps \
       time \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/ /usr/local/
COPY --from=circom-builder /src/circom/target/release/circom /usr/local/bin/circom

WORKDIR /opt/waybill
COPY requirements/waybill-formal.lock /tmp/waybill-formal.lock
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/waybill-formal.lock

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund \
    && ln -s /opt/waybill/node_modules/.bin/snarkjs /usr/local/bin/snarkjs

ENV PYTHONPATH=/work
ENV PATH=/opt/waybill/node_modules/.bin:/usr/local/bin:/usr/bin:/bin
ENV WAYBILL_CONTAINER=1
WORKDIR /work

CMD ["python", "script/waybill_formal.py", "validate-config"]
