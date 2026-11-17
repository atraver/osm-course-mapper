import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

it('finds a Japanese physical layout by alias and reopens its stable local ID', async () => {
  vi.stubEnv('VITE_LOCAL_COURSE_CATALOG', 'true');
  const local = {
    id: 'local:example-north',
    course_name: 'Example North',
    aliases: ['例カントリー 北', 'Ｅｘａｍｐｌｅ'],
    country: 'JP',
    latitude: 41.8,
    longitude: 140.6,
    holes: 9,
    osm_id: 'way/123',
  };
  const fetch = vi.fn(async () => new Response(JSON.stringify({ courses: [
    local, { ...local, id: 'local:ambiguous', holes: undefined },
  ] })));
  vi.stubGlobal('fetch', fetch);
  const { searchCourses, getCourse } = await import('./opengolf');
  for (const query of ['例カントリー北', 'example']) {
    const result = await searchCourses(query);
    expect(result.status === 'ok' && result.data.map(course => course.id)).toEqual([local.id]);
  }
  const detail = await getCourse(local.id);
  expect(detail).toMatchObject({ status: 'ok', data: { country: 'JP', holes: 9, osmCourseId: 'way/123' } });
  expect(fetch.mock.calls).toHaveLength(3);
  expect(fetch).toHaveBeenCalledWith('/course-catalog.json', expect.any(Object));
});
