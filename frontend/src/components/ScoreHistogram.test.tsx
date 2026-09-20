import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ScoreHistogram } from './ScoreHistogram'

type Options = {
  scores?: number[]
  threshold?: number
  className?: string
}

function renderHistogram(options: Options = {}) {
  return render(
    <ScoreHistogram
      scores={options.scores ?? [0.1, 0.6]}
      threshold={options.threshold ?? 0.5}
      className={options.className}
    />,
  )
}

/** Koszyki w kolejnosci z ekranu: jedna komorka na kazdy przedzial, takze na pusty. */
function buckets(): HTMLElement[] {
  return screen.getAllByTestId('score-bucket')
}

function counts(): number[] {
  return buckets().map((cell) => Number(cell.dataset.count))
}

/** Slupek siedzi w komorce koszyka; puste koszyki nie maja slupka wcale. */
function bar(index: number): HTMLElement | null {
  return buckets()[index].firstElementChild as HTMLElement | null
}

/** Kolor koszyka tak, jak widzi go oko: podejrzenie, neutralny albo brak slupka. */
function colour(index: number): string {
  const element = bar(index)
  if (element === null) return 'empty'
  return element.className.includes('bg-suspected') ? 'suspected' : 'neutral'
}

it('rysuje po jednym slupku na kazdy koszyk 0,05', () => {
  renderHistogram()

  expect(buckets()).toHaveLength(20)
  expect(buckets()[0].dataset.from).toBe('0')
  expect(buckets()[10].dataset.from).toBe('0.5')
  expect(buckets()[19].dataset.from).toBe('0.95')
})

// Recznie policzony przyklad: dwa dachy w pierwszym koszyku, po jednym w 0,05-0,10 i 0,50-0,55.
it('liczy dachy w koszykach i nie gubi zadnego', () => {
  renderHistogram({ scores: [0, 0.04, 0.05, 0.52] })

  expect(counts()[0]).toBe(2)
  expect(counts()[1]).toBe(1)
  expect(counts()[10]).toBe(1)
  expect(counts().reduce((sum, count) => sum + count, 0)).toBe(4)
})

// Sedno tego wykresu: widac, co prog zabiera i co dodaje. Ocena rowna progowi jest podejrzeniem,
// tak samo jak w `recountStats`, wiec koszyk zaczynajacy sie na progu jest juz pomaranczowy.
it('maluje koszyki od progu w gore kolorem podejrzenia, a nizsze neutralnie', () => {
  renderHistogram({ scores: [0.45, 0.5, 0.8], threshold: 0.5 })

  expect(colour(9)).toBe('neutral')
  expect(colour(10)).toBe('suspected')
  expect(colour(16)).toBe('suspected')
})

it('przemalowuje slupki, gdy prog sie zmienia', () => {
  const view = renderHistogram({ scores: [0.45, 0.5, 0.8], threshold: 0.5 })
  expect(colour(10)).toBe('suspected')

  view.rerender(<ScoreHistogram scores={[0.45, 0.5, 0.8]} threshold={0.7} />)

  // Koszyk 0,50-0,55 wypadl pod prog, a 0,80-0,85 zostal podejrzeniem.
  expect(colour(10)).toBe('neutral')
  expect(colour(16)).toBe('suspected')
})

it('przy progu 0 nie ma slupka neutralnego, a przy progu prawie 1 zadnego podejrzenia', () => {
  const view = renderHistogram({ scores: [0.1, 0.5, 0.9], threshold: 0 })
  expect([colour(2), colour(10), colour(18)]).toEqual(['suspected', 'suspected', 'suspected'])

  view.rerender(<ScoreHistogram scores={[0.1, 0.5, 0.9]} threshold={0.95} />)
  expect([colour(2), colour(10), colour(18)]).toEqual(['neutral', 'neutral', 'neutral'])
})

// Najwyzszy koszyk wypelnia pudelko, reszta jest do niego proporcjonalna — skala liniowa, bez
// logarytmu i bez obciecia, zeby dwa razy wyzszy slupek znaczyl dwa razy wiecej dachow.
it('skaluje wysokosci liniowo wzgledem najwyzszego koszyka', () => {
  renderHistogram({ scores: [0.02, 0.02, 0.02, 0.52] })

  // CSSOM skraca „100.0%" do „100%" — pasek jest zwezony do liczby, nie do napisu.
  expect(bar(0)?.getAttribute('style')).toContain('height: 100%')
  expect(bar(10)?.getAttribute('style')).toContain('height: 33.3%')
})

// Koszyk z jednym dachem obok skupiska trzystu zniknalby bez tego: pusty slupek klamie o zero.
it('daje niepustemu koszykowi co najmniej piksel wysokosci', () => {
  renderHistogram({ scores: [...Array.from({ length: 300 }, () => 0.02), 0.92] })

  expect(bar(18)?.className).toContain('min-h-px')
  expect(bar(18)?.getAttribute('style')).toContain('height: 0.3%')
})

it('nie rysuje slupka w koszyku, w ktorym nie ma zadnego dachu', () => {
  renderHistogram({ scores: [0.02] })

  expect(bar(0)).not.toBeNull()
  expect(bar(5)).toBeNull()
})

// Os pionowa bez liczby nie ma jednostki, a wtedy „wysoki slupek" nie znaczy nic.
it('podaje liczbe dachow w najwyzszym koszyku', () => {
  renderHistogram({ scores: [0.02, 0.02, 0.52] })
  expect(screen.getByText('Tallest bar 2 roofs')).toBeDefined()

  renderHistogram({ scores: [0.02, 0.52] })
  expect(screen.getByText('Tallest bar 1 roof')).toBeDefined()
})

// Podpis, bez ktorego wykres klamie: dachy bez oceny nie sa tu zerem, nie ma ich wcale.
it('mowi, ze to rozklad tylko dachow ocenionych, a brak oceny nie jest zerem', () => {
  renderHistogram()

  expect(
    screen.getByText(
      'Scored roofs only: roofs with no score from the model are not in this chart at all, and no score is not the same as a score of zero.',
    ),
  ).toBeDefined()
})

// Linia progu jedzie razem z suwakiem, bo bierze te sama wartosc, i stoi w osi wykresu.
it('stawia linie progu tam, gdzie prog', () => {
  const view = renderHistogram({ threshold: 0.35 })
  expect(screen.getByTestId('score-threshold-line').getAttribute('style')).toContain('left: 35%')

  view.rerender(<ScoreHistogram scores={[0.1, 0.6]} threshold={0.8} />)
  expect(screen.getByTestId('score-threshold-line').getAttribute('style')).toContain('left: 80%')
})

// Pusta ramka wygladalaby jak rozklad rowny zeru, a to zupelnie inna informacja niz brak ocen.
it('bez ani jednej oceny nie rysuje nic', () => {
  const view = renderHistogram({ scores: [] })

  expect(view.container.firstChild).toBeNull()
  expect(screen.queryByTestId('score-histogram')).toBeNull()
  expect(screen.queryByText(/Scored roofs only/)).toBeNull()
})

// Kontrolka zostaje jedna i jest nia suwak; wykres jest ilustracja, wiec nie jest ani kontrolka,
// ani drugim, niedostepnym suwakiem.
it('jest ilustracja, a nie druga kontrolka', () => {
  const view = renderHistogram()

  expect(screen.getByTestId('score-histogram').getAttribute('aria-hidden')).toBe('true')
  expect(view.container.querySelectorAll('input, button, [role]')).toHaveLength(0)
  expect(screen.queryAllByRole('slider')).toHaveLength(0)
})

it('przyjmuje klase od rodzica, bo odstepy sa decyzja suwaka', () => {
  const view = renderHistogram({ className: 'mt-1.5' })

  expect((view.container.firstChild as HTMLElement).className).toContain('mt-1.5')
})
