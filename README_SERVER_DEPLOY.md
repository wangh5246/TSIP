# WayBill V6 formal server runbook

The active settlement profile is
`configs/settlement_policy_profiles/ruc-demo-v9.json`. It pins the
validity-bound V6 circuit and verification key; V5/v7 artifacts are historical
baselines only.

## Current frozen status: V5 materializer-invocation successor

The immutable `waybill-formal-readiness-v3` release contains the reviewed
S2/S3/S5 runner repairs, the strict scientific aggregate, regression tests, and
the 2026-08-13 `cryptography==50.0.0` security update. A real Ubuntu
24.04/Apptainer 1.5.3 target then showed that `snarkjs 0.7.6 --version` prints
the exact version but exits 99. V3's generic version helper therefore reports a
false RG6 failure. V4 accepts only exit 0/99 for that one probe, still requires
the exact `snarkjs@0.7.6` output, and runs all probes with `--pwd /work`. V5
corrects the corpus-materializer invocation to `python -m
script.materialize_waybill_formal_corpus`, avoiding a Python import shadow in
the direct script form.

**Do not initialize M4 from V2.** The immutable V2 tag predates fixes for
attempt-local symbolic links, the S5 receiver-attestation anchor preflight, and
the registered S3 four-bucket/95% aggregate semantics. V5 supersedes V4 for
formal execution. V5 still does not authorize `init-run` by itself: the exact
release must be installed on the actual Linux x86-64 target, converted to a
read-only SIF, and pass target RG2/RG6, full materialization, and every
dependency-class smoke. An empty packaging `release_blockers` list is not a
semantic correctness proof.

This release readiness does not mean that the formal experiment is complete.
The remaining work must occur on the actual Linux x86-64 target. It consists of
validating the four authorized raw datasets, preprocessing without caps,
materializing the canonical corpus, freezing the data-dependent job plan,
passing RG6 on the target host, executing S1--S5, and completing strict merge.
No full-dataset result should be copied into the paper before the merged status
passes.

The checked-in `artifacts/waybill_formal/static-plan/plan.json` is only a
non-materialized preview. Its `materialized` field is false and its
`expected_job_count` is null. Do not use it to initialize a run. Regenerate the
plan from the final `corpus/prepared_manifest.json` after full materialization.

## Process-isolated receiver signer

The paper-facing prover must obtain fixes, signer-derived `position_valid`
(the profile-defined origin-label admissibility bit),
and a root attestation from a separate process. Production uses one
Linux service account and one systemd instance per `device_id`; do not use
`--allow-test-signer` or `WAYBILL_RECEIVER_TEST_MODE=1` in a formal run.

Install the frozen source read-only at `/opt/waybill-formal/current`, create a
Python 3.12 virtual environment at `/opt/waybill-formal/venv`, and install the
hash-locked dependencies before installing the service boundary:

```bash
sudo python3.12 -m venv /opt/waybill-formal/venv
sudo /opt/waybill-formal/venv/bin/python -m pip install --require-hashes \
  -r /opt/waybill-formal/current/services/receiver_signer/requirements.lock
sudo /opt/waybill-formal/current/deploy/install-waybill-receiver-signer.sh
```

The installer creates the non-login `waybill-receiver` account, the
owner-only `/var/lib/waybill-receiver` directory, and a hardened unit. It does
not create secrets, enable, or start the service. Copy the environment template
and generate three independent 32-byte tokens. The device token must also be
the token registered for this device at the Charger; it must not equal either
signer API token, the Charger administrator token, or the token pepper.

```bash
sudo install -o root -g root -m 0600 \
  /etc/waybill/receiver-signer.env.example \
  /etc/waybill/receiver-signer.env
openssl rand -hex 32  # acquisition token; place in the environment file
openssl rand -hex 32  # prover token; place in the environment file
openssl rand -hex 32  # Charger device token; place in both registration and the environment file
sudoedit /etc/waybill/receiver-signer.env
```

Initialize the key exactly once as the service account. The helper refuses to
overwrite an existing identity and creates the raw key with mode `0600`; the
state directory remains owned by `waybill-receiver` with mode `0700`.

```bash
sudo -u waybill-receiver \
  /opt/waybill-formal/venv/bin/python \
  /opt/waybill-formal/current/script/init_receiver_signer.py \
  --key-file /var/lib/waybill-receiver/receiver-ed25519.key \
  | sudo tee /root/waybill-receiver-public.json >/dev/null

sudo stat -c '%U:%G %a %n' \
  /var/lib/waybill-receiver \
  /var/lib/waybill-receiver/receiver-ed25519.key \
  /etc/waybill/receiver-signer.env
```

Expected permissions are `waybill-receiver:waybill-receiver 700` for the state
directory, `waybill-receiver:waybill-receiver 600` for the key, and
`root:root 600` for the environment file. The SQLite database, WAL, and SHM are
created by the signer as mode `0600` files in the same private directory.

The signer API is also authenticated with TLS; loopback is not treated as an
endpoint-authentication boundary. Issue a separate server certificate whose
`subjectAltName` contains `IP:127.0.0.1`, install the public CA, and make the
private key readable only by the signer group. A dedicated receiver CA is
preferred, although the same offline CA may issue separate Charger and signer
certificates.

```bash
sudo install -o root -g root -m 0644 RECEIVER_CA_CERT.pem \
  /etc/waybill/receiver-api-ca.pem
sudo install -o root -g root -m 0644 RECEIVER_SERVER_CHAIN.pem \
  /etc/waybill/tls/receiver-server-chain.pem
sudo install -o root -g waybill-receiver -m 0640 RECEIVER_SERVER_KEY.pem \
  /etc/waybill/tls/receiver-server.key
openssl x509 -in /etc/waybill/tls/receiver-server-chain.pem \
  -noout -ext subjectAltName
```

Start the Charger first, verify its health, and register the public key plus
the exact device token from the signer environment file as described below.
Verify the authenticated chain-head API as well: the public `/health` endpoint
is only process/database liveness and deliberately does not make a transitive
Charger request. Only after registration and this authenticated check succeed
should the signer be enabled:

```bash
curl --fail --cacert /etc/waybill/charger-ca.pem https://127.0.0.1:8443/health
sudo sh -c '. /etc/waybill/receiver-signer.env; exec curl --fail \
  --cacert "$WAYBILL_RECEIVER_CHARGER_CA_FILE" \
  -H "Authorization: Bearer $WAYBILL_RECEIVER_CHARGER_DEVICE_TOKEN" \
  "https://127.0.0.1:8443/settlement/devices/$WAYBILL_RECEIVER_DEVICE_ID/receiver-head"'
sudo systemctl enable --now waybill-receiver-signer.service
curl --fail --cacert /etc/waybill/receiver-api-ca.pem \
  https://127.0.0.1:8779/health
sudo systemctl status --no-pager waybill-receiver-signer.service
```

The signer calls the authenticated Charger TLS endpoint at
`https://127.0.0.1:8443` before sealing each period or monthly odometer
boundary. Periods atomically extend the Charger-side V5 receiver-attestation
chain. Monthly boundaries form a separate append-only device chain: the next
calendar month must begin at the exact previous odometer end, exact bytes are
idempotent, and conflicting bytes are rejected. These online comparisons make
deletion or restoration of a stale local SQLite tail fail closed. A Charger
outage therefore intentionally prevents new period and month seals;
acquisition may retry after Charger recovery. Never delete, edit, or restore
only the SQLite database, `-wal`, or `-shm` files.

After an ordinary process crash, systemd restarts the same single worker. If a
crash occurred after the Charger committed a period link or month boundary but
before SQLite committed it, the acquisition component must retry the exact
same request; the signer recovers only that exact remote-commit/local-loss
case. For storage loss or corruption, stop the signer, preserve the failed
directory for audit, and restore a complete cold backup of the directory. If
its local and Charger states do not match, do not edit or reset either side. An
unrecoverable state requires a new key and a new `device_id` enrollment under
an incident record.

There must be only one active signer for a device. Before planned migration,
stop the old unit, copy the complete stopped state directory over an
authenticated channel while preserving ownership and modes, and compare the
last local `(log_epoch, attestation_sha256)` with the authenticated Charger
`GET /settlement/devices/{device_id}/receiver-head` response. Use SQLite
read-only mode while the signer is stopped; never repair a mismatch by editing
either database. Start the replacement only when the heads match. Do not copy
the private key to two live hosts. The Charger compare-and-swap head rejects an
epoch gap or fork, but operational single-writer discipline is still
mandatory.

```bash
sudo -u waybill-receiver sqlite3 -readonly \
  /var/lib/waybill-receiver/receiver.sqlite3 \
  'SELECT log_epoch, attestation_sha256 FROM receiver_logs ORDER BY log_epoch DESC LIMIT 1;'
sudo sh -c '. /etc/waybill/receiver-signer.env; exec curl --fail \
  --cacert "$WAYBILL_RECEIVER_CHARGER_CA_FILE" \
  -H "Authorization: Bearer $WAYBILL_RECEIVER_CHARGER_DEVICE_TOKEN" \
  "https://127.0.0.1:8443/settlement/devices/$WAYBILL_RECEIVER_DEVICE_ID/receiver-head"'
```

### OCI alternative on Linux

The standalone signer image contains only the receiver runtime, a Linux-x86_64
hash lock, the active policy profile, and the one-time key initializer. Build
the release image with the same four source-identity values used by the release
finalizer; placeholders are forbidden in a release image:

```bash
docker buildx build --platform linux/amd64 --load \
  -t "waybill-receiver-signer:${WAYBILL_RELEASE_TAG:?set successor release tag}" \
  -f services/receiver_signer/Dockerfile \
  --build-arg WAYBILL_GIT_COMMIT="$WAYBILL_GIT_COMMIT" \
  --build-arg WAYBILL_GIT_TREE="$WAYBILL_GIT_TREE" \
  --build-arg WAYBILL_CODE_MANIFEST_SHA256="$WAYBILL_CODE_MANIFEST_SHA256" \
  --build-arg WAYBILL_PROTOCOL_SHA256="$WAYBILL_PROTOCOL_SHA256" .
```

This option requires native Linux host networking. It is intentionally not a
portable bridge-network recipe: `--network host` lets the unmodified signer
reach the authenticated loopback TLS endpoint while the signer itself remains
bound to host loopback. Do not add `-p`, change the bind address, bypass CA
verification, or replace the Charger URL with an unencrypted bridge hostname.

Use a container-specific state directory owned by the image UID/GID `10001`;
do not point a simultaneously installed systemd service at it. Initialize the
key once, make a container-specific copy of the receiver API key owned by GID
`10001`, then verify directory/key modes are `0700`/`0600` and `0640`:

```bash
sudo install -d -o 10001 -g 10001 -m 0700 /var/lib/waybill-receiver-oci
sudo docker run --rm --network host --read-only \
  --user 10001:10001 \
  --mount type=bind,src=/var/lib/waybill-receiver-oci,dst=/var/lib/waybill-receiver \
  --entrypoint python "waybill-receiver-signer:${WAYBILL_RELEASE_TAG:?set successor release tag}" \
  /app/script/init_receiver_signer.py \
  --key-file /var/lib/waybill-receiver/receiver-ed25519.key \
  | sudo tee /root/waybill-receiver-public.json >/dev/null
sudo stat -c '%u:%g %a %n' \
  /var/lib/waybill-receiver-oci \
  /var/lib/waybill-receiver-oci/receiver-ed25519.key
sudo install -d -o root -g root -m 0755 /etc/waybill/receiver-oci-tls
sudo install -o root -g root -m 0644 \
  /etc/waybill/tls/receiver-server-chain.pem \
  /etc/waybill/receiver-oci-tls/receiver-server-chain.pem
sudo install -o root -g 10001 -m 0640 \
  /etc/waybill/tls/receiver-server.key \
  /etc/waybill/receiver-oci-tls/receiver-server.key
```

After the same Charger registration/readiness sequence, run exactly one
read-only container. The explicit policy override replaces the systemd host
path in the shared environment example. `/tmp` is ephemeral; only the state
bind mount is writable.

```bash
sudo docker run -d --name waybill-receiver-signer \
  --network host --read-only --tmpfs /tmp:size=16m,mode=1777 \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --user 10001:10001 --restart unless-stopped \
  --env-file /etc/waybill/receiver-signer.env \
  --env WAYBILL_RECEIVER_POLICY_PROFILE=/app/configs/settlement_policy_profiles/ruc-demo-v9.json \
  --mount type=bind,src=/etc/waybill/charger-ca.pem,dst=/etc/waybill/charger-ca.pem,readonly \
  --mount type=bind,src=/etc/waybill/receiver-api-ca.pem,dst=/etc/waybill/receiver-api-ca.pem,readonly \
  --mount type=bind,src=/etc/waybill/receiver-oci-tls,dst=/run/waybill-tls,readonly \
  --mount type=bind,src=/var/lib/waybill-receiver-oci,dst=/var/lib/waybill-receiver \
  "waybill-receiver-signer:${WAYBILL_RELEASE_TAG:?set successor release tag}"
curl --fail --cacert /etc/waybill/receiver-api-ca.pem \
  https://127.0.0.1:8779/health
```

The systemd and OCI commands are alternatives, never two replicas. The same
one-active-signer, cold-backup, exact-retry, TLS authentication, and
Charger-head reconciliation rules apply to both.

The Charger TLS certificate and pinned CA authenticate the anchor endpoint;
the signer API has an independent TLS server identity for the same reason. The
signer still listens only on `127.0.0.1:8779`. Acquisition and proving clients
must use `https://127.0.0.1:8779` and validate
`/etc/waybill/receiver-api-ca.pem`; redirects and proxy-environment routing are
disabled by the supplied clients. If acquisition or proving clients are remote,
expose only the necessary API through a separately managed reverse proxy with
TLS, preferably mutual TLS and route-specific access policy. Never bind either
bearer-token API directly to a public or untrusted interface. Only the trusted
acquisition component receives the write token; the prover receives the
read-only token.

The signer accepts unsigned measurement fields and monthly odometer
boundaries, owns all receiver signatures, and rejects caller-provided
signatures, roots, validity flags, or policy commitments. For each interval,
validity is derived from the exact signed status of its origin fix under
`origin-osnma-authenticated-v1`; unknown values fail closed. It rejects
duplicate period/month logs and sequence, time, or odometer rollback. The V5
root attestation is policy-pinned and chained to the Charger-confirmed previous
head; monthly boundaries use domain-bound attestation V2 and must be confirmed
online by the Charger before local persistence. The first enrolled monthly
boundary is an explicit bootstrap trust point; all later boundaries are
calendar-sequential and odometer-continuous.

## Transactional Charger and PostgreSQL

The formal server path uses PostgreSQL; SQLite is only the local/CI evaluation
backend and production startup rejects a SQLite URL. The current relational
schema is V3; it adds a database-enforced unique device-token digest. A V2
database is rejected rather than silently altered: preserve it for audit and
perform an explicit migration or start the formal run from a fresh V3 database.
Generate independent random values of at least 32 characters for the
administrator token and token pepper. URL-encode the PostgreSQL password when
placing it in `WAYBILL_CHARGER_DATABASE_URL`.

Issue a server certificate from a dedicated offline or managed CA. Its
`subjectAltName` must contain `IP:127.0.0.1` (or the exact DNS name used in
`WAYBILL_RECEIVER_CHARGER_URL`); a CN-only certificate is rejected. Do not copy
the CA private key to this host. Install the public CA, server chain, and server
private key with the following ownership. GID `10002` is the fixed non-root
Charger group inside the release image.

```bash
sudo install -d -o root -g root -m 0755 /etc/waybill /etc/waybill/tls
sudo install -o root -g root -m 0644 CA_CERT.pem /etc/waybill/charger-ca.pem
sudo install -o root -g root -m 0644 SERVER_CHAIN.pem \
  /etc/waybill/tls/charger-server-chain.pem
sudo install -o root -g 10002 -m 0640 SERVER_KEY.pem \
  /etc/waybill/tls/charger-server.key
openssl x509 -in /etc/waybill/tls/charger-server-chain.pem \
  -noout -ext subjectAltName
```

The compose file mounts only `/etc/waybill/tls` read-only, runs Uvicorn TLS as
UID/GID `10002`, and publishes only `127.0.0.1:8443`; host port `8020` is not
published. Start the pinned stack and validate its certificate against the
installed CA:

```bash
export WAYBILL_POSTGRES_PASSWORD='replace-with-random-password'
export WAYBILL_CHARGER_DATABASE_URL='postgresql+psycopg://waybill:URL_ENCODED_PASSWORD@postgres:5432/waybill'
export WAYBILL_CHARGER_DOMAIN='ruc-demo.charger-01'
export WAYBILL_CHARGER_ADMIN_TOKEN='replace-with-at-least-32-random-characters'
export WAYBILL_CHARGER_TOKEN_PEPPER='replace-with-at-least-32-random-characters'
export WAYBILL_GIT_COMMIT='from-release-preflight'
export WAYBILL_GIT_TREE='from-release-preflight'
export WAYBILL_CODE_MANIFEST_SHA256='from-release-preflight'
export WAYBILL_PROTOCOL_SHA256='from-release-preflight'
docker compose -f deploy/waybill-charger-compose.yml up -d --build
curl --fail --cacert /etc/waybill/charger-ca.pem https://127.0.0.1:8443/health
```

Register each receiver public key with an administrator credential and a
separate random device token. The token is returned to the device out of band;
the Charger stores only a keyed digest:

```bash
curl --fail --cacert /etc/waybill/charger-ca.pem \
  -X POST https://127.0.0.1:8443/settlement/devices/register \
  -H "Authorization: Bearer $WAYBILL_CHARGER_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"device_id":"dev-v6","public_key_hex":"REPLACE_HEX","jurisdiction_id":"ruc-demo","device_token":"REPLACE_RANDOM_DEVICE_TOKEN"}'
```

Proof and monthly-attestation submissions use that device token. Month status,
reconciliation, close, and registration use the administrator token. The reset
endpoint and transparent raw-fix endpoints cannot be enabled outside explicit
test mode. Keep the Charger at one application
worker for the first formal run; PostgreSQL serializes its write transactions,
but multi-worker throughput is not a paper claim until the target-host stress
receipt is produced.

The remaining runbook applies to the verified V6 release. It does not define a
smoke, reduced, or publication-eligible shortcut. Use
`WAYBILL_TOMORROW_RUNBOOK.md` as the launch card and stop if any target-derived
digest, path, capacity, corpus, or receipt value remains unresolved.

## 0. Rent the target

Use a Linux x86_64 instance with 32 vCPU, 128 GiB RAM, and a 1 TiB
high-performance SSD/NVMe data disk. Ubuntu 24.04 LTS or 22.04 LTS is
supported. A GPU is not required by the frozen M4 container; an existing GPU
host is acceptable only if its CPU, RAM, and disk meet the same requirements.

## 1. Build and freeze the Linux image

```bash
docker buildx build --provenance=false --platform linux/amd64 --load \
  --build-arg WAYBILL_GIT_COMMIT="$WAYBILL_GIT_COMMIT" \
  --build-arg WAYBILL_GIT_TREE="$WAYBILL_GIT_TREE" \
  --build-arg WAYBILL_CODE_MANIFEST_SHA256="$WAYBILL_CODE_MANIFEST_SHA256" \
  --build-arg WAYBILL_PROTOCOL_SHA256="$WAYBILL_PROTOCOL_SHA256" \
  -t "waybill-formal:$WAYBILL_RELEASE_TAG" \
  -f containers/waybill-formal/Dockerfile .
docker image inspect "waybill-formal:$WAYBILL_RELEASE_TAG"
```

The verified digest is recorded in the successor release's
`container-manifest.json`. Either push this image to a controlled registry or
transfer the frozen image archive created during release finalization. Copy the
complete successor release directory to the target;
its inventory is self-verified and contains:

- `source.bundle`
- `containers/formal-runner-image.tar`
- `containers/charger-image.tar`
- `containers/postgres-image.tar`
- `containers/receiver-signer-image.tar`
- one bound SPDX JSON SBOM beside each image archive
- one bound Trivy JSON vulnerability report beside each image archive
- `prover.tar.zst`
- `code-manifest-v2.json`
- `protocol.json`
- `container-manifest.json`
- `release-manifest.json`
- `SHA256SUMS`

Verify and restore them on the target:

```bash
sha256sum -c SHA256SUMS
GIT_LFS_SKIP_SMUDGE=1 git clone --branch "$WAYBILL_RELEASE_TAG" \
  source.bundle waybill_formal
cd waybill_formal
test "$(git rev-parse HEAD)" = "$(jq -r .identity.commit ../release-manifest.json)"
test "$(git describe --tags --exact-match)" = "$WAYBILL_RELEASE_TAG"
test -z "$(git status --porcelain)"
docker load -i ../containers/formal-runner-image.tar
docker load -i ../containers/charger-image.tar
docker load -i ../containers/postgres-image.tar
docker load -i ../containers/receiver-signer-image.tar
python script/finalize_waybill_release.py verify --release ..
```

Build one immutable Apptainer runtime from the frozen formal-runner archive and
record its own byte hash. The OCI image digest and SIF SHA-256 are separate
bindings and both are required:

```bash
sudo install -d -m 0755 /opt/waybill-formal/runtime
sudo apptainer build "/opt/waybill-formal/runtime/${WAYBILL_RELEASE_TAG}.sif" \
  docker-archive:../containers/formal-runner-image.tar
sudo chown root:root "/opt/waybill-formal/runtime/${WAYBILL_RELEASE_TAG}.sif"
sudo chmod 0555 "/opt/waybill-formal/runtime/${WAYBILL_RELEASE_TAG}.sif"
export WAYBILL_FORMAL_SIF="/opt/waybill-formal/runtime/${WAYBILL_RELEASE_TAG}.sif"
export WAYBILL_FORMAL_SIF_SHA256="$(sha256sum "$WAYBILL_FORMAL_SIF" | awk '{print $1}')"
stat -c '%U:%G %a %n' "$WAYBILL_FORMAL_SIF" /opt/waybill-formal/runtime
apptainer inspect --json "$WAYBILL_FORMAL_SIF"
```

The LFS skip is intentional: historical proof artifacts are not release
inputs. The authorized datasets and exact PTAU are transferred separately in
the following steps.

The observed image IDs, `linux/amd64` platform, OCI revision labels, source
commit, and code-manifest hash must match the frozen manifests. Mutable tags
alone are insufficient. The proving archive supplies the exact R1CS, WASM,
zkey, and verification key; the source bundle intentionally omits those large
files and historical V5 LFS payloads.

## 2. Transfer restricted data and verify RG2

Transfer the four provider-authorized raw datasets outside Git, set
`WAYBILL_DATA_ROOT`, then run:

```bash
python script/waybill_formal.py build-data-manifest \
  --data-root "$WAYBILL_DATA_ROOT" \
  --output-dir artifacts/waybill_formal/data
python script/waybill_formal.py validate-data-manifest \
  --manifest artifacts/waybill_formal/data/data-manifest.json
```

The expected T-Drive count is 10,357 files. Raw or row-level derived records
must not be committed or published.

## 3. Materialize the full prepared and canonical corpus

Use one canonical, versioned data root. It is the only materialized copy used
by every local worker or target execution node; it contains no writable run
directory and no raw provider data. The Charger and independent receiver signer
do not mount it at all.

```bash
export WAYBILL_SHARED_DATA_ROOT=/srv/waybill-data/waybill-formal-v1
export WAYBILL_PREPARED_ROOT="$WAYBILL_SHARED_DATA_ROOT/prepared"
export WAYBILL_CORPUS_ROOT="$WAYBILL_SHARED_DATA_ROOT/corpus"
export WAYBILL_PTAU="$WAYBILL_SHARED_DATA_ROOT/ptau/powersOfTau28_hez_final_22.ptau"
```

Prepare once into `prepared/`, materialize once into `corpus/`, then make the
root immutable and mount the same absolute path read-only on each of the three
local test workers (or on every Slurm node). The frozen
`corpus/prepared_manifest.json` hashes every prepared and canonical input; it
is sealed again in each run. On the rented server, transfer this single root
once, verify its manifest and PTAU hash, and use the same layout rather than
regenerating per server.

Run preprocessing with no caps:

```bash
python script/prepare_tier1_datasets.py \
  --dataset all \
  --data-root "$WAYBILL_DATA_ROOT" \
  --output-dir "$WAYBILL_PREPARED_ROOT" \
  --max-raw-points 0 \
  --formal

python -m script.materialize_waybill_formal_corpus \
  --prepared-root "$WAYBILL_PREPARED_ROOT" \
  --output-dir "$WAYBILL_CORPUS_ROOT"
```

The materializer must produce exactly 12 S3 canonical variants per accepted
period: four bucket sizes times three radii. It fails if any prepared period is
silently dropped. `WAYBILL_PREPARED_ROOT` contains the period/tariff corpus;
`WAYBILL_CORPUS_ROOT` contains the generated canonical S3 instances. They must
be distinct directories and neither may overlap the writable run directory.

## 4. Freeze cardinality and resource plan

```bash
python script/waybill_formal.py plan \
  --prepared-manifest "$WAYBILL_CORPUS_ROOT/prepared_manifest.json" \
  --output-dir artifacts/waybill_formal/plan
```

The generated `expected.jsonl` is immutable input to the run. Formal execution
is forbidden if `plan.json` says `materialized: false`.

## 5. Pass target-host RG6

The target must be Linux x86_64, have at least 32 GiB per setup/prove job,
at least 500 GiB free workspace before materialization, the exact toolchain,
exact image digest, and the exact 4.83 GB PTAU. Rent 1 TiB initially; after
the full corpus plan is frozen, raise `WAYBILL_REQUIRED_WORKSPACE_GIB` if the
plan plus a 25% safety margin exceeds 500 GiB:

```bash
WAYBILL_WORKSPACE=/srv/waybill \
WAYBILL_PTAU=/srv/waybill/powersOfTau28_hez_final_22.ptau \
WAYBILL_CONTAINER_DIGEST='repo/image@sha256:...' \
WAYBILL_EXPECTED_CONTAINER_DIGEST='repo/image@sha256:...' \
WAYBILL_CONTAINER_RUNTIME_IMAGE="$WAYBILL_FORMAL_SIF" \
WAYBILL_EXPECTED_CONTAINER_RUNTIME_SHA256="$WAYBILL_FORMAL_SIF_SHA256" \
WAYBILL_REQUIRED_WORKSPACE_GIB=500 \
script/check_deploy_host.sh
```

This receipt must be produced on the actual target node; a laptop receipt
cannot close RG6.

## 6. Initialize and execute the immutable run

After RG0-RG8 receipts are all `passed` and semantically valid under receipt V2,
initialize once with
`script/waybill_formal.py init-run`. Existing run directories are never
overwritten. The `init-run` command must include
`--container-runtime-image "$WAYBILL_FORMAL_SIF"`,
`--workspace-root "$WAYBILL_WORKSPACE"`; the resulting `run.json` binds the
execution-container receipt and byte-hashes every immutable protocol, plan,
manifest, gate, and expected-job input before any job can start. Initialization
is staged and atomically renamed, so a failed check cannot leave a runnable
partial run directory. The formal source is already embedded in the immutable
OCI image and SIF; never mount a host checkout over `/work`.

```bash
python script/waybill_formal.py init-run \
  --plan-dir artifacts/waybill_formal/plan \
  --output-root "$WAYBILL_WORKSPACE/runs" \
  --run-id formal-001 \
  --code-manifest "$WAYBILL_RELEASE_DIR/code-manifest-v2.json" \
  --data-manifest artifacts/waybill_formal/data/data-manifest.json \
  --environment-manifest artifacts/waybill_formal/environment.json \
  --container-manifest "$WAYBILL_RELEASE_DIR/container-manifest.json" \
  --prepared-manifest "$WAYBILL_CORPUS_ROOT/prepared_manifest.json" \
  --gate-receipts artifacts/waybill_formal/gate-receipts.json \
  --container-runtime-image "$WAYBILL_FORMAL_SIF" \
  --prepared-root "$WAYBILL_PREPARED_ROOT" \
  --corpus-root "$WAYBILL_CORPUS_ROOT" \
  --ptau "$WAYBILL_PTAU" \
  --workspace-root "$WAYBILL_WORKSPACE" \
  --shared-data-root "$WAYBILL_SHARED_DATA_ROOT"
```

Render separate arrays so S2 main setup/proof jobs finish before S2
concurrency jobs:

```bash
SLURM_CONTAINER_ARGS=(
  --container-image "$WAYBILL_FORMAL_SIF"
  --prepared-root "$WAYBILL_PREPARED_ROOT"
  --corpus-root "$WAYBILL_CORPUS_ROOT"
  --ptau "$WAYBILL_PTAU"
  --workspace-root "$WAYBILL_WORKSPACE"
  --shared-data-root "$WAYBILL_SHARED_DATA_ROOT"
)
python script/waybill_formal.py render-slurm \
  --run-root "$RUN_ROOT" --stage S2 --kind main \
  --output "$RUN_ROOT/slurm/s2-main.sbatch" "${SLURM_CONTAINER_ARGS[@]}"
python script/waybill_formal.py render-slurm \
  --run-root "$RUN_ROOT" --stage S2 --kind concurrency \
  --output "$RUN_ROOT/slurm/s2-concurrency.sbatch" "${SLURM_CONTAINER_ARGS[@]}"
python script/waybill_formal.py render-slurm \
  --run-root "$RUN_ROOT" --stage S5 --kind corpus \
  --output "$RUN_ROOT/slurm/s5-corpus.sbatch" "${SLURM_CONTAINER_ARGS[@]}"
python script/waybill_formal.py render-slurm \
  --run-root "$RUN_ROOT" --stage S5 --kind verifier \
  --output "$RUN_ROOT/slurm/s5-verifier.sbatch" "${SLURM_CONTAINER_ARGS[@]}"
python script/waybill_formal.py render-slurm \
  --run-root "$RUN_ROOT" --stage S5 --kind handler \
  --output "$RUN_ROOT/slurm/s5-handler.sbatch" "${SLURM_CONTAINER_ARGS[@]}"
```

The generated arrays refuse host-Python execution. They verify the SIF hash,
launch with `--containall --cleanenv --no-home --no-mount hostfs`, disable the
network namespace, execute the image-embedded source at `/work`, and expose
only the sealed run directory read-write. When `--shared-data-root` is used,
the prepared datasets, canonical S3 instances, and exact PTAU are one
read-only mount; otherwise they remain separate read-only mounts. The runtime also
compares the embedded
Git/tree/code-manifest/protocol binding file with `execution-container.json`.
Each attempt receipt includes the OCI image digest, SIF hash, source bindings,
and `apptainer` launcher binding. S2 materializes its generated Circom wrapper
and a byte-identical base-circuit copy inside the attempt directory; it never
writes into the immutable image source tree.

Submit S1, S2-main, S3, S4, S2-concurrency, S5-corpus, and finally the
S5-verifier/S5-handler jobs with scheduler dependencies appropriate to the
site. Each S5 corpus job creates 100 distinct real Groth16 bundles for one of
fixes 25/100/200; verifier and handler jobs fail closed unless that immutable
corpus attempt passed. Failed jobs may be resumed once:

The S5 `handler` matrix is deliberately an in-process FastAPI/SQLite functional
concurrency benchmark. It exercises profile resolution, receiver-chain
preflight, proof dispatch, replay rejection, and ledger conflict handling, but
it does not measure TLS, Uvicorn, container networking, PostgreSQL connection
pools, or deployed-server capacity. Production PostgreSQL/HTTPS load testing is
a separate target-host exercise and must not be inferred from the strict S5
aggregate.

```bash
python script/waybill_formal.py resume --run-root "$RUN_ROOT"
```

Every retry receives a new immutable attempt directory.

## 7. Strict merge

```bash
python script/waybill_formal.py merge --run-root "$RUN_ROOT"
```

`status.json` is generated only by the validator. Any missing unit or a unit
without a successful attempt makes the aggregate fail. Do not copy values
manually from logs into the paper. A successful merge also writes
`failure-summary.json` and `scientific-aggregate.json`; both are embedded and
hash-bound in `aggregate.json`. The scientific aggregate records every selected
attempt and its stage-result/attempt-receipt identities, then reports every
seed plus median/min/max across otherwise identical parameters. The failure
summary preserves stage/kind/dataset denominators, invalid receipts, timeouts,
out-of-memory events, resource rejections, nonzero exits, and resource usage.
S3 additionally requires every main representative within 1%, at least 95% of
all instances certified within 5%, and zero soundness or small-oracle failure.
