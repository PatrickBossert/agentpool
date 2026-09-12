// ui/src/components/tabs/ItemReviewPanel.tsx
// Where a human records a conclusion about one value chain node or one value lever.
//
// ScriptReviewPanel is the precedent and this follows it, with one deliberate difference:
// it has two exits, not three. The third there is "Save changes", which records an `edited`
// review after a save lands. There is nothing to save here - a lever is review-only by
// decision, and the value chain model has its own editor on the same tab - so a third button
// would have had nothing to write. The review is still the artefact of having opened this
// panel rather than something bolted onto a list row.
import { useState } from 'react'
import { Check, RotateCcw } from 'lucide-react'
import { projectsApi } from '../../api/endpoints'
import { describeError } from '../../utils/describeError'
import type { ReviewableItem } from './ItemReviewRow'

const BTN = 'text-xs px-3 py-1.5 rounded transition-colors whitespace-nowrap'

export type ItemKind = 'node' | 'lever'

// Which client function each kind sends through, declared once. The two doors take different
// paths on the server, so this is the whole of the kind's effect on what is sent - and
// ItemReviewPanel.test.tsx drives both kinds rather than one, because a map like this is
// exactly where one kind's test covers the other's wiring.
const RECORD: Record<ItemKind, (
  slug: string, itemId: string,
  body: { decision: string; notes?: string; return_to?: string },
) => Promise<unknown>> = {
  node: projectsApi.reviewNode,
  lever: projectsApi.reviewLever,
}

const HEADING: Record<ItemKind, string> = {
  node: 'Value chain activity',
  lever: 'Value lever',
}

const META_LABEL: Record<ItemKind, string> = {
  node: 'Level',
  lever: 'Hypothesis',
}

interface Props {
  slug: string
  kind: ItemKind
  item: ReviewableItem
  /** The name to put on the send-back button - resolved from this project's own agent
   *  identity by the caller, never written out here. A persona is renameable and a hard-coded
   *  'Alex' is a second registry free to drift from `agents/identity.py`. */
  agentName: string
  /** GET /my-permissions' can_review, the same authority the door consults. False renders the
   *  item read-only rather than offering exits the server would refuse. Defaults to true so a
   *  caller that has not asked is not silently locked out. */
  canReview?: boolean
  onClose: () => void
}

export function ItemReviewPanel(
  { slug, kind, item, agentName, canReview = true, onClose }: Props,
) {
  const [busy, setBusy] = useState(false)
  const [sendingBack, setSendingBack] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)

  function recordReview(decision: string, extra?: { return_to?: string; notes?: string }) {
    return RECORD[kind](slug, item.item_id, { decision, ...extra })
  }

  async function handleReviewedNoChanges() {
    setError(null)
    setBusy(true)
    try {
      await recordReview('reviewed')
      onClose()
    } catch (err) {
      setError(describeError(err, 'Could not record that review.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleSendBack(target: 'agent' | 'reviewer') {
    setError(null)
    setBusy(true)
    try {
      await recordReview('changes_requested', { return_to: target, notes: note })
      onClose()
    } catch (err) {
      setError(describeError(err, 'Could not send this back.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-white border border-gray-200 rounded-lg shadow-xl w-full max-w-2xl max-h-[92vh] flex flex-col">

        <div className="flex items-start justify-between gap-3 px-5 py-3 border-b border-gray-200 shrink-0">
          <div className="flex-1 min-w-0">
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">
              {HEADING[kind]}
            </p>
            <p className="text-sm font-semibold text-gray-900 truncate">{item.label}</p>
          </div>
          <button onClick={onClose}
                  className="text-gray-400 hover:text-gray-700 text-xl leading-none">×</button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 bg-gray-50/60 space-y-3">
          <dl className="grid grid-cols-[7rem_1fr] gap-y-2 text-xs">
            <dt className="text-gray-400">Id</dt>
            <dd className="font-mono text-gray-800">{item.item_id}</dd>
            <dt className="text-gray-400">{META_LABEL[kind]}</dt>
            <dd className="text-gray-700">{item.meta || 'not recorded'}</dd>
            <dt className="text-gray-400">Review state</dt>
            <dd className="text-gray-700">
              {item.review_count} review{item.review_count === 1 ? '' : 's'} recorded
            </dd>
            <dt className="text-gray-400">Version</dt>
            <dd className="text-gray-700">
              {item.last_version === null ? 'not yet written' : `v${item.last_version}`}
            </dd>
          </dl>
          {/* The id is permanent and the label is not, which is the reason per-item review
              works at all - a reviewer cites 3.3.3 or LV-001 and it still means the same
              thing after a regeneration rewords it. */}
          <p className="text-[11px] text-gray-500 leading-relaxed">
            This records a judgement about {item.item_id} as it currently stands. The id is
            permanent; the wording above is not, and a regeneration is free to change it.
          </p>
        </div>

        <div className="border-t border-gray-200 px-5 py-3 shrink-0 space-y-2">
          {error && <p className="text-xs text-red-600">{error}</p>}

          {!canReview ? (
            <p className="text-xs text-gray-500 text-right">
              You can read this, but not review it. Ask an assigned reviewer or approver to
              record a decision.
            </p>
          ) : sendingBack ? (
            <div className="space-y-2">
              <label htmlFor="item-review-feedback" className="text-xs text-gray-600 block">
                Feedback
              </label>
              <textarea
                id="item-review-feedback"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                placeholder="What needs to change?"
                className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 outline-none focus:border-brand"
              />
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => { setSendingBack(false); setNote('') }}
                  className={`${BTN} text-gray-400 hover:text-gray-700`}
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleSendBack('reviewer')}
                  disabled={busy}
                  className={`${BTN} border border-gray-200 text-gray-600 hover:border-gray-400 disabled:opacity-50`}
                >
                  To reviewers
                </button>
                <button
                  onClick={() => handleSendBack('agent')}
                  // A regeneration request with no guidance tells the agent nothing - disabled
                  // until there is a note to send with it.
                  disabled={busy || !note.trim()}
                  className={`${BTN} bg-brand hover:bg-brand-dark disabled:opacity-50 text-white`}
                >
                  To {agentName}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setSendingBack(true)}
                disabled={busy}
                className={`${BTN} border border-gray-200 text-gray-600 hover:border-gray-400 disabled:opacity-50`}
              >
                <RotateCcw size={12} className="inline mr-1" /> Send back
              </button>
              <button
                onClick={handleReviewedNoChanges}
                disabled={busy}
                className={`${BTN} bg-brand hover:bg-brand-dark disabled:opacity-50 text-white`}
              >
                <Check size={12} className="inline mr-1" /> Reviewed, no changes
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
