"""
Pure-Python Poseidon2 hash for BN254 (t=3 state, 2 inputs).

Matches circomlib's Poseidon(2) exactly. Used for SNARK-friendly
VDPF key generation and key digest. Constants extracted from
circomlib 2.0.5 poseidon_constants.circom.

Param: R_F=8, R_P=57, alpha=5, field=BN254 scalar.
"""
from __future__ import annotations

from common.poseidon2_constants import (
    P,
    POSEIDON_C,
    POSEIDON_M,
    POSEIDON_P,
    POSEIDON_S,
)


def _poseidon2(x: int, y: int) -> int:
    """Pure-Python Poseidon2 hash matching circomlib Poseidon(2)."""
    t = 3
    nRoundsF = 8
    nRoundsP = 57
    alpha = 5

    state = [0, int(x) % P, int(y) % P]

    # Round 0: Ark only
    for i in range(t):
        state[i] = (state[i] + POSEIDON_C[i]) % P

    # First-half full rounds (rounds 1-3)
    for half_r in range(nRoundsF // 2 - 1):
        for i in range(t):
            state[i] = pow(state[i], alpha, P)
        for i in range(t):
            state[i] = (state[i] + POSEIDON_C[i + (half_r + 1) * t]) % P
        state = _mix(state, POSEIDON_M)

    # Round 4 (last full round of first half, Mix with P)
    for i in range(t):
        state[i] = pow(state[i], alpha, P)
    half = nRoundsF // 2
    for i in range(t):
        state[i] = (state[i] + POSEIDON_C[i + half * t]) % P
    state = _mix(state, POSEIDON_P)

    # Partial rounds
    for p_r in range(nRoundsP):
        state[0] = pow(state[0], alpha, P)
        state[0] = (state[0] + POSEIDON_C[(half + 1) * t + p_r]) % P
        state = _mix_s(state, p_r)

    # Second-half full rounds (rounds after partials, except last)
    for half_r in range(nRoundsF // 2 - 1):
        for i in range(t):
            state[i] = pow(state[i], alpha, P)
        sec_offset = (half + 1) * t + nRoundsP + half_r * t
        for i in range(t):
            state[i] = (state[i] + POSEIDON_C[i + sec_offset]) % P
        state = _mix(state, POSEIDON_M)

    # Final S-box and output
    for i in range(t):
        state[i] = pow(state[i], alpha, P)

    # MixLast: out = sum_j M[j][0] * state[j]
    out = 0
    for j in range(t):
        out = (out + POSEIDON_M[j * t] * state[j]) % P
    return out


def _mix(state: list[int], mat: list[int]) -> list[int]:
    """Mix layer: out[i] = sum_j mat[j][i] * state[j]."""
    t = 3
    new = [0] * t
    for i in range(t):
        s = 0
        for j in range(t):
            s = (s + mat[j * t + i] * state[j]) % P
        new[i] = s
    return new


def _mix_s(state: list[int], r: int) -> list[int]:
    """Sparse Mix layer for partial round r."""
    t = 3
    base = r * (t * 2 - 1)  # r * 5
    new = [0] * t
    s = 0
    for i in range(t):
        s = (s + POSEIDON_S[base + i] * state[i]) % P
    new[0] = s
    for i in range(1, t):
        new[i] = (state[i] + state[0] * POSEIDON_S[base + t + i - 1]) % P
    return new
