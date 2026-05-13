// ui/src/pages/Discovery.tsx
import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { campaignsApi } from '../api/campaigns'
import type { Campaign, ProjectSettings, InterviewSessionsResponse, InterviewSessionStatus } from '../types'

// ── InterviewSessionsPanel ────────────────────────────────────────────────────

const STATUS_CLASSES: Record<InterviewSessionStatus['status'], string> = {
  pending:   'bg-gray-100 text-gray-700',
  active:    'bg-amber-100 text-amber-700',
  completed: 'bg-teal-100 text-teal-700',
  abandoned: 'bg-slate-100 text-slate-500',
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
    await fetch(`/api/interviews/${token}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'abandoned' }),
    })
    queryClient.invalidateQueries({ queryKey: ['interview-sessions', slug] })
  }

  function copyUrl(session: InterviewSessionStatus) {
    navigator.clipboard.writeText(session.interview_url)
    setCopiedToken(session.session_token)
    setTimeout(() => setCopiedToken(null), 1500)
  }

  if (isLoading) return <p className="text-sm text-slate-400 py-4">Loading sessions…</p>

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
          <table className="w-full text-xs text-slate-300">
            <thead>
              <tr className="border-b border-slate-700 text-left text-slate-500 uppercase tracking-wider">
                {['Name', 'Node', 'Status', 'Interview URL', 'Started', 'Completed', 'Actions'].map(h => (
                  <th key={h} className="pb-2 pr-4 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {sessions.map(s => (
                <tr key={s.id} className="py-2">
                  <td className="py-2 pr-4">{s.name}</td>
                  <td className="py-2 pr-4 text-slate-400">{s.node_label}</td>
                  <td className="py-2 pr-4">
                    <span className={`px-2 py-0.5 rounded-full capitalize ${STATUS_CLASSES[s.status]}`}>
                      {s.status}
                    </span>
                  </td>
                  <td className="py-2 pr-4">
                    <button
                      onClick={() => copyUrl(s)}
                      className="text-xs px-2 py-0.5 bg-slate-800 hover:bg-slate-700 border border-slate-600 rounded"
                    >
                      {copiedToken === s.session_token ? 'Copied!' : 'Copy'}
                    </button>
                  </td>
                  <td className="py-2 pr-4 text-slate-500">{s.started_at ? new Date(s.started_at).toLocaleString() : '—'}</td>
                  <td className="py-2 pr-4 text-slate-500">{s.completed_at ? new Date(s.completed_at).toLocaleString() : '—'}</td>
                  <td className="py-2">
                    {(s.status === 'pending' || s.status === 'active') && (
                      <button
                        onClick={() => abandon(s.session_token)}
                        className="text-xs px-2 py-0.5 text-red-400 hover:text-red-300 border border-red-800 hover:border-red-600 rounded"
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

  const { data: campaigns = [], refetch: refetchCampaigns } = useQuery<Campaign[]>({
    queryKey: ['campaigns', slug],
    queryFn: () => campaignsApi.list(slug!),
    enabled: !!slug,
  })

  const [campaignMsg, setCampaignMsg] = useState<Record<number, string>>({})
  const progressInputRef = useRef<Record<number, HTMLInputElement | null>>({})
  const resultsInputRef = useRef<Record<number, HTMLInputElement | null>>({})
  const summaryInputRef = useRef<Record<number, HTMLInputElement | null>>({})

  async function createCampaign() {
    await campaignsApi.create(slug!, { value_stream_name: '', campaign_name: 'New Campaign' })
    refetchCampaigns()
  }

  async function updateCampaignField(id: number, data: Partial<Campaign>) {
    await campaignsApi.update(slug!, id, data)
    refetchCampaigns()
  }

  async function deleteCampaign(id: number) {
    await campaignsApi.delete(slug!, id)
    refetchCampaigns()
  }

  async function markInvited(id: number) {
    const r = await campaignsApi.markInvited(slug!, id)
    setCampaignMsg((prev) => ({ ...prev, [id]: `${r.marked} stakeholders marked as invited.` }))
    setTimeout(() => setCampaignMsg((prev) => ({ ...prev, [id]: '' })), 4000)
  }

  async function generateReminders(id: number) {
    const r = await campaignsApi.generateReminders(slug!, id)
    setCampaignMsg((prev) => ({ ...prev, [id]: `${r.created} reminder email(s) added to review queue.` }))
    setTimeout(() => setCampaignMsg((prev) => ({ ...prev, [id]: '' })), 4000)
  }

  async function handleFileImport(
    id: number,
    kind: 'progress' | 'results' | 'summary',
    file: File,
  ) {
    let msg = ''
    if (kind === 'progress') {
      const r = await campaignsApi.importProgress(slug!, id, file)
      msg = `Progress imported: ${r.updated} updated, ${r.skipped} skipped.`
    } else if (kind === 'results') {
      const r = await campaignsApi.importResults(slug!, id, file)
      msg = `Results imported: ${r.imported} imported, ${r.unmatched} unmatched.`
    } else {
      await campaignsApi.importSummary(slug!, id, file)
      msg = 'Findings summary imported.'
      refetchCampaigns()
    }
    setCampaignMsg((prev) => ({ ...prev, [id]: msg }))
    setTimeout(() => setCampaignMsg((prev) => ({ ...prev, [id]: '' })), 5000)
  }

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-100 mb-4">Discovery</h1>

      {/* Tab strip */}
      <div className="flex border-b border-slate-700 mb-6">
        {([['interviews', 'Interviews'], ['layer-map', 'Layer Map']] as const).map(([tab, label]) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${
              activeTab === tab
                ? 'text-brand border-brand'
                : 'text-slate-400 border-transparent hover:text-slate-200'
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
          <>
          <p className="text-slate-400 text-sm mb-6">
            Link a ListenLabs campaign to each value stream. Export interview targets, import
            results, and generate reminders.
          </p>

          {campaigns.length === 0 && (
            <p className="text-slate-500 text-sm italic mb-3">No campaigns linked yet.</p>
          )}

          <div className="space-y-4">
            {campaigns.map((camp) => (
              <div key={camp.id} className="border border-slate-700 rounded-lg p-4 space-y-3">
                {/* Campaign header row */}
                <div className="flex items-start gap-3">
                  <div className="flex-1 grid grid-cols-2 gap-2">
                    <input
                      defaultValue={camp.campaign_name}
                      onBlur={(e) => updateCampaignField(camp.id, { campaign_name: e.target.value })}
                      placeholder="Campaign name"
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
                    />
                    <input
                      defaultValue={camp.listenlabs_campaign_id}
                      onBlur={(e) =>
                        updateCampaignField(camp.id, { listenlabs_campaign_id: e.target.value })
                      }
                      placeholder="ListenLabs campaign ID"
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 font-mono outline-none focus:border-brand"
                    />
                    <input
                      defaultValue={camp.value_stream_name}
                      onBlur={(e) =>
                        updateCampaignField(camp.id, { value_stream_name: e.target.value })
                      }
                      placeholder="Value stream name (must match discovery output)"
                      className="col-span-2 bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
                    />
                    <input
                      type="date"
                      defaultValue={camp.interview_start ?? ''}
                      onBlur={(e) =>
                        updateCampaignField(camp.id, { interview_start: e.target.value || null })
                      }
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
                    />
                    <input
                      type="date"
                      defaultValue={camp.interview_close ?? ''}
                      onBlur={(e) =>
                        updateCampaignField(camp.id, { interview_close: e.target.value || null })
                      }
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
                    />
                  </div>
                  <button
                    onClick={() => deleteCampaign(camp.id)}
                    className="text-slate-500 hover:text-red-400 text-xs px-2 py-1 flex-shrink-0"
                  >
                    Remove
                  </button>
                </div>

                {/* Action buttons */}
                <div className="flex flex-wrap gap-2">
                  <a
                    href={campaignsApi.exportTargets(slug!, camp.id)}
                    download
                    className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-600"
                  >
                    Download Targets
                  </a>
                  <button
                    onClick={() => markInvited(camp.id)}
                    className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-600"
                  >
                    Mark as Invited
                  </button>

                  {/* Hidden file inputs */}
                  <input
                    type="file"
                    accept=".csv"
                    className="hidden"
                    ref={(el) => { progressInputRef.current[camp.id] = el }}
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) handleFileImport(camp.id, 'progress', f)
                      e.target.value = ''
                    }}
                  />
                  <input
                    type="file"
                    accept=".csv,.json"
                    className="hidden"
                    ref={(el) => { resultsInputRef.current[camp.id] = el }}
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) handleFileImport(camp.id, 'results', f)
                      e.target.value = ''
                    }}
                  />
                  <input
                    type="file"
                    accept=".txt,.json"
                    className="hidden"
                    ref={(el) => { summaryInputRef.current[camp.id] = el }}
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) handleFileImport(camp.id, 'summary', f)
                      e.target.value = ''
                    }}
                  />

                  <button
                    onClick={() => progressInputRef.current[camp.id]?.click()}
                    className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-600"
                  >
                    Import Progress
                  </button>
                  <button
                    onClick={() => resultsInputRef.current[camp.id]?.click()}
                    className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-600"
                  >
                    Import Results
                  </button>
                  <button
                    onClick={() => summaryInputRef.current[camp.id]?.click()}
                    className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-600"
                  >
                    Import Summary
                  </button>
                  <button
                    onClick={() => generateReminders(camp.id)}
                    className="text-xs px-3 py-1.5 bg-brand/10 hover:bg-brand/20 text-brand rounded border border-brand/30"
                  >
                    Generate Reminders
                  </button>
                </div>

                {campaignMsg[camp.id] && (
                  <p className="text-xs text-emerald-400">{campaignMsg[camp.id]}</p>
                )}

                {camp.findings_summary && (
                  <div>
                    <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">
                      Findings Summary
                    </p>
                    <pre className="text-xs text-slate-300 bg-slate-900 border border-slate-700 rounded p-3 whitespace-pre-wrap max-h-40 overflow-y-auto">
                      {camp.findings_summary}
                    </pre>
                  </div>
                )}
              </div>
            ))}
          </div>

          <button
            onClick={createCampaign}
            className="mt-3 text-xs text-slate-400 hover:text-slate-200 border border-slate-700 hover:border-slate-500 rounded px-3 py-1.5"
          >
            + Link Campaign
          </button>
          </>
          )}
        </div>
      )}

      {/* ── Layer Map tab (stub) ──────────────────────────────── */}
      {activeTab === 'layer-map' && (
        <div className="max-w-3xl">
          <div className="border border-slate-700 rounded-lg p-8 text-center">
            <p className="text-sm font-semibold text-slate-300 mb-2">Stakeholder Layer Assignment</p>
            <p className="text-xs text-slate-500 leading-relaxed max-w-md mx-auto">
              Stakeholders will be mapped to model layers here —
              investor → organisation → value stream → value chain → activity → customer.
              Interview findings will be displayed against each layer.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
