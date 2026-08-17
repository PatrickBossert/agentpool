// ui/src/components/AgentStatusTab.tsx
// What has happened to an agent's work: its runs, its versions, and the actions that act on
// a version rather than on the current artefact.
//
// Revert, reject, revise and the version list all moved here from the Output tab. Reverting
// is a fact about history, not an edit - and grouping the four keeps the rule stateable in
// one sentence: Output is where you change the artefact, Status is where you see what has
// happened to it.
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  RotateCcw, History, Check, X, AlertTriangle, ChevronDown, ChevronRight, Ban,
} from 'lucide-react'
import { projectsApi } from '../api/endpoints'
import { MermaidThumbnail, DiagramLightbox, CREW_WARNING_SOURCE } from './ReviewDialog'
import ValidationWarnings from './ValidationWarnings'
import { CREW_LABELS, CREW_DOWNSTREAM, CREW_AGENTS, AGENT_AVATAR, AGENT_AVATAR_IMAGE, AGENT_HUMAN_NAME } from './agentStatus'
import type { CrewStatus } from './agentStatus'
import { CREW_OUTPUT_TYPE, parseDbDate } from './crewOutputs'
import { outputLabel } from './outputTypeLabels'
import { bcp47 } from '../utils/holidays'
import type { AgentOutput, CrewRun } from '../types'
import type { StatusEvent } from './AgentDetailPanel'

// Output types this tab's non-primary list should not show for a given crew.
//
// Declaring a primary (CREW_OUTPUT_TYPE) states positively what the Output tab is for; this
// list survives only for what Status then chooses to list beside it, and applies to nothing
// else. It used to run over the whole crew output array in AgentDetailPanel, which meant a
// crew whose primary matched its own hidden prefix - Maya's did - lost the artefact its
// Output tab exists to show.
//
// Only suffixes remain. Maya Patel's *_interview_summaries are a synthesis of interview
// results, which is Casey Liu's job; they were removed from her task, but historical rows
// stay in the database for audit and this list shows every version, not just current ones.
// The old `interview_scripts` prefix entry is gone deliberately: her twenty script siblings
// are an instruction-following defect to be fixed at source, and listing them here is more
// honest than hiding them.
const CREW_HIDDEN_OUTPUT_SUFFIXES: Record<string, string[]> = {
  assessment_design: ['interview_summaries'],
}

function isHiddenFromStatusList(crewKey: string, outputType: string): boolean {
  return (CREW_HIDDEN_OUTPUT_SUFFIXES[crewKey] ?? []).some(sfx => outputType.endsWith(sfx))
}

// value_chain stays here: legacy diagram outputs from before the value chain model existed
// still exist in real projects and still render correctly as diagrams in this Status tab's
// version list. value_chain_model is JSON with no fence, so it is deliberately absent.
export const MERMAID_OUTPUT_TYPES = new Set(['value_chain', 'architecture', 'roadmap'])

// ── Value-chain diagram parser ─────────────────────────────────────────────────

interface L1Summary {
  name: string
  l2Count: number
  l3Count: number
  entities: string[]
}

function parseMermaidValueChain(content: string): L1Summary[] {
  const body = content.replace(/^```mermaid\s*/m, '').replace(/```\s*$/m, '')

  // Match node definitions: id["label"]:::className
  const nodeRegex = /(\w+)\["((?:[^"\\]|\\.)*)"\]:::([\w]+)/g
  const nodes = new Map<string, { label: string; cls: string }>()
  let m: RegExpExecArray | null
  while ((m = nodeRegex.exec(body)) !== null) {
    const [, id, labelRaw, cls] = m
    nodes.set(id, { label: labelRaw.replace(/\\n/g, '\n'), cls })
  }

  // Group node IDs by class pattern l{1|2|3}{group}
  const groups = new Map<string, { l1: string[]; l2: string[]; l3: string[] }>()
  for (const [id, { cls }] of nodes) {
    const hit = cls.match(/^(l[123])(.+)$/)
    if (!hit) continue
    const [, level, group] = hit
    if (!groups.has(group)) groups.set(group, { l1: [], l2: [], l3: [] })
    const g = groups.get(group)!
    if (level === 'l1') g.l1.push(id)
    else if (level === 'l2') g.l2.push(id)
    else g.l3.push(id)
  }

  // Strip leading emoji and misc symbols (covers ⚙ U+2699, 🏛 U+1F3DB, etc.)
  const SYMBOL_RE = /^[\s☀-➿\u{1F000}-\u{1FFFF}]+/gu

  function extractEntities(labels: string[]): string[] {
    const seen = new Set<string>()
    for (const lbl of labels) {
      const parts = lbl.split(/─{3,}/)
      if (parts.length < 2) continue
      for (const line of parts[parts.length - 1].split('\n')) {
        const cleaned = line.replace(new RegExp(SYMBOL_RE.source, 'gu'), '')
          .replace(/\(.*?\)/g, '').trim()
        if (cleaned.length > 2 && !cleaned.startsWith('(')) seen.add(cleaned)
      }
    }
    return [...seen]
  }

  const result: L1Summary[] = []
  for (const [, { l1: l1Ids, l2: l2Ids, l3: l3Ids }] of groups) {
    for (const l1Id of l1Ids) {
      const { label } = nodes.get(l1Id)!
      const name = label.split('\n')[0]
        .replace(/[☀-➿\u{1F000}-\u{1FFFF}]/gu, '').trim()
      const l2Labels = l2Ids.map(id => nodes.get(id)!.label)
      result.push({ name, l2Count: l2Ids.length, l3Count: l3Ids.length, entities: extractEntities(l2Labels) })
    }
  }
  return result
}

// ── Output item (lazy-load content + inline revision / revert / reject) ────────

function OutputItem({ slug, output, crewKey, allCrewOutputs, locale = 'GB' }: {
  slug: string
  output: AgentOutput
  crewKey: string
  allCrewOutputs: AgentOutput[]
  locale?: string
}) {
  // Previous version of this output type — used by Reject to revert automatically
  const previousVersion = allCrewOutputs.find(
    o => o.agent_name === output.agent_name &&
         o.output_type === output.output_type &&
         o.version === output.version - 1
  )
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  // Revision (current version only)
  const [revisioning, setRevisioning] = useState(false)
  const [revisionNotes, setRevisionNotes] = useState('')
  const [revisionSubmitting, setRevisionSubmitting] = useState(false)
  const [revisionDone, setRevisionDone] = useState(false)
  // Revert (non-current versions only)
  const [showRevertPanel, setShowRevertPanel] = useState(false)
  const [revertLoading, setRevertLoading] = useState(false)
  const [revertDone, setRevertDone] = useState(false)
  // Reject (current version only)
  const [showRejectPanel, setShowRejectPanel] = useState(false)
  const [rejectLoading, setRejectLoading] = useState(false)
  const [rejectDone, setRejectDone] = useState(false)

  const { data: content, isLoading } = useQuery({
    queryKey: ['output-content', slug, output.id],
    queryFn: () => projectsApi.getOutputContent(slug, output.id),
    enabled: expanded,
  })

  const isJson = content?.output_type?.includes('json')
    || content?.content?.trimStart().startsWith('{')
    || content?.content?.trimStart().startsWith('[')

  async function submitRevision() {
    if (!revisionNotes.trim()) return
    setRevisionSubmitting(true)
    try {
      await projectsApi.review(slug, output.id, 'changes_requested', revisionNotes.trim())
      setRevisionDone(true)
      setRevisioning(false)
    } catch {
      // keep form open on error
    } finally {
      setRevisionSubmitting(false)
    }
  }

  async function doRevert(targetId: number) {
    try {
      await projectsApi.revertOutput(slug, targetId)
      qc.invalidateQueries({ queryKey: ['outputs', slug] })
      qc.invalidateQueries({ queryKey: ['status', slug] })
      qc.invalidateQueries({ queryKey: ['reviews', slug] })
    } catch {
      throw new Error('revert failed')
    }
  }

  async function submitRevert() {
    setRevertLoading(true)
    try {
      await doRevert(output.id)
      setRevertDone(true)
    } catch {
      setRevertLoading(false)
    }
  }

  async function submitReject() {
    setRejectLoading(true)
    try {
      if (previousVersion) {
        // Hard reject: revert to the previous version (deletes this one + clears HITL)
        await doRevert(previousVersion.id)
        setRejectDone(true)
        setShowRejectPanel(false)
      } else {
        // No previous version — soft reject in place
        await projectsApi.review(slug, output.id, 'rejected', '')
        setRejectDone(true)
        setShowRejectPanel(false)
      }
    } catch {
      // keep panel open
    } finally {
      setRejectLoading(false)
    }
  }

  const effectiveStatus = rejectDone ? 'rejected' : revisionDone ? 'changes_requested' : output.review_status

  const reviewBadge =
    effectiveStatus === 'changes_requested'
      ? <span className="text-[9px] font-medium text-orange-600 bg-orange-50 border border-orange-200 rounded-full px-1.5 py-0.5 inline-flex items-center gap-0.5"><RotateCcw size={9} className="inline mr-0.5" />Revision requested</span> :
    effectiveStatus === 'approved'
      ? <span className="text-[9px] font-medium text-green-600 bg-green-50 border border-green-200 rounded-full px-1.5 py-0.5 inline-flex items-center gap-0.5"><Check size={9} className="inline mr-0.5" />Approved</span> :
    effectiveStatus === 'rejected'
      ? <span className="text-[9px] font-medium text-red-600 bg-red-50 border border-red-200 rounded-full px-1.5 py-0.5 inline-flex items-center gap-0.5"><X size={9} className="inline mr-0.5" />Rejected</span> :
    null

  const downstream = CREW_DOWNSTREAM[crewKey] ?? []

  return (
    <div className="border border-gray-100 rounded-lg overflow-hidden" data-testid={`output-version-${output.version}`}>
      {/* Header row */}
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-50">
        <button
          onClick={() => setExpanded(v => !v)}
          className="flex items-center gap-2 flex-1 text-left min-w-0 hover:opacity-80 transition-opacity"
        >
          <span className="text-gray-400 flex-shrink-0">{expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}</span>
          <span className="text-xs font-medium text-gray-700 flex-1 truncate">{outputLabel(output.output_type)}</span>
        </button>
        {reviewBadge}
        {output.is_current && (
          <span className="text-[9px] font-medium text-teal-600 bg-teal-50 border border-teal-200 rounded-full px-1.5 py-0.5 flex-shrink-0">Current</span>
        )}
        <span className="text-[10px] text-gray-400 flex-shrink-0">v{output.version}</span>
        <span className="text-[10px] text-gray-400 flex-shrink-0">
          {parseDbDate(output.created_at).toLocaleString(bcp47(locale), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
        </span>
        {/* Action buttons */}
        {output.is_current ? (
          <div className="flex items-center gap-1 flex-shrink-0">
            {!revisioning && !revisionDone && (
              <button
                onClick={e => { e.stopPropagation(); setExpanded(true); setRevisioning(true); setShowRejectPanel(false) }}
                title="Propose a revision to this output"
                className="text-[10px] font-medium text-gray-400 hover:text-orange-600 border border-transparent hover:border-orange-200 rounded px-1.5 py-0.5 transition-colors"
              >
                <span className="flex items-center gap-1"><RotateCcw size={10} />Revise</span>
              </button>
            )}
            {!showRejectPanel && !rejectDone && (
              <button
                onClick={e => { e.stopPropagation(); setExpanded(true); setShowRejectPanel(true); setRevisioning(false) }}
                title="Reject this output"
                className="text-[10px] font-medium text-gray-400 hover:text-red-600 border border-transparent hover:border-red-200 rounded px-1.5 py-0.5 transition-colors"
              >
                <span className="flex items-center gap-1"><Ban size={10} />Reject</span>
              </button>
            )}
          </div>
        ) : (
          !showRevertPanel && !revertDone && (
            <button
              onClick={e => { e.stopPropagation(); setExpanded(true); setShowRevertPanel(true) }}
              title={`Revert to v${output.version} (deletes newer versions)`}
              data-testid={`revert-${output.id}`}
              className="flex-shrink-0 text-[10px] font-medium text-gray-400 hover:text-amber-600 border border-transparent hover:border-amber-200 rounded px-1.5 py-0.5 transition-colors"
            >
              <span className="flex items-center gap-1"><History size={10} />Revert</span>
            </button>
          )
        )}
      </div>

      {/* What the human requested for this version (stored on the prior version's reviewer_notes) */}
      {output.is_current && output.version > 1 && previousVersion?.reviewer_notes && (
        <div className="px-3 py-2 bg-amber-50/60 border-t border-amber-100">
          <p className="text-[10px] font-semibold text-amber-500 uppercase tracking-widest mb-1">
            Revision requested (v{previousVersion.version} → v{output.version})
          </p>
          <div
            className="text-[11px] text-amber-800 leading-relaxed prose prose-sm max-w-none [&_ul]:mt-0.5 [&_li]:my-0 [&_p]:my-0.5 [&_p]:text-[11px] [&_li]:text-[11px]"
            dangerouslySetInnerHTML={{
              __html: DOMPurify.sanitize(
                marked.parse(previousVersion.reviewer_notes, { async: false }) as string
              )
            }}
          />
        </div>
      )}

      {/* Agent's summary of changes made in this version. Teal, not blue: the agent reporting
          what it did is neither a warning (the amber revision-request block above) nor an
          error, and blue-* is not a colour this product uses. */}
      {output.revision_notes && (
        <div className="px-3 py-2 bg-teal-50/60 border-t border-teal-100">
          <p className="text-[10px] font-semibold text-teal-600 uppercase tracking-widest mb-1">Changes in this version</p>
          <div
            className="text-[11px] text-teal-800 leading-relaxed prose prose-sm max-w-none [&_ul]:mt-0.5 [&_li]:my-0 [&_p]:my-0.5 [&_p]:text-[11px] [&_li]:text-[11px]"
            dangerouslySetInnerHTML={{
              __html: DOMPurify.sanitize(
                marked.parse(output.revision_notes, { async: false }) as string
              )
            }}
          />
        </div>
      )}

      {/* Content */}
      {expanded && (
        <div className="border-t border-gray-100">
          {isLoading ? (
            <p className="text-xs text-gray-400 px-3 py-4 text-center animate-pulse">Loading…</p>
          ) : content ? (
            <div className="max-h-72 overflow-y-auto">
              {MERMAID_OUTPUT_TYPES.has(output.output_type) ? (
                <div className="px-3 py-3 space-y-3">
                  {/* Rich-text summary for value chain diagrams */}
                  {output.output_type === 'value_chain' && (() => {
                    const summary = parseMermaidValueChain(content.content)
                    if (!summary.length) return null
                    return (
                      <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5 space-y-2">
                        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
                          {summary.length} L1 process{summary.length !== 1 ? 'es' : ''}
                        </p>
                        {summary.map((proc, i) => (
                          <div key={i} className="space-y-0.5">
                            <p className="text-xs font-semibold text-gray-700">{proc.name}</p>
                            <p className="text-[11px] text-gray-500">
                              {proc.l2Count} L2 step{proc.l2Count !== 1 ? 's' : ''} · {proc.l3Count} L3 sub-step{proc.l3Count !== 1 ? 's' : ''}
                            </p>
                            {proc.entities.length > 0 && (
                              <p className="text-[10px] text-gray-400">{proc.entities.join(' · ')}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    )
                  })()}
                  <div
                    onClick={() => setLightboxOpen(true)}
                    className="cursor-zoom-in"
                    title="Click to expand"
                  >
                    <MermaidThumbnail
                      content={content.content}
                      id={String(output.id)}
                      filename={`${output.output_type}_v${output.version}`}
                    />
                  </div>
                  {lightboxOpen && (
                    <DiagramLightbox
                      content={content.content}
                      outputId={String(output.id)}
                      filename={`${output.output_type}_v${output.version}`}
                      onClose={() => setLightboxOpen(false)}
                    />
                  )}
                </div>
              ) : isJson ? (
                <pre className="text-[11px] font-mono text-gray-700 px-3 py-3 whitespace-pre-wrap break-all leading-relaxed bg-white">
                  {(() => { try { return JSON.stringify(JSON.parse(content.content), null, 2) } catch { return content.content } })()}
                </pre>
              ) : (
                <div
                  className="prose prose-sm max-w-none px-3 py-3 text-xs text-gray-800 [&_pre]:bg-gray-100 [&_pre]:rounded [&_pre_code]:text-gray-800 [&_code]:text-gray-800 [&_code]:bg-gray-100"
                  dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(marked.parse(content.content) as string) }}
                />
              )}
            </div>
          ) : (
            <p className="text-xs text-gray-400 px-3 py-4 text-center">No content available.</p>
          )}

          {/* Inline revision form (current version) */}
          {revisioning && (
            <div className="border-t border-orange-100 bg-orange-50/50 px-3 py-3 space-y-2">
              <p className="text-[10px] font-bold text-orange-700 uppercase tracking-widest">Propose Revision</p>
              <p className="text-[11px] text-orange-600">Describe what should change. Re-run the crew to apply.</p>
              <textarea
                value={revisionNotes}
                onChange={e => setRevisionNotes(e.target.value)}
                placeholder="e.g. Add a separate L1 stream for Risk & Compliance. Rename 'Fleet Services' to 'Vehicle Fleet Management'."
                rows={3}
                autoFocus
                className="w-full resize-none border border-orange-200 rounded-lg px-2.5 py-1.5 text-xs text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-orange-400 bg-white"
              />
              <div className="flex items-center gap-2 justify-end">
                <button
                  onClick={() => { setRevisioning(false); setRevisionNotes('') }}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  Cancel
                </button>
                <button
                  onClick={submitRevision}
                  disabled={!revisionNotes.trim() || revisionSubmitting}
                  className="text-xs font-semibold px-3 py-1 rounded-lg bg-orange-500 hover:bg-orange-600 text-white disabled:opacity-40 transition-colors"
                >
                  {revisionSubmitting ? 'Saving…' : 'Save revision request'}
                </button>
              </div>
            </div>
          )}

          {/* Confirmation after revision saved */}
          {revisionDone && (
            <div className="border-t border-orange-100 bg-orange-50/50 px-3 py-2">
              <p className="text-[11px] text-orange-700">
                Revision request saved. Use <strong>↺ Re-run</strong> in the crew card above to apply it.
              </p>
            </div>
          )}

          {/* Reject confirmation panel (current version) */}
          {showRejectPanel && (
            <div className="border-t border-red-100 bg-red-50/50 px-3 py-3 space-y-2">
              <p className="text-[10px] font-bold text-red-700 uppercase tracking-widest flex items-center gap-1"><Ban size={11} />Reject Output</p>
              {previousVersion ? (
                <p className="text-[11px] text-red-700 leading-relaxed">
                  This version (v{output.version}) will be permanently deleted and v{previousVersion.version} restored as current. Any pending review will be dismissed.
                </p>
              ) : (
                <p className="text-[11px] text-red-700 leading-relaxed">
                  No previous version to restore. This output will be marked as rejected — revise the notes and re-run to replace it.
                </p>
              )}
              <div className="flex items-center gap-2 justify-end">
                <button
                  onClick={() => setShowRejectPanel(false)}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  Cancel
                </button>
                <button
                  onClick={submitReject}
                  disabled={rejectLoading}
                  className="text-xs font-semibold px-3 py-1 rounded-lg bg-red-500 hover:bg-red-600 text-white disabled:opacity-40 transition-colors"
                >
                  {rejectLoading ? 'Rejecting…' : previousVersion ? `Reject and restore v${previousVersion.version}` : 'Confirm reject'}
                </button>
              </div>
            </div>
          )}

          {/* After rejection: offer to revise */}
          {rejectDone && (
            <div className="border-t border-red-100 bg-red-50/50 px-3 py-2 space-y-1">
              <p className="text-[11px] text-red-700">Output marked as rejected.</p>
              <button
                onClick={() => { setRejectDone(false); setRevisioning(true) }}
                className="text-[11px] font-medium text-orange-600 hover:text-orange-700 flex items-center gap-1"
              >
                <RotateCcw size={10} /> Propose a revision and re-run
              </button>
            </div>
          )}

          {/* Revert confirmation panel (non-current versions) */}
          {showRevertPanel && (
            <div className="border-t border-amber-100 bg-amber-50/50 px-3 py-3 space-y-2">
              <p className="text-[10px] font-bold text-amber-700 uppercase tracking-widest flex items-center gap-1"><AlertTriangle size={11} />Revert to v{output.version}</p>
              {revertDone ? (
                <p className="text-[11px] text-green-700">Reverted to v{output.version}. All later versions have been deleted.</p>
              ) : (
                <>
                  <p className="text-[11px] text-amber-800 leading-relaxed">
                    All versions after v{output.version} will be permanently deleted from disk. This cannot be undone.
                  </p>
                  {downstream.length > 0 && (
                    <div className="space-y-0.5">
                      <p className="text-[11px] text-amber-700 font-medium">Re-run these crews afterwards to rebuild downstream outputs:</p>
                      <ul className="space-y-0.5">
                        {downstream.map(d => (
                          <li key={d} className="text-[11px] text-amber-800">· {CREW_LABELS[d]}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div className="flex items-center gap-2 justify-end">
                    <button
                      onClick={() => setShowRevertPanel(false)}
                      disabled={revertLoading}
                      className="text-xs text-gray-400 hover:text-gray-600 disabled:opacity-40"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={submitRevert}
                      disabled={revertLoading}
                      className="text-xs font-semibold px-3 py-1 rounded-lg bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-40 transition-colors"
                    >
                      {revertLoading ? 'Reverting…' : `Revert to v${output.version}`}
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Output summary (client-side count, never a stored field) ───────────────────

// What the Output tab's primary artefact is worth counting, when it's a structured model
// (currently only the value chain). Deliberately looser than the full ValueChainModel shape
// - this only ever reads array lengths, so it should not also enforce every element's
// invariants.
export interface PrimaryModelCounts {
  segments: unknown[]
  activities: unknown[]
  contributions: unknown[]
  tasks: unknown[]
}

// ── AgentStatusTab ───────────────────────────────────────────────────────────

export interface AgentStatusTabProps {
  slug: string
  crewKey: string
  crewRun?: CrewRun
  outputs: AgentOutput[]
  statusEvents: StatusEvent[]
  locale?: string
  primaryModel?: PrimaryModelCounts
  // The resolved status (factoring in isPipelineActive and, crucially, isWaiting), not just
  // crewRun.status - a run row can still say 'running' while the crew is paused on a human
  // review gate, and only the resolved status can tell the two states apart.
  crewStatus: CrewStatus
}

export function AgentStatusTab({
  slug, crewKey, crewRun, outputs, statusEvents, locale = 'GB', primaryModel, crewStatus,
}: AgentStatusTabProps) {
  const agents = CREW_AGENTS[crewKey] ?? []
  const primaryAgent = agents[0] ?? ''
  const primaryAvatar = AGENT_AVATAR[primaryAgent] ?? { gradient: 'from-gray-400 to-gray-600' }
  const primaryHumanName = AGENT_HUMAN_NAME[primaryAgent] ?? primaryAgent
  const firstName = primaryHumanName.split(' ')[0]

  const isRunning = crewStatus === 'running'

  // Read-only here: the Status tab is an artefact's history, and a disposition is a
  // review decision. The review dialog is where it is made.
  const warningSource = CREW_WARNING_SOURCE[crewKey]

  // The primary type's full version list, then every other output type this crew has
  // produced grouped by type - both act on a version rather than the current artefact, so
  // both live here rather than in the Output tab.
  const primaryType = CREW_OUTPUT_TYPE[crewKey]
  const primaryOutputs = primaryType ? outputs.filter(o => o.output_type === primaryType) : []

  const nonPrimaryTypes: string[] = []
  const nonPrimaryByType = new Map<string, AgentOutput[]>()
  for (const o of outputs) {
    if (o.output_type === primaryType) continue
    if (isHiddenFromStatusList(crewKey, o.output_type)) continue
    if (!nonPrimaryByType.has(o.output_type)) {
      nonPrimaryByType.set(o.output_type, [])
      nonPrimaryTypes.push(o.output_type)
    }
    nonPrimaryByType.get(o.output_type)!.push(o)
  }

  return (
    <>
      {/* Run timestamps */}
      {crewRun && (
        <div className="flex gap-4 text-[10px] text-gray-400">
          {crewRun.started_at && <span>Started {new Date(crewRun.started_at + 'Z').toLocaleString(bcp47(locale))}</span>}
          {crewRun.finished_at && <span>Finished {new Date(crewRun.finished_at + 'Z').toLocaleString(bcp47(locale))}</span>}
        </div>
      )}

      {/* Error detail */}
      {crewRun?.status === 'failed' && (crewRun as any).error_detail && (
        <div className="rounded-lg bg-red-50 border border-red-100 p-3">
          <p className="text-[10px] font-bold text-red-500 uppercase tracking-widest mb-1">Error</p>
          <pre className="text-xs text-red-700 whitespace-pre-wrap break-all font-mono">{(crewRun as any).error_detail}</pre>
        </div>
      )}

      {/* Output summary - a count of what the fetched artefact contains, computed
          client-side so it cannot disagree with the artefact it is describing. */}
      {primaryModel && (
        <div data-testid="output-summary" className="rounded-lg bg-gray-50 border border-gray-100 p-3 space-y-0.5">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Summary</p>
          <p className="text-xs text-gray-600">{primaryModel.segments.length} segments</p>
          <p className="text-xs text-gray-600">{primaryModel.activities.length} activities</p>
          <p className="text-xs text-gray-600">{primaryModel.contributions.length} contributions</p>
          <p className="text-xs text-gray-600">{primaryModel.tasks.length} tasks</p>
        </div>
      )}

      {warningSource && (
        <ValidationWarnings slug={slug} source={warningSource} readOnly />
      )}

      {/* Primary type version history */}
      {primaryOutputs.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
            Version history · {primaryOutputs.length}
          </p>
          {primaryOutputs.map(o => (
            <OutputItem key={o.id} slug={slug} output={o} crewKey={crewKey} allCrewOutputs={outputs} locale={locale} />
          ))}
        </div>
      )}

      {/* Non-primary output types - the Output tab only ever shows the primary */}
      {nonPrimaryTypes.map(t => (
        <div key={t} data-testid={`output-type-${t}`} className="space-y-1.5">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
            {outputLabel(t)} · {nonPrimaryByType.get(t)!.length}
          </p>
          {nonPrimaryByType.get(t)!.map(o => (
            <OutputItem key={o.id} slug={slug} output={o} crewKey={crewKey} allCrewOutputs={outputs} locale={locale} />
          ))}
        </div>
      ))}

      {statusEvents.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
            Activity · {statusEvents.length} event{statusEvents.length !== 1 ? 's' : ''}
          </p>
          {statusEvents.map((ev, i) => {
            const isLast = i === statusEvents.length - 1
            return (
              <div
                key={i}
                className={`flex gap-2 items-start rounded-lg px-2 py-1.5 ${
                  isLast && isRunning
                    ? 'bg-teal-50 border border-teal-100'
                    : ev.isToolUse
                      ? 'bg-amber-50 border border-amber-100'
                      : 'bg-gray-50 border border-gray-100'
                }`}
              >
                <span className="text-sm flex-shrink-0 mt-0.5 w-5 text-center">{ev.icon}</span>
                <div className="min-w-0 flex-1">
                  <p className={`text-xs font-medium ${isLast && isRunning ? 'text-teal-800' : 'text-gray-800'}`}>
                    {ev.text}
                    {isLast && isRunning && (
                      <span className="ml-1.5 inline-block w-1 h-1 rounded-full bg-teal-500 animate-pulse align-middle" />
                    )}
                  </p>
                  {ev.sub && (
                    <p className="text-[10px] text-gray-500 mt-0.5 truncate" title={ev.sub}>{ev.sub}</p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      ) : isRunning ? (
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <div className="w-16 h-16 rounded-full overflow-hidden ring-2 ring-teal-400 ring-offset-2 flex-shrink-0">
            {AGENT_AVATAR_IMAGE[primaryAgent] ? (
              <img src={AGENT_AVATAR_IMAGE[primaryAgent]} alt={firstName} className="w-full h-full object-cover" />
            ) : (
              <div className={`w-full h-full bg-gradient-to-br ${primaryAvatar.gradient} flex items-center justify-center text-2xl`}>
                {firstName[0]}
              </div>
            )}
          </div>
          <p className="text-sm font-medium text-gray-700 animate-pulse">{firstName} is working…</p>
          <p className="text-xs text-gray-400">Tool events will appear here</p>
        </div>
      ) : (
        <p className="text-xs text-gray-400 text-center py-12">No activity yet - run this crew to see live updates.</p>
      )}
    </>
  )
}
