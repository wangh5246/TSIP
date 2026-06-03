#!/usr/bin/env bash
# Compile settlement v5 period circuits. Groth16 setup is intentionally left
# to the caller because the required PTAU size depends on the selected profile.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -d "./node_modules/circomlib" ]]; then
  CIRCOMLIB_INCLUDE="./node_modules"
elif [[ -d "$HOME/node_modules/circomlib" ]]; then
  CIRCOMLIB_INCLUDE="$HOME/node_modules"
elif [[ -d "/Users/wanghao/node_modules/circomlib" ]]; then
  CIRCOMLIB_INCLUDE="/Users/wanghao/node_modules"
else
  echo "error: circomlib not found" >&2
  exit 1
fi

build_one() {
  local name="$1"
  local out_dir="$2"
  mkdir -p "$out_dir"
  circom "circuits/${name}.circom" \
    --r1cs \
    --wasm \
    --sym \
    -o "$out_dir" \
    -l "$CIRCOMLIB_INCLUDE"
  snarkjs r1cs info "${out_dir}/${name}.r1cs"
}

build_one "settlement_period_v5_k6" "zk/settlement_period_v5_k6"
build_one "settlement_period_v5_k30" "zk/settlement_period_v5_k30"
