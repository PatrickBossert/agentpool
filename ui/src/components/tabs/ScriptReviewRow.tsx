// ui/src/components/tabs/ScriptReviewRow.tsx
// One row of the script review ledger: status, a staleness indicator, and the two actions
// (mark reviewed, send back) that drive the review endpoints from Task 5.
import { useState } from 'react'
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
    // notes and returnTo travel together: returnTo decides whether Maya regenerates the
    // script (`agent`) or a human picks the thread back up (`reviewer`), and notes is the
    // text injected into Maya's prompt when it does. Neither has a meaning on its own for
    // 'reviewed' or 'approved', so both stay optional rather than always-required.
    onReview: (scriptId: string, decision: string, returnTo?: string, notes?: string) => void
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

  // The send-back form is inline and collapsed by default - this is a ledger row, not the
  // review workbench - but it must collect both a note and a target before it can send,
  // because the target is what decides whether Maya regenerates the script at all.
  const [sendingBack, setSendingBack] = useState(false)
  const [note, setNote] = useState('')

  function submitSendBack(target: 'agent' | 'reviewer') {
    onReview(row.script_id, 'changes_requested', target, note)
    setSendingBack(false)
    setNote('')
  }

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
      {sendingBack ? (
        <div className="flex items-center gap-1 shrink-0">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What needs to change?"
            aria-label="Send-back note"
            className="text-xs border border-surface-raised rounded px-1.5 py-0.5 w-40 bg-transparent text-primary"
          />
          <button onClick={() => submitSendBack('agent')}
                  className="text-brand hover:underline shrink-0">To agent</button>
          <button onClick={() => submitSendBack('reviewer')}
                  className="text-muted hover:underline shrink-0">To reviewer</button>
          <button onClick={() => { setSendingBack(false); setNote('') }}
                  className="text-muted hover:underline shrink-0">Cancel</button>
        </div>
      ) : (
        <>
          <button onClick={() => onReview(row.script_id, 'reviewed')}
                  className="text-brand hover:underline shrink-0">Mark reviewed</button>
          <button onClick={() => setSendingBack(true)}
                  className="text-muted hover:underline shrink-0">Send back</button>
        </>
      )}
    </div>
  )
}
