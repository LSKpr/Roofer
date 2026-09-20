import { useState } from 'react'
import { roofImageUrl, type RoofImage } from '../api/client'

type RoofPhotoProps = {
  buildingId: number
  size?: number
  /**
   * Skad jest kadr. `undefined` i `null` znacza „backend nie powiedzial" i wtedy podpis zostaje
   * dokladnie taki, jak przy kadrze z WMS-a: bez daty i bez liczb, ktorych nie znamy.
   */
  roofImage?: RoofImage | null
}

type PhotoState = 'loading' | 'ready' | 'unavailable'

/**
 * Zdanie prawdziwe przy obu zrodlach kadru, wiec stoi w podpisie zawsze. Zdjecie z nalotu nie
 * rozstrzyga materialu pokrycia ani stanu dachu dzisiaj — niezaleznie od tego, czy jest ostre.
 */
const SURVEY_NOTE =
  'The image shows the roof as it looked during the aerial survey. It does not confirm what the covering is made of, nor what state the roof is in today.'

const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]

/** Rozdzielczosc: 0,05 m na piksel czyta sie jako „5 cm", metry z dwoma zerami nie mowia nic. */
const GSD_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
/** Krawedz ramki ma czesc dziesietna (12,8 m) i wlasnie ona jest tu istotna. */
const FRAME_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })

/**
 * Dzien nalotu z napisu `YYYY-MM-DD`, np. „5 December 2023".
 *
 * Skladane recznie, bez `new Date()`: ten parsuje date bez godziny jako UTC, wiec w strefie na
 * zachod od Greenwich pokazalby dzien wczesniej — podpis pod zdjeciem zmienialby sie zaleznie od
 * tego, gdzie stoi przegladarka. Napis, ktorego nie rozumiemy, daje `null`, a nie zgadnieta date.
 */
function surveyDate(iso: string): string | null {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso.trim())
  if (parts === null) return null
  const month = MONTHS[Number(parts[2]) - 1]
  const day = Number(parts[3])
  if (month === undefined || day < 1 || day > 31) return null
  return `${day} ${month} ${Number(parts[1])}`
}

function resolutionLabel(gsdM: number): string {
  return `${GSD_FORMAT.format(gsdM * 100)} cm per pixel`
}

function frameLabel(frameM: number): string {
  return `${FRAME_FORMAT.format(frameM)} m`
}

/**
 * Dzien nalotu i rozdzielczosc — dwie rzeczy, ktore przy kadrze z dysku wiemy dodatkowo. Karta
 * mowi inaczej tylko „during the aerial survey", a tutaj moze podac dzien.
 *
 * Kazdy czlon wchodzi osobno, bo brak ktorejkolwiek liczby ma zabrac tylko ja, a nie cale zdanie.
 */
function localSurveyNote(image: RoofImage): string | null {
  const date = image.acquiredOn === null ? null : surveyDate(image.acquiredOn)
  const resolution = image.gsdM === null ? null : resolutionLabel(image.gsdM)
  if (date !== null && resolution !== null) return `Flown on ${date}, at ${resolution}.`
  if (date !== null) return `Flown on ${date}.`
  if (resolution !== null) return `Recorded at ${resolution}.`
  return null
}

/**
 * Najwazniejsze zastrzezenie przy kadrze z dysku: ramka ma stala krawedz, wiec dluzszy dach jest
 * przyciety. Bez tego zdania uzytkownik odczyta z obrazka, ze budynek jest mniejszy, niz jest.
 *
 * Drugie zdanie jest tu dlatego, ze kadr, ktory liczymy sami z WMS-a, jest kwadratem wokol calego
 * obrysu — te dwa zdjecia nie sa tym samym i nie wolno ich porownywac, nie mowiac, ktore jest
 * ktore.
 */
function frameNote(frameM: number): string {
  const frame = frameLabel(frameM)
  return `The frame is a fixed ${frame} square, so a roof longer than ${frame} runs past the edge and the building looks smaller than it is. The crop we ask the WMS for is a square around the whole outline, so the two are not the same picture.`
}

/**
 * Wycinek ortofotomapy GUGiK wycentrowany na dachu.
 *
 * Komponent sam nie siega po siec — zrodlem jest znacznik <img>. Dzieki temu 503 z backendu
 * (GUGiK nie odpowiedzial albo baza padla) dociera tu jako `onError`, a wtedy pokazujemy
 * komunikat zamiast pustej ramki. Atrybucja pod zdjeciem jest wymogiem regulaminu usługi.
 *
 * Podpis rosnie tylko przy kadrze z dysku (`source: 'local'`), bo tylko wtedy znamy dzien nalotu,
 * rodzima rozdzielczosc i krawedz ramki. Przy kadrze z WMS-a tych trzech liczb nie zna nikt, wiec
 * podpis zostaje dokladnie taki, jak byl — data wziecia z niczego byloby najgorszym dodatkiem.
 */
export function RoofPhoto({ buildingId, size = 384, roofImage }: RoofPhotoProps) {
  const [state, setState] = useState<PhotoState>('loading')
  const local = roofImage?.source === 'local' ? roofImage : null
  const surveyNote = local === null ? null : localSurveyNote(local)

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
        <p className="text-xs text-ink-faint">{SURVEY_NOTE}</p>
        {surveyNote === null ? null : <p className="text-xs text-ink-faint">{surveyNote}</p>}
        {local === null || local.frameM === null ? null : (
          <p className="text-xs text-ink-faint">{frameNote(local.frameM)}</p>
        )}
        <p className="label-micro">Aerial imagery: GUGiK / Geoportal.gov.pl</p>
      </figcaption>
    </figure>
  )
}
