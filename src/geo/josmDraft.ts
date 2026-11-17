import type { Position } from 'geojson';
import type { SavedHole } from '../api/holes';

const tagsByKind = {
  tee: ['golf', 'tee'],
  green: ['golf', 'green'],
  fairway: ['golf', 'fairway'],
  bunker: ['golf', 'bunker'],
} as const;

function samePosition(a: Position, b: Position): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

function validPosition([lon, lat]: Position): boolean {
  return Number.isFinite(lon) && Math.abs(lon) <= 180 && Number.isFinite(lat) && Math.abs(lat) <= 90;
}

/**
 * An upload-blocked JOSM layer of new, manually drawn features. Never invent
 * versions for existing OSM objects or translate ambiguous hazard tags.
 */
export function josmDraft(hole: SavedHole): string | null {
  let nextId = -1;
  const nodes: string[] = [];
  const ways: string[] = [];
  const addWay = (points: Position[], closed: boolean, tags: Record<string, string>) => {
    if (!points.every(validPosition) || points.length > 2000) return;
    const open = closed && points.length > 0 && samePosition(points[0], points[points.length - 1])
      ? points.slice(0, -1)
      : points;
    if (new Set(open.map(([lon, lat]) => `${lon},${lat}`)).size < (closed ? 3 : 2)) return;
    const ids = open.map(([lon, lat]) => {
      const id = nextId--;
      nodes.push(`  <node id="${id}" lat="${lat}" lon="${lon}" />`);
      return id;
    });
    if (closed) ids.push(ids[0]);
    ways.push([
      `  <way id="${nextId--}">`,
      ...ids.map(id => `    <nd ref="${id}" />`),
      ...Object.entries(tags).map(([key, value]) => `    <tag k="${key}" v="${value}" />`),
      '  </way>',
    ].join('\n'));
  };

  if (hole.lineSource === 'drawn' && !hole.osmHoleId && Number.isInteger(hole.holeNumber) && hole.holeNumber > 0) {
    const tags = { golf: 'hole', ref: String(hole.holeNumber) };
    addWay(hole.playingLine.coordinates, false, tags);
  }
  for (const feature of hole.features) {
    if (feature.origin !== 'drawn' || feature.osmAction !== 'create' || feature.osmId ||
      feature.geometry.type !== 'Polygon' || feature.geometry.coordinates.length !== 1) continue;
    switch (feature.kind) {
      case 'tee':
      case 'green':
      case 'fairway':
      case 'bunker': {
        const [key, value] = tagsByKind[feature.kind];
        addWay(feature.geometry.coordinates[0], true, { [key]: value });
      }
    }
  }
  if (ways.length === 0) return null;
  return ['<?xml version="1.0" encoding="UTF-8"?>',
    '<osm version="0.6" generator="OSM Course Mapper" upload="never" download="never">',
    ...nodes, ...ways, '</osm>', ''].join('\n');
}
