from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import (
    ReceiverFix,
    TariffTable,
    build_period_public_statement,
    canonical_month_window,
    month_window_from_period_start,
    compute_fix_commitment,
    fee_for_period,
    make_device_attestation_commitment,
    merkle_path,
    merkleize,
    sign_receiver_fix,
    verify_fix_sequence,
    verify_merkle_path,
    verify_period_submission,
)

# Deterministic test key pair derived from a fixed seed.
# Using a hash of a known string guarantees reproducibility while
# producing a valid Ed25519 key that is not a hardcoded constant in code.
_TEST_SEED = hashlib.sha256(b"tsip-test-device-key-v1").digest()
_TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(_TEST_SEED)
_TEST_PUBLIC_KEY_BYTES = _TEST_PRIVATE_KEY.public_key().public_bytes_raw()
_TEST_DAC = make_device_attestation_commitment(_TEST_PUBLIC_KEY_BYTES)
_MAY_2026_START = 1_777_593_600


def _fix(seq: int, ts: int, odo: int, x: int, y: int, period: str = "2026-05-p01") -> ReceiverFix:
    if ts < _MAY_2026_START:
        ts += _MAY_2026_START
    raw = ReceiverFix(
        device_id="dev-1",
        period_id=period,
        fix_seq=seq,
        auth_gnss_time=ts,
        cell_x=x,
        cell_y=y,
        osnma_status="authenticated",
        odometer_reading_m=odo,
        nonce=f"nonce-{seq}",
    )
    return sign_receiver_fix(raw, _TEST_SEED)


def _tariff() -> TariffTable:
    # 2x2 grid: cells 0,1 cheap; cells 2,3 expensive.
    return TariffTable(
        tariff_version=7,
        grid_w=2,
        cell_zones={0: 10, 1: 10, 2: 20, 3: 20},
        zone_rates_cents_per_m={10: 1, 20: 5},
    )


def test_receiver_signed_fix_sequence_rejects_replay_and_reorder():
    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    verify_fix_sequence(fixes, public_key_bytes=_TEST_PUBLIC_KEY_BYTES, period_id="2026-05-p01")

    replay = [fixes[0], _fix(1, 110, 1_070, 1, 0, period="2026-05-p01")]
    replay[1] = ReceiverFix(**{**replay[1].__dict__, "nonce": fixes[0].nonce})
    replay[1] = sign_receiver_fix(ReceiverFix(**{**replay[1].__dict__, "receiver_sig": ""}), _TEST_SEED)
    with pytest.raises(ValueError, match="duplicate receiver nonce"):
        verify_fix_sequence(replay, public_key_bytes=_TEST_PUBLIC_KEY_BYTES, period_id="2026-05-p01")

    with pytest.raises(ValueError, match="strictly increasing"):
        verify_fix_sequence(list(reversed(fixes)), public_key_bytes=_TEST_PUBLIC_KEY_BYTES, period_id="2026-05-p01")


def test_odometer_delta_tamper_is_rejected_by_signature():
    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    tampered = list(fixes)
    tampered[1] = ReceiverFix(**{**tampered[1].__dict__, "odometer_reading_m": 1_020})
    with pytest.raises(ValueError, match="invalid receiver signature"):
        verify_fix_sequence(tampered, public_key_bytes=_TEST_PUBLIC_KEY_BYTES, period_id="2026-05-p01")


def test_period_submission_rejects_odometer_tamper_with_stale_signature():
    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    tariff = _tariff()
    public = build_period_public_statement(
        fixes=fixes,
        tariff=tariff,
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    tampered = list(fixes)
    tampered[1] = ReceiverFix(
        **{
            **tampered[1].__dict__,
            "odometer_reading_m": 1_020,
        }
    )
    assert tampered[1].receiver_sig == fixes[1].receiver_sig

    with pytest.raises(ValueError, match="invalid receiver signature"):
        verify_period_submission(
            fixes=tampered,
            tariff=tariff,
            public_statement=public,
            public_key_bytes=_TEST_PUBLIC_KEY_BYTES,
            cadence_sec=60,
            tier_vmax_mps=33,
        )


def test_fix_commitment_is_deterministic_and_changes_on_odometer_change():
    fix = _fix(0, 100, 1_000, 0, 0)
    same = _fix(0, 100, 1_000, 0, 0)
    changed = _fix(0, 100, 1_001, 0, 0)
    assert compute_fix_commitment(fix) == compute_fix_commitment(same)
    assert compute_fix_commitment(fix) != compute_fix_commitment(changed)


def test_tariff_merkle_membership_for_cell_to_zone_lookup():
    tariff = _tariff()
    leaves = tariff.leaves()
    root = merkleize(leaves)
    path = tariff.path_for_cell(2)
    cell_2_index = sorted(tariff.cell_zones).index(2)
    assert path == merkle_path(leaves, cell_2_index)
    assert verify_merkle_path(tariff.leaf_for_cell(2), path, root)
    assert not verify_merkle_path(tariff.leaf_for_cell(1), path, root)


def test_sparse_fixes_do_not_reduce_attested_distance():
    fixes = [
        _fix(0, 100, 1_000, 0, 0),
        _fix(1, 110, 1_040, 1, 0),
        _fix(2, 120, 1_130, 1, 1),
    ]
    # Endpoint distance is one grid diagonal-ish segment, but the attested
    # odometer delta is 130 m and is the only distance counted.
    result = fee_for_period(fixes, _tariff(), cadence_sec=60, tier_vmax_mps=33)
    assert result["total_distance_m"] == 130
    assert result["total_fee_cents"] == 40 * 1 + 90 * 1


def test_odometer_delta_above_tier_speed_budget_is_rejected():
    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_331, 1, 0)]
    with pytest.raises(ValueError, match="odometer delta exceeds tier speed budget"):
        fee_for_period(fixes, _tariff(), cadence_sec=60, tier_vmax_mps=33)


def test_dropped_interval_uses_max_reachable_zone_rate_fallback():
    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 180, 1_100, 0, 1)]
    result = fee_for_period(fixes, _tariff(), cadence_sec=60, tier_vmax_mps=33)
    normal_fee = 100 * 1
    fallback_fee = 80 * 33 * 5
    assert result["fallback_intervals"] == 1
    assert result["fallback_distance_m"] == 80 * 33
    assert result["total_fee_cents"] == fallback_fee
    assert result["total_fee_cents"] > normal_fee


def test_period_public_statement_hides_route_timestamps_and_zone_histogram():
    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    public = build_period_public_statement(
        fixes=fixes,
        tariff=_tariff(),
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    assert public["total_fee_cents"] == 70
    assert public["total_distance_m"] == 70
    assert "private_zone_distance_m" not in public
    assert "auth_gnss_time" not in public
    assert "cell_x" not in public
    assert "cell_y" not in public


def test_canonical_month_window_uses_yyyymm_and_half_open_utc_boundaries():
    assert canonical_month_window("2026-05") == {
        "month_id": 202605,
        "month_start_time": 1_777_593_600,
        "month_end_time": 1_780_272_000,
    }


def test_month_window_from_period_start_assigns_boundary_second_to_one_utc_month():
    month_id, month_start, month_end = month_window_from_period_start(1_780_271_999)
    next_month_id, next_month_start, _next_month_end = month_window_from_period_start(month_end)

    assert month_id == 202605
    assert month_start == 1_777_593_600
    assert month_end == 1_780_272_000
    assert next_month_id == 202606
    assert next_month_start == month_end


def test_month_window_from_period_start_handles_leap_day():
    month_id, month_start, month_end = month_window_from_period_start(1_709_251_199)
    next_month_id, next_month_start, _next_month_end = month_window_from_period_start(month_end)

    assert month_id == 202402
    assert month_start == 1_706_745_600
    assert month_end == 1_709_251_200
    assert next_month_id == 202403
    assert next_month_start == month_end


def test_period_public_statement_binds_start_month_window_and_period_span():
    fixes = [_fix(0, 1_777_593_600, 1_000, 0, 0), _fix(1, 1_777_593_610, 1_070, 1, 0)]
    public = build_period_public_statement(
        fixes=fixes,
        tariff=_tariff(),
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )

    assert public["month_id"] == "2026-05"
    assert public["month_id_field"] == 202605
    assert public["period_start_time"] == 1_777_593_600
    assert public["period_end_time"] == 1_777_593_610
    assert public["month_start_time"] == 1_777_593_600
    assert public["month_end_time"] == 1_780_272_000


def test_period_submission_rejects_changed_tariff_root_or_total_fee():
    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    tariff = _tariff()
    public = build_period_public_statement(
        fixes=fixes,
        tariff=tariff,
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    verify_period_submission(
        fixes=fixes,
        tariff=tariff,
        public_statement=public,
        public_key_bytes=_TEST_PUBLIC_KEY_BYTES,
        cadence_sec=60,
        tier_vmax_mps=33,
    )

    bad_fee = copy.deepcopy(public)
    bad_fee["total_fee_cents"] += 1
    with pytest.raises(ValueError, match="total_fee_cents"):
        verify_period_submission(
            fixes=fixes,
            tariff=tariff,
            public_statement=bad_fee,
            public_key_bytes=_TEST_PUBLIC_KEY_BYTES,
            cadence_sec=60,
            tier_vmax_mps=33,
        )

    bad_tariff = TariffTable(
        tariff_version=7,
        grid_w=2,
        cell_zones={0: 10, 1: 20, 2: 20, 3: 20},
        zone_rates_cents_per_m={10: 1, 20: 5},
    )
    with pytest.raises(ValueError, match="tariff_root"):
        verify_period_submission(
            fixes=fixes,
            tariff=bad_tariff,
            public_statement=public,
            public_key_bytes=_TEST_PUBLIC_KEY_BYTES,
            cadence_sec=60,
            tier_vmax_mps=33,
        )
