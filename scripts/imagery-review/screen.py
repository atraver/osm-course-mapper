"""Screen automatic material guesses and collapse duplicate proposals before visual review."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import shape

from propose import Mosaic


def matches_material(hsv, mosaic, feature):
    kind = feature["properties"]["kind"]
    if kind not in {"water", "bunker"}:
        return True
    rings = [
        np.rint([mosaic.pixel(*p) for p in ring]).astype(np.int32)
        for ring in feature["geometry"]["coordinates"]
    ]
    x, y, w, h = cv2.boundingRect(rings[0])
    mask = np.zeros((h, w), np.uint8)
    for i, ring in enumerate(rings):
        cv2.fillPoly(mask, [ring - [x, y]], int(i == 0))
    interior = cv2.erode(mask, np.ones((5, 5), np.uint8))
    pixels = hsv[y : y + h, x : x + w][interior > 0]
    if not len(pixels):
        return False
    hue, sat, value = pixels.T
    mh, ms, mv = np.median(pixels, axis=0)
    if kind == "water":
        # Smooth blue-green ponds. Dark tree shadows can cover an entire SAM mask.
        return (
            84 <= mh <= 94
            and mv >= 86
            and np.mean((hue >= 82) & (hue <= 106) & (sat > 65)) >= 0.82
            and np.percentile(value, 90) - np.percentile(value, 10) <= 23
        )
    perimeter = cv2.arcLength(rings[0], True)
    compactness = 4 * np.pi * cv2.contourArea(rings[0]) / max(perimeter**2, 1)
    return (
        ms <= 26
        and mv >= 165
        and compactness >= 0.20
        and np.mean((sat < 35) & (value >= 154)) >= 0.8
    )


def screen(mosaic, raw):
    hsv = cv2.cvtColor(mosaic.image, cv2.COLOR_BGR2HSV)
    kept = []
    geometries = []
    for f in raw["features"]:
        if not matches_material(hsv, mosaic, f):
            continue
        geom, props = shape(f["geometry"]), f["properties"]
        duplicate = False
        for old, other in zip(kept, geometries):
            if old["properties"]["kind"] != props["kind"] or not other.intersects(geom):
                continue
            if geom.intersection(other).area / geom.union(other).area < 0.70:
                continue
            hints = {
                n
                for n in [
                    old["properties"]["hole"],
                    props["hole"],
                    *old["properties"].get("hole_hints", []),
                ]
                if n is not None
            }
            if len(hints) > 1:
                old["properties"]["hole"] = None
                old["properties"]["hole_hints"] = sorted(hints)
            duplicate = True
            break
        if not duplicate:
            kept.append(f)
            geometries.append(geom)
    return {"type": "FeatureCollection", "features": kept}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tiles", type=Path)
    parser.add_argument("candidates", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            screen(Mosaic(args.tiles), json.loads(args.candidates.read_text())),
            allow_nan=False,
        )
    )
