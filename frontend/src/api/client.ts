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
  id: number
  osmId: string | null
  kind: string | null
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

/** Szablon dla MapLibre — nawiasy klamrowe podstawia sama biblioteka. */
export const TILES_URL = `${API_BASE_URL}/api/tiles/buildings/{z}/{x}/{y}.mvt`

/**
 * 503 to prawidlowa odpowiedz sondy zdrowia (backend zyje, baza nie) i wraca jako dane,
 * nie jako wyjatek. Kazdy inny kod to blad, ktory ma zobaczyc uzytkownik.
 */
export async function fetchHealth(baseUrl: string = API_BASE_URL): Promise<Health> {
  const response = await fetch(`${baseUrl}/api/health`)
  if (response.status !== 200 && response.status !== 503) {
    throw new Error(`Backend odpowiedzial kodem ${response.status}`)
  }
  return (await response.json()) as Health
}

export async function fetchBuilding(id: number, baseUrl: string = API_BASE_URL): Promise<Building> {
  const response = await fetch(`${baseUrl}/api/buildings/${id}`)
  if (response.status === 404) {
    throw new Error('Nie ma budynku o tym identyfikatorze.')
  }
  if (response.status !== 200) {
    throw new Error(`Backend odpowiedzial kodem ${response.status}`)
  }
  return (await response.json()) as Building
}
