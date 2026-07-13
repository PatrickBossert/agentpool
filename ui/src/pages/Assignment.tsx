// ui/src/pages/Assignment.tsx
import { useState, useMemo, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import type { ValueChainNode, StakeholderAssignment, Stakeholder } from '../types'

type NodeKey = string

function nk(level: string, label: string): NodeKey {
  return `${level}:${label}`
}

function TreeNode({
  node,
  depth,
  selected,
  onSelect,
  assignedCounts,
}: {
  node: ValueChainNode
  depth: number
  selected: NodeKey | null
  onSelect: (k: NodeKey) => void
  assignedCounts: Record<NodeKey, number>
}) {
  const [open, setOpen] = useState(true)
  const key = nk(node.level, node.label)
  const count = assignedCounts[key] ?? 0
  const isSelected = selected === key
  const hasChildren = (node.children?.length ?? 0) > 0

  return (
    <div>
      <button
        onClick={() => { onSelect(key); if (hasChildren) setOpen((o) => !o) }}
        className={`w-full text-left px-2 py-1.5 rounded text-sm flex items-center gap-2 transition-colors ${
          isSelected ? 'bg-brand/10 text-teal-700' : 'hover:bg-gray-50 text-gray-700'
        } ${count === 0 ? 'border-l-2 border-amber-500' : 'border-l-2 border-transparent'}`}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
      >
        <span className="w-3 text-gray-400 text-xs flex-shrink-0">
          {hasChildren ? (open ? '▼' : '▶') : ''}
        </span>
        <span className="flex-1 text-left truncate">{node.label}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded-full flex-shrink-0 ${
            count === 0
              ? 'bg-amber-100 text-amber-700'
              : 'bg-brand/10 text-teal-700'
          }`}
        >
          {count}
        </span>
      </button>
      {open &&
        node.children?.map((child) => (
          <TreeNode
            key={nk(child.level, child.label)}
            node={child}
            depth={depth + 1}
            selected={selected}
            onSelect={onSelect}
            assignedCounts={assignedCounts}
          />
        ))}
    </div>
  )
}

export default function Assignment() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()

  // Find the latest awaiting_assignment run
  const { data: runs = [] } = useQuery({
    queryKey: ['runs', slug],
    queryFn: () => projectsApi.listRuns(slug!),
    enabled: !!slug,
  })

  const run = runs.find((r) => r.status === 'awaiting_assignment')
  const runId = run?.id

  const { data, isLoading } = useQuery({
    queryKey: ['assignment', slug, runId],
    queryFn: () => projectsApi.getAssignment(slug!, runId!),
    enabled: !!slug && !!runId,
  })

  const [selectedNode, setSelectedNode] = useState<NodeKey | null>(null)
  const [pending, setPending] = useState<StakeholderAssignment[]>([])
  const [search, setSearch] = useState('')

  // Initialise pending from loaded data
  const [initialised, setInitialised] = useState(false)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (data && !initialised) {
      setPending(data.assignments.map((a) => ({ stakeholder_id: a.stakeholder_id, level: a.level, node_label: a.node_label })))
      setInitialised(true)
    }
  }, [data, initialised])

  const assignedCounts = useMemo(() => {
    const counts: Record<NodeKey, number> = {}
    pending.forEach((a) => {
      const key = nk(a.level, a.node_label)
      counts[key] = (counts[key] ?? 0) + 1
    })
    return counts
  }, [pending])

  const filteredStakeholders = useMemo(() => {
    if (!data) return []
    const q = search.toLowerCase()
    return data.stakeholders.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.job_title.toLowerCase().includes(q) ||
        s.organisation.toLowerCase().includes(q),
    )
  }, [data, search])

  function toggleAssignment(stakeholder: Stakeholder) {
    if (!selectedNode) return
    const [level, ...rest] = selectedNode.split(':')
    const node_label = rest.join(':')
    const exists = pending.some(
      (a) => a.stakeholder_id === stakeholder.id && a.level === level && a.node_label === node_label,
    )
    if (exists) {
      setPending((p) =>
        p.filter(
          (a) =>
            !(a.stakeholder_id === stakeholder.id && a.level === level && a.node_label === node_label),
        ),
      )
    } else {
      setPending((p) => [...p, { stakeholder_id: stakeholder.id, level, node_label }])
    }
  }

  function isAssignedToSelected(stakeholder: Stakeholder): boolean {
    if (!selectedNode) return false
    const [level, ...rest] = selectedNode.split(':')
    const node_label = rest.join(':')
    return pending.some(
      (a) => a.stakeholder_id === stakeholder.id && a.level === level && a.node_label === node_label,
    )
  }

  const saveMutation = useMutation({
    mutationFn: () => projectsApi.saveAssignment(slug!, runId!, pending),
  })
  const advanceMutation = useMutation({
    mutationFn: () => projectsApi.advanceOrchestrationRun(slug!, runId!),
  })

  async function handleConfirm() {
    if (!runId) return
    await saveMutation.mutateAsync()
    await advanceMutation.mutateAsync()
    navigate(`/${slug}/runs`)
  }

  // Guard: redirect if no awaiting_assignment run
  if (!isLoading && !runId) {
    navigate(`/${slug}/runs`, { replace: true })
    return null
  }

  const totalNodes = countNodes(data?.value_chain_tree ?? [])
  const assignedNodes = Object.keys(assignedCounts).length
  const totalStakeholders = new Set(pending.map((a) => a.stakeholder_id)).size

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Stakeholder Assignment</h2>
        <span className="text-sm text-gray-500">
          {assignedNodes} of {totalNodes} nodes assigned · {totalStakeholders} stakeholder
          {totalStakeholders !== 1 ? 's' : ''} assigned
        </span>
      </div>

      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}

      {!isLoading && data && (
        <>
          {data.value_chain_tree.length === 0 && (
            <p className="text-sm text-amber-400">
              Value chain data not yet available. The mapping crew must complete before assigning
              stakeholders.
            </p>
          )}

          <div className="flex gap-4 h-[calc(100vh-220px)]">
            {/* Left panel — value chain tree */}
            <div className="w-1/2 bg-surface-card rounded-xl overflow-y-auto p-3">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-2 px-2">
                Value Chain
              </p>
              {data.value_chain_tree.map((node) => (
                <TreeNode
                  key={nk(node.level, node.label)}
                  node={node}
                  depth={0}
                  selected={selectedNode}
                  onSelect={setSelectedNode}
                  assignedCounts={assignedCounts}
                />
              ))}
            </div>

            {/* Right panel — stakeholder roster */}
            <div className="w-1/2 bg-surface-card rounded-xl overflow-y-auto p-3 flex flex-col gap-3">
              <p className="text-xs text-gray-400 uppercase tracking-wide">
                Stakeholders
                {selectedNode && (
                  <span className="ml-2 text-brand normal-case">
                    — assigning to: {selectedNode.split(':').slice(1).join(':')}
                  </span>
                )}
              </p>
              <input
                type="text"
                placeholder="Search name, title, org…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full bg-white text-gray-900 text-sm rounded-lg px-3 py-2 border border-gray-200 focus:outline-none focus:border-brand"
              />
              <div className="flex-1 overflow-y-auto space-y-1">
                {filteredStakeholders.map((s) => {
                  const assigned = isAssignedToSelected(s)
                  const totalAssignments = pending.filter((a) => a.stakeholder_id === s.id).length
                  return (
                    <button
                      key={s.id}
                      onClick={() => toggleAssignment(s)}
                      disabled={!selectedNode}
                      className={`w-full text-left px-3 py-2 rounded-lg text-sm flex items-center gap-3 transition-colors ${
                        assigned
                          ? 'bg-brand/10 text-teal-700'
                          : selectedNode
                          ? 'hover:bg-gray-50 text-gray-700'
                          : 'text-gray-400 cursor-default'
                      }`}
                    >
                      <span className="w-4 text-teal-400">{assigned ? '✓' : ''}</span>
                      <span className="flex-1 truncate font-medium">{s.name}</span>
                      <span className="text-xs text-gray-400 truncate">
                        {s.job_title} · {s.organisation}
                      </span>
                      {totalAssignments > 0 && (
                        <span className="text-xs bg-brand/10 text-teal-700 px-1.5 py-0.5 rounded-full">
                          {totalAssignments}
                        </span>
                      )}
                    </button>
                  )
                })}
                {filteredStakeholders.length === 0 && (
                  <p className="text-sm text-gray-400 px-2">No stakeholders match.</p>
                )}
              </div>
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              onClick={handleConfirm}
              disabled={pending.length === 0 || saveMutation.isPending || advanceMutation.isPending}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-teal-600 hover:bg-teal-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {saveMutation.isPending || advanceMutation.isPending
                ? 'Saving…'
                : 'Confirm Assignments & Begin Interviews'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function countNodes(tree: ValueChainNode[]): number {
  let count = 0
  for (const node of tree) {
    count += 1
    if (node.children) count += countNodes(node.children)
  }
  return count
}
