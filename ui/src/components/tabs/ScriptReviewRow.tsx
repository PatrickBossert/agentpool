// ui/src/components/tabs/ScriptReviewRow.tsx
// One row of the script review ledger: status, a staleness indicator, and the two actions
// (mark reviewed, send back) that drive the review endpoints from Task 5.
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
  { row, onReview }: {
    row: ScriptLedgerRow
    onReview: (scriptId: string, decision: string, returnTo?: string) => void
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
      <span className="font-mono text-muted w-16 shrink-0">{row.script_id}</span>
      <span className="text-secondary truncate flex-1">{row.node_label || row.node_id}</span>
      <span className="text-muted shrink-0">{LABEL[row.review_status]}</span>
      {stale && (
        <span className="text-amber-600 shrink-0">
          changed since (v{row.reviewed_at_version} → v{row.last_version})
        </span>
      )}
      <button onClick={() => onReview(row.script_id, 'reviewed')}
              className="text-brand hover:underline shrink-0">Mark reviewed</button>
      <button onClick={() => onReview(row.script_id, 'changes_requested', 'agent')}
              className="text-muted hover:underline shrink-0">Send back</button>
    </div>
  )
}
