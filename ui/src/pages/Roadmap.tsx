// ui/src/pages/Roadmap.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { projectsApi } from '../api/endpoints'

type Tab = 'visual' | 'gantt'

export default function Roadmap() {
  const { slug } = useParams<{ slug: string }>()
  const [tab, setTab] = useState<Tab>('visual')

  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['roadmap', slug],
    queryFn: () => projectsApi.roadmap(slug!),
    enabled: !!slug,
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

      {outputs.length > 0 && tab === 'visual' && (
        <div className="bg-surface-card rounded-xl p-4">
          <div className="space-y-2">
            {outputs.map((output) => (
              <div key={output.id} className="text-sm text-slate-300">
                {output.agent_name} — {output.file_path}
              </div>
            ))}
          </div>
        </div>
      )}

      {outputs.length > 0 && tab === 'gantt' && (
        <div className="bg-surface-card rounded-xl p-4">
          <p className="text-sm text-slate-400">Gantt data available — full chart in SP4.</p>
        </div>
      )}
    </div>
  )
}
