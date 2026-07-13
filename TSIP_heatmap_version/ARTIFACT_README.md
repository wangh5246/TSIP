# TSIP Heatmap V4 Artifact Guide

This is the Heatmap-specific artifact index. It separates static circuit
evidence, protocol smoke, fixed utility, and full-scale execution because those
layers answer different research questions and must not be substituted for one
another.

## Evidence Index

| Evidence | Canonical path | Current interpretation |
|---|---|---|
| Static and cryptographic gate | `runtime/experiments-heatmap/docker_v4_smoke/static/gate_status.json` | 22/22 checks pass for archive compatibility, the current paper circuit, negative witnesses, and route binding. |
| Artifact manifest | `runtime/experiments-heatmap/docker_v4_smoke/manifest.json` | Binds circuit/runtime hashes, public-signal order, tool versions, and the development setup label. |
| Five-dataset protocol smoke | `runtime/experiments-heatmap/docker_v4_smoke/protocol_clean_five_dataset_v2/suite_status.json` | Five datasets pass at 10 clients, 2 warmup rounds, and 6 evaluation rounds. |
| Fixed utility | `runtime/experiments-heatmap/docker_v4_smoke/utility/three_seed_n1000/status.json` | Five datasets, three seeds, 1,000 users, and ten windows pass at the fixed paper configuration. |
| Publication figure | `../TSIP/figures/v4_fixed_utility_heatmap.pdf` | Deterministic paper figure copied from `docker_v4_smoke/analysis_v4/figures/`. |
| Scale launcher | `runtime/experiments-heatmap/run_v4_docker_n1000_scale.py` | Builds the 5 by 3 N=1000 Docker execution matrix with bounded concurrency. |
| Scale launcher receipt | `runtime/experiments-heatmap/docker_n1000_v4/launch_status.json` | Records 15/15 unit execution pass; this launcher receipt alone is not a verified aggregate performance result. |
| Scale unit receipts | `runtime/experiments-heatmap/docker_n1000_v4/<dataset>/seed_<seed>/clean/status.json` | Fifteen per-dataset/per-seed protocol receipts used by the strict aggregate builder. |
| Paper evidence bundle | `runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json` | Hash-bound manuscript facts; scale remains partial until a strict aggregate receipt validates all unit hashes. |

The five-dataset source manifest is
`runtime/experiments-heatmap/five_dataset_inputs/manifest.json`. The row-level
JSONL inputs are local data products and are intentionally excluded from the
repository. See `../DATA_NOTICE.md` before acquiring or preparing data.

## Environment

The recorded passing manifest used Python 3.10.20, Node.js 20.20.2, Circom
2.1.9, snarkjs 0.7.6, Docker Server 29.1.3, and Docker Compose. Reproduction
also requires sufficient Docker CPU/memory capacity, free experiment ports,
`jq` for receipt inspection, and the Python dependencies used by the repository
test suite. `caffeinate` is optional and macOS-specific; Linux users can invoke
the scale Python command directly or use their system's sleep inhibitor.

The checked-in Groth16 proving and verification material was generated with a
development setup. It is suitable for reproducing these measurements, but it
is not evidence of a production multi-party ceremony and must not be presented
as production-ready trust setup.

## Data Preparation

Acquire the four real datasets from the official provider pages in
`../DATA_NOTICE.md`, place them in the expected local `dataset/` locations, and
then run from the experiment directory:

```bash
python prepare_five_dataset_heatmap_inputs.py \
  --users 1000 \
  --windows 10 \
  --seed 20260709 \
  --no-bootstrap
```

The command must produce a manifest showing `source_rows: 1000` and
`bootstrap: false` for every real dataset. Do not commit the generated JSONL
files.

## Static Gate

Run from the repository root:

```bash
python TSIP_heatmap_version/runtime/experiments-heatmap/run_v4_static_crypto_smoke.py \
  --repo-root "$PWD" \
  --out-dir "$PWD/TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/static"
```

Pass condition: `gate_status.json` has `state == "pass"`, 22 passed checks, and
zero failed checks.

## Five-Dataset Protocol Smoke

Run from `TSIP_heatmap_version/runtime/experiments-heatmap`:

```bash
python run_v4_docker_clean_suite.py \
  --datasets tdrive geolife porto rome synthetic \
  --clients 10 \
  --warmup-rounds 2 \
  --eval-rounds 6 \
  --seed 20260711 \
  --port-start 10100 \
  --out-dir docker_v4_smoke/protocol_clean_five_dataset_v2
```

Pass condition: the suite receipt reports five datasets, five passes, and
`state == "pass"`.

## Fixed Utility

Run from the experiment directory:

```bash
python run_v4_utility_compare.py \
  --input-dir five_dataset_inputs \
  --datasets tdrive geolife porto rome synthetic \
  --seeds 101 202 303 \
  --users 1000 \
  --rounds 10 \
  --malicious-rate 0.1 \
  --epsilons 5 \
  --taus 2 \
  --main-epsilon 5 \
  --main-tau 2 \
  --out-dir docker_v4_smoke/utility/three_seed_n1000
```

Regenerate the publication figure with:

```bash
python make_v4_fair_heatmap.py
```

Copy the resulting PDF to `TSIP/figures/v4_fixed_utility_heatmap.pdf` only after
checking that its SHA-256 digest matches the expected evidence record.

## N=1000 Docker Matrix

First write and inspect the preflight plan:

```bash
python -u run_v4_docker_n1000_scale.py \
  --dry-run \
  --jobs 2 \
  --round-timeout-sec 7200
jq '.gates' docker_n1000_v4/launch_plan.json
```

Every gate must pass. A busy port is a real preflight failure and must be freed
or assigned a non-conflicting port range before launch. On macOS, launch with:

```bash
caffeinate -dimsu python -u run_v4_docker_n1000_scale.py \
  --launch \
  --jobs 2 \
  --round-timeout-sec 7200
```

On Linux, omit `caffeinate`. Passed units are skipped by default; do not add
`--rerun-passed` unless deliberately replacing valid receipts.

Monitor without `rg`:

```bash
ps -axo pid,ppid,etime,%cpu,%mem,command \
  | grep -E 'run_v4_docker_n1000_scale|run_v4_docker_protocol_smoke|caffeinate' \
  | grep -v grep
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' \
  | grep -E 'NAMES|v4n1000'
docker stats --no-stream \
  --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' \
  | grep -E 'NAME|v4n1000'
jq '{state,completed_units,failed_units,total_units,failure}' \
  docker_n1000_v4/launch_status.json
```

The final paper may use scale metrics only after the strict aggregate command
produces an aggregate receipt that validates all 15 unit receipt hashes and is
then bound into `paper_evidence.json`. A 15/15 launcher pass is necessary but
not sufficient for a latency or throughput claim.

## Internal Quality-Control Records

Simulated reviewer reports, self-review notes, and claim maps are internal
quality-control artifacts. They are not independent peer review, experimental
observations, or evidence that a venue accepted the work.
