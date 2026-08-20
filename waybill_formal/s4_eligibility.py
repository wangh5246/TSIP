"""Shared S4 eligibility logic for identity-disjoint linkability attacks."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


def identity_for_period(raw: Mapping[str, Any]) -> str:
    """Return the original vehicle/user identity or fail closed."""

    identity = str(raw.get("device_id") or raw.get("vehicle_id") or "")
    if not identity:
        raise ValueError("S4 period lacks original vehicle/user identity")
    return identity


def period_sort_key(raw: Mapping[str, Any]) -> tuple[int, str]:
    fixes = raw.get("fixes")
    if not isinstance(fixes, list) or not fixes or not isinstance(fixes[0], Mapping):
        raise ValueError("S4 period lacks a first authenticated fix")
    return (
        int(fixes[0]["auth_gnss_time"]),
        str(raw.get("period_id") or raw.get("trip_id") or ""),
    )


def group_periods_by_identity(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group and canonically order input periods by their original identity."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in records:
        grouped[identity_for_period(raw)].append(dict(raw))
    for rows in grouped.values():
        rows.sort(key=period_sort_key)
    return dict(grouped)


def window_start_indices(
    period_count: int, *, horizon: int, temporal_gap_periods: int
) -> tuple[int, ...]:
    """Return the frozen gallery/query window starts for one identity."""

    if horizon < 1:
        raise ValueError("S4 horizon must be positive")
    if temporal_gap_periods < 1:
        raise ValueError("S4 temporal gap must be at least one period")
    starts = [0]
    starts.extend(
        range(
            horizon + temporal_gap_periods,
            period_count - horizon + 1,
            horizon,
        )
    )
    return tuple(starts)


def eligibility_summary(
    records: Iterable[Mapping[str, Any]],
    *,
    horizon: int,
    temporal_gap_periods: int,
    minimum_sequence_identities: int,
) -> dict[str, int | bool]:
    """Summarize whether a dataset/horizon supports the frozen S4 split."""

    if minimum_sequence_identities < 4:
        raise ValueError("S4 requires at least four sequence identities")
    grouped = group_periods_by_identity(records)
    sequence_counts = {
        identity: len(
            window_start_indices(
                len(rows),
                horizon=horizon,
                temporal_gap_periods=temporal_gap_periods,
            )
        )
        for identity, rows in grouped.items()
    }
    eligible_counts = [count for count in sequence_counts.values() if count >= 2]
    eligible_identity_count = len(eligible_counts)
    return {
        "original_identity_count": len(grouped),
        "sequence_eligible_identity_count": eligible_identity_count,
        "sequence_count": sum(eligible_counts),
        "minimum_sequence_identities": int(minimum_sequence_identities),
        "eligible": eligible_identity_count >= int(minimum_sequence_identities),
    }
