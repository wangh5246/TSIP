#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.osm_vectors import OSM_EXTRACTS, load_tunnel_geometries


def main() -> int:
    rows = []
    for city, info in OSM_EXTRACTS.items():
        path = ROOT_DIR / info["path"]
        if not path.exists():
            rows.append({"city": city, "path": str(path), "status": "missing"})
            continue
        geometries = load_tunnel_geometries(path)
        rows.append({"city": city, "path": str(path), "status": "ok", "tunnel_ways": len(geometries)})
    print(json.dumps(rows, indent=2))
    return 0 if all(row["status"] == "ok" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
