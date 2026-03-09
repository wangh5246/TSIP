from conftest import get_json, post_json


def test_dp_budget_gate_and_reset(a_base_url: str):
    status = get_json(f"{a_base_url}/status_latest")
    assert status.get("ok") is True
    rid = int(status["round_id"])

    reset = post_json(f"{a_base_url}/privacy_budget_reset?round_id={rid}")
    assert reset.get("ok") is True

    first = get_json(f"{a_base_url}/dp/latest")
    assert first.get("error") is None
    assert first.get("round_id") == rid
    assert first.get("cells_kept_post", 0) >= 0

    second = get_json(f"{a_base_url}/dp/latest")
    assert second.get("ok") is False
    assert second.get("error") == "privacy budget exhausted"

    reset2 = post_json(f"{a_base_url}/privacy_budget_reset?round_id={rid}")
    assert reset2.get("ok") is True

    third = get_json(f"{a_base_url}/dp/latest")
    assert third.get("error") is None
