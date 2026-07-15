// ui/src/components/tabs/AveryOutputExtra.tsx
// Avery's Output tab extra: interview sessions panel with transcript links
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Check, XCircle, ExternalLink } from 'lucide-react'
import type { InterviewSessionsResponse, InterviewSessionStatus } from '../../types'

const STATUS_CLASSES: Record<InterviewSessionStatus['status'], string> = {
  pending:   'bg-gray-100 text-gray-600',
  active:    'bg-amber-100 text-amber-700',
  completed: 'bg-teal-100 text-teal-700',
  abandoned: 'bg-gray-100 text-gray-400',
}

export default function AveryOutputExtra({ slug }: { slug: string }) {
  const qc = useQueryClient()
  const [copiedToken, setCopiedToken] = useState<string | null>(null)

  const { data, isLoading } = useQuery<InterviewSessionsResponse>({
    queryKey: ['interview-sessions', slug],
    queryFn: () => fetch(`/api/interviews/sessions/${slug}`).then(r => r.json()),
    refetchInterval: 15_000,
  })

  async function abandon(token: string) {
    await fetch(`/api/interviews/${token}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'abandoned' }),
    })
    qc.invalidateQueries({ queryKey: ['interview-sessions', slug] })
  }

  function copyUrl(session: InterviewSessionStatus) {
    navigator.clipboard.writeText(session.interview_url).catch(() => {})
    setCopiedToken(session.session_token)
    setTimeout(() => setCopiedToken(null), 1500)
  }

  if (isLoading) return <p className="text-xs text-gray-400 py-3 animate-pulse">Loading sessions…</p>

  const sessions = data?.sessions ?? []
  const summary = data?.summary

  if (sessions.length === 0) {
    return (
      <div className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-6 text-center">
        <p className="text-xs text-gray-400">No interview sessions yet — run the stakeholder management crew first to generate invite links.</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Interview Sessions</p>

      {summary && (
        <div className="flex gap-2 flex-wrap">
          {(['pending', 'active', 'completed', 'abandoned'] as const).map(s => (
            <span key={s} className={`text-[10px] px-2 py-0.5 rounded-full font-medium capitalize ${STATUS_CLASSES[s]}`}>
              {s}: {summary[s]}
            </span>
          ))}
        </div>
      )}

      <div className="space-y-1.5 max-h-60 overflow-y-auto">
        {sessions.map(s => (
          <div key={s.id} className="rounded-lg border border-gray-100 bg-white px-3 py-2.5 flex items-center gap-3">
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-gray-800 truncate">{s.name}</p>
              <p className="text-[10px] text-gray-400 truncate">{s.node_label}</p>
            </div>
            <span className={`text-[10px] px-2 py-0.5 rounded-full capitalize flex-shrink-0 ${STATUS_CLASSES[s.status]}`}>
              {s.status}
            </span>
            {s.status === 'completed' && s.interview_url && (
              <a
                href={s.interview_url}
                target="_blank"
                rel="noreferrer"
                title="View transcript"
                className="flex-shrink-0 text-brand hover:text-brand-dark"
              >
                <ExternalLink size={12} />
              </a>
            )}
            {s.status !== 'completed' && s.interview_url && (
              <button
                onClick={() => copyUrl(s)}
                title="Copy interview link"
                className="flex-shrink-0 text-gray-400 hover:text-brand"
              >
                {copiedToken === s.session_token ? <Check size={12} className="text-teal-500" /> : <Copy size={12} />}
              </button>
            )}
            {s.status === 'active' && (
              <button
                onClick={() => abandon(s.session_token)}
                title="Abandon session"
                className="flex-shrink-0 text-gray-300 hover:text-red-500"
              >
                <XCircle size={12} />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
