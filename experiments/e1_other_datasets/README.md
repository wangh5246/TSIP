# E1 Other-Dataset Runs

These runs extend the E1 mechanism ablation beyond the GeoLife 14-period main receipt.
They are robustness/scope receipts, not replacements for the paper's main E1 table.

## Inputs

- T-Drive: `data/e1_mechanism_ablation/tdrive/periods_300s.jsonl`
  - 1 legal-cadence period at 300 s.
  - Source was the existing `data/processed_grid32_check/tdrive` proof-compatible period/tariff pair.
  - A fresh full Tier-1 regeneration attempt over T-Drive produced 0 periods at legal 300 s under the 16x16 / 256-leaf tariff block (`/private/tmp/e1_other_tier1_tdrive_full/manifest.csv`): 279 resampled fixes, but no 25-fix tariff segment.
- Porto: `data/e1_mechanism_ablation/porto/periods_60s.jsonl`
  - 10 legal-cadence periods at 60 s.
  - Generated from `dataset/porto/train.csv.zip` with the Tier-1 no-map-matching pipeline.
- Rome: `data/e1_mechanism_ablation/rome/periods_60s.jsonl`
  - 162 legal-cadence periods at 60 s.
  - Generated from `dataset/Roma.txt` with the Tier-1 no-map-matching pipeline.

Each input directory contains the paired `tariff_block.json`; `script/run_e1_forensic.py`
hard-fails if that tariff receipt is missing.

## Commands

```bash
python script/run_e1_forensic.py --inputs data/e1_mechanism_ablation/tdrive/periods_300s.jsonl --output experiments/e1_other_datasets/tdrive_e1_rows.csv --summary experiments/e1_other_datasets/tdrive_e1_summary.csv --audit-output experiments/e1_receipts/e1_tdrive_pinned_receipt.json --max-users 0 --periods-per-user 0 --cadence-sec 300 --max-dt-sec 600 --distance-bucket-m 25 --branches no_zone_binding,no_continuity,no_continuity_osnma_lifted,no_cadence
python script/run_e1_forensic.py --inputs data/e1_mechanism_ablation/porto/periods_60s.jsonl --output experiments/e1_other_datasets/porto_e1_rows.csv --summary experiments/e1_other_datasets/porto_e1_summary.csv --audit-output experiments/e1_receipts/e1_porto_pinned_receipt.json --max-users 0 --periods-per-user 0 --cadence-sec 60 --max-dt-sec 600 --distance-bucket-m 25 --branches no_zone_binding,no_continuity,no_continuity_osnma_lifted,no_cadence
python script/run_e1_forensic.py --inputs data/e1_mechanism_ablation/rome/periods_60s.jsonl --output experiments/e1_other_datasets/rome_e1_rows.csv --summary experiments/e1_other_datasets/rome_e1_summary.csv --audit-output experiments/e1_receipts/e1_rome_pinned_receipt.json --max-users 0 --periods-per-user 0 --cadence-sec 60 --max-dt-sec 600 --distance-bucket-m 25 --branches no_zone_binding,no_continuity,no_continuity_osnma_lifted,no_cadence
```

## Pinned Receipt Interpretation

For `no_continuity`, pinned OSNMA keeps measured savings at 0.0 in all three datasets.

- T-Drive: 1/1 pinned replay checks fail with `osnma` pinned-cell mismatch, and receipt savings is 0.0.
- Porto: 10/10 pinned replay checks fail with `osnma` pinned-cell mismatch, and receipt savings is 0.0.
- Rome: 134/162 periods have a positive lifted continuity attack; all 134 are rejected under pinned OSNMA with pinned-cell mismatch. The other 28 periods have no positive lifted attack, so pinned savings is also 0.0.

The combined summary is `experiments/e1_other_datasets/e1_other_datasets_summary.csv`.
