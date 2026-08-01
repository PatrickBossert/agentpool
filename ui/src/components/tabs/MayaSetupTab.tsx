// ui/src/components/tabs/MayaSetupTab.tsx
// Maya's Setup tab: interview programme reference, value chain node coverage, and manual
// node template assignment (moved from the retired Value Chain page's Templates tab)
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Info, X } from 'lucide-react'
import { projectsApi } from '../../api/endpoints'
import { listTemplates } from '../../api/templates'
import { listNodeTemplates, putNodeTemplate, publishNodeTemplate } from '../../api/nodeTemplates'
import InterviewTemplateEditor from '../InterviewTemplateEditor'
import type { NodeTemplateAssignment, TemplateListItem } from '../../types'

function sortByActivityId(assignments: NodeTemplateAssignment[]): NodeTemplateAssignment[] {
  return [...assignments].sort((a, b) => {
    if (!a.activity_id && !b.activity_id) return a.node_label.localeCompare(b.node_label)
    if (!a.activity_id) return 1
    if (!b.activity_id) return -1
    const aParts = a.activity_id.split('.').map(Number)
    const bParts = b.activity_id.split('.').map(Number)
    const len = Math.max(aParts.length, bParts.length)
    for (let i = 0; i < len; i++) {
      const diff = (aParts[i] ?? 0) - (bParts[i] ?? 0)
      if (diff !== 0) return diff
    }
    return 0
  })
}

interface TypeDetail {
  approach: string
  structureNote: string
  sections: { title: string; duration?: string }[]
  features: string[]
}

const INTERVIEW_TYPE_DETAILS: Record<string, TypeDetail> = {
  L0: {
    approach: 'Positions the interviewer as synthesising evidence for the board\'s review, not conducting an audit. Framing emphasises that the conversation will inform portfolio sequencing options (A / B / C), not request decisions. The interviewer presents alternatives rather than leading the respondent.',
    structureNote: '6 fixed sections — not customisable per engagement. Includes a framing block (spoken before sections) and a synthesis check (spoken after sections). Portfolio sequencing options and a sponsorship commitment test are embedded in the synthesis.',
    sections: [
      { title: 'S1 — Strategic Mandate & Portfolio Logic', duration: '~8 min' },
      { title: 'S2 — Competitive Positioning & Disruption', duration: '~6 min' },
      { title: 'S3 — Capital Allocation & ROI Discipline', duration: '~8 min' },
      { title: 'S4 — Organisational Readiness & Execution Risk', duration: '~7 min' },
      { title: 'S5 — Governance, Accountability & Measurement', duration: '~6 min' },
      { title: 'S6 — Strategic Priorities & Board Questions', duration: '~5 min' },
    ],
    features: [
      'Framing block spoken before sections — positions as evidence synthesis, not performance review',
      'Synthesis check presents A / B / C sequencing options for the respondent to react to',
      'Sponsorship commitment test embedded in closing synthesis',
      'No maturity rating — executives assess portfolio posture, not operational maturity',
    ],
  },
  L1: {
    approach: 'Captures the GM\'s strategic view of their value stream, connecting operational realities to organisational strategy. S1, S2, and S3 form the mandatory core; Maya selects one further section from the library based on what is most important for that value stream.',
    structureNote: 'Library structure — S1, S2, and S3 are always included (~34 min combined). Maya selects 1 section from {S4, S5, S6} based on the value stream\'s known transformation priorities. S7 and S8 are available for stakeholders with cross-portfolio or peer-benchmarking insight.',
    sections: [
      { title: 'S1 — Strategic Intent & Competitive Position', duration: 'Mandatory · ~12 min' },
      { title: 'S2 — Value Creation & Business Model', duration: 'Mandatory · ~10 min' },
      { title: 'S3 — Current State Capability Maturity', duration: 'Mandatory · ~12 min' },
      { title: 'S4 — Digital & AI Transformation Readiness', duration: 'Library · ~10 min' },
      { title: 'S5 — Strategic Roadmap & Transformation Priorities', duration: 'Library · ~10 min' },
      { title: 'S6 — Organisational Capability & Change Readiness', duration: 'Library · ~8 min' },
      { title: 'S7 — Value Realisation & Success Metrics', duration: 'Library · ~8 min' },
      { title: 'S8 — Peer Contextualisation & Portfolio Fit', duration: 'Library · ~6 min' },
    ],
    features: [
      'Maturity rating (0 – 4 scale) embedded in each section — the only tier with voice-selectable ratings',
      'Framing block sets strategic context before sections begin',
      'Synthesis check and peer referral probe follow all sections',
      'Section selection tailored to each value stream\'s transformation priorities',
    ],
  },
  L2: {
    approach: 'Targets the decision-making layer below GM, focusing on how processes are governed, where decisions are made, and what structural constraints prevent improvement. S1 and S2 are mandatory; Maya selects from the library for the remaining sections.',
    structureNote: 'Library structure — S1 and S2 are always included (~18 min combined). Maya selects 2 – 4 further sections from the library based on the activity\'s known constraints and decision friction. Total interview: 35 – 50 min.',
    sections: [
      { title: 'S1 — Strategic Intent & Decision Architecture', duration: 'Mandatory · ~8 min' },
      { title: 'S2 — Decision Maturity & Governance', duration: 'Mandatory · ~10 min' },
      { title: 'S3 — Data Landscape & Decision Enablement', duration: 'Library · ~8 min' },
      { title: 'S4 — Decision Velocity & Orchestration Friction', duration: 'Library · ~8 min' },
      { title: 'S5 — Decision Quality Gaps & Maturity Opportunities', duration: 'Library · ~8 min' },
      { title: 'S6 — Orchestration Effectiveness & Downstream Impact', duration: 'Library · ~8 min' },
      { title: 'S7 — Hidden Orchestration Opportunities', duration: 'Library · ~6 min' },
    ],
    features: [
      'Maturity rating (0 – 4 scale) embedded in each section — same tier as L1',
      'Framing block sets process-layer context before sections begin',
      'Synthesis check follows all sections',
      'Deeper operational focus than L1 — probes decision authority and constraint sources',
    ],
  },
  L3: {
    approach: 'Ground-level operational interview designed to surface what actually happens, not what should happen. No framing preamble — the interviewer begins directly with the practitioner\'s daily reality. Questions use plain language and avoid jargon.',
    structureNote: '8 fixed sections — not customisable. No framing block and no synthesis check. Designed to be conversational and fast-moving, with short focused sections that together build a complete picture of execution reality. Total: ~47 min.',
    sections: [
      { title: 'Opening', duration: '~5 min' },
      { title: 'Current State', duration: '~10 min' },
      { title: 'Decision Quality', duration: '~8 min' },
      { title: 'Data & Dependencies', duration: '~7 min' },
      { title: 'Impact & Monetisation', duration: '~5 min' },
      { title: 'Scenario & Resilience', duration: '~5 min' },
      { title: 'Aspiration', duration: '~5 min' },
      { title: 'Closing', duration: '~2 min' },
    ],
    features: [
      'No framing block — starts directly with the practitioner\'s current state',
      'No synthesis check — closes with a structured aspiration and closing sequence',
      'No maturity rating — practitioners do not self-rate organisational maturity',
      'Plain-language questions designed to feel like a conversation, not an assessment',
    ],
  },
  C: {
    approach: 'Outside-in perspective from the service recipient. Framing positions the conversation as understanding the customer\'s experience and operational reality, not collecting complaints. Designed to surface unmet needs and switching signals without leading the respondent.',
    structureNote: '8 fixed sections — not customisable. Includes a framing block (spoken before sections) and S8 serves as the synthesis wrap-up. Total: ~50 min.',
    sections: [
      { title: 'S1 — Operational Context & Asset Dependence', duration: '~6 min' },
      { title: 'S2 — Current Pain Points & Friction', duration: '~10 min' },
      { title: 'S3 — Unmet Needs & Aspirations', duration: '~8 min' },
      { title: 'S4 — Satisfaction & Performance Perception', duration: '~6 min' },
      { title: 'S5 — Data, Transparency & Partnership Quality', duration: '~7 min' },
      { title: 'S6 — Change & Transformation Readiness', duration: '~5 min' },
      { title: 'S7 — Competitive & Market Context', duration: '~4 min' },
      { title: 'S8 — Wrap-Up & Partnership', duration: '~4 min' },
    ],
    features: [
      'Framing block positions as an experience study, not a complaint process',
      'S8 (Wrap-Up & Partnership) serves as the synthesis check — invites the single most important change',
      'No maturity rating — customers assess service experience, not organisational maturity',
      'S7 surfaces competitive switching signals without leading the respondent',
    ],
  },
  A: {
    approach: 'Structured debrief with an external audit or regulatory body. Positions the conversation as gathering the auditor\'s independent assessment as a knowledgeable peer, not as an adversary or inspector. The interviewer leads with respect for the auditor\'s expertise and independence.',
    structureNote: '10 fixed sections. Includes a framing block and S10 serves as the synthesis wrap-up. Focused coverage across governance, controls, financial discipline, risk, and third-party oversight. Total: ~53 min.',
    sections: [
      { title: 'S1 — Governance & Accountability Framework', duration: '~6 min' },
      { title: 'S2 — Contract & Compliance Management', duration: '~5 min' },
      { title: 'S3 — Financial Controls & Capex Discipline', duration: '~6 min' },
      { title: 'S4 — Performance Tracking & KPI Integrity', duration: '~5 min' },
      { title: 'S5 — Risk Identification & Mitigation', duration: '~6 min' },
      { title: 'S6 — Data & Information Quality', duration: '~5 min' },
      { title: 'S7 — Third-Party Management — ISS & DXI', duration: '~6 min' },
      { title: 'S8 — Transformation & Change Governance', duration: '~5 min' },
      { title: 'S9 — Comparative & Peer Assessment', duration: '~4 min' },
      { title: 'S10 — Wrap-Up & Critical Observations', duration: '~5 min' },
    ],
    features: [
      'Framing block positions as gathering independent expert perspective',
      'S10 (Wrap-Up & Critical Observations) serves as the synthesis check',
      'No maturity rating — the auditor\'s assessment is qualitative, not numerical',
      'S7 specifically addresses third-party and outsourced service providers (ISS & DXI)',
    ],
  },
  F: {
    approach: 'Explicitly NOT a performance review — confidentiality is emphasised from the opening. Uses a dual-lens approach: what creates friction (efficiency) and what the worker aspires to (effectiveness). Designed to surface the operational reality that management cannot observe from above.',
    structureNote: '9 fixed sections — not customisable. Includes a framing block (confidentiality and dual-lens positioning). S9 serves as the closing and confidentiality reassurance. Output is an anonymised cohort summary, not individual attribution. Total: ~55 min.',
    sections: [
      { title: 'S1 — Day-in-the-Life & Actual Work', duration: '~7 min' },
      { title: 'S2 — Constraints, Friction & Pain Points', duration: '~7 min' },
      { title: 'S3 — Data, Systems & Technology', duration: '~7 min' },
      { title: 'S4 — Knowledge, Training & Capability', duration: '~6 min' },
      { title: 'S5 — Safety, Health & Wellbeing', duration: '~7 min' },
      { title: 'S6 — Team Dynamics & Culture', duration: '~6 min' },
      { title: 'S7 — Change & Transformation Appetite', duration: '~6 min' },
      { title: 'S8 — Feedback Loop & Voice', duration: '~5 min' },
      { title: 'S9 — Wrap-Up & Confidentiality', duration: '~4 min' },
    ],
    features: [
      'Opening framing emphasises confidentiality — responses will not be attributed individually',
      'Dual-lens framing in S1: what actually happens vs. what would make work significantly better',
      'No maturity rating — frontline workers do not assess organisational maturity',
      'Output is an anonymised cohort summary across all F interviewees for this group',
    ],
  },
  S: {
    approach: 'Explicitly NOT a function audit — framing emphasises that the function\'s constraints and institutional knowledge are equally important as its outputs. Designed to surface what the function knows, what it is prevented from contributing, and what it wants to be asked to do.',
    structureNote: '8 fixed sections — not customisable. Includes a framing block and S8 serves as the synthesis wrap-up. Output is a function summary covering systems, manual burden, governance friction, capability gaps, and cross-function themes. Total: ~55 min.',
    sections: [
      { title: 'S1 — Daily Work & Asset Management Support', duration: '~8 min' },
      { title: 'S2 — Data, Systems & Process Friction', duration: '~10 min' },
      { title: 'S3 — Governance, Accountability & Decision-Making', duration: '~8 min' },
      { title: 'S4 — Capability Gaps & Constraints', duration: '~7 min' },
      { title: 'S5 — Organisational Alignment & Culture', duration: '~7 min' },
      { title: 'S6 — Change & Transformation Readiness', duration: '~6 min' },
      { title: 'S7 — Advice for Transformation Success', duration: '~5 min' },
      { title: 'S8 — Wrap-Up & Feedback', duration: '~4 min' },
    ],
    features: [
      'Framing block positions the function as a contributor, not a compliance subject',
      'S3 surfaces decisions made without the function\'s input — governance blind spots',
      'S7 invites the function to give direct advice — surfaces institutional knowledge',
      'S8 serves as the synthesis check — requires a named next step before closing',
      'No maturity rating — function staff assess constraints, not organisational maturity',
    ],
  },
}

const LEVEL_BADGE: Record<string, string> = {
  L0: 'bg-purple-100 text-purple-700',
  L1: 'bg-indigo-100 text-indigo-700',
  L2: 'bg-blue-100 text-blue-700',
  L3: 'bg-teal-100 text-teal-700',
}

const LEVEL_INTERVIEW_NAME: Record<string, string> = {
  L0: 'Portfolio / Board',
  L1: 'Strategy & Capability',
  L2: 'Decision Architecture',
  L3: 'Execution Fidelity',
}

const INTERVIEW_TYPES = [
  {
    code: 'L0',
    bg: 'bg-purple-50 border-purple-100',
    badge: 'bg-purple-100 text-purple-700',
    title: 'Portfolio / Board',
    who: 'Executive sponsors and board-level stakeholders',
    sections: '6 fixed',
    duration: '~40 min',
    feature: 'Capital allocation, competitive positioning, portfolio sequencing',
  },
  {
    code: 'L1',
    bg: 'bg-indigo-50 border-indigo-100',
    badge: 'bg-indigo-100 text-indigo-700',
    title: 'GM / Value Stream',
    who: 'Value stream general managers',
    sections: 'Library — 3 to 5',
    duration: '45 – 55 min',
    feature: 'Strategy, capability maturity, and resource constraints per value stream',
  },
  {
    code: 'L2',
    bg: 'bg-blue-50 border-blue-100',
    badge: 'bg-blue-100 text-blue-700',
    title: 'Process Manager',
    who: 'Activity owners and middle managers',
    sections: 'Library — 4 to 6',
    duration: '35 – 50 min',
    feature: 'Decision architecture, process dependencies, and pain points',
  },
  {
    code: 'L3',
    bg: 'bg-teal-50 border-teal-100',
    badge: 'bg-teal-100 text-teal-700',
    title: 'Practitioner',
    who: 'Front-line practitioners executing the activity',
    sections: '8 fixed',
    duration: '~47 min',
    feature: 'Execution fidelity, workarounds, and ground-level friction',
  },
  {
    code: 'C',
    bg: 'bg-amber-50 border-amber-100',
    badge: 'bg-amber-100 text-amber-700',
    title: 'Customer',
    who: 'External or internal service recipients',
    sections: '8 fixed',
    duration: '~50 min',
    feature: 'Outside-in service quality, unmet needs, and switching signals',
  },
  {
    code: 'A',
    bg: 'bg-red-50 border-red-100',
    badge: 'bg-red-100 text-red-700',
    title: 'Auditor / Regulator',
    who: 'External audit, compliance, and regulatory bodies',
    sections: '10 fixed',
    duration: '~53 min',
    feature: 'Governance maturity, control effectiveness, and findings history',
  },
  {
    code: 'F',
    bg: 'bg-orange-50 border-orange-100',
    badge: 'bg-orange-100 text-orange-700',
    title: 'Frontline Worker',
    who: 'Field and operations staff — technicians, drivers, coordinators',
    sections: '9 fixed',
    duration: '~55 min',
    feature: 'Ground-truth execution reality — friction, aspiration, and informal workarounds',
  },
  {
    code: 'S',
    bg: 'bg-emerald-50 border-emerald-100',
    badge: 'bg-emerald-100 text-emerald-700',
    title: 'Corporate Services',
    who: 'Support function staff — Finance, HR, IT, Data, Compliance, Procurement',
    sections: '8 fixed',
    duration: '~55 min',
    feature: 'Function constraints, manual burden, system gaps, and knowledge assets',
  },
]

function InterviewTypeDialog({ code, onClose }: { code: string; onClose: () => void }) {
  const t   = INTERVIEW_TYPES.find(x => x.code === code)!
  const det = INTERVIEW_TYPE_DETAILS[code]!
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className={`flex items-start gap-3 px-4 py-3 border-b border-gray-100 ${t.bg}`}>
          <span className={`text-[10px] font-bold px-2 py-1 rounded uppercase tracking-wide flex-shrink-0 mt-0.5 ${t.badge}`}>
            {t.code}
          </span>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-900">{t.title}</p>
            <p className="text-[11px] text-gray-500 mt-0.5">{t.who}</p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="text-[10px] text-gray-400">{t.sections} · {t.duration}</span>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 p-0.5 rounded"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto flex-1 px-4 py-4 space-y-4">

          {/* Approach */}
          <div>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">Approach</p>
            <p className="text-[12px] text-gray-700 leading-relaxed">{det.approach}</p>
          </div>

          {/* Section structure note */}
          <div>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">Section Structure</p>
            <p className="text-[11px] text-gray-600 leading-relaxed mb-2.5">{det.structureNote}</p>
            <div className="space-y-1">
              {det.sections.map((s, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <span className="text-[10px] font-mono text-gray-300 w-5 flex-shrink-0 pt-px">{i + 1}</span>
                  <div className="flex-1 flex items-baseline gap-2 flex-wrap">
                    <span className="text-[11px] text-gray-800">{s.title}</span>
                    {s.duration && (
                      <span className="text-[10px] text-gray-400">{s.duration}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Key features */}
          <div>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">Key Design Features</p>
            <ul className="space-y-1">
              {det.features.map((f, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="text-gray-300 mt-0.5 flex-shrink-0">·</span>
                  <span className="text-[11px] text-gray-700 leading-relaxed">{f}</span>
                </li>
              ))}
            </ul>
          </div>

        </div>
      </div>
    </div>
  )
}

export default function MayaSetupTab({ slug }: { slug: string }) {
  const [nodeAssignments, setNodeAssignments] = useState<NodeTemplateAssignment[]>([])
  const [loading, setLoading] = useState(true)
  const [inspectCode, setInspectCode] = useState<string | null>(null)

  // ── Node template assignment — moved from the old Value Chain page's Templates
  // tab. Per-level generation is meant to supersede this eventually, but that
  // generation does not exist yet, so manual assignment stays the only route to
  // control until it does. Kept as its own state, separate from nodeAssignments
  // above, since the two sections were independent on the old page and merging
  // them is out of scope for a faithful move. ────────────────────────────────
  const [templateAssignments, setTemplateAssignments] = useState<NodeTemplateAssignment[]>([])
  const [interviewTemplates, setInterviewTemplates] = useState<TemplateListItem[]>([])
  const [questionnaireTemplates, setQuestionnaireTemplates] = useState<TemplateListItem[]>([])
  const [editingNode, setEditingNode] = useState<NodeTemplateAssignment | null>(null)

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug),
  })

  useEffect(() => {
    if (!slug) return
    setLoading(true)
    listNodeTemplates(slug)
      .then(assignments => setNodeAssignments(sortByActivityId(assignments)))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [slug])

  useEffect(() => {
    if (!slug) return
    Promise.all([
      listNodeTemplates(slug),
      listTemplates('interview'),
      listTemplates('questionnaire'),
    ]).then(([assignments, interviewTpls, questionnaireTpls]) => {
      setTemplateAssignments(sortByActivityId(assignments))
      setInterviewTemplates(interviewTpls)
      setQuestionnaireTemplates(questionnaireTpls)
    }).catch(console.error)
  }, [slug])

  async function handleTemplateChange(
    nodeLabel: string,
    field: 'interview_template_id' | 'questionnaire_template_id',
    value: number | null,
  ) {
    const current = templateAssignments.find((a) => a.node_label === nodeLabel)
    const updated: NodeTemplateAssignment = current
      ? { ...current, [field]: value }
      : { node_label: nodeLabel, activity_id: null, interview_template_id: null, questionnaire_template_id: null, [field]: value }

    setTemplateAssignments((prev) =>
      prev.some((a) => a.node_label === nodeLabel)
        ? prev.map((a) => (a.node_label === nodeLabel ? updated : a))
        : [...prev, updated],
    )

    try {
      await putNodeTemplate(slug, nodeLabel, {
        interview_template_id: updated.interview_template_id,
        questionnaire_template_id: updated.questionnaire_template_id,
      })
    } catch (e) {
      console.error('Auto-save failed', e)
    }
  }

  async function handlePublish(nodeLabel: string) {
    const name = window.prompt(`Template name for "${nodeLabel}":`)
    if (!name || !name.trim()) return
    try {
      await publishNodeTemplate(slug, nodeLabel, { name: name.trim(), description: '' })
    } catch (e) {
      console.error('Publish failed', e)
      alert('Publish failed - check that the interview script has been generated for this node.')
    }
  }

  const standardsRefs = settings?.standards_references

  return (
    <div className="space-y-5">

      {inspectCode && (
        <InterviewTypeDialog code={inspectCode} onClose={() => setInspectCode(null)} />
      )}

      {/* Standards context */}
      {standardsRefs && (
        <div className="rounded-lg bg-blue-50 border border-blue-100 px-3 py-2.5">
          <p className="text-[10px] font-bold text-blue-500 uppercase tracking-widest mb-1">Standards &amp; Frameworks</p>
          <p className="text-[11px] text-blue-700 leading-relaxed">{standardsRefs}</p>
          <p className="text-[10px] text-blue-500 mt-1">Edit in Alex's Setup tab.</p>
        </div>
      )}

      {/* Interview Programme overview */}
      <div>
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Interview Programme</p>
        <p className="text-[11px] text-gray-400 mb-3">
          Eight instrument types cover every organisational tier and external perspective. All templates are tailored to the project and value chain context — no manual assignment required.
        </p>
        <div className="space-y-1.5">
          {INTERVIEW_TYPES.map(t => (
            <div key={t.code} className={`rounded-lg border px-3 py-2 ${t.bg}`}>
              <div className="flex items-start gap-2.5">
                <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide flex-shrink-0 mt-0.5 ${t.badge}`}>
                  {t.code}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="text-[11px] font-semibold text-gray-800">{t.title}</span>
                    <span className="text-[10px] text-gray-500">{t.sections} · {t.duration}</span>
                  </div>
                  <p className="text-[10px] text-gray-500 mt-0.5">{t.who}</p>
                  <p className="text-[10px] text-gray-600 mt-0.5 italic">{t.feature}</p>
                </div>
                <button
                  onClick={() => setInspectCode(t.code)}
                  title="View interview approach and sections"
                  className="flex-shrink-0 text-gray-300 hover:text-gray-500 mt-0.5 transition-colors"
                >
                  <Info size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Value chain coverage */}
      <div>
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Value Chain Coverage</p>
        <p className="text-[11px] text-gray-400 mb-3">
          Interview type is hard-assigned by node level. L1 / L2 / L3 scripts use the library structure tailored to each node's context.
        </p>
        {loading ? (
          <p className="text-xs text-gray-400 animate-pulse py-4">Loading value chain…</p>
        ) : nodeAssignments.length === 0 ? (
          <p className="text-xs text-gray-400 italic py-4">
            No nodes yet — run the Value Chain crew (Alex) first.
          </p>
        ) : (
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100 text-left text-gray-400">
                  <th className="pb-1.5 pr-2 font-medium w-10">#</th>
                  <th className="pb-1.5 pr-3 font-medium">Node</th>
                  <th className="pb-1.5 pr-3 font-medium">Level</th>
                  <th className="pb-1.5 font-medium">Interview type</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {nodeAssignments.map(a => {
                  const isL1 = a.level === 'L1'
                  const badgeCls = LEVEL_BADGE[a.level ?? ''] ?? 'bg-gray-100 text-gray-500'
                  const typeName = a.level ? (LEVEL_INTERVIEW_NAME[a.level] ?? a.level) : '—'
                  return (
                    <tr key={a.node_label} className={isL1 ? 'bg-gray-50' : ''}>
                      <td className="py-2 pr-2 font-mono text-[10px] text-gray-400 whitespace-nowrap">
                        {a.activity_id ?? '-'}
                      </td>
                      <td className="py-2 pr-3">
                        <span className={`text-xs ${isL1 ? 'font-semibold text-gray-900' : 'text-gray-700'}`}>
                          {a.node_label}
                        </span>
                      </td>
                      <td className="py-2 pr-3">
                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide ${badgeCls}`}>
                          {a.level ?? '—'}
                        </span>
                      </td>
                      <td className="py-2 text-[11px] text-gray-600">
                        {typeName}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-3 rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
          <p className="text-[10px] text-gray-400">
            <span className="font-medium text-gray-500">C · A · F · S</span> templates are generated for stakeholders assigned these levels in the Stakeholder Registry.
          </p>
        </div>
      </div>

      {/* Node Template Assignment — moved from the old Value Chain page's Templates
          tab, unchanged. Assigns a saved interview or questionnaire template to a
          specific node, overriding the generated default above. Per-level generation
          is meant to replace this eventually, but that generation does not exist
          yet, so this stays the only way to assign templates. */}
      <div>
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Node Template Assignment</p>
        <p className="text-[11px] text-gray-400 mb-3">
          Assign interview and questionnaire templates to each value chain node. Changes save automatically.
        </p>

        {templateAssignments.length === 0 ? (
          <p className="text-xs text-gray-400 italic py-4">
            Run the Value Chain crew first to generate nodes.
          </p>
        ) : (
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100 text-left text-gray-400">
                  <th className="pb-1.5 pr-2 font-medium w-10">#</th>
                  <th className="pb-1.5 pr-3 font-medium">Node</th>
                  <th className="pb-1.5 pr-3 font-medium">Interview Template</th>
                  <th className="pb-1.5 pr-3 font-medium">Questionnaire Template</th>
                  <th className="pb-1.5 pr-3 font-medium">Publish</th>
                  <th className="pb-1.5 font-medium">Script</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {templateAssignments.map((assignment) => {
                  const isL1 = assignment.level === 'L1'
                  return (
                    <tr key={assignment.node_label} className={isL1 ? 'bg-gray-50' : ''}>
                      <td className="py-2 pr-2 font-mono text-[10px] text-gray-400 whitespace-nowrap">
                        {assignment.activity_id ?? '-'}
                      </td>
                      <td className="py-2 pr-3">
                        <div className={isL1 ? 'font-semibold text-gray-900 text-xs' : 'font-medium text-gray-700 text-xs'}>
                          {assignment.node_label}
                        </div>
                        {isL1 && (
                          <span className="text-[9px] text-brand bg-brand/10 px-1.5 py-0.5 rounded font-medium">L1 Leadership</span>
                        )}
                      </td>
                      <td className="py-2 pr-3">
                        <select
                          value={assignment.interview_template_id ?? ''}
                          onChange={(e) =>
                            handleTemplateChange(
                              assignment.node_label,
                              'interview_template_id',
                              e.target.value ? Number(e.target.value) : null,
                            )
                          }
                          className="bg-white border border-gray-200 rounded px-2 py-1 text-xs text-gray-900 outline-none focus:border-brand w-full max-w-[10rem]"
                        >
                          <option value="">- None -</option>
                          {interviewTemplates.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="py-2 pr-3">
                        <select
                          value={assignment.questionnaire_template_id ?? ''}
                          onChange={(e) =>
                            handleTemplateChange(
                              assignment.node_label,
                              'questionnaire_template_id',
                              e.target.value ? Number(e.target.value) : null,
                            )
                          }
                          className="bg-white border border-gray-200 rounded px-2 py-1 text-xs text-gray-900 outline-none focus:border-brand w-full max-w-[10rem]"
                        >
                          <option value="">- None -</option>
                          {questionnaireTemplates.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="py-2 pr-3">
                        <button
                          type="button"
                          onClick={() => handlePublish(assignment.node_label)}
                          className="px-2.5 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 text-[11px] rounded transition-colors"
                        >
                          Publish
                        </button>
                      </td>
                      <td className="py-2">
                        {!isL1 && (
                          <button
                            type="button"
                            onClick={() => setEditingNode(assignment)}
                            className="px-2.5 py-1 border border-gray-200 hover:border-brand hover:text-brand text-gray-500 text-[11px] rounded transition-colors"
                          >
                            Edit Script
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editingNode && (
        <InterviewTemplateEditor
          slug={slug}
          nodeLabel={editingNode.node_label}
          activityId={editingNode.activity_id}
          onClose={() => setEditingNode(null)}
        />
      )}

    </div>
  )
}
