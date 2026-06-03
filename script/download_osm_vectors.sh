#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OSM_DIR="${ROOT_DIR}/dataset/osm"
mkdir -p "${OSM_DIR}"

download_extract() {
  local target="$1"
  local url="$2"
  local part="${target}.part"
  local complete="${target}.complete"

  if [[ -f "${target}" && -f "${complete}" ]]; then
    echo "Already complete: ${target}"
    return
  fi
  if [[ -f "${target}" && ! -f "${part}" ]]; then
    mv "${target}" "${part}"
  fi
  curl -L --fail --retry 10 --retry-all-errors --connect-timeout 30 \
    -C - -o "${part}" "${url}"
  mv "${part}" "${target}"
  touch "${complete}"
}

download_extract \
  "${OSM_DIR}/portugal-latest.osm.pbf" \
  "https://download.geofabrik.de/europe/portugal-latest.osm.pbf"

download_extract \
  "${OSM_DIR}/centro-latest.osm.pbf" \
  "https://download.geofabrik.de/europe/italy/centro-latest.osm.pbf"

cat <<'EOF'
Portugal and Italy/Centro extracts downloaded.

Beijing needs a bbox extract:
1. Open https://extract.bbbike.org/
2. Choose PBF format.
3. Use bbox: 115.7,39.4,117.4,41.1
4. Save the downloaded file as:
   dataset/osm/beijing.osm.pbf
EOF
