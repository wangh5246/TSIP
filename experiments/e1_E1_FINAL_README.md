# E1 Final Results Memo

Date: 2026-06-10

This memo records the E1 results that are safe to cite in the paper after the
billing-objective fix and Rome official-tariff reconstruction.

## Paper Claim

E1 quantifies the marginal economic attack surface exposed by relaxing settlement
constraints. In heterogeneous tariff settings, lifted replay can reduce billed
cost, while OSNMA-pinned replay is rejected and yields zero realized savings
across datasets.

Scope matters:

- Economic magnitude is supported by datasets with tariff heterogeneity.
- Cross-dataset robustness refers to pinned blocking, not to equal economic
  savings magnitude across all datasets.

## Cite These Result Directories

- `experiments/e1_objective_fix/`
  - Objective/billing drift fixed.
  - GeoLife main economic anchor remains unchanged after the fix.
  - T-Drive, Porto, and original Rome lifted values were rechecked under the
    corrected billing objective.
- `experiments/e1_rome_real_tariff_ratio_fix/`
  - Rome rerun using the official Roma Mobilita parking tariff layer.
  - Tariff mapping preserves official hourly-rate ratios:
    `0.50:1.00:1.20 EUR/h -> 5:10:12`.
- `dataset/osm/zones/rome_medium.geojson`
  - Generated Rome tariff overlay used by the Rome real-tariff rerun.
- `dataset/osm/zones/README_rome_tariff.md`
  - Method note for source data, normalization, and polyline-to-cell assignment.

## Do Not Cite As Final Results

- `experiments/e1_sweeps/`
  - Pre-fix diagnostic sweep.
  - The Rome lifted savings near `0.94` were caused by solver-objective and
    billing drift and are invalid as paper results.
- `experiments/e1_rome_real_tariff_smoke/`
  - Earlier Rome smoke run using the non-ratio-preserving `3/5/6` mapping.
  - Kept only as local diagnostic history.

## Final Numbers

### GeoLife: Main Economic Anchor

Source: `experiments/e1_objective_fix/geolife_summary.csv`

| Branch | Mean savings | Notes |
| --- | ---: | --- |
| `no_zone_binding` | `0.2695731653` | Zone-binding marginal economic exposure. |
| `no_continuity_osnma_lifted` | `0.0836535350` | Lifted replay economic exposure. |
| `no_continuity` | `0.0` | OSNMA-pinned replay blocked. |

GeoLife input periods are cadence-clean for this E1 run: `0/336` fallback edges.
The corrected billing objective leaves the GeoLife main economic numbers
unchanged.

### Rome: Official-Tariff Auxiliary Evidence

Source: `experiments/e1_rome_real_tariff_ratio_fix/summary_162.csv`

| Branch | n | Skip | Mean savings | Median savings | p95 savings | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `no_continuity` | `162` | `0` | `0.0` | `0.0` | `0.0` | OSNMA-pinned replay blocked. |
| `no_continuity_osnma_lifted` | `132` | `30` | `0.0376850594` | `0.0254646738` | `0.1166177962` | Lifted replay under official tariff. |
| `no_zone_binding` | `162` | `0` | `0.0056221780` | `0.0020081710` | `0.0211665370` | Small because Rome working block has weak tariff contrast. |
| `no_cadence` | `13` | `149` | `0.0001191621` | `0.0` | `0.0011027182` | Fallback-heavy branch; not an economic anchor. |

Rome honest-fee distribution under the ratio-preserving official tariff:

- n: `162`
- min: `27180`
- median: `172327`
- mean: `173125.5309`
- p95: `278094`
- max: `330084`

Lifted absolute saved cents under the same run:

- min: `80`
- median: `4108`
- mean: `5023.8030`
- max: `19572`

Rome interpretation:

- The official full grid contains all three tariff tiers:
  `5:800`, `10:8755`, `12:445`.
- The Rome E1 working block contains only the `10` and `12` tiers:
  `10:63`, `12:193`.
- Therefore the Rome lifted result exercises the official `1.00/1.20 EUR/h`
  contrast, not the full `0.50/1.20 EUR/h` contrast.
- This makes Rome a conservative auxiliary economic result and a strong
  162-period robustness result, not a replacement for GeoLife as the main
  economic anchor.

## Robustness Statement

The pinned branch yields zero realized savings in all E1 checks after the
objective fix. This supports the cross-dataset robustness claim: lifted attacks
may expose economic surface when constraints are relaxed, but OSNMA-pinned
claims are rejected and realize zero savings.

## Bug Fixed Before Final Results

The earlier adversary objective used `dist_m * rate`, while real billing used
`compute_bill` / `fee_for_period`, including cadence-fallback billing for
`dt > cadence_sec`. This caused false Rome lifted savings near `0.94`.

Fix:

- `common/settlement.py` now exposes shared edge-fee logic through
  `fee_for_interval_values`.
- `common/eval_harness.py` adversary objectives now use the same billing logic
  as `compute_bill`.
- Regression tests cover fallback-edge objective/billing consistency.

Verification command:

```bash
pytest tests/test_build_rome_parking_tariff_geojson.py tests/test_eval_harness.py tests/test_run_e1_forensic.py
```

Latest verification result: `15 passed`.
