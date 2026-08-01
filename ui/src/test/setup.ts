import '@testing-library/jest-dom'

// Polyfill ResizeObserver for recharts (not available in jsdom)
if (typeof window !== 'undefined' && !window.ResizeObserver) {
  window.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

// Polyfill localStorage if not available
if (typeof window !== 'undefined') {
  if (!window.localStorage || typeof window.localStorage.clear !== 'function') {
    const store: Record<string, string> = {}
    window.localStorage = {
      getItem: (key: string) => store[key] || null,
      setItem: (key: string, value: string) => {
        store[key] = value
      },
      removeItem: (key: string) => {
        delete store[key]
      },
      clear: () => {
        Object.keys(store).forEach(key => delete store[key])
      },
      key: (index: number) => Object.keys(store)[index] || null,
      length: Object.keys(store).length,
    } as any
  }
}

// Replace the global Request with a permissive stand-in. Vitest's jsdom environment copies
// Node's real fetch/Request onto the test window (jsdom implements neither), but leaves
// jsdom's own AbortController/AbortSignal in place (jsdom does implement those, for
// XMLHttpRequest.abort()). The two are different classes from different realms, so Node's
// real Request constructor - which strictly checks `signal instanceof <its own AbortSignal>`
// - rejects a signal made by jsdom's AbortController with "Expected signal to be an instance
// of AbortSignal". React Router's data routers (createMemoryRouter/createBrowserRouter)
// build one of these on every navigation, including a plain client-side <Navigate>, so any
// test exercising a data router's navigation hits this. No route in this app defines a
// loader, so nothing here needs real fetch Request semantics - a duck-typed stand-in avoids
// the crash without touching application code.
if (typeof window !== 'undefined') {
  class PermissiveRequest {
    url: string
    method: string
    signal?: AbortSignal
    constructor(input: string | URL, init: RequestInit = {}) {
      this.url = String(input)
      this.method = init.method ?? 'GET'
      this.signal = init.signal ?? undefined
    }
  }
  window.Request = PermissiveRequest as unknown as typeof Request
}
