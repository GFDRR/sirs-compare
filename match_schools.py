#!/usr/bin/env python3
"""Cross-source match analysis: OSM vs Overture school points.

For each country, pair up OSM and Overture school points that likely refer to
the same real-world school: nearest-neighbour search in metric space (local UTM)
capped at MAX_DIST_M, scored by distance and fuzzy name similarity, then a
greedy 1:1 assignment (best score first).

Outputs (all consumed by index.html):
  data/osm_schools_<ISO>.geojson       - enriched in place with match_* props
  data/overture_schools_<ISO>.geojson  - enriched in place with match_* props
  data/match_lines_<ISO>.geojson       - LineString per matched pair
  data/match_summary.json              - per-country stats for the UI panel

Match properties added to each point:
  match        "both" | "only"
  match_dist_m distance to the matched counterpart (matched points only)
  match_name   the counterpart's name (matched points only)
  name_sim     0..1 fuzzy similarity of the two names (matched, both named)

Run (after extract + clip):
    python match_schools.py
"""
import json
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
ISOS = ["NER", "GIN", "MLI", "BEN", "GHA"]

MAX_DIST_M = 300.0    # outer search radius for candidate pairs
CLOSE_DIST_M = 100.0  # within this, proximity alone is convincing
NAME_SIM_MATCH = 0.5  # beyond CLOSE_DIST_M a pair also needs this name support
NAME_SIM_AGREE = 0.6  # threshold above which we call the names "agreeing"

# Generic tokens that carry no identity (multilingual school words + stopwords).
GENERIC = {
    "ecole", "school", "schools", "college", "lycee", "groupe", "scolaire",
    "primaire", "primary", "secondaire", "secondary", "publique", "public",
    "privee", "prive", "private", "junior", "senior", "high", "basic",
    "international", "academy", "academie", "institut", "institute",
    "centre", "center", "complexe", "complex", "the", "de", "du", "des",
    "la", "le", "les", "of", "and", "et", "d", "l",
}


def normalize(name):
    if not name:
        return "", ()
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = "".join(c if c.isalnum() else " " for c in s)
    tokens = tuple(t for t in s.split() if t)
    distinct = tuple(t for t in tokens if t not in GENERIC)
    return " ".join(tokens), distinct


def name_similarity(a, b):
    """0..1 similarity; None when either side is unnamed."""
    if not a or not b:
        return None
    fa, da = normalize(a)
    fb, db = normalize(b)
    if not fa or not fb:
        return None
    full = SequenceMatcher(None, fa, fb).ratio()
    # Token-set overlap on the distinctive tokens (ignores word order and
    # generic words like "ecole"/"school").
    if da and db:
        sa, sb = set(da), set(db)
        tok = len(sa & sb) / len(sa | sb)
    else:
        tok = 0.0
    return round(max(full, tok), 3)


def load(iso, src):
    fp = DATA / f"{src}_schools_{iso}.geojson"
    g = gpd.read_file(fp).set_crs(4326, allow_override=True)
    return fp, g


# Constant-per-file or mostly-empty props we drop to keep the repo small. The
# UI derives source/country from the file name; null props are simply omitted.
DROP_PROPS = {"iso", "country", "source"}


def write_points(gdf, fp, name):
    """Compact GeoJSON writer: skip nulls, keep numbers numeric, 6 decimals."""
    cols = [c for c in gdf.columns if c != "geometry" and c not in DROP_PROPS]
    feats = []
    for _, row in gdf.iterrows():
        props = {}
        for c in cols:
            v = row[c]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                continue
            if c == "level" and v == "Unknown":
                continue
            # "only" is the implicit default; the UI treats a missing match
            # prop as unmatched, so only "both" needs to be stored.
            if c == "match" and v == "only":
                continue
            if isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.floating,)):
                v = float(v)
            props[c] = v
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [round(row.geometry.x, 6),
                                         round(row.geometry.y, 6)]},
            "properties": props,
        })
    with open(fp, "w") as fh:
        json.dump({"type": "FeatureCollection", "name": name, "features": feats},
                  fh, ensure_ascii=False)


def match_country(iso):
    fp_osm, osm = load(iso, "osm")
    fp_ovt, ovt = load(iso, "overture")

    utm = osm.estimate_utm_crs()
    osm_m = osm.to_crs(utm)
    ovt_m = ovt.to_crs(utm)
    osm_xy = np.c_[osm_m.geometry.x, osm_m.geometry.y]
    ovt_xy = np.c_[ovt_m.geometry.x, ovt_m.geometry.y]

    # Candidate pairs: every OSM point within MAX_DIST_M of each Overture point.
    tree = cKDTree(osm_xy)
    cands = []  # (score, dist, ovt_idx, osm_idx, sim)
    for j, neigh in enumerate(tree.query_ball_point(ovt_xy, r=MAX_DIST_M)):
        for i in neigh:
            d = float(np.hypot(*(osm_xy[i] - ovt_xy[j])))
            sim = name_similarity(osm.iloc[i].get("name"), ovt.iloc[j].get("name"))
            # Two-tier acceptance: very close pairs match on proximity alone;
            # farther pairs need name support to avoid weak coincidental links.
            if d > CLOSE_DIST_M and (sim is None or sim < NAME_SIM_MATCH):
                continue
            # Score: proximity (1 at 0 m, 0 at MAX_DIST_M) plus a name bonus so
            # the right pick wins when several schools sit close together.
            score = (1 - d / MAX_DIST_M) + (sim or 0.0)
            cands.append((score, d, j, i, sim))

    # Greedy 1:1 assignment, best score first.
    cands.sort(key=lambda t: -t[0])
    used_osm, used_ovt, pairs = set(), set(), []
    for score, d, j, i, sim in cands:
        if i in used_osm or j in used_ovt:
            continue
        used_osm.add(i)
        used_ovt.add(j)
        pairs.append((i, j, d, sim))

    # Enrich both layers.
    for g in (osm, ovt):
        g["match"] = "only"
        g["match_dist_m"] = None
        g["match_name"] = None
        g["name_sim"] = None
    lines = []
    for i, j, d, sim in pairs:
        osm.iloc[i, osm.columns.get_loc("match")] = "both"
        osm.iloc[i, osm.columns.get_loc("match_dist_m")] = round(d, 1)
        osm.iloc[i, osm.columns.get_loc("match_name")] = ovt.iloc[j].get("name")
        osm.iloc[i, osm.columns.get_loc("name_sim")] = sim
        ovt.iloc[j, ovt.columns.get_loc("match")] = "both"
        ovt.iloc[j, ovt.columns.get_loc("match_dist_m")] = round(d, 1)
        ovt.iloc[j, ovt.columns.get_loc("match_name")] = osm.iloc[i].get("name")
        ovt.iloc[j, ovt.columns.get_loc("name_sim")] = sim
        lines.append({
            "geometry": LineString([osm.geometry.iloc[i], ovt.geometry.iloc[j]]),
            "dist_m": round(d, 1),
            "name_sim": sim,
            "osm_name": osm.iloc[i].get("name"),
            "overture_name": ovt.iloc[j].get("name"),
        })

    write_points(osm, fp_osm, f"osm_schools_{iso}")
    write_points(ovt, fp_ovt, f"overture_schools_{iso}")
    line_feats = [{
        "type": "Feature",
        "geometry": {"type": "LineString",
                     "coordinates": [[round(x, 6), round(y, 6)]
                                     for x, y in ln["geometry"].coords]},
        "properties": {k: v for k, v in ln.items()
                       if k != "geometry" and v is not None},
    } for ln in lines]
    with open(DATA / f"match_lines_{iso}.geojson", "w") as fh:
        json.dump({"type": "FeatureCollection", "name": f"match_lines_{iso}",
                   "features": line_feats}, fh, ensure_ascii=False)

    dists = [d for _, _, d, _ in pairs]
    sims = [s for _, _, _, s in pairs if s is not None]
    n_named = len(sims)
    stats = {
        "n_osm": len(osm),
        "n_overture": len(ovt),
        "n_matched": len(pairs),
        "pct_overture_matched": round(100 * len(pairs) / len(ovt), 1) if len(ovt) else 0,
        "pct_osm_matched": round(100 * len(pairs) / len(osm), 1) if len(osm) else 0,
        "median_dist_m": round(float(np.median(dists)), 1) if dists else None,
        "n_named_pairs": n_named,
        "pct_names_agree": round(
            100 * sum(1 for s in sims if s >= NAME_SIM_AGREE) / n_named, 1
        ) if n_named else None,
        "overture_unmatched": len(ovt) - len(pairs),
        "osm_unmatched": len(osm) - len(pairs),
    }
    return stats


summary = {"max_dist_m": MAX_DIST_M, "name_sim_agree": NAME_SIM_AGREE, "countries": {}}
print(f"{'iso':5} {'matched':>8} {'%ovt':>6} {'%osm':>6} {'med m':>6} {'names agree':>12}")
for iso in ISOS:
    s = match_country(iso)
    summary["countries"][iso] = s
    agree = f"{s['pct_names_agree']}%" if s["pct_names_agree"] is not None else "-"
    print(f"{iso:5} {s['n_matched']:>8,} {s['pct_overture_matched']:>5}% "
          f"{s['pct_osm_matched']:>5}% {s['median_dist_m'] or 0:>6} {agree:>12}")

with open(DATA / "match_summary.json", "w") as f:
    json.dump(summary, f, indent=1)
print("\nWrote data/match_summary.json")
