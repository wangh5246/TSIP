# WayBill V6 formal server runbook

This runbook is only for the frozen M4 full-scale experiment. It does not
define a smoke, reduced, or publication-eligible shortcut.

## 0. Rent the target

Use a Linux x86_64 instance with 32 vCPU, 128 GiB RAM, and a 1 TiB
high-performance SSD/NVMe data disk. Ubuntu 24.04 LTS or 22.04 LTS is
supported. A GPU is not required by the frozen M4 container; an existing GPU
host is acceptable only if its CPU, RAM, and disk meet the same requirements.

## 1. Build and freeze the Linux image

```bash
docker buildx build --provenance=false --platform linux/amd64 --load \
  -t waybill-formal:local \
  -f containers/waybill-formal/Dockerfile .
docker image inspect waybill-formal:local
```

The verified local digest is recorded in
`artifacts/waybill_formal/container-manifest.json`. Either push this image to
a controlled registry or transfer the frozen image archive created during
release finalization. Copy these three release files to the target:

- `waybill-formal-readiness-v1.bundle`
- `waybill-formal-readiness-v1-image.tar`
- `SHA256SUMS`

Verify and restore them on the target:

```bash
sha256sum -c SHA256SUMS
git clone --branch waybill-formal-readiness-v1 \
  waybill-formal-readiness-v1.bundle waybill_formal
cd waybill_formal
docker load -i waybill-formal-readiness-v1-image.tar
docker image inspect waybill-formal:local
```

The observed digest must match the frozen manifest. A mutable tag alone is
insufficient.

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

Run preprocessing with no caps:

```bash
python script/prepare_tier1_datasets.py \
  --dataset all \
  --data-root "$WAYBILL_DATA_ROOT" \
  --output-dir "$WAYBILL_PREPARED_ROOT" \
  --max-raw-points 0 \
  --formal

python script/materialize_waybill_formal_corpus.py \
  --prepared-root "$WAYBILL_PREPARED_ROOT" \
  --output-dir "$WAYBILL_CORPUS_ROOT"
```

The materializer must produce exactly 12 S3 canonical variants per accepted
period: four bucket sizes times three radii. It fails if any prepared period is
silently dropped.

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
WAYBILL_REQUIRED_WORKSPACE_GIB=500 \
script/check_deploy_host.sh
```

This receipt must be produced on the actual target node; a laptop receipt
cannot close RG6.

## 6. Initialize and execute the immutable run

After RG0-RG8 receipts are all `passed`, initialize once with
`script/waybill_formal.py init-run`. Existing run directories are never
overwritten. Render separate arrays so S2 main setup/proof jobs finish before
S2 concurrency jobs:

```bash
python script/waybill_formal.py render-slurm \
  --run-root "$RUN_ROOT" --stage S2 --kind main \
  --output "$RUN_ROOT/slurm/s2-main.sbatch"
python script/waybill_formal.py render-slurm \
  --run-root "$RUN_ROOT" --stage S2 --kind concurrency \
  --output "$RUN_ROOT/slurm/s2-concurrency.sbatch"
python script/waybill_formal.py render-slurm \
  --run-root "$RUN_ROOT" --stage S5 --kind corpus \
  --output "$RUN_ROOT/slurm/s5-corpus.sbatch"
python script/waybill_formal.py render-slurm \
  --run-root "$RUN_ROOT" --stage S5 --kind verifier \
  --output "$RUN_ROOT/slurm/s5-verifier.sbatch"
python script/waybill_formal.py render-slurm \
  --run-root "$RUN_ROOT" --stage S5 --kind charger \
  --output "$RUN_ROOT/slurm/s5-charger.sbatch"
```

Submit S1, S2-main, S3, S4, S2-concurrency, S5-corpus, and finally the
S5-verifier/S5-charger jobs with scheduler dependencies appropriate to the
site. Each S5 corpus job creates 100 distinct real Groth16 bundles for one of
fixes 25/100/200; verifier and charger jobs fail closed unless that immutable
corpus attempt passed. Failed jobs may be resumed once:

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
manually from logs into the paper.
