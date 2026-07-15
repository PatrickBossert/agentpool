// ui/src/pages/Discovery.tsx
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ProjectSettings, InterviewSessionsResponse, InterviewSessionStatus } from '../types'

// ── InterviewSessionsPanel ────────────────────────────────────────────────────

const STATUS_CLASSES: Record<InterviewSessionStatus['status'], string> = {
  pending:   'bg-gray-100 text-gray-700',
  active:    'bg-amber-100 text-amber-700',
  completed: 'bg-teal-100 text-teal-700',
  abandoned: 'bg-gray-100 text-gray-400',
}

function InterviewSessionsPanel({ slug }: { slug: string }) {
  const queryClient = useQueryClient()
  const [copiedToken, setCopiedToken] = useState<string | null>(null)

  const { data, isLoading } = useQuery<InterviewSessionsResponse>({
    queryKey: ['interview-sessions', slug],
    queryFn: () => fetch(`/api/interviews/sessions/${slug}`).then(r => r.json()),
    enabled: !!slug,
  })

  async function abandon(token: string) {
    const res = await fetch(`/api/interviews/${token}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'abandoned' }),
    })
    if (!res.ok) return
    queryClient.invalidateQueries({ queryKey: ['interview-sessions', slug] })
  }

  function copyUrl(session: InterviewSessionStatus) {
    navigator.clipboard.writeText(session.interview_url).catch(() => {})
    setCopiedToken(session.session_token)
    setTimeout(() => setCopiedToken(null), 1500)
  }

  if (isLoading) return <p className="text-sm text-gray-400 py-4">Loading sessions…</p>

  const sessions = data?.sessions ?? []
  const summary = data?.summary

  return (
    <div className="mt-4">
      {/* Summary badges */}
      {summary && (
        <div className="flex gap-3 mb-4">
          {(['pending', 'active', 'completed', 'abandoned'] as const).map(s => (
            <span key={s} className={`text-xs px-2.5 py-1 rounded-full font-medium capitalize ${STATUS_CLASSES[s]}`}>
              {s}: {summary[s]}
            </span>
          ))}
        </div>
      )}

      {sessions.length === 0 ? (
        <p className="text-sm text-gray-500 py-4">No interview sessions found for the latest pipeline run.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-gray-700">
            <thead>
              <tr className="border-b border-gray-200 text-left text-gray-500 uppercase tracking-wider">
                {['Name', 'Node', 'Status', 'Interview URL', 'Started', 'Completed', 'Actions'].map(h => (
                  <th key={h} className="pb-2 pr-4 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sessions.map(s => (
                <tr key={s.id} className="py-2">
                  <td className="py-2 pr-4">{s.name}</td>
                  <td className="py-2 pr-4 text-gray-500">{s.node_label}</td>
                  <td className="py-2 pr-4">
                    <span className={`px-2 py-0.5 rounded-full capitalize ${STATUS_CLASSES[s.status]}`}>
                      {s.status}
                    </span>
                  </td>
                  <td className="py-2 pr-4 max-w-[200px] truncate">
                    <button
                      onClick={() => copyUrl(s)}
                      className="text-brand hover:underline"
                      title={s.interview_url}
                    >
                      {copiedToken === s.session_token ? 'Copied!' : 'Copy URL'}
                    </button>
                  </td>
                  <td className="py-2 pr-4 text-gray-500">
                    {s.started_at ? new Date(s.started_at).toLocaleDateString() : '-'}
                  </td>
                  <td className="py-2 pr-4 text-gray-500">
                    {s.completed_at ? new Date(s.completed_at).toLocaleDateString() : '-'}
                  </td>
                  <td className="py-2">
                    {s.status !== 'completed' && s.status !== 'abandoned' && (
                      <button
                        onClick={() => abandon(s.session_token)}
                        className="text-gray-400 hover:text-red-500 text-xs"
                      >
                        Abandon
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function Discovery() {
  const { slug } = useParams<{ slug: string }>()
  const [activeTab, setActiveTab] = useState<'interviews' | 'layer-map'>('interviews')

  const { data: settings } = useQuery<ProjectSettings>({
    queryKey: ['settings', slug],
    queryFn: () => fetch(`/api/projects/${slug}/settings`).then(r => r.json()),
    enabled: !!slug,
  })

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-gray-900 mb-4">Discovery</h1>

      {/* Tab strip */}
      <div className="flex border-b border-gray-200 mb-6">
        {([['interviews', 'Interviews'], ['layer-map', 'Layer Map']] as const).map(([tab, label]) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${
              activeTab === tab
                ? 'text-brand border-brand'
                : 'text-gray-400 border-transparent hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Interviews tab ────────────────────────────────────── */}
      {activeTab === 'interviews' && (
        <div className="max-w-3xl">
          {settings?.interview_method === 'agent' ? (
            <InterviewSessionsPanel slug={slug!} />
          ) : (
            <div className="border border-gray-200 rounded-lg p-8 text-center">
              <p className="text-sm font-semibold text-gray-700 mb-2">Interview phase not enabled</p>
              <p className="text-xs text-gray-400 leading-relaxed">
                Set <strong>Interview Method</strong> to <em>Agent interviews</em> in{' '}
                <a href={`/dashboard/${slug}/settings`} className="text-brand hover:underline">
                  Settings
                </a>{' '}
                to activate voice interviews for this project.
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── Layer Map tab ──────────────────────────────────────── */}
      {activeTab === 'layer-map' && (
        <div className="max-w-3xl">
          <div className="border border-gray-200 rounded-lg p-8 text-center">
            <p className="text-sm font-semibold text-gray-700 mb-2">Stakeholder Layer Assignment</p>
            <p className="text-xs text-gray-400 leading-relaxed max-w-md mx-auto">
              Stakeholders will be mapped to model layers here -
              investor → organisation → value stream → value chain → activity → customer.
              Interview findings will be displayed against each layer.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
