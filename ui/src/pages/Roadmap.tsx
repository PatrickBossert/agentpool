// ui/src/pages/Roadmap.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'

type Tab = 'visual' | 'gantt'

export default function Roadmap() {
  const { slug } = useParams<{ slug: string }>()
  const [tab, setTab] = useState<Tab>('visual')
  const { token } = useAuth()

  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['roadmap', slug],
    queryFn: () => projectsApi.roadmap(slug!),
    enabled: !!slug,
  })

  // Pick the latest output record (API returns DESC order)
  const latest = outputs[0] ?? null

  const { data: contentData, isLoading: contentLoading, isError: contentError } = useQuery({
    queryKey: ['outputContent', slug, latest?.id],
    queryFn: () => projectsApi.getOutputContent(slug!, latest!.id),
    // Only fetch when on the visual tab and an output exists
    enabled: !!slug && !!latest && tab === 'visual',
  })

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-100">Roadmap</h2>
        <div className="flex rounded-lg overflow-hidden border border-slate-700" role="tablist">
          {(['visual', 'gantt'] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-sm capitalize transition-colors ${
                tab === t
                  ? 'bg-brand text-white'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}

      {!isLoading && outputs.length === 0 && (
        <div className="bg-surface-card rounded-xl p-8 text-center">
          <p className="text-slate-400 text-sm">
            {tab === 'visual'
              ? 'Awaiting Roadmap Generator output — visual timeline will appear here.'
              : 'Gantt chart will appear here once initiatives are identified.'}
          </p>
          <p className="text-slate-600 text-xs mt-2">
            Run all Discovery, Value Design, and Architecture crews to generate roadmap data.
          </p>
        </div>
      )}

      {latest && tab === 'visual' && (
        <div className="bg-surface-card rounded-xl overflow-hidden">
          <div className="flex justify-between items-center px-4 py-3 border-b border-slate-800">
            <span className="text-sm text-slate-200">{latest.agent_name}</span>
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-500">v{latest.version} · {latest.review_status}</span>
              <button
                onClick={() => downloadOutput(slug!, latest.id, latest.file_path.split('/').pop() ?? latest.output_type, token!).catch(console.error)}
                className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
              >
                ↓ Download
              </button>
            </div>
          </div>
          {contentLoading && (
            <p className="text-sm text-slate-500 p-4">Loading roadmap…</p>
          )}
          {contentError && !contentLoading && (
            <p className="text-sm text-red-400 p-4">Failed to load roadmap.</p>
          )}
          {contentData && (
            <iframe
              srcDoc={contentData.content}
              sandbox="allow-scripts"
              style={{ width: '100%', height: '520px', border: 'none' }}
              title="Roadmap"
            />
          )}
        </div>
      )}

      {latest && tab === 'gantt' && (
        <div className="bg-surface-card rounded-xl p-4">
          <p className="text-sm text-slate-400">Gantt data available — full chart in SP4.</p>
        </div>
      )}
    </div>
  )
}
