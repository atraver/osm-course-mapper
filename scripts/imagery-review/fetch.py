"""Fetch a bounded GSI seamlessphoto tile grid. Only Python's standard library is required."""

import argparse
import datetime
import json
import math
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def tile(lon, lat, zoom):
    n = 2**zoom
    return math.floor((lon + 180) / 360 * n), math.floor(
        (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    )


def fetch(bounds, dest):
    west, south, east, north = bounds
    if not (-180 <= west < east < 180 and -85 < south < north < 85):
        raise ValueError("Supply west south east north in WGS84")
    z = 18
    x0, y0 = tile(west, north, z)
    x1, y1 = tile(east, south, z)
    if (x1 - x0 + 1) * (y1 - y0 + 1) > 144:
        raise ValueError(
            "Split large areas into overlapping grids of at most 144 tiles"
        )
    dest.mkdir(parents=True, exist_ok=True)
    day = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            path = dest / f"{z}-{x}-{y}.jpg"
            if not path.exists():
                url = f"https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg"
                with urlopen(
                    Request(url, headers={"User-Agent": "Golf imagery review/1.0"}),
                    timeout=25,
                ) as response:
                    data = response.read(1024 * 1024)
                if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
                    raise ValueError(f"Invalid tile {x}/{y}")
                tmp = path.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(path)
    periods = []
    for y in range(y0 >> 7, (y1 >> 7) + 1):
        for x in range(x0 >> 7, (x1 >> 7) + 1):
            url = f"https://maps.gsi.go.jp/xyz/seamlessphoto_spec/11/{x}/{y}.geojson"
            try:
                with urlopen(url, timeout=25) as response:
                    periods.extend(json.load(response)["features"])
            except HTTPError as error:
                if error.code not in (404, 410):
                    raise
    (dest / "capture-periods.geojson").write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": periods}, ensure_ascii=False
        )
    )
    grid = dict(
        z=z,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        bounds=bounds,
        assembled_utc=day,
        imagery="GSImaps/seamlessphoto",
        capture_date=None,
    )
    (dest / "grid.json").write_text(json.dumps(grid, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path)
    parser.add_argument(
        "bounds", type=float, nargs=4, metavar="COORD", help="west south east north"
    )
    args = parser.parse_args()
    fetch(args.bounds, args.dest)
