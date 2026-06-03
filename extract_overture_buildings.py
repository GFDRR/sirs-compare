#!/usr/bin/env python3
"""Extract Overture education building FOOTPRINTS for the 5 countries.

Same cloud-native pattern as extract_overture_places.py, but against the
buildings theme: polygons where subtype = 'education' (school / university /
kindergarten building footprints). These come largely from OSM but also from
Microsoft / Google / Esri sources, so they can include footprints OSM lacks.

Output: data/overture_edu_buildings_<ISO>.geojson

Clipping: features are kept when their centroid falls inside the cached
geoBoundaries admin-0 polygon (boundaries/<ISO>_adm0.geojson, created by
clip_to_borders.py).

Run:
    python extract_overture_buildings.py
    python extract_overture_buildings.py 2026-05-20.0
"""
import json
import os
import sys

import duckdb
from shapely.geometry import shape, Point

RELEASE = sys.argv[1] if len(sys.argv) > 1 else "2026-05-20.0"

COUNTRIES = {
    "NER": ("Niger",  (0.1, 11.6, 16.0, 23.6)),
    "GIN": ("Guinea", (-15.1, 7.1, -7.6, 12.7)),
    "MLI": ("Mali",   (-12.3, 10.1, 4.3, 25.0)),
    "BEN": ("Benin",  (0.7, 6.1, 3.9, 12.5)),
    "GHA": ("Ghana",  (-3.3, 4.7, 1.2, 11.2)),
}

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "data")
BND_DIR = os.path.join(ROOT, "boundaries")

BLD_SRC = (
    f"s3://overturemaps-us-west-2/release/{RELEASE}/"
    "theme=buildings/type=building/*.parquet"
)


def load_boundary(iso):
    fp = os.path.join(BND_DIR, f"{iso}_adm0.geojson")
    with open(fp) as fh:
        gj = json.load(fh)
    from shapely.ops import unary_union
    return unary_union([shape(f["geometry"]) for f in gj["features"]])


def round_coords(obj, nd=6):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(c, nd) for c in obj]
        return [round_coords(o, nd) for o in obj]
    return obj


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    # Public bucket: region only, NO secret (a secret would sign -> 403).
    con.execute("SET s3_region='us-west-2';")

    print(f"Overture release: {RELEASE} (buildings, subtype=education)\n", flush=True)
    print(f"{'ISO':4} {'Country':8} {'raw':>8} {'clipped':>8}")

    grand_total = 0
    for iso, (name, bbox) in COUNTRIES.items():
        xmin, ymin, xmax, ymax = bbox
        q = f"""
            SELECT
                id,
                names.primary AS name,
                class,
                ST_AsGeoJSON(geometry) AS geom
            FROM read_parquet('{BLD_SRC}', filename=false, hive_partitioning=1)
            WHERE bbox.xmin BETWEEN {xmin} AND {xmax}
              AND bbox.ymin BETWEEN {ymin} AND {ymax}
              AND subtype = 'education'
        """
        rows = con.execute(q).fetchall()

        poly = load_boundary(iso)
        features = []
        for rid, rname, rclass, geom_json in rows:
            if not geom_json:
                continue
            geom = json.loads(geom_json)
            c = shape(geom).centroid
            if not poly.contains(Point(c.x, c.y)):
                continue
            geom["coordinates"] = round_coords(geom["coordinates"])
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "id": rid,
                    "name": rname,
                    "class": rclass,
                    "iso": iso,
                    "source": "overture",
                },
            })

        fc = {"type": "FeatureCollection",
              "name": f"overture_edu_buildings_{iso}", "features": features}
        out_path = os.path.join(OUT_DIR, f"overture_edu_buildings_{iso}.geojson")
        with open(out_path, "w") as fh:
            json.dump(fc, fh, ensure_ascii=False)
        grand_total += len(features)
        print(f"{iso:4} {name:8} {len(rows):>8,} {len(features):>8,}", flush=True)

    print(f"\nTotal education building footprints written: {grand_total:,}")


if __name__ == "__main__":
    main()
