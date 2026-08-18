// ui/src/components/AgentDetailPanel.tsx
import { useState, useEffect, useRef, useMemo, type ReactNode, type FC } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  Play, CheckCircle2, XCircle,
  PauseCircle, Check, X, AlertTriangle, Settings,
  ArrowRight, ArrowLeft,
  Wrench, MessageSquare, Trash2, Sparkles, Loader, Paperclip,
} from 'lucide-react'
import { agentChatApi } from '../api/agentChat'
import { skillsApi } from '../api/skills'
import { useAuth } from '../context/AuthContext'
import {
  CREW_LABELS, CREW_AGENTS,
  AGENT_AVATAR, AGENT_AVATAR_IMAGE, AGENT_HUMAN_NAME, AGENT_ROLE, AGENT_SKILLS,
  getCrewStatus,
} from './agentStatus'
import { parseDbDate } from './crewOutputs'
import { CREW_ICON_COMPONENT } from './crewIcons'
import AgentHoverCard from './AgentHoverCard'
import PamReportView, { PamCrewStatusDetail } from './PamReportView'
import { AgentOutputTab } from './AgentOutputTab'
import { AgentStatusTab, type PrimaryModelCounts } from './AgentStatusTab'
import { projectsApi, valueChainApi } from '../api/endpoints'
import { describeError } from '../utils/describeError'
import type { CrewRun, AgentOutput, HumanReview } from '../types'
import StructureTab from './StructureTab'
import AlexSetupTab from './tabs/AlexSetupTab'
import MayaSetupTab from './tabs/MayaSetupTab'
import { CrewSetupSections, AGENT_SETUP_SECTION } from './tabs/CrewSetupSections'
import AveryOutputExtra from './tabs/AveryOutputExtra'
import JordanOutputExtra from './tabs/JordanOutputExtra'
import LucaOutputExtra from './tabs/LucaOutputExtra'
import MayaOutputExtra from './tabs/MayaOutputExtra'
import PamSetupTab from './tabs/PamSetupTab'

// ── Chat attachments: the tier picker ───────────────────────────────────────────
//
// Display labels only, for the three values `/my-permissions` can ever put in
// `writable_knowledge_tiers` (`interviews` is never offered - see
// api.services.knowledge_tiers.UPLOADABLE_TIERS). The *set* the picker offers is never
// decided here: it is exactly what the server returns, broadest first, because a second copy
// of that rule is the one that drifts and a tier rendered here that the door then refuses is
// worse than a tier not offered at all.
const KNOWLEDGE_TIER_LABEL: Record<string, string> = {
  sector: 'Sector - shared across every client in this sector',
  organisation: 'Organisation - shared across this organisation',
  project: 'This project only',
}

// ── Per-crew slot injection ────────────────────────────────────────────────────

export type SlotFC = FC<{ slug: string }>

// Replaces the default Setup tab reads/produces panel for these crews
// Whole-tab overrides, for crews that hold exactly one agent - the tab and the agent are
// then the same scope and naming it after them is correct.
//
// stakeholder_management and discovery_interviews are NOT here any more. The first held
// TaylorSetupTab, which is Taylor's configuration under Jordan's crew - an agent Taylor is
// not. The second held AverySetupTab for a crew of three. Both are now assembled from
// per-agent sections; see CrewSetupSections.
const CREW_SETUP_OVERRIDE: Partial<Record<string, SlotFC>> = {
  PAM:                    PamSetupTab,
  discovery_mapping:      AlexSetupTab,
  assessment_design:      MayaSetupTab,
}

// Rendered after the primary artefact in the Output tab. Exported because AgentOutputTab's
// empty state has to know a crew has one of these: "No outputs yet" printed directly above a
// populated interview-sessions or scripts panel is wrong on its face.
export const CREW_OUTPUT_EXTRA: Partial<Record<string, SlotFC>> = {
  assessment_design:      MayaOutputExtra,
  discovery_interviews:   AveryOutputExtra,
  delivery:               LucaOutputExtra,
  // What participants wrote back. The correspondent owns the conversation - engagement mail
  // leaves over Jordan's name and address - so the replies to it are read here.
  stakeholder_management: JordanOutputExtra,
}

// The bespoke editor for an agent's primary output. An agent absent from this map renders
// its primary read-only - the structure arrives for every agent, the editors arrive one at
// a time.
export const CREW_OUTPUT_EDITOR: Partial<Record<string, SlotFC>> = {
  discovery_mapping: StructureTab,
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
    // No configPage: it pointed at the retired /:slug/value-chain page, and this crew has a
    // CREW_SETUP_OVERRIDE (AlexSetupTab) that replaces the block the button lives in anyway.
    note: 'Re-running will preserve existing IDs and extend the registry - existing downstream artefacts reference these IDs.',
  },
  assessment_design: {
    reads: ['value_chain_registry.json', 'value_chain_summary.txt', 'Standards references (from Setup)', 'Project knowledge base', 'Stakeholder registry (for C / A / F / S coverage)'],
    produces: ['interview_scripts.json', 'l0_interview_summaries.json', 'l1_interview_summaries.json', 'l2_interview_summaries.json', 'audit_interview_summaries.json', 'customer_interview_summaries.json', 'frontline_interview_summaries.json', 'corp_services_interview_summaries.json'],
    configPage: null,
    note: 'Runs after value chain mapping is approved. Generates eight instrument types — L0 through L3 for the value chain, plus C, A, F, and S for external and frontline perspectives.',
  },
  requirements: {
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
  capabilities: {
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
}

export interface StatusEvent { ts: number; icon: ReactNode; text: string; sub?: string; isToolUse?: boolean }

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

// 'state' outputs are internal agent state snapshots (SQLiteStateTool) - not user deliverables
const INTERNAL_OUTPUT_TYPES = new Set(['state'])

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
  locale?: string
  // The tab named in a notification link (Dashboard's `?tab=`). Must win over whatever this
  // browser last had saved, or an approver whose last visit ended on Chat lands on Chat no
  // matter what the email said.
  initialTab?: string
}

function isTab(value: string | undefined): value is Tab {
  return value === 'output' || value === 'status' || value === 'chat' || value === 'setup' || value === 'skills'
}

export default function AgentDetailPanel({
  slug, crewKey, crewRun, outputs, logs, isPipelineActive, hitlReviews = [], locale = 'GB',
  initialTab,
}: AgentDetailPanelProps) {
  const navigate = useNavigate()
  const { user } = useAuth()

  const tabKey = user?.sub ? `ap_panel_tab:${user.sub}:${slug}:${crewKey}` : null
  const [tab, setTab] = useState<Tab>(() => {
    // A deep link from a notification must beat whatever tab this browser last used, or an
    // approver who ended their last visit on Chat lands on Chat however the email was written.
    if (isTab(initialTab)) return initialTab
    if (tabKey) {
      const saved = localStorage.getItem(tabKey)
      if (saved === 'output' || saved === 'status' || saved === 'chat' || saved === 'setup' || saved === 'skills') return saved
    }
    return 'output'
  })
  const [messages, setMessages] = useState<{ role: 'user' | 'agent'; content: string; agentName?: string }[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const statusScrollRef = useRef<HTMLDivElement>(null)
  const chatFileInputRef = useRef<HTMLInputElement>(null)
  // Defaults to project - the narrowest tier - so the common case stays a single click and
  // the tier is visible rather than implicit. Corrected below, once permissions arrive, if
  // 'project' turns out not to be one this caller may write.
  const [uploadTier, setUploadTier] = useState('project')
  const [attaching, setAttaching] = useState(false)
  const [attachError, setAttachError] = useState<string | null>(null)

  // Same query key as StakeholderForm.tsx and MayaOutputExtra.tsx - one cache entry per
  // project, shared with whichever of those is also mounted, rather than a second fetch of a
  // rule that must answer identically wherever it is asked.
  const { data: permissions } = useQuery({
    queryKey: ['my-permissions', slug],
    queryFn: () => projectsApi.getMyPermissions(slug),
  })
  const writableTiers = permissions?.writable_knowledge_tiers ?? []

  useEffect(() => {
    // The list this caller may write can change under them (a role grant, a different
    // project) or simply arrive after the first render. If the selection is no longer one of
    // the offered tiers, fall back to project rather than let a stale, now-unwritable choice
    // sit selected in a control that would then 403 on submit.
    if (writableTiers.length > 0 && !writableTiers.includes(uploadTier)) {
      setUploadTier(writableTiers.includes('project') ? 'project' : writableTiers[0])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [permissions])

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

  function openChatAttach() {
    chatFileInputRef.current?.click()
  }

  async function handleChatFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (e.target) e.target.value = '' // allow re-selecting the same file next time
    if (!file) return
    setAttachError(null)
    setAttaching(true)
    try {
      const result = await agentChatApi.uploadFile(slug, primaryAgent, file, uploadTier)
      const tierLabel = KNOWLEDGE_TIER_LABEL[result.knowledge_tier] ?? result.knowledge_tier
      setMessages(prev => [
        ...prev,
        { role: 'user', content: `Attached "${result.original_name}" - ${tierLabel}.` },
      ])
    } catch (err) {
      setAttachError(describeError(err, 'Could not attach that file.'))
    } finally {
      setAttaching(false)
    }
  }

  const primaryAvatar = AGENT_AVATAR[primaryAgent] ?? { emoji: '🤖', gradient: 'from-gray-400 to-gray-600' }
  const primaryHumanName = AGENT_HUMAN_NAME[primaryAgent] ?? primaryAgent
  const firstName = primaryHumanName.split(' ')[0]

  const waitingCrews = new Set(hitlReviews.map(r => r.crew_name).filter(Boolean) as string[])
  const isActive = crewRun?.status === 'running'
  const isWaiting = waitingCrews.has(crewKey)
  const crewStatus = getCrewStatus(crewRun, isActive, isPipelineActive, isWaiting)
  const statusEvents = parseStatusEvents(logs, crewKey)

  // Outputs for this crew - match stored snake_case agent_name, exclude internal state
  // snapshots. Deliberately unfiltered beyond that: the per-crew hiding rule is a decision
  // about what the Status tab's *non-primary* list is worth showing, and it lives there
  // (AgentStatusTab.tsx). Applying it here instead removed Maya's declared primary
  // ('interview_scripts' matches her own hidden prefix) before either tab could look for it,
  // emptying her Output tab and her version history at once.
  const agentKeys = new Set(agents.map(agentKey))
  const crewOutputs = outputs
    .filter(o => agentKeys.has(o.agent_name) && !INTERNAL_OUTPUT_TYPES.has(o.output_type))
    .sort((a, b) => parseDbDate(b.created_at).getTime() - parseDbDate(a.created_at).getTime())

  // The tab badge counts current artefacts, not rows: an agent's single declared output
  // written thirteen times is one artefact, not thirteen, and the row count read as a count
  // of interviews sitting one below the total the Output tab actually listed. Currency is
  // what makes this coherent with demotion as a data-fix tool - a row an ownership guard has
  // since demoted (is_current=0) is exactly a type this agent no longer currently owns, so it
  // stops counting here too. This also generalises: an output type since superseded by
  // another agent's write no longer counts against this crew.
  const distinctOutputTypes = new Set(crewOutputs.filter(o => o.is_current).map(o => o.output_type)).size

  const crewMeta = CREW_META[crewKey]

  // Status' output summary card counts what is *in* the current artefact, which means it
  // needs the fetched model rather than the output row describing it - and only this panel
  // sits above both tabs, so only this panel can hand it over.
  //
  // Same key, queryFn and retry as StructureTab's own query (StructureTab.tsx), which is
  // mounted in the hidden Output branch below whenever this crew is Alex's, so this observer
  // normally reads a cache entry that is already warm. The options must not diverge: two
  // observers of one key with different retry settings give the query whichever behaviour
  // belongs to whoever triggered the fetch. `enabled` is the one deliberate narrowing - no
  // other crew has an editor that wants this model, so no other crew should fetch it.
  const { data: valueChainData } = useQuery({
    queryKey: ['value-chain-model', slug],
    queryFn: () => valueChainApi.get(slug),
    enabled: !!slug && crewKey === 'discovery_mapping',
    retry: false,
  })
  const primaryModel = (valueChainData?.model ?? undefined) as PrimaryModelCounts | undefined

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
    <div
      className="flex flex-col flex-1 min-h-0 bg-white rounded-xl border border-gray-200 overflow-hidden"
      data-testid={`selected-crew-${crewKey}`}
    >

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
            onClick={() => { setTab(t.key); if (tabKey) localStorage.setItem(tabKey, t.key) }}
            data-testid={tab === t.key ? `active-tab-${t.key}` : undefined}
            className={`flex-1 py-2 text-xs font-semibold transition-colors ${
              tab === t.key
                ? 'text-teal-700 border-b-2 border-teal-600 bg-teal-50/30'
                : 'text-gray-400 hover:text-gray-600 border-b-2 border-transparent'
            }`}
          >
            {t.label}
            {t.key === 'output' && distinctOutputTypes > 0 && (
              <span className="ml-1 text-[9px] bg-gray-200 text-gray-500 rounded-full px-1">{distinctOutputTypes}</span>
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
      {/* Hidden rather than unmounted, as the Setup tab below also is. A registered
          CREW_OUTPUT_EDITOR (StructureTab, for now) holds a working copy that only Save
          commits to the server. Rendering this branch conditionally on `tab === 'output'`
          unmounts it on every click of Status, Chat, Setup or Skills, discarding that draft
          with no warning - beforeunload does not fire on an in-panel tab change, so there is
          nothing to catch it.

          Status, Chat and Skills stay conditional: their state is either derived from props
          or, in Chat's case, held here in the panel rather than in the branch, so a remount
          costs nothing but a refetch. */}
      {crewKey !== 'PAM' && (
        <div hidden={tab !== 'output'} className="flex-1 overflow-y-auto p-4 space-y-2">
          <AgentOutputTab slug={slug} crewKey={crewKey} outputs={crewOutputs} />
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
          <AgentStatusTab
            slug={slug}
            crewKey={crewKey}
            crewRun={crewRun}
            outputs={crewOutputs}
            statusEvents={statusEvents}
            locale={locale}
            primaryModel={primaryModel}
            crewStatus={crewStatus}
          />
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
            {/* Attaching a file also files it in the project's document library
                (POST /{slug}/agent-chat/upload), which is gated on the same approver
                authority as the Documents page's own upload door - so the control is offered
                only to a caller /my-permissions says can_approve, never to one it would then
                refuse. The tier picker inside it is narrower still: it offers exactly
                writable_knowledge_tiers, broadest first, and nothing this component decided
                for itself. */}
            {permissions?.can_approve && (
              <div className="flex items-center gap-2 mb-2">
                <input
                  ref={chatFileInputRef}
                  type="file"
                  className="hidden"
                  onChange={handleChatFileSelected}
                  aria-label="Attach a file"
                />
                <button
                  type="button"
                  onClick={openChatAttach}
                  disabled={attaching}
                  title="Attach a file to this project's knowledge store"
                  className="flex items-center gap-1 text-xs text-gray-500 hover:text-teal-700 disabled:opacity-40 border border-gray-200 rounded-lg px-2 py-1 flex-shrink-0"
                >
                  <Paperclip size={12} />
                  {attaching ? 'Attaching…' : 'Attach'}
                </button>
                {writableTiers.length > 1 ? (
                  <select
                    aria-label="Knowledge tier"
                    value={uploadTier}
                    onChange={e => setUploadTier(e.target.value)}
                    className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-600 focus:outline-none focus:ring-2 focus:ring-teal-500"
                  >
                    {writableTiers.map(tier => (
                      <option key={tier} value={tier}>{KNOWLEDGE_TIER_LABEL[tier] ?? tier}</option>
                    ))}
                  </select>
                ) : (
                  <span className="text-[11px] text-gray-400">
                    {KNOWLEDGE_TIER_LABEL[uploadTier] ?? uploadTier}
                  </span>
                )}
              </div>
            )}
            {attachError && <p className="text-[11px] text-red-600 mb-2">{attachError}</p>}
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
      {/* Hidden rather than unmounted, for the same reason the Output tab is. Every
          CREW_SETUP_OVERRIDE is a form whose fields are React state committed only by an
          explicit Save - AlexSetupTab alone holds ten pieces of it - so rendering this branch
          on `tab === 'setup'` threw away a half-typed discovery brief the moment the user
          clicked Output to check something, silently and with nothing to catch it. */}
      <div hidden={tab !== 'setup'} className="flex-1 overflow-y-auto p-4 space-y-4">
        {(() => {
          const SetupOverride = CREW_SETUP_OVERRIDE[crewKey]
          if (SetupOverride) return <SetupOverride slug={slug} />

          // A crew's own agents, each with their own configuration under their own name.
          // Renders null when none of them has any, so the default below still shows.
          const sections = <CrewSetupSections crewKey={crewKey} slug={slug} />
          if (CREW_AGENTS[crewKey]?.some((a) => a in AGENT_SETUP_SECTION)) return sections

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

      {/* ── ROLE & SKILLS TAB ──────────────────────────────────────────────────── */}
      {tab === 'skills' && (
        <SkillsTabContent agents={agents} />
      )}
    </div>
  )
}
