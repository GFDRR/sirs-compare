#!/usr/bin/env python3
"""Build OSM school-building footprints from Geofabrik country extracts.

The OSM counterpart of the Overture edu-buildings layer. A building qualifies
when any of these hold (the `why` property records which):
  grounds - it intersects an amenity=school grounds polygon
  tag     - it is tagged as a school itself (building=school or amenity=school)
  node    - an amenity=school node sits inside it (school POI in the building)

Country-scale OSM extraction does NOT use Overpass (a shared query server that
504s on heavy spatial queries). Instead: one cached Geofabrik .osm.pbf download
per country, `osmium tags-filter` + `osmium export` locally, then exact
classification with shapely STRtrees. Fast, reproducible, no rate limits.

Requires: osmium-tool on PATH (brew install osmium-tool), shapely.

Output: data/osm_school_buildings_<ISO>.geojson

Run:
    python build_osm_school_buildings.py            # all countries
    python build_osm_school_buildings.py GHA BEN    # subset
"""
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from shapely.geometry import shape, mapping
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
# Raw Geofabrik extracts and osmium intermediates are bulky throwaway files -
# cache them in the system temp dir, NOT the project dir.
PBF = Path(tempfile.gettempdir()) / "sirs-compare-pbf"
PBF.mkdir(exist_ok=True)

COUNTRIES = {
    "NER": ("Niger",  "niger"),
    "GIN": ("Guinea", "guinea"),
    "MLI": ("Mali",   "mali"),
    "BEN": ("Benin",  "benin"),
    "GHA": ("Ghana",  "ghana"),
}

GEOFABRIK = "https://download.geofabrik.de/africa/{slug}-latest.osm.pbf"
SIMPLIFY_DEG = 0.00001   # ~1 m - buildings need their shape


def sh(*args):
    subprocess.run(args, check=True, capture_output=True, text=True)


def download(slug):
    pbf = PBF / f"{slug}-latest.osm.pbf"
    if not pbf.exists():
        url = GEOFABRIK.format(slug=slug)
        print(f"    downloading {url}", flush=True)
        # Download to .part then rename so an interrupted download never
        # leaves a truncated file that looks like a valid cache entry.
        part = pbf.with_suffix(".pbf.part")
        urllib.request.urlretrieve(url, part)
        part.rename(pbf)
    return pbf


def export_seq(src_pbf, out_path, *filters, geometry_types):
    """tags-filter then export to GeoJSONSeq; returns parsed features."""
    tmp = out_path.with_suffix(".pbf")
    sh("osmium", "tags-filter", "-O", "-o", str(tmp), str(src_pbf), *filters)
    sh("osmium", "export", "-O", "-o", str(out_path), "-u", "type_id",
       f"--geometry-types={geometry_types}", str(tmp))
    feats = []
    with open(out_path) as fh:
        for line in fh:
            line = line.lstrip("\x1e").strip()
            if line:
                feats.append(json.loads(line))
    tmp.unlink()
    out_path.unlink()
    return feats


def round_coords(obj, nd=6):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(c, nd) for c in obj]
        return [round_coords(o, nd) for o in obj]
    return obj


def build_country(iso, name, slug):
    pbf = download(slug)

    # School grounds polygons + school POI nodes (small filter, one pass).
    school_feats = export_seq(
        pbf, PBF / f"{slug}_schools.geojsonseq",
        "nwr/amenity=school", geometry_types="point,polygon")
    grounds, nodes = [], []
    for f in school_feats:
        g = f.get("geometry") or {}
        if g.get("type") == "Point":
            nodes.append(shape(g))
        elif g.get("type") in ("Polygon", "MultiPolygon"):
            grounds.append(shape(g))

    # All building footprints (big filter, streamed once).
    bld_feats = export_seq(
        pbf, PBF / f"{slug}_buildings.geojsonseq",
        "wr/building", geometry_types="polygon")

    grounds_tree = STRtree(grounds) if grounds else None
    nodes_tree = STRtree(nodes) if nodes else None

    out = []
    for f in bld_feats:
        tags = f.get("properties", {})
        try:
            p = shape(f["geometry"])
        except Exception:
            continue
        why = []
        if grounds_tree is not None and len(
                grounds_tree.query(p, predicate="intersects")):
            why.append("grounds")
        if tags.get("building") == "school" or tags.get("amenity") == "school":
            why.append("tag")
        if nodes_tree is not None and len(
                nodes_tree.query(p, predicate="contains")):
            why.append("node")
        if not why:
            continue
        p = p.simplify(SIMPLIFY_DEG, preserve_topology=True)
        if p.is_empty:
            continue
        geom = mapping(p)
        geom = {"type": geom["type"],
                "coordinates": round_coords(geom["coordinates"])}
        props = {"id": f"osm_{f.get('id', '')}", "why": ",".join(why)}
        if tags.get("name"):
            props["name"] = tags["name"]
        out.append({"type": "Feature", "geometry": geom, "properties": props})

    fc = {"type": "FeatureCollection",
          "name": f"osm_school_buildings_{iso}", "features": out}
    fp = DATA / f"osm_school_buildings_{iso}.geojson"
    with open(fp, "w") as fh:
        json.dump(fc, fh, ensure_ascii=False)
    kb = fp.stat().st_size / 1024
    print(f"{iso:4} {name:8} {len(bld_feats):>10,} {len(out):>8,} {kb:>8,.0f}",
          flush=True)


def main():
    want = [a.upper() for a in sys.argv[1:]] or list(COUNTRIES)
    print(f"{'ISO':4} {'Country':8} {'buildings':>10} {'kept':>8} {'KB':>8}")
    for iso, (name, slug) in COUNTRIES.items():
        if iso in want:
            build_country(iso, name, slug)


if __name__ == "__main__":
    main()
