#!/usr/bin/env python3
"""Export the fixed-config V4 utility comparison as a paper figure."""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pubfig as pf


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "docker_v4_smoke/utility/three_seed_n1000/fair_fixed_comparison.csv"
OUTPUT = ROOT / "docker_v4_smoke/analysis_v4/figures/v4_fixed_utility_heatmap"
DATASETS = ["tdrive", "geolife", "porto", "rome", "synthetic"]
DISPLAY_DATASETS = ["T-Drive", "GeoLife", "Porto", "Rome", "Synthetic"]
DISPLAY_METHODS = ["SHTPC", "Nebula-style"]
FIGURE_SOURCE_DATE_EPOCH = "1783900800"  # 2026-07-13T00:00:00Z
REQUIRED_COLUMNS = {
    "dataset",
    "fixed_epsilon",
    "fixed_tau",
    "proposed_avg_jaccard",
    "proposed_std_jaccard",
    "strongest_baseline",
    "baseline_avg_jaccard",
    "baseline_std_jaccard",
    "delta_jaccard",
    "proposed_frr",
    "proposed_mrr",
    "pass",
}


def load_fixed_frame(path: Path = INPUT) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"fixed utility CSV is missing columns: {missing}")
    if frame["dataset"].tolist() != DATASETS:
        raise ValueError(
            "fixed utility CSV must contain the canonical five-dataset order"
        )

    numeric_columns = [
        "fixed_epsilon",
        "fixed_tau",
        "proposed_avg_jaccard",
        "proposed_std_jaccard",
        "baseline_avg_jaccard",
        "baseline_std_jaccard",
        "delta_jaccard",
        "proposed_frr",
        "proposed_mrr",
    ]
    numeric = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("fixed utility CSV contains a non-finite numeric value")
    if not np.allclose(numeric["fixed_epsilon"], 5.0, rtol=0.0, atol=0.0):
        raise ValueError("fixed utility figure requires epsilon=5.0 for every row")
    if not np.allclose(numeric["fixed_tau"], 2.0, rtol=0.0, atol=0.0):
        raise ValueError("fixed utility figure requires tau=2.0 for every row")
    if frame["strongest_baseline"].astype(str).str.lower().tolist() != ["nebula"] * len(
        DATASETS
    ):
        raise ValueError(
            "figure label requires Nebula to be the strongest baseline in every row"
        )
    passed = frame["pass"].map(lambda value: str(value).strip().lower() == "true")
    if not passed.all():
        raise ValueError("fixed utility figure requires every row gate to pass")

    bounded_columns = [
        "proposed_avg_jaccard",
        "proposed_std_jaccard",
        "baseline_avg_jaccard",
        "baseline_std_jaccard",
        "proposed_frr",
        "proposed_mrr",
    ]
    bounded = numeric[bounded_columns].to_numpy(dtype=float)
    if ((bounded < 0.0) | (bounded > 1.0)).any():
        raise ValueError("fixed utility metrics must be within [0, 1]")
    expected_delta = numeric["proposed_avg_jaccard"] - numeric["baseline_avg_jaccard"]
    if not np.allclose(numeric["delta_jaccard"], expected_delta, rtol=0.0, atol=1e-12):
        raise ValueError("fixed utility delta does not match proposed minus baseline")
    if (numeric["delta_jaccard"] <= 0.0).any():
        raise ValueError(
            "fixed utility figure requires a positive delta on every dataset"
        )

    frame[numeric_columns] = numeric
    return frame.set_index("dataset")


def main() -> None:
    # Matplotlib otherwise embeds the wall-clock creation time in the PDF.
    os.environ["SOURCE_DATE_EPOCH"] = FIGURE_SOURCE_DATE_EPOCH
    frame = load_fixed_frame()
    matrix = frame[["proposed_avg_jaccard", "baseline_avg_jaccard"]].to_numpy(
        dtype=float
    )
    fig = pf.heatmap(
        matrix,
        x_label="Method",
        y_label="Dataset",
        category_names=DISPLAY_METHODS,
        title="Fixed utility (N=1000, 3 seeds)",
        colorscale="YlGnBu",
        zmin=0.0,
        zmax=1.0,
        annotate=True,
        annotate_fmt=".3f",
        cell_border_line_width=0.6,
        cell_border_color="white",
        cbar_label="Released-set Jaccard",
        width=700,
        height=650,
    )
    ax = fig.axes[0]
    ax.set_yticks(np.arange(len(DISPLAY_DATASETS)))
    ax.set_yticklabels(DISPLAY_DATASETS)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    paths = pf.batch_export(
        fig,
        OUTPUT,
        formats=("pdf", "png"),
        spec="nature",
        width="single",
        height_mm=105,
        dpi=300,
        trim=True,
    )
    print("\n".join(str(path) for path in paths))


if __name__ == "__main__":
    main()
