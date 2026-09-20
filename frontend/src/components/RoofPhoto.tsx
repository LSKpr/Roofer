import { useState } from 'react'
import { roofImageUrl } from '../api/client'

type RoofPhotoProps = {
  buildingId: number
  size?: number
}

type PhotoState = 'loading' | 'ready' | 'unavailable'

/**
 * Wycinek ortofotomapy GUGiK wycentrowany na dachu.
 *
 * Komponent sam nie siega po siec — zrodlem jest znacznik <img>. Dzieki temu 503 z backendu
 * (GUGiK nie odpowiedzial albo baza padla) dociera tu jako `onError`, a wtedy pokazujemy
 * komunikat zamiast pustej ramki. Atrybucja pod zdjeciem jest wymogiem regulaminu usługi.
 */
export function RoofPhoto({ buildingId, size = 384 }: RoofPhotoProps) {
  const [state, setState] = useState<PhotoState>('loading')

  return (
    <figure data-testid="roof-photo" data-state={state}>
      {/* Tlo ramki jest jednoczesnie szkieletem wczytywania: kadr ma stala wysokosc, wiec
          karta nie przeskakuje, gdy zdjecie dojdzie. */}
      <div className="aspect-square w-full overflow-hidden rounded-card border border-hairline bg-surface-muted">
        {state === 'unavailable' ? (
          <p className="flex h-full items-center justify-center px-6 text-center text-xs text-ink-muted">
            Aerial imagery unavailable
          </p>
        ) : (
          <img
            src={roofImageUrl(buildingId, size)}
            alt={`Roof of building ${buildingId}`}
            loading="lazy"
            width={size}
            height={size}
            onLoad={() => setState('ready')}
            onError={() => setState('unavailable')}
            className={`h-full w-full object-cover ${state === 'ready' ? 'opacity-100' : 'opacity-0'}`}
          />
        )}
      </div>
      <figcaption className="mt-2 space-y-1">
        <p className="text-xs text-ink-faint">
          The image shows the roof as it looked during the aerial survey. It does not confirm what the covering is made
          of, nor what state the roof is in today.
        </p>
        <p className="label-micro">Aerial imagery: GUGiK / Geoportal.gov.pl</p>
      </figcaption>
    </figure>
  )
}
