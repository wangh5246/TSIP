from conftest import post_json


def test_reconstruct_latest_auto_expected(a_base_url: str):
    data = post_json(f"{a_base_url}/reconstruct_latest?expected=0")
    assert data.get("ok") is True
    assert isinstance(data.get("expected"), int)
    assert data["expected"] >= 0
    assert data["expected"] <= min(int(data["received_A"]), int(data["received_R"]))
