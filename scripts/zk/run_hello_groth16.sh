#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/build/hello"

circom "$ROOT/circuits/hello.circom" --r1cs --wasm --sym -o .

snarkjs powersoftau new bn128 12 pot12_0000.ptau -v
snarkjs powersoftau contribute pot12_0000.ptau pot12_0001.ptau --name="first" -v -e="test entropy"
snarkjs powersoftau prepare phase2 pot12_0001.ptau pot12_final.ptau -v

snarkjs groth16 setup hello.r1cs pot12_final.ptau hello_0000.zkey
snarkjs zkey contribute hello_0000.zkey hello_final.zkey --name="1st Contributor" -v -e="more entropy"
snarkjs zkey export verificationkey hello_final.zkey verification_key.json

cat > input.json <<'JSON'
{"a":3,"b":11}
JSON

snarkjs wtns calculate hello_js/hello.wasm input.json witness.wtns
snarkjs groth16 prove hello_final.zkey witness.wtns proof.json public.json
snarkjs groth16 verify verification_key.json public.json proof.json
