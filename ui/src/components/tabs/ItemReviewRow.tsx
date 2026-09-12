// ui/src/components/tabs/ItemReviewRow.tsx
// One row of a per-item review ledger - a value chain node or a value lever.
//
// The node and the lever ledgers differ in three column names and nothing this row cares
// about, so the row takes a normalised item rather than a union of the two wire shapes. The
// mapping from each wire row to this shape is where "a node shows its id, label and level"
// and "a lever shows its id, title and status" is actually decided, and it lives in
// DiscoveryReviewExtra where both are in front of the reader at once.
import { Check, CircleDashed, RotateCcw, ShieldCheck } from 'lucide-react'
import type { ItemReviewStatus } from '../../types'

// Keyed on the full union so adding a review_status without a label or an icon is a compile
// error. Exported because ItemReviewRow.test.tsx checks both maps against
// item_review_service.VALID_DECISIONS - the producer - rather than against a list copied out
// of here, which would agree with itself for ever.
//
// No 'edited'. The script ledger has one because a reader can change a script in front of
// them; there is nothing to change here, so the vocabulary is three and the absence is
// asserted rather than merely true today.
export const LABEL: Record<ItemReviewStatus, string> = {
  pending: 'Awaiting review',
  reviewed: 'Reviewed',
  approved: 'Approved',
  changes_requested: 'Sent back',
}

export const ICON: Record<ItemReviewStatus, typeof Check> = {
  pending: CircleDashed,
  reviewed: Check,
  approved: ShieldCheck,
  changes_requested: RotateCcw,
}

/** One reviewable item, in the shape this row draws, whichever ledger it came from. */
export interface ReviewableItem {
  /** The permanent id - `3.3.3` or `LV-001`. Displayed, because a reviewer cites it. */
  item_id: string
  /** What the id means today: a node's label, a lever's title. Free to be reworded. */
  label: string
  /** The item's own secondary fact - a node's level, a lever's hypothesis status. */
  meta: string
  review_status: ItemReviewStatus
  reviewed_at_version: number | null
  last_version: number | null
  review_count: number
}

export function ItemReviewRow(
  { item, onOpen, onApprove, canApprove }: {
    item: ReviewableItem
    onOpen: (itemId: string) => void
    onApprove: (itemId: string) => void
    // Absent or false hides Approve entirely rather than rendering it disabled - "not
    // permitted" and "permission still loading" collapse into one value deliberately, since
    // a button that appears and then becomes clickable reads as a bug.
    canApprove: boolean
  },
) {
  // Computed here from two numbers on the wire rather than sent as a boolean: a server-side
  // flag would be wrong the moment a write landed between query and render. Both fields are
  // nullable - last_version has no default and a backfilled row carries NULL - so a NULL on
  // either side must read as "not stale" rather than crash or mislead.
  const stale = item.reviewed_at_version !== null
    && item.last_version !== null
    && item.reviewed_at_version < item.last_version
  // Both lookups carry a fallback the types say is unreachable, and it is not defensive
  // clutter: review_status is an unconstrained TEXT column with no CHECK, written straight
  // from a decision string, so the wire can hand this component a value neither map knows.
  // Without the ?? the missing entry reaches JSX as `undefined`, React throws "Element type
  // is invalid", and there is no error boundary anywhere on the Output tab - one unknown
  // status takes the whole tab down.
  const Icon = ICON[item.review_status] ?? CircleDashed
  const label = LABEL[item.review_status] ?? item.review_status

  return (
    <div className="flex items-center gap-2 py-1.5 text-xs border-b border-surface-raised">
      <Icon size={12} className="text-muted shrink-0" />
      <span className="font-mono text-muted w-20 shrink-0">{item.item_id}</span>
      <span className="text-secondary truncate flex-1">{item.label || item.item_id}</span>
      {item.meta && <span className="text-muted shrink-0">{item.meta}</span>}
      <span className="text-muted shrink-0">{label}</span>
      <span className="text-muted shrink-0">
        {item.review_count} review{item.review_count === 1 ? '' : 's'}
      </span>
      {stale && (
        <span className="text-amber-600 shrink-0">
          changed since (v{item.reviewed_at_version} → v{item.last_version})
        </span>
      )}
      <button onClick={() => onOpen(item.item_id)}
              className="text-brand hover:underline shrink-0">Open</button>
      {canApprove && (
        <button
          onClick={() => onApprove(item.item_id)}
          disabled={item.review_count === 0}
          className="text-brand hover:underline shrink-0 disabled:opacity-40 disabled:no-underline disabled:cursor-not-allowed"
        >
          Approve
        </button>
      )}
    </div>
  )
}
