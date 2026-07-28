import { render, screen, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import FadingText, { FADE_MS, MAX_DELAY_MS } from '../components/FadingText'

function mockReducedMotion(reduce: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduce && query === '(prefers-reduced-motion: reduce)',
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

beforeEach(() => {
  vi.useFakeTimers()
  mockReducedMotion(false)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('FadingText', () => {
  it('shows its initial text immediately', () => {
    render(<FadingText text="Morning yoga" delayKey="pam" />)
    expect(screen.getByText('Morning yoga')).toBeInTheDocument()
  })

  it('keeps showing the old text while fading out', () => {
    const { rerender } = render(<FadingText text="Morning yoga" delayKey="pam" />)
    rerender(<FadingText text="In the sauna" delayKey="pam" />)
    expect(screen.getByText('Morning yoga')).toBeInTheDocument()
  })

  it('shows the new text once the fade completes', () => {
    const { rerender } = render(<FadingText text="Morning yoga" delayKey="pam" />)
    rerender(<FadingText text="In the sauna" delayKey="pam" />)
    act(() => { vi.advanceTimersByTime(FADE_MS + MAX_DELAY_MS) })
    expect(screen.getByText('In the sauna')).toBeInTheDocument()
  })

  it('swaps instantly under prefers-reduced-motion', () => {
    mockReducedMotion(true)
    const { rerender } = render(<FadingText text="Morning yoga" delayKey="pam" />)
    rerender(<FadingText text="In the sauna" delayKey="pam" />)
    expect(screen.getByText('In the sauna')).toBeInTheDocument()
  })

  it('gives different keys different delays so the board ripples', () => {
    const { container: a } = render(<FadingText text="x" delayKey="pam" />)
    const { container: b } = render(<FadingText text="x" delayKey="discovery" />)
    const delayOf = (c: HTMLElement) =>
      (c.firstElementChild as HTMLElement).style.transitionDelay
    expect(delayOf(a)).not.toEqual(delayOf(b))
  })
})
