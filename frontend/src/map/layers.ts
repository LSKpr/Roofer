import type {
  CircleLayerSpecification,
  ExpressionSpecification,
  FillLayerSpecification,
  FilterSpecification,
  LayerSpecification,
  LineLayerSpecification,
  SourceSpecification,
} from 'maplibre-gl'
import { TILES_URL } from '../api/client'

export const SOURCE_ID = 'roofer'

/** Nazwy warstw w kaflu ustawia backend (`app/tiles.py`): poligony i centroidy zgloszonych. */
export const POLYGON_SOURCE_LAYER = 'buildings'
export const POINT_SOURCE_LAYER = 'listed'

export const POLYGON_MIN_ZOOM = 14
export const POINT_MIN_ZOOM = 8

/**
 * Backend nie generuje kafli powyzej 16, wiec MapLibre ma nadprobkowac kafel z 16.
 * Geometria jest wektorowa, wiec przy wiekszym zoomie zostaje ostra.
 */
export const SOURCE_MAX_ZOOM = 16

/**
 * Te same hexy co tokeny `--color-listed` i `--color-not-listed` w index.css. MapLibre nie czyta
 * zmiennych CSS, wiec kolory mapy musza byc tu zdublowane — zmieniajac jedno, zmien drugie.
 *
 * Czerwony = zgloszony w rejestrze, szary = niezgloszony. Szary, nie zielony, bo brak wpisu
 * w rejestrze nie jest dowodem czystego dachu — zielony sugerowalby, ze budynek jest sprawdzony.
 */
export const STATUS_COLORS = {
  listed: '#C8102E',
  notListed: '#9AA5AD',
}

/** Kolor akcentu interfejsu (`--color-accent`): wybor to stan interfejsu, nie cecha danych. */
export const SELECTED_COLOR = '#2251FF'

/**
 * Niezgloszone budynki sa tlem, a nie wynikiem: sa tylko obwiedzione i lekko przygaszone, zeby
 * czerwien zgloszonych czytalo sie od razu. Na ortofoto pelne wypelnienie zakryloby dach.
 */
export const FILL_OPACITY: ExpressionSpecification = ['case', ['get', 'listed'], 0.62, 0.22]

export const buildingsSource: SourceSpecification = {
  type: 'vector',
  tiles: [TILES_URL],
  minzoom: POINT_MIN_ZOOM,
  maxzoom: SOURCE_MAX_ZOOM,
}

export const LAYER_IDS = {
  fill: 'roofer-buildings-fill',
  outline: 'roofer-buildings-outline',
  points: 'roofer-listed-points',
  selectedFill: 'roofer-selected-fill',
  selectedOutline: 'roofer-selected-outline',
}

/** `listed` jest atrybutem kafla, wiec kolor liczy sie po stronie GPU, bez osobnych warstw. */
export const statusColor: ExpressionSpecification = [
  'case',
  ['get', 'listed'],
  STATUS_COLORS.listed,
  STATUS_COLORS.notListed,
]

/**
 * Identyfikator obiektu w MVT nie jest atrybutem — ST_AsMVT zapisuje go w polu `id` kafla,
 * wiec `['get', 'id']` zwrocilby null. Dostep daje tylko wyrazenie `['id']`.
 * Dla braku wyboru zwracamy `false`: filtr poprawny w skladni wyrazen, ktory nie przepuszcza nic.
 */
export function selectedFilter(id: number | null): FilterSpecification {
  if (id === null) return false
  return ['==', ['id'], id]
}

export const buildingsFillLayer: FillLayerSpecification = {
  id: LAYER_IDS.fill,
  type: 'fill',
  source: SOURCE_ID,
  'source-layer': POLYGON_SOURCE_LAYER,
  minzoom: POLYGON_MIN_ZOOM,
  paint: {
    'fill-color': statusColor,
    'fill-opacity': FILL_OPACITY,
  },
}

export const buildingsOutlineLayer: LineLayerSpecification = {
  id: LAYER_IDS.outline,
  type: 'line',
  source: SOURCE_ID,
  'source-layer': POLYGON_SOURCE_LAYER,
  minzoom: POLYGON_MIN_ZOOM,
  paint: {
    'line-color': statusColor,
    // Wlosowa linia jak w interfejsie; zgloszone dostaja wyrazniejszy obrys.
    'line-width': ['case', ['get', 'listed'], 1.2, 0.7],
  },
}

export const listedPointsLayer: CircleLayerSpecification = {
  id: LAYER_IDS.points,
  type: 'circle',
  source: SOURCE_ID,
  'source-layer': POINT_SOURCE_LAYER,
  minzoom: POINT_MIN_ZOOM,
  // Od POLYGON_MIN_ZOOM kafel ma juz obrysy, a nie centroidy.
  maxzoom: POLYGON_MIN_ZOOM,
  paint: {
    'circle-radius': ['interpolate', ['linear'], ['zoom'], POINT_MIN_ZOOM, 2, POLYGON_MIN_ZOOM, 6],
    'circle-color': STATUS_COLORS.listed,
    'circle-opacity': 0.8,
    // Obwodka trzyma kontrast na jasnym podkladzie.
    'circle-stroke-color': '#FFFFFF',
    'circle-stroke-width': 0.8,
  },
}

export const selectedFillLayer: FillLayerSpecification = {
  id: LAYER_IDS.selectedFill,
  type: 'fill',
  source: SOURCE_ID,
  'source-layer': POLYGON_SOURCE_LAYER,
  minzoom: POLYGON_MIN_ZOOM,
  filter: selectedFilter(null),
  paint: {
    'fill-color': SELECTED_COLOR,
    'fill-opacity': 0.45,
  },
}

export const selectedOutlineLayer: LineLayerSpecification = {
  id: LAYER_IDS.selectedOutline,
  type: 'line',
  source: SOURCE_ID,
  'source-layer': POLYGON_SOURCE_LAYER,
  minzoom: POLYGON_MIN_ZOOM,
  filter: selectedFilter(null),
  paint: {
    'line-color': SELECTED_COLOR,
    'line-width': 2.5,
  },
}

/** Kolejnosc dodawania do mapy: wypelnienie, obrys, punkty, podswietlenie na wierzchu. */
export const MAP_LAYERS: LayerSpecification[] = [
  buildingsFillLayer,
  buildingsOutlineLayer,
  listedPointsLayer,
  selectedFillLayer,
  selectedOutlineLayer,
]

/** Warstwy podswietlenia nie sa klikalne — klik ma trafiac w budynek pod spodem. */
export const CLICKABLE_LAYER_IDS: string[] = [LAYER_IDS.fill, LAYER_IDS.points]
export const HIGHLIGHT_LAYER_IDS: string[] = [LAYER_IDS.selectedFill, LAYER_IDS.selectedOutline]
