#!/bin/sh
# Prepare a local review directory from a GSI-covered course polygon.
set -eu
if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "Usage: $0 boundary.geojson new-output-directory [numbered-lines.geojson]" >&2
    exit 2
fi
tool_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
boundary=$1
out=$2
mkdir "$out"
out=$(CDPATH='' cd -- "$out" && pwd)
mkdir -p "$out/tiles" "$out/model" "$out/site"
cp -- "$boundary" "$out/boundary.geojson"
if [ "$#" = 3 ]; then cp -- "$3" "$out/lines.geojson"; fi

python3 - "$tool_dir" "$out" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from fetch import fetch
folder=Path(sys.argv[2])
g=json.loads((folder/"boundary.geojson").read_text())
if g["type"]=="Polygon": polys=[g["coordinates"]]
elif g["type"]=="MultiPolygon": polys=g["coordinates"]
else: raise ValueError("Expected a WGS84 Polygon or MultiPolygon geometry")
points=[pt for poly in polys for pt in poly[0]]
lons,lats=zip(*points)
fetch((min(lons),min(lats),max(lons),max(lats)),folder/"tiles")
PY

revision=5850ab45f587c112167512ffef949107115e26a0
for name in vision_encoder_quantized prompt_encoder_mask_decoder_quantized; do
    curl --fail --location --retry 2 --silent --show-error \
        "https://huggingface.co/Xenova/slimsam-77-uniform/resolve/$revision/onnx/$name.onnx" \
        -o "$out/model/$name.onnx"
done
docker build -t golf-imagery-review:slimsam "$tool_dir"
run() {
    docker run --rm --network none --read-only --cap-drop ALL \
        --security-opt no-new-privileges --memory 4g --cpus 2 --pids-limit 64 \
        --mount "type=bind,src=$out,dst=/data,readonly" --entrypoint python golf-imagery-review:slimsam "$@"
}
set -- /tool/discover.py /data/tiles /data/boundary.geojson
if [ -f "$out/lines.geojson" ]; then set -- "$@" --lines /data/lines.geojson; fi
run "$@" > "$out/prompts.json"
run /tool/propose.py /data/tiles /data/model /data/prompts.json --periods /data/tiles/capture-periods.geojson > "$out/candidates.geojson"
run /tool/screen.py /data/tiles /data/candidates.geojson > "$out/queue.geojson"
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" --memory 600m --cpus 1 --pids-limit 40 \
    --mount "type=bind,src=$out,dst=/data,readonly" \
    --mount "type=bind,src=$out/site,dst=/out" --entrypoint python golf-imagery-review:slimsam \
    /tool/bundle.py /data/tiles /data/queue.geojson /out
echo "Review site: $out/site"
