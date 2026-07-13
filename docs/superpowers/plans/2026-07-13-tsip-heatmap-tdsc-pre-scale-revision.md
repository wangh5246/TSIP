# TSIP Heatmap TDSC Pre-Scale Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a freshly compiled, evidence-aligned TDSC manuscript and reproducibility package using all verified V4 evidence that does not depend on the final two N=1000 scale units.

**Architecture:** `TSIP/main.tex` remains the canonical manuscript. A small standard-library evidence builder validates the V4 manifest, gate receipts, and fixed utility JSON before generating deterministic JSON and LaTeX artifacts. A separate manuscript checker enforces abstract length, artifact facts, dataset coverage, and the partial-scale claim boundary. The newer isolated paper copy is treated as a source of candidate edits and is synchronized from the canonical manuscript only after verification.

**Tech Stack:** Python 3.12 standard library, pytest, Circom/snarkjs receipts, LaTeX/Biber/IEEEtran, Poppler, Obsidian project KB helpers, Git.

---

## File Map

- `TSIP/main.tex`: canonical manuscript and only hand-edited paper source.
- `TSIP/reference.bib`: canonical bibliography.
- `TSIP/tables/v4_paper_evidence_macros.tex`: generated current-paper circuit and gate macros.
- `TSIP/tables/tab_v4_fixed_utility.tex`: generated fixed fair five-dataset utility table.
- `TSIP/figures/v4_fixed_utility_heatmap.pdf`: generated fixed fair utility figure.
- `TSIP/CLAIM_EVIDENCE_MAP.md`: reviewer-facing claim-to-artifact audit.
- `TSIP/CITATION_AUDIT.md`: metadata and claim-support audit for new and high-risk references.
- `script/build_v4_paper_evidence.py`: deterministic receipt validator and LaTeX exporter.
- `script/check_heatmap_manuscript.py`: manuscript contract checker.
- `tests/test_build_v4_paper_evidence.py`: evidence-builder unit tests.
- `tests/test_check_heatmap_manuscript.py`: manuscript-checker unit tests.
- `DATA_NOTICE.md`: five-dataset provenance and redistribution policy.
- `LICENSE`: repository license, created only after an explicit author ownership/license decision.
- `TSIP_heatmap_version/ARTIFACT_README.md`: Heatmap-specific reproduction index.
- `docs/submission/TSIP_HEATMAP_AUTHOR_CONFIRMATIONS.md`: author-controlled submission declarations.
- `TSIP_heatmap_version/paper/main.tex`: verified mirror of the canonical manuscript, updated only after the build gate.
- `memory/Research/tsip-heatmap/`: progress and evidence write-back.

## Mandatory Obsidian Checkpoint

Before each task's commit step, use `apply_patch` to append one line to `memory/Research/tsip-heatmap/Daily/2026-07-13.md` with the task number, files changed, verification command/result, evidence status, and unresolved blocker. Update the domain note immediately when facts change: circuit facts in `Knowledge/V4方法与证据边界.md`, writing facts in `Writing/论文修订与投稿决策.md`, and experiment/result facts only in their respective notes. Then run:

```bash
python /Users/wanghao/.agents/skills/obsidian-project-kb-core/scripts/project_kb.py sync \
  --cwd /Users/wanghao/Desktop/risefl_mvp --project-id tsip-heatmap \
  --scope tdsc-pre-scale-revision
python /Users/wanghao/.agents/skills/obsidian-project-kb-core/scripts/kb_lint.py \
  --cwd /Users/wanghao/Desktop/risefl_mvp --project-id tsip-heatmap
```

Expected: every lint count is zero. Do not begin the next task while the KB checkpoint is stale or lint fails.

### Task 1: Preserve And Canonicalize The Active Manuscript

**Files:**
- Preserve: `TSIP/main.tex`
- Compare: `TSIP_heatmap_version/paper/main.tex`
- Update: `memory/Research/tsip-heatmap/Daily/2026-07-13.md`

- [ ] **Step 1: Record both manuscript identities**

Run:

```bash
cd /Users/wanghao/Desktop/risefl_mvp
printf 'HEAD '; git show HEAD:TSIP/main.tex | shasum -a 256
printf 'canonical-working '; shasum -a 256 TSIP/main.tex
printf 'isolated-paper '; shasum -a 256 TSIP_heatmap_version/paper/main.tex
git status --porcelain=v2 -- TSIP/main.tex TSIP_heatmap_version/paper/main.tex
```

Expected: three distinct identities are printed; `TSIP/main.tex` shows staged deletion plus an untracked replacement.

- [ ] **Step 2: Preserve the untracked canonical replacement in Git object storage**

Run:

```bash
git hash-object -w TSIP/main.tex
```

Expected: output equals the SHA-1 printed by `git hash-object TSIP/main.tex` and can be recovered with `git cat-file blob <sha>`.

- [ ] **Step 3: Review the isolated-paper delta without copying it**

Run:

```bash
diff -u TSIP/main.tex TSIP_heatmap_version/paper/main.tex | sed -n '1,420p'
```

Expected: the material differences are confined to the five-dataset Evaluation edits and generated-paper context; no blind overwrite is performed.

- [ ] **Step 4: Restore an intentional tracked state for the canonical manuscript**

Run:

```bash
git add -- TSIP/main.tex
git status --short -- TSIP/main.tex
git commit --only -m "chore: preserve active heatmap manuscript" -- TSIP/main.tex
```

Expected: the commit records `TSIP/main.tex` as a tracked modification while unrelated staged changes remain staged and uncommitted.

- [ ] **Step 5: Write the preservation receipt to Obsidian**

Append the working blob hash, isolated-paper hash, preservation commit, and canonical-source decision to `Daily/2026-07-13.md`. Do not mark any writing task complete yet.

### Task 2: Build A Deterministic V4 Paper Evidence Bundle

**Files:**
- Create: `script/build_v4_paper_evidence.py`
- Create: `tests/test_build_v4_paper_evidence.py`
- Generate: `TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json`
- Generate: `TSIP/tables/v4_paper_evidence_macros.tex`
- Generate: `TSIP/tables/tab_v4_fixed_utility.tex`

- [ ] **Step 1: Write tests for manifest validation and fixed utility rendering**

Create `tests/test_build_v4_paper_evidence.py` with these behaviors:

```python
import hashlib
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "script" / "build_v4_paper_evidence.py"
SPEC = importlib.util.spec_from_file_location("build_v4_paper_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixture_tree(tmp_path: Path) -> dict[str, Path]:
    artifact = tmp_path / "artifact.r1cs"
    artifact.write_bytes(b"paper-r1cs")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    static = tmp_path / "static.json"
    protocol = tmp_path / "protocol.json"
    utility = tmp_path / "utility.json"
    launch = tmp_path / "launch.json"
    scale_summary = tmp_path / "aggregate_summary.json"
    write_json(manifest, {
        "profile": "v4-paper-k6",
        "r1cs": {"wires": 3550, "constraints": 3547,
                 "private_inputs": 25, "public_inputs": 16, "outputs": 0},
        "public_signal_order": list(MODULE.PUBLIC_SIGNALS),
        "artifacts": {"r1cs": {"path": "artifact.r1cs", "sha256": digest}},
        "setup": "development Groth16 setup; not a production ceremony",
    })
    write_json(static, {"state": "pass", "summary": {"passed": 22, "failed": 0}})
    write_json(protocol, {"state": "pass", "dataset_count": 5, "pass_count": 5,
                          "results": [{"dataset": name} for name in MODULE.DATASETS]})
    rows = []
    for name in MODULE.DATASETS:
        rows.append({
            "dataset": name, "fixed_epsilon": 5, "fixed_tau": 2,
            "proposed_avg_jaccard": 0.7, "proposed_std_jaccard": 0.02,
            "strongest_baseline": "nebula", "baseline_avg_jaccard": 0.6,
            "baseline_std_jaccard": 0.01, "delta_jaccard": 0.1,
            "proposed_frr": 0, "proposed_mrr": 1, "pass": True,
        })
    write_json(utility, {"epsilon": 5, "tau": 2, "pass": True, "rows": rows})
    write_json(launch, {"state": "running", "completed_units": 13,
                        "total_units": 15, "results": []})
    return {"repo": tmp_path, "manifest": manifest, "static": static,
            "protocol": protocol, "utility": utility, "launch": launch,
            "scale_summary": scale_summary}


def test_collect_evidence_separates_verified_and_partial_layers(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    evidence = MODULE.collect_evidence(**paths)
    assert evidence["circuit"]["constraints"] == 3547
    assert evidence["circuit"]["public_inputs"] == 16
    assert evidence["circuit"]["private_inputs"] == 25
    assert evidence["gates"] == {"static": "pass", "protocol": "pass", "utility": "pass"}
    assert evidence["scale"]["status"] == "partial"
    assert evidence["scale"]["completed_units"] == 13
    assert len(evidence["fixed_utility"]) == 5


def test_collect_evidence_rejects_manifest_hash_mismatch(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    (tmp_path / "artifact.r1cs").write_bytes(b"tampered")
    try:
        MODULE.collect_evidence(**paths)
    except MODULE.EvidenceError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("hash mismatch must fail evidence collection")


def test_rendered_tex_uses_current_artifact_and_five_datasets(tmp_path: Path) -> None:
    evidence = MODULE.collect_evidence(**fixture_tree(tmp_path))
    macros = MODULE.render_macros(evidence)
    table = MODULE.render_utility_table(evidence)
    assert r"\newcommand{\VFourConstraints}{3{,}547}" in macros
    assert r"\newcommand{\VFourPublicInputs}{16}" in macros
    assert all(label in table for label in ("T-Drive", "GeoLife", "Porto", "Rome", "Synthetic"))
    assert "SHTPC $\\pm$ std" in table
    assert "Nebula $\\pm$ std" in table
    assert "FRR" in table and "MRR" in table
    assert "partial" not in table


def test_launch_pass_is_not_verified_without_strict_summary(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    write_json(paths["launch"], {"state": "pass", "completed_units": 15,
                                 "total_units": 15, "failed_units": 0})
    evidence = MODULE.collect_evidence(**paths)
    assert evidence["scale"]["status"] == "partial"


def test_strict_summary_upgrades_scale_to_verified(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    write_json(paths["launch"], {"state": "pass", "completed_units": 15,
                                 "total_units": 15, "failed_units": 0})
    write_json(paths["scale_summary"], {
        "status": "verified", "units": 15, "rounds": 240,
        "evaluation_rounds": 150, "proof_failed": 0,
    })
    evidence = MODULE.collect_evidence(**paths)
    assert evidence["scale"]["status"] == "verified"
    assert evidence["scale"]["summary_sha256"] == MODULE.sha256(paths["scale_summary"])
```

- [ ] **Step 2: Run the tests and confirm the module is absent**

Run:

```bash
python -m pytest -q tests/test_build_v4_paper_evidence.py
```

Expected: collection fails because `script/build_v4_paper_evidence.py` does not exist.

- [ ] **Step 3: Implement the evidence builder**

Create `script/build_v4_paper_evidence.py` with this public interface and behavior:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DATASETS = ("tdrive", "geolife", "porto", "rome", "synthetic")
PUBLIC_SIGNALS = (
    "hash_prev", "hash_curr", "hash_anchor", "step_dt_sq", "tier_vmax_sq",
    "tier_anchor_cap_sq", "cap_policy_sq", "primary_commitment",
    "payload_commitment_v2", "share_content_commitment_a",
    "share_content_commitment_r", "context_commitment", "blob_hash",
    "secret_commitment", "modeset_commitment", "mode_tag",
)


class EvidenceError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(repo: Path, manifest: dict[str, Any]) -> None:
    for name, item in manifest.get("artifacts", {}).items():
        path = repo / str(item["path"])
        if not path.is_file():
            raise EvidenceError(f"missing manifest artifact {name}: {path}")
        actual = sha256(path)
        if actual != item["sha256"]:
            raise EvidenceError(f"manifest hash mismatch for {name}: {actual}")


def collect_evidence(*, repo: Path, manifest: Path, static: Path,
                     protocol: Path, utility: Path, launch: Path,
                     scale_summary: Path | None) -> dict[str, Any]:
    manifest_data = load_json(manifest)
    static_data = load_json(static)
    protocol_data = load_json(protocol)
    utility_data = load_json(utility)
    launch_data = load_json(launch)
    verify_manifest(repo, manifest_data)
    if (static_data.get("state") != "pass"
            or static_data.get("summary") != {"failed": 0, "passed": 22}):
        raise EvidenceError("static gate is not pass")
    protocol_datasets = {row.get("dataset") for row in protocol_data.get("results", [])}
    if (protocol_data.get("state") != "pass"
            or protocol_data.get("pass_count") != 5
            or protocol_datasets != set(DATASETS)):
        raise EvidenceError("five-dataset protocol gate is not pass")
    if utility_data.get("pass") is not True:
        raise EvidenceError("fixed utility gate is not pass")
    rows = utility_data.get("rows")
    if not isinstance(rows, list) or {row.get("dataset") for row in rows} != set(DATASETS):
        raise EvidenceError("fixed utility rows do not cover exactly five datasets")
    if not all(row.get("pass") is True for row in rows):
        raise EvidenceError("one or more fixed utility rows failed")
    epsilon, tau = utility_data.get("epsilon"), utility_data.get("tau")
    if (epsilon, tau) != (5, 2) or not all(
        (row.get("fixed_epsilon"), row.get("fixed_tau")) == (epsilon, tau)
        for row in rows
    ):
        raise EvidenceError("fixed utility configuration is not epsilon=5, tau=2")
    completed = int(launch_data.get("completed_units", 0))
    total = int(launch_data.get("total_units", 0))
    scale_data = load_json(scale_summary) if scale_summary and scale_summary.is_file() else None
    scale_verified = (
        launch_data.get("state") == "pass"
        and completed == total == 15
        and launch_data.get("failed_units") == 0
        and scale_data is not None
        and scale_data.get("status") == "verified"
        and scale_data.get("units") == 15
        and scale_data.get("rounds") == 240
        and scale_data.get("evaluation_rounds") == 150
        and scale_data.get("proof_failed") == 0
    )
    scale_status = "verified" if scale_verified else "partial"
    counts = manifest_data.get("r1cs", {})
    expected = {"constraints": 3547, "public_inputs": 16,
                "private_inputs": 25, "wires": 3550, "outputs": 0}
    if any(int(counts.get(key, -1)) != value for key, value in expected.items()):
        raise EvidenceError(f"unexpected manifest-bound paper R1CS: {counts}")
    if tuple(manifest_data.get("public_signal_order", [])) != PUBLIC_SIGNALS:
        raise EvidenceError("unexpected public-signal order")
    return {
        "schema_version": 1,
        "profile": manifest_data.get("profile"),
        "setup_scope": manifest_data.get("setup"),
        "circuit": {key: int(counts[key]) for key in expected},
        "public_signal_order": list(PUBLIC_SIGNALS),
        "artifact_hashes": {name: item["sha256"] for name, item in manifest_data["artifacts"].items()},
        "gates": {"static": "pass", "protocol": "pass", "utility": "pass"},
        "fixed_config": {"epsilon": epsilon, "tau": tau},
        "fixed_utility": sorted(rows, key=lambda row: DATASETS.index(row["dataset"])),
        "scale": {"status": scale_status, "state": launch_data.get("state"),
                  "completed_units": completed, "total_units": total,
                  "summary_sha256": sha256(scale_summary) if scale_data is not None else None},
    }


def render_macros(evidence: dict[str, Any]) -> str:
    circuit = evidence["circuit"]
    return "\n".join([
        "% Generated by script/build_v4_paper_evidence.py; do not edit.",
        rf"\newcommand{{\VFourConstraints}}{{{circuit['constraints']:,}}}".replace(",", r"{,}"),
        rf"\newcommand{{\VFourPublicInputs}}{{{circuit['public_inputs']}}}",
        rf"\newcommand{{\VFourPrivateInputs}}{{{circuit['private_inputs']}}}",
        rf"\newcommand{{\VFourStaticChecks}}{{22}}",
        rf"\newcommand{{\VFourProtocolDatasets}}{{5}}",
        "",
    ])


def render_utility_table(evidence: dict[str, Any]) -> str:
    labels = {"tdrive": "T-Drive", "geolife": "GeoLife", "porto": "Porto",
              "rome": "Rome", "synthetic": "Synthetic"}
    lines = [
        "% Generated by script/build_v4_paper_evidence.py; do not edit.",
        r"\begin{table*}[t]", r"\centering", r"\scriptsize",
        r"\caption{Fixed fair five-dataset utility comparison at $N{=}1000$, three seeds, $\varepsilon{=}5.0$, and $\tau{=}2.0$. Higher Jaccard is better.}",
        r"\label{tab:v4-fixed-utility}", r"\setlength{\tabcolsep}{3pt}",
        r"\begin{tabular}{lrrrrr}", r"\toprule",
        r"Dataset & SHTPC $\pm$ std & Nebula $\pm$ std & $\Delta$ & FRR & MRR \\", r"\midrule",
    ]
    for row in evidence["fixed_utility"]:
        lines.append(
            f"{labels[row['dataset']]} & {row['proposed_avg_jaccard']:.3f} $\\pm$ {row['proposed_std_jaccard']:.3f} & "
            f"{row['baseline_avg_jaccard']:.3f} $\\pm$ {row['baseline_std_jaccard']:.3f} & "
            f"+{row['delta_jaccard']:.3f} & {row['proposed_frr']:.3f} & {row['proposed_mrr']:.3f} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--static", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--utility", type=Path, required=True)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--scale-summary", type=Path)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-macros", type=Path, required=True)
    parser.add_argument("--out-table", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence = collect_evidence(repo=args.repo, manifest=args.manifest,
                                static=args.static, protocol=args.protocol,
                                utility=args.utility, launch=args.launch,
                                scale_summary=args.scale_summary)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_macros.parent.mkdir(parents=True, exist_ok=True)
    args.out_table.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out_macros.write_text(render_macros(evidence), encoding="utf-8")
    args.out_table.write_text(render_utility_table(evidence), encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the focused tests**

Run:

```bash
python -m pytest -q tests/test_build_v4_paper_evidence.py
```

Expected: `5 passed`.

- [ ] **Step 5: Generate the real evidence bundle**

Run:

```bash
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
```

Expected: circuit values are 3547/16/25, all three completed gates are pass, and scale remains `partial` until the strict aggregate receipt exists. `completed_units` may be 13, 14, or 15 depending on the externally running resume, but launcher completion alone cannot set `scale.status=verified`.

- [ ] **Step 6: Commit only the evidence-builder work unit**

```bash
git add script/build_v4_paper_evidence.py tests/test_build_v4_paper_evidence.py \
  TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json \
  TSIP/tables/v4_paper_evidence_macros.tex TSIP/tables/tab_v4_fixed_utility.tex
git commit --only -m "feat: build verified V4 paper evidence" -- \
  script/build_v4_paper_evidence.py tests/test_build_v4_paper_evidence.py \
  TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json \
  TSIP/tables/v4_paper_evidence_macros.tex TSIP/tables/tab_v4_fixed_utility.tex
```

### Task 3: Add A Manuscript Contract Checker

**Files:**
- Create: `script/check_heatmap_manuscript.py`
- Create: `tests/test_check_heatmap_manuscript.py`

- [ ] **Step 1: Write focused contract tests**

Create `tests/test_check_heatmap_manuscript.py`:

```python
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "script" / "check_heatmap_manuscript.py"
SPEC = importlib.util.spec_from_file_location("check_heatmap_manuscript", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

GOOD = r"""
\title{SHTPC: Stateful Hidden Trajectory-Payload Consistency for Private Heatmap Aggregation}
\begin{abstract}
ABSTRACT_BODY
\end{abstract}
T-Drive GeoLife Porto Rome Synthetic
\VFourConstraints{} constraints, \VFourPublicInputs{} public inputs, and
\VFourPrivateInputs{} private inputs.
\label{eq:r-shtpc}
"""
PARTIAL = {"scale": {"status": "partial"}}


def paper(words: int = 150) -> str:
    return GOOD.replace("ABSTRACT_BODY", "word " * words)


def test_valid_partial_scale_manuscript_passes() -> None:
    assert MODULE.check_text(paper(), PARTIAL) == []


@pytest.mark.parametrize("words", [99, 201])
def test_abstract_word_boundaries_fail(words: int) -> None:
    assert any("abstract word count" in issue for issue in MODULE.check_text(paper(words), PARTIAL))


@pytest.mark.parametrize("stale", ["3,056", r"3{,}056", "14 public inputs",
                                    "23 private inputs", r"\label{eq:r-tsip}"])
def test_stale_current_paper_facts_fail(stale: str) -> None:
    assert MODULE.check_text(paper() + stale, PARTIAL)


@pytest.mark.parametrize("dataset", ["Porto", "Rome", "Synthetic"])
def test_missing_required_dataset_fails(dataset: str) -> None:
    assert any("dataset missing" in issue for issue in MODULE.check_text(
        paper().replace(dataset, ""), PARTIAL
    ))


def test_missing_generated_artifact_macro_fails() -> None:
    assert any("artifact macro missing" in issue for issue in MODULE.check_text(
        paper().replace(r"\VFourConstraints{}", ""), PARTIAL
    ))


@pytest.mark.parametrize("claim", [
    "15/15 units passed.",
    "All 15 dataset-seed units completed successfully.",
])
def test_complete_scale_claim_fails_while_summary_is_partial(claim: str) -> None:
    assert any("scale evidence is partial" in issue for issue in MODULE.check_text(
        paper() + claim, PARTIAL
    ))
```

- [ ] **Step 2: Run the tests and verify failure before implementation**

```bash
python -m pytest -q tests/test_check_heatmap_manuscript.py
```

Expected: import/file-not-found failure.

- [ ] **Step 3: Implement the checker**

Implement these functions in `script/check_heatmap_manuscript.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ABSTRACT_RE = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.S)
STALE_PATTERNS = {
    r"3(?:\{,\}|,)056": "stale constraint count 3,056",
    r"\b14\s+public inputs\b": "stale 14-public-input paper claim",
    r"\b23\s+private inputs\b": "stale 23-private-input paper claim",
    r"eq:r-tsip": "stale internal TSIP label",
}
REQUIRED_MACROS = (r"\VFourConstraints", r"\VFourPublicInputs", r"\VFourPrivateInputs")
SCALE_COMPLETE_PATTERNS = (
    r"15\s*/\s*15\s+units?.{0,40}\b(?:passed|completed|successful)\b",
    r"(?:all\s+)?15\s+dataset[- ]seed\s+units?.{0,40}\b(?:passed|completed|successful)\b",
)


def latex_word_count(text: str) -> int:
    text = re.sub(r"%.*", " ", text)
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^]]*\])?", " ", text)
    text = re.sub(r"[{}$~^_]", " ", text)
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", text))


def check_text(text: str, evidence: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    match = ABSTRACT_RE.search(text)
    if not match:
        issues.append("abstract environment missing")
    else:
        words = latex_word_count(match.group(1))
        if not 100 <= words <= 200:
            issues.append(f"abstract word count is {words}, expected 100..200")
    for pattern, message in STALE_PATTERNS.items():
        if re.search(pattern, text):
            issues.append(message)
    for dataset in ("T-Drive", "GeoLife", "Porto", "Rome", "Synthetic"):
        if dataset not in text:
            issues.append(f"dataset missing from manuscript: {dataset}")
    for macro in REQUIRED_MACROS:
        if macro not in text:
            issues.append(f"artifact macro missing from manuscript: {macro}")
    scale_complete_claimed = any(re.search(pattern, text, re.I | re.S)
                                 for pattern in SCALE_COMPLETE_PATTERNS)
    if evidence.get("scale", {}).get("status") != "verified" and scale_complete_claimed:
        issues.append("manuscript claims 15/15 completion while scale evidence is partial")
    return issues


def abstract_words(text: str) -> int | None:
    match = ABSTRACT_RE.search(text)
    return latex_word_count(match.group(1)) if match else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tex", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    text = args.tex.read_text(encoding="utf-8")
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    issues = check_text(text, evidence)
    print(json.dumps({"abstract_words": abstract_words(text), "issues": issues},
                     indent=2, sort_keys=True))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests and the current manuscript check**

```bash
python -m pytest -q tests/test_check_heatmap_manuscript.py
python script/check_heatmap_manuscript.py \
  --tex TSIP/main.tex \
  --evidence TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json
```

Expected: tests pass; the current manuscript check fails on the oversized abstract, stale artifact facts, and missing canonical five-dataset text.

- [ ] **Step 5: Commit the checker**

```bash
git add script/check_heatmap_manuscript.py tests/test_check_heatmap_manuscript.py
git commit --only -m "test: enforce heatmap manuscript evidence contract" -- \
  script/check_heatmap_manuscript.py tests/test_check_heatmap_manuscript.py
```

### Task 4: Reconcile Circuit Facts And Canonical Paper Sources

**Files:**
- Modify: `TSIP/main.tex:180-220,1070-1260,1858-1935,1954-1975`
- Reference only: `TSIP_heatmap_version/paper/main.tex`
- Generate: `TSIP/tables/v4_paper_evidence_macros.tex`

- [ ] **Step 1: Load the generated macros in the preamble**

Add exactly one input before `\begin{document}`:

```latex
\input{tables/v4_paper_evidence_macros}
```

- [ ] **Step 2: Replace current-paper numeric literals with macros**

Use `\VFourConstraints`, `\VFourPublicInputs`, and `\VFourPrivateInputs` in Method, Security, RQ6, and Conclusion. Remove all current-paper uses of `3{,}056`, `14 public inputs`, and `23 private inputs`.

- [ ] **Step 3: Separate historical benchmark evidence**

Rewrite RQ6 so three distinct layers remain separate: the 2,728/14/23 archive-compatibility relation, the 3,056/14/23 historical benchmark receipts, and the 3,547/16/25 manifest-bound paper relation. The current-paper paragraph must use only the third layer and state that final three-seed end-to-end throughput remains pending strict 15/15 validation. Keep 128 B proof-size or 5,694 B report-frame claims only if they point to a receipt produced by the manifest-bound V4 serializer; otherwise remove them from current-circuit claims or label them explicitly as historical. Archive and historical microbenchmarks must be excluded from current-circuit latency claims.

- [ ] **Step 4: Rename the stale internal label**

Change `\label{eq:r-tsip}` to `\label{eq:r-shtpc}` and update every reference to the old label.

- [ ] **Step 5: Run the artifact-fact searches**

```bash
rg -n '3(\{,\}|,)056|14 public inputs|23 private inputs|eq:r-tsip' TSIP/main.tex
rg -n '\\VFourConstraints|\\VFourPublicInputs|\\VFourPrivateInputs' TSIP/main.tex
rg -n '128\\,B|5\{,\}694|5\.7\\,KB' TSIP/main.tex || true
```

Expected: the first command returns no lines; the second covers Method, RQ6, and Conclusion. Every third-command match is explicitly tied to a manifest-bound measurement receipt or labeled as historical rather than silently reused.

- [ ] **Step 6: Commit the artifact-consistency edit**

```bash
git add TSIP/main.tex
git commit --only -m "fix: align SHTPC paper with manifest-bound circuit" -- TSIP/main.tex
```

### Task 5: Rewrite The Abstract And Build The Claim-Evidence Map

**Files:**
- Modify: `TSIP/main.tex:238-357,1954-1975`
- Create: `TSIP/CLAIM_EVIDENCE_MAP.md`
- Read during execution: `/Users/wanghao/.codex/skills/research-paper-writing/references/abstract.md`
- Read during final review: `/Users/wanghao/.codex/skills/research-paper-writing/references/paper-review.md`

- [ ] **Step 1: Write a five-message abstract outline**

The outline must contain exactly: problem significance; missing same-relation binding; SHTPC mechanism; verified evidence; scoped limitation. Do not include the incomplete 15-unit scale claim.

- [ ] **Step 2: Rewrite the abstract to 100-to-200 words**

Keep one sentence or tightly coupled sentence pair per outline message. Report only verified static/fixed-utility evidence. State that SHTPC does not prove physical presence or reject all in-envelope false reports.

- [ ] **Step 3: Reverse-outline the five core sections**

For every paragraph in Introduction, Method, Evaluation, Discussion, and Conclusion, record its topic sentence and role in `TSIP/CLAIM_EVIDENCE_MAP.md`. Remove duplicated claims and make the first sentence of each paragraph state its message and support the section thesis.

- [ ] **Step 4: Populate the claim-evidence map**

Use this exact table schema:

```markdown
| ID | Claim | Manuscript location | Evidence artifact | Status | Action |
|---|---|---|---|---|---|
```

Statuses are limited to `supported`, `partial`, `analytical`, `assumption`, and `unsupported`. Remove unsupported claims from the manuscript. Keep final-scale claims as partial and absent from the Abstract.

- [ ] **Step 5: Run the abstract and stale-claim checker**

```bash
python script/check_heatmap_manuscript.py \
  --tex TSIP/main.tex \
  --evidence TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json
```

Expected: abstract length passes; artifact-fact checks pass. Dataset coverage may remain as the only failure until Task 6.

- [ ] **Step 6: Commit the writing unit**

```bash
git add TSIP/main.tex TSIP/CLAIM_EVIDENCE_MAP.md
git commit --only -m "docs: sharpen SHTPC claims for TDSC" -- \
  TSIP/main.tex TSIP/CLAIM_EVIDENCE_MAP.md
```

### Task 6: Integrate The Fixed Fair Five-Dataset Evidence

**Files:**
- Modify: `TSIP/main.tex:1556-1612,1728-1874`
- Add: `TSIP/tables/tab_v4_fixed_utility.tex`
- Add: `TSIP/figures/v4_fixed_utility_heatmap.pdf`
- Reference: `TSIP_heatmap_version/paper/main.tex:1558-1860`
- Source: `TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/utility/three_seed_n1000/fair_fixed_comparison.json`

- [ ] **Step 1: Merge only verified dataset-description improvements**

Describe T-Drive, GeoLife, Porto, and Rome as real trajectory-derived inputs and Synthetic as clustered random-walk stress data. State N=1000 for the fixed utility evaluation. Do not copy the isolated paper's EIFFeL tuned numbers into the fair main comparison.

- [ ] **Step 2: Separate the three evidence layers in Experimental Setup**

Create one paragraph each for original-input utility, safe-trajectory protocol smoke, and full Groth16 scale. State that `TSIP_SAFE_PROTOCOL_TRAJECTORY=1` is smoke/scale protocol isolation and not the source of utility values.

- [ ] **Step 3: Replace the old RQ5 result with the generated table**

Insert:

```latex
\input{tables/tab_v4_fixed_utility}
```

Explain the fixed `epsilon=5.0`, `tau=2.0`, three-seed protocol and report all five absolute deltas. Explicitly call the Porto and Synthetic gains small rather than uniformly large.

- [ ] **Step 4: Install the generated publication figure**

Run the existing generator and mechanically copy its PDF into the canonical figure directory:

```bash
python TSIP_heatmap_version/runtime/experiments-heatmap/make_v4_fair_heatmap.py
cp TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/figures/v4_fixed_utility_heatmap.pdf \
  TSIP/figures/v4_fixed_utility_heatmap.pdf
```

Reference this figure from RQ5 with a caption that says fixed config, N=1000, and three seeds.

- [ ] **Step 5: Run the full manuscript contract**

```bash
python script/check_heatmap_manuscript.py \
  --tex TSIP/main.tex \
  --evidence TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json
```

Expected: zero issues while scale remains partial.

- [ ] **Step 6: Commit the five-dataset writing unit**

```bash
git add TSIP/main.tex TSIP/tables/tab_v4_fixed_utility.tex \
  TSIP/figures/v4_fixed_utility_heatmap.pdf
git commit --only -m "docs: integrate fixed five-dataset V4 evidence" -- \
  TSIP/main.tex TSIP/tables/tab_v4_fixed_utility.tex \
  TSIP/figures/v4_fixed_utility_heatmap.pdf
```

### Task 7: Add Compliance And Reproducibility Records

**Files:**
- Create: `DATA_NOTICE.md`
- Create after author approval or explicitly block: `LICENSE`
- Create: `TSIP_heatmap_version/ARTIFACT_README.md`
- Create: `docs/submission/TSIP_HEATMAP_AUTHOR_CONFIRMATIONS.md`
- Create: `TSIP/CITATION_AUDIT.md`
- Modify: `TSIP/main.tex:1914-1953`

- [ ] **Step 1: Verify dataset provenance from primary sources**

For each dataset, record source owner, official landing/download page, required citation, license or terms, redistribution rule, local preprocessing, and whether raw data is stored or distributed. Use primary sources only. Mark Synthetic as repository-generated and record its generation script and seed policy.

- [ ] **Step 2: Write `DATA_NOTICE.md`**

Use one section per dataset and this field order:

```markdown
## Dataset Name
- Type:
- Owner/source:
- Official URL:
- Required citation:
- License/terms:
- Redistribution:
- Local preprocessing:
- Repository contents:
```

Every field must contain a verified value or the explicit sentence `Author confirmation required before redistribution.`

- [ ] **Step 3: Write the Heatmap artifact index**

`TSIP_heatmap_version/ARTIFACT_README.md` must list the static gate, manifest, protocol smoke, fixed utility, publication figure, scale launcher, unit receipts, exact rerun commands, environment prerequisites, and the development-setup limitation. It must not reuse the RUC-focused root `README_ARTIFACT.md` as the Heatmap guide.

- [ ] **Step 4: Write author-confirmation controls**

`docs/submission/TSIP_HEATMAP_AUTHOR_CONFIRMATIONS.md` must include checkboxes for repository license selection, author order, ORCIDs, corresponding-author email, COI, prior/concurrent versions, funding, human-subject/ethics determination, code/data availability wording, and AI-use disclosure. Do not invent author answers.

- [ ] **Step 5: Resolve the repository-license gate without guessing**

Run `git log --format='%an <%ae>' --all | sort -u` and `rg -n -i 'copyright|license|third[- ]party|redistribut' README* TSIP TSIP_heatmap_version docs 2>/dev/null` to identify ownership boundaries. If the author-confirmation file contains an explicit approved license, install the unmodified official SPDX text as `LICENSE` and record the SPDX identifier. Otherwise, leave `LICENSE` absent and record `BLOCKED: explicit author license selection required` in both the confirmation file and `TSIP/TDSC_SELF_REVIEW.md`; do not infer a license from dependencies or dataset terms.

- [ ] **Step 6: Audit new and high-risk references**

Create `TSIP/CITATION_AUDIT.md` with this schema:

```markdown
| Bib key | Primary source | Metadata verified | Supported manuscript claim | Quote/paraphrase checked | Status/action |
|---|---|---|---|---|---|
```

Verify each dataset citation, each VDAF/DP/ZK construction used for a technical claim, and every reference added during the revision against the publisher, standards body, official dataset owner, or original paper. Remove or narrow unsupported claims; do not use search-result snippets as evidence.

- [ ] **Step 7: Align manuscript statements**

Update Artifact/Reproducibility and Ethics so the manuscript matches `DATA_NOTICE.md` and explicitly treats simulated reviewer reports as internal quality control. Keep raw GPS redistribution restrictions and development Groth16 setup limitations visible.

- [ ] **Step 8: Commit the compliance unit**

```bash
paths=(DATA_NOTICE.md TSIP_heatmap_version/ARTIFACT_README.md \
  docs/submission/TSIP_HEATMAP_AUTHOR_CONFIRMATIONS.md \
  TSIP/CITATION_AUDIT.md TSIP/main.tex)
if [[ -f LICENSE ]]; then paths+=(LICENSE); fi
git add -- "${paths[@]}"
git commit --only -m "docs: add heatmap provenance and submission controls" -- \
  "${paths[@]}"
```

### Task 8: Compile, Render, And Synchronize The Verified Paper

**Files:**
- Modify as needed: `TSIP/main.tex`, `TSIP/reference.bib`, `TSIP/figures/*`
- Synchronize after pass: `TSIP_heatmap_version/paper/main.tex`, `TSIP_heatmap_version/paper/reference.bib`
- Generate: `TSIP/main.pdf`

- [ ] **Step 1: Run focused Python verification**

```bash
python -m pytest -q tests/test_build_v4_paper_evidence.py tests/test_check_heatmap_manuscript.py
python script/check_heatmap_manuscript.py \
  --tex TSIP/main.tex \
  --evidence TSIP_heatmap_version/runtime/experiments-heatmap/docker_v4_smoke/analysis_v4/paper_evidence.json
```

Expected: all tests pass and manuscript issues are empty.

- [ ] **Step 2: Compile from a clean auxiliary state**

```bash
cd /Users/wanghao/Desktop/risefl_mvp/TSIP
rm -f main.aux main.bbl main.bcf main.blg main.log main.out main.run.xml
pdflatex -interaction=nonstopmode -halt-on-error main.tex
biber main
pdflatex -interaction=nonstopmode -halt-on-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error main.tex
```

Expected: every command exits 0.

- [ ] **Step 3: Enforce log and page gates**

```bash
grep -E 'Undefined|undefined references|Citation.*undefined|LaTeX Error|Fatal error|Please.*rerun' main.log main.blg && exit 1 || true
grep -E 'Overfull|Underfull|LaTeX Warning|Package .* Warning' main.log > /tmp/tsip-heatmap-latex-warnings.txt || true
cat /tmp/tsip-heatmap-latex-warnings.txt
pdfinfo main.pdf | grep -E 'Pages|Page size|File size'
```

Expected: no fatal/undefined/rerun lines. Review every nonfatal warning, fix any warning that corresponds to clipped or unreadable output, and record the remaining warning count plus fresh page count without reusing the old 17-page claim.

- [ ] **Step 4: Render every page and inspect visually**

```bash
rm -rf /tmp/tsip-heatmap-pages
mkdir -p /tmp/tsip-heatmap-pages
pdftoppm -png -r 144 main.pdf /tmp/tsip-heatmap-pages/page
```

Inspect every rendered page with `view_image`. Reject clipped tables, unreadable figure labels, blank float regions, overlapping text, inconsistent captions, or missing visual assets.

- [ ] **Step 5: Synchronize the verified canonical paper mechanically**

```bash
cd /Users/wanghao/Desktop/risefl_mvp
cp TSIP/main.tex TSIP_heatmap_version/paper/main.tex
cp TSIP/reference.bib TSIP_heatmap_version/paper/reference.bib
cmp TSIP/main.tex TSIP_heatmap_version/paper/main.tex
cmp TSIP/reference.bib TSIP_heatmap_version/paper/reference.bib
```

Expected: both `cmp` commands exit 0. Do not synchronize build auxiliaries.

- [ ] **Step 6: Commit the verified paper state**

```bash
git add TSIP/main.tex TSIP/main.pdf TSIP_heatmap_version/paper/main.tex \
  TSIP_heatmap_version/paper/reference.bib
git commit --only -m "docs: verify pre-scale SHTPC TDSC manuscript" -- \
  TSIP/main.tex TSIP/main.pdf TSIP_heatmap_version/paper/main.tex \
  TSIP_heatmap_version/paper/reference.bib
```

### Task 9: Adversarial Self-Review And Obsidian Write-Back

**Files:**
- Create: `TSIP/TDSC_SELF_REVIEW.md`
- Modify: `TSIP/CLAIM_EVIDENCE_MAP.md`
- Modify: `memory/Research/tsip-heatmap/00-Hub.md`
- Modify: `memory/Research/tsip-heatmap/01-Plan.md`
- Modify: `memory/Research/tsip-heatmap/Daily/2026-07-13.md`
- Modify: `memory/Research/tsip-heatmap/Writing/论文修订与投稿决策.md`
- Modify: `memory/Research/tsip-heatmap/Knowledge/V4方法与证据边界.md`

- [ ] **Step 1: Run the five-dimension paper review**

Review contribution, writing clarity, experimental strength, evaluation completeness, and method soundness. For every high-risk question, record evidence and either revise the manuscript or state the residual limitation.

- [ ] **Step 2: Close the claim-evidence map**

No row may remain `unsupported`. `partial` is allowed only for final three-seed scale and must not appear as a completed Abstract claim.

- [ ] **Step 3: Write `TSIP/TDSC_SELF_REVIEW.md`**

Include final abstract word count, fresh page count, build commands, warning summary, five review dimensions, unresolved author confirmations, and the exact deferred 15/15 work.

- [ ] **Step 4: Update Obsidian immediately**

Mark completed pre-scale tasks in Plan, update Hub focus, write current page/word counts and claims to Writing, write canonical circuit facts to Knowledge, and append test/build receipts to Daily. Keep Results status `partial-verified` and Experiment status `interrupted`.

- [ ] **Step 5: Run KB verification**

```bash
python /Users/wanghao/.agents/skills/obsidian-project-kb-core/scripts/project_kb.py sync \
  --cwd /Users/wanghao/Desktop/risefl_mvp --project-id tsip-heatmap \
  --scope tdsc-pre-scale-revision
python /Users/wanghao/.agents/skills/obsidian-project-kb-core/scripts/kb_lint.py \
  --cwd /Users/wanghao/Desktop/risefl_mvp --project-id tsip-heatmap
```

Expected: zero broken links, missing registry/index entries, and experiment/result linkage issues.

- [ ] **Step 6: Commit the review and KB checkpoint only**

```bash
git add TSIP/TDSC_SELF_REVIEW.md TSIP/CLAIM_EVIDENCE_MAP.md \
  memory/Research/tsip-heatmap
git commit --only -m "docs: record SHTPC TDSC pre-scale review" -- \
  TSIP/TDSC_SELF_REVIEW.md TSIP/CLAIM_EVIDENCE_MAP.md \
  memory/Research/tsip-heatmap
```
