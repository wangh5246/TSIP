"""E4 baseline comparison settings: enforcement exchange rate and head-to-head table.

Extends the single-number E4 result ("spot-check needs N cameras, TSIP needs 0")
into a full baseline comparison:

1. Detection curve P(detect | cameras) for the spot-check lineage on BOTH road
   universes (observed-path generous proxy and real drivable graph), using the
   same exponential coverage model as ``e4_required_cameras``:
   P = 1 - exp(-coverage * omit_fraction * segments_per_driver).
2. Equal-detection work points: cameras needed at P in {0.5, 0.8, 0.95, 0.99}.
3. Head-to-head table across the design-doc baseline trio (Baseline R
   reconstructed spot-check, Baseline T TEE billing, Baseline Z ZKLP predicate
   proof) plus TSIP-RUC, with TSIP costs taken from measured receipts only.

Generous-baseline discipline: every free parameter favors the spot-check
lineage (zero camera error, independent coverage, zero audit cost, zero
crypto/communication overhead); assumptions are recorded in the receipt.

Inputs (must exist): experiments/e4_e5_ruc/e4_spotcheck_summary.csv,
experiments/e4_e5_ruc/e4_drivable_receipt.json,
experiments/e6_rapidsnark/receipt.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import canonical_json  # noqa: E402

E4_DIR = ROOT_DIR / "experiments" / "e4_e5_ruc"
E6_RECEIPT = ROOT_DIR / "experiments" / "e6_rapidsnark" / "receipt.json"
SNARKJS_PROVE_MS = 7133.64  # design doc §15.1, 2026-06-11 local run
SNARKJS_PROOF_BYTES = 805

DETECTION_TARGETS = (0.50, 0.80, 0.95, 0.99)
OMIT_FRACTIONS = (0.10, 0.20)


def p_detect(coverage: float, omit_fraction: float, segments_per_driver: int) -> float:
    return 1.0 - math.exp(-min(1.0, coverage) * float(omit_fraction) * int(segments_per_driver))


def cameras_for_target(target: float, omit_fraction: float, segments_per_driver: int, road_segments: int) -> int | None:
    """Cameras to reach the target detection probability; None if unreachable at full coverage."""

    omitted = float(omit_fraction) * int(segments_per_driver)
    if 1.0 - math.exp(-omitted) < float(target):
        return None
    coverage = -math.log(1.0 - float(target)) / omitted
    return math.ceil(min(1.0, coverage) * int(road_segments))


def load_universes() -> dict[str, dict[str, int]]:
    """Return {dataset: {universe_name: road_segments}} plus segments_per_driver."""

    out: dict[str, dict[str, int]] = {}
    spd: dict[str, int] = {}
    with open(E4_DIR / "e4_spotcheck_summary.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["road_proxy"] != "observed_path_proxy_generous":
                continue
            out.setdefault(row["dataset"], {})["observed_proxy_generous"] = int(row["road_network_segments"])
            spd[row["dataset"]] = int(row["segments_per_driver"])
    drivable = json.load(open(E4_DIR / "e4_drivable_receipt.json"))
    for dataset, info in drivable["datasets"].items():
        if "segments_100m" in info:
            out.setdefault(dataset, {})["drivable_graph"] = int(info["segments_100m"])
    return {"universes": out, "segments_per_driver": spd}


def tsip_measured_costs() -> dict[str, float | int]:
    e6 = json.load(open(E6_RECEIPT))
    # Representative public statement byte size from the deterministic k6 demo.
    from script.prove_settlement_period_v5 import build_input

    _input_json, submission = build_input()
    statement_bytes = len(canonical_json(submission["public_statement"]).encode())
    attestation_bytes = 120  # device_id + base64 Ed25519 signature envelope
    return {
        "client_prove_ms_snarkjs": SNARKJS_PROVE_MS,
        "client_prove_ms_rapidsnark": float(e6["rapidsnark_prove_ms_median"]),
        "client_witness_ms": float(e6["witness_ms_snarkjs"]),
        "server_verify_ms": float(e6["snarkjs_verify_ms"]),
        "proof_bytes_snarkjs": SNARKJS_PROOF_BYTES,
        "proof_bytes_rapidsnark": int(e6["proof_json_bytes"]),
        "statement_bytes": statement_bytes,
        "attestation_bytes": attestation_bytes,
        "comm_bytes_per_period": statement_bytes + SNARKJS_PROOF_BYTES + attestation_bytes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build E4 baseline comparison artifacts.")
    parser.add_argument("--out-dir", default=str(E4_DIR))
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    loaded = load_universes()
    universes: dict[str, dict[str, int]] = loaded["universes"]
    spd: dict[str, int] = loaded["segments_per_driver"]
    tsip = tsip_measured_costs()

    curve_rows: list[dict] = []
    for dataset, by_universe in sorted(universes.items()):
        s = spd.get(dataset)
        if not s:
            continue
        for universe, segments in sorted(by_universe.items()):
            budgets = sorted({0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, segments})
            for omit in OMIT_FRACTIONS:
                for cams in budgets:
                    if cams > segments:
                        continue
                    curve_rows.append(
                        {
                            "dataset": dataset,
                            "road_universe": universe,
                            "road_segments": segments,
                            "segments_per_driver": s,
                            "omit_fraction": omit,
                            "cameras": cams,
                            "spotcheck_p_detect": round(p_detect(cams / segments, omit, s), 6),
                            "tsip_p_detect_proof_violating": 1.0,
                            "tsip_cameras": 0,
                        }
                    )

    workpoint_rows: list[dict] = []
    for dataset, by_universe in sorted(universes.items()):
        s = spd.get(dataset)
        if not s:
            continue
        for universe, segments in sorted(by_universe.items()):
            for omit in OMIT_FRACTIONS:
                for target in DETECTION_TARGETS:
                    cams = cameras_for_target(target, omit, s, segments)
                    workpoint_rows.append(
                        {
                            "dataset": dataset,
                            "road_universe": universe,
                            "road_segments": segments,
                            "omit_fraction": omit,
                            "target_p_detect": target,
                            "spotcheck_required_cameras": "" if cams is None else cams,
                            "reachable_at_full_coverage": cams is not None,
                            "tsip_required_cameras": 0,
                        }
                    )

    head_rows = build_head_to_head(universes, spd, tsip)

    write_csv(out_dir / "e4_detection_curve.csv", curve_rows)
    write_csv(out_dir / "e4_equal_detection_workpoints.csv", workpoint_rows)
    write_csv(out_dir / "e4_baseline_head_to_head.csv", head_rows)
    plot_curves(curve_rows, out_dir / "fig_e4_enforcement_exchange_rate.png")

    receipt = {
        "experiment": "E4 baseline comparison settings",
        "detection_model": "P = 1 - exp(-coverage * omit_fraction * segments_per_driver); same as e4_required_cameras",
        "generous_baseline_assumptions": [
            "cameras observe their segment with zero error",
            "camera coverage draws are independent across observed segments",
            "audit, dispute, and false-positive costs for spot-check are zero",
            "spot-check communication overhead is zero bytes (favoring the baseline)",
            "TEE attestation infrastructure and remote-attestation cost are zero",
        ],
        "tsip_measured_costs": tsip,
        "sources": {
            "road_universes": "experiments/e4_e5_ruc/e4_spotcheck_summary.csv + e4_drivable_receipt.json",
            "tsip_costs": "experiments/e6_rapidsnark/receipt.json + design doc §15.1 snarkjs run",
        },
        "model_caveat": (
            "e4_required_cameras caps coverage at 1.0; when omit_fraction*segments_per_driver is small, "
            "the 0.95 target is unreachable at any camera count (e.g. rome omit 0.10, S=24: max P=0.909). "
            "Earlier summary rows reporting full coverage as meeting the target should be read with "
            "reachable_at_full_coverage from e4_equal_detection_workpoints.csv."
        ),
        "outputs": [
            "e4_detection_curve.csv",
            "e4_equal_detection_workpoints.csv",
            "e4_baseline_head_to_head.csv",
            "fig_e4_enforcement_exchange_rate.png",
        ],
    }
    json.dump(receipt, open(out_dir / "e4_baseline_comparison_receipt.json", "w"), indent=1, sort_keys=True)
    print(
        f"wrote {len(curve_rows)} curve rows, {len(workpoint_rows)} workpoints, "
        f"{len(head_rows)} head-to-head rows to {out_dir}"
    )


def build_head_to_head(
    universes: dict[str, dict[str, int]],
    spd: dict[str, int],
    tsip: dict[str, float | int],
) -> list[dict]:
    """One row per baseline; camera columns use the Rome drivable graph at 95%/omit 0.1."""

    rome_segments = universes.get("rome", {}).get("drivable_graph", 0)
    s = spd.get("rome", 24)

    def fmt_cams(omit: float) -> str:
        cams = cameras_for_target(0.95, omit, s, rome_segments) if rome_segments else None
        if cams is None:
            max_p = 1.0 - math.exp(-omit * s)
            return f"unreachable at omit {omit:.2f} (max P={max_p:.3f} at full coverage)"
        return f"{cams} @ omit {omit:.2f}"

    spotcheck_units = "; ".join(fmt_cams(omit) for omit in OMIT_FRACTIONS)
    common = {
        "comparison_anchor": "rome drivable graph, target P=0.95",
        "rome_drivable_segments": rome_segments,
    }
    return [
        {
            **common,
            "baseline": "TSIP-RUC (this work)",
            "enforcement": "Groth16 proof rejection at submission",
            "roadside_units_rome": 0,
            "detection_proof_violating": "deterministic (P=1)",
            "detection_proof_consistent_relay": "residual bounded by E3 sweep",
            "detection_latency": "at submission",
            "client_cost_per_period": f"prove {tsip['client_prove_ms_rapidsnark']:.0f} ms rapidsnark / {tsip['client_prove_ms_snarkjs']:.0f} ms snarkjs (measured)",
            "server_cost_per_period": f"verify {tsip['server_verify_ms']:.0f} ms (measured)",
            "comm_bytes_per_period": tsip["comm_bytes_per_period"],
            "route_privacy": "proof-only statement; leakage profile L audited in E5",
            "policy_in_tcb": "no (trust sensing, verify policy)",
            "sensing_trust": "OSNMA receiver + odometer + device attestation",
            "compromise_blast_radius": "compromised receiver can distort readings, not billing arithmetic",
        },
        {
            **common,
            "baseline": "Baseline R: spot-check lineage (VPriv/PrETP/Milo), reconstructed",
            "enforcement": "roadside observation / random audits",
            "roadside_units_rome": spotcheck_units,
            "detection_proof_violating": "probabilistic; P=0.95 needs the camera count at left",
            "detection_proof_consistent_relay": "not addressed by roadside observation",
            "detection_latency": "next audit/observation cycle",
            "client_cost_per_period": "commitments only (modeled as zero; generous)",
            "server_cost_per_period": "audit sampling (modeled as zero; generous)",
            "comm_bytes_per_period": "modeled as zero (generous)",
            "route_privacy": "strong except segments revealed by observation/audits",
            "policy_in_tcb": "no",
            "sensing_trust": "none beyond OBU commitments",
            "compromise_blast_radius": "undetected fraud scales with uncovered segments",
        },
        {
            **common,
            "baseline": "Baseline T: TEE billing",
            "enforcement": "remote attestation of billing enclave",
            "roadside_units_rome": 0,
            "detection_proof_violating": "n/a (bill computed inside TCB)",
            "detection_proof_consistent_relay": "same GNSS exposure as TSIP, unaudited",
            "detection_latency": "n/a",
            "client_cost_per_period": "negligible compute (generous)",
            "server_cost_per_period": "attestation check (modeled as zero; generous)",
            "comm_bytes_per_period": "bill + attestation quote (~1KB, modeled)",
            "route_privacy": "strong while TEE holds",
            "policy_in_tcb": "YES: tariff + billing code inside TCB",
            "sensing_trust": "TEE + GNSS + odometer",
            "compromise_blast_radius": "TEE break => arbitrary bills accepted",
        },
        {
            **common,
            "baseline": "Baseline Z: ZKLP predicate proofs",
            "enforcement": "per-predicate location proof",
            "roadside_units_rome": "deployment-dependent (verifier anchors)",
            "detection_proof_violating": "predicate-level only",
            "detection_proof_consistent_relay": "out of scope",
            "detection_latency": "per predicate query",
            "client_cost_per_period": "one proof per predicate, not per settlement",
            "server_cost_per_period": "per-predicate verification",
            "comm_bytes_per_period": "per-predicate proof bytes",
            "route_privacy": "predicate-minimal",
            "policy_in_tcb": "no",
            "sensing_trust": "scheme-dependent",
            "compromise_blast_radius": "n/a: does not bind period bill, odometer, fallback, or month",
        },
    ]


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def plot_curves(curve_rows: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for ax, universe in zip(axes, ("observed_proxy_generous", "drivable_graph")):
        for dataset in sorted({r["dataset"] for r in curve_rows}):
            rows = [
                r
                for r in curve_rows
                if r["dataset"] == dataset and r["road_universe"] == universe and r["omit_fraction"] == 0.10
            ]
            if not rows:
                continue
            rows.sort(key=lambda r: r["cameras"])
            ax.plot([r["cameras"] for r in rows], [r["spotcheck_p_detect"] for r in rows], marker="o", ms=3, label=dataset)
        ax.axhline(1.0, color="black", ls="--", lw=1, label="TSIP-RUC (0 cameras)")
        ax.set_xscale("symlog")
        ax.set_xlabel("roadside cameras")
        ax.set_title(universe)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("P(detect) per period, omit fraction 0.10")
    axes[0].legend(fontsize=8)
    fig.suptitle("E4 enforcement exchange rate: spot-check cameras vs proof rejection")
    fig.tight_layout()
    fig.savefig(path, dpi=160)


if __name__ == "__main__":
    main()
