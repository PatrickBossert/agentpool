// ui/src/pages/Roadmap.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState, Fragment } from 'react'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { downloadOutput } from '../utils/download'
import type { RoadmapData, Initiative } from '../types'

type Tab = 'visual' | 'gantt' | 'register'
type GroupBy = 'category' | 'value_stream'

const CATEGORY_COLOURS: Record<string, string> = {
  enabling: '#3b82f6',
  operating_model: '#f59e0b',
  business_change: '#22c55e',
}

export default function Roadmap() {
  const { slug } = useParams<{ slug: string }>()
  const [tab, setTab] = useState<Tab>('visual')
  const [groupBy, setGroupBy] = useState<GroupBy>('category')
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

  const { data: allOutputs = [] } = useQuery({
    queryKey: ['outputs', slug],
    queryFn: () => projectsApi.outputs(slug!),
    enabled: !!slug && tab === 'gantt',
  })
  const roadmapDataOutput = allOutputs.find((o) => o.output_type === 'roadmap_data') ?? null

  const { data: roadmapData } = useQuery({
    queryKey: ['roadmap-data', slug],
    queryFn: () => projectsApi.roadmapData(slug!),
    enabled: !!slug && (tab === 'gantt' || tab === 'register'),
  })

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-100">Roadmap</h2>
        <div className="flex rounded-lg overflow-hidden border border-slate-700" role="tablist">
          {(['visual', 'gantt', 'register'] as Tab[]).map((t) => (
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

      {!isLoading && outputs.length === 0 && tab === 'visual' && (
        <div className="bg-surface-card rounded-xl p-8 text-center">
          <p className="text-slate-400 text-sm">
            Awaiting Roadmap Generator output — visual timeline will appear here.
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

      {tab === 'gantt' && (
        <div className="bg-surface-card rounded-xl overflow-hidden">
          {/* Controls row */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-500 uppercase tracking-widest">Group by</span>
              <div className="flex rounded-lg overflow-hidden border border-slate-700">
                {(['category', 'value_stream'] as GroupBy[]).map((g) => (
                  <button
                    key={g}
                    onClick={() => setGroupBy(g)}
                    className={`px-3 py-1 text-xs capitalize transition-colors ${
                      groupBy === g ? 'bg-brand text-white' : 'text-slate-400 hover:bg-slate-800'
                    }`}
                  >
                    {g === 'value_stream' ? 'Value Stream' : 'Category'}
                  </button>
                ))}
              </div>
            </div>
            {roadmapDataOutput && (
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500">
                  {roadmapDataOutput.agent_name} · v{roadmapDataOutput.version}
                </span>
                <button
                  onClick={() =>
                    downloadOutput(
                      slug!,
                      roadmapDataOutput.id,
                      'roadmap_data.json',
                      token!,
                    ).catch(console.error)
                  }
                  className="text-xs text-sky-400 hover:text-sky-300 transition-colors"
                >
                  ↓ Download JSON
                </button>
              </div>
            )}
          </div>

          {/* Empty state */}
          {!roadmapData && (
            <p className="text-sm text-slate-500 p-4">
              Gantt chart will appear here once initiatives are identified.
            </p>
          )}

          {/* Gantt table */}
          {roadmapData && <GanttTable data={roadmapData} groupBy={groupBy} />}
        </div>
      )}

      {tab === 'register' && (
        <div className="bg-surface-card rounded-xl overflow-hidden">
          {/* Controls row — same Group By toggle as Gantt */}
          <div className="flex items-center px-4 py-3 border-b border-slate-800">
            <span className="text-xs text-slate-500 uppercase tracking-widest">Group by</span>
            <div className="flex rounded-lg overflow-hidden border border-slate-700 ml-3">
              {(['category', 'value_stream'] as GroupBy[]).map((g) => (
                <button
                  key={g}
                  onClick={() => setGroupBy(g)}
                  className={`px-3 py-1 text-xs capitalize transition-colors ${
                    groupBy === g ? 'bg-brand text-white' : 'text-slate-400 hover:bg-slate-800'
                  }`}
                >
                  {g === 'value_stream' ? 'Value Stream' : 'Category'}
                </button>
              ))}
            </div>
          </div>

          {/* Empty state */}
          {!roadmapData && (
            <p className="text-sm text-slate-500 p-4">
              Initiative register will appear here once initiatives are identified.
            </p>
          )}

          {/* Register table */}
          {roadmapData && <RegisterTable data={roadmapData} groupBy={groupBy} />}
        </div>
      )}
    </div>
  )
}

function GanttTable({ data, groupBy }: { data: RoadmapData; groupBy: GroupBy }) {
  const groups =
    groupBy === 'category'
      ? [...new Set(data.initiatives.map((i) => i.category))]
      : data.value_streams

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-slate-900">
            <th className="px-4 py-2 text-left text-slate-500 font-medium min-w-[180px]">
              Initiative
            </th>
            {data.periods.map((p) => (
              <th key={p} className="px-3 py-2 text-center text-slate-500 font-medium min-w-[90px]">
                {p}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const members =
              groupBy === 'category'
                ? data.initiatives.filter((i) => i.category === group)
                : data.initiatives.filter((i) => i.value_streams.includes(group))
            const colour =
              groupBy === 'category' ? (CATEGORY_COLOURS[group] ?? '#9ca3af') : '#6366f1'
            return (
              <Fragment key={group}>
                <tr className="bg-slate-900/60 border-t-2 border-slate-800">
                  <td
                    colSpan={data.periods.length + 1}
                    className="px-4 py-1.5 text-xs font-semibold uppercase tracking-widest"
                    style={{ color: colour }}
                  >
                    ● {group.replace(/_/g, ' ')}
                  </td>
                </tr>
                {members.map((initiative: Initiative) => (
                  <tr key={initiative.title} className="border-t border-slate-800">
                    <td className="px-4 py-2 text-slate-300">{initiative.title}</td>
                    {data.periods.map((p) => {
                      const active = initiative.period === p
                      return (
                        <td
                          key={p}
                          className="px-1.5 py-1 border-l border-slate-800 text-center"
                          style={{ background: active ? `${colour}10` : undefined }}
                        >
                          {active && (
                            <div
                              className="rounded flex items-center justify-center h-5 text-white font-semibold"
                              style={{ background: colour, fontSize: '0.68rem' }}
                            >
                              {initiative.complexity_score}
                            </div>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function RegisterTable({ data, groupBy }: { data: RoadmapData; groupBy: GroupBy }) {
  const hasUnassigned =
    groupBy === 'value_stream' && data.initiatives.some((i) => i.value_streams.length === 0)
  const groups =
    groupBy === 'category'
      ? [...new Set(data.initiatives.map((i) => i.category))]
      : hasUnassigned
      ? [...data.value_streams, 'Unassigned']
      : data.value_streams

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-slate-900">
            <th className="px-4 py-2 text-left text-slate-500 font-medium min-w-[200px]">
              Initiative
            </th>
            {groupBy === 'value_stream' && (
              <th className="px-3 py-2 text-left text-slate-500 font-medium">Category</th>
            )}
            <th className="px-3 py-2 text-left text-slate-500 font-medium">Value Streams</th>
            <th className="px-3 py-2 text-center text-slate-500 font-medium min-w-[90px]">
              Period
            </th>
            <th className="px-3 py-2 text-center text-slate-500 font-medium min-w-[80px]">
              Complexity
            </th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const members =
              groupBy === 'category'
                ? data.initiatives.filter((i) => i.category === group)
                : group === 'Unassigned'
                ? data.initiatives.filter((i) => i.value_streams.length === 0)
                : data.initiatives.filter((i) => i.value_streams.includes(group))
            const colour =
              groupBy === 'category' ? (CATEGORY_COLOURS[group] ?? '#9ca3af') : '#6366f1'
            const columnCount = groupBy === 'value_stream' ? 5 : 4

            return (
              <Fragment key={group}>
                <tr className="bg-slate-900/60 border-t-2 border-slate-800">
                  <td
                    colSpan={columnCount}
                    className="px-4 py-1.5 text-xs font-semibold uppercase tracking-widest"
                    style={{ color: colour }}
                  >
                    ● {group.replace(/_/g, ' ')}
                  </td>
                </tr>
                {members.map((initiative: Initiative) => (
                  <tr
                    key={`${group}-${initiative.title}`}
                    className="border-t border-slate-800"
                  >
                    <td className="px-4 py-2 text-slate-300">{initiative.title}</td>
                    {groupBy === 'value_stream' && (
                      <td className="px-3 py-2">
                        <span
                          className="rounded px-2 py-0.5 text-xs font-medium"
                          style={{
                            background: `${CATEGORY_COLOURS[initiative.category] ?? '#9ca3af'}20`,
                            color: CATEGORY_COLOURS[initiative.category] ?? '#9ca3af',
                          }}
                        >
                          {initiative.category.replace(/_/g, ' ')}
                        </span>
                      </td>
                    )}
                    <td className="px-3 py-2 text-slate-400">
                      {initiative.value_streams.join(', ')}
                    </td>
                    <td className="px-3 py-2 text-center text-slate-400">{initiative.period}</td>
                    <td className="px-3 py-2 text-center">
                      <span
                        className="rounded px-2 py-0.5 text-xs font-bold text-white"
                        style={{
                          background: CATEGORY_COLOURS[initiative.category] ?? '#9ca3af',
                        }}
                      >
                        {initiative.complexity_score}
                      </span>
                    </td>
                  </tr>
                ))}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
