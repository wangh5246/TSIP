from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.tsip import (
    commitment_to_field,
    compute_chain_commitment,
    compute_location_commitment,
)


def test_location_commitment_depends_on_coordinates():
    c1 = compute_location_commitment("u", 100, 200, 1000, 10, "")
    c2 = compute_location_commitment("u", 101, 200, 1000, 10, "")
    assert c1 != c2
    assert commitment_to_field(c1) != commitment_to_field(c2)


def test_chain_commitment_binds_previous_chain_and_time():
    loc = compute_location_commitment("u", 100, 200, 1000, 10, "")
    chain1 = compute_chain_commitment("", loc, 1000, 10)
    chain2 = compute_chain_commitment(chain1, loc, 1060, 11)
    chain3 = compute_chain_commitment("", loc, 1060, 11)

    assert chain1 != chain2
    assert chain2 != chain3
