import { expect, it } from 'vitest'
import { OSM_TILES, basemapStyle } from './basemap'

it('uses the documented OpenStreetMap tile endpoint', () => {
  const source = basemapStyle.sources.osm
  expect(source.type).toBe('raster')
  expect(source.type === 'raster' && source.tiles).toEqual([OSM_TILES])
})

it('keeps the attribution that the tile usage policy requires', () => {
  const source = basemapStyle.sources.osm
  expect(source.type === 'raster' && source.attribution).toContain('OpenStreetMap')
})

it('has no layer pointing at a source that does not exist', () => {
  const declared = Object.keys(basemapStyle.sources)
  const referenced = basemapStyle.layers.flatMap((layer) => ('source' in layer && layer.source ? [layer.source] : []))

  expect(referenced.length).toBeGreaterThan(0)
  for (const source of referenced) expect(declared).toContain(source)
})
