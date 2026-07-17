// ui/src/components/RerunDialog.tsx
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { X, Play, RotateCcw, AlertTriangle, MessageSquare, Check, ArrowLeft, Sparkles, ChevronDown, ChevronUp, Loader } from 'lucide-react'
import { projectsApi } from '../api/endpoints'
import { OutputPreview } from './ReviewDialog'
import { CREW_LABELS, CREW_AGENTS } from './agentStatus'
import { skillsApi } from '../api/skills'
import type { AgentOutput } from '../types'

type Step = 'choice' | 'fresh-confirm' | 'revision' | 'revision-done'

const OUTPUT_TYPE_LABELS: Record<string, string> = {
  value_chain:                  'Value Chain',
  interview_scripts:            'Interview Scripts',
  questionnaire_scripts:        'Maturity Questionnaires',
  requirements:                 'Requirements',
  value_levers:                 'Value Levers',
  value_propositions:           'Value Propositions',
  portfolio_register:           'Portfolio Register',
  architecture_blueprint:       'Architecture Blueprint',
  roadmap:                      'Roadmap',
  business_plan:                'Business Plan',
  stakeholder_engagement_plan:  'Stakeholder Engagement Plan',
  interview_transcripts:        'Interview Transcripts',
  activity_insights:            'Activity Insights',
}

function outputLabel(t: string) {
  return OUTPUT_TYPE_LABELS[t] ?? t.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export interface RerunDialogProps {
  slug: string
  crewKey: string
  /** Latest outputs for this crew (state snapshots already excluded) */
  outputs: AgentOutput[]
  /** Names of downstream crew keys that will be invalidated */
  downstream: string[]
  onFreshRun: () => void
  onClose: () => void
}

export default function RerunDialog({
  slug, crewKey, outputs, downstream, onFreshRun, onClose,
}: RerunDialogProps) {
  const qc = useQueryClient()
  const [step, setStep] = useState<Step>('choice')
  // Pre-populate from the most recent reviewer notes for this crew's outputs
  const existingNotes = outputs.find(o => o.reviewer_notes)?.reviewer_notes ?? ''
  const [notes, setNotes] = useState(existingNotes)
  const [submitting, setSubmitting] = useState(false)

  const crewLabel = CREW_LABELS[crewKey] ?? crewKey
  const primaryAgent = CREW_AGENTS[crewKey]?.[0] ?? ''
  const agentFirst = primaryAgent.split(' ')[0]

  // Skill extraction state
  const [learnOpen, setLearnOpen] = useState(false)
  const [learnLoading, setLearnLoading] = useState(false)
  const [learnName, setLearnName] = useState('')
  const [learnDesc, setLearnDesc] = useState('')
  const [learnSubmit, setLearnSubmit] = useState(false)

  async function openLearnCard() {
    setLearnOpen(o => {
      if (!o && notes.trim() && !learnName) {
        // trigger extraction
        setLearnLoading(true)
        skillsApi.extract(notes.trim()).then(r => {
          setLearnName(r.name)
          setLearnDesc(r.description)
        }).finally(() => setLearnLoading(false))
      }
      return !o
    })
  }

  async function saveRevision() {
    if (!notes.trim() || outputs.length === 0) return
    setSubmitting(true)
    try {
      await Promise.all(
        outputs.map(o => projectsApi.review(slug, o.id, 'changes_requested', notes.trim()))
      )
      if (learnOpen && learnSubmit && learnName.trim() && primaryAgent) {
        await skillsApi.create({
          agents: [primaryAgent],
          name: learnName.trim(),
          description: learnDesc.trim(),
          source: 'review',
          source_project: slug,
        })
      }
      qc.invalidateQueries({ queryKey: ['outputs', slug] })
      setStep('revision-done')
    } catch {
      // keep form open
    } finally {
      setSubmitting(false)
    }
  }

  function handleFreshConfirm() {
    onFreshRun()
    onClose()
  }

  const hasDownstream = downstream.length > 0

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-50" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-white rounded-2xl shadow-2xl flex flex-col w-full max-w-xl max-h-[90vh] pointer-events-auto">

          {/* Header */}
          <div className="flex items-center gap-3 px-6 py-4 border-b border-gray-200 flex-shrink-0">
            {step !== 'choice' && (
              <button
                onClick={() => setStep('choice')}
                className="text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0"
                aria-label="Back"
              >
                <ArrowLeft size={16} />
              </button>
            )}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold text-gray-900">{crewLabel}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">
                {step === 'choice'         && 'This crew has already produced outputs.'}
                {step === 'fresh-confirm'  && 'Start fresh'}
                {step === 'revision'       && 'Suggest a revision'}
                {step === 'revision-done'  && 'Revision request saved'}
              </p>
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 flex-shrink-0" aria-label="Close">
              <X size={14} />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">

            {/* ── choice ── */}
            {step === 'choice' && (
              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => setStep(hasDownstream ? 'fresh-confirm' : 'fresh-confirm')}
                  className="flex flex-col items-start gap-3 rounded-xl border-2 border-gray-200 hover:border-teal-300 hover:bg-teal-50/40 p-4 text-left transition-all group"
                >
                  <div className="w-9 h-9 rounded-full bg-gray-100 group-hover:bg-teal-100 flex items-center justify-center transition-colors flex-shrink-0">
                    <Play size={16} className="text-gray-500 group-hover:text-teal-600 transition-colors" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-gray-800 group-hover:text-teal-800">Start fresh</p>
                    <p className="text-xs text-gray-400 mt-1 leading-relaxed">
                      Re-run from scratch, replacing all previous outputs.
                    </p>
                  </div>
                </button>

                <button
                  onClick={() => setStep('revision')}
                  className="flex flex-col items-start gap-3 rounded-xl border-2 border-gray-200 hover:border-orange-300 hover:bg-orange-50/40 p-4 text-left transition-all group"
                >
                  <div className="w-9 h-9 rounded-full bg-gray-100 group-hover:bg-orange-100 flex items-center justify-center transition-colors flex-shrink-0">
                    <MessageSquare size={16} className="text-gray-500 group-hover:text-orange-600 transition-colors" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-gray-800 group-hover:text-orange-800">Suggest a revision</p>
                    <p className="text-xs text-gray-400 mt-1 leading-relaxed">
                      Review the previous output and describe what you'd like changed.
                    </p>
                  </div>
                </button>
              </div>
            )}

            {/* ── fresh-confirm ── */}
            {step === 'fresh-confirm' && (
              <div className="space-y-4">
                {hasDownstream && (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 space-y-2">
                    <p className="text-xs font-bold text-amber-700 uppercase tracking-widest flex items-center gap-1.5">
                      <AlertTriangle size={12} />Downstream impact
                    </p>
                    <p className="text-xs text-amber-800 leading-relaxed">
                      Re-running this crew will invalidate outputs from:
                    </p>
                    <ul className="space-y-0.5">
                      {downstream.map(d => (
                        <li key={d} className="text-xs text-amber-700 flex items-center gap-1.5">
                          <span className="w-1 h-1 rounded-full bg-amber-500 flex-shrink-0" />
                          {CREW_LABELS[d] ?? d}
                        </li>
                      ))}
                    </ul>
                    <p className="text-xs text-amber-600">Those crews will need to be re-run afterwards.</p>
                  </div>
                )}
                {!hasDownstream && (
                  <p className="text-sm text-gray-600 leading-relaxed">
                    All previous outputs for <strong>{crewLabel}</strong> will be replaced.
                    No downstream crews depend on these outputs.
                  </p>
                )}
              </div>
            )}

            {/* ── revision ── */}
            {step === 'revision' && (
              <div className="space-y-5">
                {outputs.length > 0 ? outputs.map(o => (
                  <div key={o.id} className="space-y-2">
                    <div className="flex items-center gap-2">
                      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest flex-1">
                        {outputLabel(o.output_type)}
                      </p>
                      <span className="text-[10px] text-gray-400">v{o.version}</span>
                    </div>
                    <OutputPreview slug={slug} output={o} />
                  </div>
                )) : (
                  <p className="text-xs text-gray-400 text-center py-4">No previous outputs found.</p>
                )}

                <div className="space-y-2 pt-2">
                  <label className="text-[10px] font-bold text-gray-400 uppercase tracking-widest block">
                    What would you like revised?
                  </label>
                  <textarea
                    autoFocus
                    value={notes}
                    onChange={e => setNotes(e.target.value)}
                    placeholder="e.g. Add a separate stream for Risk &amp; Compliance. Rename 'Fleet Services' to 'Vehicle Fleet Management'."
                    rows={4}
                    className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-orange-400 resize-none"
                  />
                  <p className="text-[10px] text-gray-400">
                    These notes will replace any previous revision request. Re-run the crew to apply them.
                  </p>
                </div>

                {/* ── What can they learn? ── */}
                {primaryAgent && notes.trim().length > 10 && (
                  <div className="rounded-xl border border-gray-200 overflow-hidden">
                    <button
                      type="button"
                      onClick={openLearnCard}
                      className="w-full flex items-center gap-2 px-3 py-2.5 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
                    >
                      <Sparkles size={12} className="text-teal-500 flex-shrink-0" />
                      <span className="text-xs font-medium text-gray-600 flex-1">
                        What can {agentFirst} learn from this?
                      </span>
                      {learnOpen ? <ChevronUp size={12} className="text-gray-400" /> : <ChevronDown size={12} className="text-gray-400" />}
                    </button>
                    {learnOpen && (
                      <div className="px-3 pb-3 pt-2 space-y-2">
                        {learnLoading ? (
                          <div className="flex items-center gap-2 py-3">
                            <Loader size={12} className="text-teal-500 animate-spin" />
                            <span className="text-xs text-gray-400">Extracting lesson…</span>
                          </div>
                        ) : (
                          <>
                            <input
                              className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-xs font-semibold text-gray-800 focus:outline-none focus:ring-2 focus:ring-teal-400"
                              placeholder="Skill name"
                              value={learnName}
                              onChange={e => setLearnName(e.target.value)}
                            />
                            <textarea
                              className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-gray-700 leading-relaxed resize-none focus:outline-none focus:ring-2 focus:ring-teal-400"
                              placeholder="Skill description"
                              rows={2}
                              value={learnDesc}
                              onChange={e => setLearnDesc(e.target.value)}
                            />
                            <label className="flex items-center gap-2 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={learnSubmit}
                                onChange={e => setLearnSubmit(e.target.checked)}
                                className="rounded border-gray-300 text-teal-600 focus:ring-teal-500"
                              />
                              <span className="text-xs text-gray-500">
                                Submit this for {agentFirst}'s skills review
                              </span>
                            </label>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* ── revision-done ── */}
            {step === 'revision-done' && (
              <div className="flex flex-col items-center gap-4 py-6 text-center">
                <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center">
                  <Check size={22} className="text-green-600" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-gray-800">Revision request saved</p>
                  <p className="text-xs text-gray-400 mt-1 leading-relaxed max-w-xs">
                    Re-run the crew now to apply your revision, or close and run it later.
                  </p>
                </div>
              </div>
            )}

          </div>

          {/* Footer */}
          {(step === 'fresh-confirm' || step === 'revision') && (
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100 flex-shrink-0 bg-gray-50 rounded-b-2xl">
              <button
                onClick={onClose}
                className="text-sm text-gray-500 hover:text-gray-700 px-4 py-2 rounded-lg transition-colors"
                disabled={submitting}
              >
                Cancel
              </button>
              {step === 'fresh-confirm' && (
                <button
                  onClick={handleFreshConfirm}
                  className="text-sm font-semibold px-5 py-2 rounded-lg bg-teal-600 hover:bg-teal-700 text-white transition-colors"
                >
                  <span className="flex items-center gap-1.5"><Play size={13} />Confirm fresh run</span>
                </button>
              )}
              {step === 'revision' && (
                <button
                  onClick={saveRevision}
                  disabled={!notes.trim() || submitting}
                  className="text-sm font-semibold px-5 py-2 rounded-lg bg-orange-500 hover:bg-orange-600 disabled:opacity-40 text-white transition-colors"
                >
                  {submitting ? 'Saving…' : <span className="flex items-center gap-1.5"><RotateCcw size={13} />Save revision request</span>}
                </button>
              )}
            </div>
          )}
          {step === 'revision-done' && (
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100 flex-shrink-0 bg-gray-50 rounded-b-2xl">
              <button
                onClick={onClose}
                className="text-sm text-gray-500 hover:text-gray-700 px-4 py-2 rounded-lg transition-colors"
              >
                Run later
              </button>
              <button
                onClick={() => { onFreshRun(); onClose() }}
                className="text-sm font-semibold px-5 py-2 rounded-lg bg-teal-600 hover:bg-teal-700 text-white transition-colors"
              >
                <span className="flex items-center gap-1.5"><Play size={13} />Re-run now</span>
              </button>
            </div>
          )}

        </div>
      </div>
    </>
  )
}
