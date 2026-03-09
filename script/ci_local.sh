#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "== local ci: py_compile =="
python3 -m py_compile \
  services/aggregator_a/app.py \
  services/aggregator_r/app.py \
  services/decoder/app.py \
  services/shuffler/app.py \
  client/sim/client.py

echo "== local ci: P0 smoke check =="
bash script/p0_smoke_check.sh

echo "local ci passed"
