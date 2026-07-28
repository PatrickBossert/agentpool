// ui/src/components/HeartbeatDot.tsx
import { useEffect, useRef, useState } from 'react'

import { useSchedulerHeartbeat } from '../context/SchedulerHeartbeatContext'

/**
 * Ambient scheduler liveness, and the diagnosis behind it.
 *
 * The dot itself stays deliberately quiet - two colours, no wording, meaningless
 * to anyone who does not know the convention. The panel exists because the colour
 * alone cannot say whether the clock stopped or the API never answered, and those
 * want different actions from whoever is looking.
 */
export default function HeartbeatDot() {
  const { status, lastTickAt, secondsSince, diagnosis, refresh } = useSchedulerHeartbeat()
  const [open, setOpen] = useState(false)
  const [checking, setChecking] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelId = 'heartbeat-panel'

  useEffect(() => {
    if (!open) return

    // Focus was inside the panel when it closed, e.g. "Check again" held it - return
    // focus to the trigger rather than letting it fall to <body>, which would strand
    // a keyboard or screen-reader user with no sense of where they are in the header.
    function restoreFocusIfInsidePanel() {
      if (containerRef.current?.contains(document.activeElement)) {
        triggerRef.current?.focus()
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        restoreFocusIfInsidePanel()
        setOpen(false)
      }
    }
    function onPointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        restoreFocusIfInsidePanel()
        setOpen(false)
      }
    }

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('mousedown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('mousedown', onPointerDown)
    }
  }, [open])

  async function checkAgain() {
    setChecking(true)
    try {
      await refresh()
    } finally {
      setChecking(false)
    }
  }

  const detail = [
    lastTickAt ? `Last tick ${lastTickAt}` : 'No tick recorded',
    secondsSince === null ? null : `${secondsSince}s ago`,
    diagnosis.httpStatus === null ? null : `HTTP ${diagnosis.httpStatus}`,
  ]
    .filter(Boolean)
    .join(' - ')

  return (
    <div ref={containerRef} className="relative flex items-center">
      <button
        ref={triggerRef}
        type="button"
        data-testid="heartbeat-dot-button"
        title={diagnosis.title}
        aria-label={diagnosis.title}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        // Padding rather than a bigger dot: the target is comfortable to hit while
        // the mark itself stays as small and quiet as it was.
        className="p-2 -m-2 flex items-center"
      >
        <span
          data-testid="heartbeat-dot"
          className={`block w-1.5 h-1.5 rounded-full ${
            status === 'alive' ? 'bg-brand opacity-60' : 'bg-gray-300'
          }`}
        />
      </button>

      {open && (
        <div
          id={panelId}
          data-testid="heartbeat-panel"
          className="absolute top-6 left-0 z-50 w-72 rounded-lg border border-gray-200 bg-white p-3 shadow-lg"
        >
          <p className="text-xs font-semibold text-gray-900">{diagnosis.title}</p>
          <p className="text-[11px] text-gray-500 mt-1">{detail}</p>
          {diagnosis.action !== '' && (
            <p className="text-[11px] text-gray-700 mt-2">{diagnosis.action}</p>
          )}
          <button
            type="button"
            onClick={() => void checkAgain()}
            disabled={checking}
            className="mt-3 text-[11px] font-semibold text-brand hover:text-brand-dark disabled:opacity-50"
          >
            {checking ? 'Checking…' : 'Check again'}
          </button>
        </div>
      )}
    </div>
  )
}
