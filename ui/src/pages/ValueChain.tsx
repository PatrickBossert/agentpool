// ui/src/pages/ValueChain.tsx
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { projectsApi, valueChainApi } from '../api/endpoints'
import { listTemplates } from '../api/templates'
import { listNodeTemplates, putNodeTemplate, publishNodeTemplate } from '../api/nodeTemplates'
import InterviewTemplateEditor from '../components/InterviewTemplateEditor'
import { ValueChainTable, type ValueChainModel, type ValueChainSelection } from '../components/ValueChainTable'
import { ContributionPanel } from '../components/ContributionPanel'
import type { ProjectSettings, DiscoveryLink, ClientDocument, NodeTemplateAssignment, TemplateListItem } from '../types'

function sortByActivityId(assignments: NodeTemplateAssignment[]): NodeTemplateAssignment[] {
  return [...assignments].sort((a, b) => {
    if (!a.activity_id && !b.activity_id) return a.node_label.localeCompare(b.node_label)
    if (!a.activity_id) return 1
    if (!b.activity_id) return -1
    const aParts = a.activity_id.split('.').map(Number)
    const bParts = b.activity_id.split('.').map(Number)
    const len = Math.max(aParts.length, bParts.length)
    for (let i = 0; i < len; i++) {
      const diff = (aParts[i] ?? 0) - (bParts[i] ?? 0)
      if (diff !== 0) return diff
    }
    return 0
  })
}

// A refused migration carries the reason it was refused - which registry levels were found
// where L1 was expected - and that message is the only route to correcting the registry, so
// it is shown rather than flattened into "Migration failed".
function migrationErrorMessage(error: unknown): string {
  if (!axios.isAxiosError(error)) return 'Migration failed. Try again.'
  if (error.response?.status === 404) {
    return 'No existing diagram was found to migrate from - run the Value Chain Mapper first.'
  }
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
  if (error.response?.status === 422 && typeof detail === 'string' && detail) return detail
  return 'Migration failed. Try again.'
}

export default function ValueChain() {
  const { slug } = useParams<{ slug: string }>()
  const qc = useQueryClient()

  // ── Setup tab state ──────────────────────────────────────────
  const [brief, setBrief] = useState('')
  const [links, setLinks] = useState<DiscoveryLink[]>([])
  const [selectedDocIds, setSelectedDocIds] = useState<number[]>([])
  const [newUrl, setNewUrl] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [standardsRefs, setStandardsRefs] = useState('')
  const [prefSections, setPrefSections] = useState(4)
  const [prefQuestionsPerSection, setPrefQuestionsPerSection] = useState(3)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── Template editor modal state ──────────────────────────────
  const [editingNode, setEditingNode] = useState<NodeTemplateAssignment | null>(null)

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
      setStandardsRefs(settings.standards_references ?? '')
      setPrefSections(settings.preferred_questionnaire_sections ?? 4)
      setPrefQuestionsPerSection(settings.preferred_questions_per_section ?? 3)
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
      standards_references: standardsRefs,
      preferred_questionnaire_sections: prefSections,
      preferred_questions_per_section: prefQuestionsPerSection,
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

  // ── Structure tab state ──────────────────────────────────────
  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['value-chain', slug],
    queryFn: () => projectsApi.valueChain(slug!),
    enabled: !!slug,
  })

  const {
    data: modelData,
    isLoading: modelLoading,
    isError: modelIsError,
    error: modelError,
  } = useQuery({
    queryKey: ['value-chain-model', slug],
    queryFn: () => valueChainApi.get(slug!),
    enabled: !!slug,
    retry: false,
  })

  const modelMissing = modelIsError && axios.isAxiosError(modelError) && modelError.response?.status === 404
  const model = (modelData?.model ?? null) as ValueChainModel | null

  const migrateMutation = useMutation({
    mutationFn: () => valueChainApi.migrate(slug!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['value-chain-model', slug] }),
  })

  // Edits are held here, in the page, and only committed to the server by the Save
  // control - never per-keystroke, so the version history and change log stay meaningful.
  const [editedModel, setEditedModel] = useState<ValueChainModel | null>(null)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [changeSummary, setChangeSummary] = useState('')
  const [saveProblems, setSaveProblems] = useState<string[] | null>(null)

  // Reseed the working copy from the server whenever a fresh model arrives and there is
  // nothing unsaved to lose - covers first load and the refetch after a successful save.
  useEffect(() => {
    if (model && !hasUnsavedChanges) setEditedModel(model)
  }, [model, hasUnsavedChanges])

  function handleModelChange(updated: ValueChainModel) {
    setEditedModel(updated)
    setHasUnsavedChanges(true)
    setSaveProblems(null)
  }

  // The table owns editing; the page owns which contribution is selected, since the panel
  // that shows it lives outside the table.
  const [selectedContribution, setSelectedContribution] = useState<ValueChainSelection | null>(null)

  function handleSelectContribution(activityId: string, partyId: string) {
    setSelectedContribution({ activityId, partyId })
  }

  const saveModelMutation = useMutation({
    mutationFn: () => valueChainApi.save(slug!, editedModel, changeSummary),
    onSuccess: () => {
      setHasUnsavedChanges(false)
      setSaveProblems(null)
      setChangeSummary('')
      qc.invalidateQueries({ queryKey: ['value-chain-model', slug] })
    },
    onError: (e: unknown) => {
      if (axios.isAxiosError(e) && e.response?.status === 422) {
        const problems = (e.response.data as { detail?: { problems?: string[] } } | undefined)?.detail?.problems
        setSaveProblems(problems && problems.length > 0 ? problems : ['The value chain model could not be saved.'])
      } else {
        setSaveProblems(['Failed to save changes. Try again.'])
      }
    },
  })

  // Unsaved edits are discarded on navigation - the usual browser warning is the only
  // safeguard, since there is nowhere else in this app that persists a draft.
  useEffect(() => {
    function warnBeforeUnload(e: BeforeUnloadEvent) {
      if (!hasUnsavedChanges) return
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [hasUnsavedChanges])

  // ── Templates tab state ──────────────────────────────────────
  const [nodeAssignments, setNodeAssignments] = useState<NodeTemplateAssignment[]>([])
  const [interviewTemplates, setInterviewTemplates] = useState<TemplateListItem[]>([])
  const [questionnaireTemplates, setQuestionnaireTemplates] = useState<TemplateListItem[]>([])

  // ── Tab ──────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<'setup' | 'structure' | 'templates'>('setup')

  // Switch to the Structure tab automatically once outputs are known to exist
  useEffect(() => {
    if (!isLoading && outputs.length > 0) setActiveTab('structure')
  }, [isLoading, outputs.length])

  // Fetch templates data when Templates tab is active
  useEffect(() => {
    if (activeTab !== 'templates' || !slug) return
    Promise.all([
      listNodeTemplates(slug),
      listTemplates('interview'),
      listTemplates('questionnaire'),
    ]).then(([assignments, interviewTpls, questionnaireTpls]) => {
      setNodeAssignments(sortByActivityId(assignments))
      setInterviewTemplates(interviewTpls)
      setQuestionnaireTemplates(questionnaireTpls)
    }).catch(console.error)
  }, [activeTab, slug])

  async function handleTemplateChange(
    nodeLabel: string,
    field: 'interview_template_id' | 'questionnaire_template_id',
    value: number | null,
  ) {
    const current = nodeAssignments.find((a) => a.node_label === nodeLabel)
    const updated: NodeTemplateAssignment = current
      ? { ...current, [field]: value }
      : { node_label: nodeLabel, activity_id: null, interview_template_id: null, questionnaire_template_id: null, [field]: value }

    setNodeAssignments((prev) =>
      prev.some((a) => a.node_label === nodeLabel)
        ? prev.map((a) => (a.node_label === nodeLabel ? updated : a))
        : [...prev, updated],
    )

    try {
      await putNodeTemplate(slug!, nodeLabel, {
        interview_template_id: updated.interview_template_id,
        questionnaire_template_id: updated.questionnaire_template_id,
      })
    } catch (e) {
      console.error('Auto-save failed', e)
    }
  }

  async function handlePublish(nodeLabel: string) {
    const name = window.prompt(`Template name for "${nodeLabel}":`)
    if (!name || !name.trim()) return
    try {
      await publishNodeTemplate(slug!, nodeLabel, { name: name.trim(), description: '' })
    } catch (e) {
      console.error('Publish failed', e)
      alert('Publish failed - check that the interview script has been generated for this node.')
    }
  }

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Value Chain</h2>

      {/* Tab strip */}
      <div className="flex border-b border-gray-200 mb-6">
        {(['setup', 'structure', 'templates'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm capitalize border-b-2 transition-colors ${
              activeTab === tab
                ? 'text-brand border-brand'
                : 'text-gray-400 border-transparent hover:text-gray-700'
            }`}
          >
            {tab === 'setup' ? 'Setup' : tab === 'structure' ? 'Structure' : 'Templates'}
          </button>
        ))}
      </div>

      {/* ── Setup tab ─────────────────────────────────────────── */}
      {activeTab === 'setup' && (
        <div className="max-w-3xl">
          <p className="text-gray-500 text-sm mb-8">
            Configure what the Value Chain Mapper uses before it starts. Changes take effect on the next crew run.
          </p>

          {/* Research Brief */}
          <section className="mb-8">
            <h3 className="text-sm font-medium text-gray-700 uppercase tracking-wide mb-2">Research Brief</h3>
            <p className="text-gray-400 text-xs mb-3">
              Any context the crew should know before it starts - strategic priorities, scope constraints, what the client has flagged.
            </p>
            <textarea
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              rows={5}
              placeholder="e.g. The client operates primarily in passenger rail in the UK. Focus on operational efficiency and safety compliance themes."
              className="w-full bg-white border border-gray-200 rounded p-3 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-brand resize-y"
            />
          </section>

          {/* Research Links */}
          <section className="mb-8">
            <h3 className="text-sm font-medium text-gray-700 uppercase tracking-wide mb-2">Research Links</h3>
            <p className="text-gray-400 text-xs mb-3">
              URLs the crew will fetch and read before analysis. Add industry bodies, regulatory sites, company pages, or reports.
            </p>
            {links.length > 0 && (
              <ul className="mb-3 space-y-1">
                {links.map((link, i) => (
                  <li key={i} className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded px-3 py-2">
                    <span className="text-brand text-xs font-mono flex-1 truncate">{link.url}</span>
                    {link.label && <span className="text-gray-500 text-xs">{link.label}</span>}
                    <button
                      type="button"
                      onClick={() => removeLink(i)}
                      className="text-gray-400 hover:text-red-400 text-xs ml-2"
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
                className="flex-1 bg-white border border-gray-200 rounded px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-brand"
              />
              <input
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addLink()}
                placeholder="Label (optional)"
                className="w-40 bg-white border border-gray-200 rounded px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-brand"
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
            <h3 className="text-sm font-medium text-gray-700 uppercase tracking-wide mb-2">Source Documents</h3>
            <p className="text-gray-400 text-xs mb-3">
              Select documents to prioritise. The crew will focus ChromaDB queries on these files.
            </p>
            {documents.length === 0 ? (
              <p className="text-gray-400 text-sm italic">No documents uploaded yet. Upload documents on the Documents page.</p>
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
                    <label htmlFor={`doc-${doc.id}`} className="text-sm text-gray-700 cursor-pointer">
                      {doc.original_name}
                      <span className="text-gray-400 text-xs ml-2">
                        ({(doc.size_bytes / 1024).toFixed(0)} KB)
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Standards & Questionnaire Preferences */}
          <section className="mb-8">
            <h3 className="text-sm font-medium text-gray-700 uppercase tracking-wide mb-2">Standards &amp; Questionnaire Build</h3>
            <p className="text-gray-400 text-xs mb-3">
              Standards, frameworks, or references the Questionnaire Builder should use when designing maturity assessment questionnaires for each value chain node.
            </p>
            <textarea
              value={standardsRefs}
              onChange={(e) => setStandardsRefs(e.target.value)}
              rows={4}
              placeholder="e.g. ISO 55001 (Asset Management), IIMM, PAS 55, IIRC Six Capitals, ISO 9001, local regulatory frameworks…"
              className="w-full bg-white border border-gray-200 rounded p-3 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-brand resize-y mb-4"
            />
            <div className="flex gap-6">
              <div className="flex-1">
                <label className="block text-xs text-gray-600 mb-1">Preferred sections per questionnaire</label>
                <input
                  type="number"
                  min={1}
                  max={12}
                  value={prefSections}
                  onChange={(e) => setPrefSections(Math.max(1, Number(e.target.value)))}
                  className="w-24 bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
                />
              </div>
              <div className="flex-1">
                <label className="block text-xs text-gray-600 mb-1">Preferred questions per section</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={prefQuestionsPerSection}
                  onChange={(e) => setPrefQuestionsPerSection(Math.max(1, Number(e.target.value)))}
                  className="w-24 bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
                />
              </div>
            </div>
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

      {/* ── Templates tab ─────────────────────────────────────── */}
      {activeTab === 'templates' && (
        <div>
          <p className="text-gray-500 text-sm mb-6">
            Assign interview and questionnaire templates to each value chain node. Changes save automatically.
          </p>

          {nodeAssignments.length === 0 ? (
            <div className="bg-surface-card rounded-xl p-8 text-center">
              <p className="text-gray-400 text-sm">Run the Value Chain crew first to generate nodes.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 text-left">
                    <th className="pb-2 pr-4 text-gray-500 font-medium w-8">#</th>
                    <th className="pb-2 pr-4 text-gray-500 font-medium">Node</th>
                    <th className="pb-2 pr-4 text-gray-500 font-medium">Interview Template</th>
                    <th className="pb-2 pr-4 text-gray-500 font-medium">Questionnaire Template</th>
                    <th className="pb-2 pr-4 text-gray-500 font-medium">Publish</th>
                    <th className="pb-2 text-gray-500 font-medium">Script</th>
                  </tr>
                </thead>
                <tbody>
                  {nodeAssignments.map((assignment) => {
                    const isL1 = assignment.level === 'L1'
                    return (
                    <tr key={assignment.node_label} className={`border-b border-gray-200 ${isL1 ? 'bg-gray-50' : ''}`}>
                      <td className="py-3 pr-3 font-mono text-xs text-gray-400 whitespace-nowrap">
                        {assignment.activity_id ?? '-'}
                      </td>
                      <td className="py-3 pr-4">
                        <div className={isL1 ? 'font-semibold text-gray-900 text-sm' : 'font-medium text-gray-900 text-sm'}>
                          {assignment.node_label}
                        </div>
                        {isL1 && (
                          <span className="text-xs text-brand bg-brand/10 px-1.5 py-0.5 rounded font-medium">L1 Leadership</span>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        <select
                          value={assignment.interview_template_id ?? ''}
                          onChange={(e) =>
                            handleTemplateChange(
                              assignment.node_label,
                              'interview_template_id',
                              e.target.value ? Number(e.target.value) : null,
                            )
                          }
                          className="bg-white border border-gray-200 rounded px-2 py-1 text-sm text-gray-900 outline-none focus:border-brand w-full max-w-xs"
                        >
                          <option value="">- None -</option>
                          {interviewTemplates.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="py-3 pr-4">
                        <select
                          value={assignment.questionnaire_template_id ?? ''}
                          onChange={(e) =>
                            handleTemplateChange(
                              assignment.node_label,
                              'questionnaire_template_id',
                              e.target.value ? Number(e.target.value) : null,
                            )
                          }
                          className="bg-white border border-gray-200 rounded px-2 py-1 text-sm text-gray-900 outline-none focus:border-brand w-full max-w-xs"
                        >
                          <option value="">- None -</option>
                          {questionnaireTemplates.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="py-3 pr-4">
                        <button
                          type="button"
                          onClick={() => handlePublish(assignment.node_label)}
                          className="px-3 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs rounded transition-colors"
                        >
                          Publish
                        </button>
                      </td>
                      <td className="py-3">
                        {!isL1 && (
                          <button
                            type="button"
                            onClick={() => setEditingNode(assignment)}
                            className="px-3 py-1 border border-gray-200 hover:border-brand hover:text-brand text-gray-500 text-xs rounded transition-colors"
                          >
                            Edit Script
                          </button>
                        )}
                      </td>
                    </tr>
                  )})}

                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Interview Script Editor modal ────────────────────── */}
      {editingNode && slug && (
        <InterviewTemplateEditor
          slug={slug}
          nodeLabel={editingNode.node_label}
          activityId={editingNode.activity_id}
          onClose={() => setEditingNode(null)}
        />
      )}

      {/* ── Structure tab ─────────────────────────────────────── */}
      {activeTab === 'structure' && (
        <>
          {/* What the migration actually recovered. A bare "success" hid a registry that
              yielded almost nothing, so the counts are shown rather than assumed. */}
          {migrateMutation.data && (
            <div
              data-testid="migration-counts"
              className="mb-4 bg-surface-card border border-surface rounded p-3"
            >
              <p className="text-primary text-xs font-medium mb-1">
                Migrated from the existing diagram
              </p>
              <p className="text-secondary text-xs">
                {migrateMutation.data.counts.segments} segments,{' '}
                {migrateMutation.data.counts.activities} activities,{' '}
                {migrateMutation.data.counts.contributions} contributions,{' '}
                {migrateMutation.data.counts.tasks} tasks across{' '}
                {migrateMutation.data.counts.parties} parties -{' '}
                {migrateMutation.data.counts.derived} attributed by inference.
              </p>
            </div>
          )}

          {modelLoading && <p className="text-sm text-muted">Loading…</p>}

          {!modelLoading && editedModel && (
            <div className="flex flex-col lg:flex-row gap-6 items-start">
              <div className="flex-1 min-w-0">
                <ValueChainTable
                  model={editedModel}
                  onChange={handleModelChange}
                  selected={selectedContribution}
                  onSelect={handleSelectContribution}
                />

                <div className="mt-6 flex flex-wrap items-center gap-3">
                  <input
                    type="text"
                    value={changeSummary}
                    onChange={(e) => setChangeSummary(e.target.value)}
                    placeholder="Summary of this change (optional)"
                    className="flex-1 min-w-[16rem] max-w-md bg-surface-raised border border-surface rounded px-3 py-2 text-sm text-primary placeholder-muted outline-none focus:border-brand"
                  />
                  <button
                    type="button"
                    onClick={() => saveModelMutation.mutate()}
                    disabled={!hasUnsavedChanges || saveModelMutation.isPending}
                    className="px-4 py-2 bg-brand hover:bg-brand-dark disabled:opacity-50 text-white text-sm font-medium rounded"
                  >
                    {saveModelMutation.isPending ? 'Saving…' : 'Save'}
                  </button>
                  {hasUnsavedChanges && !saveModelMutation.isPending && (
                    <span data-testid="unsaved-changes" className="text-secondary text-xs">
                      Unsaved changes
                    </span>
                  )}
                </div>

                {saveProblems && (
                  <div className="mt-3 bg-surface-card border border-surface rounded p-3">
                    <p className="text-primary text-xs font-medium mb-1">Could not save:</p>
                    <ul className="list-disc list-inside text-xs text-red-400 space-y-0.5">
                      {saveProblems.map((problem, i) => (
                        <li key={i}>{problem}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Side panel: a contribution's tasks and its activity's propositions, in place
                  of a pop-up - selected from the table on the left. */}
              <div className="w-full lg:w-80 flex-shrink-0">
                {selectedContribution ? (
                  <ContributionPanel
                    model={editedModel}
                    activityId={selectedContribution.activityId}
                    partyId={selectedContribution.partyId}
                  />
                ) : (
                  <div
                    data-testid="contribution-panel-placeholder"
                    className="bg-surface-card rounded-xl p-4 text-center"
                  >
                    <p className="text-muted text-sm">
                      Select a contribution to see its tasks and propositions.
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {!modelLoading && modelMissing && (
            <div className="bg-surface-card rounded-xl p-8 text-center">
              <p className="text-muted text-sm mb-4">
                No value chain model has been saved for this project yet.
              </p>
              <button
                type="button"
                onClick={() => migrateMutation.mutate()}
                disabled={migrateMutation.isPending}
                className="px-4 py-2 bg-brand hover:bg-brand-dark disabled:opacity-50 text-white text-sm font-medium rounded"
              >
                {migrateMutation.isPending ? 'Migrating…' : 'Migrate from the existing diagram'}
              </button>
              {migrateMutation.isError && (
                <p className="text-red-400 text-xs mt-3">{migrationErrorMessage(migrateMutation.error)}</p>
              )}
            </div>
          )}

          {!modelLoading && modelIsError && !modelMissing && (
            <p className="text-sm text-red-400">Failed to load the value chain model.</p>
          )}
        </>
      )}
    </div>
  )
}
