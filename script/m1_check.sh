#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
python -m pytest -q \
  tests/test_settlement_v6.py \
  tests/test_run_waybill_m1_v6_gate.py \
  tests/test_charger_v6_period.py \
  tests/test_charger_v6_month_close.py
