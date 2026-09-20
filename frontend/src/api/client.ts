export type Health = {
  status: 'ok' | 'degraded'
  database: 'ok' | 'unavailable'
  postgis: string | null
  detail: string | null
}

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8001'

/**
 * 503 to prawidlowa odpowiedz sondy zdrowia (backend zyje, baza nie) i wraca jako dane,
 * nie jako wyjatek. Kazdy inny kod to blad, ktory ma zobaczyc uzytkownik.
 */
export async function fetchHealth(baseUrl: string = API_BASE_URL): Promise<Health> {
  const response = await fetch(`${baseUrl}/health`)
  if (response.status !== 200 && response.status !== 503) {
    throw new Error(`Backend odpowiedzial kodem ${response.status}`)
  }
  return (await response.json()) as Health
}
