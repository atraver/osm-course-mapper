// @vitest-environment jsdom
import { expect, it } from 'vitest';
import type { SavedFeature, SavedHole } from '../api/holes';
import { josmDraft } from './josmDraft';

const tee: SavedFeature = {
  kind: 'tee', origin: 'drawn', osmId: null, osmAction: 'create',
  geometry: { type: 'Polygon', coordinates: [[[140, 41], [140.1, 41], [140.1, 41.1], [140, 41]]] },
  edited: false, teeSets: [], label: null, osmTags: { source: 'GSImaps/seamlessphoto' }, proposal: null,
};
const hole: SavedHole = {
  courseId: 'local:north', holeNumber: 3, par: 4, lineSource: 'drawn', osmHoleId: null,
  playingLine: { type: 'LineString', coordinates: [[140, 41], [140.1, 41.1]] },
  features: [tee, { ...tee, kind: 'green', origin: 'osm', osmId: 'way/123', osmAction: 'modify' }],
};

it('writes valid XML for new manual features and closes rings without sharing nodes with the line', () => {
  const xml = new DOMParser().parseFromString(josmDraft(hole) ?? '', 'text/xml');
  expect(xml.documentElement.tagName).toBe('osm');
  expect(xml.documentElement.getAttribute('upload')).toBe('never');
  expect(xml.querySelectorAll('node')).toHaveLength(5);
  const [line, area] = [...xml.querySelectorAll('way')];
  const refs = (way: Element) => [...way.querySelectorAll('nd')].map(node => node.getAttribute('ref'));
  expect(line.querySelector('tag[k="ref"]')?.getAttribute('v')).toBe('3');
  expect(area.querySelector('tag[k="golf"]')?.getAttribute('v')).toBe('tee');
  expect(area.querySelector('tag[k="source"]')?.getAttribute('v')).toBe('GSImaps/seamlessphoto');
  const ring = refs(area);
  expect(ring[0]).toBe(ring[3]);
  expect(refs(line).some(ref => ring.includes(ref))).toBe(false);
  expect(xml.querySelector('tag[v="green"]')).toBeNull();
  expect(josmDraft({ ...hole, lineSource: 'osm', osmHoleId: 'way/5', features: [hole.features[1]] })).toBeNull();
});

it('exports saved model-assisted outlines into the upload-blocked review layer', () => {
  const modelGreen: SavedFeature = {
    ...tee, kind: 'green', origin: 'proposed',
    proposal: { confidence: null, provenance: {
      acquired: '2017-06', gsdMeters: 0.45, source: 'GSImaps/seamlessphoto',
      modelId: 'opencv/grabcut', itemId: 'example',
    } },
  };
  const text = josmDraft({ ...hole, lineSource: 'osm_edited', features: [modelGreen] });
  const xml = new DOMParser().parseFromString(text!, 'text/xml');
  expect(xml.documentElement.getAttribute('upload')).toBe('never');
  expect(xml.querySelectorAll('way')).toHaveLength(1);
  expect(xml.querySelector('tag[k="golf"]')?.getAttribute('v')).toBe('green');
});
