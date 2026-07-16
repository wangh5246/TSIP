# Rome Parking Tariff Overlay

This directory contains the reproducible Rome tariff overlay used for the E1
Rome real-tariff check.

## Official Sources

The source map is the public Roma Mobilita "Sosta tariffata" ArcGIS web map:

- App item: `962c8b4334d74dc6ae043a5e4b8643d0`
- Web map item: `b7be6a72ce2b4e54b1b9adde1a11df8f`
- Blue-stripe parking streets:
  `https://services2.arcgis.com/NZMqCJwY3kMjFOqf/arcgis/rest/services/strisce_blu_strade/FeatureServer/0`
- ZTL center boundary, retained for provenance:
  `https://services2.arcgis.com/NZMqCJwY3kMjFOqf/arcgis/rest/services/confini_ZTL_centro_diurna/FeatureServer/0`

The blue-stripe layer is a polyline FeatureServer with `TARIFFA`, `ZONA`,
`AMBITO`, `GIORNI`, `DALLE`, and `ALLE` fields. The observed official tariffs
are `0,50 euro/h`, `1 euro/h`, and `1,20 euro/h`.

## Rate Normalization

The TSIP settlement harness expects integer `rate_cents_per_m` tiers, while the
official parking layer reports hourly rates. The overlay preserves only the
official relative tariff structure and normalizes the absolute scale:

- `0,50 euro/h -> 5`
- `1 euro/h -> 10`
- `1,20 euro/h -> 12`

This exactly preserves the official ratio `0.50:1.00:1.20 = 5:10:12`.
The absolute units are not interpreted as real cents per meter.

## Polyline-To-Cell Assignment

The official parking layer is street-linear, but the circuit tariff is a grid of
area cells. The conversion assigns each 100m Rome tariff-grid cell to the
normalized rate of the nearest official blue-stripe street segment.

The importer fails unless the maximum nearest-street distance is explicitly
accepted with `--max-nearest-m`. For the generated full 100x100 Rome grid, the
maximum nearest distance is about 3.63 km. The E1 working block used by the Rome
periods is checked separately before running the experiment; the current block
contains only the `1 euro/h` and `1,20 euro/h` tiers, so Rome's lifted savings
exercise the conservative 1.2x tariff contrast rather than the full 2.4x
contrast present elsewhere in the official grid.

## Rebuild

```bash
python script/build_rome_parking_tariff_geojson.py \
  --output dataset/osm/zones/rome_medium.geojson \
  --raw-output-dir dataset/osm/zones/raw \
  --max-nearest-m 4000
```
