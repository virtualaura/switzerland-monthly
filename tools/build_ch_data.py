"""Build ch-data.js for 404.html: the Swiss border and commune centres, projected to SVG units.

Run once from the repo root:  python3 tools/build_ch_data.py
Standard library only. Border: geoBoundaries (fallback Natural Earth). Communes: Wikidata.
"""
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "ch-data.js"
HEADERS = {"User-Agent": "switzerland-monthly-404/1.0 (static site build script)"}
WIDTH = 1000
TOLERANCE = 0.3  # SVG units; lower keeps more border detail

SPARQL = """
SELECT ?c (SAMPLE(?coord) AS ?pt) (SAMPLE(?de) AS ?label)
       (GROUP_CONCAT(DISTINCT ?official; separator="|") AS ?officials) WHERE {
  ?c wdt:P31 wd:Q70208 ; wdt:P625 ?coord .
  FILTER NOT EXISTS { ?c wdt:P576 ?end }
  OPTIONAL { ?c rdfs:label ?de FILTER(LANG(?de) = "de") }
  OPTIONAL { ?c wdt:P1448 ?official }
} GROUP BY ?c
"""


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def rings_from_geojson(gj):
    feats = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
    rings = []
    for f in feats:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            rings.extend(poly)
    return rings


def border_rings():
    try:
        meta = get_json("https://www.geoboundaries.org/api/current/gbOpen/CHE/ADM0/")
        rings = rings_from_geojson(get_json(meta["gjDownloadURL"]))
        print("border: geoBoundaries,", sum(len(r) for r in rings), "raw points")
        return rings
    except Exception as e:
        print("geoBoundaries failed (%s); using Natural Earth via mledoze/countries" % e)
        gj = get_json("https://raw.githubusercontent.com/mledoze/countries/master/data/che.geo.json")
        rings = rings_from_geojson(gj)
        print("border: Natural Earth,", sum(len(r) for r in rings), "raw points")
        return rings


def communes():
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(SPARQL)
    rows = get_json(url)["results"]["bindings"]
    out = []
    for r in rows:
        lon, lat = map(float, r["pt"]["value"].removeprefix("Point(").rstrip(")").split())
        officials = [o for o in r.get("officials", {}).get("value", "").split("|") if o]
        if len(officials) == 1:
            name = officials[0]
        elif len(officials) == 2:
            name = "/".join(officials)
        else:
            name = r.get("label", {}).get("value", "")
        if name:
            out.append((name, lon, lat))
    print("communes:", len(out))
    return out


def simplify(points, tol):
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            if norm < 1e-9:  # closed ring: first and last points coincide
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dy * (px - ax) - dx * (py - ay)) / norm
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def main():
    rings = border_rings()
    lons = [p[0] for r in rings for p in r]
    lats = [p[1] for r in rings for p in r]
    lon0, lon1, lat0, lat1 = min(lons), max(lons), min(lats), max(lats)
    k = math.cos(math.radians((lat0 + lat1) / 2))
    sy = WIDTH / ((lon1 - lon0) * k)
    kx = k * sy
    height = (lat1 - lat0) * sy

    def proj(lon, lat):
        return ((lon - lon0) * kx, (lat1 - lat) * sy)

    parts, kept = [], 0
    for ring in rings:
        pts = simplify([proj(lon, lat) for lon, lat in ring], TOLERANCE)
        if len(pts) < 4:
            continue
        kept += len(pts)
        parts.append("M" + "L".join("%.1f,%.1f" % p for p in pts) + "Z")
    print("border: %d points after simplification, %d rings" % (kept, len(parts)))

    towns = [[n, round(x, 1), round(y, 1)] for n, lon, lat in communes() for x, y in [proj(lon, lat)]]

    data = {
        "w": WIDTH, "h": round(height, 1),
        "lon0": lon0, "lat1": lat1, "kx": kx, "sy": sy,
        "path": "".join(parts),
        "communes": towns,
    }
    OUT.write_text("window.CH=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("wrote", OUT, "(%d KB)" % (OUT.stat().st_size // 1024))


if __name__ == "__main__":
    main()
