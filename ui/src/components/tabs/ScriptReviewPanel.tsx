// ui/src/components/tabs/ScriptReviewPanel.tsx
// The document view where a human actually reads a script before reaching a conclusion
// about it. The ledger row's "Mark reviewed" / "Send back" used to be reachable without ever
// seeing the instrument; this renders it (via MayaOutputExtra's ScriptCard, not a second
// renderer) and offers the three exits a reader can take. Each exit records that a human
// read the script - the review is the artefact of having opened this panel, not an
// afterthought bolted onto a list row.
import { useState } from 'react'
import { Check, RotateCcw, Save } from 'lucide-react'
import { projectsApi } from '../../api/endpoints'
import { ScriptCard, type ReviewableScript } from './MayaOutputExtra'
import type { ScriptLedgerRow } from '../../types'

// Duck-types the error shape rather than gating on axios's own `isAxiosError` flag. A
// server rejection surfaced through axios always carries `response.data.detail`, and
// nothing here needs the flag to trust that shape - checking for it only means a plain
// object shaped like a failed response (which is exactly what a stale-save 409 looks like
// once axios has unwrapped it) gets treated as untrusted and replaced with a fixed string
// that names none of what went wrong.
function describeError(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: unknown } } }).response
    const detail = response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
  }
  return fallback
}

const BTN = 'text-xs px-3 py-1.5 rounded transition-colors whitespace-nowrap'

interface Props {
  slug: string
  script: ReviewableScript
  row: ScriptLedgerRow
  onClose: () => void
}

export function ScriptReviewPanel({ slug, script, row, onClose }: Props) {
  const [title, setTitle] = useState(script.node_label)
  const [saving, setSaving] = useState(false)
  const [busy, setBusy] = useState(false)
  const [sendingBack, setSendingBack] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)

  const dirty = title !== script.node_label

  function recordReview(decision: string, extra?: { return_to?: string; notes?: string }) {
    return projectsApi.reviewScript(slug, row.script_id, { decision, ...extra })
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

  async function handleSaveChanges() {
    setError(null)
    setSaving(true)
    try {
      // base_version is what closes SP36's stale-edit hole - without it the PATCH has no
      // way to know this save was opened against v3 and not whatever is current now.
      await projectsApi.patchInterviewScript(slug, row.script_id, {
        script: { ...script, node_label: title },
        base_version: row.last_version,
      })
      // Only recorded once the save has actually landed. A rejected PATCH (stale version,
      // validation failure, anything) means the reader has not landed a change, and an
      // 'edited' review claiming otherwise would be a lie the ledger has no way to retract.
      await recordReview('edited')
      onClose()
    } catch (err) {
      setError(describeError(err, 'Save failed.'))
    } finally {
      setSaving(false)
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
      <div className="bg-white border border-gray-200 rounded-lg shadow-xl w-full max-w-3xl max-h-[92vh] flex flex-col">

        {/* Header - the one editable field lives here, not buried in the read-only card */}
        <div className="flex items-start justify-between gap-3 px-5 py-3 border-b border-gray-200 shrink-0">
          <div className="flex-1 min-w-0">
            <label htmlFor="script-review-title" className="text-[10px] font-bold text-gray-400 uppercase tracking-widest block mb-1">
              Script title
            </label>
            <input
              id="script-review-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full text-sm font-semibold text-gray-900 border border-gray-200 rounded px-2 py-1 outline-none focus:border-brand"
            />
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none mt-4">×</button>
        </div>

        {/* Body - reused rendering, not rebuilt */}
        <div className="flex-1 overflow-y-auto p-5 bg-gray-50/60">
          <ScriptCard script={script} />
        </div>

        {/* Footer - the three exits */}
        <div className="border-t border-gray-200 px-5 py-3 shrink-0 space-y-2">
          {error && <p className="text-xs text-red-600">{error}</p>}

          {sendingBack ? (
            <div className="space-y-2">
              <label htmlFor="script-review-feedback" className="text-xs text-gray-600 block">
                Feedback
              </label>
              <textarea
                id="script-review-feedback"
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
                  // A regeneration request with no guidance tells Maya nothing - disabled
                  // until there is a note to send with it.
                  disabled={busy || !note.trim()}
                  className={`${BTN} bg-brand hover:bg-brand-dark disabled:opacity-50 text-white`}
                >
                  To Maya
                </button>
              </div>
            </div>
          ) : (
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setSendingBack(true)}
                disabled={busy || saving}
                className={`${BTN} border border-gray-200 text-gray-600 hover:border-gray-400 disabled:opacity-50`}
              >
                <RotateCcw size={12} className="inline mr-1" /> Send back
              </button>
              <button
                onClick={handleReviewedNoChanges}
                disabled={busy || saving || dirty}
                title={dirty ? 'Save or discard the title change first' : undefined}
                className={`${BTN} border border-gray-200 text-gray-600 hover:border-gray-400 disabled:opacity-50`}
              >
                <Check size={12} className="inline mr-1" /> Reviewed, no changes
              </button>
              <button
                onClick={handleSaveChanges}
                disabled={saving || busy || !dirty}
                className={`${BTN} bg-brand hover:bg-brand-dark disabled:opacity-50 text-white`}
              >
                <Save size={12} className="inline mr-1" /> {saving ? 'Saving…' : 'Save changes'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
