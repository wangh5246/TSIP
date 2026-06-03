#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

R1CS="zk/settlement_period_v5_k6/settlement_period_v5_k6.r1cs"
PTAU="zk/hello/pot18_final.ptau"
PTAU_PHASE2="zk/hello/pot18_final_phase2.ptau"
ZKEY_0000="zk/settlement_period_v5_k6/settlement_period_v5_k6_0000.zkey"
ZKEY_FINAL="zk/settlement_period_v5_k6/settlement_period_v5_k6_final.zkey"
VKEY="zk/settlement_period_v5_k6/verification_key.json"

if [[ ! -f "$PTAU_PHASE2" ]]; then
  echo "== prepare Phase-2 PTAU =="
  snarkjs powersoftau prepare phase2 "$PTAU" "$PTAU_PHASE2" -v
fi

echo "== Groth16 setup =="
snarkjs groth16 setup "$R1CS" "$PTAU_PHASE2" "$ZKEY_0000"

echo "== local contribution =="
ENTROPY="${SETTLEMENT_ZKEY_ENTROPY:-$(openssl rand -hex 32)}"
snarkjs zkey contribute \
  "$ZKEY_0000" \
  "$ZKEY_FINAL" \
  --name="TSIP settlement v5 k6" \
  -e="$ENTROPY"

echo "== export verification key =="
snarkjs zkey export verificationkey "$ZKEY_FINAL" "$VKEY"

echo "== verify artifact =="
snarkjs zkey verify "$R1CS" "$PTAU_PHASE2" "$ZKEY_FINAL"

echo "== remove intermediate zkey =="
rm -f "$ZKEY_0000"
