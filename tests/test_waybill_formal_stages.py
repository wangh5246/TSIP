from __future__ import annotations

from collections import Counter
from pathlib import Path

from script import run_waybill_m2_circuit_matrix as m2
from script.run_waybill_s1_formal_unit import burst_outage_edges
from script.run_waybill_s4_formal_unit import _auc, _split_identities
from script.run_waybill_s5_formal_unit import _build_corpus_input, _request_plan


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


def test_s4_split_is_identity_disjoint_and_auc_direction_is_correct() -> None:
    train, test = _split_identities([f"vehicle-{index}" for index in range(20)], 31)

    assert train
    assert test
    assert train.isdisjoint(test)
    assert train | test == {f"vehicle-{index}" for index in range(20)}
    assert _auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert _auc([0.1], [0.9]) == 0.0


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
