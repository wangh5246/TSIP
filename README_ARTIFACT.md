# WayBill artifact guide

> Active protocol baseline: V6 validity-bound settlement, policy profile
> `ruc-demo-v9`, receipt schema V2. V5 artifacts are retained only as historical
> baselines and are not paper-facing evidence.

> **Formal-run release (2026-08-13):** the immutable
> `waybill-formal-readiness-v2` bundle remains useful only for reproducing its
> canonical receipt. M4 execution uses the V5 successor to the repaired V3
> release and must still pass target RG2/RG6,
> corpus materialization, and all dependency-class smokes before `init-run`.

## 1. Default verification

The default command collects the complete repository test suite:

```bash
python -m pytest
```

`pytest.ini` no longer hides non-legacy tests behind an explicit three-file
allowlist. Tests that require unavailable external tools or restricted datasets
must skip or fail with an explicit prerequisite error; they must not silently
substitute a reduced experiment.

The focused P0 checks are:

```bash
python -m pytest \
  tests/test_receiver_signer.py \
  tests/test_receiver_chain_anchor.py \
  tests/test_settlement_v6.py \
  tests/test_charger_service.py \
  tests/test_charger_auth.py \
  tests/test_charger_persistence.py \
  tests/test_policy_profile.py \
  tests/test_waybill_release_finalizer.py \
  tests/test_waybill_formal.py \
  tests/test_waybill_formal_stages.py
```

## 2. Canonical V6 circuit and policy

| Item | Frozen value |
|---|---|
| Circuit | `SettlementPeriodV6(25,8,6)` |
| Circuit identifier | `settlement-period-v6-validity-bound-k25-d8` |
| Constraints | 246,255 |
| Public signals | 22 |
| Policy profile | `configs/settlement_policy_profiles/ruc-demo-v9.json` |
| Profile commitment | `19189060107095078943373029755233485227080367977087589742745959455447551318479` |
| Verification-key SHA-256 | `9715ac43bc809c94844b0cb8af120fb3b5342f6bcfa8adf27f9dcbce30add471` |
| Receiver commitment semantics | `receiver-fix-validity-v2` |
| Position-validity rule | `origin-osnma-authenticated-v1` |
| Root-attestation schema | `waybill.receiver.root-attestation/v5` |

The receiver root commits every fix together with its receiver-owned
`position_valid` bit (the terminal fix binds a false sentinel). The root
attestation is emitted only by the process-isolated receiver signer after it seals
an append-only acquisition log. The acquisition API accepts unsigned
measurement fields; the signer creates fix signatures itself and separately
seals the monthly odometer boundary. For interval `i`, it derives validity
solely from the exact signed status of origin fix `i`: `authenticated` is true
and `unavailable` is false. The terminal status is checked but has no outgoing
flag. A normal prover cannot submit a caller-chosen signature, root, validity
vector, rule, or month attestation. Root-attestation V5 includes the previous
attestation hash. Before a local seal commits, the signer extends the
authenticated Charger head with an epoch-and-hash compare-and-swap; the exact
one-link-ahead response is the only recoverable crash case. Local tail deletion,
snapshot rollback, epoch gaps, and forks therefore fail closed.

Large R1CS/WASM/zkey files remain outside ordinary Git history. Their immutable
hashes are recorded in the checked-in receipt. The checked-in verification key
is `zk/settlement_period_v6_k6/verification_key.json`.

## 3. Reproduce the canonical proof path

The external test PTAU and direct Groth16 setup are test-only. They demonstrate
the circuit/prover/charger differential path and are not a production ceremony.
`zk/hello/pot18_final_phase2.ptau` is deliberately not in the source bundle;
its expected size is 301,989,824 bytes and its SHA-256 is
`d324d7af83d1c1016529856f33b8610bb4d5c7211f84c6fb292303f1b9f90558`.

Initialize the receiver signer in a separate process. Production mode requires
an already-running HTTPS Charger, a CA file that validates its certificate, and
a registered device token; loopback HTTP is intentionally rejected. The exact
certificate, registration, and service commands are in
`README_SERVER_DEPLOY.md`.

```bash
python script/init_receiver_signer.py \
  --key-file /srv/waybill/receiver-ed25519.key

WAYBILL_RECEIVER_DB=/srv/waybill/receiver.sqlite3 \
WAYBILL_RECEIVER_KEY_FILE=/srv/waybill/receiver-ed25519.key \
WAYBILL_RECEIVER_ACQUISITION_TOKEN='replace-with-secret' \
WAYBILL_RECEIVER_PROVER_TOKEN='replace-with-independent-secret' \
WAYBILL_RECEIVER_CHARGER_DEVICE_TOKEN='replace-with-device-secret' \
WAYBILL_RECEIVER_ID=receiver-01 \
WAYBILL_RECEIVER_DEVICE_ID=dev-v6 \
WAYBILL_CHARGER_DOMAIN=ruc-demo.charger-test \
WAYBILL_RECEIVER_POLICY_PROFILE="$PWD/configs/settlement_policy_profiles/ruc-demo-v9.json" \
WAYBILL_RECEIVER_CHARGER_URL=https://127.0.0.1:8443 \
WAYBILL_RECEIVER_CHARGER_CA_FILE=/etc/waybill/charger-ca.pem \
WAYBILL_RECEIVER_TEST_MODE=0 \
uvicorn services.receiver_signer.app:app \
  --host 127.0.0.1 --port 8779 --workers 1 \
  --no-proxy-headers --no-server-header
```

After an authorized acquisition component has appended and sealed the period
and monthly boundary, prove against the signer-owned material. The deterministic
fixture loader exercises both protected write paths:

```bash
python script/load_receiver_fixture_v6.py \
  --receiver-url https://127.0.0.1:8779 \
  --receiver-ca-file /etc/waybill/receiver-api-ca.pem \
  --acquisition-token 'replace-with-secret'

WAYBILL_RECEIVER_PROVER_TOKEN='replace-with-independent-secret' \
python script/prove_settlement_period_v6.py \
  --receiver-url https://127.0.0.1:8779 \
  --receiver-ca-file /etc/waybill/receiver-api-ca.pem \
  --policy-profile configs/settlement_policy_profiles/ruc-demo-v9.json \
  --artifacts-dir zk/settlement_period_v6_k6 \
  --ptau zk/hello/pot18_final_phase2.ptau \
  --proof-output-dir experiments/waybill_m1/v2/circuit_differential \
  --receipt experiments/waybill_m1/v2/circuit_differential/receipt.json

python script/run_waybill_m1_endpoint_gate.py
```

P1 Charger persistence and security checks are:

```bash
python -m pytest \
  tests/test_charger_auth.py \
  tests/test_charger_persistence.py \
  tests/test_charger_service.py \
  tests/test_charger_v6_month_close.py
```

The PostgreSQL parity test runs only when `WAYBILL_TEST_POSTGRES_URL` is set. It
must be exercised on the formal server; a skipped local test is not evidence of
PostgreSQL deployment readiness.

The canonical evidence directory is
`experiments/waybill_m1/v2/circuit_differential/`. Its circuit receipt records
the sealed receiver-log hash; its endpoint receipt covers canonical acceptance,
replay rejection, public-signal tampering, and month-close reconciliation. The
endpoint gate also verifies that the signed monthly odometer boundary is
online-anchored at the Charger by its exact canonical SHA-256, that an exact
retry is idempotent, and that a different validly signed boundary for the same
device-month is rejected as a conflict.

## 4. Build the self-verifying release

`script/finalize_waybill_release.py` accepts exactly the four configured image
roles: `formal-runner`, `charger`, `postgres`, and `receiver-signer`. Each image archive is
parsed independently; its platform, immutable digest, config digest, image
reference, and four source-binding labels are derived from the archive rather
than trusted from caller metadata. Every image also requires both a bound SPDX
2.3 SBOM and a bound Trivy JSON vulnerability report. The finalizer verifies
that Trivy 0.72.0 scanned the same image ID and enforces the role-specific
HIGH/CRITICAL policy. Preflight recomputes the policy commitment and
public-signal vector and runs `snarkjs groth16 verify` over the tagged proof.

The formal-runner image embeds the reviewed execution source at `/work` and a
machine-readable copy of the same Git commit, Git tree, code-manifest hash, and
protocol hash under `/opt/waybill/release-bindings.json`. Server jobs execute
those image bytes directly; a host source checkout is not an execution mount.
The release finalizer reconstructs `/work` from the ordered OCI layers,
applies whiteout semantics, rejects links and extra files, and compares every
embedded byte, mode, and path with the tagged code manifest.

The V5 config retains the V3 S2/S3/S5 repairs and pins
`cryptography==50.0.0` after the 2026-08-13 vulnerability refresh. Its four
Linux/amd64 image archives, bound SBOMs, and bound vulnerability reports belong
to the annotated `waybill-formal-readiness-v9` tag. The self-verifying release
is stored at `artifacts/releases/waybill-formal-readiness-v9`. V9 retains the
target-discovered `snarkjs --version` exit-99 RG6 probe contract, pins every
target probe to `/work`, and executes every S1--S5 runner with `python -m`.
It additionally records M2 artifacts under an external formal workspace as
absolute paths, while retaining repository-relative paths for in-tree runs.
This prevents receipt finalization from incorrectly requiring the target
Btrfs run root to be beneath `/work`. Run the
verification command below after transfer and before target-host execution. A
future dependency or scanner finding must create a new reviewed release rather
than changing this tagged bundle in place.

Run `preflight` on a clean annotated release tag first. Use the emitted Git
commit, tree, code-manifest hash, and protocol hash as the four Docker build
arguments for all four images. Save each built image, derive its metadata from
the archive, scan the immutable image ID, and bind both scanner outputs:

```bash
python script/finalize_waybill_release.py preflight \
  --tag waybill-formal-readiness-v9 \
  --config configs/waybill_formal/release-v9.json \
  --output-manifest artifacts/release-inputs-v9/preflight.json

docker save --output artifacts/release-inputs-v9/formal-runner-image.tar \
  waybill-formal:readiness-v9
python script/finalize_waybill_release.py image-metadata \
  --image artifacts/release-inputs-v9/formal-runner-image.tar \
  --image-ref waybill-formal:readiness-v9 \
  --role formal-runner \
  --config configs/waybill_formal/release-v9.json \
  --preflight artifacts/release-inputs-v9/preflight.json \
  --output artifacts/release-inputs-v9/formal-runner-metadata.json
docker run --rm \
  -v "$PWD/artifacts/release-inputs-v9:/out" \
  aquasec/trivy:0.72.0@sha256:cffe3f5161a47a6823fbd23d985795b3ed72a4c806da4c4df16266c02accdd6f \
  image --format spdx-json \
  --output /out/formal-runner-raw.spdx.json \
  --input /out/formal-runner-image.tar
python script/finalize_waybill_release.py bind-sbom \
  --input artifacts/release-inputs-v9/formal-runner-raw.spdx.json \
  --metadata artifacts/release-inputs-v9/formal-runner-metadata.json \
  --role formal-runner \
  --preflight artifacts/release-inputs-v9/preflight.json \
  --output artifacts/release-inputs-v9/formal-runner-sbom.spdx.json
docker run --rm \
  -v "$PWD/artifacts/release-inputs-v9:/out" \
  aquasec/trivy:0.72.0@sha256:cffe3f5161a47a6823fbd23d985795b3ed72a4c806da4c4df16266c02accdd6f \
  image --scanners vuln --format json \
  --output /out/formal-runner-raw.trivy.json \
  --input /out/formal-runner-image.tar
python script/finalize_waybill_release.py bind-vulnerability-report \
  --input artifacts/release-inputs-v9/formal-runner-raw.trivy.json \
  --metadata artifacts/release-inputs-v9/formal-runner-metadata.json \
  --role formal-runner \
  --config configs/waybill_formal/release-v9.json \
  --preflight artifacts/release-inputs-v9/preflight.json \
  --output artifacts/release-inputs-v9/formal-runner-vulnerabilities.trivy.json
```

Repeat those image/SBOM/vulnerability steps for `charger`, `postgres`, and
`receiver-signer`, then
invoke `build` with one repeated
`--image ROLE=PATH`, `--image-metadata ROLE=PATH`, `--sbom ROLE=PATH`, and
`--vulnerability-report ROLE=PATH` for each role. The resulting directory
contains its own tagged source bundle and can be checked without a
caller-supplied config. The finalizer verifies SPDX and Trivy report structure,
binds both scanner outputs to the exact image archive and tagged source, and
fails on any fixable vulnerability or an unexpected HIGH/CRITICAL finding. It does not
independently reimplement either package scanner.

```bash
python script/finalize_waybill_release.py verify \
  --release artifacts/releases/waybill-formal-readiness-v9
```

## 5. Formal experiment receipts

Formal jobs emit `waybill.formal.stage-result/v2` with a job hash and a recursive
artifact manifest. Attempt receipts bind the job, stage result, and artifact
hashes. Merge revalidates all of these values from disk, so a copied or edited
`passed` field cannot satisfy a gate. The final gate receipt is likewise sealed
under its V2 receipt hash.

Restricted four-dataset results are separate evidence. If the authorized raw
datasets are not mounted, the cryptographic endpoint receipt explicitly reports
that the data gate was not run; it never infers a data result from circuit
success.

## 6. Historical material

`settlement_period_v5_*`, `ruc-demo-v7`, and
`experiments/waybill_m1/v1/` remain for regression and historical comparison.
They implement the earlier time/speed fallback and must not be cited as the
active WayBill protocol or as evidence for V6 validity binding.
