// ui/src/components/tabs/MayaOutputExtra.tsx
// Maya's Output tab extra: generated interview scripts organised by level
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { projectsApi } from '../../api/endpoints'
import { ScriptReviewRow } from './ScriptReviewRow'
import { ScriptReviewPanel } from './ScriptReviewPanel'
import type { InterviewQuestion, InterviewScript, InterviewSection } from '../../types'

// The server's own explanation - 403 (not a reviewer/approver), 409 (already approved), 422
// (a send-back with no valid target) - beats a fixed string, because a fixed string cannot
// tell the person which of those three happened. Mirrors describeError in
// InterviewTemplateEditor.tsx, which closed the same gap for the script editor's save path.
function describeError(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
  }
  return fallback
}

const LEVEL_BADGE: Record<string, string> = {
  L0: 'bg-purple-100 text-purple-700',
  L1: 'bg-indigo-100 text-indigo-700',
  L2: 'bg-blue-100 text-blue-700',
  L3: 'bg-teal-100 text-teal-700',
  C:  'bg-amber-100 text-amber-700',
  A:  'bg-red-100 text-red-700',
  F:  'bg-orange-100 text-orange-700',
  S:  'bg-emerald-100 text-emerald-700',
}

const LEVEL_TITLE: Record<string, string> = {
  L0: 'Portfolio / Board',
  L1: 'GM / Value Stream',
  L2: 'Process Manager',
  L3: 'Practitioner',
  C:  'Customer',
  A:  'Auditor / Regulator',
  F:  'Frontline Worker',
  S:  'Corporate Services',
}

function Block({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-1">{label}</p>
      {children}
    </div>
  )
}

function Spoken({ text }: { text: string }) {
  return (
    <p className="text-[11px] text-gray-700 leading-relaxed italic border-l-2 border-gray-200 pl-2">
      {text}
    </p>
  )
}

function QuestionBlock({ q, index }: { q: InterviewQuestion; index: number }) {
  return (
    <div className="pl-2 border-l-2 border-gray-200 space-y-1.5">
      <div className="flex items-start gap-2">
        <span className="text-[9px] font-mono text-gray-400 mt-0.5 flex-shrink-0">{q.id || `Q${index + 1}`}</span>
        <p className="text-[11px] text-gray-800 leading-relaxed flex-1">{q.text}</p>
      </div>

      {q.probing_instructions && (
        <div>
          <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest">Probing</p>
          <p className="text-[10px] text-gray-600 leading-relaxed">{q.probing_instructions}</p>
        </div>
      )}

      {q.follow_up_branches?.length > 0 && (
        <div>
          <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest">
            Follow-ups ({q.follow_up_branches.length})
          </p>
          <ul className="space-y-0.5 mt-0.5">
            {q.follow_up_branches.map((b, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <span className="text-gray-300 mt-0.5 flex-shrink-0 text-[10px]">→</span>
                <p className="text-[10px] text-gray-600 leading-relaxed">{b}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {q.evasion_signals?.length > 0 && (
        <div>
          <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest">Evasion signals</p>
          <div className="flex flex-wrap gap-1 mt-0.5">
            {q.evasion_signals.map((sig, i) => (
              <span key={i} className="text-[9px] text-amber-700 bg-amber-50 rounded px-1.5 py-0.5 italic">
                “{sig}”
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function SectionBlock({ section, index }: { section: InterviewSection; index: number }) {
  const [open, setOpen] = useState(false)
  const qCount = section.questions?.length ?? 0

  return (
    <div className="rounded border border-gray-200 bg-white overflow-hidden">
      <button
        className="w-full flex items-start gap-2 px-2.5 py-2 text-left hover:bg-gray-50 transition-colors"
        onClick={() => setOpen(v => !v)}
      >
        <span className="mt-0.5 flex-shrink-0 text-gray-300">
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        </span>
        <span className="text-[10px] text-gray-400 font-mono flex-shrink-0 mt-0.5">{index + 1}</span>
        <div className="flex-1 min-w-0">
          <p className="text-[11px] text-gray-700">{section.title}</p>
          <p className="text-[10px] text-gray-400">
            {qCount} question{qCount !== 1 ? 's' : ''}
            {section.target_minutes ? ` · ${section.target_minutes} min` : ''}
            {section.maturity_rating ? ' · maturity rating' : ''}
          </p>
        </div>
      </button>

      {open && (
        <div className="border-t border-gray-100 px-2.5 py-2.5 space-y-3">
          {(section.questions ?? []).map((q, i) => (
            <QuestionBlock key={q.id || i} q={q} index={i} />
          ))}

          {section.maturity_rating && (
            <div className="rounded bg-blue-50/60 px-2 py-1.5">
              <p className="text-[9px] font-bold text-blue-500 uppercase tracking-widest">
                Maturity rating — {section.maturity_rating.dimension}
              </p>
              <p className="text-[10px] text-gray-600 leading-relaxed mt-0.5">{section.maturity_rating.prompt}</p>
              {section.maturity_rating.scale && (
                <ul className="mt-1 space-y-0.5">
                  {Object.entries(section.maturity_rating.scale).map(([lvl, desc]) => (
                    <li key={lvl} className="flex items-start gap-1.5">
                      <span className="text-[9px] font-mono text-blue-400 flex-shrink-0 mt-0.5">{lvl}</span>
                      <p className="text-[10px] text-gray-600 leading-relaxed">{desc}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Loose enough for ScriptReviewPanel to open on a script it fetched for editing, and equally
// satisfied by a full InterviewScript from GET /interview-scripts - node_label and sections
// are what ScriptCard actually dereferences without an optional-chain fallback; everything
// else it reads defensively.
export type ReviewableScript = Partial<InterviewScript> & Pick<InterviewScript, 'node_label' | 'sections'>

export function ScriptCard({ script }: { script: ReviewableScript }) {
  const [expanded, setExpanded] = useState(false)
  // Perspective, when the script carries one, is what a stakeholder recognises - "Frontline",
  // not "L1" - so the badge and title read from it first and fall back to the tier. The
  // final '' is a type-safety net, not a state anyone sees - a real InterviewScript always
  // carries level, and ScriptReviewPanel's edit path never touches it.
  const badgeKey = script.perspective ?? script.level ?? ''
  const badgeCls = LEVEL_BADGE[badgeKey] ?? 'bg-gray-100 text-gray-600'
  const totalQuestions = (script.sections ?? []).reduce((n, s) => n + (s.questions?.length ?? 0), 0)

  return (
    <div className="rounded-lg border border-gray-100 overflow-hidden">
      <button
        className="w-full flex items-start gap-2.5 px-3 py-2.5 text-left hover:bg-gray-50 transition-colors"
        onClick={() => setExpanded(v => !v)}
      >
        <span className="mt-0.5 flex-shrink-0 text-gray-300">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5 flex-wrap">
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide ${badgeCls}`}>
              {badgeKey}
            </span>
            <span className="text-[10px] text-gray-500">{LEVEL_TITLE[badgeKey] ?? badgeKey}</span>
            <span className="text-xs font-medium text-gray-800 truncate">{script.node_label}</span>
          </div>
          <p className="text-[10px] text-gray-400 line-clamp-1">{script.research_brief}</p>
        </div>
        <span className="text-[10px] text-gray-300 flex-shrink-0 mt-0.5 whitespace-nowrap">
          {script.sections.length} sections · {totalQuestions} questions
        </span>
      </button>

      {expanded && (
        <div className="border-t border-gray-100 px-3 py-2.5 space-y-3 bg-gray-50/60">
          <p className="text-[9px] font-bold text-gray-500 uppercase tracking-widest border-b border-gray-200 pb-1">
            Research
          </p>
          <div>
            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-1">Research Brief</p>
            <p className="text-[11px] text-gray-700 leading-relaxed">{script.research_brief}</p>
          </div>
          {(script.study_objectives ?? []).length > 0 && (
            <div>
              <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-1">Study Objectives</p>
              <ul className="space-y-0.5">
                {(script.study_objectives ?? []).map((obj, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <span className="text-gray-300 mt-0.5 flex-shrink-0">·</span>
                    <p className="text-[11px] text-gray-600 leading-relaxed">{obj}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-[9px] font-bold text-gray-500 uppercase tracking-widest border-b border-gray-200 pb-1 pt-1">
            Interview script
          </p>

          {script.welcome_message && (
            <Block label="Welcome (spoken)"><Spoken text={script.welcome_message} /></Block>
          )}

          {script.framing_block && (
            <Block label="Framing (spoken)">
              <div className="space-y-1.5">
                <Spoken text={script.framing_block.positioning} />
                {script.framing_block.context_setting?.length > 0 && (
                  <ul className="space-y-0.5">
                    {script.framing_block.context_setting.map((c, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <span className="text-[10px] leading-relaxed text-gray-300 flex-shrink-0">·</span>
                        <p className="text-[10px] text-gray-600 leading-relaxed">{c}</p>
                      </li>
                    ))}
                  </ul>
                )}
                {script.framing_block.dual_lenses && (
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded bg-white px-2 py-1.5">
                      <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest">Efficiency</p>
                      <p className="text-[10px] text-gray-600 leading-relaxed">{script.framing_block.dual_lenses.efficiency}</p>
                    </div>
                    <div className="rounded bg-white px-2 py-1.5">
                      <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest">Effectiveness</p>
                      <p className="text-[10px] text-gray-600 leading-relaxed">{script.framing_block.dual_lenses.effectiveness}</p>
                    </div>
                  </div>
                )}
              </div>
            </Block>
          )}

          <div>
            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">Sections</p>
            <div className="space-y-1">
              {script.sections.map((s, i) => (
                <SectionBlock key={i} section={s} index={i} />
              ))}
            </div>
          </div>

          {script.synthesis_check && (
            <Block label="Synthesis check (spoken after sections)">
              <div className="space-y-1.5">
                <Spoken text={script.synthesis_check.synthesis_prompt} />
                {script.synthesis_check.response_probes && (
                  <div className="space-y-1">
                    {Object.entries(script.synthesis_check.response_probes).map(([k, v]) => (
                      <div key={k} className="flex items-start gap-1.5">
                        <span className="text-[9px] font-mono text-gray-400 flex-shrink-0 mt-0.5 w-16">
                          {k.replace('if_', 'if ')}
                        </span>
                        <p className="text-[10px] text-gray-600 leading-relaxed flex-1">{v}</p>
                      </div>
                    ))}
                  </div>
                )}
                {script.synthesis_check.peer_referral && (
                  <p className="text-[10px] text-gray-600 leading-relaxed">
                    <span className="text-gray-400">Peer referral: </span>{script.synthesis_check.peer_referral}
                  </p>
                )}
                {script.synthesis_check.forward_roadmap && (
                  <p className="text-[10px] text-gray-600 leading-relaxed">
                    <span className="text-gray-400">Forward roadmap: </span>{script.synthesis_check.forward_roadmap}
                  </p>
                )}
              </div>
            </Block>
          )}

          {script.closing_message && (
            <Block label="Closing (spoken)"><Spoken text={script.closing_message} /></Block>
          )}
        </div>
      )}
    </div>
  )
}

export default function MayaOutputExtra({ slug }: { slug: string }) {
  const qc = useQueryClient()
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [openScriptId, setOpenScriptId] = useState<string | null>(null)

  const { data: scriptsMap, isLoading } = useQuery({
    queryKey: ['interview-scripts', slug],
    queryFn: () => projectsApi.getInterviewScripts(slug),
  })

  const { data: ledgerRows, isError: ledgerFailed } = useQuery({
    queryKey: ['script-ledger', slug],
    queryFn: () => projectsApi.getScriptLedger(slug),
  })

  // Undefined while loading collapses into "not permitted" for canApprove below - a missing
  // Approve button while permissions are still in flight, never a disabled one that becomes
  // clickable once the response lands.
  const { data: permissions } = useQuery({
    queryKey: ['my-permissions', slug],
    queryFn: () => projectsApi.getMyPermissions(slug),
  })

  function handleApprove(scriptId: string) {
    setReviewError(null)
    projectsApi
      .reviewScript(slug, scriptId, { decision: 'approved' })
      .then(() => qc.invalidateQueries({ queryKey: ['script-ledger', slug] }))
      .catch((err) => setReviewError(describeError(err, 'Could not approve that script.')))
  }

  function closePanel() {
    setOpenScriptId(null)
    // Both the script content and the ledger row may have changed while the panel was open
    // (a save, a review, a send-back) - the list must reflect either without a manual refresh.
    qc.invalidateQueries({ queryKey: ['interview-scripts', slug] })
    qc.invalidateQueries({ queryKey: ['script-ledger', slug] })
  }

  if (isLoading) {
    return <p className="text-xs text-gray-400 animate-pulse py-3">Loading interview scripts…</p>
  }

  const scripts: InterviewScript[] = Object.values(scriptsMap ?? {})

  if (scripts.length === 0) return null

  // Split on perspective, not level. The previous version filtered on two hardcoded level sets and
  // rendered nothing outside them, so a script with an unexpected level vanished with no message.
  const vcScripts  = scripts.filter(s => !s.perspective)
  const extScripts = scripts.filter(s => !!s.perspective)

  const openScript = openScriptId ? scriptsMap?.[openScriptId] : undefined
  const openRow = openScriptId ? ledgerRows?.find((r) => r.script_id === openScriptId) : undefined

  return (
    <div className="space-y-4">
      {(ledgerFailed || (ledgerRows && ledgerRows.length > 0)) && (
        <div className="space-y-2">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
            Script Review Ledger
          </p>
          {ledgerFailed ? (
            // Distinct from "no rows" - an empty ledger and a failed fetch used to render
            // identically (nothing), leaving no way to tell "could not load" from "nothing
            // to review".
            <p className="text-[11px] text-red-600">Could not load the script review ledger.</p>
          ) : (
            <div>
              {ledgerRows!.map((row) => (
                <ScriptReviewRow
                  key={row.script_id}
                  row={row}
                  onOpen={setOpenScriptId}
                  onApprove={handleApprove}
                  canApprove={!!permissions?.can_approve}
                />
              ))}
            </div>
          )}
          {reviewError && (
            <p className="text-[11px] text-red-600">{reviewError}</p>
          )}
        </div>
      )}
      {vcScripts.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
            Value Chain Interviews
          </p>
          <div className="space-y-1.5">
            {vcScripts.map((s, i) => <ScriptCard key={i} script={s} />)}
          </div>
        </div>
      )}
      {extScripts.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
            External Perspectives
          </p>
          <div className="space-y-1.5">
            {extScripts.map((s, i) => <ScriptCard key={i} script={s} />)}
          </div>
        </div>
      )}
      {openScript && openRow && (
        // can_review was produced by /my-permissions and consumed nowhere. It gates the
        // panel's exits - the same authority the PATCH and the review endpoint now both
        // consult - so a reader who may not review is shown the script rather than three
        // buttons the server would refuse.
        <ScriptReviewPanel slug={slug} script={openScript} row={openRow}
                           canReview={!!permissions?.can_review} onClose={closePanel} />
      )}
    </div>
  )
}
