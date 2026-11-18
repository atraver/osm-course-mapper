import type { Position } from 'geojson';
import type { SavedHole } from '../api/holes';

const tagsByKind = {
  tee: ['golf', 'tee'],
  green: ['golf', 'green'],
  fairway: ['golf', 'fairway'],
  bunker: ['golf', 'bunker'],
  water: ['natural', 'water'],
  trees: ['natural', 'wood'],
} as const;

function samePosition(a: Position, b: Position): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

function validPosition([lon, lat]: Position): boolean {
  return Number.isFinite(lon) && Math.abs(lon) <= 180 && Number.isFinite(lat) && Math.abs(lat) <= 90;
}

/**
 * An upload-blocked JOSM layer of new features retained in a saved review. Never invent
 * versions for existing OSM objects or translate ambiguous hazard tags.
 */
export function josmDraft(hole: SavedHole): string | null {
  let nextId = -1;
  const nodes: string[] = [];
  const ways: string[] = [];
  const relations: string[] = [];
  const tagLines = (tags: Record<string, string>) =>
    Object.entries(tags).map(([key, value]) => `    <tag k="${key}" v="${value}" />`);
  const openWay = (points: Position[], closed: boolean): Position[] | null => {
    if (points.length > 2000 || !points.every(validPosition)) return null;
    const open = closed && points.length > 0 && samePosition(points[0], points[points.length - 1])
      ? points.slice(0, -1)
      : points;
    return new Set(open.map(([lon, lat]) => `${lon},${lat}`)).size >= (closed ? 3 : 2) ? open : null;
  };
  const addWay = (points: Position[], closed: boolean, tags: Record<string, string>) => {
    const ids = points.map(([lon, lat]) => {
      const id = nextId--;
      nodes.push(`  <node id="${id}" lat="${lat}" lon="${lon}" />`);
      return id;
    });
    if (closed) ids.push(ids[0]);
    const wayId = nextId--;
    ways.push([
      `  <way id="${wayId}">`,
      ...ids.map(id => `    <nd ref="${id}" />`),
      ...tagLines(tags),
      '  </way>',
    ].join('\n'));
    return wayId;
  };

  if (hole.lineSource === 'drawn' && !hole.osmHoleId && Number.isInteger(hole.holeNumber) && hole.holeNumber > 0) {
    const tags = { golf: 'hole', ref: String(hole.holeNumber) };
    const line = openWay(hole.playingLine.coordinates, false);
    if (line) addWay(line, false, tags);
  }
  for (const feature of hole.features) {
    if (feature.origin === 'osm' || feature.osmAction !== 'create' || feature.osmId ||
        feature.geometry.type !== 'Polygon') continue;
    const kind = feature.kind;
    if (kind === 'waste_area' || kind === 'native_area' || kind === 'other') continue;
    const rings = feature.geometry.coordinates.map(ring => openWay(ring, true));
    if (rings.length === 0 || rings.some(ring => ring === null)) continue;
    const [key, value] = tagsByKind[kind];
    const tags: Record<string, string> = { [key]: value };
    if (feature.osmTags.source === 'GSImaps/seamlessphoto') tags.source = feature.osmTags.source;
    if (rings.length === 1) {
      addWay(rings[0]!, true, tags);
    } else {
      const members = rings.map((ring, index) => {
        const wayId = addWay(ring!, true, {});
        return `    <member type="way" ref="${wayId}" role="${index === 0 ? 'outer' : 'inner'}" />`;
      });
      relations.push([
        `  <relation id="${nextId--}">`,
        ...members,
        ...tagLines({ type: 'multipolygon', ...tags }),
        '  </relation>',
      ].join('\n'));
    }
  }
  if (ways.length === 0) return null;
  return ['<?xml version="1.0" encoding="UTF-8"?>',
    '<osm version="0.6" generator="OSM Course Mapper" upload="never" download="never">',
    ...nodes, ...ways, ...relations, '</osm>', ''].join('\n');
}
