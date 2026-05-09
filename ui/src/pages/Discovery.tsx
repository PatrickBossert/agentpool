// ui/src/pages/Discovery.tsx
import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { campaignsApi } from '../api/campaigns'
import type { Campaign } from '../types'

export default function Discovery() {
  const { slug } = useParams<{ slug: string }>()
  const [activeTab, setActiveTab] = useState<'interviews' | 'layer-map'>('interviews')

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
