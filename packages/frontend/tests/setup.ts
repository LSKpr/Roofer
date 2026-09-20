import { JSDOM } from 'jsdom'

const { window } = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/',
  pretendToBeVisual: true,
})

function define(key: string, value: unknown) {
  Object.defineProperty(globalThis, key, { value, configurable: true, writable: true })
}

define('window', window)
define('document', window.document)
define('navigator', window.navigator)
define('IS_REACT_ACT_ENVIRONMENT', true)

const source = window as unknown as Record<string, unknown>
for (const key of Object.getOwnPropertyNames(window)) {
  if (key in globalThis) continue
  define(key, source[key])
}
