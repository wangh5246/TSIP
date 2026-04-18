#!/usr/bin/env bash
# build_tsip_main_v3.sh — compile TSIP v3 circuits (k6 + k30) and run Groth16 setup.
#
# Usage:
#   bash script/build_tsip_main_v3.sh
#
# Outputs:
#   zk/tsip_main_v3_k6/*
#   zk/tsip_main_v3_k30/*

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PTAU_FILE="${PTAU_FILE:-zk/hello/pot12_final.ptau}"

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
  echo ""
  echo "═══════════════════════════════════════════"
  echo "  Building ${name}"
  echo "═══════════════════════════════════════════"

  circom "circuits/${name}.circom" \
    --r1cs \
    --wasm \
    --sym \
    -o "$out_dir" \
    -l "$CIRCOMLIB_INCLUDE"

  snarkjs r1cs info "${out_dir}/${name}.r1cs"

  snarkjs groth16 setup \
    "${out_dir}/${name}.r1cs" \
    "$PTAU_FILE" \
    "${out_dir}/${name}_0000.zkey"

  snarkjs zkey contribute \
    "${out_dir}/${name}_0000.zkey" \
    "${out_dir}/${name}_final.zkey" \
    --name="${name}-dev" \
    -v \
    -e="tsip main v3 ${name} dev entropy 2026-04-18"

  snarkjs zkey export verificationkey \
    "${out_dir}/${name}_final.zkey" \
    "${out_dir}/verification_key.json"

  echo "  wasm : ${out_dir}/${name}_js/${name}.wasm"
  echo "  zkey : ${out_dir}/${name}_final.zkey"
  echo "  vkey : ${out_dir}/verification_key.json"
}

build_one "tsip_main_v3_k6" "zk/tsip_main_v3_k6"
build_one "tsip_main_v3_k30" "zk/tsip_main_v3_k30"

echo ""
echo "done: TSIP v3 artifacts generated."
