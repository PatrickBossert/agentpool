// ui/src/pages/ValueChain.tsx
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import mermaid from 'mermaid'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'
import type { ProjectSettings, DiscoveryLink, ClientDocument } from '../types'

mermaid.initialize({ startOnLoad: false, theme: 'dark' })

export default function ValueChain() {
  const { slug } = useParams<{ slug: string }>()
  const { token } = useAuth()
  const qc = useQueryClient()

  // ── Setup tab state ──────────────────────────────────────────
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

  // ── Diagram tab state ────────────────────────────────────────
  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['value-chain', slug],
    queryFn: () => projectsApi.valueChain(slug!),
    enabled: !!slug,
  })

  const latest = outputs[0] ?? null

  const { data: contentData, isLoading: contentLoading, isError: contentError } = useQuery({
    queryKey: ['outputContent', slug, latest?.id],
    queryFn: () => projectsApi.getOutputContent(slug!, latest!.id),
    enabled: !!slug && !!latest,
  })

  const svgContainerRef = useRef<HTMLDivElement>(null)
  const mountKey = useRef(Math.random().toString(36).slice(2))
  const [renderError, setRenderError] = useState(false)

  useEffect(() => {
    if (!contentData?.content || !svgContainerRef.current) return
    let cancelled = false
    const container = svgContainerRef.current
    setRenderError(false)
    ;(async () => {
      try {
        const renderId = 'vc-' + mountKey.current + '-' + (latest?.id ?? 0)
        const { svg } = await mermaid.render(renderId, contentData.content)
        if (cancelled) return
        const parser = new DOMParser()
        const svgDoc = parser.parseFromString(svg, 'image/svg+xml')
        const svgEl = svgDoc.documentElement
        container.replaceChildren(svgEl)
      } catch {
        if (!cancelled) setRenderError(true)
        if (!cancelled) container.replaceChildren()
      }
    })()
    return () => {
      cancelled = true
    }
  }, [contentData?.content, latest?.id])

  // ── Tab ──────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<'setup' | 'diagram'>('setup')

  // Switch to Diagram tab automatically once outputs are known to exist
  useEffect(() => {
    if (!isLoading && outputs.length > 0) setActiveTab('diagram')
  }, [isLoading, outputs.length])

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold text-slate-100 mb-4">Value Chain</h2>

      {/* Tab strip */}
      <div className="flex border-b border-slate-700 mb-6">
        {(['setup', 'diagram'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm capitalize border-b-2 transition-colors ${
              activeTab === tab
                ? 'text-brand border-brand'
                : 'text-slate-400 border-transparent hover:text-slate-200'
            }`}
          >
            {tab === 'setup' ? 'Setup' : 'Diagram'}
          </button>
        ))}
      </div>

      {/* ── Setup tab ─────────────────────────────────────────── */}
      {activeTab === 'setup' && (
        <div className="max-w-3xl">
          <p className="text-slate-400 text-sm mb-8">
            Configure what the Value Chain Mapper uses before it starts. Changes take effect on the next crew run.
          </p>

          {/* Research Brief */}
          <section className="mb-8">
            <h3 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Research Brief</h3>
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

          {/* Research Links */}
          <section className="mb-8">
            <h3 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Research Links</h3>
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

          {/* Source Documents */}
          <section className="mb-8">
            <h3 className="text-sm font-medium text-slate-300 uppercase tracking-wide mb-2">Source Documents</h3>
            <p className="text-slate-500 text-xs mb-3">
              Select documents to prioritise. The crew will focus ChromaDB queries on these files.
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
      )}

      {/* ── Diagram tab ───────────────────────────────────────── */}
      {activeTab === 'diagram' && (
        <>
          {isLoading && <p className="text-sm text-slate-500">Loading…</p>}

          {!isLoading && outputs.length === 0 && (
            <div className="bg-surface-card rounded-xl p-8 text-center">
              <p className="text-slate-400 text-sm">Awaiting Value Chain Mapper output.</p>
              <p className="text-slate-600 text-xs mt-2">
                Run the Discovery crew to generate the value chain analysis.
              </p>
            </div>
          )}

          {latest && (
            <div className="bg-surface-card rounded-xl p-4">
              <div className="flex justify-between items-center mb-4">
                <span className="text-sm text-slate-200">{latest.agent_name}</span>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-500">
                    v{latest.version} · {latest.review_status}
                  </span>
                  <button
                    onClick={() =>
                      downloadOutput(
                        slug!,
                        latest.id,
                        latest.file_path.split('/').pop() ?? latest.output_type,
                        token!,
                      ).catch(console.error)
                    }
                    className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
                  >
                    ↓ Download
                  </button>
                </div>
              </div>
              {contentLoading && <p className="text-sm text-slate-500">Rendering diagram…</p>}
              {contentError && !contentLoading && (
                <p className="text-sm text-red-400">Failed to load diagram.</p>
              )}
              {renderError && <p className="text-sm text-red-400">Invalid diagram source.</p>}
              {/* SVG inserted here via DOMParser + replaceChildren */}
              <div ref={svgContainerRef} className="overflow-auto" />
            </div>
          )}
        </>
      )}
    </div>
  )
}
