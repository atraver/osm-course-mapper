"""Seed a first review pass from a course boundary and optional numbered playing lines."""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import LineString, Point, shape

from propose import Mosaic


def prompts(mosaic, boundary, holes):
    image = mosaic.image
    height, width = image.shape[:2]
    centres = [
        (mosaic.pixel(*p.coords[0]), hole)
        for hole, line in holes
        for p in [line.interpolate(1, normalized=True)]
    ]
    lines = {
        hole: LineString([mosaic.pixel(*p) for p in line.coords])
        for hole, line in holes
    }
    _, latitude = mosaic.lonlat(width // 2, height // 2)
    gsd = 40075016.68557849 * math.cos(math.radians(latitude)) / mosaic.scale
    groups = defaultdict(list)

    def add(id_, kind, x, y, hole):
        x, y = round(x), round(y)
        if (
            0 <= x < width
            and 0 <= y < height
            and boundary.covers(Point(mosaic.lonlat(x, y)))
        ):
            groups[(x // 384, y // 384)].append(
                dict(id=id_, kind=kind, hole=hole, positive=[[x, y]])
            )

    # Endpoints are hints. A pin may lie on the fringe, and the first node
    # may represent any tee. Never assign a tee name from this operation.
    for (x, y), hole in centres:
        add(f"line-{hole}-green", "green", x, y, hole)
        line = lines[hole]
        add(f"line-{hole}-tee", "tee", *line.coords[0], hole)
        if line.length * gsd > 200:
            p = line.interpolate(0.66, normalized=True)
            add(f"line-{hole}-fairway", "fairway", p.x, p.y, hole)

    hsv = cv2.cvtColor(cv2.GaussianBlur(image, (5, 5), 0), cv2.COLOR_BGR2HSV)
    # Conservative colour seeds only. Light roofs can resemble sand and
    # shaded vegetation can resemble water. Both need visual classification.
    masks = {
        "bunker": cv2.inRange(hsv, (0, 0, 156), (179, 34, 255)),
        "water": cv2.inRange(hsv, (85, 65, 40), (106, 190, 150)),
    }
    for kind, mask in masks.items():
        clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(clean)
        for i in range(1, count):
            x, y, w, h, area = stats[i]
            metres = area * gsd**2
            if metres < (12 if kind == "bunker" else 85) or metres > (
                1200 if kind == "bunker" else 12000
            ):
                continue
            if min(w, h) < 4 or area / (w * h) < 0.22:
                continue
            local = np.pad((labels[y : y + h, x : x + w] == i).astype(np.uint8), 1)
            distance = cv2.distanceTransform(local, cv2.DIST_L2, 5)
            v, u = np.unravel_index(np.argmax(distance), distance.shape)
            if distance[v, u] * gsd < (1.4 if kind == "bunker" else 3.0):
                continue
            if kind == "water":
                interior = distance[1:-1, 1:-1] > 2.0 / gsd
                values = hsv[y : y + h, x : x + w, 2][interior]
                if np.std(values) > 10:
                    continue
            # Hole ownership is intentionally left open for physical areas.
            add(f"{kind}-{x}-{y}", kind, int(x + u - 1), int(y + v - 1), None)
    windows = []
    for (col, row), group in sorted(groups.items()):
        x, y = max(0, col * 384 - 128), max(0, row * 384 - 128)
        right, bottom = (
            min(width, (col + 1) * 384 + 128),
            min(height, (row + 1) * 384 + 128),
        )
        windows.append(dict(crop=[x, y, right - x, bottom - y], prompts=group))
    return dict(
        grid=[mosaic.grid[k] for k in ("z", "x0", "y0", "x1", "y1")],
        boundary=boundary.__geo_interface__,
        windows=windows,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tiles", type=Path)
    parser.add_argument(
        "boundary", type=Path, help="WGS84 GeoJSON Polygon/MultiPolygon geometry"
    )
    parser.add_argument(
        "--lines",
        type=Path,
        help="GeoJSON FeatureCollection with a unique integer hole property per line",
    )
    args = parser.parse_args()
    boundary = shape(json.loads(args.boundary.read_text()))
    if (
        boundary.geom_type not in {"Polygon", "MultiPolygon"}
        or not boundary.is_valid
        or boundary.is_empty
    ):
        raise ValueError("Invalid course polygon")
    holes = []
    if args.lines:
        for f in json.loads(args.lines.read_text())["features"]:
            line, hole = shape(f["geometry"]), f["properties"]["hole"]
            if (
                line.geom_type != "LineString"
                or line.is_empty
                or type(hole) is not int
                or hole < 1
                or any(h == hole for h, _ in holes)
            ):
                raise ValueError("Expected a distinct numbered playing line")
            holes.append((hole, line))
    print(json.dumps(prompts(Mosaic(args.tiles), boundary, holes)))
