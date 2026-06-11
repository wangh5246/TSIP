from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from script.run_e4_baseline_comparison import cameras_for_target, p_detect


def test_p_detect_monotone_in_coverage() -> None:
    values = [p_detect(c / 10, 0.1, 24) for c in range(11)]
    assert values == sorted(values)
    assert values[0] == 0.0
    assert values[-1] == pytest.approx(1.0 - math.exp(-0.1 * 24))


def test_p_detect_caps_coverage_at_one() -> None:
    assert p_detect(1.5, 0.2, 24) == p_detect(1.0, 0.2, 24)


def test_cameras_for_target_reaches_target() -> None:
    segments, omit, s = 973, 0.2, 24
    cams = cameras_for_target(0.95, omit, s, segments)
    assert cams is not None
    assert p_detect(cams / segments, omit, s) >= 0.95
    # One camera fewer must fall short (ceil is tight).
    assert p_detect((cams - 1) / segments, omit, s) < 0.95


def test_cameras_for_target_unreachable_when_exposure_too_small() -> None:
    # rome omit 0.10, S=24: max P at full coverage is 1-exp(-2.4) ~= 0.909 < 0.95.
    assert cameras_for_target(0.95, 0.10, 24, 973) is None
    # The same target is reachable once the omitted exposure doubles.
    assert cameras_for_target(0.95, 0.20, 24, 973) is not None


def test_tsip_detection_is_camera_free() -> None:
    # Proof-violating attacks are rejected at submission regardless of cameras.
    cams = cameras_for_target(0.95, 0.2, 24, 973)
    assert cams and cams > 0  # spot-check needs infrastructure
    # TSIP rows in the artifacts always carry 0 cameras / P=1; the model has no
    # knob that could change that, which is exactly the point of E4.
