# Local course imagery review

Generate WGS84 draft polygons from a course boundary, inspect them over the source imagery and export the ones to investigate in JOSM. This tool uses GSI seamless aerial photography in Japan. The image encoder and decoder run on a CPU inside a networkless container.

## Run a course

Supply a GeoJSON **geometry** in longitude, latitude order. An optional FeatureCollection of LineStrings must identify each physical hole with an integer `properties.hole`. Use the best known playing lines. Their first and last nodes seed possible tee and green outlines. Tee names and penalty-area rules require separate evidence.

```sh
./run.sh boundary.geojson new-course-review numbered-lines.geojson
python3 -m http.server 41740 --bind 127.0.0.1 --directory new-course-review/site
```

Open the local server in a browser. **Next pending** zooms to a candidate. Filter by feature, zoom or drag to pan, and use **Keep** or **Skip**. **Export kept GeoJSON** downloads the selection with its source and model metadata. Decisions are stored in this browser for this dataset. The GeoJSON can be opened as a separate JOSM layer to reconcile with a fresh download of OSM data. Course Mapper drafts and Golf app bundles have separate review and save steps.

The runner fetches the imagery and two pinned ONNX files, builds the Docker image, then performs inference offline. Use a new output directory to preserve earlier work. The container checks both weights against their published SHA-256 digests. The source tile grid and exact model revision are retained for reproducing a run. The default fetch is bounded to 144 zoom-18 tiles. Split larger courses into overlapping grids and reconcile repeated objects. Other countries require an imagery source suitable for OSM tracing and a matching georeferencing adapter.

## Processing stages

- `fetch.py` caches the original GSI JPEG tiles with their XYZ indices. Zooming in beyond the native tiles does not add ground detail. Check capture periods using GSI’s metadata layer.
- `discover.py` uses image colour and connected regions to place prompts on possible sand and water. Known playing lines add turf prompts. Physical feature ownership stays open when it cannot be established from the line.
- `propose.py` encodes overlapping imagery windows with quantized SlimSAM. It selects connected masks consistent with foreground/background clicks and rejects masks truncated by the crop. For a manually refined prompt, supply a rough `guide` polygon and a `band` in pixels to fit the edge with GrabCut. This option has no model confidence score. Use `--periods FOOTPRINT.geojson` for the applicable GSI seamlessphoto_spec footprint tile. The output distinguishes a known month from an exact date.
- `screen.py` filters obvious shadows and paths using the material across a candidate, then collapses similar outlines. These conservative colour rules were tried on one Hokkaido course. Dark water, pale turf, tree shadows, small bunkers and grass varieties at another site can produce missed features and false positives.
- `bundle.py` accepts `--reference EXISTING.geojson` and removes from the queue same-kind outlines that overlap a reference polygon by at least 50% intersection over union. Supply reviewed or existing polygons with `properties.kind` and optionally playing lines. Inspect shared greens and fairways as physical objects across holes.

The prompts file records its tile grid and uses pixel coordinates measured from the mosaic’s upper-left pixel centre. Each window has `crop: [left, top, width, height]` and a list of prompts. Each prompt has a unique ID, kind, optional hole association (null if unknown), and positive points with optional negative points, or an edge guide. A networkless container can rerun that file deterministically for the same inputs. Raw mask scores are model estimates of overlap and can slightly exceed one. They do not measure yardage accuracy.

Sources: [GSI imagery catalogue](https://maps.gsi.go.jp/development/ichiran.html), [GSI capture-period guide](https://maps.gsi.go.jp/legend/seamlessphoto.pdf), [SlimSAM model](https://huggingface.co/Xenova/slimsam-77-uniform), [SlimSAM research](https://github.com/czg1225/SlimSAM).

## Click-to-trace in Course Mapper

Run `trace_server.py` in the imagery-review image on a private network with the
same checksum-verified weights mounted read-only at `/model`. Override the image
entrypoint with `python /tool/trace_server.py`. The service listens on port
8081. Route only `POST /v1/trace` from the mapper's origin to this service and
allow up to 50 seconds for cold CPU inference. Keep the tracer off public
ingress and give it 4 GiB of memory. Build the web app with
`VITE_POINT_TRACE=true` to enable the button for GSI imagery.

In the hole review, choose **Trace outline from imagery** and click inside the
visible feature. Try **Tighter**, **Balanced** or **Wider** before moving
vertices. The options adjust the threshold on one image mask and require a
closed outline around the click. **Choose another point** starts a fresh trace.
Select the hazard type before keeping a hazard. Use **Save current draft**
to store the hole, then **Download JOSM review draft** for reconciliation.
Large or faint features can exceed the trace window or need manual editing.

The browser assembles native zoom-18 tiles from GSI and sends a JPEG crop to
the local point service. The server returns crop-space rings and the browser
projects them to longitude and latitude. It retains the GSI source and model
revision in the saved feature record. If the exact imagery acquisition date is
unavailable, the saved date is null. A polygon is imagery evidence for review
in JOSM. Water and wood exports describe visible land cover. Designating a
penalty area requires evidence of its markings.
