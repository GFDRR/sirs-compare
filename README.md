# SIRS Compare

A lightweight public web app to compare **open** school-location datasets over high-resolution satellite imagery for five West African countries: **Niger, Guinea, Mali, Benin, and Ghana**.

Pick a country, toggle data sources on and off, and zoom in to a school to eyeball whether each point actually sits on a real school building. It is a quick, visual way to gauge the completeness and accuracy of any one source before relying on it.

This app deliberately includes **only open data** (OpenStreetMap and Overture Maps). UNICEF Giga school data is **intentionally excluded** from this public app and is compared separately in a private variant.

## What it shows

- **Basemap**: Esri World Imagery (with an optional OpenStreetMap street basemap toggle).
- **Country selector** that loads each country's points and zooms to it.
- **Two toggleable point layers** per country, with a legend:
  - OpenStreetMap schools (green)
  - Overture Maps education places (orange)
- **Stats panel** with the live count of each source for the selected country.
- **Click a point** to see its name, source, and category.

## Running locally

It is a single self-contained `index.html` that fetches GeoJSON from `data/`. Serve the folder over HTTP (the `fetch` calls need a server, not `file://`):

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

## Data sources and licenses

| Source | Layer | License |
|--------|-------|---------|
| [OpenStreetMap](https://www.openstreetmap.org/) | `osm_schools_<ISO>.geojson` | ODbL - (c) OpenStreetMap contributors |
| [Overture Maps Foundation](https://overturemaps.org/) | `overture_schools_<ISO>.geojson` | ODbL / CC-BY (per-feature) |
| [Esri World Imagery](https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9) | basemap tiles | (c) Esri, Maxar, Earthstar Geographics |

Both vector datasets are open and used here with attribution. Counts are not de-duplicated against each other - overlap between OSM and Overture is expected.

## Rebuilding the Overture extract

The Overture school/education places are extracted cloud-natively with DuckDB (anonymous, unsigned reads against the public Overture S3 bucket - no bulk download). The build script is checked in:

```bash
pip install duckdb
python extract_overture_places.py 2026-05-20.0
```

This reads `s3://overturemaps-us-west-2/release/2026-05-20.0/theme=places/type=place/*.parquet`, pushes each country bounding box down into the `bbox` column, keeps places whose primary category is one of `school`, `primary_school`, `secondary_school`, `college_university`, or `education`, and writes one `data/overture_schools_<ISO>.geojson` per country.

Notes:
- Set `s3_region='us-west-2'` only - do **not** configure an S3 secret, or DuckDB will sign with empty credentials and get a 403.
- Country bounding boxes overlap neighbours; this is acceptable for v1. The Overture per-place address `country` attribute proved unreliable in this region, so the script filters by bounding box only.

The OpenStreetMap layers were prepared upstream from OSM extracts and copied into `data/` as `osm_schools_<ISO>.geojson`.

## Extract counts (Overture release 2026-05-20.0)

| Country | OSM | Overture |
|---------|-----|----------|
| Niger (NER)  | 2,514 | 1,052 |
| Guinea (GIN) | 2,352 | 836 |
| Mali (MLI)   | 11,816 | 936 |
| Benin (BEN)  | 2,739 | 4,423 |
| Ghana (GHA)  | 4,506 | 2,563 |

## AI-assisted development

> This project was developed with significant assistance from AI coding tools.

- **[Claude Code](https://claude.ai/claude-code)** (Anthropic) - code generation, architecture, data extraction, and documentation
- All functionality has been tested and verified to work as intended
- Features and infrastructure choices have been reviewed and approved by the maintainer

This disclosure follows emerging best practices for transparency in AI-assisted software development.

## License

Application code is provided as-is for public use. The underlying datasets retain their respective licenses (ODbL for OpenStreetMap and Overture Maps; Esri imagery per Esri terms). Attribution is required when reusing the data.
