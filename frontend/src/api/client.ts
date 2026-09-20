export type Health = {
  status: 'ok' | 'degraded'
  database: 'ok' | 'unavailable'
  postgis: string | null
  detail: string | null
}

/** Rekord rejestru GeoAzbest dopasowany do budynku, razem z miara dopasowania. */
export type RegistryMatch = {
  sourceId: string | null
  nrDzialki: string | null
  recordAreaM2: number
  overlapM2: number
  shareBuilding: number
  shareRecord: number
}

/** `not_listed` znaczy „nie ma go w rejestrze", a nie „dach jest czysty". */
export type Building = {
  /**
   * `osm_id` z OpenStreetMap, nie klucz z sekwencji bazy: ten przezywa ponowny import danych,
   * a klucz z sekwencji nie (`TRUNCATE` go nie zeruje, wiec po imporcie numery sie przesuwaja).
   */
  id: number
  /** `fclass` z warstwy Geofabrik — dla kazdego budynku to 'building', wiec nic nie wnosi. */
  kind: string | null
  /** Rodzaj z OSM (`type`): 'house', 'apartments', 'outbuilding', 'garage'. Ma go ~65% budynkow. */
  osmType: string | null
  name: string | null
  areaM2: number
  centroid: { lng: number; lat: number }
  status: 'listed' | 'not_listed'
  registryMatches: RegistryMatch[]
  otherIntersecting: number
}

/**
 * Domyslnie pusty, czyli zapytania ida na wlasny origin pod /api, a dev server Vite
 * przekazuje je do FastAPI. Dzieki temu CORS nie zalezy od tego, pod jakim adresem
 * otwarto strone. Ustaw VITE_API_BASE_URL tylko wtedy, gdy backend stoi osobno.
 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

/** Szablony dla MapLibre — nawiasy klamrowe podstawia sama biblioteka. */
export const TILES_URL = `${API_BASE_URL}/api/tiles/buildings/{z}/{x}/{y}.mvt`
export const ORTHOPHOTO_TILES_URL = `${API_BASE_URL}/api/imagery/orthophoto/{z}/{x}/{y}.png`

/** Wycinek ortofoto wycentrowany na dachu; backend wymusza kwadrat i margines. */
export function roofImageUrl(id: number, size = 384, baseUrl: string = API_BASE_URL): string {
  return `${baseUrl}/api/buildings/${id}/roof.png?size=${size}`
}

/**
 * Ocena pokrycia dachu ze zdjecia.
 *
 * `source` jest najwazniejszym polem: `mock` znaczy wynik demonstracyjny, ktory NIE pochodzi
 * z zadnego modelu i nie wolno go pokazac jak prawdziwej analizy. `unavailable` to brak
 * odpowiedzi — wtedy `probability` jest `null`, nigdy 0, bo zero znaczyloby „model sprawdzil
 * i nie widzi eternitu".
 *
 * `verdict` ma trzy stany, nie dwa: `suspected` (podejrzenie falistego, szarego pokrycia),
 * `unlikely` (model nie widzi takiego pokrycia) i `unknown` (nie wiadomo).
 */
export type RoofAnalysis = {
  source: 'mock' | 'model' | 'unavailable'
  verdict: 'suspected' | 'unlikely' | 'unknown'
  /** 0–1 albo null. */
  probability: number | null
  modelName: string | null
  /** Zdanie gotowe do pokazania: co ten wynik znaczy i czego nie dowodzi. */
  note: string
}

export async function fetchRoofAnalysis(id: number, baseUrl: string = API_BASE_URL): Promise<RoofAnalysis> {
  const response = await fetch(`${baseUrl}/api/buildings/${id}/analysis`)
  if (response.status === 404) {
    throw new Error('There is no building with this identifier.')
  }
  if (response.status !== 200) {
    throw new Error(`Backend responded with status ${response.status}`)
  }
  return (await response.json()) as RoofAnalysis
}

export type Coordinates = { lng: number; lat: number }

/** Prostokat zaznaczony na mapie. Backend odrzuca zaznaczenia wieksze niz limit z /api/area/limits. */
export type Bounds = { ne: Coordinates; sw: Coordinates }

export type AreaStats = {
  total: number
  listed: number
  notListed: number
  /** Udzial zgloszonych: 0–1. */
  listedShare: number
  roofAreaM2: number
  listedRoofAreaM2: number
  registryRecords: number
}

export type ListedBuilding = {
  id: number
  areaM2: number
  centroid: Coordinates
  nrDzialki: string | null
}

export type AreaScan = {
  stats: AreaStats
  listedBuildings: ListedBuilding[]
  /** true, gdy zgloszonych bylo wiecej, niz backend oddaje w liscie. */
  truncated: boolean
  areaKm2: number
}

/**
 * Limity modelu sa twardsze niz limit skanu: tamten serwis odrzuca zadania powyzej 100 budynkow
 * i 4 km2. Front pokazuje te liczby w powodzie zablokowanego przycisku, wiec musi je znac przed
 * kliknieciem — ale nie trzyma ich wlasnej kopii.
 */
export type AreaModelLimits = { maxBuildings: number; maxAreaKm2: number }

/** `model` jest opcjonalny: backend bez analizy obszaru oddaje sam limit zaznaczenia. */
export type AreaLimits = { maxAreaKm2: number; model?: AreaModelLimits }

/** Limit powierzchni zaznaczenia. Front pyta backend, zamiast trzymac wlasna kopie tej liczby. */
export async function fetchAreaLimits(baseUrl: string = API_BASE_URL): Promise<AreaLimits> {
  const response = await fetch(`${baseUrl}/api/area/limits`)
  if (response.status !== 200) throw new Error(`Backend responded with status ${response.status}`)
  return (await response.json()) as AreaLimits
}

/**
 * Statystyki zaznaczonego obszaru. Przy 400 backend tlumaczy w `detail`, co jest nie tak
 * (np. ile km2 zaznaczono wobec limitu) — ten tekst jest gotowy do pokazania uzytkownikowi.
 */
export async function fetchAreaScan(bounds: Bounds, baseUrl: string = API_BASE_URL): Promise<AreaScan> {
  const response = await fetch(`${baseUrl}/api/area/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(bounds),
  })
  if (response.status === 400 || response.status === 503) {
    const body = (await response.json()) as { detail?: string }
    throw new Error(body.detail ?? 'Could not scan the area.')
  }
  if (response.status !== 200) throw new Error(`Backend responded with status ${response.status}`)
  return (await response.json()) as AreaScan
}

/**
 * Obrys dachu tak, jak oddal go backend. Ksztalt jest zgodny z GeoJSON-em, wiec mapa bierze go
 * wprost; `MultiPolygon` jest tu, bo budynek z dziura albo z dwoma czesciami przyjdzie wlasnie tak.
 */
export type RoofGeometry =
  | { type: 'Polygon'; coordinates: number[][][] }
  | { type: 'MultiPolygon'; coordinates: number[][][][] }

/**
 * Budynek z ocena modelu. `probability` jest zawsze liczba 0–1 — budynki bez oceny nie trafiaja
 * do tej listy, liczy je `noResult`. `listed` mowi o rejestrze, nie o modelu.
 */
export type SuspectedRoof = {
  id: number
  probability: number
  listed: boolean
  areaM2: number
  /**
   * Obrys od modelu. `null` jest tu mozliwe, bo geometria pochodzi z cudzej odpowiedzi — budynek
   * bez obrysu liczy sie do statystyk, ale nie da sie go narysowac, wiec mapa go nie dostaje.
   */
  geometry: RoofGeometry | null
}

/**
 * Wynik modelu dla calego obszaru.
 *
 * `suspectedNotListed` jest tu najwazniejsza liczba: budynki, ktorych nikt nie zglosil, a model
 * widzi na nich pokrycie typu eternit. `noResult` to osobny stan — brak oceny nie jest ocena
 * „nic nie widac". `threshold` jest progiem, powyzej ktorego ocena liczy sie jako podejrzenie.
 */
export type AreaAnalysisStats = {
  analysed: number
  noResult: number
  suspected: number
  /** Udzial podejrzanych wsrod ocenionych: 0–1. */
  suspectedShare: number
  suspectedNotListed: number
  suspectedListed: number
  listedNotSuspected: number
  suspectedRoofAreaM2: number
  threshold: number
  modelName: string
}

export type AreaAnalysis = {
  stats: AreaAnalysisStats
  buildings: SuspectedRoof[]
  /** true, gdy ocenionych bylo wiecej, niz backend oddaje w liscie. */
  truncated: boolean
}

/**
 * Ocena modelu dla zaznaczonego prostokata. Osobne zadanie od skanu, bo model ma twarde limity
 * (100 budynkow, 4 km2 — patrz /api/area/limits) i liczy kilka sekund.
 *
 * Przy 400 i 503 backend tlumaczy w `detail`, co jest nie tak; ten tekst jest gotowy do pokazania
 * uzytkownikowi i nie przerabiamy go.
 */
export async function fetchAreaAnalysis(bounds: Bounds, baseUrl: string = API_BASE_URL): Promise<AreaAnalysis> {
  const response = await fetch(`${baseUrl}/api/area/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(bounds),
  })
  if (response.status === 400 || response.status === 503) {
    const body = (await response.json()) as { detail?: string }
    throw new Error(body.detail ?? 'Could not analyse the area.')
  }
  if (response.status !== 200) throw new Error(`Backend responded with status ${response.status}`)
  return (await response.json()) as AreaAnalysis
}

/** Miejsce z wyszukiwarki. `bbox` jest w kolejnosci [south, west, north, east]. */
export type Place = {
  label: string
  lat: number
  lng: number
  bbox: [number, number, number, number] | null
  kind: string | null
}

/**
 * 503 to prawidlowa odpowiedz sondy zdrowia (backend zyje, baza nie) i wraca jako dane,
 * nie jako wyjatek. Kazdy inny kod to blad, ktory ma zobaczyc uzytkownik.
 */
export async function fetchHealth(baseUrl: string = API_BASE_URL): Promise<Health> {
  const response = await fetch(`${baseUrl}/api/health`)
  if (response.status !== 200 && response.status !== 503) {
    throw new Error(`Backend responded with status ${response.status}`)
  }
  return (await response.json()) as Health
}

/**
 * Wyszukiwanie miejsc. Backend jest tu proxy do Nominatima, ktory dopuszcza jedno zapytanie
 * na sekunde — przy 429 komunikat mowi, zeby sprobowac za chwile, a nie udaje braku wynikow.
 */
export async function fetchPlaces(query: string, limit = 5, baseUrl: string = API_BASE_URL): Promise<Place[]> {
  const search = new URLSearchParams({ q: query, limit: String(limit) })
  const response = await fetch(`${baseUrl}/api/geocode?${search}`)
  if (response.status === 429) {
    throw new Error('Too many search requests. Try again in a moment.')
  }
  if (response.status === 503) {
    throw new Error('The place search is not responding.')
  }
  if (response.status !== 200) {
    throw new Error(`Backend responded with status ${response.status}`)
  }
  const body = (await response.json()) as { results: Place[] }
  return body.results
}

export async function fetchBuilding(id: number, baseUrl: string = API_BASE_URL): Promise<Building> {
  const response = await fetch(`${baseUrl}/api/buildings/${id}`)
  if (response.status === 404) {
    throw new Error('There is no building with this identifier.')
  }
  if (response.status !== 200) {
    throw new Error(`Backend responded with status ${response.status}`)
  }
  return (await response.json()) as Building
}
