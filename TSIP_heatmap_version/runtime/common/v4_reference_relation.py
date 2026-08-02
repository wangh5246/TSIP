"""Independent integer-level checks for the V4-paper admission statement.

This module deliberately does not import the Circom witness builders or the
route-validation helpers.  It is not a second SNARK implementation and does
not establish cryptographic soundness.  Its purpose is differential assurance:
it checks the public, integer, grid, and additive-share semantics that a
well-formed witness is intended to encode before the circuit is invoked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


GRID_WIDTH = 100
GRID_HEIGHT = 100
DOMAIN = GRID_WIDTH * GRID_HEIGHT
MASK_MODULUS = 1 << 32


@dataclass(frozen=True)
class ReferenceResult:
    accepted: bool
    reasons: tuple[str, ...]


def _integer(values: Mapping[str, object], name: str) -> int:
    try:
        return int(str(values[name]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer field {name}") from exc


def _in_grid(x: int, y: int) -> bool:
    return 0 <= x < GRID_WIDTH * 100 and 0 <= y < GRID_HEIGHT * 100


def check_witness(values: Mapping[str, object]) -> ReferenceResult:
    """Check relation semantics that can be evaluated over ordinary integers."""

    reasons: list[str] = []
    try:
        x1, y1 = _integer(values, "x1"), _integer(values, "y1")
        x2, y2 = _integer(values, "x2"), _integer(values, "y2")
        xa, ya = _integer(values, "x_anchor"), _integer(values, "y_anchor")
        px, py = _integer(values, "payload_cell_x"), _integer(values, "payload_cell_y")
        rx, ry = _integer(values, "payload_rem_x"), _integer(values, "payload_rem_y")
        primary = _integer(values, "payload_primary_idx")
        contribution = _integer(values, "contribution_bit")
        step_dt_sq = _integer(values, "step_dt_sq")
        tier_vmax_sq = _integer(values, "tier_vmax_sq")
        tier_anchor_cap_sq = _integer(values, "tier_anchor_cap_sq")
        cap_policy_sq = _integer(values, "cap_policy_sq")
    except ValueError as exc:
        return ReferenceResult(False, (str(exc),))

    if not all(_in_grid(x, y) for x, y in ((x1, y1), (x2, y2), (xa, ya))):
        reasons.append("coordinate outside public grid")
    if not (0 <= px < GRID_WIDTH and 0 <= py < GRID_HEIGHT):
        reasons.append("payload cell outside public grid")
    if not (0 <= rx < 100 and 0 <= ry < 100):
        reasons.append("payload remainder outside cell")
    if x2 != px * 100 + rx or y2 != py * 100 + ry:
        reasons.append("current coordinate and payload cell decomposition disagree")
    if primary != py * GRID_WIDTH + px or not (0 <= primary < DOMAIN):
        reasons.append("payload primary does not match payload cell")
    if contribution not in (0, 1):
        reasons.append("contribution bit is not Boolean")
    if step_dt_sq <= 0 or tier_vmax_sq <= 0:
        reasons.append("non-positive public time or tier bound")
    if cap_policy_sq < 0 or cap_policy_sq > tier_anchor_cap_sq:
        reasons.append("policy cap is outside tier anchor cap")
    return ReferenceResult(not reasons, tuple(reasons))


def check_route_shares(
    idx: Sequence[int], val_a: Sequence[int], val_r: Sequence[int], *, primary: int, contribution: int
) -> ReferenceResult:
    """Check canonical sparse additive reconstruction without field helpers."""

    reasons: list[str] = []
    if not (len(idx) == len(val_a) == len(val_r)):
        reasons.append("sparse package lengths differ")
        return ReferenceResult(False, tuple(reasons))
    if list(idx) != sorted(idx) or len(set(idx)) != len(idx):
        reasons.append("sparse support is not canonical")
    if any(cell < 0 or cell >= DOMAIN for cell in idx):
        reasons.append("sparse support contains an out-of-domain cell")
    expected = {int(primary): int(contribution)} if contribution else {}
    reconstructed: dict[int, int] = {}
    for cell, a, r in zip(idx, val_a, val_r):
        if not (0 <= int(a) < MASK_MODULUS and 0 <= int(r) < MASK_MODULUS):
            reasons.append("share is outside unsigned 32-bit representation")
            break
        value = (int(a) + int(r)) % MASK_MODULUS
        if value:
            reconstructed[int(cell)] = value
    if reconstructed != expected:
        reasons.append("A/R shares do not reconstruct the canonical contribution")
    return ReferenceResult(not reasons, tuple(reasons))
