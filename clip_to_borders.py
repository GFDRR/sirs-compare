#!/usr/bin/env python3
"""Clip the school-point layers to actual country boundaries.

The bbox-based extract pulled in neighbouring countries (Overture especially).
This downloads admin-0 boundaries (geoBoundaries gbOpen, CC-BY) and keeps only
points that fall WITHIN each country polygon. Overwrites data/*.geojson in place
and reports before/after counts.

Run after extract_overture_places.py / refreshing the OSM layers.
"""
import json
import urllib.request
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
BND = ROOT / "boundaries"          # gitignored cache
BND.mkdir(exist_ok=True)

ISOS = ["NER", "GIN", "MLI", "BEN", "GHA"]
GB = ("https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/"
      "gbOpen/{iso}/ADM0/geoBoundaries-{iso}-ADM0_simplified.geojson")


def boundary(iso):
    f = BND / f"{iso}_adm0.geojson"
    if not f.exists():
        urllib.request.urlretrieve(GB.format(iso=iso), f)
    g = gpd.read_file(f).to_crs(4326)
    return g.geometry.union_all()


def clip(iso, src):
    fp = DATA / f"{src}_schools_{iso}.geojson"
    if not fp.exists():
        return None
    pts = gpd.read_file(fp).set_crs(4326, allow_override=True)
    poly = boundary(iso)
    inside = pts[pts.within(poly)].copy()
    before, after = len(pts), len(inside)
    # write back as plain GeoJSON (preserve all properties)
    inside.to_file(fp, driver="GeoJSON")
    return before, after


print(f"{'country':8} {'source':9} {'before':>8} {'after':>8} {'dropped':>8}")
for iso in ISOS:
    for src in ["osm", "overture"]:
        r = clip(iso, src)
        if r:
            b, a = r
            print(f"{iso:8} {src:9} {b:>8,} {a:>8,} {b-a:>8,}")
