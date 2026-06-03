from __future__ import annotations

import json
import math
from dataclasses import dataclass
from numbers import Integral
from pathlib import Path
from typing import Callable, Protocol

from common.settlement import ReceiverFix, TariffTable


OSM_DIR = Path("dataset/osm")
OSM_EXTRACTS: dict[str, dict[str, str]] = {
    "beijing": {
        "path": str(OSM_DIR / "beijing.osm.pbf"),
        "source": "BBBike bbox export",
        "url": "https://extract.bbbike.org/",
        "bbox": "115.7,39.4,117.4,41.1",
    },
    "porto": {
        "path": str(OSM_DIR / "portugal-latest.osm.pbf"),
        "source": "Geofabrik Portugal extract",
        "url": "https://download.geofabrik.de/europe/portugal-latest.osm.pbf",
    },
    "rome": {
        "path": str(OSM_DIR / "centro-latest.osm.pbf"),
        "source": "Geofabrik Centro extract (includes Lazio/Rome)",
        "url": "https://download.geofabrik.de/europe/italy/centro-latest.osm.pbf",
    },
}


@dataclass(frozen=True)
class CircleZone:
    zone_id: int
    center_lat: float
    center_lon: float
    radius_m: float
    rate_cents_per_m: int

    def contains(self, lat: float, lon: float) -> bool:
        return _haversine_m(lat, lon, self.center_lat, self.center_lon) <= self.radius_m


@dataclass(frozen=True)
class PolygonZone:
    zone_id: int
    rings: tuple[tuple[tuple[float, float], ...], ...]
    rate_cents_per_m: int

    def contains(self, lat: float, lon: float) -> bool:
        if not self.rings or not _point_in_ring(lat, lon, self.rings[0]):
            return False
        return not any(_point_in_ring(lat, lon, hole) for hole in self.rings[1:])


class Zone(Protocol):
    zone_id: int
    rate_cents_per_m: int

    def contains(self, lat: float, lon: float) -> bool: ...


@dataclass(frozen=True)
class TariffGeometry:
    city: str
    granularity: str
    origin_lat: float
    origin_lon: float
    grid_w: int
    cell_size_m: int
    zones: tuple[Zone, ...]
    default_zone_id: int
    default_rate_cents_per_m: int

    def to_table(self) -> TariffTable:
        cell_zones: dict[int, int] = {}
        zone_rates = {zone.zone_id: zone.rate_cents_per_m for zone in self.zones}
        zone_rates[self.default_zone_id] = self.default_rate_cents_per_m
        for y in range(self.grid_w):
            for x in range(self.grid_w):
                lat, lon = _cell_center_latlon(self, x, y)
                cell_zones[y * self.grid_w + x] = self.zone_at(lat, lon)
        return TariffTable(
            tariff_version=_tariff_version(self.city, self.granularity),
            grid_w=self.grid_w,
            cell_zones=cell_zones,
            zone_rates_cents_per_m=zone_rates,
        )

    def zone_at(self, lat: float, lon: float) -> int:
        for zone in self.zones:
            if zone.contains(lat, lon):
                return zone.zone_id
        return self.default_zone_id


def tariff_at_granularity(
    city: str,
    granularity: str,
    *,
    grid_w: int = 100,
    cell_size_m: int = 100,
    boundary_buffer_m: float = 0.0,
) -> TariffGeometry:
    city = city.lower()
    granularity = granularity.lower()
    if granularity not in {"coarse", "medium", "fine"}:
        raise ValueError("granularity must be coarse, medium, or fine")
    if city == "beijing":
        rings = {
            "coarse": [(5_000, 1, 5)],
            "medium": [(5_000, 1, 5), (10_000, 2, 3)],
            "fine": [(5_000, 1, 6), (10_000, 2, 5), (15_000, 3, 4), (20_000, 4, 3), (30_000, 5, 2)],
        }[granularity]
        return _geometry(city, granularity, 39.9042, 116.4074, rings, grid_w, cell_size_m, boundary_buffer_m)
    if city == "rome":
        rings = {"coarse": [(3_000, 1, 5)], "medium": [(3_000, 1, 5), (7_000, 2, 3)], "fine": [(3_000, 1, 6), (7_000, 2, 4), (14_000, 3, 2)]}[granularity]
        return _geometry(city, granularity, 41.9028, 12.4964, rings, grid_w, cell_size_m, boundary_buffer_m)
    if city == "porto":
        rings = {"coarse": [(3_000, 1, 5)], "medium": [(3_000, 1, 5), (7_000, 2, 3)], "fine": [(2_000, 1, 6), (5_000, 2, 4), (10_000, 3, 2)]}[granularity]
        return _geometry(city, granularity, 41.1579, -8.6291, rings, grid_w, cell_size_m, boundary_buffer_m)
    raise ValueError(f"unsupported city: {city}")


def tariff_from_geojson(
    path: Path,
    *,
    city: str,
    granularity: str,
    origin_lat: float,
    origin_lon: float,
    grid_w: int = 100,
    cell_size_m: int = 100,
    default_zone_id: int = 99,
    default_rate_cents_per_m: int = 1,
) -> TariffGeometry:
    """Load ordered tariff polygons from a GeoJSON FeatureCollection.

    Each feature requires integer ``zone_id`` and ``rate_cents_per_m``
    properties. Put inner/high-priority polygons before outer polygons.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    zones: list[PolygonZone] = []
    for feature in payload.get("features", []):
        props = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        kind = geometry.get("type")
        coordinates = geometry.get("coordinates", [])
        polygons = [coordinates] if kind == "Polygon" else coordinates if kind == "MultiPolygon" else []
        for polygon in polygons:
            rings = tuple(
                tuple((float(lat), float(lon)) for lon, lat in ring)
                for ring in polygon
            )
            zones.append(PolygonZone(int(props["zone_id"]), rings, int(props["rate_cents_per_m"])))
    if not zones:
        raise ValueError(f"no Polygon/MultiPolygon tariff zones in {path}")
    return TariffGeometry(
        city=city,
        granularity=granularity,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        grid_w=grid_w,
        cell_size_m=cell_size_m,
        zones=tuple(zones),
        default_zone_id=default_zone_id,
        default_rate_cents_per_m=default_rate_cents_per_m,
    )


def build_env_labeler(
    osm_pbf: Path,
    geometry: TariffGeometry,
    *,
    tunnel_buffer_m: float = 30.0,
) -> Callable[[ReceiverFix], str]:
    """Return an OSM-backed labeler once pyrosm is installed.

    The matcher remains independent: this loader is for lightweight vector
    metadata such as tunnel=yes. A caller should enrich fixes with projected
    locations before using the resulting labeler in a full E2 run.
    """

    if not osm_pbf.exists():
        raise FileNotFoundError(f"missing OSM extract: {osm_pbf}")
    try:
        from shapely.geometry import Point  # type: ignore
        from shapely.strtree import STRtree  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("OSM tunnel labeling requires shapely: python -m pip install shapely") from exc
    tunnel_geometries = load_tunnel_geometries(osm_pbf)
    tunnel_tree = STRtree(tunnel_geometries) if tunnel_geometries else None

    def labeler(fix: ReceiverFix) -> str:
        if tunnel_tree is None:
            return "urban"
        lat, lon = _cell_center_latlon(geometry, int(fix.cell_x), int(fix.cell_y))
        point = Point(lon, lat)
        buffer_deg = float(tunnel_buffer_m) / 111_320.0
        nearby = tunnel_tree.query(point.buffer(buffer_deg))
        for candidate in nearby:
            geom = tunnel_geometries[int(candidate)] if isinstance(candidate, Integral) else candidate
            if geom.distance(point) <= buffer_deg:
                return "tunnel"
        return "urban"

    return labeler


def load_tunnel_geometries(osm_pbf: Path) -> list:
    """Load tunnel road geometries with pyrosm when available, else osmium."""

    if not osm_pbf.exists():
        raise FileNotFoundError(f"missing OSM extract: {osm_pbf}")
    try:
        import pyrosm  # type: ignore
    except ModuleNotFoundError:
        return _load_tunnel_geometries_osmium(osm_pbf)
    osm = pyrosm.OSM(str(osm_pbf))
    roads = osm.get_network(network_type="driving", extra_attributes=["tunnel"])
    return list(roads.loc[roads["tunnel"].notna(), "geometry"])


def _load_tunnel_geometries_osmium(osm_pbf: Path) -> list:
    try:
        import osmium  # type: ignore
        from shapely.geometry import LineString  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("OSM parsing requires osmium and shapely: python -m pip install osmium shapely") from exc

    geometries: list = []

    class TunnelHandler(osmium.SimpleHandler):
        def way(self, way):
            tunnel = way.tags.get("tunnel")
            highway = way.tags.get("highway")
            if not highway or not tunnel or tunnel in {"no", "false", "0"}:
                return
            coords = [(node.lon, node.lat) for node in way.nodes if node.location.valid()]
            if len(coords) >= 2:
                geometries.append(LineString(coords))

    handler = TunnelHandler()
    handler.apply_file(str(osm_pbf), locations=True)
    return geometries


def write_extract_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(OSM_EXTRACTS, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def missing_extracts(root: Path = Path(".")) -> list[dict[str, str]]:
    missing = []
    for city, info in OSM_EXTRACTS.items():
        extract = root / info["path"]
        complete = Path(f"{extract}.complete")
        needs_marker = city in {"porto", "rome"}
        if not extract.exists() or (needs_marker and not complete.exists()):
            reason = "missing_file" if not extract.exists() else "incomplete_download"
            missing.append({"city": city, "reason": reason, **info})
    return missing


def _geometry(
    city: str,
    granularity: str,
    lat: float,
    lon: float,
    rings,
    grid_w: int,
    cell_size_m: int,
    boundary_buffer_m: float,
) -> TariffGeometry:
    zones = tuple(CircleZone(zone_id, lat, lon, max(0.0, radius + boundary_buffer_m), rate) for radius, zone_id, rate in rings)
    return TariffGeometry(city, granularity, lat, lon, grid_w, cell_size_m, zones, 99, 1)


def _cell_center_latlon(geometry: TariffGeometry, x: int, y: int) -> tuple[float, float]:
    half = geometry.grid_w * geometry.cell_size_m / 2
    east = (x + 0.5) * geometry.cell_size_m - half
    north = (y + 0.5) * geometry.cell_size_m - half
    lat = geometry.origin_lat + math.degrees(north / 6_371_000.0)
    lon = geometry.origin_lon + math.degrees(east / (6_371_000.0 * math.cos(math.radians(geometry.origin_lat))))
    return lat, lon


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    dlat, dlon = lat2_r - lat1_r, lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_000.0 * math.asin(math.sqrt(a))


def _tariff_version(city: str, granularity: str) -> int:
    return {"beijing": 100, "rome": 200, "porto": 300}[city] + {"coarse": 1, "medium": 2, "fine": 3}[granularity]


def _point_in_ring(lat: float, lon: float, ring: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    j = len(ring) - 1
    for i, (yi, xi) in enumerate(ring):
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside
