"""Point-prompt inference behind the mapper's same-origin relay."""

import base64
import binascii
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

import cv2
import numpy as np
from shapely.geometry import Point, mapping

from propose import MODEL, Segmenter, polygon, prompt_component

# The larger window gives fairways and water more context than tee boxes and greens.
SIZES = {"tee": 384, "green": 384, "fairway": 768, "bunker": 384, "hazard": 768}
MAX_BODY = 1024 * 1024


def trace(model, image, seed):
    model.encode(image)
    for logits, _ in model.logits(image.shape[:2], [seed], []):
        options = []
        for name, threshold in (("tight", 1.4), ("balanced", 0), ("wide", -1.4)):
            mask = prompt_component(logits, [seed], threshold=threshold)
            if mask is None:
                continue
            area = polygon(mask, (0, 0), lambda x, y: (int(x), int(y)))
            if area is None or not area.covers(Point(*seed)) or area.area < 16:
                continue
            if (
                sum(len(ring.coords) for ring in [area.exterior, *area.interiors])
                > 1200
            ):
                continue
            options.append({"tolerance": name, "geometry": mapping(area)})
        if any(option["tolerance"] == "balanced" for option in options):
            return options
    return []


def decode(body):
    kind = body["kind"]
    size = SIZES.get(kind)
    if size is None:
        raise ValueError
    # The client crops exactly around the selected point, at native GSI resolution.
    seed = size // 2
    jpeg = base64.b64decode(body["image"], validate=True)
    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise ValueError
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape != (size, size, 3):
        raise ValueError
    return image, (seed, seed)


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, **body):
        data = json.dumps(body, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/v1/trace":
            return self.reply(404, message="Unknown trace endpoint.")
        if not self.server.slot.acquire(blocking=False):
            return self.reply(503, message="The tracer is busy. Try again in a moment.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                return self.reply(
                    413, message="The imagery crop exceeds the trace limit."
                )
            image, seed = decode(json.loads(self.rfile.read(length)))
        except (
            ValueError,
            TypeError,
            KeyError,
            binascii.Error,
            cv2.error,
            TimeoutError,
        ):
            return self.reply(400, message="The tracer needs a native imagery crop.")
        else:
            try:
                options = trace(self.server.model, image, seed)
            except Exception:
                self.log_error("Model inference failed")
                return self.reply(
                    500,
                    message="The outline could not be traced. Try again or edit the shape by hand.",
                )
            if not options:
                return self.reply(
                    422,
                    message="No closed outline found. Click farther inside the feature or use the manual editor.",
                )
            return self.reply(200, model=MODEL, options=options)
        finally:
            self.server.slot.release()


class Server(ThreadingHTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(12)
        return connection, address


if __name__ == "__main__":
    cv2.setNumThreads(1)
    server = Server(("0.0.0.0", 8081), Handler)
    server.model = Segmenter(Path("/model"))
    server.slot = threading.Lock()
    server.serve_forever()
