from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.e3_certification import (
    MODEL_ID,
    RECEIPT_SCHEMA,
    ClaimedFix,
    E3Instance,
    E3Profile,
    Point,
    Rectangle,
    TariffCell,
    TrueFix,
    ViolationCode,
    bucket_center_coordinates,
    certify_instance,
    solve_center_feasible,
    solve_independent_relaxation,
    solve_rectangle_relaxation,
    solve_small_oracle,
    strict_check,
    truthful_claim,
    verify_projection_containment,
)
from script.run_m3_certified_e3 import (
    _nested_grid_incumbents,
    main as run_m3_main,
)


def _instance(*, dt_sec: int = 20, odometer_end_m: int = 10) -> E3Instance:
    """A two-fix case with one cheap displaced source cell.

    With dt=20 the cheap centre is feasible.  With dt=10 it is admitted by
    R_ind but cannot reach the second layer in R_rect.
    """

    cells = (
        TariffCell("low", Rectangle(-6, -1, -4, 1), 1),
        TariffCell("true-0", Rectangle(-1, -1, 1, 1), 10),
        TariffCell("true-1", Rectangle(9, -1, 11, 1), 10),
    )
    profile = E3Profile(
        cadence_sec=60,
        max_dt_sec=1_000,
        tier_vmax_mps=1,
        relay_radius_units=5,
        r_max_cents_per_m=10,
        coordinate_scale_per_m=1,
    )
    fixes = (
        TrueFix("dev", "period", 0, 0, 0, Point(0, 0), "true-0"),
        TrueFix("dev", "period", 1, dt_sec, odometer_end_m, Point(10, 0), "true-1"),
    )
    return E3Instance(
        instance_id=f"unit-dt-{dt_sec}-odo-{odometer_end_m}",
        dataset="unit",
        profile=profile,
        tariff_cells=cells,
        fixes=fixes,
        bucket_size_units=2,
    )


def _noncenter_optimum_instance() -> E3Instance:
    return E3Instance(
        instance_id="noncenter-optimum",
        dataset="unit",
        profile=E3Profile(
            cadence_sec=60,
            max_dt_sec=100,
            tier_vmax_mps=1,
            relay_radius_units=2,
            r_max_cents_per_m=10,
            coordinate_scale_per_m=1,
        ),
        tariff_cells=(
            TariffCell("low", Rectangle(-3, -1, -1, 1), 1),
            TariffCell("true-0", Rectangle(-1, -1, 1, 1), 10),
            TariffCell("true-1", Rectangle(9, -1, 11, 1), 10),
        ),
        fixes=(
            TrueFix("dev", "period", 0, 0, 0, Point(0, 0), "true-0"),
            TrueFix("dev", "period", 1, 10, 10, Point(10, 0), "true-1"),
        ),
        bucket_size_units=2,
    )


def _nested_grid_pair() -> tuple[E3Instance, E3Instance]:
    profile = E3Profile(
        cadence_sec=60,
        max_dt_sec=100,
        tier_vmax_mps=1,
        relay_radius_units=2,
        r_max_cents_per_m=10,
        coordinate_scale_per_m=1,
    )
    immutable = (
        ("dev", "nested", 0, 0, 0, Point(1, -1)),
        ("dev", "nested", 1, 12, 10, Point(11, -1)),
    )
    fine = E3Instance(
        instance_id="nested:fine",
        dataset="unit",
        profile=profile,
        tariff_cells=(
            TariffCell("fine-low", Rectangle(-2, -2, 0, 0), 1),
            TariffCell("fine-true-0", Rectangle(0, -2, 2, 0), 10),
            TariffCell("fine-true-1", Rectangle(10, -2, 12, 0), 10),
        ),
        fixes=tuple(
            TrueFix(*values, true_cell_id=f"fine-true-{index}")
            for index, values in enumerate(immutable)
        ),
        bucket_size_units=2,
    )
    coarse = E3Instance(
        instance_id="nested:coarse",
        dataset="unit",
        profile=profile,
        tariff_cells=(
            TariffCell("coarse-low", Rectangle(-4, -2, 0, 2), 1),
            TariffCell("coarse-true-0", Rectangle(0, -2, 4, 2), 10),
            TariffCell("coarse-true-1", Rectangle(8, -2, 12, 2), 10),
        ),
        fixes=tuple(
            TrueFix(*values, true_cell_id=f"coarse-true-{index}")
            for index, values in enumerate(immutable)
        ),
        bucket_size_units=4,
    )
    return fine, coarse


def test_certified_bounds_bracket_independent_small_oracle():
    instance = _instance(dt_sec=20)

    lower = solve_center_feasible(instance)
    oracle = solve_small_oracle(instance)
    upper = solve_rectangle_relaxation(instance)

    assert oracle.complete is True
    assert lower.underpayment_cents <= oracle.optimum_underpayment_cents <= upper.underpayment_cents
    assert lower.underpayment_cents == oracle.optimum_underpayment_cents == 90
    assert strict_check(instance, lower.claim).accepted is True

    receipt = certify_instance(instance, run_oracle=True)
    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["bindings"]["model_id"] == MODEL_ID
    assert receipt["LB_cents"] <= receipt["oracle"]["optimum_underpayment_cents"] <= receipt["UB_cents"]
    assert receipt["gap_cents"] == receipt["UB_cents"] - receipt["LB_cents"]
    assert isinstance(receipt["H_cents"], int)
    assert isinstance(receipt["LB_cents"], int)
    assert isinstance(receipt["UB_cents"], int)
    assert isinstance(receipt["gap_cents"], int)
    # The receipt is directly JSON serializable and contains no monetary float.
    json.dumps(receipt, allow_nan=False)


def test_projection_containment_and_rectangle_is_tighter_than_independent():
    instance = _instance(dt_sec=10)

    containment = verify_projection_containment(instance)
    rectangle = solve_rectangle_relaxation(instance)
    independent = solve_independent_relaxation(instance)

    assert containment.valid is True
    assert containment.center_points_checked > 0
    assert containment.center_edges_checked > 0
    assert rectangle.underpayment_cents <= independent.underpayment_cents
    assert rectangle.underpayment_cents == 0
    assert independent.underpayment_cents == 90


def test_small_oracle_is_exact_on_original_integer_points_not_center_only():
    instance = _noncenter_optimum_instance()

    center = solve_center_feasible(instance)
    oracle = solve_small_oracle(instance, max_paths=10_000)
    rectangle = solve_rectangle_relaxation(instance)

    assert center.underpayment_cents == 0
    assert oracle.complete is True
    assert oracle.to_dict()["domain"] == "F_continuous_integer"
    assert oracle.optimum_underpayment_cents == 90
    assert rectangle.underpayment_cents == 90
    assert center.underpayment_cents < oracle.optimum_underpayment_cents
    assert strict_check(instance, oracle.claim).accepted is True
    assert any(fix.claimed_point != instance.cell_map[fix.claimed_cell_id].rectangle.center for fix in oracle.claim.fixes)


def test_nested_fine_witness_lifts_to_coarse_without_moving_points():
    fine, coarse = _nested_grid_pair()
    fine_receipt = certify_instance(fine)
    center_only = solve_center_feasible(coarse)

    incumbents = _nested_grid_incumbents(
        target=coarse,
        completed=((fine, fine_receipt),),
    )
    receipt = certify_instance(coarse, feasible_incumbents=incumbents)

    assert center_only.underpayment_cents == 0
    assert len(incumbents) == 1
    fine_points = [
        item["claimed_point"]
        for item in fine_receipt["lower_bound"]["witness"]["fixes"]
    ]
    coarse_points = [
        item["claimed_point"]
        for item in receipt["lower_bound"]["witness"]["fixes"]
    ]
    assert coarse_points == fine_points
    assert receipt["LB_cents"] == receipt["UB_cents"] == 90
    assert receipt["lower_bound"]["checker"]["accepted"] is True
    assert receipt["lower_bound"]["selected_search_domain"] == "F_strict-feasible/v1"
    assert receipt["lower_bound"]["selected_source"].startswith("nested-grid-lift:")
    assert receipt["lower_bound"]["incumbent_selection"]["all_candidates_strictly_accepted"] is True


def test_strict_checker_reports_structured_binding_and_payload_mutations():
    instance = _instance(dt_sec=20)
    claim = solve_center_feasible(instance).claim
    assert claim is not None

    bad_header = replace(claim, tariff_hash="00" * 32)
    assert ViolationCode.TARIFF_HASH in {item.code for item in strict_check(instance, bad_header).violations}

    bad_identity_fix = replace(claim.fixes[0], device_id="other-device")
    bad_identity = replace(claim, fixes=(bad_identity_fix, *claim.fixes[1:]))
    assert ViolationCode.DEVICE_BINDING in {item.code for item in strict_check(instance, bad_identity).violations}

    bad_validity_fix = replace(claim.fixes[0], position_valid=False)
    bad_validity = replace(claim, fixes=(bad_validity_fix, *claim.fixes[1:]))
    assert ViolationCode.POSITION_VALID in {item.code for item in strict_check(instance, bad_validity).violations}

    bad_payload_fix = replace(claim.fixes[0], claimed_point=Point(100, 100))
    bad_payload = replace(claim, fixes=(bad_payload_fix, *claim.fixes[1:]))
    payload_codes = {item.code for item in strict_check(instance, bad_payload).violations}
    assert ViolationCode.PAYLOAD_CELL_BINDING in payload_codes
    assert ViolationCode.RADIUS in payload_codes

    bad_fee = replace(claim, fee_cents=claim.fee_cents + 1)
    assert ViolationCode.FEE_BINDING in {item.code for item in strict_check(instance, bad_fee).violations}

    bad_time_fix = replace(claim.fixes[1], auth_time_sec=2_000)
    bad_time = replace(claim, fixes=(claim.fixes[0], bad_time_fix))
    bad_time_codes = {item.code for item in strict_check(instance, bad_time).violations}
    assert ViolationCode.TIME_BINDING in bad_time_codes
    assert ViolationCode.MAX_DT in bad_time_codes

    bad_cadence_segment = replace(claim.segments[0], outage=not claim.segments[0].outage)
    bad_cadence = replace(claim, segments=(bad_cadence_segment,))
    assert ViolationCode.CADENCE_BINDING in {
        item.code for item in strict_check(instance, bad_cadence).violations
    }

    bad_objective = replace(claim, underpayment_cents=claim.underpayment_cents + 1)
    assert ViolationCode.OBJECTIVE_BINDING in {
        item.code for item in strict_check(instance, bad_objective).violations
    }


def test_old_rome_648_to_361_projection_is_rejected_without_bucket_tolerance():
    """Regression for the old Rome period ``rome:60:67-1-s1:p0``.

    The legacy bucket solver accepted a 648 m true odometer period projected to
    a 361 m claimed path because its checker expanded a bucket tolerance.  The
    frozen model binds every reading, so even a matching endpoint mutation is
    rejected as ODO_BINDING.
    """

    instance = _instance(dt_sec=648, odometer_end_m=648)
    instance = replace(instance, instance_id="rome:60:67-1-s1:p0")
    claim = truthful_claim(instance)
    projected_last = replace(claim.fixes[-1], odometer_m=361)
    legacy_projection = replace(claim, fixes=(*claim.fixes[:-1], projected_last))

    result = strict_check(instance, legacy_projection)

    assert result.accepted is False
    assert ViolationCode.ODO_BINDING in {item.code for item in result.violations}
    assert instance.fixes[-1].odometer_m - instance.fixes[0].odometer_m == 648
    assert legacy_projection.fixes[-1].odometer_m - legacy_projection.fixes[0].odometer_m == 361


def test_bucket_centres_are_not_nested_for_required_refinement_pairs():
    span = 200_000  # millimetres, so 25 m still has an integral centre
    centers_100 = set(bucket_center_coordinates(lower=0, upper=span, bucket_size=100_000))
    centers_50 = set(bucket_center_coordinates(lower=0, upper=span, bucket_size=50_000))
    centers_25 = set(bucket_center_coordinates(lower=0, upper=span, bucket_size=25_000))
    centers_10 = set(bucket_center_coordinates(lower=0, upper=span, bucket_size=10_000))

    assert not centers_100.issubset(centers_50)
    assert not centers_50.issubset(centers_100)
    assert not centers_25.issubset(centers_10)
    assert not centers_10.issubset(centers_25)


def test_claimed_fix_json_parser_defaults_position_valid_to_false():
    claim = truthful_claim(_instance())
    raw = claim.fixes[0].to_dict()
    raw.pop("position_valid")

    parsed = ClaimedFix.from_dict(raw)

    assert parsed.position_valid is False


def test_runner_emits_jsonl_and_summary_for_canonical_instance(tmp_path: Path):
    instance_path = tmp_path / "instance.json"
    output_dir = tmp_path / "out"
    instance_path.write_text(json.dumps(_instance().to_dict()), encoding="utf-8")

    exit_code = run_m3_main(
        [
            "--instances",
            str(instance_path),
            "--output-dir",
            str(output_dir),
            "--oracle-max-fixes",
            "5",
        ]
    )

    assert exit_code == 0
    receipts = [json.loads(line) for line in (output_dir / "bound_receipts.jsonl").read_text().splitlines()]
    summary = json.loads((output_dir / "summary.json").read_text())
    assert receipts[0]["status"] == "certified"
    assert receipts[0]["schema"] == RECEIPT_SCHEMA
    assert summary["attempted"] == 1
    legacy_review = summary["legacy_rome_review"]
    assert legacy_review["classification"] == "legacy_bucket_sensitivity_not_certified_bound"
    assert legacy_review["reported_legacy_p95_change"] == {
        "from": "0.464",
        "to": "0.295",
        "copied_into_certified_results": False,
    }
    assert legacy_review["distance_projection_regression"]["violation_code"] == "ODO_BINDING"
    assert (output_dir / "summary.csv").exists()


def test_timeout_receipt_retains_feasible_lb_and_safe_independent_ub():
    receipt = certify_instance(_instance(), timeout_sec=0)

    assert receipt["status"] == "certified"
    assert receipt["timeout"] is True
    assert receipt["upper_bound"]["relaxation_id"] == "R_ind/v1"
    assert receipt["LB_cents"] <= receipt["UB_cents"]
