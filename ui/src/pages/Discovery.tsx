// ui/src/pages/Discovery.tsx
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { campaignsApi } from '../api/campaigns'
import type { ProjectSettings, DiscoveryLink, ClientDocument, Campaign } from '../types'

export default function Discovery() {
  const { slug } = useParams<{ slug: string }>()
  const qc = useQueryClient()

  const [brief, setBrief] = useState('')
  const [links, setLinks] = useState<DiscoveryLink[]>([])
  const [selectedDocIds, setSelectedDocIds] = useState<number[]>([])
  const [newUrl, setNewUrl] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  const { data: documents = [] } = useQuery<ClientDocument[]>({
    queryKey: ['documents', slug],
    queryFn: () => projectsApi.documents(slug!),
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

  useEffect(() => {
    if (settings) {
      setBrief(settings.discovery_brief ?? '')
      setLinks(settings.discovery_links ?? [])
      setSelectedDocIds(settings.discovery_document_ids ?? [])
    }
  }, [settings])

  const mutation = useMutation({
    mutationFn: (updated: ProjectSettings) => projectsApi.updateSettings(slug!, updated),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', slug] })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
    onError: (e: Error) => setError(e.message),
  })

  function handleSave() {
    if (!settings) return
    setError(null)
    mutation.mutate({
      ...settings,
      discovery_brief: brief,
      discovery_links: links,
      discovery_document_ids: selectedDocIds,
    })
  }

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
    file: File
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

  function addLink() {
    const trimmedUrl = newUrl.trim()
    if (!trimmedUrl) return
    setLinks((prev) => [...prev, { url: trimmedUrl, label: newLabel.trim() }])
    setNewUrl('')
    setNewLabel('')
  }

  function removeLink(index: number) {
    setLinks((prev) => prev.filter((_, i) => i !== index))
  }

  function toggleDoc(id: number) {
    setSelectedDocIds((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id],
    )
  }

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-xl font-semibold text-slate-100 mb-1">Discovery Inputs</h1>
      <p className="text-slate-400 text-sm mb-8">
        Configure what the Value Chain Mapper uses before it starts. Changes take effect on the next crew run.
      </p>

      {/* Section 1: Research Brief */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Research Brief</h2>
        <p className="text-slate-500 text-xs mb-3">
          Any context the crew should know before it starts — strategic priorities, scope constraints, what the client has flagged.
        </p>
        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          rows={5}
          placeholder="e.g. The client operates primarily in passenger rail in the UK. Focus on operational efficiency and safety compliance themes."
          className="w-full bg-slate-900 border border-slate-700 rounded p-3 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-brand resize-y"
        />
      </section>

      {/* Section 2: Research Links */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Research Links</h2>
        <p className="text-slate-500 text-xs mb-3">
          URLs the crew will fetch and read before analysis. Add industry bodies, regulatory sites, company pages, or reports.
        </p>

        {links.length > 0 && (
          <ul className="mb-3 space-y-1">
            {links.map((link, i) => (
              <li key={i} className="flex items-center gap-2 bg-slate-900 border border-slate-700 rounded px-3 py-2">
                <span className="text-brand text-xs font-mono flex-1 truncate">{link.url}</span>
                {link.label && <span className="text-slate-400 text-xs">{link.label}</span>}
                <button
                  type="button"
                  onClick={() => removeLink(i)}
                  className="text-slate-500 hover:text-red-400 text-xs ml-2"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex gap-2">
          <input
            value={newUrl}
            onChange={(e) => setNewUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addLink()}
            placeholder="https://..."
            className="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-brand"
          />
          <input
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addLink()}
            placeholder="Label (optional)"
            className="w-40 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-brand"
          />
          <button
            type="button"
            onClick={addLink}
            disabled={!newUrl.trim()}
            className="px-4 py-2 bg-brand hover:bg-brand-dark disabled:opacity-40 text-white text-sm rounded"
          >
            Add
          </button>
        </div>
      </section>

      {/* Section 3: Source Documents */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Source Documents</h2>
        <p className="text-slate-500 text-xs mb-3">
          Select documents to prioritise. The crew will focus ChromaDB queries on these files. If nothing is selected, all uploaded documents are weighted equally.
        </p>

        {documents.length === 0 ? (
          <p className="text-slate-500 text-sm italic">No documents uploaded yet. Upload documents on the Documents page.</p>
        ) : (
          <ul className="space-y-1">
            {documents.map((doc) => (
              <li key={doc.id} className="flex items-center gap-3">
                <input
                  type="checkbox"
                  id={`doc-${doc.id}`}
                  checked={selectedDocIds.includes(doc.id)}
                  onChange={() => toggleDoc(doc.id)}
                  className="accent-brand"
                />
                <label htmlFor={`doc-${doc.id}`} className="text-sm text-slate-300 cursor-pointer">
                  {doc.original_name}
                  <span className="text-slate-500 text-xs ml-2">
                    ({(doc.size_bytes / 1024).toFixed(0)} KB)
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Section 4: Interviews */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Interviews</h2>
        <p className="text-slate-500 text-xs mb-4">
          Link a ListenLabs campaign to each value stream. Export interview targets, import results, and generate reminders.
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
                    onBlur={(e) => updateCampaignField(camp.id, { listenlabs_campaign_id: e.target.value })}
                    placeholder="ListenLabs campaign ID"
                    className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 font-mono outline-none focus:border-brand"
                  />
                  <input
                    defaultValue={camp.value_stream_name}
                    onBlur={(e) => updateCampaignField(camp.id, { value_stream_name: e.target.value })}
                    placeholder="Value stream name (must match discovery output)"
                    className="col-span-2 bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
                  />
                  <input
                    type="date"
                    defaultValue={camp.interview_start ?? ''}
                    onBlur={(e) => updateCampaignField(camp.id, { interview_start: e.target.value || null })}
                    className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-brand"
                  />
                  <input
                    type="date"
                    defaultValue={camp.interview_close ?? ''}
                    onBlur={(e) => updateCampaignField(camp.id, { interview_close: e.target.value || null })}
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
                <input type="file" accept=".csv" className="hidden"
                  ref={(el) => { progressInputRef.current[camp.id] = el }}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileImport(camp.id, 'progress', f); e.target.value = '' }}
                />
                <input type="file" accept=".csv,.json" className="hidden"
                  ref={(el) => { resultsInputRef.current[camp.id] = el }}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileImport(camp.id, 'results', f); e.target.value = '' }}
                />
                <input type="file" accept=".txt,.json" className="hidden"
                  ref={(el) => { summaryInputRef.current[camp.id] = el }}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileImport(camp.id, 'summary', f); e.target.value = '' }}
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
      </section>

      {/* Save */}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={handleSave}
          disabled={mutation.isPending}
          className="px-6 py-2 bg-brand hover:bg-brand-dark disabled:opacity-50 text-white text-sm font-medium rounded"
        >
          {mutation.isPending ? 'Saving…' : 'Save'}
        </button>
        {saved && <span className="text-emerald-400 text-sm">Saved.</span>}
      </div>
    </div>
  )
}
