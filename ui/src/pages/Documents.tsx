// ui/src/pages/Documents.tsx
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { Upload, FolderOpen, Folder, CheckCircle2, AlertCircle, RotateCcw, X, Download, Loader2 } from 'lucide-react'
import { projectsApi } from '../api/endpoints'
import type { ClientDocument, AgentOutput } from '../types'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const OUTPUT_TYPE_LABELS: Record<string, string> = {
  value_chain:                      'Value Chain',
  interview_scripts:                'Interview Scripts',
  l0_interview_summaries:           'L0 Board Summaries',
  l1_interview_summaries:           'L1 GM Summaries',
  l2_interview_summaries:           'L2 Process Manager Summaries',
  audit_interview_summaries:        'Audit Summaries',
  customer_interview_summaries:     'Customer Summaries',
  frontline_interview_summaries:    'Frontline Summaries',
  corp_services_interview_summaries:'Corporate Services Summaries',
  requirements:                     'Requirements',
  value_levers:                     'Value Levers',
  value_propositions:               'Value Propositions',
  portfolio_register:               'Portfolio Register',
  architecture_blueprint:           'Architecture Blueprint',
  roadmap:                          'Roadmap',
  roadmap_data:                     'Roadmap Data',
  business_plan:                    'Business Plan',
  stakeholder_engagement_plan:      'Stakeholder Engagement Plan',
  interview_transcripts:            'Interview Transcripts',
  activity_insights:                'Activity Insights',
  initiative_register:              'Initiative Register',
}

const INTERNAL_TYPES = new Set(['value_chain_tree', 'value_chain_registry', 'value_chain_summary', 'state'])

function outputLabel(t: string) {
  return OUTPUT_TYPE_LABELS[t] ?? t.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export default function Documents() {
  const { slug } = useParams<{ slug: string }>()
  const qc = useQueryClient()
  const { token } = useAuth()
  const inputRef = useRef<HTMLInputElement>(null)
  const [activeTab, setActiveTab] = useState<'inputs' | 'outputs'>('inputs')
  const [isDragging, setIsDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [reingestingId, setReingestingId] = useState<number | null>(null)

  const { data: clientDocs = [] } = useQuery<ClientDocument[]>({
    queryKey: ['documents', slug],
    queryFn: () => projectsApi.documents(slug!),
    enabled: !!slug,
  })

  const { data: agentOutputs = [] } = useQuery<AgentOutput[]>({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug,
    refetchInterval: 10_000,
  })

  async function reingestDoc(docId: number) {
    if (!slug) return
    setReingestingId(docId)
    try {
      await projectsApi.reingestDocument(slug, docId)
      setTimeout(() => qc.invalidateQueries({ queryKey: ['documents', slug] }), 2000)
    } finally {
      setReingestingId(null)
    }
  }

  async function deleteDoc(docId: number) {
    if (!slug) return
    setDeletingId(docId)
    try {
      await projectsApi.deleteDocument(slug, docId)
      qc.invalidateQueries({ queryKey: ['documents', slug] })
    } finally {
      setDeletingId(null)
    }
  }

  async function uploadFile(file: File) {
    if (!slug) return
    setUploading(true)
    try {
      await projectsApi.uploadDocument(slug, file)
      qc.invalidateQueries({ queryKey: ['documents', slug] })
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) await uploadFile(file)
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) uploadFile(file)
  }

  function handleDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDragging(true)
  }

  function handleDragLeave(e: DragEvent<HTMLDivElement>) {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragging(false)
    }
  }

  if (!slug) return null

  // Only current, non-internal outputs in the Outputs tab
  const downloadableOutputs = agentOutputs.filter(o => o.is_current && !INTERNAL_TYPES.has(o.output_type))

  const tabCls = (active: boolean) =>
    `px-5 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
      active ? 'text-brand border-brand' : 'text-gray-400 border-transparent hover:text-gray-700'
    }`

  return (
    <div className="flex flex-col h-full">

      {/* Page header */}
      <div className="px-6 pt-5 pb-0 border-b border-gray-200 bg-white flex-shrink-0">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Documents</h2>
        <div className="flex">
          <button onClick={() => setActiveTab('inputs')} className={tabCls(activeTab === 'inputs')}>
            Inputs
            {clientDocs.length > 0 && (
              <span className="ml-1.5 text-[10px] bg-gray-100 text-gray-500 rounded-full px-1.5">{clientDocs.length}</span>
            )}
          </button>
          <button onClick={() => setActiveTab('outputs')} className={tabCls(activeTab === 'outputs')}>
            Outputs
            {downloadableOutputs.length > 0 && (
              <span className="ml-1.5 text-[10px] bg-gray-100 text-gray-500 rounded-full px-1.5">{downloadableOutputs.length}</span>
            )}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* ── INPUTS TAB ── */}
        {activeTab === 'inputs' && (
          <>
            {/* Upload drop zone */}
            <section>
              <div
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onClick={() => !uploading && inputRef.current?.click()}
                className={`cursor-pointer rounded-xl border-2 border-dashed px-8 py-10 flex flex-col items-center gap-3 transition-colors select-none ${
                  isDragging
                    ? 'border-brand bg-teal-50'
                    : uploading
                    ? 'border-gray-200 bg-gray-50 cursor-default'
                    : 'border-gray-200 bg-gray-50 hover:border-brand/50 hover:bg-teal-50/30'
                }`}
              >
                <div className="leading-none">
                  {uploading
                    ? <Upload size={32} className="text-gray-300 animate-pulse" />
                    : isDragging
                    ? <FolderOpen size={32} className="text-teal-400" />
                    : <Folder size={32} className="text-gray-300" />}
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-gray-700">
                    {uploading ? 'Uploading…' : isDragging ? 'Drop to upload' : 'Drag & drop a file here'}
                  </p>
                  {!uploading && !isDragging && (
                    <p className="text-xs text-gray-400 mt-0.5">or click to browse</p>
                  )}
                </div>
                {!uploading && (
                  <button
                    type="button"
                    onClick={e => { e.stopPropagation(); inputRef.current?.click() }}
                    className="text-xs font-semibold text-white bg-brand hover:bg-brand-dark px-4 py-1.5 rounded-lg transition-colors"
                  >
                    Browse files
                  </button>
                )}
                <p className="text-xs text-gray-400">PDF · DOCX · XLSX · CSV · TXT</p>
              </div>

              <input
                id="file-upload"
                ref={inputRef}
                type="file"
                accept=".pdf,.docx,.xlsx,.csv,.txt"
                onChange={handleFileChange}
                className="sr-only"
                aria-label="Upload document"
              />
            </section>

            {/* Uploaded documents list */}
            {clientDocs.length === 0 ? (
              <p className="text-sm text-gray-400">No source documents uploaded yet.</p>
            ) : (
              <section>
                <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">
                  Source Documents · {clientDocs.length}
                </h3>
                <div className="space-y-2">
                  {clientDocs.map(doc => (
                    <div
                      key={doc.id}
                      className="flex items-center justify-between bg-white border border-gray-200 rounded-lg px-4 py-3"
                    >
                      <div>
                        <p className="text-sm font-medium text-gray-900">{doc.original_name}</p>
                        <p className="text-xs text-gray-400 flex items-center gap-2">
                          {formatBytes(doc.size_bytes)} · {doc.content_type}
                          {doc.ingested ? (
                            <span className="text-emerald-600 flex items-center gap-0.5"><CheckCircle2 size={11} /> ingested</span>
                          ) : (
                            <span className="text-amber-500 flex items-center gap-0.5"><AlertCircle size={11} /> pending ingestion</span>
                          )}
                        </p>
                      </div>
                      <div className="flex items-center gap-3 ml-4 flex-shrink-0">
                        {!doc.ingested && (
                          <button
                            onClick={() => reingestDoc(doc.id)}
                            disabled={reingestingId === doc.id}
                            className="text-xs text-amber-600 hover:text-amber-800 disabled:opacity-40 transition-colors"
                            title="Retry ingestion into ChromaDB"
                          >
                            {reingestingId === doc.id
                              ? <Loader2 size={12} className="animate-spin" />
                              : <span className="flex items-center gap-1"><RotateCcw size={12} /> Ingest</span>}
                          </button>
                        )}
                        <button
                          onClick={() => deleteDoc(doc.id)}
                          disabled={deletingId === doc.id}
                          className="text-xs text-gray-400 hover:text-red-500 disabled:opacity-40 transition-colors"
                          title="Delete document"
                        >
                          {deletingId === doc.id ? <Loader2 size={12} className="animate-spin" /> : <X size={12} />}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}

        {/* ── OUTPUTS TAB ── */}
        {activeTab === 'outputs' && (
          <>
            {downloadableOutputs.length === 0 ? (
              <p className="text-sm text-gray-400">No agent outputs yet — run the pipeline to generate deliverables.</p>
            ) : (
              <div className="space-y-2">
                {downloadableOutputs
                  .sort((a, b) => a.agent_name.localeCompare(b.agent_name) || a.output_type.localeCompare(b.output_type))
                  .map(o => (
                    <div
                      key={o.id}
                      className="flex items-center justify-between bg-white border border-gray-200 rounded-lg px-4 py-3"
                    >
                      <div>
                        <p className="text-sm font-medium text-gray-900">{outputLabel(o.output_type)}</p>
                        <p className="text-xs text-gray-400">
                          {o.agent_name.replace(/_/g, ' ')} · v{o.version}
                          {o.review_status === 'approved' && (
                            <span className="ml-1.5 text-emerald-600 inline-flex items-center gap-0.5">
                              <CheckCircle2 size={10} /> approved
                            </span>
                          )}
                        </p>
                      </div>
                      <button
                        onClick={() =>
                          downloadOutput(slug, o.id, o.file_path.split('/').pop() ?? o.output_type, token!).catch(console.error)
                        }
                        className="flex items-center gap-1.5 text-xs font-medium text-brand hover:text-brand-dark transition-colors ml-4 flex-shrink-0"
                      >
                        <Download size={13} /> Download
                      </button>
                    </div>
                  ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
