#!/usr/bin/env python3
"""
test_tsip_main_v3.py — tsip_main_v3_{k6|k30} end-to-end Groth16 checks.

Run:
  python script/test_tsip_main_v3.py
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from common.tsip import _poseidon2_hash, SNARK_FIELD, compute_policy_cap_sq, compute_tier_anchor_cap_sq  # noqa: E402

PROFILE = os.getenv("TSIP_CIRCUIT_PROFILE", "k6").strip().lower()
if PROFILE not in {"k6", "k30"}:
    PROFILE = "k6"
K_WINDOW = 30 if PROFILE == "k30" else 6

ART_DIR = ROOT / "zk" / f"tsip_main_v3_{PROFILE}"
CIRCUIT_NAME = f"tsip_main_v3_{PROFILE}"
WASM = ART_DIR / f"{CIRCUIT_NAME}_js" / f"{CIRCUIT_NAME}.wasm"
ZKEY = ART_DIR / f"{CIRCUIT_NAME}_final.zkey"
VKEY = ART_DIR / "verification_key.json"
SNARKJS = os.getenv("SNARKJS_BIN", "snarkjs")


def _run(cmd: list[str], cwd: str | None = None) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:500])
    return (r.stdout + r.stderr).strip()


def poseidon2(a: int, b: int) -> int:
    return _poseidon2_hash(int(a) % SNARK_FIELD, int(b) % SNARK_FIELD)


# Witness values
X1, Y1 = 100000, 200000
X2, Y2 = 100080, 200060
XA, YA = 100020, 200020

STEP_DT = 60
STEP_DT_SQ = STEP_DT * STEP_DT
TIER_VMAX_SQ = 1600  # transit tier
TIER_ANCHOR_CAP_SQ = int(compute_tier_anchor_cap_sq(TIER_VMAX_SQ, K_WINDOW, STEP_DT_SQ))
CAP_POLICY_SQ = int(compute_policy_cap_sq(TIER_ANCHOR_CAP_SQ, 0.5))

PAYLOAD_DIGEST = hashlib.sha256(json.dumps(sorted([0, 1, 2, 3]), separators=(",", ":")).encode()).hexdigest()
PAYLOAD_LO = int(PAYLOAD_DIGEST[:32], 16) % SNARK_FIELD
PAYLOAD_HI = int(PAYLOAD_DIGEST[32:], 16) % SNARK_FIELD

SECRET = int(hashlib.sha256(b"secret_alice").hexdigest(), 16) % SNARK_FIELD
USER_ID_FIELD = int(hashlib.sha256(b"user_alice").hexdigest(), 16) % SNARK_FIELD

HASH_PREV = poseidon2(X1, Y1)
HASH_CURR = poseidon2(X2, Y2)
HASH_ANCHOR = poseidon2(XA, YA)
PAYLOAD_COMMITMENT = poseidon2(PAYLOAD_LO, PAYLOAD_HI)
SECRET_COMMITMENT = poseidon2(SECRET, USER_ID_FIELD)

MODESET_BITMAP = 0b1111
MODESET_SALT = int(hashlib.sha256(b"modeset_salt_alice").hexdigest(), 16) % SNARK_FIELD
MODESET_COMMITMENT = poseidon2(MODESET_BITMAP, MODESET_SALT)
MODE_ID = 2  # vehicle
MODE_S0, MODE_S1, MODE_S2, MODE_S3 = 0, 0, 1, 0
MODE_TAG = poseidon2(MODE_ID, SECRET)

VALID_INPUT = {
    # private
    "x1": str(X1),
    "y1": str(Y1),
    "x2": str(X2),
    "y2": str(Y2),
    "x_anchor": str(XA),
    "y_anchor": str(YA),
    "payload_lo": str(PAYLOAD_LO),
    "payload_hi": str(PAYLOAD_HI),
    "secret": str(SECRET),
    "user_id_field": str(USER_ID_FIELD),
    "modeset_bitmap": str(MODESET_BITMAP),
    "modeset_salt": str(MODESET_SALT),
    "mode_s0": str(MODE_S0),
    "mode_s1": str(MODE_S1),
    "mode_s2": str(MODE_S2),
    "mode_s3": str(MODE_S3),
    # public
    "hash_prev": str(HASH_PREV),
    "hash_curr": str(HASH_CURR),
    "hash_anchor": str(HASH_ANCHOR),
    "step_dt_sq": str(STEP_DT_SQ),
    "tier_vmax_sq": str(TIER_VMAX_SQ),
    "tier_anchor_cap_sq": str(TIER_ANCHOR_CAP_SQ),
    "cap_policy_sq": str(CAP_POLICY_SQ),
    "payload_commitment": str(PAYLOAD_COMMITMENT),
    "secret_commitment": str(SECRET_COMMITMENT),
    "modeset_commitment": str(MODESET_COMMITMENT),
    "mode_tag": str(MODE_TAG),
}


PASS_C = "\033[32mPASS\033[0m"
FAIL_C = "\033[31mFAIL\033[0m"
results: list[bool] = []


def prove_and_verify(circuit_input: dict, tamper_public: dict | None = None) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="tsip_v3_test_") as td:
        td = Path(td)
        inp_path = td / "input.json"
        wit_path = td / "witness.wtns"
        proof_path = td / "proof.json"
        pub_path = td / "public.json"
        inp_path.write_text(json.dumps(circuit_input), encoding="utf-8")

        try:
            _run([SNARKJS, "wtns", "calculate", str(WASM), str(inp_path), str(wit_path)])
        except RuntimeError as e:
            return False, f"witness generation failed: {e}"

        try:
            _run([SNARKJS, "groth16", "prove", str(ZKEY), str(wit_path), str(proof_path), str(pub_path)])
        except RuntimeError as e:
            return False, f"prove failed: {e}"

        if tamper_public:
            pub = json.loads(pub_path.read_text(encoding="utf-8"))
            for idx, val in tamper_public.items():
                pub[int(idx)] = val
            pub_path.write_text(json.dumps(pub), encoding="utf-8")

        try:
            out = _run([SNARKJS, "groth16", "verify", str(VKEY), str(pub_path), str(proof_path)])
            if "OK" in out:
                return True, "verification OK"
            return False, f"verification returned: {out[:100]}"
        except RuntimeError as e:
            return False, f"verification failed: {e}"


def check(name: str, ok: bool, msg: str, expect_ok: bool) -> None:
    passed = ok == expect_ok
    badge = PASS_C if passed else FAIL_C
    print(f"  [{badge}] {name}")
    print(f"         expect={'accept' if expect_ok else 'reject'} got={'accept' if ok else 'reject'} msg={msg[:100]}")
    results.append(passed)


print(f"\n═══ TSIP v3 circuit profile={PROFILE} K={K_WINDOW} ═══")

print("\n═══ T1: valid proof/public → EXPECT accept ═══")
ok, msg = prove_and_verify(VALID_INPUT)
check("T1 valid", ok, msg, expect_ok=True)

print("\n═══ T2: tamper tier_vmax_sq (public[4]) → EXPECT reject ═══")
ok, msg = prove_and_verify(VALID_INPUT, tamper_public={4: str(TIER_VMAX_SQ + 1)})
check("T2 tier_vmax_sq", ok, msg, expect_ok=False)

print("\n═══ T3: tamper modeset_commitment (public[9]) → EXPECT reject ═══")
ok, msg = prove_and_verify(VALID_INPUT, tamper_public={9: str((MODESET_COMMITMENT + 1) % SNARK_FIELD)})
check("T3 modeset_commitment", ok, msg, expect_ok=False)

print("\n═══ T4: tamper mode_tag (public[10]) → EXPECT reject ═══")
ok, msg = prove_and_verify(VALID_INPUT, tamper_public={10: str((MODE_TAG + 1) % SNARK_FIELD)})
check("T4 mode_tag", ok, msg, expect_ok=False)

print("\n═══ T5: tamper hash_anchor (public[2]) → EXPECT reject ═══")
ok, msg = prove_and_verify(VALID_INPUT, tamper_public={2: str((HASH_ANCHOR + 1) % SNARK_FIELD)})
check("T5 hash_anchor", ok, msg, expect_ok=False)

print("\n═══ T6: tamper cap_policy_sq (public[6]) → EXPECT reject ═══")
ok, msg = prove_and_verify(VALID_INPUT, tamper_public={6: str(CAP_POLICY_SQ + 1)})
check("T6 cap_policy_sq", ok, msg, expect_ok=False)

print("\n═══ T7: tamper tier_anchor_cap_sq (public[5]) → EXPECT reject ═══")
ok, msg = prove_and_verify(VALID_INPUT, tamper_public={5: str(TIER_ANCHOR_CAP_SQ + 1)})
check("T7 tier_anchor_cap_sq", ok, msg, expect_ok=False)

print("\n═══ T8: input cap_policy_sq > tier_anchor_cap_sq → EXPECT reject ═══")
bad_input = dict(VALID_INPUT)
bad_input["cap_policy_sq"] = str(TIER_ANCHOR_CAP_SQ + 1)
ok, msg = prove_and_verify(bad_input)
check("T8 cap_policy_vs_tier", ok, msg, expect_ok=False)

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
passed = sum(results)
total = len(results)
print(f"  {passed}/{total} tests passed")
if all(results):
    print("\n  All tests PASSED.")
    print("  ✓ Anchor hash binding is explicit and enforced")
    print("  ✓ Mode membership / mode tag bindings are enforced")
    print("  ✓ tier_anchor_cap_sq and cap_policy_sq relations are enforced")
    sys.exit(0)
print("\n  Some tests FAILED.")
sys.exit(1)
