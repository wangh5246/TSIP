from conftest import get_json, post_json


def test_secure_reconstruct_latest_and_status(d_base_url: str):
    recon = post_json(f"{d_base_url}/secure/reconstruct_latest?expected=0")
    assert recon.get("ok") is True
    rid = int(recon["round_id"])
    assert int(recon.get("cells_in_final_map", 0)) > 0

    status = get_json(f"{d_base_url}/secure/status_latest")
    assert status.get("ok") is True
    assert int(status.get("round_id")) == rid
    assert int(status.get("cells_in_final_map", 0)) > 0
