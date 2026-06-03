#!/usr/bin/env python3
"""Fetch OSM school CAMPUS polygons (school grounds) via Overpass.

The point layers only carry centroids; this pulls the actual amenity=school
polygons - the open equivalent of campus/compound outlines. Closed ways become
Polygons; multipolygon relations are assembled from their outer ways (simple
ring stitching; inner holes are ignored - fine for visual comparison).

Output: data/osm_school_grounds_<ISO>.geojson

Geometry is simplified (~5 m tolerance) and rounded to 6 decimals to keep the
repo small.

Run:
    python fetch_osm_school_grounds.py
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from shapely.geometry import Polygon, mapping

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

# ISO3166-1 alpha-2 codes for the Overpass country areas.
COUNTRIES = {
    "NER": ("Niger",  "NE"),
    "GIN": ("Guinea", "GN"),
    "MLI": ("Mali",   "ML"),
    "BEN": ("Benin",  "BJ"),
    "GHA": ("Ghana",  "GH"),
}

OVERPASS = "https://overpass-api.de/api/interpreter"
SIMPLIFY_DEG = 0.00005  # ~5 m


def query(iso2):
    return f"""
[out:json][timeout:600];
area["ISO3166-1"="{iso2}"][admin_level=2]->.a;
(
  way["amenity"="school"](area.a);
  relation["amenity"="school"](area.a);
);
out tags geom;
"""


def fetch(iso2):
    data = ("data=" + urllib.parse.quote(query(iso2))).encode()
    req = urllib.request.Request(OVERPASS, data=data, headers={
        "User-Agent": "sirs-compare/1.0 (school location comparison; GFDRR)"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)


def way_polygon(el):
    """Closed way -> Polygon, else None."""
    geom = el.get("geometry")
    if not geom or len(geom) < 4:
        return None
    coords = [(p["lon"], p["lat"]) for p in geom]
    if coords[0] != coords[-1]:
        return None
    try:
        poly = Polygon(coords)
        return poly if poly.is_valid and poly.area > 0 else poly.buffer(0)
    except Exception:
        return None


def relation_polygons(el):
    """Stitch outer-way members into rings -> list of Polygons."""
    segs = []
    for m in el.get("members", []):
        if m.get("type") == "way" and m.get("role") in ("outer", "") and m.get("geometry"):
            segs.append([(p["lon"], p["lat"]) for p in m["geometry"]])
    rings, polys = [], []
    while segs:
        ring = segs.pop(0)
        progress = True
        while ring[0] != ring[-1] and progress:
            progress = False
            for k, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]
                elif s[-1] == ring[-1]:
                    ring += list(reversed(s))[1:]
                elif s[-1] == ring[0]:
                    ring = s + ring[1:]
                elif s[0] == ring[0]:
                    ring = list(reversed(s)) + ring[1:]
                else:
                    continue
                segs.pop(k)
                progress = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    for ring in rings:
        try:
            poly = Polygon(ring)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if not poly.is_empty:
                polys.append(poly)
        except Exception:
            pass
    return polys


def round_coords(obj, nd=6):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(c, nd) for c in obj]
        return [round_coords(o, nd) for o in obj]
    return obj


def main():
    print(f"{'ISO':4} {'Country':8} {'elements':>9} {'polygons':>9} {'KB':>8}")
    for iso, (name, iso2) in COUNTRIES.items():
        resp = fetch(iso2)
        feats = []
        for el in resp.get("elements", []):
            tags = el.get("tags", {})
            polys = []
            if el["type"] == "way":
                p = way_polygon(el)
                if p is not None and not p.is_empty:
                    polys = [p]
            elif el["type"] == "relation":
                polys = relation_polygons(el)
            for p in polys:
                p = p.simplify(SIMPLIFY_DEG, preserve_topology=True)
                if p.is_empty:
                    continue
                geom = mapping(p)
                geom = {"type": geom["type"],
                        "coordinates": round_coords(geom["coordinates"])}
                feats.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "id": f"osm_{el['type'][0]}{el['id']}",
                        "name": tags.get("name"),
                        "iso": iso,
                        "source": "osm",
                    },
                })
        fc = {"type": "FeatureCollection",
              "name": f"osm_school_grounds_{iso}", "features": feats}
        out = DATA / f"osm_school_grounds_{iso}.geojson"
        with open(out, "w") as fh:
            json.dump(fc, fh, ensure_ascii=False)
        kb = out.stat().st_size / 1024
        print(f"{iso:4} {name:8} {len(resp.get('elements', [])):>9,} "
              f"{len(feats):>9,} {kb:>8,.0f}", flush=True)
        time.sleep(10)  # be polite to Overpass between country queries


if __name__ == "__main__":
    main()
