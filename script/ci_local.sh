#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
python -m compileall -q common waybill_formal script services/charger tests
python -m flake8 \
  common/resource_probe.py \
  waybill_formal \
  script/waybill_formal.py \
  script/waybill_formal_cli.py \
  script/run_waybill_s1_formal_unit.py \
  script/run_waybill_s2_formal_unit.py \
  script/run_waybill_s3_formal_unit.py \
  script/run_waybill_s4_formal_unit.py \
  script/run_waybill_s5_formal_unit.py \
  script/materialize_waybill_formal_corpus.py \
  tests/test_waybill_formal.py \
  tests/test_waybill_formal_stages.py
PYTHONPATH="$ROOT" python -m mypy --explicit-package-bases \
  waybill_formal \
  common/resource_probe.py \
  script/waybill_formal_cli.py
python script/waybill_formal.py validate-config
script/run_pytests.sh
