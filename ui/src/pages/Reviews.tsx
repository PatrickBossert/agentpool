// ui/src/pages/Reviews.tsx
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { campaignsApi } from '../api/campaigns'
import type { HumanReview, ReminderEmail } from '../types'

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
        <p className="text-xs text-slate-500 mt-1.5">Run #{review.crew_run_id}</p>
      </div>
      <div className="px-4 pb-3">
        <p className="text-sm text-slate-200 leading-relaxed bg-[#0f172a] rounded-md px-3 py-2.5 border border-slate-800 whitespace-pre-wrap">
          {review.prompt}
        </p>
      </div>
      <div className="px-4 pb-4 flex flex-col gap-2.5">
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Notes for the crew (optional) — your text is returned verbatim as the crew's input"
          className="w-full bg-[#0f172a] border border-slate-700 rounded-md text-slate-300 text-sm px-3 py-2 resize-y min-h-[72px] placeholder:text-slate-600 focus:outline-none focus:border-slate-500"
        />
        <div className="flex gap-2 justify-end">
          <button
            disabled={submitting}
            onClick={() => resolve('changes_requested')}
            className="text-xs px-4 py-1.5 rounded-md bg-red-900/60 text-red-300 hover:bg-red-900 disabled:opacity-50 transition-colors"
          >
            Request Changes
          </button>
          <button
            disabled={submitting}
            onClick={() => resolve('approved')}
            className="text-xs px-4 py-1.5 rounded-md bg-emerald-900/60 text-emerald-300 hover:bg-emerald-900 disabled:opacity-50 transition-colors"
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
          Reminder — {item.escalation_level}
        </span>
      </div>
      <div className="px-4 pb-2 space-y-2">
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Subject</p>
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="w-full bg-[#0f172a] border border-slate-800 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-slate-600"
          />
        </div>
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Body</p>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={6}
            className="w-full bg-[#0f172a] border border-slate-700 rounded-md text-slate-300 text-sm px-3 py-2 resize-y placeholder:text-slate-600 focus:outline-none focus:border-slate-500"
          />
        </div>
      </div>
      <div className="px-4 pb-4 flex gap-2 justify-end">
        <button
          disabled={submitting}
          onClick={() => resolve('dismissed')}
          className="text-xs px-4 py-1.5 rounded-md bg-slate-800 text-slate-400 hover:bg-slate-700 disabled:opacity-50 transition-colors"
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

export default function Reviews() {
  const { slug } = useParams<{ slug: string }>()

  const { data: reviews = [], isLoading } = useQuery({
    queryKey: ['reviews', slug],
    queryFn: () => projectsApi.listReviews(slug!),
    enabled: !!slug,
    refetchInterval: 5000,
  })

  const { data: reminderEmails = [] } = useQuery({
    queryKey: ['reminder-emails', slug],
    queryFn: () => campaignsApi.listReminderEmails(slug!),
    enabled: !!slug,
    refetchInterval: 10_000,
  })

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Reviews</h2>
      {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
      {!isLoading && reviews.length === 0 && (
        <p className="text-sm text-slate-500">
          No pending reviews — the crew is running autonomously.
        </p>
      )}
      <div className="space-y-4">
        {reviews.map((r) => (
          <ReviewCard key={r.id} review={r} slug={slug!} />
        ))}
      </div>
      {reminderEmails.length > 0 && (
        <>
          <h3 className="text-sm font-semibold text-slate-300 mt-6 mb-3">Reminder Emails</h3>
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
