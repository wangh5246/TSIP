#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
python script/waybill_formal.py validate-config
python -m pytest -q tests/test_waybill_formal.py
echo "Preflight only: this command does not produce paper evidence."
