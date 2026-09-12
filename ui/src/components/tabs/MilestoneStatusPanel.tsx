// ui/src/components/tabs/MilestoneStatusPanel.tsx
//
// What the engagement is doing against its schedule: how many milestones are complete, overdue
// and due soon, what is next, and how far through the interview programme it is.
//
// It was the top and the middle of `PamSetupTab`, which read as PAM's own configuration
// because of the filename. Apply the rename test - if PAM were renamed or replaced, would this
// move with her? - and the answer is plainly no: an overdue count belongs to the project.
//
// **It shares `['milestones', slug]` with `ProjectScheduleSetup` rather than fetching its
// own.** The schedule editor on Setup and these statistics on Status are two views of one set
// of rows; a second query key would be a second request and, worse, two answers that can
// disagree while one of them is stale - the reader would see four complete on one tab and
// three on the other with nothing to say which was right.
import { useQuery } from '@tanstack/react-query'
import { Clock } from 'lucide-react'

import { milestonesApi } from '../../api/endpoints'
import type { Milestone } from '../../types'
import { countdownLabel, daysBetween, milestoneState, todayStr } from './scheduleDates'

// ── Interview completion tracker ──────────────────────────────────────────────
//
// It used to be folded behind a "View completion tracker" toggle on one milestone row, which
// put a project-wide progress bar inside a control for editing a single date. Nothing about it
// is an edit, so it reads here beside the counts it belongs with.

interface SessionRow { session_token: string; stakeholder_name: string; status: string }

function InterviewCompletionPanel({ slug }: { slug: string }) {
  const { data: sessions = [] } = useQuery({
    queryKey: ['interview-sessions', slug],
    queryFn: () =>
      fetch(`/api/interviews/sessions/${slug}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
      }).then(r => r.ok ? r.json() as Promise<SessionRow[]> : Promise.resolve([])),
    refetchInterval: 60_000,
  })
  if (!sessions.length) return null
  const complete    = sessions.filter(s => s.status === 'completed')
  const outstanding = sessions.filter(s => s.status !== 'completed')
  return (
    <div className="mt-3 rounded-lg border border-gray-100 bg-gray-50 p-3" data-testid="interview-completion">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-semibold text-gray-600">Interview completion</p>
        <span className="text-xs text-gray-500">{complete.length} / {sessions.length} complete</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-1.5 mb-3">
        <div className="h-1.5 rounded-full bg-teal-500 transition-all"
          style={{ width: `${Math.round((complete.length / sessions.length) * 100)}%` }} />
      </div>
      {outstanding.length > 0 && (
        <ul className="space-y-1">
          {outstanding.map(s => (
            <li key={s.session_token} className="flex items-center justify-between text-xs">
              <span className="text-gray-700">{s.stakeholder_name}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                s.status === 'active'
                  ? 'bg-brand/10 text-brand border-brand/20'
                  : 'bg-gray-100 text-gray-500 border-gray-200'
              }`}>{s.status === 'active' ? 'In progress' : 'Not started'}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── Summary stats ─────────────────────────────────────────────────────────────

export function ScheduleSummary({ milestones }: { milestones: Milestone[] }) {
  const overdue  = milestones.filter(m => milestoneState(m) === 'overdue')
  const dueSoon  = milestones.filter(m => milestoneState(m) === 'due_soon')
  const complete = milestones.filter(m => m.status === 'complete')
  const next     = milestones
    .filter(m => m.status === 'pending' && m.due_date && daysBetween(todayStr(), m.due_date) >= 0)
    .sort((a, b) => (a.due_date ?? '').localeCompare(b.due_date ?? ''))[0]

  return (
    <div className="grid grid-cols-4 gap-3" data-testid="milestone-statistics">
      {[
        { label: 'Complete', value: complete.length, color: 'text-teal-600', bg: 'bg-teal-50 border-teal-100' },
        { label: 'Overdue',  value: overdue.length,  color: overdue.length  ? 'text-red-600'   : 'text-gray-400', bg: overdue.length  ? 'bg-red-50 border-red-100'     : 'bg-gray-50 border-gray-100' },
        { label: 'Due soon', value: dueSoon.length,  color: dueSoon.length  ? 'text-amber-600' : 'text-gray-400', bg: dueSoon.length  ? 'bg-amber-50 border-amber-100' : 'bg-gray-50 border-gray-100' },
        { label: 'Total',    value: milestones.length, color: 'text-gray-600', bg: 'bg-gray-50 border-gray-100' },
      ].map(({ label, value, color, bg }) => (
        <div key={label} className={`rounded-xl border p-3 ${bg}`}>
          <p className={`text-xl font-bold ${color}`}>{value}</p>
          <p className="text-xs text-gray-500 mt-0.5">{label}</p>
        </div>
      ))}
      {next && (
        <div className="col-span-4 rounded-xl border border-gray-100 bg-gray-50 p-3 flex items-center gap-2">
          <Clock size={14} className="text-gray-400 flex-shrink-0" />
          <p className="text-xs text-gray-600">
            <span className="font-semibold">Next: </span>{next.title}
            {next.due_date && <span className="text-gray-400 ml-1">— {countdownLabel(next)}</span>}
          </p>
        </div>
      )}
    </div>
  )
}

// ── The Status section ────────────────────────────────────────────────────────

export default function MilestoneStatusPanel({ slug }: { slug: string }) {
  // Same key, same queryFn and same `enabled` as ProjectScheduleSetup's own query. Two
  // observers of one cache entry, not two fetches - the request count is asserted in
  // TabClassification.test.tsx, because a duplicated fetch looks identical on screen.
  const { data: milestones = [], isLoading } = useQuery({
    queryKey: ['milestones', slug],
    queryFn:  () => milestonesApi.list(slug),
    enabled:  !!slug,
  })

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
        Milestone status
      </p>
      {isLoading ? (
        <p className="text-sm text-gray-400">Loading schedule…</p>
      ) : milestones.length === 0 ? (
        <p className="text-xs text-gray-400">
          No milestones yet - the schedule is set up on the Setup tab.
        </p>
      ) : (
        <ScheduleSummary milestones={milestones} />
      )}
      <InterviewCompletionPanel slug={slug} />
    </div>
  )
}
