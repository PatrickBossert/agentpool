// ui/src/pages/Documents.tsx
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, ChangeEvent } from 'react'
import { projectsApi } from '../api/endpoints'
import type { ClientDocument, AgentOutput } from '../types'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function Documents() {
  const { slug } = useParams<{ slug: string }>()
  const qc = useQueryClient()
  const { token } = useAuth()
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: clientDocs = [] } = useQuery<ClientDocument[]>({
    queryKey: ['documents', slug],
    queryFn: () => projectsApi.documents(slug!),
    enabled: !!slug,
  })

  const { data: agentOutputs = [] } = useQuery<AgentOutput[]>({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug,
  })

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !slug) return
    await projectsApi.uploadDocument(slug, file)
    qc.invalidateQueries({ queryKey: ['documents', slug] })
    if (inputRef.current) inputRef.current.value = ''
  }

  if (!slug) return null

  return (
    <div className="p-6 space-y-8">
      {/* Upload */}
      <section>
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">
          Upload Document
        </h3>
        <label
          htmlFor="file-upload"
          className="cursor-pointer inline-flex items-center gap-2 bg-brand hover:bg-brand-dark text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          Upload file
        </label>
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

      {/* Client docs */}
      <section>
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">
          Source Documents
        </h3>
        {clientDocs.length === 0 ? (
          <p className="text-sm text-gray-400">No documents uploaded yet.</p>
        ) : (
          <div className="space-y-2">
            {clientDocs.map((doc) => (
              <div
                key={doc.id}
                className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900">{doc.original_name}</p>
                  <p className="text-xs text-gray-400">
                    {formatBytes(doc.size_bytes)} · {doc.content_type}
                    {doc.ingested ? (
                      <span className="ml-2 text-emerald-400">✓ ingested</span>
                    ) : (
                      <span className="ml-2 text-gray-400">pending ingestion</span>
                    )}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Agent outputs */}
      <section>
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">
          Agent Outputs
        </h3>
        {agentOutputs.length === 0 ? (
          <p className="text-sm text-gray-400">No agent outputs yet.</p>
        ) : (
          <div className="space-y-2">
            {agentOutputs.map((o) => (
              <div
                key={o.id}
                className="flex items-center justify-between bg-surface-card rounded-lg px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900">{o.agent_name}</p>
                  <p className="text-xs text-gray-400">{o.output_type} · v{o.version} · {o.review_status}</p>
                </div>
                <button
                  onClick={() => downloadOutput(slug, o.id, o.file_path.split('/').pop() ?? o.output_type, token!).catch(console.error)}
                  className="text-xs text-brand hover:text-brand-dark transition-colors"
                >
                  ↓ Download
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
