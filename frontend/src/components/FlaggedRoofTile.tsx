import { useState } from 'react'
import { roofImageUrl } from '../api/client'

type FlaggedRoofTileProps = {
  /** Identyfikator OSM: adres tego dachu w calej aplikacji, wiec nim adresujemy zdjecie i `onPick`. */
  id: number
  /** Ocena modelu jako ulamek 0–1; kafelek pokazuje ja jako liczbe calkowita procent. */
  probability: number
  areaM2: number
  /** Krawedz kadru w pikselach — po co akurat tyle, patrz `THUMBNAIL_SIZE`. */
  size?: number
  onPick: (id: number) => void
}

type PhotoState = 'loading' | 'ready' | 'unavailable'

/**
 * Krawedz kadru miniatury.
 *
 * Panel ma 352 px, wiec w siatce trzech kolumn na kadr wypada okolo 100 px — 128 to najmniejszy
 * rozmiar, ktory przyjmuje backend (`ROOF_MIN_SIZE`), i jednoczesnie zapas na ekrany o gestszych
 * pikselach. Wiekszy kadr nie ma tu sensu: w jednym renderze idzie do naszego backendu
 * dwadziescia piec zapytan, a on ma wlasny ogranicznik do GUGiK. Duzy kadr jest w karcie
 * budynku po kliknieciu w kafelek.
 */
export const THUMBNAIL_SIZE = 128

const NUMBER_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/**
 * GUGiK czasem nie oddaje kadru (503 z backendu). Dach bez zdjecia jest nadal dachem do
 * sprawdzenia, wiec w miejscu kadru staje ten komunikat, a ocena i powierzchnia zostaja.
 * Ta sama fraza stoi w duzym kadrze karty budynku (`RoofPhoto`), zeby brak zdjecia czytal sie
 * wszedzie tak samo.
 */
const UNAVAILABLE_NOTE = 'Aerial imagery unavailable'

function scoreLabel(probability: number): string {
  return `${Math.round(probability * 100)}%`
}

function areaLabel(squareMeters: number): string {
  return `${NUMBER_FORMAT.format(squareMeters)} m²`
}

/**
 * Jeden dach z listy podejrzen: wycinek ortofoto, ocena pod nim i powierzchnia.
 *
 * Kafelek sam nie siega po siec — zrodlem jest znacznik <img>, dokladnie jak w `RoofPhoto`.
 * Dzieki temu 503 z backendu dociera tu jako `onError` i zamienia kadr na komunikat zamiast
 * pustej ramki, a kafelek nadal jest klikalny: brak zdjecia nie usuwa dachu z listy.
 *
 * Klikalny jest caly kafelek, nie zdjecie ani numer w podpisie: celem jest ten dach, nie jego
 * kadr. Identyfikator OSM stoi w podpisie, bo to on jest adresem dachu w reszcie aplikacji —
 * i dlatego niesie go takze `alt` zdjecia, zeby czytnik ekranu dostal go razem z kadrem.
 */
export function FlaggedRoofTile({ id, probability, areaM2, size = THUMBNAIL_SIZE, onPick }: FlaggedRoofTileProps) {
  const [state, setState] = useState<PhotoState>('loading')

  return (
    <button
      type="button"
      data-testid="flagged-roof-tile"
      data-state={state}
      onClick={() => onPick(id)}
      className="block w-full text-left hover:bg-surface-muted"
    >
      {/* Stala proporcja kwadratu jest jednoczesnie szkieletem wczytywania: kafelek zajmuje swoje
          miejsce, zanim zdjecie dojdzie, wiec siatka nie skacze w trakcie wczytywania. */}
      <span
        data-testid="flagged-roof-frame"
        className="block aspect-square w-full overflow-hidden rounded-card border border-hairline bg-surface-muted"
      >
        {state === 'unavailable' ? (
          <span className="flex h-full items-center justify-center px-1 text-center text-[10px] leading-tight text-ink-muted">
            {UNAVAILABLE_NOTE}
          </span>
        ) : (
          <img
            src={roofImageUrl(id, size)}
            alt={`Roof of building ${id}`}
            loading="lazy"
            width={size}
            height={size}
            onLoad={() => setState('ready')}
            onError={() => setState('unavailable')}
            className={`h-full w-full object-cover ${state === 'ready' ? 'opacity-100' : 'opacity-0'}`}
          />
        )}
      </span>
      <span className="mt-1 flex items-center gap-1.5">
        {/* Ten sam pomaranczowy token, ktorym mapa maluje obrys tego dachu. */}
        <span
          data-testid="flagged-roof-dot"
          className="inline-block h-2 w-2 shrink-0 bg-suspected"
          aria-hidden="true"
        />
        {/* Ocena wyrozniona, bo to ona ustawia kolejnosc: gora siatki to pierwszy wyjazd. */}
        <span className="font-display text-sm leading-none text-ink">{scoreLabel(probability)}</span>
        <span className="min-w-0 truncate text-[10px] leading-none text-ink-muted">{areaLabel(areaM2)}</span>
      </span>
      <span className="label-micro block truncate">OSM {id}</span>
    </button>
  )
}
