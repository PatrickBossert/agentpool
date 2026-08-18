// ui/src/pages/DataArchitecture.tsx
//
// Data Architecture & Privacy, for one project, generated from the system's own declarations.
//
// Everything under "What this system says about itself" is rendered from
// GET /projects/{slug}/data-architecture, which reads agents/egress.py, agents/reads.py and
// agents/charter.py through agents/graph.py. Nothing in that half is typed here. The page this
// replaced was entirely hand-typed and had drifted in four directions at once: it named
// Anthropic forty-four times and Tavily seventeen, listed "Web fetch" as a tool two agents hold
// while giving it no destination anywhere, showed a crew called "Discovery" that no dispatch map
// has known for two sprints, and carried its own list of the seventeen personas.
//
// The second half, "Undertakings", is prose on purpose and is kept visibly apart from the first.
// Retention is not derivable: no declaration in this repository can say that ElevenLabs
// synthesises in real time and keeps nothing, or that the skills library is a deliberate
// always-hosted exception. A reader has to be able to tell what the system asserts about itself
// from what a person has promised, so the two never share a section.
//
// The route is administrator-only (see router.tsx). It was outside ProtectedRoute - public by
// omission rather than design - while its only link has always sat inside the guard.
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Cloud,
  Database,
  FileSignature,
  Globe,
  Lock,
  Server,
  Share2,
  ShieldCheck,
  Users,
  Workflow,
  Zap,
} from 'lucide-react'
import { dataArchitectureApi } from '../api/dataArchitecture'
import type { DataArchitecture as DataArchitectureModel } from '../api/dataArchitecture'
import { projectsApi } from '../api/endpoints'
import { describeError } from '../utils/describeError'
import logoUrl from '../assets/TR_Logo_strapiline.png'

// ── Small pieces ──────────────────────────────────────────────────────────────

type Tone = 'neutral' | 'leaves' | 'stays' | 'warn'

const TONE: Record<Tone, string> = {
  neutral: 'bg-surface text-muted border-surface-border',
  leaves: 'bg-amber-50 text-amber-800 border-amber-200',
  stays: 'bg-green-50 text-green-700 border-green-200',
  warn: 'bg-red-50 text-red-700 border-red-200',
}

function Pill({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: Tone }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border whitespace-nowrap ${TONE[tone]}`}
    >
      {children}
    </span>
  )
}

function EgressPill({ leaves }: { leaves: boolean }) {
  return leaves ? (
    <Pill tone="leaves">
      <Globe size={10} />
      Leaves this deployment
    </Pill>
  ) : (
    <Pill tone="stays">
      <Lock size={10} />
      Stays on this server
    </Pill>
  )
}

function Section({
  title,
  icon,
  intro,
  children,
}: {
  title: string
  icon: React.ReactNode
  intro?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="mb-10">
      <div className="flex items-center gap-2 mb-3 pb-2 border-b border-surface-border">
        <span className="text-brand-dark">{icon}</span>
        <h2 className="text-base font-bold text-primary">{title}</h2>
      </div>
      {intro && <p className="text-xs text-muted leading-relaxed mb-4">{intro}</p>}
      {children}
    </section>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-4">{children}</div>
  )
}

// ── The generated half ────────────────────────────────────────────────────────

// The scope notice derives *who* falls outside the declared crews and deliberately does not
// explain *why*. It is `pam` today, and the reason is that her own orchestration crews are
// built outside the graph - but an agent that falls out of every crew for some quite different
// reason tomorrow would inherit that sentence as an account of its own absence, which is a
// derived list carrying a hard-coded explanation. What is said instead is true of any orphan:
// whatever it runs outside the declared crews is not enumerated here.
function ScopeNotice({ data }: { data: DataArchitectureModel }) {
  const orphans = data.scope.agents_in_no_crew
  return (
    <div className="rounded-xl border border-brand-light bg-surface-raised p-5 mb-8 flex items-start gap-3">
      <ShieldCheck size={18} className="text-brand-dark flex-shrink-0 mt-0.5" />
      <div>
        <p className="text-sm font-semibold text-primary mb-1">What this page covers, and what it does not</p>
        <p className="text-xs text-secondary leading-relaxed">
          Everything in the first half of this page is generated from the declarations the system
          holds about itself - what each tool reaches, what each agent draws on, and what each crew
          is for - and resolved for this project's own processing mode. It covers the{' '}
          <strong>{data.scope.crew_count} crews</strong> the system declares.
        </p>
        {orphans.length > 0 && (
          <p className="text-xs text-secondary leading-relaxed mt-2">
            It does not cover everything that runs on an engagement.{' '}
            {orphans.map((a) => a.display_name).join(', ')}{' '}
            {orphans.length === 1 ? 'runs' : 'run'} in none of those crews, so whatever{' '}
            {orphans.length === 1 ? 'that agent executes' : 'those agents execute'} outside them
            is not enumerated below. Every agent inside the declared crews is.
          </p>
        )}
      </div>
    </div>
  )
}

function ModeBanner({ data }: { data: DataArchitectureModel }) {
  const moved = [
    ...data.tools.filter((t) => t.gated_by_mode).map((t) => t.tool),
    ...(data.inference.gated_by_mode ? ["the agents' own model calls"] : []),
  ]
  const unmoved = data.tools.filter((t) => !t.gated_by_mode && t.leaves_deployment)
  return (
    <Card>
      <div className="flex items-center gap-2 mb-2">
        <p className="text-sm font-semibold text-primary">Processing mode</p>
        <Pill tone={data.llm_mode === 'sensitive' ? 'stays' : 'neutral'}>{data.llm_mode}</Pill>
      </div>
      <p className="text-xs text-muted leading-relaxed">
        The mode moves {moved.length} of the destinations below: {moved.join(', ')}. It moves
        nothing else. {unmoved.length} of the tools this project's agents hold reach outside this
        deployment in either mode - {unmoved.map((t) => t.tool).join(', ')} - so a sensitive
        project reaches those the same way a standard one does.
      </p>
    </Card>
  )
}

function EgressTable({ data }: { data: DataArchitectureModel }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-surface-border">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-surface border-b border-surface-border">
            <th className="text-left px-4 py-2.5 font-semibold text-muted">Tool</th>
            <th className="text-left px-4 py-2.5 font-semibold text-muted">Reaches</th>
            <th className="text-left px-4 py-2.5 font-semibold text-muted">Where that is, here</th>
            <th className="text-left px-4 py-2.5 font-semibold text-muted">What travels</th>
            <th className="text-left px-4 py-2.5 font-semibold text-muted">Held by</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-t border-surface-border bg-surface">
            <td className="px-4 py-2.5 font-medium text-primary">
              Model inference
              <div className="mt-1">
                <Pill tone="neutral">Every agent</Pill>
              </div>
            </td>
            <td className="px-4 py-2.5 text-secondary">{data.inference.reaches}</td>
            <td className="px-4 py-2.5 text-secondary">
              {data.inference.destination}
              <div className="mt-1">
                <EgressPill leaves={data.inference.leaves_deployment} />
              </div>
            </td>
            <td className="px-4 py-2.5 text-secondary">{data.inference.sends}</td>
            <td className="px-4 py-2.5 text-muted">All {data.agents.length} agents</td>
          </tr>
          {data.tools.map((row) => (
            <tr key={row.tool} className="border-t border-surface-border">
              <td className="px-4 py-2.5 font-medium text-primary">
                {row.tool}
                {row.gated_by_mode && (
                  <div className="mt-1">
                    <Pill tone="neutral">Moves with the mode</Pill>
                  </div>
                )}
              </td>
              <td className="px-4 py-2.5 text-secondary">{row.reaches}</td>
              <td className="px-4 py-2.5 text-secondary">
                {row.destination}
                <div className="mt-1">
                  <EgressPill leaves={row.leaves_deployment} />
                </div>
              </td>
              <td className="px-4 py-2.5 text-secondary">{row.sends}</td>
              <td className="px-4 py-2.5 text-muted">{row.held_by.join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SharedSources({ data }: { data: DataArchitectureModel }) {
  if (data.shared_sources.length === 0) return null
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle size={14} className="text-amber-700" />
        <p className="text-sm font-semibold text-amber-900">
          Not scoped to this project
        </p>
      </div>
      <p className="text-xs text-amber-800 leading-relaxed mb-3">
        These stores are not this engagement's alone - a Chroma collection whose name carries no
        project, or a table in the deployment's own database. They are shared with every other
        engagement that uses them, and material an agent draws from one of them did not
        necessarily come from this engagement - nor does material placed in one stay within it.
      </p>
      <ul className="space-y-2">
        {data.shared_sources.map((s) => (
          <li key={s.source} className="text-xs text-amber-900">
            <span className="font-mono font-semibold">{s.source}</span>
            <span className="text-amber-700"> - {s.medium}</span>
            {s.handed_to_every_agent ? (
              <span className="text-amber-700">
                , handed to every agent when a crew is dispatched
              </span>
            ) : (
              <span className="text-amber-700">, declared readers: {s.read_by.join(', ')}</span>
            )}
            {s.reachable_by.length > s.read_by.length && (
              <span className="block text-amber-800">
                Those are the agents instructed to read it. The collection is an argument to{' '}
                {s.via}, so any of the {s.reachable_by.length} agents holding that tool can query
                it: {s.reachable_by.join(', ')}.
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function AgentCard({ agent }: { agent: DataArchitectureModel['agents'][number] }) {
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised">
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 border-b border-surface-border">
        <div>
          <p className="text-sm font-semibold text-primary">{agent.display_name}</p>
          <p className="text-[11px] text-brand-dark font-medium">
            {agent.crews.length > 0 ? agent.crews.join(', ') : 'In no declared crew'}
          </p>
        </div>
        <div className="flex flex-wrap gap-1 justify-end">
          {agent.destinations.map((d) => (
            <Pill key={d.label} tone={d.leaves_deployment ? 'leaves' : 'stays'}>
              {d.label}
            </Pill>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3 px-4 py-3">
        <div>
          <p className="text-[10px] font-bold text-muted uppercase tracking-widest mb-1">Tools</p>
          <div className="flex flex-wrap gap-1">
            {agent.tools.length > 0 ? (
              agent.tools.map((t) => <Pill key={t}>{t}</Pill>)
            ) : (
              <span className="text-[11px] text-muted">None</span>
            )}
          </div>
        </div>
        <div>
          <p className="text-[10px] font-bold text-muted uppercase tracking-widest mb-1">Writes</p>
          <div className="flex flex-wrap gap-1">
            {agent.writes.length > 0 ? (
              agent.writes.map((w) => <Pill key={w}>{w}</Pill>)
            ) : (
              <span className="text-[11px] text-muted">Nothing</span>
            )}
          </div>
        </div>
        <div className="md:col-span-2">
          <p className="text-[10px] font-bold text-muted uppercase tracking-widest mb-1">
            Draws on
          </p>
          {agent.sources.length === 0 ? (
            <p className="text-[11px] text-muted">
              Nothing is handed to this agent - it works from what it is told to do.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {agent.sources.map((s) => (
                <li key={`${s.source}:${s.via}`} className="text-[11px] text-secondary leading-relaxed">
                  <span className="font-mono font-semibold text-primary">{s.source}</span>{' '}
                  <span className="text-muted">
                    ({s.medium}, through {s.via})
                  </span>
                  {s.shared_beyond_this_project && (
                    <span className="ml-1">
                      <Pill tone="warn">Shared beyond this project</Pill>
                    </span>
                  )}
                  <span className="block text-muted">{s.note}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

// ── The prose half ────────────────────────────────────────────────────────────

// Commitments a person has made, which no declaration in this repository can derive. Kept in
// one place, under one heading, so that the boundary between "the system says this about
// itself" and "we promise this" is a section break rather than a matter of tone.
//
// `appliesTo` is what stops this half contradicting the other. These are prose, but they are
// prose *about* a deployment whose behaviour the generated half has just described, and the
// first version of this array was mapped unconditionally: on a sensitive engagement the table
// said inference resolves to the local model and stayed on this server, and two sections later
// a card headed "Anthropic - inference, in flight only" asserted a contract about Anthropic
// processing that client's prompts. It over-reported exposure rather than hiding it, so it was
// not a safety hole - but a visible self-contradiction on the one question the page exists to
// answer, on the engagement type read most carefully, is worse than most safety holes for what
// it does to a reader's trust in everything around it.
//
// Note what is NOT done here: the Anthropic card is not simply hidden on a sensitive project.
// Anthropic is still reached on one - the skills library is hosted by decision whatever the
// project's mode - so removing the terms altogether would under-report. The card is replaced by
// one that says which paths do and do not reach it.
const UNDERTAKINGS: {
  title: string
  detail: string
  appliesTo?: (data: DataArchitectureModel) => boolean
}[] = [
  {
    title: 'Anthropic - inference, in flight only',
    detail:
      "Under Anthropic's commercial terms, API inputs and outputs are not used to train models and are not retained beyond the call. That is a contractual undertaking, not something this system can observe.",
    appliesTo: (data) => data.inference.leaves_deployment,
  },
  {
    title: "Anthropic - not this engagement's agents",
    detail:
      "This engagement's inference resolves to the local model on this host, so no agent's prompt reaches Anthropic. One path still does, whatever the mode: the skills library below. Anthropic's commercial terms - inputs and outputs neither retained beyond the call nor used for training - govern that path.",
    appliesTo: (data) => !data.inference.leaves_deployment,
  },
  {
    title: 'ElevenLabs - speech synthesis, nothing kept',
    detail:
      'Interview question text is streamed for synthesis and is not retained. Voice services were accepted in secure mode by decision on that basis; local speech synthesis is future work rather than a current requirement.',
  },
  {
    title: 'Deepgram - transcription, nothing kept',
    detail:
      'Interview audio is streamed for transcription with content retention disabled. The same decision covers it as covers ElevenLabs, and for the same reason.',
  },
  {
    title: 'Resend - invitation and reminder email',
    detail:
      "Interview invitations carry a stakeholder's name and a unique link. Delivery logs are held by Resend under its own policy. Email is a dispatch path rather than an agent tool, so it does not appear in the generated table above.",
  },
  {
    title: 'Review gates notify nobody',
    detail:
      'When an agent pauses for a review, the request is written to this project’s own database and the agent waits there for a decision. Nothing is pushed out to announce it - the automation webhook that used to relay review prompts to Slack has been retired and no channel has replaced it, so a reviewer finds a waiting gate by opening this dashboard.',
  },
  {
    title: 'The skills library is deliberately always hosted',
    detail:
      "Reviewer feedback about how an agent behaves is summarised by a hosted model regardless of a project's mode. This is a decision rather than an oversight: the library is global across engagements and its endpoints carry no project, so there is no project mode to honour. It is still reviewer feedback typed on an engagement, and a project-scoped library is the fix if that stops being acceptable.",
  },
  {
    title: 'Paths outside the crews',
    detail:
      "Not everything that touches this engagement's material is an agent in a crew: uploading a document indexes it, an interview answer is indexed as it is given, the agent chat retrieves against the same collections, and a live interview presses for elaboration. Each of those was checked against the table above and reaches only destinations already named there, and each follows this project's processing mode. They are stated here rather than in the generated half because nothing derives them.",
  },
  {
    title: 'Data at rest, and in transit',
    detail:
      "Project databases and output files live on this server's filesystem; disk encryption and file permissions belong to whoever hosts it. All traffic to this application and onward to every third party is over TLS. Third-party keys live in the server's environment and are never returned to the browser.",
  },
  {
    title: 'One database, one directory, per project',
    detail:
      'Each engagement has its own SQLite database and its own outputs directory, and access is checked against project membership on every request. The exceptions are named above: any store the generated half marks as shared is shared.',
  },
]

// ── Page ──────────────────────────────────────────────────────────────────────

function Chrome({ subtitle, children }: { subtitle: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-surface">
      <div className="bg-surface-raised border-b border-surface-border px-6 py-4 flex items-center gap-4">
        <img src={logoUrl} alt="TaskReimagination.ai" className="h-7 w-auto" />
        <div className="border-l border-surface-border pl-4">
          <h1 className="text-sm font-bold text-primary">Data Architecture &amp; Privacy</h1>
          <p className="text-xs text-muted">{subtitle}</p>
        </div>
      </div>
      <div className="max-w-5xl mx-auto px-6 py-8">{children}</div>
    </div>
  )
}

function ProjectChooser() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['projects'],
    queryFn: () => projectsApi.list(),
  })

  return (
    <Chrome subtitle="Choose an engagement">
      <Section
        title="Which engagement?"
        icon={<Server size={16} />}
        intro="The answer depends on the project: its processing mode decides where inference and the document store actually are, so this page is generated per engagement rather than once."
      >
        {isLoading && <p className="text-xs text-muted">Loading engagements...</p>}
        {error && (
          <p className="text-xs text-red-700">{describeError(error, 'Could not load the engagements.')}</p>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {(data ?? []).map((p) => (
            <Link
              key={p.slug}
              to={`/data-architecture/${p.slug}`}
              className="rounded-lg border border-surface-border bg-surface-raised p-4 hover:border-brand"
            >
              <p className="text-sm font-semibold text-primary">{p.slug}</p>
              <p className="text-xs text-muted">
                {p.sector} - {p.llm_mode}
              </p>
            </Link>
          ))}
        </div>
      </Section>
    </Chrome>
  )
}

export default function DataArchitecture() {
  const { slug } = useParams<{ slug?: string }>()

  const { data, isLoading, error } = useQuery({
    queryKey: ['data-architecture', slug],
    queryFn: () => dataArchitectureApi.get(slug!),
    enabled: !!slug,
  })

  if (!slug) return <ProjectChooser />

  if (isLoading) {
    return (
      <Chrome subtitle={slug}>
        <p className="text-xs text-muted">Reading this engagement's declarations...</p>
      </Chrome>
    )
  }

  if (error || !data) {
    return (
      <Chrome subtitle={slug}>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="text-xs text-red-700">
            {describeError(error, "Could not load this engagement's data architecture.")}
          </p>
        </div>
      </Chrome>
    )
  }

  return (
    <Chrome subtitle={`${data.slug} - how this engagement's material is stored, processed, and passed on`}>
      <ScopeNotice data={data} />

      <Section
        title="What this system says about itself"
        icon={<Server size={16} />}
        intro="Generated from the declarations, not written by hand. If a tool's destination or an agent's inputs change, this changes with them."
      >
        <div className="space-y-4">
          <ModeBanner data={data} />
          <SharedSources data={data} />
        </div>
      </Section>

      <Section
        title="Where this project's work reaches"
        icon={<Cloud size={16} />}
        intro="One row per tool this project's agents hold, plus the model calls every agent makes. The destination is the one that applies in this project's mode."
      >
        <EgressTable data={data} />
        {data.declared_not_held.length > 0 && (
          <div className="mt-4 rounded-lg border border-surface-border bg-surface p-4">
            <p className="text-xs font-semibold text-primary mb-2">
              Declared, and held by no agent on this deployment
            </p>
            <p className="text-xs text-muted leading-relaxed mb-2">
              These are described so that nothing is silently missing from the table above. No
              agent holds them, so nothing here is in use.
            </p>
            <ul className="space-y-1">
              {data.declared_not_held.map((t) => (
                <li key={t.tool} className="text-xs text-secondary">
                  <span className="font-semibold">{t.tool}</span> - would reach {t.reaches} ({t.destination})
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      <Section
        title="What is handed to every agent when a crew runs"
        icon={<Share2 size={16} />}
        intro="Read on the agent's behalf by the dispatch path and folded into its instructions before the crew starts. No agent asks for these, and none can decline them."
      >
        <div className="space-y-2">
          {data.dispatch_reads.map((r) => (
            <div key={r.source} className="rounded-lg border border-surface-border bg-surface-raised p-3">
              <p className="text-xs font-mono font-semibold text-primary">{r.source}</p>
              <p className="text-[11px] text-muted">{r.medium}</p>
              <p className="text-[11px] text-secondary leading-relaxed mt-1">{r.note}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section
        title="How a crew can be started"
        icon={<Workflow size={16} />}
        intro="What can start a crew, not who may - the authority to press any of these is a question of the caller's role, and is enforced by the API rather than described here."
      >
        <div className="space-y-2">
          {data.dispatch_paths.map((p) => (
            <div key={p.trigger} className="rounded-lg border border-surface-border bg-surface-raised p-3">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-xs font-semibold text-primary">{p.label}</p>
                {p.injects_dispatch_reads ? (
                  <Pill tone="neutral">Carries the material above</Pill>
                ) : (
                  <Pill tone="warn">Carries none of the material above</Pill>
                )}
              </div>
              <p className="text-[11px] text-secondary leading-relaxed mt-1">{p.note}</p>
              {p.defect && (
                <p className="text-[11px] text-red-700 leading-relaxed mt-1">{p.defect}</p>
              )}
            </div>
          ))}
        </div>
      </Section>

      <Section
        title="The crews"
        icon={<Users size={16} />}
        intro="Each crew's purpose, what it waits on, and which of the paths above can start it."
      >
        <div className="space-y-3">
          {data.crews.map((c) => (
            <div key={c.crew_id} className="rounded-lg border border-surface-border bg-surface-raised p-4">
              <div className="flex flex-wrap items-center gap-2 mb-1">
                <p className="text-sm font-semibold text-primary">{c.display_name}</p>
                {c.defect && <Pill tone="warn">Cannot currently run</Pill>}
              </div>
              <p className="text-xs text-secondary leading-relaxed">{c.purpose}</p>
              {c.note && <p className="text-[11px] text-muted leading-relaxed mt-1">{c.note}</p>}
              {c.defect && (
                <p className="text-[11px] text-red-700 leading-relaxed mt-1">{c.defect}</p>
              )}
              <div className="flex flex-wrap gap-1 mt-2">
                {c.agents.map((a) => (
                  <Pill key={a}>{a}</Pill>
                ))}
              </div>
              <p className="text-[11px] text-muted mt-2">
                Started by: {c.triggers.join('; ')}.
                {c.depends_on.length > 0 && ` Waits on ${c.depends_on.join(', ')}.`}
              </p>
            </div>
          ))}
        </div>
      </Section>

      <Section
        title="What each agent draws on"
        icon={<Zap size={16} />}
        intro={
          <>
            Every agent, with the tools it holds, everywhere its work can reach in this project's
            mode, and the material the deployment hands it. What is listed against an agent is
            what it is <strong>instructed</strong> to read. A Chroma collection is named at query
            time rather than fixed per agent, so any agent holding the query tool can reach any
            collection - including this project's interview answers and the shared sector store -
            whether or not it is listed below.
          </>
        }
      >
        <div className="space-y-3">
          {data.agents.map((a) => (
            <AgentCard key={a.agent_id} agent={a} />
          ))}
        </div>
      </Section>

      <Section
        title="Undertakings"
        icon={<FileSignature size={16} />}
        intro="This section is not generated. Retention, contractual terms, and deliberate exceptions cannot be derived from the code, so they are written here by a person and kept apart from everything above."
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {UNDERTAKINGS.filter((u) => u.appliesTo?.(data) ?? true).map((u) => (
            <Card key={u.title}>
              <p className="text-sm font-semibold text-primary mb-1">{u.title}</p>
              <p className="text-xs text-muted leading-relaxed">{u.detail}</p>
            </Card>
          ))}
        </div>
      </Section>

      <div className="border-t border-surface-border pt-6 pb-2 text-center">
        <p className="text-xs text-muted">
          <Database size={12} className="inline-block mr-1 -mt-0.5" />
          TaskReimagination.ai - Data Architecture &amp; Privacy, generated for {data.slug}
        </p>
        <p className="text-xs text-muted mt-1">
          For questions about data handling, contact your TaskReimagination.ai engagement lead.
        </p>
      </div>
    </Chrome>
  )
}
