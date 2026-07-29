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
}: {
  crewName: string
  changeCount: number
  onCommit: (crewName: string) => void | Promise<void>
}) {
  const [busy, setBusy] = useState(false)

  async function commit() {
    setBusy(true)
    try {
      await onCommit(crewName)
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
          ? `Commit over ${changeCount} change${changeCount === 1 ? '' : 's'}`
          : 'Commit'}
    </button>
  )
}
