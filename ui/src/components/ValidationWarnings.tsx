// ui/src/components/ValidationWarnings.tsx
//
// Structural findings a validator raised on this artefact and did not refuse.
//
// Rendered in the review dialog, where a reviewer chooses approve or changes_requested - a
// warning they never see cannot inform that decision - and read-only in the agent's Status
// tab, this project's home for an artefact's history.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, X } from 'lucide-react'
import { validationsApi } from '../api/endpoints'
import type { ValidationWarning } from '../types'

const TONE: Record<ValidationWarning['disposition'], string> = {
  open: 'border-amber-700/50 bg-amber-950/20',
  acknowledged: 'border-amber-700/50 bg-amber-950/20',
  dismissed: 'border-slate-700/50 bg-surface-card opacity-70',
}

export default function ValidationWarnings({
  slug,
  source,
  readOnly = false,
}: {
  slug: string
  source: string
  readOnly?: boolean
}) {
  const qc = useQueryClient()
  const [dismissing, setDismissing] = useState<number | null>(null)
  const [reason, setReason] = useState('')

  const { data } = useQuery({
    queryKey: ['validation-warnings', slug, source],
    queryFn: () => validationsApi.list(slug, source),
  })

  const dispose = useMutation({
    mutationFn: ({
      id,
      disposition,
      note,
    }: {
      id: number
      disposition: 'acknowledged' | 'dismissed'
      note: string
    }) => validationsApi.dispose(slug, id, disposition, note),
    onSuccess: () => {
      setDismissing(null)
      setReason('')
      qc.invalidateQueries({ queryKey: ['validation-warnings', slug, source] })
    },
  })

  const warnings = data ?? []
  if (warnings.length === 0) return null

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
        Structural warnings
      </p>
      {warnings.map((w) => (
        <div key={w.id} className={`rounded-lg border p-3 ${TONE[w.disposition]}`}>
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-mono text-amber-400 uppercase tracking-wide">
                {w.code}
                {w.subject ? ` - ${w.subject}` : ''}
              </p>
              <p className="text-sm text-slate-300 mt-0.5">{w.detail}</p>

              {w.disposition === 'dismissed' && w.disposition_note && (
                <p className="text-xs text-muted mt-1">Dismissed: {w.disposition_note}</p>
              )}
              {w.disposition === 'acknowledged' && (
                <p className="text-xs text-muted mt-1">
                  Acknowledged - carried into the agent&apos;s next run.
                </p>
              )}

              {!readOnly && w.disposition === 'open' && dismissing !== w.id && (
                <div className="flex gap-2 mt-2">
                  <button
                    type="button"
                    onClick={() =>
                      dispose.mutate({ id: w.id, disposition: 'acknowledged', note: '' })
                    }
                    className="text-xs px-2 py-1 rounded bg-brand/20 text-brand hover:bg-brand/30"
                  >
                    <Check className="w-3 h-3 inline mr-1" />
                    Acknowledge
                  </button>
                  <button
                    type="button"
                    onClick={() => setDismissing(w.id)}
                    className="text-xs px-2 py-1 rounded bg-surface-raised text-secondary hover:text-primary"
                  >
                    <X className="w-3 h-3 inline mr-1" />
                    Dismiss as false positive
                  </button>
                </div>
              )}

              {dismissing === w.id && (
                <div className="mt-2 space-y-2">
                  {/* The API refuses an unexplained dismissal, so the control does too - a
                      dismissal with no reason is indistinguishable from nobody looking. */}
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Why is this a false positive?"
                    className="w-full text-xs bg-surface-raised rounded p-2 text-primary"
                    rows={2}
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={!reason.trim()}
                      onClick={() =>
                        dispose.mutate({
                          id: w.id,
                          disposition: 'dismissed',
                          note: reason.trim(),
                        })
                      }
                      className="text-xs px-2 py-1 rounded bg-brand/20 text-brand disabled:opacity-40"
                    >
                      Dismiss
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setDismissing(null)
                        setReason('')
                      }}
                      className="text-xs px-2 py-1 rounded text-secondary"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
