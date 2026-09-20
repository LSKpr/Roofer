import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ThresholdSlider } from './ThresholdSlider'

type Options = {
  value?: number
  onChange?: (value: number) => void
  modelDefault?: number
  className?: string
}

function renderSlider(options: Options = {}) {
  return render(
    <ThresholdSlider
      value={options.value ?? 0.5}
      onChange={options.onChange ?? (() => {})}
      modelDefault={options.modelDefault ?? 0.5}
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
