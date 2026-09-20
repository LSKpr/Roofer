import type {
  ExpressionSpecification,
  FillLayerSpecification,
  FilterSpecification,
  HeatmapLayerSpecification,
  LayerSpecification,
  LineLayerSpecification,
  SourceSpecification,
} from 'maplibre-gl'
import { TILES_URL } from '../api/client'

export const SOURCE_ID = 'roofer'

/**
 * Nazwy warstw w kaflu ustawia backend (`app/tiles.py`): od zoomu 14 obrysy budynkow,
 * nizej siatka zageszczenia zgloszonych. Kazda nazwa stoi tu raz — MapLibre odrzuca warstwe
 * z nieistniejacym `source-layer` po cichu, wiec literowka nie zglosilaby sie bledem.
 */
export const POLYGON_SOURCE_LAYER = 'buildings'
export const DENSITY_SOURCE_LAYER = 'listed_density'

/**
 * Atrybut komorki siatki: liczba zgloszonych budynkow, ktore do niej wpadly. Komorka nie ma
 * identyfikatora, bo nie jest budynkiem — dlatego nie ma jej w `CLICKABLE_LAYER_IDS`.
 */
export const DENSITY_COUNT_PROPERTY = 'count'

export const POLYGON_MIN_ZOOM = 14
/** Nizej kafel nie niesie nic; nazwa zostaje, bo czyta ja `ZoomHint`. */
export const POINT_MIN_ZOOM = 8
/**
 * Ostatni zoom, na ktorym widac cieplo. `maxzoom` warstwy w MapLibre jest granica wylaczna,
 * wiec sama warstwa dostaje `POLYGON_MIN_ZOOM`, a interpolacje po zoomie koncza sie tutaj.
 */
export const DENSITY_MAX_ZOOM = POLYGON_MIN_ZOOM - 1

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
  listed: '#c8102e',
  notListed: '#9aa5ad',
}

/** Kolor akcentu interfejsu (`--color-accent`): wybor to stan interfejsu, nie cecha danych. */
export const SELECTED_COLOR = '#2251ff'

/**
 * Prog nasycenia wagi heatmapy: od tylu zgloszen w jednej komorce cieplo juz nie rosnie.
 *
 * Skad 40. Backend tnie kazdy kafel na 64×64 komorki (`DENSITY_GRID` w `app/tiles.py`), wiec
 * komorka ma staly rozmiar na ekranie (8 px przy kaflu 512 px), ale w terenie kurczy sie
 * czterokrotnie na kazdy zoom: na szerokosci 52° to ok. 1,5 km boku przy z8 i ok. 47 m przy z13.
 * Tyle samo razy spada liczba zgloszen w komorce. W najgestszym fragmencie wojewodztwa (AGENTS.md:
 * 341 zgloszonych w komorce 0,01°, czyli ok. 440 na km²) wychodzi z tego rzad wielkosci 1000
 * zgloszen na komorke przy z8, ok. 60 przy z10, ok. 16 przy z11 i pojedyncze sztuki przy z13.
 *
 * 40 celuje w srodek tego zakresu (z10–z11), bo tam `count` naprawde rozroznia komorki. Cena jest
 * znana i przyjeta swiadomie: przy z8 wiekszosc zamieszkanych komorek przekroczy prog i zrowna sie
 * na wadze 1 — kontrast niesie wtedy liczba niepustych komorek, nie ich zawartosc — a przy z13
 * prawie kazda komorka ma jedno zgloszenie i siedzi na `HEATMAP_MIN_WEIGHT`.
 *
 * WARTOSC DO KALIBRACJI NA ZYWEJ MAPIE, nie pomiar. Jesli przy z8 cale wojewodztwo bedzie plaska
 * czerwienia, jedna liczba nie wystarczy i prog musi zalezec od zoomu: `interpolate` po `['zoom']`,
 * w ktorego przystankach siedza osobne `interpolate` po `['get', 'count']`. Nie robimy tego z gory,
 * bo bez ogladu prawdziwych `count` dobieralibysmy piec liczb na oko zamiast jednej.
 */
export const HEATMAP_SATURATION_COUNT = 40

/**
 * Waga najrzadszej komorki. Nie zero: komorka z jednym zgloszeniem ma byc widoczna, bo „jedno
 * zgloszenie" i „zero zgloszen" to w tej mapie dwie rozne informacje — a przy z13 wlasnie takich
 * komorek jest najwiecej.
 */
export const HEATMAP_MIN_WEIGHT = 0.15

/**
 * Rampa ciepla. Pierwszy przystanek MUSI byc calkowicie przezroczysty, inaczej MapLibre pokrywa
 * kolorem cala mape — gestosc 0 jest wszedzie tam, gdzie nikt nic nie zglosil. Jest to ta sama
 * czerwien co koniec rampy, tylko z alfa 0: inny odcien przebijalby na brzegach plam.
 *
 * Dalej same odbarwione warianty czerwieni rejestru, az do `STATUS_COLORS.listed`. Zieleni ani
 * niebieskiego tu nie ma i byc nie moze: w tym projekcie kolor niesie znaczenie, a zielone
 * „chlodne" konce klasycznych ramp czytaloby sie jako „tu jest czysto", czego nie wiemy.
 */
export const HEATMAP_RAMP: Array<[number, string]> = [
  [0, 'rgba(200, 16, 46, 0)'],
  [0.2, '#f6ded9'],
  [0.45, '#e8ada2'],
  [0.7, '#d9736b'],
  [1, STATUS_COLORS.listed],
]

/**
 * Widoczne przystanki rampy, od najslabszego do najmocniejszego — probka w legendzie bierze
 * kolory stad, zeby nie mogla rozjechac sie z mapa. Zerowy przystanek jest przezroczysty,
 * wiec w pasku legendy bylby po prostu bialym kwadratem.
 */
export const HEATMAP_RAMP_COLORS: string[] = HEATMAP_RAMP.slice(1).map(([, color]) => color)

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

/** Kolejnosc kluczy jest kolejnoscia dokladania warstw do mapy — obrysy musza byc nad cieplem. */
export const LAYER_IDS = {
  density: 'roofer-listed-density',
  fill: 'roofer-buildings-fill',
  outline: 'roofer-buildings-outline',
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

/**
 * Cala tresc agregacji: komorka z 40 zgloszeniami ma wazyc wiecej niz komorka z jednym.
 * Bez tego heatmapa liczylaby komorki, a nie zgloszenia, i rzadka zabudowa o duzej liczbie
 * komorek wygladalaby jak skupisko.
 */
export const heatmapWeight: ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['get', DENSITY_COUNT_PROPERTY],
  1,
  HEATMAP_MIN_WEIGHT,
  HEATMAP_SATURATION_COUNT,
  1,
]

/** `heatmap-density` to znormalizowane 0–1, wiec rampa jest niezalezna od progu wagi. */
export const heatmapColor: ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['heatmap-density'],
  ...HEATMAP_RAMP.flat(),
]

/**
 * Warstwa gestosci zamiast punktow: przy z8 kafel z centroidami wazyl 815 KB i liczyl sie 1,1 s
 * (319 869 zgloszonych budynkow), a i tak nie dalo sie z niego nic odczytac poza czerwona plama.
 *
 * Promien i intensywnosc rosna z zoomem, ale nie dlatego, ze komorka rosnie na ekranie — ta ma
 * stale 8 px. Zmienia sie to, co w niej siedzi: przy z8 niepusta jest niemal kazda komorka wokol,
 * wiec w jeden promien wpada gesty dywan wag i suma szybko dochodzi do maksimum rampy — starczy
 * waski promien i maly mnoznik. Przy z13 niepuste komorki sa rzadkie i lekkie (zwykle jedno
 * zgloszenie), wiec plama musi byc szersza i mocniej wzmocniona, inaczej pojedyncze zgloszenia
 * znikna. Obie pary liczb sa DO KALIBRACJI NA ZYWEJ MAPIE.
 */
export const listedDensityLayer: HeatmapLayerSpecification = {
  id: LAYER_IDS.density,
  type: 'heatmap',
  source: SOURCE_ID,
  'source-layer': DENSITY_SOURCE_LAYER,
  minzoom: POINT_MIN_ZOOM,
  // Od POLYGON_MIN_ZOOM kafel ma obrysy i pokazujemy budynki, a nie ich zageszczenie.
  maxzoom: POLYGON_MIN_ZOOM,
  paint: {
    'heatmap-weight': heatmapWeight,
    'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], POINT_MIN_ZOOM, 0.6, DENSITY_MAX_ZOOM, 1.8],
    'heatmap-color': heatmapColor,
    'heatmap-radius': ['interpolate', ['linear'], ['zoom'], POINT_MIN_ZOOM, 12, DENSITY_MAX_ZOOM, 26],
    // Cieplo lezy na ortofoto, wiec nie moze go zamalowac na glucho.
    'heatmap-opacity': 0.8,
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

/**
 * Kolejnosc dodawania do mapy: cieplo na spodzie, potem wypelnienie i obrysy budynkow,
 * podswietlenie na wierzchu. Zakresy zoomow ciepla i obrysow sie nie stykaja, ale kolejnosc
 * i tak trzyma zasade „agregat pod danymi jednostkowymi".
 */
export const MAP_LAYERS: LayerSpecification[] = [
  listedDensityLayer,
  buildingsFillLayer,
  buildingsOutlineLayer,
  selectedFillLayer,
  selectedOutlineLayer,
]

/**
 * Klikalne sa tylko obrysy budynkow. Komorka siatki nie jest budynkiem i nie ma identyfikatora,
 * wiec klik w cieplo wyslalby do `/api/buildings/{id}` liczbe, ktora nic nie znaczy — albo nie
 * wyslalby nic i kasowal wybor. Warstwy podswietlenia tez nie sa klikalne: klik ma trafiac
 * w budynek pod spodem.
 */
export const CLICKABLE_LAYER_IDS: string[] = [LAYER_IDS.fill]
export const HIGHLIGHT_LAYER_IDS: string[] = [LAYER_IDS.selectedFill, LAYER_IDS.selectedOutline]
