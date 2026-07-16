from __future__ import annotations

import random
import hashlib
import json
import re
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
    fee_for_interval_values,
    make_device_attestation_commitment,
    sign_receiver_fix,
)
from common.policy_profile import PolicyProfile, validate_profile_local_artifacts
from common.settlement_v6 import (
    PUBLIC_SIGNAL_COUNT_V6,
    PUBLIC_SIGNAL_ORDER_V6,
    UINT32_MAX,
    UINT64_MAX,
    UINT96_MAX,
    build_period_public_statement_v6,
    fee_for_interval_values_v6,
    fee_for_period_v6,
    reconcile_month_v6,
    verify_period_submission_v6,
)
import common.settlement_v6 as settlement_v6
from script.prove_settlement_period_v6 import (
    build_input as build_circuit_input_v6,
    sha256_file,
)
from script.run_m1_odometer_fallback import run_m1_checks, validate_circuit_receipt


_DEVICE_SEED = hashlib.sha256(b"waybill-v6-reference-test-key").digest()
_DEVICE_PUBLIC_KEY = Ed25519PrivateKey.from_private_bytes(_DEVICE_SEED).public_key().public_bytes_raw()
_DEVICE_DAC = make_device_attestation_commitment(_DEVICE_PUBLIC_KEY)


def _fix(seq: int, timestamp: int, odometer_m: int, cell_x: int = 0, cell_y: int = 0) -> ReceiverFix:
    return ReceiverFix(
        device_id="dev-v6",
        period_id="2026-05-v6-p01",
        fix_seq=seq,
        auth_gnss_time=timestamp,
        cell_x=cell_x,
        cell_y=cell_y,
        osnma_status="authenticated",
        odometer_reading_m=odometer_m,
        nonce=f"nonce-{seq}",
    )


def _signed_fix(
    seq: int,
    timestamp: int,
    odometer_m: int,
    cell_x: int = 0,
    cell_y: int = 0,
) -> ReceiverFix:
    return sign_receiver_fix(_fix(seq, timestamp, odometer_m, cell_x, cell_y), _DEVICE_SEED)


def _tariff() -> TariffTable:
    return TariffTable(
        tariff_version=8,
        grid_w=2,
        cell_zones={0: 10, 1: 20, 2: 30, 3: 30},
        zone_rates_cents_per_m={10: 1, 20: 3, 30: 5},
    )


def test_position_valid_is_explicit_per_interval_and_strictly_boolean() -> None:
    fixes = [_fix(0, 100, 1_000), _fix(1, 110, 1_070)]

    with pytest.raises(ValueError, match="one position_valid flag per interval"):
        fee_for_period_v6(fixes, _tariff(), position_valid=[], r_max_cents_per_m=5)

    with pytest.raises(TypeError, match=r"position_valid\[0\] must be bool"):
        fee_for_period_v6(fixes, _tariff(), position_valid=[1], r_max_cents_per_m=5)  # type: ignore[list-item]


def test_normal_and_outage_charge_the_same_odometer_delta_at_different_rates() -> None:
    fixes = [_fix(0, 100, 1_000), _fix(1, 110, 1_070)]

    normal = fee_for_period_v6(fixes, _tariff(), position_valid=[True], r_max_cents_per_m=5)
    outage = fee_for_period_v6(fixes, _tariff(), position_valid=[False], r_max_cents_per_m=5)

    assert normal["total_distance_m"] == outage["total_distance_m"] == 70
    assert normal["total_fee_cents"] == 70 * 1
    assert outage["total_fee_cents"] == 70 * 5
    assert outage["fallback_distance_m"] == 70
    assert outage["fallback_intervals"] == 1


def test_v6_public_statement_binds_position_validity_via_interval_root() -> None:
    fixes = [
        _signed_fix(0, 1_777_593_600, 1_000),
        _signed_fix(1, 1_777_593_610, 1_070),
    ]
    normal = build_period_public_statement_v6(
        fixes=fixes,
        tariff=_tariff(),
        position_valid=[True],
        period_id="2026-05-v6-p01",
        month_id="2026-05",
        cadence_sec=300,
        tier_vmax_mps=33,
        max_dt_sec=600,
        r_max_cents_per_m=5,
        device_attestation_commitment=_DEVICE_DAC,
        tariff_tree_depth=2,
    )
    outage = build_period_public_statement_v6(
        fixes=fixes,
        tariff=_tariff(),
        position_valid=[False],
        period_id="2026-05-v6-p01",
        month_id="2026-05",
        cadence_sec=300,
        tier_vmax_mps=33,
        max_dt_sec=600,
        r_max_cents_per_m=5,
        device_attestation_commitment=_DEVICE_DAC,
        tariff_tree_depth=2,
    )

    assert normal["domain_sep"] == "tsip_settlement_public_v6"
    assert normal["policy_profile_commitment"] == "0"
    assert normal["total_fee_cents"] == 70
    assert outage["total_fee_cents"] == 350
    assert normal["interval_commitment_root"] != outage["interval_commitment_root"]
    assert "position_valid" not in normal


def test_verify_v6_submission_rejects_position_flag_tampering() -> None:
    fixes = [
        _signed_fix(0, 1_777_593_600, 1_000),
        _signed_fix(1, 1_777_593_610, 1_070),
    ]
    public = build_period_public_statement_v6(
        fixes=fixes,
        tariff=_tariff(),
        position_valid=[True],
        period_id="2026-05-v6-p01",
        month_id="2026-05",
        cadence_sec=300,
        tier_vmax_mps=33,
        max_dt_sec=600,
        r_max_cents_per_m=5,
        device_attestation_commitment=_DEVICE_DAC,
        tariff_tree_depth=2,
    )

    verified = verify_period_submission_v6(
        fixes=fixes,
        tariff=_tariff(),
        position_valid=[True],
        public_statement=public,
        public_key_bytes=_DEVICE_PUBLIC_KEY,
        cadence_sec=300,
        tier_vmax_mps=33,
        max_dt_sec=600,
        r_max_cents_per_m=5,
        tariff_tree_depth=2,
    )
    assert verified == public

    with pytest.raises(ValueError, match="public statement mismatch"):
        verify_period_submission_v6(
            fixes=fixes,
            tariff=_tariff(),
            position_valid=[False],
            public_statement=public,
            public_key_bytes=_DEVICE_PUBLIC_KEY,
            cadence_sec=300,
            tier_vmax_mps=33,
            max_dt_sec=600,
            r_max_cents_per_m=5,
            tariff_tree_depth=2,
        )


def test_v6_public_signal_order_includes_profile_commitment() -> None:
    assert PUBLIC_SIGNAL_COUNT_V6 == 22
    assert PUBLIC_SIGNAL_ORDER_V6[:4] == [
        "receiver_fix_root",
        "tariff_root",
        "interval_commitment_root",
        "policy_profile_commitment",
    ]


def test_v6_receiver_root_commits_each_fix_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    fixes = [_fix(i, 100 + i, 1_000 + i) for i in range(4)]
    original = settlement_v6.compute_fix_commitment_v6
    seen: list[int] = []

    def counting_commitment(fix: ReceiverFix, **kwargs: int) -> int:
        seen.append(fix.fix_seq)
        return original(fix, **kwargs)

    monkeypatch.setattr(settlement_v6, "compute_fix_commitment_v6", counting_commitment)
    root = settlement_v6.compute_receiver_fix_root_v6(fixes, dac_field=7, policy_profile_commitment=11)

    assert seen == [0, 1, 2, 3]
    assert root == settlement_v6.commitment_chain_root(
        [original(fix, dac_field=7, policy_profile_commitment=11) for fix in fixes]
    )


def test_v6_wrapper_and_prover_share_the_public_signal_order() -> None:
    wrapper = (
        ROOT_DIR / "experiments-heatmap" / "circuits" / "settlement_period_v6_k6.circom"
    ).read_text(encoding="utf-8")
    match = re.search(r"component\s+main\s*\{public\s*\[(.*?)\]\}\s*=", wrapper, flags=re.S)
    assert match is not None
    wrapper_order = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", match.group(1))

    assert wrapper_order == PUBLIC_SIGNAL_ORDER_V6
    assert "SettlementPeriodV6(25, 8, 6)" in wrapper


def test_real_circuit_receipt_matches_current_python_input_vector() -> None:
    receipt_dir = ROOT_DIR / "experiments" / "waybill_m1" / "v1" / "circuit_differential"
    receipt_path = receipt_dir / "receipt.json"
    profile = PolicyProfile.from_dict(
        json.loads((receipt_dir / "policy-profile-v6-k6.json").read_text(encoding="utf-8"))
    )
    validate_profile_local_artifacts(profile, base_dir=receipt_dir)
    receipt = validate_circuit_receipt(receipt_path)
    input_json, submission = build_circuit_input_v6(profile)
    expected = [input_json[name] for name in PUBLIC_SIGNAL_ORDER_V6]

    assert receipt["ok"] is True
    assert receipt["constraints"] == 240_258
    assert receipt["canonical_profile_bound"] is True
    assert int(receipt["policy_profile_commitment"]) == profile.commitment != 0
    assert submission["receiver_root_attestation"]["signature"]
    assert receipt["public_signal_count"] == PUBLIC_SIGNAL_COUNT_V6
    assert receipt["public_signal_order"] == PUBLIC_SIGNAL_ORDER_V6
    assert receipt["public_signals"] == receipt["python_reference_public_signals"] == expected
    circuit_dir = receipt_dir.parent / "circuit"
    artifact_paths = {
        "r1cs": circuit_dir / "settlement_period_v6_k6.r1cs",
        "wasm": circuit_dir / "settlement_period_v6_k6_js" / "settlement_period_v6_k6.wasm",
        "zkey": circuit_dir / "settlement_period_v6_k6_final.zkey",
        "verification_key": circuit_dir / "verification_key.json",
        "proof_json": receipt_dir / "proof.json",
        "public_json": receipt_dir / "public.json",
    }
    missing = [name for name, path in artifact_paths.items() if not path.is_file()]
    if missing:
        # Formal RG0 keeps large R1CS/WASM/zkey artifacts outside ordinary
        # Git. Their immutable hashes remain in the checked-in receipt and are
        # revalidated when the artifact bundle is mounted on a target host.
        assert set(missing) <= {"r1cs", "wasm", "zkey"}
        assert all(
            len(str(receipt["artifact_sha256"][name])) == 64 for name in missing
        )
        present = {
            name: sha256_file(path)
            for name, path in artifact_paths.items()
            if path.is_file()
        }
        assert present == {
            name: receipt["artifact_sha256"][name] for name in present
        }
    else:
        assert {
            name: sha256_file(path) for name, path in artifact_paths.items()
        } == receipt["artifact_sha256"]


def test_circuit_v6_uses_odometer_fallback_while_v5_baseline_stays_time_based() -> None:
    v5 = (
        ROOT_DIR / "experiments-heatmap" / "circuits" / "settlement_period_v5_base.circom"
    ).read_text(encoding="utf-8")
    v6 = (
        ROOT_DIR / "experiments-heatmap" / "circuits" / "settlement_period_v6_base.circom"
    ).read_text(encoding="utf-8")

    assert "fallback_distance_m[i] <== dt[i] * tier_vmax_mps" in v5
    assert "fallback_distance_m[i] <== odo_delta[i]" in v6
    assert "position_valid[i] * (position_valid[i] - 1) === 0" in v6
    assert "fallback_flag[i] <== 1 - position_valid[i]" in v6


def test_m1_runner_reports_all_hard_safety_gates() -> None:
    result = run_m1_checks(trials=100, seed=7)

    assert result["parking"]["v6_exact_zero"] is True
    assert result["withholding"]["no_benefit"] is True
    assert result["omission_reconciliation"]["no_undercharge"] is True
    assert result["integer_contract"]["max_product_within_uint96"] is True


def test_parking_outage_is_exactly_zero_even_for_a_long_checkpoint_gap() -> None:
    fixes = [_fix(0, 100, 10_000), _fix(1, 700, 10_000)]

    result = fee_for_period_v6(
        fixes,
        _tariff(),
        position_valid=[False],
        r_max_cents_per_m=5,
        max_dt_sec=600,
    )

    assert result["total_distance_m"] == 0
    assert result["fallback_distance_m"] == 0
    assert result["total_fee_cents"] == 0

    # V5 remains a separate time-based baseline and is intentionally unchanged.
    baseline = fee_for_interval_values(
        dt_sec=600,
        odo_delta_m=0,
        cell_idx=0,
        tariff=_tariff(),
        cadence_sec=300,
        tier_vmax_mps=33,
    )
    assert baseline["fee_cents"] == 600 * 33 * 5


def test_withholding_never_reduces_fee_property() -> None:
    rng = random.Random(20260713)
    tariff = _tariff()
    for _ in range(500):
        delta = rng.randrange(0, 1_000_000)
        cell_idx = rng.randrange(0, 4)
        normal = fee_for_interval_values_v6(
            odometer_start_m=123,
            odometer_end_m=123 + delta,
            cell_idx=cell_idx,
            tariff=tariff,
            position_valid=True,
            r_max_cents_per_m=5,
        )
        withheld = fee_for_interval_values_v6(
            odometer_start_m=123,
            odometer_end_m=123 + delta,
            cell_idx=cell_idx,
            tariff=tariff,
            position_valid=False,
            r_max_cents_per_m=5,
        )
        assert withheld["fee_cents"] >= normal["fee_cents"]
        assert withheld["fee_cents"] - normal["fee_cents"] == delta * (
            5 - int(normal["zone_rate_cents_per_m"])
        )


def test_rmax_must_be_the_tariff_maximum_and_rates_are_uint32() -> None:
    with pytest.raises(ValueError, match="r_max.*tariff maximum"):
        fee_for_interval_values_v6(
            odometer_start_m=0,
            odometer_end_m=1,
            cell_idx=0,
            tariff=_tariff(),
            position_valid=False,
            r_max_cents_per_m=4,
        )

    oversized_rate = TariffTable(
        tariff_version=8,
        grid_w=1,
        cell_zones={0: 10},
        zone_rates_cents_per_m={10: UINT32_MAX + 1},
    )
    with pytest.raises(OverflowError, match="tariff rate.*uint32"):
        fee_for_interval_values_v6(
            odometer_start_m=0,
            odometer_end_m=1,
            cell_idx=0,
            tariff=oversized_rate,
            position_valid=True,
            r_max_cents_per_m=UINT32_MAX,
        )


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (-1, 0, "odometer_start_m.*uint64"),
        (0, UINT64_MAX + 1, "odometer_end_m.*uint64"),
        (2, 1, "monotonic"),
    ],
)
def test_odometer_bounds_and_rollback_are_rejected(start: int, end: int, message: str) -> None:
    with pytest.raises((ValueError, OverflowError), match=message):
        fee_for_interval_values_v6(
            odometer_start_m=start,
            odometer_end_m=end,
            cell_idx=0,
            tariff=_tariff(),
            position_valid=True,
            r_max_cents_per_m=5,
        )


def test_maximum_interval_product_fits_uint96_without_field_wraparound() -> None:
    tariff = TariffTable(
        tariff_version=8,
        grid_w=1,
        cell_zones={0: 10},
        zone_rates_cents_per_m={10: UINT32_MAX},
    )

    result = fee_for_interval_values_v6(
        odometer_start_m=0,
        odometer_end_m=UINT64_MAX,
        cell_idx=0,
        tariff=tariff,
        position_valid=False,
        r_max_cents_per_m=UINT32_MAX,
    )

    assert result["fee_cents"] == UINT64_MAX * UINT32_MAX
    assert result["fee_cents"] <= UINT96_MAX


def test_period_fee_matches_integer_formula_property() -> None:
    rng = random.Random(0xC0FFEE)
    tariff = _tariff()
    for case in range(100):
        distances = [rng.randrange(0, 500) for _ in range(8)]
        flags = [bool(rng.randrange(0, 2)) for _ in distances]
        cells = [rng.randrange(0, 4) for _ in distances]
        readings = [1_000]
        for distance in distances:
            readings.append(readings[-1] + distance)
        fix_cells = [*cells, cells[-1]]
        fixes = [
            _fix(i, 10_000 + i * 10, readings[i], fix_cells[i] % 2, fix_cells[i] // 2)
            for i in range(len(readings))
        ]

        result = fee_for_period_v6(
            fixes,
            tariff,
            position_valid=flags,
            r_max_cents_per_m=5,
            tier_vmax_mps=None,
        )
        expected = sum(
            distance * (tariff.rate_for_zone(tariff.zone_for_cell(cell)) if valid else 5)
            for distance, valid, cell in zip(distances, flags, cells)
        )
        assert result["total_fee_cents"] == expected, f"case={case}"
        assert result["total_distance_m"] == sum(distances)


def test_month_close_reconciles_only_unaccounted_distance() -> None:
    result = reconcile_month_v6(
        monthly_odometer_start_m=0,
        monthly_odometer_end_m=2_000,
        accounted_distance_m=70,
        accepted_period_fee_cents=70,
        r_max_cents_per_m=5,
    )

    assert result == {
        "monthly_distance_m": 2_000,
        "accounted_distance_m": 70,
        "unaccounted_distance_m": 1_930,
        "reconciliation_fee_cents": 9_650,
        "accepted_period_fee_cents": 70,
        "total_month_bill_cents": 9_720,
    }


def test_month_close_rejects_excess_accounting_but_honors_named_tolerance() -> None:
    with pytest.raises(ValueError, match="accounted distance exceeds monthly odometer delta"):
        reconcile_month_v6(
            monthly_odometer_start_m=1_000,
            monthly_odometer_end_m=1_100,
            accounted_distance_m=102,
            accepted_period_fee_cents=100,
            r_max_cents_per_m=5,
            tolerance_m=1,
        )

    within_tolerance = reconcile_month_v6(
        monthly_odometer_start_m=1_000,
        monthly_odometer_end_m=1_100,
        accounted_distance_m=101,
        accepted_period_fee_cents=100,
        r_max_cents_per_m=5,
        tolerance_m=1,
    )
    assert within_tolerance["unaccounted_distance_m"] == 0
    assert within_tolerance["reconciliation_fee_cents"] == 0


def test_month_total_overflow_is_rejected() -> None:
    with pytest.raises(OverflowError, match="total_month_bill_cents.*uint96"):
        reconcile_month_v6(
            monthly_odometer_start_m=0,
            monthly_odometer_end_m=1,
            accounted_distance_m=0,
            accepted_period_fee_cents=UINT96_MAX,
            r_max_cents_per_m=1,
        )


def test_omitting_periods_cannot_lower_the_reconciled_month_bill_property() -> None:
    rng = random.Random(424242)
    for _ in range(250):
        distances = [rng.randrange(0, 10_000) for _ in range(12)]
        rates = [rng.randrange(0, 6) for _ in distances]
        full_bill = sum(distance * rate for distance, rate in zip(distances, rates))
        submitted = [bool(rng.randrange(0, 2)) for _ in distances]
        accounted = sum(distance for distance, keep in zip(distances, submitted) if keep)
        accepted_fee = sum(
            distance * rate
            for distance, rate, keep in zip(distances, rates, submitted)
            if keep
        )

        reconciled = reconcile_month_v6(
            monthly_odometer_start_m=0,
            monthly_odometer_end_m=sum(distances),
            accounted_distance_m=accounted,
            accepted_period_fee_cents=accepted_fee,
            r_max_cents_per_m=5,
        )

        assert reconciled["total_month_bill_cents"] >= full_bill
