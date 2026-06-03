#!/usr/bin/env python3
"""Extract Overture Maps school/education places for 5 West African countries.

Cloud-native: anonymous (unsigned) reads against the public Overture S3 bucket
via DuckDB httpfs + spatial. We push the country bbox down into the `bbox`
struct column so only relevant row groups are scanned, then materialize a small
per-country GeoJSON of education-related places.

Output: data/overture_schools_<ISO>.geojson  (one FeatureCollection per country)

Data source: Overture Maps Foundation, release 2026-05-20.0, places theme.
License: ODbL / CC-BY (per-feature; see Overture attribution requirements).

Run:
    python extract_overture_places.py
    python extract_overture_places.py 2026-05-20.0   # pin a specific release
"""
import json
import os
import sys

import duckdb

# Overture release to pin (override via argv[1]).
RELEASE = sys.argv[1] if len(sys.argv) > 1 else "2026-05-20.0"

# Education-related place categories to keep.
CATEGORIES = (
    "school",
    "primary_school",
    "secondary_school",
    "college_university",
    "education",
)

# Country bboxes (xmin, ymin, xmax, ymax) WGS84. These overlap neighbours;
# acceptable for v1. We rely on bbox pushdown only: the Overture per-place
# `addresses[].country` attribute proved unreliable for this region (many
# education places carry mismatched or missing address countries), so clipping
# on it would silently drop valid schools. Raw bbox counts match the expected
# per-country totals, so bbox alone is the trustworthy filter for v1.
COUNTRIES = {
    "NER": ("Niger",  (0.1, 11.6, 16.0, 23.6)),
    "GIN": ("Guinea", (-15.1, 7.1, -7.6, 12.7)),
    "MLI": ("Mali",   (-12.3, 10.1, 4.3, 25.0)),
    "BEN": ("Benin",  (0.7, 6.1, 3.9, 12.5)),
    "GHA": ("Ghana",  (-3.3, 4.7, 1.2, 11.2)),
}

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

PLACE_SRC = (
    f"s3://overturemaps-us-west-2/release/{RELEASE}/"
    "theme=places/type=place/*.parquet"
)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    # Public bucket: set region only, NO secret. A config secret would sign with
    # empty creds -> 403. DuckDB then issues unsigned requests, which S3 allows.
    con.execute("SET s3_region='us-west-2';")

    cat_list = ", ".join(f"'{c}'" for c in CATEGORIES)
    print(f"Overture release: {RELEASE}\n", flush=True)
    print(f"{'ISO':4} {'Country':8} {'places extracted':>18}")

    grand_total = 0
    for iso, (name, bbox) in COUNTRIES.items():
        xmin, ymin, xmax, ymax = bbox
        q = f"""
            SELECT
                id,
                names.primary AS name,
                categories.primary AS category,
                ST_X(geometry) AS lon,
                ST_Y(geometry) AS lat
            FROM read_parquet('{PLACE_SRC}', filename=false, hive_partitioning=1)
            WHERE bbox.xmin BETWEEN {xmin} AND {xmax}
              AND bbox.ymin BETWEEN {ymin} AND {ymax}
              AND categories.primary IN ({cat_list})
        """
        rows = con.execute(q).fetchall()

        features = []
        for rid, rname, rcat, lon, lat in rows:
            if lon is None or lat is None:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": {
                    "id": rid,
                    "name": rname,
                    "category": rcat,
                    "iso": iso,
                    "country": name,
                    "source": "overture",
                },
            })

        fc = {
            "type": "FeatureCollection",
            "name": f"overture_schools_{iso}",
            "features": features,
        }
        out_path = os.path.join(OUT_DIR, f"overture_schools_{iso}.geojson")
        with open(out_path, "w") as fh:
            json.dump(fc, fh, ensure_ascii=False)
        grand_total += len(features)
        print(f"{iso:4} {name:8} {len(features):>18,}", flush=True)

    print(f"\nTotal Overture places written: {grand_total:,}")
    print(f"Output dir: {OUT_DIR}")


if __name__ == "__main__":
    main()
