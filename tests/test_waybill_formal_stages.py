from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from script import run_waybill_m2_circuit_matrix as m2
from script import prove_settlement_period_v6 as v6_prover
from common.settlement import ReceiverFix, TariffTable, receiver_attestation_sha256
from services.charger.app import ChargerSettings, create_app
from script.run_waybill_s2_formal_unit import _copy_artifacts
from script.run_waybill_s1_formal_unit import (
    _identity_cluster_id,
    _fallback_job,
    burst_outage_edges,
    cluster_bootstrap_summary,
)
from script.run_waybill_s4_formal_unit import (
    _auc,
    identity_cluster_bootstrap,
    _observation_fields,
    _period_observation,
    _sequence_rows,
    _split_identities,
)
from script.run_waybill_s5_formal_unit import (
    _build_corpus_input,
    _copy_main_artifacts,
    _request_plan,
)
from waybill_formal.core import read_json, write_json
from waybill_formal.core import FormalError
from waybill_formal.stage import finish_stage


def test_burst_mask_is_deterministic_and_has_the_frozen_share() -> None:
    first = burst_outage_edges(
        dataset="tdrive",
        period_id="p1",
        n_intervals=100,
        share=0.10,
        length_fixes=10,
        seed=17,
    )
    second = burst_outage_edges(
        dataset="tdrive",
        period_id="p1",
        n_intervals=100,
        share=0.10,
        length_fixes=10,
        seed=17,
    )

    assert first == second
    assert len(first) == 10
    assert all(0 <= edge < 100 for edge in first)


def test_s1_cluster_bootstrap_is_deterministic_and_cluster_scoped() -> None:
    rows = [
        {"cluster_id": "a", "metric": 1},
        {"cluster_id": "a", "metric": 3},
        {"cluster_id": "b", "metric": 9},
    ]
    first = cluster_bootstrap_summary(
        rows,
        metrics=("metric",),
        percentiles=(50,),
        replicates=200,
        seed=17,
    )
    second = cluster_bootstrap_summary(
        rows,
        metrics=("metric",),
        percentiles=(50,),
        replicates=200,
        seed=17,
    )

    assert first == second
    assert first["clusters"] == 2
    assert first["metrics"]["metric"]["p50"]["estimate"] == 3.0


def test_s1_identity_cluster_never_falls_back_to_period_id() -> None:
    assert _identity_cluster_id({"vehicle_id": "vehicle-1"}, period_id="p1") == "vehicle-1"
    with pytest.raises(FormalError, match="lacks the required"):
        _identity_cluster_id({}, period_id="p1")


def test_s2_stage_summary_reports_preregistered_p99_as_descriptive_order_statistic() -> None:
    trials = [
        {
            "status": "verified",
            "prove": {"elapsed_ms": float(index), "max_rss_bytes": index * 1000},
        }
        for index in range(1, 11)
    ]
    summary = m2.stage_summary(trials, "prove")
    assert summary["samples"] == 10
    assert summary["elapsed_ms_p95_nearest_rank"] == 10.0
    assert summary["elapsed_ms_p99_nearest_rank"] == 10.0


def test_s1_month_close_ablation_is_real_and_rejections_fail_closed(tmp_path: Path) -> None:
    periods = tmp_path / "tdrive-periods.jsonl"
    tariff = {
        "tariff_version": 8,
        "grid_w": 2,
        "cell_zones": {"0": 10, "1": 20},
        "zone_rates_cents_per_m": {"10": 1, "20": 5},
    }
    (tmp_path / "tariff_block.json").write_text(
        json.dumps({"tariff": tariff}) + "\n", encoding="utf-8"
    )
    fixes = [
        ReceiverFix(
            device_id="vehicle-1",
            period_id="period-1",
            fix_seq=index,
            auth_gnss_time=1000 + index * 60,
            cell_x=index,
            cell_y=0,
            osnma_status="authenticated",
            odometer_reading_m=1000 + index * 100,
            nonce=f"nonce-{index}",
        ).to_dict()
        for index in range(2)
    ]
    periods.write_text(
        json.dumps({"period_id": "period-1", "vehicle_id": "vehicle-1", "fixes": fixes})
        + "\n",
        encoding="utf-8",
    )
    attempt = tmp_path / "attempt-good"
    attempt.mkdir()
    summary = _fallback_job(
        parameters={"dataset": "tdrive", "scenario": "natural", "seed": 17},
        periods_path=periods,
        attempt_dir=attempt,
    )
    row = json.loads((attempt / "period-results.jsonl").read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert row["v6_without_month_close_fee_cents"] == 0
    assert row["v6_with_month_close_withholding_fee_cents"] == 500
    assert summary["bootstrap"]["replicates"] == 5000

    periods.write_text(
        periods.read_text(encoding="utf-8") + json.dumps({"period_id": "bad"}) + "\n",
        encoding="utf-8",
    )
    failed_attempt = tmp_path / "attempt-bad"
    failed_attempt.mkdir()
    failed = _fallback_job(
        parameters={"dataset": "tdrive", "scenario": "natural", "seed": 17},
        periods_path=periods,
        attempt_dir=failed_attempt,
    )
    assert failed["status"] == "failed"
    assert failed["rejected_periods"] == 1


def test_s4_split_is_identity_disjoint_and_auc_direction_is_correct() -> None:
    train, test = _split_identities([f"vehicle-{index}" for index in range(20)], 31)

    assert train
    assert test
    assert train.isdisjoint(test)
    assert train | test == {f"vehicle-{index}" for index in range(20)}
    assert _auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert _auc([0.1], [0.9]) == 0.0


def test_s4_identity_cluster_bootstrap_is_deterministic() -> None:
    rows = [
        {
            "true_identity": identity,
            "correct_top1": correct,
            "correct_top5": True,
            "query_auc": auc,
        }
        for identity, correct, auc in (
            ("vehicle-a", True, 1.0),
            ("vehicle-a", False, 0.5),
            ("vehicle-b", False, 0.0),
            ("vehicle-b", False, 0.5),
        )
    ]
    first = identity_cluster_bootstrap(rows, replicates=200, seed=31)
    second = identity_cluster_bootstrap(rows, replicates=200, seed=31)

    assert first == second
    assert first["clusters"] == 2
    assert first["metrics"]["top1_accuracy"]["macro_estimate"] == 0.25
    assert first["metrics"]["top5_accuracy"]["macro_estimate"] == 1.0


def test_s4_bucketed_views_exclude_exact_fields_and_windows_do_not_overlap(
    tmp_path: Path,
) -> None:
    assert "total_fee_cents" in _observation_fields("O1")
    assert "total_distance_m" in _observation_fields("O1")
    assert "total_fee_cents" not in _observation_fields("O2")
    assert "total_distance_m" not in _observation_fields("O3")
    tariff = TariffTable(
        tariff_version=8,
        grid_w=10,
        cell_zones={index: 10 for index in range(10)},
        zone_rates_cents_per_m={10: 1},
    )
    records = []
    for period in range(7):
        fixes = [
            ReceiverFix(
                device_id="vehicle-1",
                period_id=f"period-{period}",
                fix_seq=index,
                auth_gnss_time=1000 + period * 1000 + index * 60,
                cell_x=index,
                cell_y=0,
                osnma_status="authenticated",
                odometer_reading_m=period * 100 + index * 100,
                nonce=f"nonce-{period}-{index}",
            ).to_dict()
            for index in range(2)
        ]
        records.append(
            {"vehicle_id": "vehicle-1", "period_id": f"period-{period}", "fixes": fixes}
        )
    periods_path = tmp_path / "periods.jsonl"
    periods_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    observation = _period_observation(records[0], tariff, view="O2", opening=0.0, seed=17)
    assert "amount_bucket_500c" in observation
    assert "distance_bucket_100m" in observation
    assert "total_fee_cents" not in observation
    assert "total_distance_m" not in observation

    sequences = _sequence_rows(
        periods_path,
        tariff,
        view="O2",
        opening=0.0,
        horizon=2,
        seed=17,
        temporal_gap_periods=1,
    )
    assert [row["window_start_index"] for row in sequences] == [0, 3, 5]
    gallery_periods = set(sequences[0]["period_ids"])
    assert all(not gallery_periods.intersection(row["period_ids"]) for row in sequences[1:])


def test_s5_workload_composition_is_exact() -> None:
    bundles = [
        {
            "bundle_id": f"bundle-{index}",
            "proof": {"pi_a": [str(index)]},
            "public_signals": [str(index), "2"],
            "endpoint_payload": {
                "period_id": f"period-{index}",
                "proof": {"pi_a": [str(index)]},
                "public_signals": [str(index), "2"],
            },
        }
        for index in range(100)
    ]
    plan = _request_plan("valid-90-tampered-5-replay-5", bundles, seed=73)

    assert len(plan) == 100
    assert Counter(kind for kind, _payload in plan) == {
        "valid": 90,
        "tampered": 5,
        "replay": 5,
    }


def test_s5_corpus_inputs_are_distinct_profile_bound_periods(tmp_path: Path) -> None:
    vkey = m2.config_paths(tmp_path, 14, 25)["vkey"]
    vkey.parent.mkdir(parents=True)
    vkey.write_text("{}\n", encoding="utf-8")
    profile = m2.create_policy_profile_for_config(
        output_dir=tmp_path,
        depth=14,
        fixes_count=25,
        verification_key_path=vkey,
    )

    first_input, first_submission = _build_corpus_input(
        fixes_count=25,
        corpus_index=0,
        profile=profile,
    )
    second_input, second_submission = _build_corpus_input(
        fixes_count=25,
        corpus_index=1,
        profile=profile,
    )

    first_public = first_submission["public_statement"]
    second_public = second_submission["public_statement"]
    assert first_public["period_id"] != second_public["period_id"]
    assert first_public["receiver_fix_root"] != second_public["receiver_fix_root"]
    assert first_input["policy_profile_commitment"] == str(profile.commitment)
    assert second_input["policy_profile_commitment"] == str(profile.commitment)


def test_s2_and_s5_copied_artifacts_finish_as_regular_hashed_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    s2_target = tmp_path / "s2-attempt" / "m2-concurrency"
    name = m2.wrapper_name(14, 25)
    source_paths = m2.config_paths(source, 14, 25)
    for key in ("wasm", "zkey", "vkey"):
        source_paths[key].parent.mkdir(parents=True, exist_ok=True)
        source_paths[key].write_bytes(f"{key}-bytes".encode())
    write_json(source / "inputs" / f"{name}.json", {"input": 1})
    write_json(source / "receipts" / "proof" / f"{name}.json", {"status": "verified"})

    input_path, proof_receipt = _copy_artifacts(source, s2_target, 25)
    assert proof_receipt["status"] == "verified"
    assert input_path.is_file() and not input_path.is_symlink()
    copied_s2 = m2.config_paths(s2_target, 14, 25)
    assert all(
        copied_s2[key].is_file() and not copied_s2[key].is_symlink()
        for key in ("wasm", "zkey", "vkey")
    )
    s2_job = {
        "job_id": "s2-copy",
        "stage": "S2",
        "kind": "concurrency",
    }
    finish_stage(
        job=s2_job,
        attempt_dir=tmp_path / "s2-attempt",
        payload={"status": "passed"},
    )
    assert read_json(tmp_path / "s2-attempt" / "stage-result.json")["status"] == "passed"

    s5_attempt = tmp_path / "s5-attempt"
    copied = _copy_main_artifacts(source, s5_attempt / "proof-corpus" / "m2", 25)
    assert all(copied[key].is_file() and not copied[key].is_symlink() for key in ("wasm", "zkey", "vkey"))
    s5_job = {"job_id": "s5-copy", "stage": "S5", "kind": "corpus"}
    finish_stage(job=s5_job, attempt_dir=s5_attempt, payload={"status": "passed"})
    assert read_json(s5_attempt / "stage-result.json")["status"] == "passed"


def test_s5_formal_corpus_attestations_form_an_anchorable_device_chain(
    tmp_path: Path,
) -> None:
    vkey = m2.config_paths(tmp_path / "profile", 14, 25)["vkey"]
    vkey.parent.mkdir(parents=True)
    vkey.write_text("{}\n", encoding="utf-8")
    profile = m2.create_policy_profile_for_config(
        output_dir=tmp_path / "profile",
        depth=14,
        fixes_count=25,
        verification_key_path=vkey,
    )
    _first_input, first = _build_corpus_input(
        fixes_count=25,
        corpus_index=0,
        profile=profile,
        log_epoch=1,
    )
    first_attestation = first["receiver_root_attestation"]
    _second_input, second = _build_corpus_input(
        fixes_count=25,
        corpus_index=1,
        profile=profile,
        log_epoch=2,
        previous_attestation_sha256=receiver_attestation_sha256(first_attestation),
    )
    second_attestation = second["receiver_root_attestation"]
    assert first_attestation["log_epoch"] == 1
    assert second_attestation["log_epoch"] == 2
    assert second_attestation["previous_attestation_sha256"] == receiver_attestation_sha256(
        first_attestation
    )

    application = create_app(
        ChargerSettings(
            database_url=f"sqlite+pysqlite:///{tmp_path / 'charger.sqlite'}",
            charger_domain=str(first_attestation["charger_domain"]),
            admin_token="s5-test-admin-token",
            token_pepper="s5-test-token-pepper",
            test_mode=True,
            enable_reset=True,
            allow_sqlite_backend_for_tests=True,
        )
    )
    with TestClient(application) as client:
        registered = client.post(
            "/settlement/devices/register",
            json={
                "device_id": first_attestation["device_id"],
                "public_key_hex": v6_prover._DEVICE_PUBLIC_KEY_BYTES.hex(),
                "jurisdiction_id": profile.jurisdiction_id,
            },
        )
        assert registered.status_code == 200, registered.text
        for attestation in (first_attestation, second_attestation):
            response = client.post(
                "/settlement/receiver-chain/anchor",
                json={"root_attestation": attestation},
            )
            assert response.status_code == 200, response.text
