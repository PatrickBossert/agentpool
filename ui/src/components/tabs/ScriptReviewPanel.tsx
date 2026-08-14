// ui/src/components/tabs/ScriptReviewPanel.tsx
// The document view where a human actually reads a script before reaching a conclusion
// about it. The ledger row's "Mark reviewed" / "Send back" used to be reachable without ever
// seeing the instrument; this renders it (via MayaOutputExtra's ScriptCard, not a second
// renderer) and offers the three exits a reader can take. Each exit records that a human
// read the script - the review is the artefact of having opened this panel, not an
// afterthought bolted onto a list row.
import { useState } from 'react'
import axios from 'axios'
import { Check, ListChecks, RotateCcw, Save } from 'lucide-react'
import { projectsApi } from '../../api/endpoints'
import InterviewTemplateEditor from '../InterviewTemplateEditor'
import { ScriptCard, type ReviewableScript } from './MayaOutputExtra'
import type { ScriptLedgerRow } from '../../types'

// The server's own explanation - a stale-save 409 names who changed it and which version -
// beats a fixed string. Mirrors describeError in InterviewTemplateEditor.tsx and
// MayaOutputExtra.tsx: apiClient is a genuine axios.create() instance, so every error off
// the real request path already carries isAxiosError:true, and axios.isAxiosError gets the
// AxiosError narrowing for free rather than trusting any object that merely has a
// `.response` property.
function describeError(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
  }
  return fallback
}

const BTN = 'text-xs px-3 py-1.5 rounded transition-colors whitespace-nowrap'

interface Props {
  slug: string
  script: ReviewableScript
  row: ScriptLedgerRow
  /** Whether this caller may record a review at all - GET /my-permissions' can_review, which
   *  is now the same authority the PATCH and the review endpoint both consult. False renders
   *  the script read-only rather than offering exits the server would refuse. Optional and
   *  defaulting to true so a caller that has not asked is not silently locked out. */
  canReview?: boolean
  onClose: () => void
}

export function ScriptReviewPanel({ slug, script, row, canReview = true, onClose }: Props) {
  const [title, setTitle] = useState(script.node_label)
  const [saving, setSaving] = useState(false)
  const [busy, setBusy] = useState(false)
  const [sendingBack, setSendingBack] = useState(false)
  const [editingQuestions, setEditingQuestions] = useState(false)
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

  // The full editor saves for itself - it owns the sections, questions, and probes, and it
  // already versions and validates them through the same PATCH. All that is left here is to
  // record that a human read this script and changed it, which is the panel's whole purpose.
  // Recorded after the save landed, same ordering and same reason as handleSaveChanges: a
  // rejected PATCH means nothing was changed, and an 'edited' review claiming otherwise is a
  // lie the ledger cannot retract.
  async function handleQuestionsSaved() {
    setError(null)
    setEditingQuestions(false)
    try {
      await recordReview('edited')
      onClose()
    } catch (err) {
      setError(describeError(err, 'The script was saved, but the review was not recorded.'))
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

          {!canReview ? (
            <p className="text-xs text-gray-500 text-right">
              You can read this script, but not review it. Ask an assigned reviewer or
              approver to record a decision.
            </p>
          ) : sendingBack ? (
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
              {/* Sections, questions, and probes. The header input above edits the title and
                  nothing else, and for the length of this branch that was the only editable
                  thing left anywhere in the application - MayaSetupTab's mount of this editor
                  went with the template-assignment layer and nothing replaced it, so a
                  reviewer who spotted a bad question could only send the whole script back to
                  Maya. This is where that editor was always meant to land. */}
              <button
                onClick={() => setEditingQuestions(true)}
                disabled={busy || saving}
                className={`${BTN} border border-gray-200 text-gray-600 hover:border-gray-400 disabled:opacity-50`}
              >
                <ListChecks size={12} className="inline mr-1" /> Edit questions
              </button>
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

      {editingQuestions && (
        <InterviewTemplateEditor
          slug={slug}
          scriptId={row.script_id}
          nodeLabel={script.node_label}
          activityId={script.node_id ?? null}
          // The same version this panel opened against, so a save that lands behind
          // somebody else's is refused rather than silently overwriting it. The editor
          // PATCHed without it until now, which left the full-editing path carrying the
          // stale-edit hole the title path had already closed.
          baseVersion={row.last_version}
          onClose={() => setEditingQuestions(false)}
          onSaved={handleQuestionsSaved}
        />
      )}
    </div>
  )
}
