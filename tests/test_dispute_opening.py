from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from common.dispute import (
    build_interval_opening,
    build_interval_records,
    opening_disclosure_profile,
    verify_interval_opening,
)
from common.settlement import (
    ReceiverFix,
    TariffTable,
    commitment_chain_root,
    fee_for_period,
    field_from_text,
    make_device_attestation_commitment,
    sign_receiver_fix,
)

_TEST_SEED = hashlib.sha256(b"tsip-test-device-key-v1").digest()
_TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(_TEST_SEED)
_TEST_PUBLIC_KEY_BYTES = _TEST_PRIVATE_KEY.public_key().public_bytes_raw()
_TEST_DAC = make_device_attestation_commitment(_TEST_PUBLIC_KEY_BYTES)
_MAY_2026_START = 1_777_593_600

_CADENCE_SEC = 300
_TIER_VMAX_MPS = 33


def _fix(seq: int, ts: int, odo: int, x: int, y: int, period: str = "2026-05-p01") -> ReceiverFix:
    raw = ReceiverFix(
        device_id="dev-1",
        period_id=period,
        fix_seq=seq,
        auth_gnss_time=_MAY_2026_START + ts,
        cell_x=x,
        cell_y=y,
        osnma_status="authenticated",
        odometer_reading_m=odo,
        nonce=f"nonce-{seq}",
    )
    return sign_receiver_fix(raw, _TEST_SEED)


def _tariff() -> TariffTable:
    # 2x2 grid: zone 0 cheap (1 cent/m), zone 1 expensive (5 cents/m).
    return TariffTable(
        tariff_version=7,
        grid_w=2,
        cell_zones={0: 0, 1: 0, 2: 1, 3: 1},
        zone_rates_cents_per_m={0: 1, 1: 5},
    )


def _fixes() -> list[ReceiverFix]:
    # Four fixes / three intervals; the middle interval exceeds cadence -> fallback.
    return [
        _fix(0, 0, 0, 0, 0),
        _fix(1, 300, 600, 1, 0),
        _fix(2, 900, 1200, 0, 1),
        _fix(3, 1200, 1500, 1, 1),
    ]


def _root(fixes: list[ReceiverFix], tariff: TariffTable) -> int:
    fee = fee_for_period(
        fixes,
        tariff,
        cadence_sec=_CADENCE_SEC,
        tier_vmax_mps=_TIER_VMAX_MPS,
        dac_field=field_from_text(_TEST_DAC),
    )
    return int(fee["interval_commitment_root"])


def test_interval_records_match_fee_for_period_root() -> None:
    fixes, tariff = _fixes(), _tariff()
    records = build_interval_records(
        fixes,
        tariff,
        cadence_sec=_CADENCE_SEC,
        tier_vmax_mps=_TIER_VMAX_MPS,
        dac_field=field_from_text(_TEST_DAC),
    )
    assert len(records) == len(fixes) - 1
    assert commitment_chain_root([r["leaf"] for r in records]) == _root(fixes, tariff)
    assert [r["values"]["fallback_flag"] for r in records] == [0, 1, 0]


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("with_fixes", [False, True])
def test_opening_roundtrip(index: int, with_fixes: bool) -> None:
    fixes, tariff = _fixes(), _tariff()
    opening = build_interval_opening(
        fixes,
        tariff,
        index,
        cadence_sec=_CADENCE_SEC,
        tier_vmax_mps=_TIER_VMAX_MPS,
        device_attestation_commitment=_TEST_DAC,
        include_fix_opening=with_fixes,
    )
    result = verify_interval_opening(
        opening,
        interval_commitment_root=_root(fixes, tariff),
        expected_interval_count=len(fixes) - 1,
        device_attestation_commitment=_TEST_DAC,
        device_public_key_bytes=_TEST_PUBLIC_KEY_BYTES if with_fixes else None,
        tariff=tariff if with_fixes else None,
        cadence_sec=_CADENCE_SEC,
        tier_vmax_mps=_TIER_VMAX_MPS,
    )
    assert result["ok"], result["failed"]


def test_tampered_fee_fails_chain_root() -> None:
    fixes, tariff = _fixes(), _tariff()
    opening = build_interval_opening(
        fixes,
        tariff,
        1,
        cadence_sec=_CADENCE_SEC,
        tier_vmax_mps=_TIER_VMAX_MPS,
        device_attestation_commitment=_TEST_DAC,
    )
    opening["interval"]["fee_cents"] = str(int(opening["interval"]["fee_cents"]) - 100)
    result = verify_interval_opening(
        opening,
        interval_commitment_root=_root(fixes, tariff),
        expected_interval_count=3,
    )
    assert not result["ok"]
    assert "chain_root" in result["failed"]


def test_position_shift_is_rejected() -> None:
    # Claiming a different interval position without adjusting the suffix
    # must fail positional binding.
    fixes, tariff = _fixes(), _tariff()
    opening = build_interval_opening(
        fixes,
        tariff,
        1,
        cadence_sec=_CADENCE_SEC,
        tier_vmax_mps=_TIER_VMAX_MPS,
        device_attestation_commitment=_TEST_DAC,
    )
    opening["interval_index"] = 2
    result = verify_interval_opening(
        opening,
        interval_commitment_root=_root(fixes, tariff),
        expected_interval_count=3,
    )
    assert not result["ok"]
    assert "position_binding" in result["failed"]


def test_wrong_root_fails() -> None:
    fixes, tariff = _fixes(), _tariff()
    opening = build_interval_opening(
        fixes,
        tariff,
        0,
        cadence_sec=_CADENCE_SEC,
        tier_vmax_mps=_TIER_VMAX_MPS,
        device_attestation_commitment=_TEST_DAC,
    )
    result = verify_interval_opening(opening, interval_commitment_root=_root(fixes, tariff) + 1)
    assert not result["ok"]
    assert "chain_root" in result["failed"]


def test_fix_opening_binds_commitments_and_billing() -> None:
    fixes, tariff = _fixes(), _tariff()
    opening = build_interval_opening(
        fixes,
        tariff,
        2,
        cadence_sec=_CADENCE_SEC,
        tier_vmax_mps=_TIER_VMAX_MPS,
        device_attestation_commitment=_TEST_DAC,
        include_fix_opening=True,
    )
    tampered = copy.deepcopy(opening)
    tampered["fix_opening"]["curr"]["cell_x"] = 0  # move the disputed fix to a cheaper cell
    result = verify_interval_opening(
        tampered,
        interval_commitment_root=_root(fixes, tariff),
        expected_interval_count=3,
        device_attestation_commitment=_TEST_DAC,
        tariff=tariff,
        cadence_sec=_CADENCE_SEC,
        tier_vmax_mps=_TIER_VMAX_MPS,
    )
    assert not result["ok"]
    assert "curr_fix_commitment" in result["failed"]


def test_fix_opening_signature_check() -> None:
    fixes, tariff = _fixes(), _tariff()
    opening = build_interval_opening(
        fixes,
        tariff,
        0,
        cadence_sec=_CADENCE_SEC,
        tier_vmax_mps=_TIER_VMAX_MPS,
        device_attestation_commitment=_TEST_DAC,
        include_fix_opening=True,
    )
    other_key = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"other-device").digest())
    result = verify_interval_opening(
        opening,
        interval_commitment_root=_root(fixes, tariff),
        device_attestation_commitment=_TEST_DAC,
        device_public_key_bytes=other_key.public_key().public_bytes_raw(),
    )
    assert not result["ok"]
    assert "fix_signatures" in result["failed"]


def test_malformed_opening_reports_failure() -> None:
    result = verify_interval_opening({"domain_sep": "bogus"}, interval_commitment_root=1)
    assert not result["ok"]
    assert "malformed_opening" in result["failed"]


def test_disclosure_profile_levels() -> None:
    fixes, tariff = _fixes(), _tariff()
    kwargs = dict(
        cadence_sec=_CADENCE_SEC,
        tier_vmax_mps=_TIER_VMAX_MPS,
        device_attestation_commitment=_TEST_DAC,
    )
    level1 = build_interval_opening(fixes, tariff, 1, **kwargs)
    level2 = build_interval_opening(fixes, tariff, 1, include_fix_opening=True, **kwargs)
    profile1 = opening_disclosure_profile(level1)
    profile2 = opening_disclosure_profile(level2)
    # Level 1 reveals only the disputed interval's billing tuple.
    assert profile1 == [f"interval[1].{k}" for k in (
        "prev_fix_commitment",
        "curr_fix_commitment",
        "odo_delta_m",
        "zone_id",
        "zone_rate_cents_per_m",
        "fee_cents",
        "fallback_flag",
    )]
    # Level 2 adds exactly the two bounding fixes, nothing about other intervals.
    assert set(profile1) < set(profile2)
    assert not any("interval[0]" in f or "interval[2]" in f for f in profile2)
