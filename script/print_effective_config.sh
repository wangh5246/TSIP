#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
python script/waybill_formal.py validate-config
python script/waybill_formal.py plan \
  --output-dir "${1:-artifacts/waybill_formal/plan}" || status=$?
if [[ ${status:-0} -eq 3 ]]; then
  echo "Static protocol is valid; final cardinality awaits the full prepared manifest." >&2
  exit 3
fi
exit "${status:-0}"
