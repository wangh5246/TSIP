# E1 Mechanism Ablation Receipt

This directory stores the receipt for Table `tab:e1-mechanism-ablation`.

Input:

`data/e1_mechanism_ablation/geolife/geolife_medium_identity.jsonl`

Tariff:

`data/e1_mechanism_ablation/geolife/tariff_block.json`

Command:

```bash
python script/run_e1_forensic.py \
  --inputs data/e1_mechanism_ablation/geolife/geolife_medium_identity.jsonl \
  --output experiments/e1_forensic_rows.csv \
  --summary experiments/e1_forensic_summary.csv \
  --audit-output experiments/e1_receipts/e1_geolife_14period_pinned_receipt.json \
  --max-users 53 \
  --periods-per-user 0 \
  --cadence-sec 60 \
  --max-dt-sec 600 \
  --distance-bucket-m 25 \
  --branches no_zone_binding,no_continuity,no_continuity_osnma_lifted,no_cadence
```

The pinned `no_continuity` receipt replays the lifted continuity attack under
the pinned OSNMA branch. The expected result is 14/14 `chk.passed=false` with
`receipt_savings_ratio=0.0`.
