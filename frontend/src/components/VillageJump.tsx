import type { Village } from '../api/client'

type VillageJumpProps = {
  /** Wsie z `/api/villages`. Pusta lista jest normalnym stanem: nie ma czego pokazac. */
  villages: Village[]
  /** Rodzic zamienia wies na cel kamery, tak samo jak przy wyborze miejsca z wyszukiwarki. */
  onPick: (village: Village) => void
  className?: string
}

/**
 * Mikropodpis sekcji. Mowi o zdjeciach, nie o wsiach: wyrozniony jest tu stan naszego dysku,
 * a nie te dwie miejscowosci.
 */
const HEADING = 'Cached imagery'

/**
 * Zdanie, bez ktorego ta sekcja klamie.
 *
 * Dwa przyciski obok siebie wygladaja na skrot do miejsc wybranych merytorycznie — najgorszych,
 * najbardziej zglaszanych, sprawdzonych. Nic takiego nie zachodzi: te wsie maja wycinki dachow
 * na dysku i to jedyna rzecz, ktora je wyroznia. Liczby na przyciskach sa z eksportu, wiec
 * tlumacza sie same; zdanie mowi to, czego z liczb nie widac.
 */
const NOTE =
  'Roof photos for these villages are already exported to disk, so they open without a network request and at the resolution on each button. Nothing in the register singles them out — the only difference is that we have their crops locally.'

const COUNT_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

function cropsLabel(crops: number): string {
  return `${COUNT_FORMAT.format(crops)} crops`
}

/**
 * Podpis przycisku: liczba kadrow, a rozdzielczosc tylko wtedy, gdy backend ja podal.
 *
 * `gsdM` bywa `null`, gdy kadry jednej wsi maja rozna rozdzielczosc — backend nie podaje wtedy
 * zadnej, bo jedna liczba bylaby polprawda. Mnozenie `null * 100` dalo by „0 cm/px", czyli liczbe
 * wziete z powietrza; 0,05 m czyta sie jako „5 cm/px", bo metry z dwoma zerami nic nie mowia.
 */
function buttonLabel(crops: number, gsdM: number | null): string {
  const counted = cropsLabel(crops)
  if (gsdM === null) return counted
  return `${counted} · ${COUNT_FORMAT.format(gsdM * 100)} cm/px`
}

/**
 * Skoki do wsi, dla ktorych wycinki dachow leza na dysku.
 *
 * Komponent jest czysto prezentacyjny: liste pobiera `App` (tak jak limit powierzchni), a klik
 * oddaje cala wies rodzicowi, ktory przesuwa mape na jej obwiednie tym samym mechanizmem, co
 * wybor miejscowosci z wyszukiwarki. Dzieki temu nie ma tu drugiego pojecia o kamerze.
 */
export function VillageJump({ villages, onPick, className }: VillageJumpProps) {
  // Pusta lista to backend bez skonfigurowanych danych. Naglowek z podpisem i bez przyciskow
  // wygladalby na awarie, a zdanie o zdjeciach z dysku bylo by wtedy nieprawda.
  if (villages.length === 0) return null

  return (
    <section
      aria-label={HEADING}
      data-testid="village-jump"
      className={`rounded-card border border-hairline bg-surface px-4 py-3 text-ink ${className ?? ''}`}
    >
      <p className="label-micro">{HEADING}</p>
      {/* Dwie kolumny, bo kolumna ma 352 px: nazwa wsi i jej liczby mieszcza sie w jednym rzedzie,
          a trzecia wies (gdyby doszla) spada do drugiego rzedu bez zmiany ukladu. */}
      <div className="mt-2 grid grid-cols-2 gap-2">
        {villages.map((village) => (
          <button
            key={village.folder}
            type="button"
            onClick={() => onPick(village)}
            className="rounded-card border border-hairline bg-surface px-2.5 py-2 text-left hover:bg-surface-muted"
          >
            <span className="block truncate text-xs leading-none text-ink">{village.name}</span>
            {/* Liczby z API, nie z kodu: eksport jest konkretem, ktory sam tlumaczy przycisk. */}
            <span className="label-micro mt-1 block truncate">
              {buttonLabel(village.crops, village.gsdM)}
            </span>
          </button>
        ))}
      </div>
      <p className="mt-2.5 text-xs text-ink-faint">{NOTE}</p>
    </section>
  )
}
