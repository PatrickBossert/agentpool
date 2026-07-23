// ui/src/components/tabs/AlexSetupTab.tsx
// Alex's Setup tab: value chain discovery configuration (brief, links, docs, standards, questionnaire prefs)
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../../api/endpoints'
import type { ProjectSettings, DiscoveryLink, ClientDocument } from '../../types'

export default function AlexSetupTab({ slug }: { slug: string }) {
  const qc = useQueryClient()
  const [brief, setBrief] = useState('')
  const [links, setLinks] = useState<DiscoveryLink[]>([])
  const [selectedDocIds, setSelectedDocIds] = useState<number[]>([])
  const [newUrl, setNewUrl] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [standardsRefs, setStandardsRefs] = useState('')
  const [prefSections, setPrefSections] = useState(4)
  const [prefQuestionsPerSection, setPrefQuestionsPerSection] = useState(3)
  const [clientName, setClientName] = useState('')
  const [serviceCategories, setServiceCategories] = useState('')
  const [keyVendors, setKeyVendors] = useState('')
  const [applicableRegulations, setApplicableRegulations] = useState('')
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug),
  })

  const { data: documents = [] } = useQuery<ClientDocument[]>({
    queryKey: ['documents', slug],
    queryFn: () => projectsApi.documents(slug),
  })

  useEffect(() => {
    if (!settings) return
    setBrief(settings.discovery_brief ?? '')
    setLinks(settings.discovery_links ?? [])
    setSelectedDocIds(settings.discovery_document_ids ?? [])
    setStandardsRefs(settings.standards_references ?? '')
    setPrefSections(settings.preferred_questionnaire_sections ?? 4)
    setPrefQuestionsPerSection(settings.preferred_questions_per_section ?? 3)
    setClientName(settings.client_name ?? '')
    setServiceCategories(settings.service_categories ?? '')
    setKeyVendors(settings.key_vendors ?? '')
    setApplicableRegulations(settings.applicable_regulations ?? '')
  }, [settings])

  const mutation = useMutation({
    mutationFn: (updated: ProjectSettings) => projectsApi.updateSettings(slug, updated),
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
      standards_references: standardsRefs,
      preferred_questionnaire_sections: prefSections,
      preferred_questions_per_section: prefQuestionsPerSection,
      client_name: clientName,
      service_categories: serviceCategories,
      key_vendors: keyVendors,
      applicable_regulations: applicableRegulations,
    })
  }

  function addLink() {
    const trimmedUrl = newUrl.trim()
    if (!trimmedUrl) return
    setLinks(prev => [...prev, { url: trimmedUrl, label: newLabel.trim() }])
    setNewUrl('')
    setNewLabel('')
  }

  function removeLink(index: number) {
    setLinks(prev => prev.filter((_, i) => i !== index))
  }

  function toggleDoc(id: number) {
    setSelectedDocIds(prev =>
      prev.includes(id) ? prev.filter(d => d !== id) : [...prev, id]
    )
  }

  const inputCls = 'w-full bg-white border border-gray-200 rounded px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-brand'

  return (
    <div className="space-y-6">

      {/* Research Brief */}
      <section>
        <h3 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Research Brief</h3>
        <p className="text-[11px] text-gray-400 mb-2">
          Context Alex uses before starting — strategic priorities, scope constraints, client flags.
        </p>
        <textarea
          value={brief}
          onChange={e => setBrief(e.target.value)}
          rows={4}
          placeholder="e.g. The client operates primarily in passenger rail in the UK. Focus on operational efficiency and safety compliance."
          className={`${inputCls} resize-y`}
        />
      </section>

      {/* Research Links */}
      <section>
        <h3 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Research Links</h3>
        <p className="text-[11px] text-gray-400 mb-2">
          URLs Alex will fetch before analysis — industry bodies, regulatory sites, company pages, reports.
        </p>
        {links.length > 0 && (
          <ul className="mb-2 space-y-1">
            {links.map((link, i) => (
              <li key={i} className="flex items-center gap-2 bg-gray-50 border border-gray-100 rounded px-2 py-1.5 text-xs">
                <span className="text-brand font-mono flex-1 truncate">{link.url}</span>
                {link.label && <span className="text-gray-400">{link.label}</span>}
                <button onClick={() => removeLink(i)} className="text-gray-300 hover:text-red-400 flex-shrink-0">
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <input
            value={newUrl}
            onChange={e => setNewUrl(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addLink()}
            placeholder="https://..."
            className="flex-1 bg-white border border-gray-200 rounded px-2.5 py-1.5 text-xs text-gray-900 placeholder-gray-400 outline-none focus:border-brand"
          />
          <input
            value={newLabel}
            onChange={e => setNewLabel(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addLink()}
            placeholder="Label (optional)"
            className="w-32 bg-white border border-gray-200 rounded px-2.5 py-1.5 text-xs text-gray-900 placeholder-gray-400 outline-none focus:border-brand"
          />
          <button
            type="button"
            onClick={addLink}
            disabled={!newUrl.trim()}
            className="px-3 py-1.5 bg-brand hover:bg-brand-dark disabled:opacity-40 text-white text-xs rounded flex-shrink-0"
          >
            Add
          </button>
        </div>
      </section>

      {/* Source Documents */}
      <section>
        <h3 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Source Documents</h3>
        <p className="text-[11px] text-gray-400 mb-2">
          Alex will focus ChromaDB queries on these documents.
        </p>
        {documents.length === 0 ? (
          <p className="text-[11px] text-gray-400 italic">No documents uploaded yet — use the Documents page to upload.</p>
        ) : (
          <ul className="space-y-1">
            {documents.map(doc => (
              <li key={doc.id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id={`adoc-${doc.id}`}
                  checked={selectedDocIds.includes(doc.id)}
                  onChange={() => toggleDoc(doc.id)}
                  className="accent-brand"
                />
                <label htmlFor={`adoc-${doc.id}`} className="text-xs text-gray-700 cursor-pointer">
                  {doc.original_name}
                  <span className="text-gray-400 ml-1.5">({(doc.size_bytes / 1024).toFixed(0)} KB)</span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Project Context — Alex's handoff to Maya */}
      <section>
        <h3 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Project Context</h3>
        <p className="text-[11px] text-gray-400 mb-3">
          Alex establishes these fields after value chain discovery. Maya reads them at run time to make interview instruments specific to this engagement — populate before running Maya.
        </p>
        <div className="space-y-3">
          <div>
            <label className="block text-[10px] text-gray-500 mb-1">Client organisation name</label>
            <input
              type="text"
              value={clientName}
              onChange={e => setClientName(e.target.value)}
              placeholder="e.g. Network Rail, Tesco, HSBC"
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-[10px] text-gray-500 mb-1">Service categories (what the client delivers)</label>
            <input
              type="text"
              value={serviceCategories}
              onChange={e => setServiceCategories(e.target.value)}
              placeholder="e.g. track maintenance, retail operations, retail banking"
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-[10px] text-gray-500 mb-1">Key vendors / outsourced service providers</label>
            <input
              type="text"
              value={keyVendors}
              onChange={e => setKeyVendors(e.target.value)}
              placeholder="e.g. Amey, Capita, IBM — comma-separated"
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-[10px] text-gray-500 mb-1">Applicable regulatory frameworks</label>
            <input
              type="text"
              value={applicableRegulations}
              onChange={e => setApplicableRegulations(e.target.value)}
              placeholder="e.g. ORR, FCA, ISO 55001 — comma-separated"
              className={inputCls}
            />
          </div>
        </div>
      </section>

      {/* Standards & Questionnaire Preferences */}
      <section>
        <h3 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Standards &amp; Questionnaire Build</h3>
        <p className="text-[11px] text-gray-400 mb-2">
          Frameworks Maya uses when designing maturity questionnaires for each value chain node.
        </p>
        <textarea
          value={standardsRefs}
          onChange={e => setStandardsRefs(e.target.value)}
          rows={3}
          placeholder="e.g. ISO 55001 (Asset Management), IIMM, PAS 55, IIRC Six Capitals, ISO 9001…"
          className={`${inputCls} resize-y mb-3`}
        />
        <div className="flex gap-4">
          <div>
            <label className="block text-[10px] text-gray-500 mb-1">Sections per questionnaire</label>
            <input
              type="number"
              min={1}
              max={12}
              value={prefSections}
              onChange={e => setPrefSections(Math.max(1, Number(e.target.value)))}
              className="w-20 bg-white border border-gray-200 rounded px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
            />
          </div>
          <div>
            <label className="block text-[10px] text-gray-500 mb-1">Questions per section</label>
            <input
              type="number"
              min={1}
              max={20}
              value={prefQuestionsPerSection}
              onChange={e => setPrefQuestionsPerSection(Math.max(1, Number(e.target.value)))}
              className="w-20 bg-white border border-gray-200 rounded px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
            />
          </div>
        </div>
      </section>

      {error && <p className="text-red-400 text-xs">{error}</p>}
      <div className="flex items-center gap-3 pt-1">
        <button
          type="button"
          onClick={handleSave}
          disabled={mutation.isPending}
          className="px-4 py-1.5 bg-brand hover:bg-brand-dark disabled:opacity-50 text-white text-xs font-medium rounded"
        >
          {mutation.isPending ? 'Saving…' : 'Save'}
        </button>
        {saved && <span className="text-emerald-500 text-xs">Saved.</span>}
      </div>
    </div>
  )
}
