#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
: "${WAYBILL_WORKSPACE:?set WAYBILL_WORKSPACE to the target formal workspace}"
: "${WAYBILL_CONTAINER_DIGEST:?set WAYBILL_CONTAINER_DIGEST to the observed immutable digest}"
: "${WAYBILL_EXPECTED_CONTAINER_DIGEST:?set WAYBILL_EXPECTED_CONTAINER_DIGEST to the frozen digest}"
: "${WAYBILL_PTAU:?set WAYBILL_PTAU to powersOfTau28_hez_final_22.ptau}"

OUTPUT=${1:-"$WAYBILL_WORKSPACE/target-host-preflight.json"}
cd "$ROOT"
python script/waybill_formal.py host-preflight \
  --workspace "$WAYBILL_WORKSPACE" \
  --ptau "$WAYBILL_PTAU" \
  --container-digest "$WAYBILL_CONTAINER_DIGEST" \
  --expected-container-digest "$WAYBILL_EXPECTED_CONTAINER_DIGEST" \
  --required-workspace-gib "${WAYBILL_REQUIRED_WORKSPACE_GIB:-500}" \
  --output "$OUTPUT"
