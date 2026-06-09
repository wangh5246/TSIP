from __future__ import annotations

import csv
from collections import Counter, defaultdict
import io
import json
import math
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol

from common.eval_harness import HarnessParams, compute_bill
from common.settlement import ReceiverFix, TariffTable


EARTH_RADIUS_M = 6_371_000.0
ROME_LINE = re.compile(r"^([^;]+);([^;]+);POINT\(([-+0-9.eE]+) ([-+0-9.eE]+)\)$")
REBASE_ANCHOR = 1_777_593_600
CELL_SIZE_M = 100
TARIFF_BLOCK_W = 16
TARIFF_CELLS_CAPACITY = TARIFF_BLOCK_W * TARIFF_BLOCK_W
TRIP_GAP_SEC = 1_800
MAX_DT_SEC = 600
N_PERIOD_FIXES = 25
PERIOD_MAX_SEC = 14_400
DEFAULT_OUTAGE_BRIDGE_MAX_ODO_M = 200

LEGAL_CADENCES: dict[str, tuple[int, ...]] = {
    "tdrive": (300,),
    "geolife": (60, 120, 300),
    "porto": (60, 120, 300),
    "rome": (60, 120, 300),
}
CITY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "beijing": (39.4, 41.1, 115.7, 117.4),
    "porto": (40.8, 41.5, -8.9, -8.3),
    "rome": (41.5, 42.2, 12.0, 13.0),
}


@dataclass(frozen=True)
class RawPoint:
    vehicle_id: str
    timestamp: int
    lat: float
    lon: float

    @property
    def device_id(self) -> str:
        return self.vehicle_id

    @property
    def t_unix(self) -> int:
        return self.timestamp


@dataclass(frozen=True)
class TariffBlock:
    origin_lat: float
    origin_lon: float
    global_cell_x_min: int
    global_cell_y_min: int
    width: int = TARIFF_BLOCK_W
    cell_size_m: int = CELL_SIZE_M

    @property
    def cells_capacity(self) -> int:
        return int(self.width) * int(self.width)

    def contains_global(self, global_cell_x: int, global_cell_y: int) -> bool:
        return (
            self.global_cell_x_min <= int(global_cell_x) < self.global_cell_x_min + self.width
            and self.global_cell_y_min <= int(global_cell_y) < self.global_cell_y_min + self.width
        )

    def local_cell(self, global_cell_x: int, global_cell_y: int) -> tuple[int, int, int]:
        cell_x = int(global_cell_x) - int(self.global_cell_x_min)
        cell_y = int(global_cell_y) - int(self.global_cell_y_min)
        if not (0 <= cell_x < self.width and 0 <= cell_y < self.width):
            raise ValueError("global cell is outside tariff block")
        return cell_x, cell_y, cell_y * self.width + cell_x

    def to_dict(self) -> dict[str, int | float]:
        return {
            "origin_lat": float(self.origin_lat),
            "origin_lon": float(self.origin_lon),
            "global_cell_x_min": int(self.global_cell_x_min),
            "global_cell_y_min": int(self.global_cell_y_min),
            "width": int(self.width),
            "cell_size_m": int(self.cell_size_m),
        }


@dataclass(frozen=True)
class RejectRecord:
    dataset: str
    cadence_sec: int
    device_id: str
    trip_id: str
    stage: str
    reason: str
    count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatchedPoint:
    timestamp: int
    lat: float
    lon: float
    cumulative_distance_m: float


@dataclass(frozen=True)
class PreparedTrip:
    dataset: str
    vehicle_id: str
    trip_id: str
    matcher: str
    origin_lat: float
    origin_lon: float
    odometer_distance_m: int
    honest_bill_cents: int
    fixes: list[ReceiverFix]

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "vehicle_id": self.vehicle_id,
            "trip_id": self.trip_id,
            "matcher": self.matcher,
            "origin_lat": self.origin_lat,
            "origin_lon": self.origin_lon,
            "odometer_distance_m": self.odometer_distance_m,
            "honest_bill_cents": self.honest_bill_cents,
            "fixes": [asdict(fix) for fix in self.fixes],
        }


class MapMatcher(Protocol):
    name: str

    def match(self, points: list[RawPoint]) -> list[MatchedPoint]: ...


class IdentityMatcher:
    name = "identity"

    def match(self, points: list[RawPoint]) -> list[MatchedPoint]:
        if not points:
            return []
        out = [MatchedPoint(points[0].timestamp, points[0].lat, points[0].lon, 0.0)]
        distance = 0.0
        for prev, curr in zip(points, points[1:]):
            distance += haversine_m(prev.lat, prev.lon, curr.lat, curr.lon)
            out.append(MatchedPoint(curr.timestamp, curr.lat, curr.lon, distance))
        return out


class ExternalMapMatcher:
    """Adapter slot for OSRM/FMM integration without coupling the pipeline."""

    def __init__(self, name: str, match_fn):
        self.name = str(name)
        self._match_fn = match_fn

    def match(self, points: list[RawPoint]) -> list[MatchedPoint]:
        return list(self._match_fn(points))


def iter_tdrive_trips(root: Path, *, gap_sec: int = 120) -> Iterator[tuple[str, list[RawPoint]]]:
    for path in sorted(root.glob("*.txt"), key=lambda p: int(p.stem)):
        points: list[RawPoint] = []
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 4:
                    continue
                try:
                    points.append(
                        RawPoint(
                            vehicle_id=parts[0].strip(),
                            timestamp=_parse_datetime(parts[1].strip()),
                            lon=float(parts[2]),
                            lat=float(parts[3]),
                        )
                    )
                except ValueError:
                    continue
        yield from _yield_segmented(path.stem, points, gap_sec=gap_sec)


def iter_tdrive_raw_points(root: Path) -> Iterator[RawPoint]:
    for path in sorted(root.glob("*.txt"), key=lambda p: int(p.stem)):
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 4:
                    continue
                try:
                    yield RawPoint(
                        vehicle_id=parts[0].strip(),
                        timestamp=_parse_datetime(parts[1].strip()),
                        lon=float(parts[2]),
                        lat=float(parts[3]),
                    )
                except ValueError:
                    continue


def iter_rome_trips(path: Path, *, gap_sec: int = 120) -> Iterator[tuple[str, list[RawPoint]]]:
    active: dict[str, list[RawPoint]] = {}
    segment_idx: dict[str, int] = {}
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            match = ROME_LINE.match(line.strip())
            if not match:
                continue
            vehicle, ts, lat, lon = match.groups()
            point = RawPoint(vehicle, _parse_datetime(ts), float(lat), float(lon))
            segment = active.setdefault(vehicle, [])
            if segment and point.timestamp - segment[-1].timestamp > gap_sec:
                if len(segment) >= 2:
                    idx = segment_idx.get(vehicle, 0)
                    yield f"{vehicle}-{idx}", segment
                    segment_idx[vehicle] = idx + 1
                segment = []
                active[vehicle] = segment
            segment.append(point)
    for vehicle, segment in sorted(active.items()):
        if len(segment) >= 2:
            yield f"{vehicle}-{segment_idx.get(vehicle, 0)}", segment


def iter_rome_raw_points(path: Path) -> Iterator[RawPoint]:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            match = ROME_LINE.match(line.strip())
            if not match:
                continue
            vehicle, ts, lat, lon = match.groups()
            try:
                yield RawPoint(vehicle, _parse_datetime(ts), float(lat), float(lon))
            except ValueError:
                continue


def iter_porto_trips(path: Path) -> Iterator[tuple[str, list[RawPoint]]]:
    with _open_csv_text(path) as f:
        for row in csv.DictReader(f):
            try:
                coords = json.loads(row["POLYLINE"])
                start = int(row["TIMESTAMP"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if len(coords) < 2:
                continue
            vehicle = str(row.get("TAXI_ID") or row.get("TRIP_ID") or "porto")
            points = [
                RawPoint(vehicle, start + i * 15, float(lon_lat[1]), float(lon_lat[0]))
                for i, lon_lat in enumerate(coords)
                if isinstance(lon_lat, list) and len(lon_lat) >= 2
            ]
            if len(points) >= 2:
                yield str(row.get("TRIP_ID") or f"{vehicle}-{start}"), points


def iter_porto_raw_points(path: Path) -> Iterator[RawPoint]:
    with _open_csv_text(path) as f:
        for row in csv.DictReader(f):
            try:
                coords = json.loads(row["POLYLINE"])
                start = int(row["TIMESTAMP"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            vehicle = str(row.get("TAXI_ID") or row.get("TRIP_ID") or "porto")
            for i, lon_lat in enumerate(coords):
                if not (isinstance(lon_lat, list) and len(lon_lat) >= 2):
                    continue
                try:
                    yield RawPoint(vehicle, start + i * 15, float(lon_lat[1]), float(lon_lat[0]))
                except (TypeError, ValueError):
                    continue


def _open_csv_text(path: Path):
    if path.suffix.lower() != ".zip":
        return path.open("r", encoding="utf-8", newline="")
    archive = zipfile.ZipFile(path)
    names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if not names:
        archive.close()
        raise FileNotFoundError(f"no csv member in {path}")
    raw = archive.open(names[0], "r")
    text = io.TextIOWrapper(raw, encoding="utf-8", newline="")

    class ZipText:
        def __enter__(self):
            return text

        def __exit__(self, exc_type, exc, tb):
            text.close()
            raw.close()
            archive.close()

    return ZipText()


def iter_geolife_driving_trips(root: Path, *, gap_sec: int = 120) -> Iterator[tuple[str, list[RawPoint]]]:
    for user_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        labels = _read_geolife_driving_labels(user_dir / "labels.txt")
        if not labels:
            continue
        traj_dir = user_dir / "Trajectory"
        for path in sorted(traj_dir.glob("*.plt")):
            points: list[RawPoint] = []
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f):
                    if idx < 6:
                        continue
                    parts = line.strip().split(",")
                    if len(parts) < 7:
                        continue
                    try:
                        ts = _parse_datetime(f"{parts[5]} {parts[6]}")
                        if _inside_any(ts, labels):
                            points.append(RawPoint(user_dir.name, ts, float(parts[0]), float(parts[1])))
                    except ValueError:
                        continue
            yield from _yield_segmented(f"{user_dir.name}-{path.stem}", points, gap_sec=gap_sec)


def iter_geolife_driving_raw_points(root: Path) -> Iterator[RawPoint]:
    for user_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        labels = _read_geolife_driving_labels(user_dir / "labels.txt")
        if not labels:
            continue
        traj_dir = user_dir / "Trajectory"
        for path in sorted(traj_dir.glob("*.plt")):
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f):
                    if idx < 6:
                        continue
                    parts = line.strip().split(",")
                    if len(parts) < 7:
                        continue
                    try:
                        ts = _parse_datetime(f"{parts[5]} {parts[6]}")
                        if _inside_any(ts, labels):
                            yield RawPoint(user_dir.name, ts, float(parts[0]), float(parts[1]))
                    except ValueError:
                        continue


def prepare_trip(
    dataset: str,
    trip_id: str,
    points: list[RawPoint],
    *,
    matcher: MapMatcher,
    tariff: TariffTable,
    params: HarnessParams,
    cadence_sec: int,
    origin_lat: float,
    origin_lon: float,
) -> PreparedTrip | None:
    matched = matcher.match(points)
    sampled = resample_matched_points(matched, cadence_sec=cadence_sec)
    if len(sampled) < 2:
        return None
    fixes: list[ReceiverFix] = []
    for seq, point in enumerate(sampled):
        x_m, y_m = project_xy_m(point.lat, point.lon, origin_lat, origin_lon)
        half_grid_m = tariff.grid_w * params.cell_size_m / 2
        cell_x = int(math.floor((x_m + half_grid_m) / params.cell_size_m))
        cell_y = int(math.floor((y_m + half_grid_m) / params.cell_size_m))
        if not (0 <= cell_x < tariff.grid_w and 0 <= cell_y < tariff.grid_w):
            return None
        fixes.append(
            ReceiverFix(
                device_id=f"{dataset}:{points[0].vehicle_id}",
                period_id=f"{dataset}:{trip_id}",
                fix_seq=seq,
                auth_gnss_time=int(point.timestamp),
                cell_x=cell_x,
                cell_y=cell_y,
                osnma_status="authenticated",
                odometer_reading_m=int(round(point.cumulative_distance_m)),
                nonce=f"{dataset}-{trip_id}-{seq}",
            )
        )
    bill = compute_bill(fixes, tariff, params)
    return PreparedTrip(
        dataset=dataset,
        vehicle_id=points[0].vehicle_id,
        trip_id=trip_id,
        matcher=matcher.name,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        odometer_distance_m=int(fixes[-1].odometer_reading_m - fixes[0].odometer_reading_m),
        honest_bill_cents=int(bill["total_fee_cents"]),
        fixes=fixes,
    )


def resample_matched_points(points: list[MatchedPoint], *, cadence_sec: int) -> list[MatchedPoint]:
    if len(points) < 2:
        return points
    if cadence_sec <= 0:
        raise ValueError("cadence_sec must be positive")
    out: list[MatchedPoint] = []
    target = int(points[0].timestamp)
    end = int(points[-1].timestamp)
    idx = 0
    while target <= end:
        while idx + 1 < len(points) and points[idx + 1].timestamp < target:
            idx += 1
        if idx + 1 >= len(points):
            break
        out.append(_interpolate(points[idx], points[idx + 1], target))
        target += int(cadence_sec)
    if not out or out[-1].timestamp != points[-1].timestamp:
        out.append(points[-1])
    return out


def write_jsonl(path: Path, trips: Iterable[PreparedTrip]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as out:
        for trip in trips:
            out.write(json.dumps(trip.to_dict(), ensure_ascii=True) + "\n")
            count += 1
    return count


def clean_raw_points(
    dataset: str,
    points: Iterable[RawPoint],
    *,
    city_bbox: tuple[float, float, float, float] | None = None,
) -> tuple[list[dict[str, Any]], list[RejectRecord]]:
    rows: list[dict[str, Any]] = []
    rejects: Counter[tuple[str, str, str]] = Counter()
    seen: set[tuple[str, int]] = set()
    for point in points:
        device_id = str(point.device_id)
        if not _valid_latlon(point.lat, point.lon):
            rejects[(device_id, "", "invalid_latlon")] += 1
            continue
        if city_bbox is not None and not _inside_bbox(point.lat, point.lon, city_bbox):
            rejects[(device_id, "", "outside_city_bbox")] += 1
            continue
        key = (device_id, int(point.t_unix))
        if key in seen:
            rejects[(device_id, "", "duplicate_timestamp")] += 1
            continue
        seen.add(key)
        rows.append(
            {
                "dataset": dataset,
                "device_id": device_id,
                "t_unix": int(point.t_unix),
                "lat": float(point.lat),
                "lon": float(point.lon),
            }
        )
    rows.sort(key=lambda row: (row["device_id"], row["t_unix"]))
    return rows, [
        RejectRecord(dataset, 0, device, trip, "stage0", reason, count)
        for (device, trip, reason), count in sorted(rejects.items())
    ]


def rebase_points_to_2026(rows: list[dict[str, Any]], *, anchor: int = REBASE_ANCHOR, device_spacing_sec: int = 300) -> list[dict[str, Any]]:
    first_by_device: dict[str, int] = {}
    for row in rows:
        first_by_device.setdefault(str(row["device_id"]), int(row["t_unix"]))
    offset_by_device = {
        device: int(anchor) + idx * int(device_spacing_sec) - first_t
        for idx, (device, first_t) in enumerate(sorted(first_by_device.items()))
    }
    out: list[dict[str, Any]] = []
    for row in rows:
        rebased = dict(row)
        rebased["t_unix_original"] = int(row["t_unix"])
        rebased["t_unix"] = int(row["t_unix"]) + offset_by_device[str(row["device_id"])]
        out.append(rebased)
    out.sort(key=lambda row: (row["device_id"], row["t_unix"]))
    return out


def segment_native_trips(
    dataset: str,
    rows: list[dict[str, Any]],
    *,
    gap_sec: int = TRIP_GAP_SEC,
    min_points: int = 2,
) -> tuple[list[dict[str, Any]], list[RejectRecord]]:
    out: list[dict[str, Any]] = []
    rejects: list[RejectRecord] = []
    by_device: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_device[str(row["device_id"])].append(row)
    for device_id, device_rows in sorted(by_device.items()):
        trip_idx = 0
        segment: list[dict[str, Any]] = []
        for row in device_rows:
            if segment and int(row["t_unix"]) - int(segment[-1]["t_unix"]) > int(gap_sec):
                _flush_native_segment(dataset, device_id, trip_idx, segment, out, rejects, min_points)
                trip_idx += 1
                segment = []
            segment.append(row)
        _flush_native_segment(dataset, device_id, trip_idx, segment, out, rejects, min_points)
    return out, rejects


def choose_density_peak_block(
    rows: list[dict[str, Any]],
    *,
    origin_lat: float,
    origin_lon: float,
    width: int = TARIFF_BLOCK_W,
    cell_size_m: int = CELL_SIZE_M,
    moving_only: bool = False,
) -> TariffBlock:
    visits: set[tuple[str, int, int]] = set()
    placement_rows = [
        row
        for row in rows
        if not moving_only or int(row.get("native_step_distance_m", 1)) > 0
    ]
    if not placement_rows:
        placement_rows = rows
    for row in placement_rows:
        x_m, y_m = project_xy_m(float(row["lat"]), float(row["lon"]), origin_lat, origin_lon)
        gx = math.floor(x_m / int(cell_size_m))
        gy = math.floor(y_m / int(cell_size_m))
        visits.add((str(row["device_id"]), int(gx), int(gy)))
    if not visits:
        return TariffBlock(origin_lat, origin_lon, 0, 0, width=width, cell_size_m=cell_size_m)
    cell_counts: Counter[tuple[int, int]] = Counter((gx, gy) for _device, gx, gy in visits)
    window_scores: Counter[tuple[int, int]] = Counter()
    for (gx, gy), count in cell_counts.items():
        for dx in range(width):
            for dy in range(width):
                window_scores[(gx - dx, gy - dy)] += int(count)
    best = min(
        window_scores,
        key=lambda xy: (-window_scores[xy], xy[1], xy[0]),
    )
    return TariffBlock(origin_lat, origin_lon, best[0], best[1], width=width, cell_size_m=cell_size_m)


def build_local_tariff_table(block: TariffBlock, geometry, *, circuit_grid_w: int = 100) -> TariffTable:
    cell_zones: dict[int, int] = {}
    zone_rates = {int(zone.zone_id): int(zone.rate_cents_per_m) for zone in geometry.zones}
    zone_rates[int(geometry.default_zone_id)] = int(geometry.default_rate_cents_per_m)
    for cell_y in range(block.width):
        for cell_x in range(block.width):
            global_x = block.global_cell_x_min + cell_x
            global_y = block.global_cell_y_min + cell_y
            lat, lon = global_cell_center_latlon(
                global_x,
                global_y,
                origin_lat=block.origin_lat,
                origin_lon=block.origin_lon,
                cell_size_m=block.cell_size_m,
            )
            cell_zones[cell_y * int(circuit_grid_w) + cell_x] = int(geometry.zone_at(lat, lon))
    return TariffTable(
        tariff_version=int(geometry.to_table().tariff_version),
        grid_w=int(circuit_grid_w),
        cell_zones=cell_zones,
        zone_rates_cents_per_m=zone_rates,
    )


def build_resampled_fixes(
    dataset: str,
    native_rows: list[dict[str, Any]],
    *,
    cadence_sec: int,
    block: TariffBlock,
    tariff: TariffTable,
    tier_vmax_mps: int = 33,
    max_dt_sec: int = MAX_DT_SEC,
    outage_bridge_max_odo_m: int = DEFAULT_OUTAGE_BRIDGE_MAX_ODO_M,
) -> tuple[list[dict[str, Any]], list[RejectRecord]]:
    if int(cadence_sec) not in LEGAL_CADENCES.get(dataset, ()):
        return [], [RejectRecord(dataset, int(cadence_sec), "", "", "stage3", "unsupported_cadence", 1)]
    selected: list[dict[str, Any]] = []
    rejects: Counter[tuple[str, str, str, str]] = Counter()
    by_trip: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in native_rows:
        by_trip[(str(row["device_id"]), str(row["trip_id"]))].append(row)
    for (device_id, trip_id), trip_rows in sorted(by_trip.items()):
        sampled = select_real_points_by_cadence(trip_rows, cadence_sec=cadence_sec)
        if len(sampled) < 2:
            rejects[(device_id, trip_id, "stage3", "too_few_points")] += 1
            continue
        prev_kept: dict[str, Any] | None = None
        segment_seq = 0
        local_seq = 0
        for row in sampled:
            x_m, y_m = project_xy_m(float(row["lat"]), float(row["lon"]), block.origin_lat, block.origin_lon)
            global_cell_x = math.floor(x_m / block.cell_size_m)
            global_cell_y = math.floor(y_m / block.cell_size_m)
            if not block.contains_global(global_cell_x, global_cell_y):
                rejects[(device_id, trip_id, "stage4", "outside_tariff_region")] += 1
                prev_kept = None
                segment_seq += 1
                local_seq = 0
                continue
            cell_x, cell_y, _leaf_offset = block.local_cell(global_cell_x, global_cell_y)
            cell_idx = tariff.cell_index(cell_x, cell_y)
            zone_id = tariff.zone_for_cell(cell_idx)
            fix = {
                **row,
                "cadence_sec": int(cadence_sec),
                "x_m": float(x_m),
                "y_m": float(y_m),
                "global_cell_x": int(global_cell_x),
                "global_cell_y": int(global_cell_y),
                "cell_x": int(cell_x),
                "cell_y": int(cell_y),
                "cell_idx": int(cell_idx),
                "in_tariff_region": True,
                "zone_id": int(zone_id),
                "rate_cents_per_m": int(tariff.rate_for_zone(zone_id)),
                "tariff_segment_id": f"{trip_id}-s{segment_seq}",
                "fix_seq_in_segment": int(local_seq),
                "outage_candidate": False,
                "period_break_before": False,
            }
            if prev_kept is not None:
                dt = int(fix["t_unix"]) - int(prev_kept["t_unix"])
                odo_delta = int(fix["odometer_reading_m"]) - int(prev_kept["odometer_reading_m"])
                if dt <= 0 or dt > int(max_dt_sec) or odo_delta < 0 or odo_delta > dt * int(tier_vmax_mps):
                    reason = "max_dt_exceeded" if dt > int(max_dt_sec) else "odometer_speed_exceeded"
                    rejects[(device_id, trip_id, "stage6", reason)] += 1
                    segment_seq += 1
                    local_seq = 0
                    fix["tariff_segment_id"] = f"{trip_id}-s{segment_seq}"
                    fix["fix_seq_in_segment"] = 0
                    fix["period_break_before"] = True
                elif dt > int(cadence_sec):
                    if odo_delta > int(outage_bridge_max_odo_m):
                        rejects[(device_id, trip_id, "stage6", "geographic_outage_bridge")] += 1
                        segment_seq += 1
                        local_seq = 0
                        fix["tariff_segment_id"] = f"{trip_id}-s{segment_seq}"
                        fix["fix_seq_in_segment"] = 0
                        fix["period_break_before"] = True
                    else:
                        fix["outage_candidate"] = True
            selected.append(fix)
            prev_kept = fix
            local_seq = int(fix["fix_seq_in_segment"]) + 1
    return selected, [
        RejectRecord(dataset, int(cadence_sec), device, trip, stage, reason, count)
        for (device, trip, stage, reason), count in sorted(rejects.items())
    ]


def build_period_records(
    dataset: str,
    fixes_rows: list[dict[str, Any]],
    *,
    cadence_sec: int,
    tariff: TariffTable,
) -> tuple[list[dict[str, Any]], list[RejectRecord]]:
    periods: list[dict[str, Any]] = []
    rejects: list[RejectRecord] = []
    by_segment: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in fixes_rows:
        by_segment[(str(row["device_id"]), str(row["trip_id"]), str(row["tariff_segment_id"]))].append(row)
    for (device_id, trip_id, segment_id), rows in sorted(by_segment.items()):
        rows.sort(key=lambda row: int(row["t_unix"]))
        full_count = len(rows) // N_PERIOD_FIXES
        for period_idx in range(full_count):
            chunk = rows[period_idx * N_PERIOD_FIXES : (period_idx + 1) * N_PERIOD_FIXES]
            if int(chunk[-1]["t_unix"]) - int(chunk[0]["t_unix"]) > PERIOD_MAX_SEC:
                rejects.append(RejectRecord(dataset, cadence_sec, device_id, trip_id, "stage6", "period_span_exceeded", 1))
                continue
            if int(chunk[-1]["odometer_reading_m"]) - int(chunk[0]["odometer_reading_m"]) <= 0:
                rejects.append(RejectRecord(dataset, cadence_sec, device_id, trip_id, "stage6", "zero_odometer_distance", 1))
                continue
            period_id = f"{dataset}:{cadence_sec}:{segment_id}:p{period_idx}"
            receiver_fixes: list[dict[str, Any]] = []
            n_outage = 0
            max_dt = 0
            for seq, row in enumerate(chunk):
                if seq > 0:
                    dt = int(row["t_unix"]) - int(chunk[seq - 1]["t_unix"])
                    max_dt = max(max_dt, dt)
                    if dt > int(cadence_sec):
                        n_outage += 1
                fix = ReceiverFix(
                    device_id=f"{dataset}:{device_id}",
                    period_id=period_id,
                    fix_seq=seq,
                    auth_gnss_time=int(row["t_unix"]),
                    cell_x=int(row["cell_x"]),
                    cell_y=int(row["cell_y"]),
                    osnma_status="authenticated",
                    odometer_reading_m=int(row["odometer_reading_m"]),
                    nonce=f"{dataset}-{cadence_sec}-{segment_id}-{period_idx}-{seq}",
                    receiver_sig="",
                ).to_dict()
                fix.update(
                    {
                        "x_m": float(row["x_m"]),
                        "y_m": float(row["y_m"]),
                        "cell_idx": int(row["cell_idx"]),
                        "zone_id": int(row["zone_id"]),
                        "rate_cents_per_m": int(row["rate_cents_per_m"]),
                        "global_cell_x": int(row["global_cell_x"]),
                        "global_cell_y": int(row["global_cell_y"]),
                    }
                )
                receiver_fixes.append(fix)
            periods.append(
                {
                    "dataset": dataset,
                    "cadence_sec": int(cadence_sec),
                    "device_id": device_id,
                    "trip_id": trip_id,
                    "tariff_segment_id": segment_id,
                    "period_id": period_id,
                    "period_start_time": int(chunk[0]["t_unix"]),
                    "period_end_time": int(chunk[-1]["t_unix"]),
                    "period_span_sec": int(chunk[-1]["t_unix"]) - int(chunk[0]["t_unix"]),
                    "month_id": _month_id_from_unix(int(chunk[0]["t_unix"])),
                    "n_fixes": N_PERIOD_FIXES,
                    "n_intervals": N_PERIOD_FIXES - 1,
                    "n_outage_intervals": int(n_outage),
                    "max_intra_period_dt": int(max_dt),
                    "tariff_version": int(tariff.tariff_version),
                    "tariff_grid_w": int(tariff.grid_w),
                    "fixes": receiver_fixes,
                }
            )
        remainder = len(rows) - full_count * N_PERIOD_FIXES
        if remainder:
            rejects.append(RejectRecord(dataset, cadence_sec, device_id, trip_id, "stage6", "period_less_than_25_fixes", remainder))
    return periods, rejects


def receiver_fixes_from_period(period: dict[str, Any]) -> list[ReceiverFix]:
    return [ReceiverFix.from_dict(row) for row in period["fixes"]]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    dlat, dlon = lat2_r - lat1_r, lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def project_xy_m(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    x = math.radians(lon - lon0) * math.cos(math.radians((lat + lat0) / 2)) * EARTH_RADIUS_M
    y = math.radians(lat - lat0) * EARTH_RADIUS_M
    return x, y


def global_cell_center_latlon(
    global_cell_x: int,
    global_cell_y: int,
    *,
    origin_lat: float,
    origin_lon: float,
    cell_size_m: int = CELL_SIZE_M,
) -> tuple[float, float]:
    east = (int(global_cell_x) + 0.5) * int(cell_size_m)
    north = (int(global_cell_y) + 0.5) * int(cell_size_m)
    lat = float(origin_lat) + math.degrees(north / EARTH_RADIUS_M)
    lon = float(origin_lon) + math.degrees(east / (EARTH_RADIUS_M * math.cos(math.radians(float(origin_lat)))))
    return lat, lon


def select_real_points_by_cadence(rows: list[dict[str, Any]], *, cadence_sec: int) -> list[dict[str, Any]]:
    if int(cadence_sec) <= 0:
        raise ValueError("cadence_sec must be positive")
    if not rows:
        return []
    ordered = sorted(rows, key=lambda row: int(row["t_unix"]))
    first_t = int(ordered[0]["t_unix"])
    by_bucket: dict[int, dict[str, Any]] = {}
    for row in ordered:
        bucket = int((int(row["t_unix"]) - first_t) // int(cadence_sec))
        boundary = first_t + bucket * int(cadence_sec)
        current = by_bucket.get(bucket)
        if current is None or (
            abs(int(row["t_unix"]) - boundary),
            int(row["t_unix"]),
        ) < (
            abs(int(current["t_unix"]) - boundary),
            int(current["t_unix"]),
        ):
            by_bucket[bucket] = row
    return [dict(by_bucket[bucket]) for bucket in sorted(by_bucket)]


def _yield_segmented(prefix: str, points: list[RawPoint], *, gap_sec: int) -> Iterator[tuple[str, list[RawPoint]]]:
    points = sorted(points, key=lambda p: p.timestamp)
    segment: list[RawPoint] = []
    seg_idx = 0
    for point in points:
        if segment and point.timestamp - segment[-1].timestamp > gap_sec:
            if len(segment) >= 2:
                yield f"{prefix}-{seg_idx}", segment
            seg_idx += 1
            segment = []
        segment.append(point)
    if len(segment) >= 2:
        yield f"{prefix}-{seg_idx}", segment


def _flush_native_segment(
    dataset: str,
    device_id: str,
    trip_idx: int,
    segment: list[dict[str, Any]],
    out: list[dict[str, Any]],
    rejects: list[RejectRecord],
    min_points: int,
) -> None:
    if not segment:
        return
    trip_id = f"{device_id}-{trip_idx}"
    if len(segment) < int(min_points):
        rejects.append(RejectRecord(dataset, 0, device_id, trip_id, "stage2", "too_few_points", len(segment)))
        return
    odometer = 0.0
    prev: dict[str, Any] | None = None
    for seq, row in enumerate(segment):
        step_distance = 0.0
        if prev is not None:
            step_distance = haversine_m(float(prev["lat"]), float(prev["lon"]), float(row["lat"]), float(row["lon"]))
            odometer += step_distance
        out.append(
            {
                **row,
                "trip_id": trip_id,
                "trip_seq": int(seq),
                "gap_prev_sec": None if prev is None else int(row["t_unix"]) - int(prev["t_unix"]),
                "native_outage_candidate": False if prev is None else int(row["t_unix"]) - int(prev["t_unix"]) > MAX_DT_SEC,
                "native_step_distance_m": int(round(step_distance)),
                "odometer_reading_m": int(round(odometer)),
                "odometer_delta_from_trip_start_m": int(round(odometer)),
            }
        )
        prev = row


def _valid_latlon(lat: float, lon: float) -> bool:
    return math.isfinite(float(lat)) and math.isfinite(float(lon)) and -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180


def _inside_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    lat_min, lat_max, lon_min, lon_max = bbox
    return float(lat_min) <= float(lat) <= float(lat_max) and float(lon_min) <= float(lon) <= float(lon_max)


def _month_id_from_unix(t_unix: int) -> int:
    dt = datetime.fromtimestamp(int(t_unix), tz=timezone.utc)
    return int(dt.year * 100 + dt.month)


def _read_geolife_driving_labels(path: Path) -> list[tuple[int, int]]:
    if not path.exists():
        return []
    out: list[tuple[int, int]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        next(f, None)
        for line in f:
            parts = line.rstrip().split("\t")
            if len(parts) >= 3 and parts[2].strip().lower() in {"car", "taxi", "driving"}:
                out.append((_parse_datetime(parts[0]), _parse_datetime(parts[1])))
    return out


def _inside_any(timestamp: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= timestamp <= end for start, end in ranges)


def _interpolate(a: MatchedPoint, b: MatchedPoint, timestamp: int) -> MatchedPoint:
    if timestamp <= a.timestamp:
        return MatchedPoint(timestamp, a.lat, a.lon, a.cumulative_distance_m)
    if timestamp >= b.timestamp:
        return MatchedPoint(timestamp, b.lat, b.lon, b.cumulative_distance_m)
    ratio = (timestamp - a.timestamp) / (b.timestamp - a.timestamp)
    return MatchedPoint(
        timestamp=timestamp,
        lat=a.lat + (b.lat - a.lat) * ratio,
        lon=a.lon + (b.lon - a.lon) * ratio,
        cumulative_distance_m=a.cumulative_distance_m + (b.cumulative_distance_m - a.cumulative_distance_m) * ratio,
    )


def _parse_datetime(value: str) -> int:
    cleaned = value.strip()
    try:
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return int(datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                continue
    raise ValueError(f"unsupported datetime: {value}")
