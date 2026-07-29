// ui/src/components/CommitControl.tsx
import { useState } from 'react'

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

  async function commit() {
    setBusy(true)
    try {
      await onCommit(crewName)
    } catch (err) {
      // A rejection (e.g. a 403 from caller_may_commit) would otherwise just
      // re-enable the button with no sign anything went wrong.
      console.error(`Commit failed for crew "${crewName}":`, err)
    } finally {
      setBusy(false)
    }
  }

  return (
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
  )
}
