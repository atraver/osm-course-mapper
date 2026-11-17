"""Package the image and review queue as a static site. All review decisions stay in the browser."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import cv2
from shapely.geometry import shape

from propose import Mosaic


def package(tiles, queue, references, title, dest):
    mosaic = Mosaic(tiles)
    checked = [
        (f["properties"].get("kind"), shape(f["geometry"]))
        for f in references["features"]
        if f["geometry"]["type"] == "Polygon"
    ]
    pending = []
    for f in queue["features"]:
        area = shape(f["geometry"])
        if any(
            kind == f["properties"]["kind"]
            and area.intersects(existing)
            and area.intersection(existing).area / area.union(existing).area >= 0.5
            for kind, existing in checked
        ):
            continue
        pending.append(f)
    content = dict(
        title=title,
        grid=mosaic.grid,
        reference=references,
        candidates=dict(type="FeatureCollection", features=pending),
    )
    content["revision"] = hashlib.sha256(
        json.dumps(content, sort_keys=True).encode()
    ).hexdigest()[:20]
    dest.mkdir(parents=True, exist_ok=True)
    for file in (Path(__file__).parent / "viewer").iterdir():
        if file.is_file():
            shutil.copyfile(file, dest / file.name)
    if not cv2.imwrite(
        str(dest / "imagery.jpg"), mosaic.image, [cv2.IMWRITE_JPEG_QUALITY, 92]
    ):
        raise OSError("Could not write review imagery")
    (dest / "review.json").write_text(json.dumps(content, allow_nan=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tiles", type=Path)
    parser.add_argument("queue", type=Path)
    parser.add_argument("dest", type=Path)
    parser.add_argument(
        "--reference", type=Path, help="WGS84 polygon or line FeatureCollection"
    )
    parser.add_argument("--title", default="Course imagery review")
    args = parser.parse_args()
    refs = (
        json.loads(args.reference.read_text())
        if args.reference
        else {"type": "FeatureCollection", "features": []}
    )
    package(args.tiles, json.loads(args.queue.read_text()), refs, args.title, args.dest)
