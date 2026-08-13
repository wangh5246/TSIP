# WayBill M4 Tomorrow-Night Launch Card

Status on 2026-08-13: **LOCAL RELEASE READY; TARGET NO-GO**. Do not run
`init-run` until every STOP item below is closed. V3 supersedes the immutable V2
release for formal execution; V2 may be used only to reproduce its canonical
receipt.

## 1. Verify the frozen V3 release

These values come from the clean annotated V3 tag, never from a working tree or
V2:

```bash
export WAYBILL_RELEASE_TAG='waybill-formal-readiness-v3'
export WAYBILL_RELEASE_DIR='/srv/waybill-release/waybill-formal-readiness-v3'
export WAYBILL_WORKSPACE='/srv/waybill'
export WAYBILL_SHARED_DATA_ROOT='/srv/waybill-data/waybill-formal-v1'
export WAYBILL_PREPARED_ROOT="$WAYBILL_SHARED_DATA_ROOT/prepared"
export WAYBILL_CORPUS_ROOT="$WAYBILL_SHARED_DATA_ROOT/corpus"
export WAYBILL_PTAU="$WAYBILL_SHARED_DATA_ROOT/ptau/powersOfTau28_hez_final_22.ptau"
export WAYBILL_FORMAL_SIF="/opt/waybill-formal/runtime/${WAYBILL_RELEASE_TAG}.sif"
```

Verify the copied release before loading any image:

```bash
sha256sum -c "$WAYBILL_RELEASE_DIR/SHA256SUMS"
python script/finalize_waybill_release.py verify \
  --release "$WAYBILL_RELEASE_DIR"
test "$(git describe --tags --exact-match)" = "$WAYBILL_RELEASE_TAG"
test -z "$(git status --porcelain)"
```

Build the SIF from the V3 formal-runner archive, make it read-only, and
record its independent byte identity:

```bash
sudo apptainer build "$WAYBILL_FORMAL_SIF" \
  "docker-archive:$WAYBILL_RELEASE_DIR/containers/formal-runner-image.tar"
sudo chown root:root "$WAYBILL_FORMAL_SIF"
sudo chmod 0555 "$WAYBILL_FORMAL_SIF"
export WAYBILL_FORMAL_SIF_SHA256="$(sha256sum "$WAYBILL_FORMAL_SIF" | awk '{print $1}')"
```

## 2. Verify restricted inputs and materialize once

The local recovery manifest is an audit aid, not a substitute for target-side
RG2. On the target, build and validate a fresh uncapped manifest, then create
one prepared/corpus root:

```bash
python script/waybill_formal.py build-data-manifest \
  --data-root "$WAYBILL_DATA_ROOT" \
  --output-dir artifacts/waybill_formal/data
python script/waybill_formal.py validate-data-manifest \
  --manifest artifacts/waybill_formal/data/data-manifest.json

python script/prepare_tier1_datasets.py \
  --dataset all --data-root "$WAYBILL_DATA_ROOT" \
  --output-dir "$WAYBILL_PREPARED_ROOT" --max-raw-points 0 --formal
python script/materialize_waybill_formal_corpus.py \
  --prepared-root "$WAYBILL_PREPARED_ROOT" \
  --output-dir "$WAYBILL_CORPUS_ROOT"
python script/waybill_formal.py plan \
  --prepared-manifest "$WAYBILL_CORPUS_ROOT/prepared_manifest.json" \
  --output-dir artifacts/waybill_formal/plan
```

Required checks:

```bash
jq -e '.materialized == true and (.expected_job_count | type == "number")' \
  artifacts/waybill_formal/plan/plan.json
test "$(realpath "$WAYBILL_PREPARED_ROOT")" != "$(realpath "$WAYBILL_CORPUS_ROOT")"
test "$(realpath "$WAYBILL_SHARED_DATA_ROOT")" != "$(realpath "$WAYBILL_WORKSPACE")"
```

## 3. Pass target RG6

Run on the actual Linux x86-64 execution node using the exact V3 image and SIF.
A laptop receipt does not count. Derive the OCI digest from the verified
container manifest instead of transcribing it:

```bash
export WAYBILL_CONTAINER_DIGEST="$(jq -r '.images["formal-runner"].image_digest' \
  "$WAYBILL_RELEASE_DIR/container-manifest.json")"
WAYBILL_EXPECTED_CONTAINER_DIGEST="$WAYBILL_CONTAINER_DIGEST" \
WAYBILL_CONTAINER_RUNTIME_IMAGE="$WAYBILL_FORMAL_SIF" \
WAYBILL_EXPECTED_CONTAINER_RUNTIME_SHA256="$WAYBILL_FORMAL_SIF_SHA256" \
WAYBILL_REQUIRED_WORKSPACE_GIB=500 \
script/check_deploy_host.sh
```

Increase the workspace threshold if the materialized plan plus a 25% safety
margin exceeds 500 GiB.

## 4. Smoke every dependency class

Before the large arrays, execute one representative job from each of:

1. S1 fallback/sensitivity;
2. S2 main;
3. S3 four-bucket certified-bound group;
4. S4 linkage;
5. S2 concurrency;
6. S5 corpus;
7. S5 verifier;
8. S5 in-process handler.

Each smoke must create a validated regular-file artifact manifest, a bound
attempt receipt, and a passed stage result. The S3 smoke must record a passed
small-oracle gate. The S5 corpus/handler smoke must anchor the complete receiver
attestation chain before proof-only acceptance.

## 5. Initialize only after every gate passes

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

Submit in dependency order: S1, S2-main, S3, S4, S2-concurrency, S5-corpus,
S5-verifier, S5-handler. Use the rendered Apptainer arrays in
`README_SERVER_DEPLOY.md`; do not execute host Python. Resume at most once and
retain the original failed attempt.

## 6. Strict close

```bash
python script/waybill_formal.py resume --run-root "$RUN_ROOT"
python script/waybill_formal.py merge --run-root "$RUN_ROOT"
jq -e '.status == "passed" and .s3_gate.passed == true' \
  "$RUN_ROOT/aggregate.json"
```

Only `scientific-aggregate.json` and `failure-summary.json` from a passed
strict merge may populate paper result slots. S1 remains formula-level trace
sensitivity; S5 handler results remain in-process FastAPI/SQLite evidence.

## STOP — any one item forbids `init-run`

- release tag is not `waybill-formal-readiness-v3`, is dirty/unannotated, or
  fails self-verification;
- OCI label, release manifest, SIF SHA-256, protocol, or code manifest differs;
- any dataset is incomplete or target RG2 fails;
- prepared/corpus paths overlap the writable workspace;
- plan is not materialized or has null cardinality;
- target RG6 is absent or failed;
- free workspace is below the frozen threshold plus safety margin;
- any dependency-class smoke is absent or failed;
- author attempts to replace a failed job with a smaller experiment.
