export type Health = {
  status: 'ok' | 'degraded'
  database: 'ok' | 'unavailable'
  postgis: string | null
  detail: string | null
}

/**
 * Domyslnie pusty, czyli zapytania ida na wlasny origin pod /api, a dev server Vite
 * przekazuje je do FastAPI. Dzieki temu CORS nie zalezy od tego, pod jakim adresem
 * otwarto strone. Ustaw VITE_API_BASE_URL tylko wtedy, gdy backend stoi osobno.
 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

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
