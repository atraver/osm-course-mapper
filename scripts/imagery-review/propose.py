"""Turn point prompts on GSI tiles into reviewable WGS84 polygons, entirely offline."""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from shapely.geometry import Polygon, mapping, shape
from shapely.geometry.polygon import orient

WEIGHTS = {
    "vision_encoder_quantized": "cce23c7b2e5d4f330932738fb67ba518e04b0d99ccdd1cccd22a7da4e01f2971",
    "prompt_encoder_mask_decoder_quantized": "cb90b279f549d2cab7fd6e20c38522438c65d84bdcca3d2a764cff7d857fdce2",
}
MODEL = "Xenova/slimsam-77-uniform@5850ab45f587c112167512ffef949107115e26a0"
KINDS = {"tee", "green", "fairway", "bunker", "water"}


class Mosaic:
    def __init__(self, folder):
        g = json.loads((folder / "grid.json").read_text())
        self.grid = g
        rows = []
        for y in range(g["y0"], g["y1"] + 1):
            tiles = []
            for x in range(g["x0"], g["x1"] + 1):
                image = cv2.imread(str(folder / f"{g['z']}-{x}-{y}.jpg"))
                if image is None or image.shape != (256, 256, 3):
                    raise ValueError(f"Missing or invalid tile {x}/{y}")
                tiles.append(image)
            rows.append(np.hstack(tiles))
        self.image = np.vstack(rows)
        self.scale = 256 * 2 ** g["z"]

    def lonlat(self, x, y):
        # OpenCV contour coordinates refer to pixel centres.
        g = self.grid
        col = (g["x0"] * 256 + x + 0.5) / self.scale
        row = (g["y0"] * 256 + y + 0.5) / self.scale
        return (
            round(col * 360 - 180, 8),
            round(math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row)))), 8),
        )

    def pixel(self, lon, lat):
        g = self.grid
        return (
            (lon + 180) / 360 * self.scale - g["x0"] * 256 - 0.5,
            (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * self.scale
            - g["y0"] * 256
            - 0.5,
        )


class Segmenter:
    def __init__(self, directory):
        sessions = []
        options = ort.SessionOptions()
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        for name, digest in WEIGHTS.items():
            path = directory / (name + ".onnx")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Weight checksum mismatch for {name}")
            sessions.append(
                ort.InferenceSession(
                    str(path), options, providers=["CPUExecutionProvider"]
                )
            )
        self.encoder, self.decoder = sessions

    def encode(self, image):
        height, width = image.shape[:2]
        self.size = (
            round(width * 1024 / max(width, height)),
            round(height * 1024 / max(width, height)),
        )
        rgb = cv2.cvtColor(cv2.resize(image, self.size), cv2.COLOR_BGR2RGB)
        norm = (rgb.astype(np.float32) / 255 - [0.485, 0.456, 0.406]) / [
            0.229,
            0.224,
            0.225,
        ]
        tensor = np.zeros((1, 3, 1024, 1024), dtype=np.float32)
        tensor[0, :, : self.size[1], : self.size[0]] = norm.transpose(2, 0, 1)
        self.embeddings = self.encoder.run(None, {"pixel_values": tensor})

    def logits(self, shape, positive, negative):
        height, width = shape
        points = np.array(positive + negative, dtype=np.float32)
        if (
            not positive
            or not np.isfinite(points).all()
            or (points < 0).any()
            or (points >= [width, height]).any()
        ):
            raise ValueError(
                "Prompts must be inside their crop and include a foreground point"
            )
        points *= [self.size[0] / width, self.size[1] / height]
        labels = [1] * len(positive) + [0] * len(negative)
        scores, masks = self.decoder.run(
            None,
            {
                "input_points": points[None, None],
                "input_labels": np.array([[labels]], dtype=np.int64),
                "image_embeddings": self.embeddings[0],
                "image_positional_embeddings": self.embeddings[1],
            },
        )
        for idx in np.argsort(scores[0, 0])[::-1]:
            logits = cv2.resize(masks[0, 0, idx], (1024, 1024))[
                : self.size[1], : self.size[0]
            ]
            yield cv2.resize(logits, (width, height)), float(scores[0, 0, idx])

    def mask(self, shape, positive, negative):
        for logits, score in self.logits(shape, positive, negative):
            selected = prompt_component(logits, positive, negative)
            if selected is not None:
                return selected, score
        return None, None


def prompt_component(logits, positive, negative=(), threshold=0):
    mask = (logits > threshold).astype(np.uint8)
    _, parts = cv2.connectedComponents(mask)
    component = parts[positive[0][1], positive[0][0]]
    if not component or any(parts[y, x] != component for x, y in positive):
        return None
    selected = (parts == component).astype(np.uint8)
    if any(selected[y, x] for x, y in negative):
        return None
    if (
        selected[0].any()
        or selected[-1].any()
        or selected[:, 0].any()
        or selected[:, -1].any()
    ):
        return None
    return selected


def snap_guide(image, guide, band):
    """Anchor the centre and surrounding rough, then find the cut across the edge band."""
    height, width = image.shape[:2]
    points = np.asarray(guide, dtype=np.int32)
    if len(points) < 3 or not Polygon(points).is_valid or not 1 <= band <= 20:
        raise ValueError("Invalid guide polygon or search radius")
    if (points < 0).any() or (points >= [width, height]).any():
        raise ValueError("Guide extends outside crop")
    initial = np.zeros((height, width), np.uint8)
    cv2.fillPoly(initial, [points], 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * band + 1, 2 * band + 1))
    inner = cv2.erode(initial, kernel)
    outer = cv2.dilate(initial, kernel)
    if (
        not inner.any()
        or outer[0].any()
        or outer[-1].any()
        or outer[:, 0].any()
        or outer[:, -1].any()
    ):
        return None
    labels = np.full_like(initial, cv2.GC_BGD)
    labels[outer > 0] = cv2.GC_PR_BGD
    labels[initial > 0] = cv2.GC_PR_FGD
    labels[inner > 0] = cv2.GC_FGD
    cv2.setRNGSeed(7)
    cv2.grabCut(
        image,
        labels,
        None,
        np.zeros((1, 65)),
        np.zeros((1, 65)),
        5,
        cv2.GC_INIT_WITH_MASK,
    )
    return (labels & 1).astype(np.uint8)


def polygon(mask, offset, coordinate_at):
    smooth = (cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 1.35) >= 0.5).astype(
        np.uint8
    )
    if not smooth.any():
        return None
    contours, tree = cv2.findContours(smooth, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    shell = max(
        (i for i in range(len(contours)) if tree[0, i, 3] < 0),
        key=lambda i: cv2.contourArea(contours[i]),
    )

    def ring(idx):
        return [
            coordinate_at(x + offset[0], y + offset[1])
            for x, y in contours[idx].reshape(-1, 2)
        ]

    holes = [
        ring(i)
        for i in range(len(contours))
        if tree[0, i, 3] == shell and cv2.contourArea(contours[i]) > 4
    ]
    if cv2.contourArea(contours[shell]) < 1:
        return None
    area = Polygon(ring(shell), holes)

    # Simplify in pixel space to give the same tolerance in both axes.
    def simplified(idx):
        vertices = cv2.approxPolyDP(contours[idx], 1.1, True).reshape(-1, 2)
        return [coordinate_at(x + offset[0], y + offset[1]) for x, y in vertices]

    small_holes = [
        simplified(i)
        for i in range(len(contours))
        if tree[0, i, 3] == shell and cv2.contourArea(contours[i]) > 4
    ]
    outer = simplified(shell)
    if len(outer) < 3:
        return None
    simple = Polygon(outer, [h for h in small_holes if len(h) >= 3])
    if simple.is_valid and not simple.is_empty:
        return orient(simple, sign=1)
    return orient(area, sign=1) if area.is_valid and not area.is_empty else None


def propose(mosaic, windows, model, boundary=None):
    features, rejected = [], []
    seen = set()
    for window in windows:
        x, y, w, h = window["crop"]
        height, width = mosaic.image.shape[:2]
        if min(x, y) < 0 or min(w, h) < 16 or x + w > width or y + h > height:
            raise ValueError(f"Crop outside the mosaic: {window['crop']}")
        crop = mosaic.image[y : y + h, x : x + w]
        if any("guide" not in p for p in window["prompts"]):
            model.encode(crop)
        for prompt in window["prompts"]:
            name, kind = prompt["id"], prompt["kind"]
            if name in seen or kind not in KINDS:
                raise ValueError(f"Duplicate ID or unsupported kind: {name}, {kind}")
            seen.add(name)
            if "guide" in prompt:
                mask = snap_guide(
                    crop,
                    [(u - x, v - y) for u, v in prompt["guide"]],
                    prompt.get("band", 5),
                )
                method, score = "opencv/grabcut@4.12.0", None
            else:
                pos = [(u - x, v - y) for u, v in prompt["positive"]]
                neg = [(u - x, v - y) for u, v in prompt.get("negative", [])]
                mask, score = model.mask((h, w), pos, neg)
                method = MODEL
            geom = None if mask is None else polygon(mask, (x, y), mosaic.lonlat)
            if geom is not None and boundary is not None:
                # Screen obviously implausible point-prompt masks before review.
                lat = math.radians(geom.centroid.y)
                square_metres = (
                    geom.area * (math.pi * 6378137 / 180) ** 2 * math.cos(lat)
                )
                bounds = {
                    "green": (35, 3200),
                    "tee": (8, 1400),
                    "bunker": (7, 1600),
                    "water": (35, 18000),
                    "fairway": (100, 50000),
                }
                minimum, maximum = bounds[kind]
                if not boundary.covers(geom) or not minimum <= square_metres <= maximum:
                    geom = None
            if geom is None:
                rejected.append(name)
                continue
            properties = {
                "kind": kind,
                "hole": prompt["hole"],
                "model": method,
                "score": score,
                "status": "candidate",
                "source": mosaic.grid["imagery"],
                "capture_date": None,
            }
            features.append(
                {
                    "type": "Feature",
                    "id": name,
                    "properties": properties,
                    "geometry": mapping(geom),
                }
            )
    return {
        "type": "FeatureCollection",
        "features": features,
        "rejected_prompts": rejected,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tiles", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("prompts", type=Path)
    parser.add_argument(
        "--periods", type=Path, help="GSI seamlessphoto_spec GeoJSON footprint tile"
    )
    args = parser.parse_args()
    cv2.setNumThreads(1)
    grid = Mosaic(args.tiles)
    doc = json.loads(args.prompts.read_text())
    if doc["grid"] != [grid.grid[k] for k in ("z", "x0", "y0", "x1", "y1")]:
        raise ValueError("Prompts belong to a different tile grid")
    boundary = shape(doc["boundary"]) if "boundary" in doc else None
    result = propose(grid, doc["windows"], Segmenter(args.model), boundary)
    if args.periods:
        periods = [
            (shape(f["geometry"]), f["properties"].get("撮影年月"))
            for f in json.loads(args.periods.read_text())["features"]
        ]
        for feature in result["features"]:
            geom = shape(feature["geometry"])
            covering = {
                period for footprint, period in periods if footprint.intersects(geom)
            }
            if len(covering) == 1 and any(
                footprint.covers(geom) for footprint, _ in periods
            ):
                period = covering.pop()
                feature["properties"]["gsi_capture_period"] = period
                month = re.fullmatch(r"(\d{4})年(\d{1,2})月", period or "")
                if month:
                    feature["properties"]["capture_month"] = (
                        f"{month[1]}-{int(month[2]):02d}"
                    )
    print(json.dumps(result, allow_nan=False))
