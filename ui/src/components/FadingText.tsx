// ui/src/components/FadingText.tsx
import { useEffect, useMemo, useRef, useState } from 'react'

export const FADE_MS = 600
export const MAX_DELAY_MS = 1200

/** Spread the change across a window so the board ripples rather than snapping in unison. */
function hashToDelay(key: string): number {
  let h = 0
  for (let i = 0; i < key.length; i++) h = (Math.imul(31, h) + key.charCodeAt(i)) | 0
  return Math.abs(h) % MAX_DELAY_MS
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

/**
 * Fades out, swaps, and fades back in when `text` changes.
 *
 * Sequential rather than an overlapping crossfade: two absolutely positioned
 * spans would need a fixed width, and these sit inline in cards that size to
 * their content.
 */
export default function FadingText({
  text,
  delayKey,
  className,
}: {
  text: string
  delayKey: string
  className?: string
}) {
  const [displayed, setDisplayed] = useState(text)
  const [visible, setVisible] = useState(true)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const delay = useMemo(() => hashToDelay(delayKey), [delayKey])

  useEffect(() => {
    if (text === displayed) return

    if (prefersReducedMotion()) {
      setDisplayed(text)
      return
    }

    setVisible(false)
    timerRef.current = setTimeout(() => {
      setDisplayed(text)
      setVisible(true)
    }, delay + FADE_MS)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [text, displayed, delay])

  const reduced = prefersReducedMotion()
  return (
    <span
      className={className}
      style={{
        opacity: visible ? 1 : 0,
        transition: reduced ? undefined : `opacity ${FADE_MS}ms ease-in-out`,
        transitionDelay: reduced ? undefined : `${delay}ms`,
      }}
    >
      {displayed}
    </span>
  )
}
