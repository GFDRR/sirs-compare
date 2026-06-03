# SIRS Compare

**Live app: https://gfdrr.github.io/sirs-compare/**

A lightweight public web app to compare **open** school-location datasets over high-resolution satellite imagery for five West African countries: **Niger, Guinea, Mali, Benin, and Ghana**.

Pick a country, switch to the **Agreement** view to see which schools appear in both OpenStreetMap and Overture Maps and which are unique to one source, check how well their names agree, and toggle on building footprints and campus polygons to compare points against actual school compounds on the imagery.

This app deliberately includes **only open data** (OpenStreetMap and Overture Maps). UNICEF Giga school data is **intentionally excluded** from this public app and is compared separately in a private variant.

## What it shows

- **Basemap**: Esri World Imagery (with an optional OpenStreetMap street basemap toggle).
- **Country selector** that loads each country's layers and zooms to it.
- **Two view modes**:
  - *By source*: OpenStreetMap schools (green) vs Overture Maps education places (orange).
  - *Agreement*: points colored by cross-source match status - in both (cyan), OSM only (green), Overture only (orange) - with dashed connector lines between matched pairs when zoomed in.
- **Match analysis panel**: matched pair count, share of Overture found in OSM, median offset between matched points, and name agreement rate for the selected country.
- **Footprint layers**:
  - *OSM school grounds*: `amenity=school` polygons (campus/compound outlines).
  - *OSM school buildings*: `building` footprints that intersect school grounds, are tagged as schools (`building=school` / `amenity=school`), or contain an `amenity=school` node. Each popup states why the building qualifies.
  - *Overture edu buildings*: building footprints tagged `subtype=education`, drawn as a dashed orange outline so the solid OSM buildings stay visible underneath - solid green is OSM-only, green with an orange ring is in both, a dashed orange ring alone is an Overture-only footprint.
- **Click a point** to see its name, source, category, and its matched counterpart in the other source (name, distance, name similarity) - or confirmation that no counterpart exists within 300 m.

### How matching works

An OSM point and an Overture point are paired when they are within 100 m of each other, or within 300 m with similar names (fuzzy similarity of accent-stripped, stopword-filtered names). Assignment is 1:1, best pair first. See `match_schools.py`.

## Running locally

It is a single self-contained `index.html` that fetches GeoJSON from `data/`. Serve the folder over HTTP (the `fetch` calls need a server, not `file://`):

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

## Data sources and licenses

| Source | Layer | License |
|--------|-------|---------|
| [OpenStreetMap](https://www.openstreetmap.org/) | `osm_schools_<ISO>.geojson`, `osm_school_grounds_<ISO>.geojson`, `osm_school_buildings_<ISO>.geojson` | ODbL - (c) OpenStreetMap contributors |
| [Overture Maps Foundation](https://overturemaps.org/) | `overture_schools_<ISO>.geojson`, `overture_edu_buildings_<ISO>.geojson` | ODbL / CC-BY (per-feature) |
| [geoBoundaries](https://www.geoboundaries.org/) | `country_boundaries.geojson` (admin-0 clip + outlines) | CC-BY 4.0 |
| [Esri World Imagery](https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9) | basemap tiles | (c) Esri, Maxar, Earthstar Geographics |

All vector datasets are open and used here with attribution.

## Data pipeline

All layers are reproducible from checked-in scripts, run in this order:

```bash
pip install duckdb geopandas scipy shapely
brew install osmium-tool   # for the OSM school-buildings step

# 1. Overture education places (cloud-native DuckDB, anonymous S3 reads)
python extract_overture_places.py 2026-05-20.0

# 2. Overture education building footprints (buildings theme, subtype=education)
python extract_overture_buildings.py 2026-05-20.0

# 3. OSM school campus polygons (Overpass, amenity=school ways/relations)
python fetch_osm_school_grounds.py

# 4. OSM school buildings (Geofabrik country PBFs + osmium, classified locally)
python build_osm_school_buildings.py

# 5. Clip the point layers to admin-0 boundaries (geoBoundaries)
python clip_to_borders.py

# 6. Cross-source matching: enrich points, write match lines + summary stats
python match_schools.py
```

Country-scale OSM extraction (step 4) deliberately avoids Overpass: a query for "all buildings intersecting 1,200+ school polygons" times out on shared Overpass servers. Instead the script downloads each country's Geofabrik `.osm.pbf` once (cached in the system temp dir), filters with `osmium tags-filter`, and classifies buildings locally with spatial indexes.

Notes on the Overture extracts:
- Reads `s3://overturemaps-us-west-2/release/<release>/theme=.../*.parquet` with the country bounding box pushed down into the `bbox` column - no bulk download.
- Set `s3_region='us-west-2'` only - do **not** configure an S3 secret, or DuckDB will sign with empty credentials and get a 403.
- The Overture per-place address `country` attribute proved unreliable in this region, so clipping is done geometrically against geoBoundaries admin-0 polygons instead.

The OpenStreetMap point layers were prepared upstream from OSM extracts and copied into `data/` as `osm_schools_<ISO>.geojson`.

## Counts (clipped to admin-0; Overture release 2026-05-20.0)

| Country | OSM points | Overture points | Matched pairs | OSM campus polygons | OSM school buildings | Overture edu buildings |
|---------|-----------:|----------------:|--------------:|--------------------:|---------------------:|-----------------------:|
| Niger (NER)  | 2,512 | 156 | 14 | 942 | 4,059 | 707 |
| Guinea (GIN) | 2,351 | 291 | 40 | 1,051 | 4,007 | 874 |
| Mali (MLI)   | 11,798 | 297 | 54 | 964 | 5,972 | 651 |
| Benin (BEN)  | 2,713 | 303 | 25 | 1,270 | 5,576 | 1,838 |
| Ghana (GHA)  | 4,500 | 2,466 | 315 | 1,850 | 31,532 | 2,829 |

Headline findings so far:
- **The two POINT sources barely overlap**: only 8-18% of Overture education places have an OSM school within 300 m. Each source contributes mostly distinct records, so neither is a substitute for the other.
- **Overture POI coverage is sparse in francophone West Africa** (156-303 places per country) but strong in Ghana (2,466). OSM is the more complete point source everywhere.
- **Matched points sit 55-91 m apart (median)**, and among matched, named pairs the names agree 17-54% of the time - so even "the same school" is recorded quite differently across sources.
- **Overture adds essentially no school FOOTPRINTS beyond OSM**: Overture derives `subtype=education` from the building's own tags, which in this region come from OSM - so its edu-building counts track OSM's *tagged* school buildings within ~5-10% everywhere (e.g. Ghana 2,829 vs 2,593). The much larger OSM school-building counts come from the spatial-context criterion Overture has no equivalent of: untagged `building=yes` classroom blocks inside `amenity=school` campus polygons (28,469 of Ghana's 31,532).

## AI-assisted development

> This project was developed with significant assistance from AI coding tools.

- **[Claude Code](https://claude.ai/claude-code)** (Anthropic) - code generation, architecture, data extraction, and documentation
- All functionality has been tested and verified to work as intended
- Features and infrastructure choices have been reviewed and approved by the maintainer

This disclosure follows emerging best practices for transparency in AI-assisted software development.

## License

Application code is provided as-is for public use. The underlying datasets retain their respective licenses (ODbL for OpenStreetMap and Overture Maps; Esri imagery per Esri terms). Attribution is required when reusing the data.
