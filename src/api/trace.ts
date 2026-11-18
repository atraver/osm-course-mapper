import type { LngLat } from '../geo/coords';
import type { ShapeKind } from '../data/course';
import { imagerySource } from '../map/imagerySources';

export const POINT_TRACE_ENABLED = import.meta.env.VITE_POINT_TRACE === 'true';
export const TRACE_TOLERANCES = ['tight', 'balanced', 'wide'] as const;
type Tolerance = (typeof TRACE_TOLERANCES)[number];

export interface TraceOutline {
  tolerance: Tolerance;
  rings: LngLat[][];
}

const ZOOM = 18;
const TILE_SIZE = 256;
const WORLD = TILE_SIZE * 2 ** ZOOM;

function imageCrop([lon, lat]: LngLat, size: number) {
  const left = Math.floor((lon + 180) / 360 * WORLD) - size / 2;
  const top = Math.floor((1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) * WORLD / 2) - size / 2;
  return { left, top, size };
}

async function loadCrop({ left, top, size }: ReturnType<typeof imageCrop>, signal: AbortSignal) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('The browser could not prepare the imagery.');
  const template = imagerySource('gsi-seamlessphoto').tiles[0];
  const tiles = [];
  for (let y = Math.floor(top / TILE_SIZE); y <= Math.floor((top + size - 1) / TILE_SIZE); y++) {
    for (let x = Math.floor(left / TILE_SIZE); x <= Math.floor((left + size - 1) / TILE_SIZE); x++) {
      tiles.push((async () => {
        const url = template.replace('{z}', String(ZOOM)).replace('{x}', String(x)).replace('{y}', String(y));
        const response = await fetch(url, { signal, credentials: 'omit' });
        if (!response.ok) throw new Error('GSI imagery is missing around that point.');
        const bitmap = await createImageBitmap(await response.blob());
        try {
          if (bitmap.width !== TILE_SIZE || bitmap.height !== TILE_SIZE) {
            throw new Error('GSI did not return a full imagery tile.');
          }
          ctx.drawImage(bitmap, x * TILE_SIZE - left, y * TILE_SIZE - top);
        } finally {
          bitmap.close();
        }
      })());
    }
  }
  await Promise.all(tiles);
  return canvas.toDataURL('image/jpeg', 0.94).split(',')[1];
}

function outlineFromWire(value: unknown, crop: ReturnType<typeof imageCrop>): TraceOutline {
  const entry = value as { tolerance?: Tolerance; geometry?: {type?: string; coordinates?: unknown[]} } | null;
  if (!entry?.tolerance || !TRACE_TOLERANCES.includes(entry.tolerance) || entry.geometry?.type !== 'Polygon' ||
      !Array.isArray(entry.geometry.coordinates) || !entry.geometry.coordinates.length) {
    throw new Error('The tracer returned an invalid outline.');
  }
  const rings: LngLat[][] = entry.geometry.coordinates.map(ring => {
    if (!Array.isArray(ring) || ring.length < 4 || ring.length > 1200) throw new Error('Invalid traced ring.');
    const positions: LngLat[] = ring.map(point => {
      if (!Array.isArray(point) || point.length !== 2 ||
          !point.every(n => Number.isFinite(n) && n >= 0 && n < crop.size)) throw new Error('Invalid traced vertex.');
      const [x, y] = point;
      return [(crop.left + x + 0.5) / WORLD * 360 - 180,
        Math.atan(Math.sinh(Math.PI * (1 - 2 * (crop.top + y + 0.5) / WORLD))) * 180 / Math.PI];
    });
    const first = positions[0], last = positions[positions.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) throw new Error('Traced ring is open.');
    return positions.slice(0, -1);
  });
  return { tolerance: entry.tolerance, rings };
}

export async function requestTrace(kind: ShapeKind, point: LngLat, signal: AbortSignal) {
  const crop = imageCrop(point, kind === 'fairway' || kind === 'hazard' ? 768 : 384);
  const image = await loadCrop(crop, signal);
  const response = await fetch('/v1/trace', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, image }), signal,
  });
  const result = await response.json().catch(() => null);
  if (!response.ok || typeof result?.model !== 'string' || !Array.isArray(result?.options)) {
    throw new Error(result?.message || 'The imagery tracer is unavailable.');
  }
  const options = result.options.map((item: unknown) => outlineFromWire(item, crop)) as TraceOutline[];
  if (!options.some(option => option.tolerance === 'balanced')) throw new Error('No closed outline found.');
  return {
    options,
    provenance: {
      acquired: null,
      gsdMeters: 40075016.68557849 * Math.cos(point[1] * Math.PI / 180) / WORLD,
      source: 'GSImaps/seamlessphoto',
      modelId: result.model as string,
      itemId: `z${ZOOM}/px${crop.left},${crop.top}/${crop.size}`,
    },
  };
}
