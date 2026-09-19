"""A0b regression: memoized Poseidon2 must be byte-identical to the sealed
pure implementation, and the memoization must be invisible to callers.

Background (2026-09-19): the S5 handler verify path spent ~207 ms/request in
pure-Python Poseidon2 hashing.  Across a corpus the tariff Merkle interior
nodes and fix-commitment chain prefixes repeat heavily (measured 49.1%
distinct-input redundancy over 10 bundles), so ``_poseidon2`` is now an
``lru_cache`` wrapper keyed on exact integer inputs.  The hash is a pure
function of its inputs, so caching cannot change any output -- this test
pins that property against the sealed (pre-cache) implementation extracted
from the V14 seal commit.
"""
from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

from common.poseidon2_constants import P

ROOT = Path(__file__).resolve().parents[1]
SEAL_COMMIT = "3c9a13e7"


def _sealed_poseidon2():
    """Load the sealed (uncached) implementation from the V14 seal commit."""
    src = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{SEAL_COMMIT}:common/poseidon2_py.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    scratch = ROOT / ".wb_scratch"
    scratch.mkdir(exist_ok=True)
    sealed_path = scratch / "_poseidon_sealed_under_test.py"
    sealed_path.write_text(src, encoding="utf-8")
    import importlib.util

    spec = importlib.util.spec_from_file_location("poseidon_sealed_under_test", sealed_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["poseidon_sealed_under_test"] = module
    spec.loader.exec_module(module)
    return module._poseidon2


def test_poseidon2_matches_sealed_implementation():
    sealed = _sealed_poseidon2()
    from common.poseidon2_py import _poseidon2

    rng = random.Random(20260919)
    for _ in range(200):
        x = rng.randrange(0, 2**254)
        y = rng.randrange(0, 2**254)
        assert _poseidon2(x, y) == sealed(x, y), (x, y)

    # Edge cases: zero, one, field elements, and wrap-around inputs.
    edges = [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
        (int(P) - 1, int(P) - 1),
        (int(P), int(P)),
        (int(P) + 1, 0),
        (2**256 - 1, 2**256 - 1),
    ]
    for x, y in edges:
        assert _poseidon2(x, y) == sealed(x, y), (x, y)


def test_poseidon2_cache_is_invisible_to_callers():
    """Repeated calls, cache clearing, and non-int numeric types must all
    return the same digest for the same logical input."""
    from common.poseidon2_py import _poseidon2, _poseidon2_cached

    x, y = 0x1234567890ABCDEF, 0xFEDCBA0987654321
    first = _poseidon2(x, y)

    # Repeated call hits the memo but returns the same value.
    assert _poseidon2(x, y) == first

    # bool is an int subclass; True/False must reduce like 1/0.
    assert _poseidon2(True, False) == _poseidon2(1, 0)

    # After clearing the memo the digest is unchanged.
    _poseidon2_cached.cache_clear()
    assert _poseidon2(x, y) == first
    assert _poseidon2(True, False) == _poseidon2(1, 0)


def test_poseidon2_cache_populates_and_clears():
    """The memo must actually engage (hits recorded) and clear cleanly."""
    from common.poseidon2_py import _poseidon2_cached

    _poseidon2_cached.cache_clear()
    info_before = _poseidon2_cached.cache_info()
    assert info_before.currsize == 0

    _poseidon2_cached(11, 22)
    _poseidon2_cached(11, 22)
    info = _poseidon2_cached.cache_info()
    assert info.misses >= 1
    assert info.hits >= 1
    assert info.currsize >= 1

    _poseidon2_cached.cache_clear()
    assert _poseidon2_cached.cache_info().currsize == 0
