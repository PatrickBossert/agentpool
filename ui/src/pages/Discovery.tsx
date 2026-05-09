// ui/src/pages/Discovery.tsx
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import type { ProjectSettings, DiscoveryLink, ClientDocument } from '../types'

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
