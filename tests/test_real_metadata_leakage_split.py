import sys
from pathlib import Path

import numpy as np


MODULE_DIR = (
    Path(__file__).parents[1]
    / "TSIP_heatmap_version/runtime/experiments-heatmap"
)
sys.path.insert(0, str(MODULE_DIR))

from run_real_metadata_leakage import build_session_pairs, split_user_ids  # noqa: E402


def test_session_split_is_user_disjoint_and_has_declared_size() -> None:
    train_users, test_users = split_user_ids(1000, seed=24, test_size=0.30)

    assert train_users.size == 700
    assert test_users.size == 300
    assert set(train_users).isdisjoint(test_users)
    assert set(np.concatenate([train_users, test_users])) == set(range(1000))


def test_session_pairs_are_balanced_and_deterministic_within_partition() -> None:
    segments = [
        (np.full(3, uid, dtype=float), np.full(3, uid + 0.5, dtype=float))
        for uid in range(1000)
    ]
    train_users, test_users = split_user_ids(1000, seed=24, test_size=0.30)

    train_x, train_y = build_session_pairs(segments, train_users, seed=1708)
    test_x, test_y = build_session_pairs(segments, test_users, seed=2708)
    repeat_x, repeat_y = build_session_pairs(segments, test_users, seed=2708)

    assert train_x.shape == (1400, 9)
    assert test_x.shape == (600, 9)
    assert np.bincount(train_y).tolist() == [700, 700]
    assert np.bincount(test_y).tolist() == [300, 300]
    np.testing.assert_array_equal(test_x, repeat_x)
    np.testing.assert_array_equal(test_y, repeat_y)
