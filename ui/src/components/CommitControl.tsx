// ui/src/components/CommitControl.tsx
import { useState } from 'react'
import axios from 'axios'

// A 409 means the mid-run guard blocked it (a crew run is in progress); a 403 means
// the caller lacks the role the action requires. Both carry a human-readable detail
// from the API - fall back to a generic sentence only if that is missing.
function describeFailure(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    const message = typeof detail === 'string' ? detail : null
    if (err.response?.status === 409) {
      return message ?? 'A crew run is currently in progress - try again once it finishes.'
    }
    if (err.response?.status === 403) {
      return message ?? 'You do not have permission to do that.'
    }
    if (message) return message
  }
  return 'That failed. Try again.'
}

/**
 * Commit a crew's outputs.
 *
 * The count of outstanding changes is shown rather than blocking on it: an approver
 * holds the governing authority, so they may commit over unaddressed requests - but
 * they should be able to see what they are committing over.
 */
export default function CommitControl({
  crewName,
  changeCount,
  onCommit,
  label = 'Commit',
}: {
  crewName: string
  changeCount: number
  onCommit: (crewName: string) => void | Promise<void>
  label?: string
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function commit() {
    setBusy(true)
    setError(null)
    try {
      await onCommit(crewName)
    } catch (err) {
      // A rejection (e.g. a 403 from caller_may_commit, or a 409 from the mid-run
      // guard) would otherwise just re-enable the button with no sign anything went
      // wrong - the approver would click again and get the same silent failure.
      console.error(`Commit failed for crew "${crewName}":`, err)
      setError(describeFailure(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => void commit()}
        disabled={busy}
        className="text-xs font-semibold text-white bg-brand hover:bg-brand-dark px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
      >
        {busy
          ? 'Committing…'
          : changeCount > 0
            ? `${label} over ${changeCount} change${changeCount === 1 ? '' : 's'}`
            : label}
      </button>
      {error && (
        <span role="alert" className="text-xs text-red-600">
          {error}
        </span>
      )}
    </div>
  )
}
