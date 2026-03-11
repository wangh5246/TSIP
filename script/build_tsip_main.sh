#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

CIRCUIT_NAME="tsip_main"
OUT_DIR="${OUT_DIR:-zk/tsip_main}"
BUILD_DIR="${OUT_DIR}"
PTAU_FILE="${PTAU_FILE:-zk/hello/pot12_final.ptau}"

if [[ -d "./node_modules/circomlib" ]]; then
  CIRCOMLIB_INCLUDE="./node_modules"
elif [[ -d "$HOME/node_modules/circomlib" ]]; then
  CIRCOMLIB_INCLUDE="$HOME/node_modules"
elif [[ -d "/Users/wanghao/node_modules/circomlib" ]]; then
  CIRCOMLIB_INCLUDE="/Users/wanghao/node_modules"
else
  echo "error: circomlib not found; install it under ./node_modules, \$HOME/node_modules, or /Users/wanghao/node_modules" >&2
  exit 1
fi

mkdir -p "$BUILD_DIR"

echo "== compile ${CIRCUIT_NAME} =="
circom "circuits/${CIRCUIT_NAME}.circom" \
  --r1cs \
  --wasm \
  --sym \
  -o "$BUILD_DIR" \
  -l "$CIRCOMLIB_INCLUDE"

echo "== r1cs info =="
snarkjs r1cs info "${BUILD_DIR}/${CIRCUIT_NAME}.r1cs"

echo "== groth16 setup =="
snarkjs groth16 setup \
  "${BUILD_DIR}/${CIRCUIT_NAME}.r1cs" \
  "$PTAU_FILE" \
  "${BUILD_DIR}/${CIRCUIT_NAME}_0000.zkey"

echo "== contribute =="
snarkjs zkey contribute \
  "${BUILD_DIR}/${CIRCUIT_NAME}_0000.zkey" \
  "${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey" \
  --name="tsip-main" \
  -v \
  -e="tsip main entropy"

echo "== export verification key =="
snarkjs zkey export verificationkey \
  "${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey" \
  "${BUILD_DIR}/verification_key.json"

echo "built:"
echo "  wasm: ${BUILD_DIR}/${CIRCUIT_NAME}_js/${CIRCUIT_NAME}.wasm"
echo "  zkey: ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey"
echo "  vkey: ${BUILD_DIR}/verification_key.json"
