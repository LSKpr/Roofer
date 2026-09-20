import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ThresholdSlider } from './ThresholdSlider'

type Options = {
  value?: number
  onChange?: (value: number) => void
  modelDefault?: number
  scores?: number[]
  className?: string
}

function renderSlider(options: Options = {}) {
  return render(
    <ThresholdSlider
      value={options.value ?? 0.5}
      onChange={options.onChange ?? (() => {})}
      modelDefault={options.modelDefault ?? 0.5}
      scores={options.scores ?? []}
      className={options.className}
    />,
  )
}

/** Suwak szukamy tak, jak znalazlby go czytnik ekranu: po etykiecie. */
function slider(): HTMLInputElement {
  return screen.getByLabelText('Suspicion threshold') as HTMLInputElement
}

// Prawdziwy `<input type="range">`, bo strzalki, Home/End i komunikat czytnika ekranu maja
// przyjsc z przegladarki, a nie z wlasnego uchwytu z diva.
it('jest natywnym suwakiem od 0 do 1 z krokiem 0,05', () => {
  renderSlider()

  expect(slider().type).toBe('range')
  expect(slider().getAttribute('min')).toBe('0')
  expect(slider().getAttribute('max')).toBe('1')
  expect(slider().getAttribute('step')).toBe('0.05')
})

it('pokazuje wartosc jako procent, a nie jako ulamek', () => {
  renderSlider({ value: 0.65 })
  expect(screen.getByTestId('threshold-value').textContent).toBe('65%')

  renderSlider({ value: 0.05 })
  expect(screen.getAllByTestId('threshold-value')[1].textContent).toBe('5%')
})

it('stoi tam, gdzie wskazuje podana wartosc', () => {
  renderSlider({ value: 0.35 })

  expect(slider().value).toBe('0.35')
})

it('oddaje nowy prog jako liczbe, nie jako tekst z pola', () => {
  const onChange = vi.fn()
  renderSlider({ onChange })

  fireEvent.change(slider(), { target: { value: '0.8' } })

  expect(onChange).toHaveBeenCalledTimes(1)
  expect(onChange).toHaveBeenCalledWith(0.8)
  expect(typeof onChange.mock.calls[0][0]).toBe('number')
})

// Sama liczba „35%" nie mowi, w ktora strone jest ostrozniej — to jest istota tej decyzji.
it('podpisuje oba konce kompromisem, ktory za nimi stoi', () => {
  renderSlider()

  expect(screen.getByText('Fewer flags, more missed')).toBeDefined()
  expect(screen.getByText('More flags, more false alarms')).toBeDefined()
})

// Wlasne ustawienie nie moze wygladac jak wynik modelu.
it('podaje prog modelu, gdy ustawiony jest inny', () => {
  renderSlider({ value: 0.35, modelDefault: 0.5 })

  expect(screen.getByText('Model default: 50%')).toBeDefined()
})

it('nie powtarza progu modelu, gdy suwak stoi dokladnie na nim', () => {
  renderSlider({ value: 0.5, modelDefault: 0.5 })

  expect(screen.queryByText(/Model default/)).toBeNull()
})

it('uzywa tokenu podejrzenia na uchwyt, nie czerwieni rejestru', () => {
  renderSlider()

  expect(slider().className).toContain('accent-suspected')
  expect(slider().className).not.toContain('accent-listed')
})

it('przyjmuje klase od rodzica, bo odstepy sa decyzja panelu', () => {
  const view = renderSlider({ className: 'mb-3' })

  expect((view.container.firstChild as HTMLElement).className).toContain('mb-3')
})

// Sam suwak jest galka bez kontekstu: „60%" nie mowi, czy odcina dwa dachy, czy dwiescie.
it('pokazuje rozklad ocen, gdy sa oceny', () => {
  renderSlider({ scores: [0.1, 0.52, 0.9] })

  expect(screen.getByTestId('score-histogram')).toBeDefined()
  expect(screen.getAllByTestId('score-bucket')).toHaveLength(20)
})

// Wykres i tor suwaka musza czytac sie w jednej osi, wiec miedzy polem a slupkami nie ma niczego.
it('stawia rozklad tuz pod torem suwaka', () => {
  renderSlider({ scores: [0.1, 0.52] })

  const afterInput = slider().nextElementSibling as HTMLElement

  expect(afterInput.querySelector('[data-testid="score-histogram"]')).not.toBeNull()
})

// Bez ocen nie ma rozkladu, a pusta ramka pod suwakiem wygladalaby jak rozklad rowny zeru.
it('nie rysuje rozkladu, gdy nie ma ani jednej oceny', () => {
  renderSlider({ scores: [] })

  expect(screen.queryByTestId('score-histogram')).toBeNull()
  expect(slider().type).toBe('range')
})

// Prog na wykresie to ta sama liczba, ktora stoi na suwaku — inaczej kolory opisywalyby inny prog
// niz liczby w panelu.
it('dzieli kolory slupkow dokladnie na wartosci suwaka', () => {
  renderSlider({ value: 0.6, scores: [0.55, 0.6] })

  const cells = screen.getAllByTestId('score-bucket')

  expect((cells[11].firstElementChild as HTMLElement).className).toContain('bg-not-listed')
  expect((cells[12].firstElementChild as HTMLElement).className).toContain('bg-suspected')
  expect(screen.getByTestId('score-threshold-line').getAttribute('style')).toContain('left: 60%')
})

// Histogram jest ilustracja: kontrolka zostaje jedna i ma etykiete, ktora czyta czytnik ekranu.
it('nie tworzy drugiego suwaka razem z wykresem', () => {
  renderSlider({ scores: [0.1, 0.52, 0.9] })

  expect(screen.getAllByRole('slider')).toHaveLength(1)
  expect(screen.getByLabelText('Suspicion threshold')).toBe(slider())
  expect(screen.getByTestId('score-histogram').getAttribute('aria-hidden')).toBe('true')
})
