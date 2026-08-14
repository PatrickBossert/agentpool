// ui/src/components/tabs/ScriptReviewRow.tsx
// One row of the script review ledger: status, a staleness indicator, and the two actions
// left in the list once reading moved to ScriptReviewPanel - Open, always, and Approve,
// gated on permission and on the script having actually been read.
import { Check, CircleDashed, RotateCcw, ShieldCheck } from 'lucide-react'
import type { ScriptLedgerRow } from '../../types'

const LABEL: Record<ScriptLedgerRow['review_status'], string> = {
  pending: 'Awaiting review',
  reviewed: 'Reviewed',
  approved: 'Approved',
  changes_requested: 'Sent back',
}

const ICON: Record<ScriptLedgerRow['review_status'], typeof Check> = {
  pending: CircleDashed,
  reviewed: Check,
  approved: ShieldCheck,
  changes_requested: RotateCcw,
}

export function ScriptReviewRow(
  { row, onOpen, onApprove, canApprove }: {
    row: ScriptLedgerRow
    onOpen: (scriptId: string) => void
    onApprove: (scriptId: string) => void
    // Absent (or false) hides Approve entirely rather than rendering it disabled - the
    // caller collapses "not permitted" and "permission still loading" into the same value
    // deliberately, since a button that appears and then becomes clickable reads as a bug.
    canApprove: boolean
  },
) {
  // Staleness is computed here from two numbers on the wire rather than sent as a boolean:
  // a server-side flag would be wrong the moment a write landed between query and render.
  // Both fields are nullable - last_version has no default, and backfilled rows carry
  // NULL for it - so a NULL on either side must read as "not stale", never crash.
  const stale = row.reviewed_at_version !== null
    && row.last_version !== null
    && row.reviewed_at_version < row.last_version
  const Icon = ICON[row.review_status]

  return (
    <div className="flex items-center gap-2 py-1.5 text-xs border-b border-surface-raised">
      <Icon size={12} className="text-muted shrink-0" />
      {/* Identity is the node id, not the script id - SC-042 is a citation token that means
          nothing to a reviewer, while 1.4.2 is the reference used everywhere else in the app. */}
      <span className="font-mono text-muted w-20 shrink-0">{row.node_id}</span>
      <span className="text-secondary truncate flex-1">{row.node_label || row.node_id}</span>
      <span className="text-muted shrink-0">{LABEL[row.review_status]}</span>
      <span className="text-muted shrink-0">
        {row.review_count} review{row.review_count === 1 ? '' : 's'}
      </span>
      {stale && (
        <span className="text-amber-600 shrink-0">
          changed since (v{row.reviewed_at_version} → v{row.last_version})
        </span>
      )}
      <button onClick={() => onOpen(row.script_id)}
              className="text-brand hover:underline shrink-0">Open</button>
      {canApprove && (
        <button
          onClick={() => onApprove(row.script_id)}
          disabled={row.review_count === 0}
          className="text-brand hover:underline shrink-0 disabled:opacity-40 disabled:no-underline disabled:cursor-not-allowed"
        >
          Approve
        </button>
      )}
    </div>
  )
}
