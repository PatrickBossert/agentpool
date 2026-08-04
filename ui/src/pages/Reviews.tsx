// ui/src/pages/Reviews.tsx
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CircleCheck, Clock, PauseCircle, Play, RotateCcw } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { projectsApi, commitsApi } from '../api/endpoints'
import { campaignsApi } from '../api/campaigns'
import { CrewApprovalRow, type CrewState } from '../components/CrewApprovalRow'
import { CREW_LABELS, agentDisplayName } from '../components/agentStatus'
import { CREW_OUTPUT_TYPE } from '../components/crewOutputs'
import type { AgentOutput, HumanReview, ReminderEmail } from '../types'

// A single crew's change count, fetched independently so one crew's request does not
// block the rest of the section from rendering.
function CrewApprovalRowWithChanges({
  slug,
  crewName,
  state,
  onSubmit,
  onApprove,
}: {
  slug: string
  crewName: string
  state: CrewState
  onSubmit: (crewName: string) => void | Promise<void>
  onApprove: (crewName: string) => void | Promise<void>
}) {
  // CrewApprovalRow discards this for a working crew (it hard-codes changeCount to 0
  // until there is something to approve), so fetching it then would be a wasted request
  // against every in-progress row on every poll.
  const { data: changeCount = 0 } = useQuery({
    queryKey: ['crew-changes', slug, crewName],
    queryFn: () => commitsApi.changeCount(slug, crewName),
    enabled: state === 'ready',
  })

  return (
    <CrewApprovalRow
      crewName={crewName}
      state={state}
      changeCount={changeCount}
      onSubmit={onSubmit}
      onApprove={onApprove}
    />
  )
}

type CommitOutcome = Awaited<ReturnType<typeof commitsApi.create>>

function crewLabel(crew: string) {
  return CREW_LABELS[crew] ?? crew
}

function joinLabels(crews: string[]) {
  const labels = crews.map(crewLabel)
  if (labels.length < 2) return labels.join('')
  return `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`
}

// What the approval just did. Without it the row flips to Approved and nothing else is
// said, so a start, a skip and a project-wide suppression all look identical from here.
//
// The skip is the one that costs something: the in-flight run read its inputs before this
// approval landed, so it does not contain what was just approved and has to be re-run.
// `waiting` is what makes an approval that started nothing legible - it names the approval
// still needed rather than leaving the reviewer to work it out.
function ApprovalOutcome({ outcome }: { outcome: CommitOutcome }) {
  const lines: { Icon: LucideIcon; tone: string; text: string }[] = []

  if (outcome.autostart_failed) {
    // The endpoint reports nothing else in this case, so neither does this - saying
    // "nothing is waiting" or "nothing follows" here would be inventing an answer.
    return (
      <div className="bg-surface-raised border border-gray-200 rounded-xl px-4 py-3">
        <p className="flex items-start gap-2 text-xs text-red-600">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            The next crew could not be started. The approval is recorded - check the crew
            board before assuming anything is running.
          </span>
        </p>
      </div>
    )
  }

  if (outcome.inactive) {
    lines.push({
      Icon: PauseCircle,
      tone: 'text-amber-700',
      text:
        'Nothing started - this project is not active yet. The approval is recorded; ' +
        'activate the project to let the next crew run.',
    })
  }

  const started = outcome.started ?? []
  const skipped = outcome.skipped ?? []
  const waiting = outcome.waiting ?? []

  if (started.length > 0) {
    lines.push({
      Icon: Play,
      tone: 'text-secondary',
      text: `Started ${joinLabels(started.map((s) => s.crew))}.`,
    })
  }

  if (skipped.length > 0) {
    lines.push({
      Icon: RotateCcw,
      tone: 'text-amber-700',
      text:
        `${joinLabels(skipped)} was already running, so this approval is not in ` +
        'it - re-run it once the current run finishes.',
    })
  }

  for (const item of waiting) {
    // A reason is given when the blocker is not an approval at all - Pamela dispatching
    // the crew herself, or configuration the project has never been given. Waiting for
    // an upstream approval is the ordinary case and names the crew instead.
    lines.push({
      Icon: Clock,
      tone: 'text-muted',
      text: item.reason
        ? `${crewLabel(item.crew)} did not start. ${item.reason}`
        : `${crewLabel(item.crew)} still needs ${joinLabels(item.waiting_on)}.`,
    })
  }

  if (lines.length === 0) {
    lines.push({
      Icon: CircleCheck,
      tone: 'text-muted',
      text: 'Approved. No crew follows this one.',
    })
  }

  return (
    <div className="bg-surface-raised border border-gray-200 rounded-xl px-4 py-3 space-y-1.5">
      {lines.map(({ Icon, tone, text }) => (
        <p key={text} className={`flex items-start gap-2 text-xs ${tone}`}>
          <Icon className="w-3.5 h-3.5 mt-0.5 shrink-0" aria-hidden="true" />
          <span>{text}</span>
        </p>
      ))}
    </div>
  )
}

// Every crew whose state is working or ready, so a contributor can mark work ready and
// an approver can approve it from the same place they review everything else.
//
// A crew that is working and has never been run has nothing to submit - it is omitted so
// the section lists work that exists rather than every crew in the graph.
function CrewApprovalSection({ slug }: { slug: string }) {
  const qc = useQueryClient()
  const [outcome, setOutcome] = useState<CommitOutcome | null>(null)

  const { data: states = {} } = useQuery({
    queryKey: ['crew-states', slug],
    queryFn: () => commitsApi.states(slug),
    refetchInterval: 5000,
  })

  const { data: status } = useQuery({
    queryKey: ['status', slug],
    queryFn: () => projectsApi.status(slug),
  })

  // Only a completed run produced real output. A run that failed, or is still
  // running, must not make its crew look ready for approval or ready to submit -
  // approving a failed crew commits zero outputs and still releases the next crew
  // on the board as though real work had been approved.
  const completedRunCrews = new Set(
    (status?.crew_runs ?? [])
      .filter((r) => r.status === 'completed')
      .map((r) => r.crew_name),
  )

  const crews = Object.entries(states).filter(([crew, state]) => {
    if (state === 'committed') return false
    if ((state === 'working' || state === 'ready') && !completedRunCrews.has(crew)) return false
    return true
  })

  async function invalidate() {
    await qc.invalidateQueries({ queryKey: ['crew-states', slug] })
    await qc.invalidateQueries({ queryKey: ['crew-readiness', slug] })
  }

  async function submit(crewName: string) {
    await commitsApi.submit(slug, crewName)
    await invalidate()
  }

  async function approve(crewName: string) {
    // Set before invalidating: the refetch drops this crew's row from the section, and
    // the outcome is the only thing left saying what the approval did.
    setOutcome(await commitsApi.create(slug, crewName))
    await invalidate()
  }

  if (crews.length === 0 && !outcome) return null

  return (
    <div className="space-y-3">
      {crews.length > 0 && (
        <div className="bg-surface rounded-xl border border-gray-200 px-4 py-2">
          {crews.map(([crew, state]) => (
            <CrewApprovalRowWithChanges
              key={crew}
              slug={slug}
              crewName={crew}
              state={state}
              onSubmit={submit}
              onApprove={approve}
            />
          ))}
        </div>
      )}
      {outcome && <ApprovalOutcome outcome={outcome} />}
    </div>
  )
}

// A project stays 'created' until this is clicked - nothing else in the product calls
// the activate endpoint. Two things read projects.status, and both are off until then:
// Pamela's daily report skips an inactive project (api/services/pam_report_job.py:133),
// and approving a crew's output records the approval but starts nothing
// (api/services/autostart_service.py). Approvers are already on this page to approve, so
// the act belongs here too.
function ActivateProjectControl({ slug }: { slug: string }) {
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: status } = useQuery({
    queryKey: ['status', slug],
    queryFn: () => projectsApi.status(slug),
  })

  if (!status || status.project_status === 'active') return null

  async function activate() {
    setBusy(true)
    setError(null)
    try {
      await commitsApi.activate(slug)
      await qc.invalidateQueries({ queryKey: ['status', slug] })
    } catch (err) {
      console.error(`Activating project "${slug}" failed:`, err)
      setError('That failed. Only an approver can activate a project.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center justify-between gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
      <div>
        <p className="text-sm text-amber-800">
          This project is not active yet - approving output will not start the next crew,
          and Pamela's daily report will not run, until it is.
        </p>
        {error && (
          <p role="alert" className="text-xs text-red-600 mt-1">
            {error}
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={() => void activate()}
        disabled={busy}
        className="shrink-0 text-xs font-semibold text-white bg-brand hover:bg-brand-dark px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
      >
        {busy ? 'Activating…' : 'Activate project'}
      </button>
    </div>
  )
}

function ReviewCard({ review, slug }: { review: HumanReview; slug: string }) {
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const qc = useQueryClient()

  async function resolve(decision: string) {
    setSubmitting(true)
    try {
      await projectsApi.resolveReview(slug, review.id, decision, notes)
      qc.invalidateQueries({ queryKey: ['reviews', slug] })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="bg-surface rounded-xl border-l-4 border-amber-500 overflow-hidden">
      <div className="px-4 pt-3 pb-2">
        <span className="rounded px-2 py-0.5 text-xs font-bold tracking-wide bg-amber-500/10 text-amber-400 uppercase">
          Pending
        </span>
        <p className="text-xs text-gray-400 mt-1.5">Run #{review.crew_run_id}</p>
      </div>
      <div className="px-4 pb-3">
        <p className="text-sm text-gray-700 leading-relaxed bg-gray-50 rounded-md px-3 py-2.5 border border-gray-200 whitespace-pre-wrap">
          {review.prompt}
        </p>
      </div>
      <div className="px-4 pb-4 flex flex-col gap-2.5">
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Notes for the crew (optional) - your text is returned verbatim as the crew's input"
          className="w-full bg-white border border-gray-200 rounded-md text-gray-700 text-sm px-3 py-2 resize-y min-h-[72px] placeholder:text-gray-400 focus:outline-none focus:border-brand"
        />
        <div className="flex gap-2 justify-end">
          <button
            disabled={submitting}
            onClick={() => resolve('changes_requested')}
            className="text-xs px-4 py-1.5 rounded-md bg-red-100 text-red-700 hover:bg-red-200 disabled:opacity-50 transition-colors"
          >
            Request Changes
          </button>
          <button
            disabled={submitting}
            onClick={() => resolve('approved')}
            className="text-xs px-4 py-1.5 rounded-md bg-emerald-100 text-emerald-700 hover:bg-emerald-200 disabled:opacity-50 transition-colors"
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  )
}

function ReminderEmailCard({ item, slug }: { item: ReminderEmail; slug: string }) {
  const [subject, setSubject] = useState(item.subject)
  const [body, setBody] = useState(item.body)
  const [submitting, setSubmitting] = useState(false)
  const qc = useQueryClient()

  const levelColour =
    item.escalation_level === 'urgent' ? 'border-red-500' :
    item.escalation_level === 'firm' ? 'border-amber-400' :
    'border-brand'

  async function resolve(status: 'approved' | 'dismissed') {
    setSubmitting(true)
    try {
      await campaignsApi.updateReminderEmail(slug, item.id, { status, subject, body })
      qc.invalidateQueries({ queryKey: ['reminder-emails', slug] })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={`bg-surface rounded-xl border-l-4 ${levelColour} overflow-hidden`}>
      <div className="px-4 pt-3 pb-2 flex items-center gap-2">
        <span className="rounded px-2 py-0.5 text-xs font-bold tracking-wide bg-brand/10 text-brand uppercase">
          Reminder - {item.escalation_level}
        </span>
      </div>
      <div className="px-4 pb-2 space-y-2">
        <div>
          <p className="text-[10px] text-gray-400 uppercase tracking-widest mb-1">Subject</p>
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="w-full bg-white border border-gray-200 rounded px-2 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
          />
        </div>
        <div>
          <p className="text-[10px] text-gray-400 uppercase tracking-widest mb-1">Body</p>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={6}
            className="w-full bg-white border border-gray-200 rounded-md text-gray-700 text-sm px-3 py-2 resize-y placeholder:text-gray-400 focus:outline-none focus:border-brand"
          />
        </div>
      </div>
      <div className="px-4 pb-4 flex gap-2 justify-end">
        <button
          disabled={submitting}
          onClick={() => resolve('dismissed')}
          className="text-xs px-4 py-1.5 rounded-md bg-gray-100 text-gray-500 hover:bg-gray-200 disabled:opacity-50 transition-colors"
        >
          Dismiss
        </button>
        <button
          disabled={submitting}
          onClick={() => resolve('approved')}
          className="text-xs px-4 py-1.5 rounded-md bg-brand/20 text-brand hover:bg-brand/30 disabled:opacity-50 transition-colors"
        >
          Approve & Send
        </button>
      </div>
    </div>
  )
}

// An output's crew deliverable, plus PAM's report. Listing every pending output would put
// 79 rows in this queue for one project, two dozen of them variants of one interview
// script - so the queue shows the artefact each crew is judged on.
//
// PAM is deliberately absent from CREW_OUTPUT_TYPE because her Output tab is an Overview
// rather than a versioned artefact. Naming her report here rather than adding her to that
// map keeps the queue right without changing her tab or the Dashboard preview.
const REVIEWABLE_OUTPUT_TYPES = new Set([...Object.values(CREW_OUTPUT_TYPE), 'pam_report'])

function OutputReviewCard({ output, slug }: { output: AgentOutput; slug: string }) {
  const qc = useQueryClient()
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)

  async function decide(decision: string) {
    setBusy(true)
    try {
      await projectsApi.submitOutputReview(slug, output.id, decision, notes)
      await qc.invalidateQueries({ queryKey: ['outputs', slug] })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      data-testid={`output-review-${output.id}`}
      className="bg-surface-card border border-surface-border rounded-lg p-4 shadow-sm"
    >
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-primary">
          {agentDisplayName(output.agent_name)}
          <span className="text-muted font-normal"> · {output.output_type}</span>
        </p>
        <span className="text-xs text-muted font-mono">v{output.version}</span>
      </div>
      <textarea
        data-testid={`output-notes-${output.id}`}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="What needs changing? Left empty when approving."
        rows={2}
        className="mt-3 w-full bg-surface rounded px-2 py-1 text-xs text-secondary resize-none"
      />
      <div className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          data-testid={`request-changes-output-${output.id}`}
          disabled={busy}
          onClick={() => decide('changes_requested')}
          className="text-xs text-secondary px-3 py-1 disabled:opacity-40"
        >
          Request changes
        </button>
        <button
          type="button"
          data-testid={`approve-output-${output.id}`}
          disabled={busy}
          onClick={() => decide('approved')}
          className="text-xs bg-brand text-white rounded px-3 py-1 disabled:opacity-40"
        >
          Approve
        </button>
      </div>
    </div>
  )
}

export default function Reviews() {
  const { slug } = useParams<{ slug: string }>()

  const { data: reviews = [], isLoading } = useQuery({
    queryKey: ['reviews', slug],
    queryFn: () => projectsApi.listReviews(slug!),
    enabled: !!slug,
    refetchInterval: 5000,
  })

  const { data: outputs = [] } = useQuery({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug,
    refetchInterval: 10_000,
  })

  const pendingOutputs = outputs.filter(
    (o) => o.is_current && o.review_status === 'pending' &&
      REVIEWABLE_OUTPUT_TYPES.has(o.output_type),
  )

  const { data: reminderEmails = [] } = useQuery({
    queryKey: ['reminder-emails', slug],
    queryFn: () => campaignsApi.listReminderEmails(slug!),
    enabled: !!slug,
    refetchInterval: 10_000,
  })

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">Reviews</h2>
      {slug && <ActivateProjectControl slug={slug} />}
      {slug && <CrewApprovalSection slug={slug} />}
      {pendingOutputs.length > 0 && (
        <>
          <h3 className="text-sm font-semibold text-gray-700 mt-6 mb-3">
            Outputs awaiting review
          </h3>
          <div className="space-y-4">
            {pendingOutputs.map((o) => (
              <OutputReviewCard key={o.id} output={o} slug={slug!} />
            ))}
          </div>
        </>
      )}
      {isLoading && <p className="text-sm text-gray-400">Loading...</p>}
      {!isLoading && reviews.length === 0 && pendingOutputs.length === 0 && (
        <p className="text-sm text-gray-400">
          No pending reviews - the crew is running autonomously.
        </p>
      )}
      <div className="space-y-4">
        {reviews.map((r) => (
          <ReviewCard key={r.id} review={r} slug={slug!} />
        ))}
      </div>
      {reminderEmails.length > 0 && (
        <>
          <h3 className="text-sm font-semibold text-gray-700 mt-6 mb-3">Reminder Emails</h3>
          <div className="space-y-4">
            {reminderEmails.map((item) => (
              <ReminderEmailCard key={item.id} item={item} slug={slug!} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
