// ui/src/pages/DataArchitecture.tsx
// Stakeholder-facing page — publicly accessible at /dashboard/data-architecture.
// Explains where and how project data is stored and processed.

import { ShieldCheck, Database, Cloud, Globe, AlertTriangle, Lock, Server, Zap } from 'lucide-react'
import logoUrl from '../assets/TR_Logo_strapiline.png'

// ── Design tokens ─────────────────────────────────────────────────────────────

function Badge({ children, colour }: { children: React.ReactNode; colour: 'green' | 'blue' | 'amber' | 'orange' | 'gray' }) {
  const cls: Record<string, string> = {
    green:  'bg-green-50 text-green-700 border-green-200',
    blue:   'bg-blue-50 text-blue-700 border-blue-200',
    amber:  'bg-amber-50 text-amber-700 border-amber-200',
    orange: 'bg-orange-50 text-orange-700 border-orange-200',
    gray:   'bg-gray-50 text-gray-600 border-gray-200',
  }
  return (
    <span className={`inline-block text-[11px] font-semibold px-2 py-0.5 rounded-full border ${cls[colour]}`}>
      {children}
    </span>
  )
}

function PrivacyPill({ level }: { level: 0 | 1 | 2 | 3 }) {
  const config = [
    { label: 'L0 — Fully local',             colour: 'green'  as const, icon: <Lock size={10} /> },
    { label: 'L1 — Cloud processed',          colour: 'blue'   as const, icon: <Cloud size={10} /> },
    { label: 'L2 — Third-party service',      colour: 'amber'  as const, icon: <Globe size={10} /> },
    { label: 'L3 — Public / workspace',       colour: 'orange' as const, icon: <AlertTriangle size={10} /> },
  ]
  const { label, colour, icon } = config[level]
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${
      colour === 'green'  ? 'bg-green-50 text-green-700 border-green-200' :
      colour === 'blue'   ? 'bg-blue-50 text-blue-700 border-blue-200' :
      colour === 'amber'  ? 'bg-amber-50 text-amber-700 border-amber-200' :
      'bg-orange-50 text-orange-700 border-orange-200'
    }`}>{icon}{label}</span>
  )
}

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="mb-10">
      <div className="flex items-center gap-2 mb-4 pb-2 border-b border-gray-200">
        <span className="text-teal-600">{icon}</span>
        <h2 className="text-base font-bold text-gray-900">{title}</h2>
      </div>
      {children}
    </section>
  )
}

// ── Agent data manifest ───────────────────────────────────────────────────────

interface AgentEntry {
  agent: string
  crew: string
  tools: string[]
  externalServices: string[]
  dataShared: string
  storageAfterUse: string
  privacyLevel: 0 | 1 | 2 | 3
}

const AGENTS: AgentEntry[] = [
  {
    agent: 'PMO (Pamela Reid)',
    crew: 'Pipeline Director',
    tools: ['Project database read', 'Milestone tracker', 'Slack notifications', 'Human review gate'],
    externalServices: ['Anthropic Claude API', 'Slack'],
    dataShared: 'Full project state — milestones, crew run history, output summaries, review statuses, risk indicators. No client document content.',
    storageAfterUse: 'Anthropic: not retained. Slack: visible to workspace members.',
    privacyLevel: 2,
  },
  {
    agent: 'Value Chain Mapper (Alex Chen)',
    crew: 'Value Chain Mapping',
    tools: ['Web search (Tavily)', 'Web fetch', 'ChromaDB semantic search', 'Mermaid diagram renderer', 'Project state read/write'],
    externalServices: ['Anthropic Claude API', 'Tavily Search API'],
    dataShared: 'Organisation context, sector description, and ingested document excerpts sent to Claude. Web search sends keyword queries only (no document content) to Tavily.',
    storageAfterUse: 'Anthropic: not retained. Tavily: query logs per Tavily policy.',
    privacyLevel: 2,
  },
  {
    agent: 'Interaction Designer (Maya Patel)',
    crew: 'Assessment Design',
    tools: ['ChromaDB semantic search', 'Template library write', 'Project state read/write'],
    externalServices: ['Anthropic Claude API'],
    dataShared: 'Value chain structure, document excerpts from ChromaDB, configured assessment standards.',
    storageAfterUse: 'Anthropic: not retained.',
    privacyLevel: 1,
  },
  {
    agent: 'Stakeholder Manager (Jordan Williams)',
    crew: 'Stakeholder Management',
    tools: ['Stakeholder registry read', 'Interview session tracker', 'Slack notifications', 'Project state read/write'],
    externalServices: ['Anthropic Claude API', 'Slack'],
    dataShared: 'Stakeholder names, roles, email addresses, and coverage percentages sent to Claude. Stakeholder names and node assignments included in Slack notifications.',
    storageAfterUse: 'Anthropic: not retained. Slack: visible to workspace members.',
    privacyLevel: 2,
  },
  {
    agent: 'Requirements Capture (Sam Torres)',
    crew: 'Discovery',
    tools: ['Human review gate', 'Project state write'],
    externalServices: ['Anthropic Claude API'],
    dataShared: 'Consultant input from the HITL session; organisation context.',
    storageAfterUse: 'Anthropic: not retained.',
    privacyLevel: 1,
  },
  {
    agent: 'Requirements Analyst (Riley Kim)',
    crew: 'Discovery',
    tools: ['ChromaDB semantic search', 'Web search (Tavily)', 'Project state read/write'],
    externalServices: ['Anthropic Claude API', 'Tavily Search API'],
    dataShared: 'Captured requirements and document excerpts sent to Claude. Keyword queries sent to Tavily.',
    storageAfterUse: 'Anthropic: not retained. Tavily: query logs.',
    privacyLevel: 2,
  },
  {
    agent: 'Value Lever Analyst (Morgan Davis)',
    crew: 'Discovery',
    tools: ['ChromaDB semantic search', 'Web search (Tavily)', 'Web fetch', 'Project state read/write'],
    externalServices: ['Anthropic Claude API', 'Tavily Search API'],
    dataShared: 'Analysed requirements and sector context sent to Claude. Benchmarking queries sent to Tavily (no project data in search terms).',
    storageAfterUse: 'Anthropic: not retained. Tavily: query logs.',
    privacyLevel: 2,
  },
  {
    agent: 'Interview Coordinator (Taylor Brooks)',
    crew: 'Discovery Interviews',
    tools: ['Stakeholder registry read', 'Interview session creator', 'Human review gate', 'Project state read/write'],
    externalServices: ['Anthropic Claude API', 'Resend (email delivery)'],
    dataShared: 'Stakeholder names and interview schedule sent to Claude. Invitation emails (containing stakeholder name and unique interview link) sent via Resend.',
    storageAfterUse: 'Anthropic: not retained. Resend: email delivery logs per Resend policy.',
    privacyLevel: 2,
  },
  {
    agent: 'Stakeholder Interviewer (Avery Singh)',
    crew: 'Discovery Interviews',
    tools: ['Interview session manager', 'ElevenLabs TTS', 'Deepgram STT', 'Project state write'],
    externalServices: ['Anthropic Claude API', 'ElevenLabs (voice synthesis)', 'Deepgram (speech recognition)'],
    dataShared: 'Interview script text sent to ElevenLabs for voice synthesis. Stakeholder audio recordings sent to Deepgram for transcription. Interview responses sent to Claude for analysis.',
    storageAfterUse: 'Anthropic: not retained. ElevenLabs: not retained (TTS is real-time). Deepgram: transcription logs per Deepgram policy.',
    privacyLevel: 2,
  },
  {
    agent: 'Synthesis Analyst (Casey Liu)',
    crew: 'Discovery Interviews',
    tools: ['ChromaDB semantic search', 'Human review gate', 'Project state read/write'],
    externalServices: ['Anthropic Claude API'],
    dataShared: 'All completed interview transcripts (containing stakeholder responses) sent to Claude for synthesis.',
    storageAfterUse: 'Anthropic: not retained.',
    privacyLevel: 1,
  },
  {
    agent: 'Value Proposition Generator (Quinn Harper)',
    crew: 'Value Design',
    tools: ['ChromaDB semantic search', 'Human review gate', 'Project state read/write'],
    externalServices: ['Anthropic Claude API'],
    dataShared: 'Discovery findings, value levers, and interview synthesis sent to Claude.',
    storageAfterUse: 'Anthropic: not retained.',
    privacyLevel: 1,
  },
  {
    agent: 'Portfolio Manager (Blake Anderson)',
    crew: 'Value Design',
    tools: ['Excel export', 'Human review gate', 'Project state read/write'],
    externalServices: ['Anthropic Claude API'],
    dataShared: 'Initiative list, scoring weights, and financial parameters sent to Claude.',
    storageAfterUse: 'Anthropic: not retained.',
    privacyLevel: 1,
  },
  {
    agent: 'Enterprise Architect (Drew Mitchell)',
    crew: 'Architecture',
    tools: ['ChromaDB semantic search', 'Mermaid diagram renderer', 'Human review gate', 'Project state read/write'],
    externalServices: ['Anthropic Claude API'],
    dataShared: 'Portfolio register, initiative list, and document context excerpts sent to Claude.',
    storageAfterUse: 'Anthropic: not retained.',
    privacyLevel: 1,
  },
  {
    agent: 'Initiative Identifier (Sage Thompson)',
    crew: 'Architecture',
    tools: ['Human review gate', 'Project state read/write'],
    externalServices: ['Anthropic Claude API'],
    dataShared: 'Architecture blueprint sent to Claude for initiative decomposition.',
    storageAfterUse: 'Anthropic: not retained.',
    privacyLevel: 1,
  },
  {
    agent: 'Roadmap Generator (River Martinez)',
    crew: 'Delivery Planning',
    tools: ['HTML generator', 'JSON export', 'Human review gate', 'Project state read/write'],
    externalServices: ['Anthropic Claude API'],
    dataShared: 'Initiative register and portfolio scores sent to Claude.',
    storageAfterUse: 'Anthropic: not retained.',
    privacyLevel: 1,
  },
  {
    agent: 'Visual Illustrator (Luca Romano)',
    crew: 'Delivery Planning',
    tools: ['Project state read', 'JSON export'],
    externalServices: ['Anthropic Claude API'],
    dataShared: 'Value chain structure and roadmap data sent to Claude to generate illustration briefs (text descriptions only — no images are generated by this agent).',
    storageAfterUse: 'Anthropic: not retained.',
    privacyLevel: 1,
  },
  {
    agent: 'Business Plan Generator (Finley Cooper)',
    crew: 'Business Plan',
    tools: ['Word document export', 'PowerPoint export', 'Financial model', 'Human review gate', 'Project state read'],
    externalServices: ['Anthropic Claude API'],
    dataShared: 'Complete project model — value chain, propositions, initiatives, roadmap, and financial parameters — sent to Claude.',
    storageAfterUse: 'Anthropic: not retained.',
    privacyLevel: 1,
  },
]

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DataArchitecture() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
        <img src={logoUrl} alt="TaskReimagination.ai" className="h-7 w-auto" />
        <div className="border-l border-gray-200 pl-4">
          <h1 className="text-sm font-bold text-gray-900">Data Architecture &amp; Privacy</h1>
          <p className="text-xs text-gray-500">How your data is stored, processed, and protected</p>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-8">

        {/* Intro */}
        <div className="rounded-xl border border-teal-200 bg-teal-50 p-5 mb-8 flex items-start gap-3">
          <ShieldCheck size={18} className="text-teal-600 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-teal-800 mb-1">Your data stays on your infrastructure by default</p>
            <p className="text-xs text-teal-700 leading-relaxed">
              All project databases, documents, and outputs are stored on your own server — nothing is uploaded to a
              TaskReimagination.ai cloud service. AI inference is performed via the Anthropic Claude API (processed
              in-flight; not retained or used for training under Anthropic's enterprise terms). A small number of
              specialist tools — web search, voice synthesis, speech recognition, and messaging — use third-party
              services, and these are called out explicitly below.
            </p>
          </div>
        </div>

        {/* Architecture overview */}
        <Section title="System architecture" icon={<Server size={16} />}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              {
                title: 'Application server',
                detail: 'Python / FastAPI running on your infrastructure. Handles all API requests, crew orchestration, and file operations.',
                store: 'Your server',
                colour: 'green' as const,
              },
              {
                title: 'Project databases',
                detail: 'One SQLite file per project, stored at data/<project-slug>.db on your server. Contains crew runs, outputs, stakeholders, milestones, and interview sessions.',
                store: 'Your server (SQLite)',
                colour: 'green' as const,
              },
              {
                title: 'Document store / vector search',
                detail: 'ChromaDB running in a local Docker container (port 8002). Stores text embeddings of uploaded client documents for semantic retrieval. No data leaves your server.',
                store: 'Your server (Docker)',
                colour: 'green' as const,
              },
              {
                title: 'Output files',
                detail: 'Word documents, PowerPoint presentations, HTML roadmaps, and JSON data files are written to the local filesystem at projects/<slug>/outputs/.',
                store: 'Your server (filesystem)',
                colour: 'green' as const,
              },
              {
                title: 'AI inference — Anthropic Claude API',
                detail: 'AI agents send prompts (containing project context) to the Anthropic Claude API for inference. Under Anthropic\'s enterprise usage policy, API inputs and outputs are not used to train models and are not retained beyond the API call.',
                store: 'Ephemeral — not retained',
                colour: 'blue' as const,
              },
              {
                title: 'Sensitive mode (optional)',
                detail: 'When sensitive mode is enabled in project settings, all crew agents (except the PMO) route LLM calls to a locally-hosted LLaMA-compatible model via an OpenAI-compatible endpoint. No AI calls leave your server.',
                store: 'Your server (local LLM)',
                colour: 'green' as const,
              },
            ].map((item, i) => (
              <div key={i} className="rounded-lg border border-gray-200 bg-white p-4">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <h3 className="text-sm font-semibold text-gray-900">{item.title}</h3>
                  <Badge colour={item.colour}>{item.store}</Badge>
                </div>
                <p className="text-xs text-gray-600 leading-relaxed">{item.detail}</p>
              </div>
            ))}
          </div>
        </Section>

        {/* External services */}
        <Section title="External services" icon={<Cloud size={16} />}>
          <p className="text-xs text-gray-500 mb-4">These services are used by specific agents and are called only when that agent runs. They are not used by default for all projects.</p>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-2.5 font-semibold text-gray-600">Service</th>
                  <th className="text-left px-4 py-2.5 font-semibold text-gray-600">Purpose</th>
                  <th className="text-left px-4 py-2.5 font-semibold text-gray-600">Data sent</th>
                  <th className="text-left px-4 py-2.5 font-semibold text-gray-600">Retention</th>
                  <th className="text-left px-4 py-2.5 font-semibold text-gray-600">Privacy</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { svc: 'Anthropic Claude API', purpose: 'AI inference for all crew agents', sent: 'Project context in prompts (organisation name, sector, outputs, stakeholder names)', retention: 'Not retained; not used for training under enterprise terms', level: 1 as const },
                  { svc: 'Tavily Search API', purpose: 'Web search for benchmarking and sector research', sent: 'Keyword search queries (no project documents or stakeholder data)', retention: 'Query logs per Tavily privacy policy', level: 2 as const },
                  { svc: 'ElevenLabs', purpose: 'Text-to-speech for voice interviews', sent: 'Interview script text (questions, not stakeholder responses)', retention: 'Real-time synthesis; not retained', level: 2 as const },
                  { svc: 'Deepgram', purpose: 'Speech-to-text for voice interviews', sent: 'Stakeholder audio recordings during interview sessions', retention: 'Transcription logs per Deepgram privacy policy', level: 2 as const },
                  { svc: 'Slack', purpose: 'PMO and stakeholder management notifications', sent: 'Stakeholder names, node coverage %ages, and escalation summaries', retention: 'Slack workspace message history', level: 3 as const },
                  { svc: 'Resend', purpose: 'Interview invitation emails', sent: 'Stakeholder name and unique interview link', retention: 'Email delivery logs per Resend privacy policy', level: 2 as const },
                ].map((row, i) => (
                  <tr key={i} className="border-t border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-2.5 font-medium text-gray-800">{row.svc}</td>
                    <td className="px-4 py-2.5 text-gray-600">{row.purpose}</td>
                    <td className="px-4 py-2.5 text-gray-600">{row.sent}</td>
                    <td className="px-4 py-2.5 text-gray-600">{row.retention}</td>
                    <td className="px-4 py-2.5"><PrivacyPill level={row.level} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        {/* Privacy scale */}
        <Section title="Privacy level scale" icon={<Lock size={16} />}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {([
              { level: 0, title: 'Fully local', desc: 'All processing occurs on your server. No data leaves your infrastructure.' },
              { level: 1, title: 'Cloud processed — no training', desc: 'Data is sent to the Anthropic Claude API for inference. Under enterprise terms, API data is not retained and is not used to train models.' },
              { level: 2, title: 'Third-party service', desc: 'Data is shared with a third-party service (Tavily, ElevenLabs, Deepgram, Resend, or Slack) for a specific purpose. Each provider\'s privacy policy applies.' },
              { level: 3, title: 'Public / workspace-visible', desc: 'Data is sent to a team communication tool (Slack) and is visible to workspace members. Treat as semi-public.' },
            ] as { level: 0|1|2|3; title: string; desc: string }[]).map(({ level, title, desc }) => (
              <div key={level} className="rounded-lg border border-gray-200 bg-white p-4 flex items-start gap-3">
                <PrivacyPill level={level} />
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-gray-800 mb-1">{title}</p>
                  <p className="text-xs text-gray-500 leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Per-agent manifest */}
        <Section title="Per-agent data manifest" icon={<Zap size={16} />}>
          <p className="text-xs text-gray-500 mb-4">
            Each agent runs independently. The table below shows exactly which external services each agent calls,
            what project data is shared, and the resulting privacy level. Agents that are not used in a given project
            never run and never make external calls.
          </p>

          <div className="space-y-3">
            {AGENTS.map((a, i) => (
              <div key={i} className="rounded-lg border border-gray-200 bg-white">
                {/* Agent header */}
                <div className="flex items-start justify-between gap-4 px-4 py-3 border-b border-gray-100">
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{a.agent}</p>
                    <p className="text-[11px] text-teal-600 font-medium">{a.crew}</p>
                  </div>
                  <PrivacyPill level={a.privacyLevel} />
                </div>

                {/* Detail grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3 px-4 py-3">
                  <div>
                    <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Tools</p>
                    <div className="flex flex-wrap gap-1">
                      {a.tools.map((t, j) => (
                        <Badge key={j} colour="gray">{t}</Badge>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">External services</p>
                    <div className="flex flex-wrap gap-1">
                      {a.externalServices.map((s, j) => (
                        <Badge key={j} colour={s.includes('Anthropic') ? 'blue' : 'amber'}>{s}</Badge>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Data shared externally</p>
                    <p className="text-[11px] text-gray-600 leading-relaxed">{a.dataShared}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Storage after use</p>
                    <p className="text-[11px] text-gray-600 leading-relaxed">{a.storageAfterUse}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Security posture */}
        <Section title="Information security" icon={<Database size={16} />}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              { title: 'Authentication', detail: 'JWT bearer tokens with configurable expiry. All API endpoints (except the public interview page) require a valid token.' },
              { title: 'Transport encryption', detail: 'All HTTP traffic served over TLS (HTTPS) via Caddy in production. API calls to Anthropic and all third-party services are made over HTTPS.' },
              { title: 'Data at rest', detail: 'SQLite files and output files are stored on the host filesystem. File system permissions and disk encryption are the responsibility of the hosting infrastructure owner.' },
              { title: 'API key management', detail: 'Third-party API keys (Anthropic, Tavily, ElevenLabs, Deepgram, Resend) are stored in a .env file on the server and never exposed to the frontend or included in API responses.' },
              { title: 'Sensitive mode', detail: 'When enabled per project, all LLM calls except the PMO route to a local LLaMA-compatible model. The PMO always uses Claude Opus for governance and reporting quality.' },
              { title: 'No cross-project data leakage', detail: 'Each project uses an isolated SQLite database and output directory. Project access is enforced per-user via JWT claims and project membership checks on every API endpoint.' },
            ].map((item, i) => (
              <div key={i} className="rounded-lg border border-gray-200 bg-white p-4">
                <p className="text-sm font-semibold text-gray-900 mb-1">{item.title}</p>
                <p className="text-xs text-gray-600 leading-relaxed">{item.detail}</p>
              </div>
            ))}
          </div>
        </Section>

        {/* Footer */}
        <div className="border-t border-gray-200 pt-6 pb-2 text-center">
          <p className="text-xs text-gray-400">TaskReimagination.ai · Data Architecture &amp; Privacy Reference · v1</p>
          <p className="text-xs text-gray-300 mt-1">
            For questions about data handling, contact your TaskReimagination.ai engagement lead.
          </p>
        </div>
      </div>
    </div>
  )
}
