# TSIP Heatmap TDSC Final Scale Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the two interrupted V4 N=1000 units, validate all 15 dataset-seed receipts, generate deterministic scale statistics, and propagate only verified final-scale evidence into the paper and Obsidian.

**Architecture:** The existing launcher remains the execution authority and skips passed receipts. A strict standard-library summarizer validates every unit before emitting JSON, CSV, and LaTeX. The paper evidence builder then upgrades scale status from partial to verified, after which RQ6, Abstract, Conclusion, and Obsidian are updated once.

**Tech Stack:** Docker Compose, Python 3.12, pytest, JSON/CSV receipts, LaTeX/Biber, Obsidian KB helpers.

---

## Mandatory Obsidian Checkpoint

Before each task's commit step, use `apply_patch` to append the live experiment state, validated receipt path, commands/results, and remaining blocker to `memory/Research/tsip-heatmap/Daily/2026-07-13.md`. Update `Experiments/V4-Docker-N1000完整实验.md` when execution state changes and `Results/Reports/V4实验结果-2026-07.md` only after strict receipt validation. After every such update, run:

```bash
python /Users/wanghao/.agents/skills/obsidian-project-kb-core/scripts/project_kb.py sync \
  --cwd /Users/wanghao/Desktop/risefl_mvp --project-id tsip-heatmap \
  --scope tdsc-final-scale-handoff
python /Users/wanghao/.agents/skills/obsidian-project-kb-core/scripts/kb_lint.py \
  --cwd /Users/wanghao/Desktop/risefl_mvp --project-id tsip-heatmap
```

Expected: all counts remain zero.

### Task 1: Guard The Active Resume And Recover Only If It Is Stale

**Files:**
- Read: `TSIP_heatmap_version/runtime/experiments-heatmap/docker_n1000_v4/launch_status.json`
- Update by launcher: `docker_n1000_v4/rome/seed_303/clean/`
- Update by launcher: `docker_n1000_v4/synthetic/seed_303/clean/`

- [ ] **Step 1: Snapshot the launcher, unit, and container state**

```bash
cd /Users/wanghao/Desktop/risefl_mvp/TSIP_heatmap_version/runtime/experiments-heatmap
jq '{state,completed_units,total_units}' docker_n1000_v4/launch_status.json
ps -axo pid,ppid,etime,%cpu,%mem,command | \
  grep -E 'run_v4_docker_n1000_scale|run_v4_docker_protocol_smoke|caffeinate' | grep -v grep || true
for dataset in rome synthetic; do
  jq -r --arg dataset "$dataset" \
    '[$dataset, .state, (.rounds | length), (.finished_at // "null")] | @tsv' \
    "docker_n1000_v4/$dataset/seed_303/clean/status.json"
done
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | \
  grep -E 'NAMES|v4n1000_(rome|synthetic)_303' || true
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' | \
  grep -E 'NAME|v4n1000_(rome|synthetic)_303' || true
```

Expected at plan creation: launcher PID 9233 and protocol PIDs 9353/9354 exist, both unit receipts are `running`, both Compose stacks are healthy, and proof generation consumes CPU. If `launch_status.json` is already `pass` with 15/15, skip to Task 2.

- [ ] **Step 2: Classify the state without changing it**

Run:

```bash
launcher_count="$(ps -axo command | \
  grep -E 'python .*run_v4_docker_n1000_scale.py --launch' | \
  grep -v -E 'grep|caffeinate' | wc -l | tr -d ' ')"
launch_state="$(jq -r '.state' docker_n1000_v4/launch_status.json)"
if [ "$launch_state" = pass ]; then
  echo COMPLETE
elif [ "$launcher_count" -ge 1 ]; then
  echo ACTIVE
else
  echo RECOVERY_REQUIRED
fi
```

Expected: exactly one of `COMPLETE`, `ACTIVE`, or `RECOVERY_REQUIRED`.

- [ ] **Step 3: For ACTIVE, monitor and do not launch a duplicate**

Run this only when Step 2 prints `ACTIVE`:

```bash
while ps -axo command | grep -E 'python .*run_v4_docker_n1000_scale.py --launch' | \
  grep -v -E 'grep|caffeinate' >/dev/null; do
  date '+%Y-%m-%d %H:%M:%S'
  for dataset in rome synthetic; do
    jq -r --arg dataset "$dataset" \
      '[$dataset, .state, (.rounds | length), (.finished_at // "null")] | @tsv' \
      "docker_n1000_v4/$dataset/seed_303/clean/status.json"
  done
  sleep 300
done
jq '{state,completed_units,total_units,failed_units}' docker_n1000_v4/launch_status.json
```

Expected: round counts increase toward 16 and the final launcher receipt becomes 15/15 pass. A stable round count during one proof-generation interval is not by itself a hang; require no host process before recovery.

- [ ] **Step 4: For RECOVERY_REQUIRED, remove only the two stale Compose projects**

Run this only when Step 2 prints `RECOVERY_REQUIRED`:

```bash
docker compose -p v4n1000_rome_303 \
  -f /Users/wanghao/Desktop/risefl_mvp/docker-compose.yml \
  -f docker-compose.v4-smoke.yml down --remove-orphans
docker compose -p v4n1000_synthetic_303 \
  -f /Users/wanghao/Desktop/risefl_mvp/docker-compose.yml \
  -f docker-compose.v4-smoke.yml down --remove-orphans
```

Expected: ports 13301/13302/13303/13310 and 13401/13402/13403/13410 are free.

- [ ] **Step 5: For RECOVERY_REQUIRED, launch once with pass-receipt semantics**

Run this only after Step 4:

```bash
set -o pipefail
caffeinate -dimsu python -u run_v4_docker_n1000_scale.py \
  --launch --jobs 2 --round-timeout-sec 7200 \
  2>&1 | tee docker_n1000_v4/resume.log
```

Expected: every already passed unit is reported as `skipped_pass`; only units without a pass receipt execute (Rome/303 and Synthetic/303 at plan creation).

- [ ] **Step 6: Verify the launcher final receipt**

```bash
jq '{state,completed_units,total_units,failed_units}' docker_n1000_v4/launch_status.json
```

Expected: `state=pass`, `completed_units=15`, `total_units=15`, `failed_units=0`.

### Task 2: Add A Strict Fifteen-Unit Scale Summarizer

**Files:**
- Create: `script/summarize_v4_n1000_scale.py`
- Create: `tests/test_summarize_v4_n1000_scale.py`
- Generate: `docker_n1000_v4/aggregate_summary.json`
- Generate: `docker_n1000_v4/aggregate_by_dataset.csv`
- Generate: `TSIP/tables/tab_v4_n1000_scale.tex`

- [ ] **Step 1: Write validation tests**

Create `tests/test_summarize_v4_n1000_scale.py`:

```python
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "script" / "summarize_v4_n1000_scale.py"
SPEC = importlib.util.spec_from_file_location("summarize_v4_n1000_scale", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def round_row(logical_round: int) -> dict[str, object]:
    bootstrap = logical_round == 0
    evaluation = logical_round >= 6
    proofs = 0 if bootstrap else 1000
    return {
        "logical_round": logical_round,
        "phase": "evaluation" if evaluation else "warmup",
        "client_proof_attempts": proofs,
        "client_proof_generated": proofs,
        "shuffler_proof_attempts": proofs,
        "shuffler_proof_verified": proofs,
        "shuffler_proof_failed": 0,
        "received_a": 1000 if evaluation else None,
        "received_r": 1000 if evaluation else None,
        "reconstruction_ok": True if evaluation else None,
        "dp_ok": True if evaluation else None,
    }


def write_unit(root: Path, dataset: str, seed: int, *, state: str = "pass") -> Path:
    path = root / dataset / f"seed_{seed}" / "clean" / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "started_at": "2026-07-13T00:00:00Z",
        "finished_at": "2026-07-13T01:00:00Z" if state == "pass" else None,
        "config": {"dataset": dataset, "seed": seed, "clients": 1000,
                   "warmup_rounds": 6, "eval_rounds": 10,
                   "profile": "v4-paper-k6"},
        "gate": {"protocol": "pass", "paired_routes": "pass",
                 "full_groth16": "pass", "reconstruction": "pass",
                 "dp_release": "pass"},
        "rounds": [round_row(index) for index in range(16)],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def complete_tree(tmp_path: Path) -> Path:
    for dataset in MODULE.DATASETS:
        for seed in MODULE.SEEDS:
            write_unit(tmp_path, dataset, seed)
    return tmp_path


def test_summarize_accepts_exact_fifteen_unit_matrix(tmp_path: Path) -> None:
    summary = MODULE.summarize(complete_tree(tmp_path))
    assert summary["status"] == "verified"
    assert summary["units"] == 15
    assert summary["rounds"] == 240
    assert summary["evaluation_rounds"] == 150
    assert summary["proof_verified"] == 225_000
    assert summary["proof_failed"] == 0
    assert set(summary["by_dataset"]) == set(MODULE.DATASETS)


def test_missing_unit_is_rejected(tmp_path: Path) -> None:
    root = complete_tree(tmp_path)
    (root / "rome/seed_303/clean/status.json").unlink()
    with pytest.raises(MODULE.ScaleReceiptError, match="missing unit receipt"):
        MODULE.summarize(root)


def test_partial_unit_is_rejected(tmp_path: Path) -> None:
    root = complete_tree(tmp_path)
    write_unit(root, "synthetic", 303, state="running")
    with pytest.raises(MODULE.ScaleReceiptError, match="unit not pass"):
        MODULE.summarize(root)


def test_route_mismatch_is_rejected(tmp_path: Path) -> None:
    root = complete_tree(tmp_path)
    path = root / "tdrive/seed_101/clean/status.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rounds"][6]["received_a"] = 999
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MODULE.ScaleReceiptError, match="route count mismatch"):
        MODULE.summarize(root)


def test_proof_accounting_mismatch_is_rejected(tmp_path: Path) -> None:
    root = complete_tree(tmp_path)
    path = root / "geolife/seed_202/clean/status.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rounds"][7]["shuffler_proof_failed"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MODULE.ScaleReceiptError, match="proof accounting mismatch"):
        MODULE.summarize(root)
```

- [ ] **Step 2: Run tests before implementation**

```bash
python -m pytest -q tests/test_summarize_v4_n1000_scale.py
```

Expected: import/file-not-found failure.

- [ ] **Step 3: Implement strict receipt validation**

Create `script/summarize_v4_n1000_scale.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any


DATASETS = ("tdrive", "geolife", "porto", "rome", "synthetic")
SEEDS = (101, 202, 303)
LABELS = {"tdrive": "T-Drive", "geolife": "GeoLife", "porto": "Porto",
          "rome": "Rome", "synthetic": "Synthetic"}
REQUIRED_GATES = ("protocol", "paired_routes", "full_groth16",
                  "reconstruction", "dp_release")
EXPECTED_PROOFS_PER_UNIT = 15_000


class ScaleReceiptError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ScaleReceiptError(f"missing unit receipt: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScaleReceiptError(f"invalid unit receipt {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ScaleReceiptError(f"unit receipt is not an object: {path}")
    return payload


def validate_unit(path: Path, dataset: str, seed: int) -> dict[str, object]:
    payload = read_json(path)
    rounds = payload.get("rounds", [])
    warmup = [row for row in rounds if row.get("phase") == "warmup"]
    evaluation = [row for row in rounds if row.get("phase") == "evaluation"]
    if payload.get("state") != "pass" or not payload.get("finished_at"):
        raise ScaleReceiptError(f"unit not pass: {dataset}/{seed}")
    config = payload.get("config", {})
    expected_config = {"dataset": dataset, "seed": seed, "clients": 1000,
                       "warmup_rounds": 6, "eval_rounds": 10,
                       "profile": "v4-paper-k6"}
    if any(config.get(key) != value for key, value in expected_config.items()):
        raise ScaleReceiptError(f"unit config mismatch: {dataset}/{seed}")
    gate = payload.get("gate", {})
    if any(gate.get(name) != "pass" for name in REQUIRED_GATES):
        raise ScaleReceiptError(f"unit gate mismatch: {dataset}/{seed}")
    if len(rounds) != 16 or len(warmup) != 6 or len(evaluation) != 10:
        raise ScaleReceiptError(f"round count mismatch: {dataset}/{seed}")
    if [row.get("logical_round") for row in rounds] != list(range(16)):
        raise ScaleReceiptError(f"logical round mismatch: {dataset}/{seed}")
    if [row.get("phase") for row in rounds] != ["warmup"] * 6 + ["evaluation"] * 10:
        raise ScaleReceiptError(f"round phase mismatch: {dataset}/{seed}")
    for row in evaluation:
        if row.get("received_a") != 1000 or row.get("received_r") != 1000:
            raise ScaleReceiptError(f"route count mismatch: {dataset}/{seed}")
        if row.get("reconstruction_ok") is not True or row.get("dp_ok") is not True:
            raise ScaleReceiptError(f"release gate mismatch: {dataset}/{seed}")
    client_attempted = sum(int(row.get("client_proof_attempts", 0)) for row in rounds)
    attempted = sum(int(row.get("shuffler_proof_attempts", 0)) for row in rounds)
    verified = sum(int(row.get("shuffler_proof_verified", 0)) for row in rounds)
    failed = sum(int(row.get("shuffler_proof_failed", 0)) for row in rounds)
    generated = sum(int(row.get("client_proof_generated", 0)) for row in rounds)
    if (failed != 0
            or client_attempted != EXPECTED_PROOFS_PER_UNIT
            or generated != EXPECTED_PROOFS_PER_UNIT
            or attempted != EXPECTED_PROOFS_PER_UNIT
            or verified != EXPECTED_PROOFS_PER_UNIT):
        raise ScaleReceiptError(f"proof accounting mismatch: {dataset}/{seed}")
    started = datetime.fromisoformat(payload["started_at"].replace("Z", "+00:00"))
    finished = datetime.fromisoformat(payload["finished_at"].replace("Z", "+00:00"))
    wall_seconds = (finished - started).total_seconds()
    if wall_seconds <= 0:
        raise ScaleReceiptError(f"non-positive unit duration: {dataset}/{seed}")
    return {"dataset": dataset, "seed": seed, "rounds": 16,
            "evaluation_rounds": 10, "proof_generated": generated,
            "proof_verified": verified, "proof_failed": failed,
            "wall_seconds": wall_seconds,
            "proofs_per_second": verified / wall_seconds,
            "receipt_sha256": sha256(path)}


def summarize(root: Path) -> dict[str, Any]:
    units = [
        validate_unit(root / dataset / f"seed_{seed}" / "clean" / "status.json",
                      dataset, seed)
        for dataset in DATASETS
        for seed in SEEDS
    ]
    by_dataset: dict[str, dict[str, float | int]] = {}
    for dataset in DATASETS:
        selected = [row for row in units if row["dataset"] == dataset]
        rates = [float(row["proofs_per_second"]) for row in selected]
        walls = [float(row["wall_seconds"]) for row in selected]
        by_dataset[dataset] = {
            "units": len(selected),
            "proofs_per_second_mean": statistics.mean(rates),
            "proofs_per_second_std": statistics.stdev(rates),
            "wall_seconds_mean": statistics.mean(walls),
            "wall_seconds_std": statistics.stdev(walls),
        }
    return {
        "schema_version": 1,
        "status": "verified",
        "datasets": list(DATASETS),
        "seeds": list(SEEDS),
        "units": len(units),
        "rounds": sum(int(row["rounds"]) for row in units),
        "evaluation_rounds": sum(int(row["evaluation_rounds"]) for row in units),
        "proof_generated": sum(int(row["proof_generated"]) for row in units),
        "proof_verified": sum(int(row["proof_verified"]) for row in units),
        "proof_failed": sum(int(row["proof_failed"]) for row in units),
        "by_dataset": by_dataset,
        "unit_receipts": units,
    }


def render_tex(summary: dict[str, Any]) -> str:
    lines = [
        "% Generated by script/summarize_v4_n1000_scale.py; do not edit.",
        r"\begin{table}[t]", r"\centering", r"\scriptsize",
        r"\caption{Manifest-bound Groth16 N=1000 end-to-end execution across three seeds. Throughput is the mean and sample standard deviation of per-unit accepted proofs per wall-clock second.}",
        r"\label{tab:v4-n1000-scale}", r"\begin{tabular}{lrr}",
        r"\toprule", r"Dataset & Proofs/s & Wall time (h) \\", r"\midrule",
    ]
    for dataset in DATASETS:
        row = summary["by_dataset"][dataset]
        lines.append(
            f"{LABELS[dataset]} & {row['proofs_per_second_mean']:.3f} $\\pm$ "
            f"{row['proofs_per_second_std']:.3f} & "
            f"{row['wall_seconds_mean'] / 3600:.3f} $\\pm$ "
            f"{row['wall_seconds_std'] / 3600:.3f} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}", ""])
    return "\n".join(lines)


def write_outputs(summary: dict[str, Any], out_json: Path,
                  out_csv: Path, out_tex: Path) -> None:
    for path in (out_json, out_csv, out_tex):
        path.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "dataset", "units", "proofs_per_second_mean", "proofs_per_second_std",
            "wall_seconds_mean", "wall_seconds_std",
        ])
        writer.writeheader()
        for dataset in DATASETS:
            writer.writerow({"dataset": dataset, **summary["by_dataset"][dataset]})
    out_tex.write_text(render_tex(summary), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-csv", type=Path, required=True)
    parser.add_argument("--out-tex", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = summarize(args.root)
    write_outputs(summary, args.out_json, args.out_csv, args.out_tex)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests and real aggregation**

```bash
python -m pytest -q tests/test_summarize_v4_n1000_scale.py
python script/summarize_v4_n1000_scale.py \
  --root TSIP_heatmap_version/runtime/experiments-heatmap/docker_n1000_v4 \
  --out-json TSIP_heatmap_version/runtime/experiments-heatmap/docker_n1000_v4/aggregate_summary.json \
  --out-csv TSIP_heatmap_version/runtime/experiments-heatmap/docker_n1000_v4/aggregate_by_dataset.csv \
  --out-tex TSIP/tables/tab_v4_n1000_scale.tex
```

Expected: status verified, 15 units, 240 total rounds, 150 evaluation rounds, zero proof failures.

- [ ] **Step 5: Commit the summarizer and generated receipts**

```bash
git add script/summarize_v4_n1000_scale.py tests/test_summarize_v4_n1000_scale.py \
  TSIP_heatmap_version/runtime/experiments-heatmap/docker_n1000_v4/aggregate_summary.json \
  TSIP_heatmap_version/runtime/experiments-heatmap/docker_n1000_v4/aggregate_by_dataset.csv \
  TSIP/tables/tab_v4_n1000_scale.tex
git commit --only -m "feat: summarize verified V4 N1000 scale receipts" -- \
  script/summarize_v4_n1000_scale.py tests/test_summarize_v4_n1000_scale.py \
  TSIP_heatmap_version/runtime/experiments-heatmap/docker_n1000_v4/aggregate_summary.json \
  TSIP_heatmap_version/runtime/experiments-heatmap/docker_n1000_v4/aggregate_by_dataset.csv \
  TSIP/tables/tab_v4_n1000_scale.tex
```

### Task 3: Propagate Final Scale Evidence Once

**Files:**
- Regenerate: `docker_v4_smoke/analysis_v4/paper_evidence.json`
- Modify: `TSIP/main.tex`
- Add: `TSIP/tables/tab_v4_n1000_scale.tex`
- Modify: `TSIP/CLAIM_EVIDENCE_MAP.md`

- [ ] **Step 1: Rebuild the paper evidence bundle**

```bash
cd /Users/wanghao/Desktop/risefl_mvp
python script/build_v4_paper_evidence.py \
  --repo /Users/wanghao/Desktop/risefl_mvp \
  --manifest TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/manifest.json \
  --static TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/static/gate_status.json \
  --protocol TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/protocol_clean_five_dataset_v2/suite_status.json \
  --utility TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/utility/three_seed_n1000/fair_fixed_comparison.json \
  --launch TSIP_heatmap_version/runtime/experiments-heatmap/docker_n1000_v4/launch_status.json \
  --scale-summary TSIP_heatmap_version/runtime/experiments-heatmap/docker_n1000_v4/aggregate_summary.json \
  --out-json TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json \
  --out-macros TSIP/tables/v4_paper_evidence_macros.tex \
  --out-table TSIP/tables/tab_v4_fixed_utility.tex
jq '.scale' TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json
```

Expected: `scale.status=verified`, 15/15, and a non-null strict-summary SHA-256.

- [ ] **Step 2: Add the final scale table to RQ6**

Insert `\input{tables/tab_v4_n1000_scale}` and describe mean plus seed variability. Do not report only the fastest dataset or seed.

- [ ] **Step 3: Update Abstract and Conclusion conservatively**

Add one compact statement that the full manifest-bound Groth16 path completed 15 dataset-seed units at N=1000 with zero proof failures. Keep the physical-presence and in-envelope limitations unchanged.

- [ ] **Step 4: Upgrade claim-evidence rows**

Change only scale rows from `partial` to `supported`, linking `aggregate_summary.json` and the 15 unit receipts.

- [ ] **Step 5: Run manuscript and receipt gates**

```bash
python script/check_heatmap_manuscript.py \
  --tex TSIP/main.tex \
  --evidence TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json
python -m pytest -q tests/test_build_v4_paper_evidence.py \
  tests/test_check_heatmap_manuscript.py tests/test_summarize_v4_n1000_scale.py
```

Expected: zero issues and all tests pass.

- [ ] **Step 6: Commit final-scale paper propagation**

```bash
git add TSIP/main.tex TSIP/CLAIM_EVIDENCE_MAP.md TSIP/tables/tab_v4_n1000_scale.tex \
  TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json
git commit --only -m "docs: propagate verified V4 N1000 scale evidence" -- \
  TSIP/main.tex TSIP/CLAIM_EVIDENCE_MAP.md TSIP/tables/tab_v4_n1000_scale.tex \
  TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json
```

### Task 4: Final Build, Visual Review, And Obsidian Promotion

**Files:**
- Generate: `TSIP/main.pdf`
- Synchronize: `TSIP_heatmap_version/paper/main.tex`
- Modify: `memory/Research/tsip-heatmap/00-Hub.md`
- Modify: `memory/Research/tsip-heatmap/01-Plan.md`
- Modify: `memory/Research/tsip-heatmap/Experiments/V4-Docker-N1000完整实验.md`
- Modify: `memory/Research/tsip-heatmap/Results/Reports/V4实验结果-2026-07.md`
- Modify: `memory/Research/tsip-heatmap/Daily/2026-07-13.md`

- [ ] **Step 1: Repeat the clean LaTeX build and all-page visual inspection**

```bash
cd /Users/wanghao/Desktop/risefl_mvp/TSIP
rm -f main.aux main.bbl main.bcf main.blg main.log main.out main.run.xml
pdflatex -interaction=nonstopmode -halt-on-error main.tex
biber main
pdflatex -interaction=nonstopmode -halt-on-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error main.tex
grep -E 'Undefined|undefined references|Citation.*undefined|LaTeX Error|Fatal error|Please.*rerun' \
  main.log main.blg && exit 1 || true
grep -E 'Overfull|Underfull|LaTeX Warning|Package .* Warning' main.log > \
  /tmp/tsip-heatmap-final-latex-warnings.txt || true
cat /tmp/tsip-heatmap-final-latex-warnings.txt
pdfinfo main.pdf | grep -E 'Pages|Page size|File size'
rm -rf /tmp/tsip-heatmap-final-pages
mkdir -p /tmp/tsip-heatmap-final-pages
pdftoppm -png -r 144 main.pdf /tmp/tsip-heatmap-final-pages/page
```

Inspect every rendered PNG with `view_image`. Expected: clean references, a fresh page count, and no clipped tables, unreadable labels, blank float regions, overlapping text, inconsistent captions, or missing assets.

- [ ] **Step 2: Synchronize the verified canonical source**

```bash
cd /Users/wanghao/Desktop/risefl_mvp
cp TSIP/main.tex TSIP_heatmap_version/paper/main.tex
cp TSIP/reference.bib TSIP_heatmap_version/paper/reference.bib
cmp TSIP/main.tex TSIP_heatmap_version/paper/main.tex
cmp TSIP/reference.bib TSIP_heatmap_version/paper/reference.bib
```

Expected: both `cmp` commands exit 0.

- [ ] **Step 3: Promote Obsidian statuses**

Set Experiment status to `verified`, Result status to `verified`, check all scale tasks in Plan, update Hub to submission-package focus, and append aggregate receipt paths and statistics to Daily. Never delete the historical interrupted checkpoint.

- [ ] **Step 4: Run KB lint**

```bash
python /Users/wanghao/.agents/skills/obsidian-project-kb-core/scripts/project_kb.py sync \
  --cwd /Users/wanghao/Desktop/risefl_mvp --project-id tsip-heatmap \
  --scope tdsc-final-scale-handoff
python /Users/wanghao/.agents/skills/obsidian-project-kb-core/scripts/kb_lint.py \
  --cwd /Users/wanghao/Desktop/risefl_mvp --project-id tsip-heatmap
```

Expected: every count is zero.

- [ ] **Step 5: Commit the final verified checkpoint**

```bash
git add TSIP/main.pdf TSIP_heatmap_version/paper/main.tex \
  memory/Research/tsip-heatmap
git commit --only -m "docs: finalize verified SHTPC scale evidence" -- \
  TSIP/main.pdf TSIP_heatmap_version/paper/main.tex \
  memory/Research/tsip-heatmap
```
