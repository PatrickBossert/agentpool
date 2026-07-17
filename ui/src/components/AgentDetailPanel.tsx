// ui/src/components/AgentDetailPanel.tsx
import { useState, useEffect, useRef, useMemo, type ReactNode, type FC } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  Play, RotateCcw, History, CheckCircle2, XCircle,
  PauseCircle, Check, X, AlertTriangle, Settings,
  ChevronDown, ChevronRight, ArrowRight, ArrowLeft,
  Wrench, MessageSquare, Ban, Trash2, Sparkles, Loader,
} from 'lucide-react'
import { projectsApi } from '../api/endpoints'
import { MermaidThumbnail, DiagramLightbox } from './ReviewDialog'
import { agentChatApi } from '../api/agentChat'
import { skillsApi } from '../api/skills'
import { useAuth } from '../context/AuthContext'
import {
  CREW_LABELS, CREW_AGENTS,
  AGENT_AVATAR, AGENT_AVATAR_IMAGE, AGENT_HUMAN_NAME, AGENT_ROLE, AGENT_SKILLS,
  CREW_DOWNSTREAM, getCrewStatus,
} from './agentStatus'
import { CREW_ICON_COMPONENT } from './crewIcons'
import AgentHoverCard from './AgentHoverCard'
import PamReportView, { PamCrewStatusDetail } from './PamReportView'
import type { CrewRun, AgentOutput, HumanReview } from '../types'
import AlexSetupTab from './tabs/AlexSetupTab'
import MayaSetupTab from './tabs/MayaSetupTab'
import TaylorSetupTab from './tabs/TaylorSetupTab'
import AverySetupTab from './tabs/AverySetupTab'
import AveryOutputExtra from './tabs/AveryOutputExtra'
import LucaOutputExtra from './tabs/LucaOutputExtra'
import PamSetupTab from './tabs/PamSetupTab'

// ── Per-crew slot injection ────────────────────────────────────────────────────

type SlotFC = FC<{ slug: string }>

// Replaces the default Setup tab reads/produces panel for these crews
const CREW_SETUP_OVERRIDE: Partial<Record<string, SlotFC>> = {
  PAM:                    PamSetupTab,
  discovery_mapping:      AlexSetupTab,
  assessment_design:      MayaSetupTab,
  stakeholder_management: TaylorSetupTab,
  discovery_interviews:   AverySetupTab,
}

// Rendered after the DB output list in the Output tab
const CREW_OUTPUT_EXTRA: Partial<Record<string, SlotFC>> = {
  discovery_interviews: AveryOutputExtra,
  delivery:             LucaOutputExtra,
}

marked.use({ async: false, gfm: true, breaks: true })

type Tab = 'output' | 'status' | 'chat' | 'setup' | 'skills'

// ── Static crew metadata ───────────────────────────────────────────────────────

interface CrewMeta {
  reads: string[]
  produces: string[]
  configPage?: string | null
  configLabel?: string
  note?: string
}

const CREW_META: Record<string, CrewMeta> = {
  discovery_mapping: {
    reads: ['Uploaded documents', 'Discovery settings (sector, standards)', 'Existing registry (for iteration)'],
    produces: ['value_chain_registry.json', 'value_chain_tree.json', 'value_chain_summary.txt'],
    configPage: 'value-chain',
    configLabel: 'Configure in Value Chain → Setup',
    note: 'Re-running will preserve existing IDs and extend the registry - existing downstream artefacts reference these IDs.',
  },
  assessment_design: {
    reads: ['value_chain_registry.json', 'value_chain_summary.txt', 'Standards references (from Setup)', 'Project knowledge base'],
    produces: ['interview_scripts.json', 'questionnaire_scripts.json', 'Node template assignments'],
    configPage: 'value-chain',
    configLabel: 'Edit templates in Value Chain → Templates',
    note: 'Runs after value chain mapping is approved. Scripts and questionnaires are designed together for coherence.',
  },
  discovery: {
    reads: ['Uploaded documents', 'Project knowledge base', 'Captured requirements'],
    produces: ['requirements.json', 'value_levers.json'],
    note: 'Discovery can run in parallel with assessment design - it does not depend on interview scripts.',
  },
  stakeholder_management: {
    reads: ['Stakeholder registry', 'Node template assignments', 'Interview session status'],
    produces: ['stakeholder_engagement_plan.json'],
    configPage: 'stakeholders',
    configLabel: 'Manage stakeholders in Stakeholders',
    note: 'This crew actively sends communications and tracks coverage. Re-run at any time to refresh the engagement plan.',
  },
  discovery_interviews: {
    reads: ['interview_scripts.json', 'Stakeholder assignments', 'Interview sessions'],
    produces: ['interview_transcripts.json', 'activity_insights.json'],
    note: 'Interview scripts must be designed (Assessment Design crew) before this crew runs.',
  },
  value_design: {
    reads: ['activity_insights.json', 'value_levers.json', 'requirements.json'],
    produces: ['value_propositions.json', 'portfolio_register.json', 'portfolio.xlsx'],
    note: 'Combines discovery findings and interview insights into a scored initiative portfolio.',
  },
  architecture: {
    reads: ['portfolio_register.json', 'Project knowledge base'],
    produces: ['architecture_blueprint.json', 'architecture_diagram.svg'],
    note: 'Designs the enterprise capability architecture to deliver the prioritised portfolio.',
  },
  delivery: {
    reads: ['architecture_blueprint.json', 'portfolio_register.json'],
    produces: ['roadmap.json', 'roadmap.html', 'roadmap_data.json'],
    configPage: null,
    note: 'Sequences initiatives into a phased roadmap. The HTML output can be opened directly for client presentations.',
  },
  business_plan: {
    reads: ['All prior outputs', 'Financial assumptions'],
    produces: ['business_plan.docx', 'business_plan.pptx', 'financial_model.json'],
    note: 'Compiles the complete investment case. The agent will pause to confirm financial assumptions before modelling.',
  },
}

// ── Tool name labels ───────────────────────────────────────────────────────────

const TOOL_LABELS: Record<string, string> = {
  ChromaQueryTool:        'Searching knowledge base',
  TavilySearchTool:       'Searching the web',
  WebFetchTool:           'Fetching web page',
  DocumentIngestionTool:  'Reading document',
  SQLiteStateTool:        'Reading project state',
  HumanInputTool:         'Requesting human input',
  MermaidRenderTool:      'Rendering diagram',
  HtmlRoadmapTool:        'Generating roadmap',
  ExcelOutputTool:        'Generating Excel file',
  WordOutputTool:         'Generating Word document',
  PowerPointOutputTool:   'Generating PowerPoint',
  FinancialModelTool:     'Running financial model',
  InterviewSessionTool:   'Managing interview session',
  RunCrewTool:            'Dispatching sub-crew',
  SlackNotifyTool:        'Sending Slack notification',
}

interface StatusEvent { ts: number; icon: ReactNode; text: string; sub?: string; isToolUse?: boolean }

function parseStatusEvents(logs: string[], crewKey: string): StatusEvent[] {
  const events: StatusEvent[] = []
  for (const raw of logs) {
    try {
      const obj = JSON.parse(raw)
      if (obj.crew && obj.crew !== crewKey) continue
      if (obj.type === 'crew_started') {
        events.push({ ts: Date.now(), icon: <Play size={12} className="text-teal-600" />, text: 'Started', sub: `Run #${obj.run_id}` })
      } else if (obj.type === 'crew_completed') {
        events.push({ ts: Date.now(), icon: <CheckCircle2 size={12} className="text-green-600" />, text: 'Completed', sub: `Run #${obj.run_id}` })
      } else if (obj.type === 'crew_failed') {
        events.push({ ts: Date.now(), icon: <XCircle size={12} className="text-red-500" />, text: 'Failed', sub: obj.error ?? '' })
      } else if (obj.type === 'agent_step') {
        events.push({ ts: Date.now(), icon: <MessageSquare size={12} className="text-blue-500" />, text: obj.text ?? 'Step complete', sub: obj.sub ?? undefined })
      } else if (obj.type === 'tool_use') {
        events.push({ ts: Date.now(), icon: <Wrench size={12} className="text-amber-500" />, text: TOOL_LABELS[obj.tool] ?? `Using ${obj.tool}`, sub: obj.input ?? undefined, isToolUse: true })
      }
    } catch { /* plain text line */ }
  }
  return events
}

const MERMAID_OUTPUT_TYPES = new Set(['value_chain', 'architecture', 'roadmap'])

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

// Human-readable labels for output_type values stored in the DB
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
  roadmap_data:                 'Roadmap Data',
  business_plan:                'Business Plan',
  stakeholder_engagement_plan:  'Stakeholder Engagement Plan',
  interview_transcripts:        'Interview Transcripts',
  activity_insights:            'Activity Insights',
  initiative_register:          'Initiative Register',
}

// 'state' outputs are internal agent state snapshots (SQLiteStateTool) - not user deliverables
const INTERNAL_OUTPUT_TYPES = new Set(['state'])

function outputLabel(outputType: string): string {
  return OUTPUT_TYPE_LABELS[outputType] ?? outputType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// SQLite timestamps use space separator; convert to ISO 'T' so Date parses correctly in all browsers
function parseDbDate(ts: string | undefined | null): Date {
  if (!ts) return new Date(0)
  return new Date(ts.replace(' ', 'T') + 'Z')
}

// ── Markdown bubble ────────────────────────────────────────────────────────────

function MessageBubble({
  role,
  content,
  agentName,
  slug,
}: {
  role: 'user' | 'agent'
  content: string
  agentName?: string
  slug?: string
}) {
  const html = useMemo(() => {
    if (role !== 'agent') return null
    return DOMPurify.sanitize(marked.parse(content) as string)
  }, [role, content])

  const [saveOpen, setSaveOpen] = useState(false)
  const [saveLoading, setSaveLoading] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveDesc, setSaveDesc] = useState('')
  const [saved, setSaved] = useState(false)

  async function openSaveSkill() {
    if (saveOpen) { setSaveOpen(false); return }
    setSaveOpen(true)
    if (!saveName && content.length > 20) {
      setSaveLoading(true)
      skillsApi.extract(content.slice(0, 800)).then(r => {
        setSaveName(r.name)
        setSaveDesc(r.description)
      }).finally(() => setSaveLoading(false))
    }
  }

  async function submitSkill() {
    if (!agentName || !saveName.trim()) return
    setSaveLoading(true)
    try {
      await skillsApi.create({
        agents: [agentName],
        name: saveName.trim(),
        description: saveDesc.trim(),
        source: 'chat',
        source_project: slug,
      })
      setSaved(true)
      setSaveOpen(false)
    } finally {
      setSaveLoading(false)
    }
  }

  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm px-3 py-2 text-sm bg-teal-600 text-white whitespace-pre-wrap">
          {content}
        </div>
      </div>
    )
  }

  const firstName = agentName?.split(' ')[0] ?? 'agent'

  return (
    <div className="flex justify-start flex-col gap-1">
      <div
        className="max-w-[85%] rounded-2xl rounded-bl-sm px-3 py-2 text-sm bg-gray-100 text-gray-800 prose prose-sm prose-gray max-w-none"
        dangerouslySetInnerHTML={{ __html: html! }}
      />
      {agentName && (
        <div className="pl-1">
          {saved ? (
            <span className="text-[10px] text-green-600 flex items-center gap-1">
              <Check size={9} /> Submitted for skills review
            </span>
          ) : (
            <button
              onClick={openSaveSkill}
              className="text-[10px] text-gray-300 hover:text-teal-500 transition-colors flex items-center gap-0.5"
            >
              <Sparkles size={9} /> Teach {firstName}
            </button>
          )}
          {saveOpen && !saved && (
            <div className="mt-1.5 p-2.5 rounded-xl border border-gray-200 bg-white space-y-2 max-w-[85%]">
              {saveLoading && !saveName ? (
                <div className="flex items-center gap-1.5 py-2">
                  <Loader size={11} className="text-teal-500 animate-spin" />
                  <span className="text-xs text-gray-400">Extracting lesson…</span>
                </div>
              ) : (
                <>
                  <input
                    className="w-full border border-gray-200 rounded-lg px-2 py-1 text-xs font-semibold text-gray-800 focus:outline-none focus:ring-2 focus:ring-teal-400"
                    placeholder="Skill name"
                    value={saveName}
                    onChange={e => setSaveName(e.target.value)}
                  />
                  <textarea
                    className="w-full border border-gray-200 rounded-lg px-2 py-1 text-xs text-gray-600 resize-none focus:outline-none focus:ring-2 focus:ring-teal-400"
                    placeholder="Description"
                    rows={2}
                    value={saveDesc}
                    onChange={e => setSaveDesc(e.target.value)}
                  />
                  <div className="flex justify-end gap-2">
                    <button
                      onClick={() => setSaveOpen(false)}
                      className="text-[10px] text-gray-400 hover:text-gray-600"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={submitSkill}
                      disabled={!saveName.trim() || saveLoading}
                      className="text-[10px] text-white bg-teal-600 hover:bg-teal-700 disabled:opacity-40 px-2 py-1 rounded font-semibold"
                    >
                      {saveLoading ? 'Saving…' : `Submit for review`}
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

// Convert display agent name → DB-stored snake_case key
function agentKey(displayName: string): string {
  return displayName.toLowerCase().replace(/\s+/g, '_')
}

// ── Output item (lazy-load content + inline revision / revert / reject) ────────

function OutputItem({ slug, output, crewKey, allCrewOutputs }: {
  slug: string
  output: AgentOutput
  crewKey: string
  allCrewOutputs: AgentOutput[]
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
    <div className="border border-gray-100 rounded-lg overflow-hidden">
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
          {parseDbDate(output.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
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

      {/* Agent's summary of changes made in this version */}
      {output.revision_notes && (
        <div className="px-3 py-2 bg-blue-50/60 border-t border-blue-100">
          <p className="text-[10px] font-semibold text-blue-500 uppercase tracking-widest mb-1">Changes in this version</p>
          <div
            className="text-[11px] text-blue-800 leading-relaxed prose prose-sm max-w-none [&_ul]:mt-0.5 [&_li]:my-0 [&_p]:my-0.5 [&_p]:text-[11px] [&_li]:text-[11px]"
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

// ── Skills Tab ────────────────────────────────────────────────────────────────

/** Inline card for a pending skill — admin can approve, edit, or reject. */
function PendingSkillCard({
  skill,
  onApprove,
  onReject,
}: {
  skill: import('../api/skills').AgentSkill
  onApprove: (id: number, name: string, description: string) => void
  onReject: (id: number) => void
}) {
  const [name, setName] = useState(skill.name)
  const [desc, setDesc] = useState(skill.description)
  const [editing, setEditing] = useState(false)

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2.5 space-y-2">
      {skill.flag_reason && (
        <div className="flex items-start gap-1.5 text-amber-700">
          <AlertTriangle size={11} className="flex-shrink-0 mt-0.5" />
          <p className="text-[10px] leading-snug">
            Client-specific content detected: {skill.flag_reason}
            {skill.flag_suggestion && (
              <> — suggested reword: <em>{skill.flag_suggestion}</em></>
            )}
          </p>
        </div>
      )}
      {editing ? (
        <>
          <input
            className="w-full border border-amber-300 rounded px-2 py-1 text-xs font-semibold text-gray-800 bg-white focus:outline-none focus:ring-1 focus:ring-amber-400"
            value={name}
            onChange={e => setName(e.target.value)}
          />
          <textarea
            className="w-full border border-amber-300 rounded px-2 py-1 text-[11px] text-gray-700 leading-snug bg-white resize-none focus:outline-none focus:ring-1 focus:ring-amber-400"
            rows={2}
            value={desc}
            onChange={e => setDesc(e.target.value)}
          />
        </>
      ) : (
        <>
          <p className="text-xs font-semibold text-gray-800">{name}</p>
          <p className="text-[11px] text-gray-600 leading-snug">{desc}</p>
        </>
      )}
      <p className="text-[10px] text-amber-600">
        Source: {skill.source}{skill.source_project ? ` · ${skill.source_project}` : ''}
      </p>
      <div className="flex items-center justify-end gap-1.5">
        <button
          onClick={() => setEditing(e => !e)}
          className="text-[10px] text-gray-400 hover:text-gray-600 px-1.5 py-0.5 rounded"
        >
          {editing ? 'Cancel' : 'Edit'}
        </button>
        <button
          onClick={() => onReject(skill.id)}
          className="text-[10px] text-red-400 hover:text-red-600 border border-red-200 px-2 py-0.5 rounded flex items-center gap-0.5"
        >
          <X size={9} /> Reject
        </button>
        <button
          onClick={() => onApprove(skill.id, name, desc)}
          className="text-[10px] text-white bg-teal-600 hover:bg-teal-700 px-2 py-0.5 rounded font-semibold flex items-center gap-0.5"
        >
          <Check size={9} /> Approve
        </button>
      </div>
    </div>
  )
}

/** Inline form to add a new skill directly for an agent. */
type AddSkillStep = 'input' | 'loading' | 'selecting'

interface ExtractedSkill {
  name: string
  description: string
  selected: boolean
}

function AddSkillForm({
  agentName,
  onAdded,
}: {
  agentName: string
  onAdded: () => void
}) {
  const [open, setOpen]     = useState(false)
  const [step, setStep]     = useState<AddSkillStep>('input')
  const [raw, setRaw]       = useState('')
  const [skills, setSkills] = useState<ExtractedSkill[]>([])
  const [saving, setSaving] = useState(false)

  function reset() {
    setStep('input')
    setRaw('')
    setSkills([])
    setOpen(false)
  }

  async function identify() {
    if (!raw.trim()) return
    setStep('loading')
    try {
      const extracted = await skillsApi.extractMany(raw.trim())
      setSkills(extracted.map(s => ({ ...s, selected: true })))
      setStep('selecting')
    } catch {
      setStep('input')
    }
  }

  async function addSelected() {
    const chosen = skills.filter(s => s.selected)
    if (!chosen.length) return
    setSaving(true)
    try {
      await Promise.all(
        chosen.map(s =>
          skillsApi.create({ agents: [agentName], name: s.name.trim(), description: s.description.trim(), source: 'manual' })
        )
      )
      reset()
      onAdded()
    } finally {
      setSaving(false)
    }
  }

  function updateSkill(i: number, field: 'name' | 'description', value: string) {
    setSkills(prev => prev.map((s, idx) => idx === i ? { ...s, [field]: value } : s))
  }

  function toggleSkill(i: number) {
    setSkills(prev => prev.map((s, idx) => idx === i ? { ...s, selected: !s.selected } : s))
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full text-[10px] text-gray-500 hover:text-teal-600 border border-dashed border-gray-300 hover:border-teal-300 rounded-lg py-1.5 transition-colors flex items-center justify-center gap-1"
      >
        + Add skill
      </button>
    )
  }

  return (
    <div className="rounded-lg border border-teal-200 bg-teal-50/40 px-3 py-2.5 space-y-2.5">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-bold text-teal-700 uppercase tracking-widest">
          {step === 'selecting' ? `${skills.length} skill${skills.length === 1 ? '' : 's'} identified` : 'Add skill'}
        </p>
        {step === 'selecting' && (
          <button onClick={() => setStep('input')} className="text-[10px] text-gray-500 hover:text-gray-700">
            ← Edit input
          </button>
        )}
      </div>

      {/* Step 1 — free-form input */}
      {(step === 'input' || step === 'loading') && (
        <>
          <textarea
            autoFocus={step === 'input'}
            className="w-full border border-gray-200 rounded px-2 py-1.5 text-[11px] text-gray-800 leading-relaxed bg-white resize-none focus:outline-none focus:ring-1 focus:ring-teal-400"
            placeholder="Describe what you'd like this agent to know or do. Paste notes, observations, or feature ideas — the system will identify the skills."
            rows={4}
            value={raw}
            onChange={e => setRaw(e.target.value)}
            disabled={step === 'loading'}
          />
          <div className="flex items-center justify-end gap-2">
            <button onClick={reset} className="text-[10px] text-gray-500 hover:text-gray-700">Cancel</button>
            <button
              onClick={identify}
              disabled={!raw.trim() || step === 'loading'}
              className="flex items-center gap-1.5 text-[10px] text-white bg-teal-600 hover:bg-teal-700 disabled:opacity-40 px-2.5 py-1 rounded font-semibold"
            >
              {step === 'loading' ? (
                <><Loader size={10} className="animate-spin" /> Identifying…</>
              ) : (
                <><Sparkles size={10} /> Identify skills</>
              )}
            </button>
          </div>
        </>
      )}

      {/* Step 2 — checkbox selection */}
      {step === 'selecting' && (
        <>
          <div className="space-y-2">
            {skills.map((skill, i) => (
              <label
                key={i}
                className={`flex items-start gap-2.5 rounded-lg border px-2.5 py-2 cursor-pointer transition-colors ${
                  skill.selected
                    ? 'border-teal-200 bg-white'
                    : 'border-gray-100 bg-gray-50 opacity-50'
                }`}
              >
                <input
                  type="checkbox"
                  checked={skill.selected}
                  onChange={() => toggleSkill(i)}
                  className="mt-0.5 rounded border-gray-300 text-teal-600 focus:ring-teal-500 flex-shrink-0"
                />
                <div className="flex-1 min-w-0 space-y-1">
                  <input
                    className="w-full text-xs font-semibold text-gray-800 bg-transparent border-b border-transparent hover:border-gray-200 focus:border-teal-300 focus:outline-none py-0.5"
                    value={skill.name}
                    onChange={e => updateSkill(i, 'name', e.target.value)}
                    onClick={e => e.stopPropagation()}
                  />
                  <textarea
                    className="w-full text-[11px] text-gray-600 leading-relaxed bg-transparent border-b border-transparent hover:border-gray-200 focus:border-teal-300 focus:outline-none resize-none py-0.5"
                    value={skill.description}
                    rows={2}
                    onChange={e => updateSkill(i, 'description', e.target.value)}
                    onClick={e => e.stopPropagation()}
                  />
                </div>
              </label>
            ))}
          </div>
          <div className="flex items-center justify-between pt-0.5">
            <p className="text-[10px] text-gray-500">
              {skills.filter(s => s.selected).length} selected · added as pending
            </p>
            <div className="flex items-center gap-2">
              <button onClick={reset} className="text-[10px] text-gray-500 hover:text-gray-700">Cancel</button>
              <button
                onClick={addSelected}
                disabled={!skills.some(s => s.selected) || saving}
                className="text-[10px] text-white bg-teal-600 hover:bg-teal-700 disabled:opacity-40 px-2.5 py-1 rounded font-semibold"
              >
                {saving ? 'Adding…' : `Add ${skills.filter(s => s.selected).length} skill${skills.filter(s => s.selected).length === 1 ? '' : 's'}`}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function SkillsTabContent({ agents }: { agents: string[] }) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const isAdmin = user?.role === 'sysadmin'

  const { data: approvedSkills = [] } = useQuery({
    queryKey: ['skills', 'approved'],
    queryFn: () => skillsApi.list({ status: 'approved' }),
  })

  const { data: pendingSkills = [] } = useQuery({
    queryKey: ['skills', 'pending'],
    queryFn: () => skillsApi.list({ status: 'pending' }),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof skillsApi.update>[1] }) =>
      skillsApi.update(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['skills'] }),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => skillsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['skills'] }),
  })

  function approve(id: number, name: string, description: string) {
    updateMut.mutate({ id, data: { status: 'approved', name, description } })
  }

  function reject(id: number) {
    updateMut.mutate({ id, data: { status: 'rejected' } })
  }

  // Icon lookup by skill name — built from the full hardcoded AGENT_SKILLS catalogue
  const skillIconByName = useMemo(() => {
    const map = new Map<string, typeof Wrench>()
    for (const skills of Object.values(AGENT_SKILLS)) {
      for (const s of skills) map.set(s.name.toLowerCase(), s.icon)
    }
    return map
  }, [])

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-5">
      {agents.map(agentName => {
        const avatar     = AGENT_AVATAR[agentName] ?? { gradient: 'from-gray-400 to-gray-600' }
        const humanName  = AGENT_HUMAN_NAME[agentName] ?? agentName
        const agentFirst = humanName.split(' ')[0]
        const imageSrc   = AGENT_AVATAR_IMAGE[agentName]
        const role       = AGENT_ROLE[agentName] ?? ''
        const hardcoded      = AGENT_SKILLS[agentName] ?? []
        const agentDB        = approvedSkills.filter(s => s.agents.includes(agentName))
        const dbBaseline     = agentDB.filter(s => s.source === 'baseline')
        const learned        = agentDB.filter(s => s.source !== 'baseline')
        const pending        = pendingSkills.filter(s => s.agents.includes(agentName))
        // Supplement DB baseline with any hardcoded skills not yet seeded
        const dbBaselineNames = new Set(dbBaseline.map(s => s.name.toLowerCase()))
        const hardcodedOnly  = hardcoded.filter(s => !dbBaselineNames.has(s.name.toLowerCase()))

        return (
          <div key={agentName} className="space-y-2">
            {/* Agent header */}
            <div className="flex items-center gap-2.5">
              <AgentHoverCard agentName={agentName}>
                <div className="w-10 h-10 rounded-full overflow-hidden flex-shrink-0 cursor-default">
                  {imageSrc ? (
                    <img src={imageSrc} alt={agentFirst} className="w-full h-full object-cover" />
                  ) : (
                    <div className={`w-full h-full bg-gradient-to-br ${avatar.gradient} flex items-center justify-center text-sm font-bold text-white`}>
                      {humanName.split(' ').map((w: string) => w[0]).join('').slice(0, 2)}
                    </div>
                  )}
                </div>
              </AgentHoverCard>
              <div className="flex-1">
                <p className="text-xs font-bold text-gray-800">{agentFirst}</p>
                <p className="text-[10px] text-gray-400">{agentName}</p>
              </div>
              {pending.length > 0 && (
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${isAdmin ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'}`}>
                  {pending.length} {isAdmin ? 'pending' : 'in dev'}
                </span>
              )}
            </div>

            {/* Role */}
            {role && (
              <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Role</p>
                <p className="text-xs text-gray-600 leading-relaxed">{role}</p>
              </div>
            )}

            {/* Pending skills — admins can approve/reject; non-admins see read-only "In development" */}
            {pending.length > 0 && (
              <div className="space-y-1.5">
                {isAdmin ? (
                  <>
                    <p className="text-[10px] font-bold text-amber-600 uppercase tracking-widest">
                      Awaiting review
                    </p>
                    {pending.map(s => (
                      <PendingSkillCard key={s.id} skill={s} onApprove={approve} onReject={reject} />
                    ))}
                  </>
                ) : (
                  <>
                    <p className="text-[10px] font-bold text-blue-600 uppercase tracking-widest flex items-center gap-1">
                      <Wrench size={9} /> In development
                    </p>
                    {pending.map(s => (
                      <div key={s.id} className="flex gap-2.5 items-start rounded-lg border border-blue-100 bg-blue-50/40 px-3 py-2">
                        <Wrench size={12} className="flex-shrink-0 mt-0.5 text-blue-400" />
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-semibold text-gray-800">{s.name}</p>
                          <p className="text-[11px] text-gray-500 leading-relaxed mt-0.5">{s.description}</p>
                          <p className="text-[10px] text-blue-500 mt-1">Awaiting administrator review</p>
                        </div>
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}

            {/* Learned skills (approved from library) */}
            {learned.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-[10px] font-bold text-teal-600 uppercase tracking-widest flex items-center gap-1">
                  <Sparkles size={9} /> {learned.length} Learnt skill{learned.length > 1 ? 's' : ''}
                </p>
                {learned.map(s => (
                  <div key={s.id} className="flex gap-2.5 items-start rounded-lg border border-teal-100 bg-teal-50/40 px-3 py-2 group">
                    <Sparkles size={12} className="flex-shrink-0 mt-0.5 text-teal-400" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-gray-800">{s.name}</p>
                      <p className="text-[11px] text-gray-500 leading-relaxed mt-0.5">{s.description}</p>
                    </div>
                    {isAdmin && (
                      <button
                        onClick={() => { if (confirm(`Remove skill "${s.name}"?`)) deleteMut.mutate(s.id) }}
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-300 hover:text-red-400 flex-shrink-0 mt-0.5"
                        aria-label="Remove skill"
                      >
                        <X size={12} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Base skills — DB baseline (authoritative) + hardcoded fallback for any not yet seeded */}
            {(dbBaseline.length > 0 || hardcodedOnly.length > 0) && (
              <div className="space-y-1.5">
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
                  {dbBaseline.length + hardcodedOnly.length} Base skill{dbBaseline.length + hardcodedOnly.length === 1 ? '' : 's'}
                </p>
                {dbBaseline.map(s => {
                  const Icon = skillIconByName.get(s.name.toLowerCase()) ?? Wrench
                  return (
                    <div key={s.id} className="flex gap-2.5 items-start rounded-lg border border-gray-100 bg-white px-3 py-2">
                      <Icon size={14} className="flex-shrink-0 mt-0.5 text-gray-400" />
                      <div>
                        <p className="text-xs font-semibold text-gray-800">{s.name}</p>
                        <p className="text-[11px] text-gray-500 leading-relaxed mt-0.5">{s.description}</p>
                      </div>
                    </div>
                  )
                })}
                {hardcodedOnly.map((skill, i) => (
                  <div key={`hc-${i}`} className="flex gap-2.5 items-start rounded-lg border border-gray-100 bg-white px-3 py-2">
                    <skill.icon size={14} className="flex-shrink-0 mt-0.5 text-gray-400" />
                    <div>
                      <p className="text-xs font-semibold text-gray-800">{skill.name}</p>
                      <p className="text-[11px] text-gray-500 leading-relaxed mt-0.5">{skill.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Add skill (admin only) */}
            {isAdmin && (
              <AddSkillForm
                agentName={agentName}
                onAdded={() => qc.invalidateQueries({ queryKey: ['skills'] })}
              />
            )}

            {/* Divider between agents */}
            {agents.indexOf(agentName) < agents.length - 1 && (
              <div className="border-t border-gray-100 pt-2" />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── AgentDetailPanel ───────────────────────────────────────────────────────────

export interface AgentDetailPanelProps {
  slug: string
  crewKey: string
  crewRun: CrewRun | undefined
  outputs: AgentOutput[]
  logs: string[]
  isPipelineActive: boolean
  hitlReviews?: HumanReview[]
}

export default function AgentDetailPanel({
  slug, crewKey, crewRun, outputs, logs, isPipelineActive, hitlReviews = [],
}: AgentDetailPanelProps) {
  const navigate = useNavigate()
  useAuth()
  const [tab, setTab] = useState<Tab>('output')
  const [messages, setMessages] = useState<{ role: 'user' | 'agent'; content: string; agentName?: string }[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const statusScrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (chatScrollRef.current) chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight
  }, [messages, chatLoading])

  useEffect(() => {
    if (statusScrollRef.current) statusScrollRef.current.scrollTop = statusScrollRef.current.scrollHeight
  }, [logs])

  const agents = CREW_AGENTS[crewKey] ?? []
  const primaryAgent = agents[0] ?? ''

  // Load persisted history from the server when the crew changes
  useEffect(() => {
    setMessages([])
    setChatInput('')
    agentChatApi.getHistory(slug, crewKey).then(rows => {
      setMessages(rows.map(r => ({
        role: r.role === 'assistant' ? 'agent' : 'user',
        content: r.content,
      } as { role: 'user' | 'agent'; content: string })))
    }).catch(() => { /* network error — start with empty history */ })
  }, [slug, crewKey])

  async function clearChat() {
    setMessages([])
    await agentChatApi.clearHistory(slug, crewKey).catch(() => {})
  }
  const primaryAvatar = AGENT_AVATAR[primaryAgent] ?? { emoji: '🤖', gradient: 'from-gray-400 to-gray-600' }
  const primaryHumanName = AGENT_HUMAN_NAME[primaryAgent] ?? primaryAgent
  const firstName = primaryHumanName.split(' ')[0]

  const waitingCrews = new Set(hitlReviews.map(r => r.crew_name).filter(Boolean) as string[])
  const isActive = crewRun?.status === 'running'
  const isWaiting = waitingCrews.has(crewKey)
  const crewStatus = getCrewStatus(crewRun, isActive, isPipelineActive, isWaiting)
  const statusEvents = parseStatusEvents(logs, crewKey)

  // Outputs for this crew - match stored snake_case agent_name, exclude internal state snapshots
  const agentKeys = new Set(agents.map(agentKey))
  const crewOutputs = outputs
    .filter(o => agentKeys.has(o.agent_name) && !INTERNAL_OUTPUT_TYPES.has(o.output_type))
    .sort((a, b) => parseDbDate(b.created_at).getTime() - parseDbDate(a.created_at).getTime())

  const crewMeta = CREW_META[crewKey]

  async function sendChat() {
    if (!chatInput.trim() || chatLoading) return
    const text = chatInput.trim()
    setChatInput('')
    const history = messages.map(m => ({ role: m.role === 'agent' ? 'assistant' : 'user', content: m.content }))
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setChatLoading(true)
    try {
      const { response, agent_name } = await agentChatApi.send(slug, primaryAgent, crewKey, agents, text, history)
      setMessages(prev => [...prev, { role: 'agent', content: response, agentName: agent_name }])
    } catch {
      setMessages(prev => [...prev, { role: 'agent', content: 'Sorry, I could not process that. Please try again.' }])
    } finally {
      setChatLoading(false)
    }
  }

  const TABS: { key: Tab; label: string }[] = [
    { key: 'output', label: crewKey === 'PAM' ? 'Overview' : 'Output' },
    { key: 'status', label: 'Status' },
    { key: 'chat',   label: 'Chat' },
    { key: 'setup',  label: 'Setup' },
    { key: 'skills', label: 'Role & Skills' },
  ]

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-white rounded-xl border border-gray-200 overflow-hidden">

      {/* Panel header */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-100 flex-shrink-0 bg-gray-50/50">
        {(() => { const CrewIcon = CREW_ICON_COMPONENT[crewKey]; return CrewIcon ? <CrewIcon size={18} className="text-gray-500" /> : null })()}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-900">{CREW_LABELS[crewKey]}</p>
          {crewKey === 'PAM' ? (
            <p className="text-[11px] text-gray-400">Pamela Reid · Pipeline Orchestrator</p>
          ) : agents.length === 1 ? (
            <p className="text-[11px] text-gray-400">{firstName} · {primaryAgent}</p>
          ) : (
            <p className="text-[11px] text-gray-400">{agents.length} agents</p>
          )}
        </div>
        {/* Live status pill */}
        {crewStatus === 'running' && (
          <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-teal-50 text-teal-700 border border-teal-200 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse inline-block" /> Running
          </span>
        )}
        {crewStatus === 'waiting' && (
          <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 flex items-center gap-1"><PauseCircle size={12} /> Waiting for review</span>
        )}
        {crewStatus === 'completed' && (
          <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-green-50 text-green-700 border border-green-200 flex items-center gap-1"><CheckCircle2 size={12} />Completed</span>
        )}
        {crewStatus === 'failed' && (
          <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-red-50 text-red-700 border border-red-200 flex items-center gap-1"><XCircle size={12} />Failed</span>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-100 flex-shrink-0 items-center">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 py-2 text-xs font-semibold transition-colors ${
              tab === t.key
                ? 'text-teal-700 border-b-2 border-teal-600 bg-teal-50/30'
                : 'text-gray-400 hover:text-gray-600 border-b-2 border-transparent'
            }`}
          >
            {t.label}
            {t.key === 'output' && crewOutputs.length > 0 && (
              <span className="ml-1 text-[9px] bg-gray-200 text-gray-500 rounded-full px-1">{crewOutputs.length}</span>
            )}
          </button>
        ))}
        {tab === 'chat' && messages.length > 0 && (
          <button
            onClick={clearChat}
            title="Clear chat history"
            className="flex-shrink-0 px-2.5 py-2 text-gray-300 hover:text-red-400 transition-colors border-b-2 border-transparent"
          >
            <Trash2 size={13} />
          </button>
        )}
      </div>

      {/* ── PAM OVERVIEW TAB ──────────────────────────────────────────────────── */}
      {tab === 'output' && crewKey === 'PAM' && <PamReportView slug={slug} />}

      {/* ── OUTPUT TAB ─────────────────────────────────────────────────────────── */}
      {tab === 'output' && crewKey !== 'PAM' && (
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {crewOutputs.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <div className="w-16 h-16 rounded-full overflow-hidden opacity-30 flex-shrink-0">
                {AGENT_AVATAR_IMAGE[primaryAgent] ? (
                  <img src={AGENT_AVATAR_IMAGE[primaryAgent]} alt={firstName} className="w-full h-full object-cover" />
                ) : (
                  <div className={`w-full h-full bg-gradient-to-br ${primaryAvatar.gradient} flex items-center justify-center text-2xl`}>
                    {firstName[0]}
                  </div>
                )}
              </div>
              <p className="text-sm text-gray-400">No outputs yet</p>
              <p className="text-xs text-gray-300">Run this crew to see results here</p>
            </div>
          ) : (
            <>
              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-3">
                {crewOutputs.length} output{crewOutputs.length !== 1 ? 's' : ''}
              </p>
              {crewOutputs.map(o => (
                <OutputItem
                  key={o.id}
                  slug={slug}
                  output={o}
                  crewKey={crewKey}
                  allCrewOutputs={crewOutputs}
                />
              ))}
            </>
          )}
          {/* Crew-specific extra output content (interview sessions, visual artefacts, etc.) */}
          {(() => {
            const OutputExtra = CREW_OUTPUT_EXTRA[crewKey]
            if (!OutputExtra) return null
            return (
              <div className="mt-4 pt-4 border-t border-gray-100">
                <OutputExtra slug={slug} />
              </div>
            )
          })()}
        </div>
      )}

      {/* ── STATUS TAB ─────────────────────────────────────────────────────────── */}
      {tab === 'status' && crewKey === 'PAM' && (
        <div ref={statusScrollRef} className="flex-1 overflow-y-auto p-4">
          <PamCrewStatusDetail slug={slug} />
        </div>
      )}

      {tab === 'status' && crewKey !== 'PAM' && (
        <div ref={statusScrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">

          {/* Run timestamps */}
          {crewRun && (
            <div className="flex gap-4 text-[10px] text-gray-400">
              {crewRun.started_at && <span>Started {new Date(crewRun.started_at + 'Z').toLocaleString()}</span>}
              {crewRun.finished_at && <span>Finished {new Date(crewRun.finished_at + 'Z').toLocaleString()}</span>}
            </div>
          )}

          {/* Error detail */}
          {crewRun?.status === 'failed' && (crewRun as any).error_detail && (
            <div className="rounded-lg bg-red-50 border border-red-100 p-3">
              <p className="text-[10px] font-bold text-red-500 uppercase tracking-widest mb-1">Error</p>
              <pre className="text-xs text-red-700 whitespace-pre-wrap break-all font-mono">{(crewRun as any).error_detail}</pre>
            </div>
          )}

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
                      isLast && crewStatus === 'running'
                        ? 'bg-teal-50 border border-teal-100'
                        : ev.isToolUse
                          ? 'bg-amber-50 border border-amber-100'
                          : 'bg-gray-50 border border-gray-100'
                    }`}
                  >
                    <span className="text-sm flex-shrink-0 mt-0.5 w-5 text-center">{ev.icon}</span>
                    <div className="min-w-0 flex-1">
                      <p className={`text-xs font-medium ${isLast && crewStatus === 'running' ? 'text-teal-800' : 'text-gray-800'}`}>
                        {ev.text}
                        {isLast && crewStatus === 'running' && (
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
          ) : crewStatus === 'running' ? (
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
        </div>
      )}

      {/* ── CHAT TAB ───────────────────────────────────────────────────────────── */}
      {tab === 'chat' && (
        <>
          <div ref={chatScrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.length === 0 && (
              <div className="flex flex-col items-center gap-3 py-10 text-center">
                {agents.length > 1 ? (
                  <>
                    <div className="flex items-center justify-center">
                      {agents.map((agent, i) => {
                        const av = AGENT_AVATAR[agent] ?? { gradient: 'from-gray-400 to-gray-600' }
                        const hn = AGENT_HUMAN_NAME[agent] ?? agent
                        const fn = hn.split(' ')[0]
                        return (
                          <div
                            key={agent}
                            className="flex flex-col items-center gap-1"
                            style={{ marginLeft: i === 0 ? 0 : -8, zIndex: agents.length - i }}
                          >
                            <div className="w-10 h-10 rounded-full overflow-hidden ring-2 ring-white flex-shrink-0">
                              {AGENT_AVATAR_IMAGE[agent] ? (
                                <img src={AGENT_AVATAR_IMAGE[agent]} alt={fn} className="w-full h-full object-cover" />
                              ) : (
                                <div className={`w-full h-full bg-gradient-to-br ${av.gradient} flex items-center justify-center text-sm font-semibold text-white`}>
                                  {fn[0]}
                                </div>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                    <div className="flex items-center gap-1.5 flex-wrap justify-center">
                      {agents.map((agent, i) => {
                        const hn = AGENT_HUMAN_NAME[agent] ?? agent
                        return (
                          <span key={agent} className="text-xs text-gray-500">
                            {hn.split(' ')[0]}{i < agents.length - 1 ? ' ·' : ''}
                          </span>
                        )
                      })}
                    </div>
                    <p className="text-xs text-gray-400">This crew will collectively answer your questions.</p>
                  </>
                ) : (
                  <>
                    <div className="w-12 h-12 rounded-full overflow-hidden flex-shrink-0">
                      {AGENT_AVATAR_IMAGE[primaryAgent] ? (
                        <img src={AGENT_AVATAR_IMAGE[primaryAgent]} alt={firstName} className="w-full h-full object-cover" />
                      ) : (
                        <div className={`w-full h-full bg-gradient-to-br ${primaryAvatar.gradient} flex items-center justify-center text-xl`}>
                          {firstName[0]}
                        </div>
                      )}
                    </div>
                    <p className="text-xs text-gray-400">Ask {firstName} anything about this project…</p>
                  </>
                )}
              </div>
            )}
            {messages.map((msg, i) => (
              <MessageBubble
                key={i}
                role={msg.role}
                content={msg.content}
                agentName={msg.role === 'agent' ? (msg.agentName ?? primaryAgent) : undefined}
                slug={slug}
              />
            ))}
            {chatLoading && (
              <div className="flex justify-start">
                <div className="bg-gray-100 rounded-2xl rounded-bl-sm px-4 py-2">
                  <span className="text-gray-400 text-sm animate-pulse">···</span>
                </div>
              </div>
            )}
          </div>
          <div className="border-t border-gray-100 px-4 py-3 flex-shrink-0">
            <div className="flex gap-2 items-end">
              <textarea
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat() } }}
                placeholder={`Ask ${firstName}…`}
                rows={2}
                className="flex-1 resize-none border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
              <button
                onClick={sendChat}
                disabled={!chatInput.trim() || chatLoading}
                className="bg-teal-600 hover:bg-teal-700 disabled:opacity-40 text-white text-sm font-medium px-3 py-2 rounded-lg transition-colors flex-shrink-0"
              >
                Send
              </button>
            </div>
            <p className="text-[10px] text-gray-400 mt-1">Enter to send · Shift+Enter for newline</p>
          </div>
        </>
      )}

      {/* ── SETUP TAB ──────────────────────────────────────────────────────────── */}
      {tab === 'setup' && (
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {(() => {
            const SetupOverride = CREW_SETUP_OVERRIDE[crewKey]
            if (SetupOverride) return <SetupOverride slug={slug} />

            // Default: reads/produces metadata
            return crewMeta ? (
              <>
                {crewMeta.note && (
                  <div className="rounded-lg bg-blue-50 border border-blue-100 px-3 py-2.5">
                    <p className="text-[11px] text-blue-700 leading-relaxed">{crewMeta.note}</p>
                  </div>
                )}

                <div className="space-y-1">
                  <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Reads</p>
                  <ul className="space-y-1">
                    {crewMeta.reads.map((item, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-gray-600">
                        <ArrowRight size={11} className="text-gray-300 mt-0.5 flex-shrink-0" />
                        <span className="font-mono text-[11px]">{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="space-y-1">
                  <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Produces</p>
                  <ul className="space-y-1">
                    {crewMeta.produces.map((item, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-gray-600">
                        <ArrowLeft size={11} className="text-teal-400 mt-0.5 flex-shrink-0" />
                        <span className="font-mono text-[11px]">{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                {crewMeta.configPage && (
                  <button
                    onClick={() => navigate(`/${slug}/${crewMeta!.configPage}`)}
                    className="inline-flex items-center gap-1.5 text-xs font-medium text-teal-600 hover:text-teal-700 border border-teal-200 rounded-lg px-3 py-1.5 hover:bg-teal-50 transition-colors"
                  >
                    <><Settings size={13} /> {crewMeta.configLabel}</>
                  </button>
                )}
              </>
            ) : (
              <p className="text-xs text-gray-400 text-center py-12">No setup information available.</p>
            )
          })()}
        </div>
      )}

      {/* ── ROLE & SKILLS TAB ──────────────────────────────────────────────────── */}
      {tab === 'skills' && (
        <SkillsTabContent agents={agents} />
      )}
    </div>
  )
}
