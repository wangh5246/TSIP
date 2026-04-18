from pathlib import Path
import sys

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from client.sim import client as client_mod
import common.tsip as tsip_mod
from common.tsip import compute_location_commitment, tsip_window_id
from services.shuffler import app as shuffler


def _build_linear_trajectory(n: int, start_t: int = 1000) -> list[tuple[float, float, int]]:
    out = []
    for i in range(n):
        out.append((1000.0 + 7.0 * i, 2000.0 + 5.0 * i, int(start_t + 60 * i)))
    return out


def _loc_commitment(user_id: str, p: tuple[float, float, int]) -> str:
    x, y, t = p
    return compute_location_commitment(
        user_id=user_id,
        x=int(round(x)),
        y=int(round(y)),
        timestamp=int(t),
        window_id=tsip_window_id(int(t), client_mod.TSIP_WINDOW_SEC),
        prev_commitment="",
    )


@pytest.fixture(autouse=True)
def _reset_shuffler_tsip_state(monkeypatch):
    monkeypatch.setattr(
        tsip_mod,
        "_poseidon2_hash",
        lambda a, b: (int(a) * 1315423911 + int(b) * 2654435761 + 97) % tsip_mod.SNARK_FIELD,
    )
    shuffler.tsip_state_by_user.clear()
    yield
    shuffler.tsip_state_by_user.clear()


def test_recover_tsip_state_from_server_snapshot_success():
    user_id = "geolife_u_recovery"
    traj = _build_linear_trajectory(24)
    accepted_count = 10
    current_i = accepted_count - 1
    k = int(client_mod.TSIP_ADWC_WINDOW_K)

    history = []
    for idx in range(max(0, current_i - k), current_i + 1):
        history.append({"idx": idx, "loc_commitment": _loc_commitment(user_id, traj[idx])})

    recovery = {
        "ok": True,
        "exists": True,
        "user_id": user_id,
        "accepted_count": accepted_count,
        "loc_commitment": _loc_commitment(user_id, traj[current_i]),
        "chain_commitment": "a" * 64,
        "adwc_history": history,
    }

    state, err = client_mod._recover_tsip_state_from_server(user_id, recovery, traj)
    assert err == ""
    assert state is not None
    assert int(state["accepted_count"]) == accepted_count
    assert int(state["cursor"]) == current_i
    assert int(state["x"]) == int(round(traj[current_i][0]))
    assert int(state["y"]) == int(round(traj[current_i][1]))
    assert len(state["adwc_history"]) == len(history)
    assert int(state["adwc_history"][0]["idx"]) == history[0]["idx"]
    assert "user_secret" in state and len(str(state["user_secret"])) == 64


def test_recover_tsip_state_fails_when_remote_commitment_not_in_trajectory():
    user_id = "geolife_u_recovery_fail"
    traj = _build_linear_trajectory(12)
    recovery = {
        "ok": True,
        "exists": True,
        "user_id": user_id,
        "accepted_count": 6,
        "loc_commitment": "f" * 64,
        "chain_commitment": "b" * 64,
        "adwc_history": [{"idx": 5, "loc_commitment": "f" * 64}],
    }
    state, err = client_mod._recover_tsip_state_from_server(user_id, recovery, traj)
    assert state is None
    assert "cannot map" in err


def test_shuffler_tsip_state_endpoint_returns_commitment_only_history():
    uid = "u_commitment_only"
    shuffler.tsip_state_by_user.clear()
    shuffler.tsip_state_by_user[uid] = {
        "loc_commitment": "1" * 64,
        "chain_commitment": "2" * 64,
        "timestamp": 1111,
        "window_id": 18,
        "accepted_count": 2,
        "adwc_history": [
            {"idx": 0, "loc_commitment": "0" * 64, "x": 10, "y": 20},
            {"idx": 1, "loc_commitment": "1" * 64, "x": 11, "y": 21},
        ],
    }

    out = shuffler.tsip_state(uid)
    assert out["ok"] is True
    assert out["exists"] is True
    assert len(out["adwc_history"]) == 2
    for item in out["adwc_history"]:
        assert "idx" in item and "loc_commitment" in item
        assert "x" not in item and "y" not in item
