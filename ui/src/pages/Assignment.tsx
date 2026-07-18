// ui/src/pages/Assignment.tsx
import { useState, useMemo, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { ChevronDown, ChevronRight, GripVertical, X } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { stakeholdersApi, stakeholderNodeAssignmentsApi, projectsApi } from '../api/endpoints'
import type { Stakeholder, ValueChainRegistryActivity } from '../types'

// node_key = "L0:Governance" | "L1:Some Label" | "L2:Sub Section" | "L3:Activity"
type NodeKey = string

interface TreeNode {
  key: NodeKey
  label: string
  level: 'L0' | 'L1' | 'L2' | 'L3'
  children: TreeNode[]
  virtual?: boolean
}

interface LocalAssignment {
  stakeholder_id: number
  node_key: NodeKey
}

const L0_NODE: TreeNode = {
  key: 'L0:Governance',
  label: 'Governance',
  level: 'L0',
  children: [],
  virtual: true,
}

const LEVEL_BADGE: Record<string, string> = {
  L0: 'bg-purple-100 text-purple-700',
  L1: 'bg-brand/10 text-teal-700',
  L2: 'bg-gray-100 text-gray-600',
  L3: 'bg-gray-50 text-gray-500 text-[10px]',
}

function buildTree(activities: ValueChainRegistryActivity[]): TreeNode[] {
  const active = activities.filter(a => a.active)
  const nodeMap: Record<string, TreeNode> = {}

  active.forEach(a => {
    nodeMap[a.id] = {
      key: `${a.level}:${a.label}`,
      label: a.label,
      level: a.level as 'L1' | 'L2' | 'L3',
      children: [],
    }
  })

  const roots: TreeNode[] = []
  active.forEach(a => {
    if (a.parent_id && nodeMap[a.parent_id]) {
      nodeMap[a.parent_id].children.push(nodeMap[a.id])
    } else if (!a.parent_id) {
      roots.push(nodeMap[a.id])
    }
  })

  return [L0_NODE, ...roots]
}

// ── TreeNode component ────────────────────────────────────────────────────────

function TreeNodeRow({
  node,
  depth,
  assignments,
  stakeholders,
  draggingId,
  onDrop,
  onRemove,
}: {
  node: TreeNode
  depth: number
  assignments: LocalAssignment[]
  stakeholders: Stakeholder[]
  draggingId: number | null
  onDrop: (stakeholderId: number, nodeKey: NodeKey) => void
  onRemove: (stakeholderId: number, nodeKey: NodeKey) => void
}) {
  const [open, setOpen] = useState(depth < 2)
  const [isDragOver, setIsDragOver] = useState(false)

  const assignedHere = assignments.filter(a => a.node_key === node.key)
  const assignedStakeholders = assignedHere
    .map(a => stakeholders.find(s => s.id === a.stakeholder_id))
    .filter((s): s is Stakeholder => s !== undefined)

  const hasChildren = node.children.length > 0

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
    setIsDragOver(true)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setIsDragOver(false)
    const id = Number(e.dataTransfer.getData('stakeholderId'))
    if (id) onDrop(id, node.key)
  }

  const paddingLeft = 8 + depth * 16

  return (
    <div>
      <div
        onDragOver={handleDragOver}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        className={`rounded-lg border transition-colors ${
          isDragOver ? 'border-brand bg-brand/5' : 'border-transparent'
        }`}
        style={{ marginLeft: paddingLeft }}
      >
        {/* Node row */}
        <div
          className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg cursor-pointer hover:bg-gray-50 ${
            node.level === 'L0' ? 'bg-purple-50/50' : ''
          }`}
          onClick={() => hasChildren && setOpen(o => !o)}
        >
          <span className="w-3.5 text-gray-300 flex-shrink-0">
            {hasChildren ? (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : null}
          </span>
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded flex-shrink-0 ${LEVEL_BADGE[node.level]}`}>
            {node.level}
          </span>
          <span className="text-sm text-gray-700 flex-1 truncate">{node.label}</span>
          {assignedHere.length > 0 && (
            <span className="text-[10px] bg-brand/10 text-teal-700 px-1.5 py-0.5 rounded-full flex-shrink-0">
              {assignedHere.length}
            </span>
          )}
        </div>

        {/* Assigned stakeholder chips */}
        {assignedStakeholders.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-2 pb-2">
            {assignedStakeholders.map(s => (
              <span
                key={s.id}
                className="flex items-center gap-1 text-[10px] bg-white border border-gray-200 text-gray-700 rounded-full px-2 py-0.5"
              >
                {s.level && (
                  <span className={`text-[9px] font-bold ${LEVEL_BADGE[s.level]?.split(' ')[1] ?? 'text-gray-500'}`}>
                    {s.level}
                  </span>
                )}
                {s.name}
                <button
                  onClick={(e) => { e.stopPropagation(); onRemove(s.id, node.key) }}
                  className="text-gray-400 hover:text-red-400 transition-colors"
                  aria-label={`Remove ${s.name}`}
                >
                  <X size={9} />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Drop hint when dragging */}
        {isDragOver && (
          <div className="px-3 pb-2 text-[10px] text-brand font-medium">
            Drop to assign here
          </div>
        )}
      </div>

      {/* Children */}
      {open && node.children.map(child => (
        <TreeNodeRow
          key={child.key}
          node={child}
          depth={depth + 1}
          assignments={assignments}
          stakeholders={stakeholders}
          draggingId={draggingId}
          onDrop={onDrop}
          onRemove={onRemove}
        />
      ))}
    </div>
  )
}

// ── Stakeholder drag card ─────────────────────────────────────────────────────

function StakeholderCard({
  stakeholder,
  assignmentCount,
  onDragStart,
  onDragEnd,
  isDragging,
}: {
  stakeholder: Stakeholder
  assignmentCount: number
  onDragStart: () => void
  onDragEnd: () => void
  isDragging: boolean
}) {
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('stakeholderId', String(stakeholder.id))
        e.dataTransfer.effectAllowed = 'copy'
        onDragStart()
      }}
      onDragEnd={onDragEnd}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-grab active:cursor-grabbing select-none transition-all ${
        isDragging
          ? 'border-brand/30 bg-brand/5 opacity-60'
          : 'border-gray-100 bg-white hover:border-brand/40 hover:shadow-sm'
      }`}
    >
      <GripVertical size={12} className="text-gray-300 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          {stakeholder.level && (
            <span className={`text-[9px] font-bold px-1 py-0.5 rounded ${LEVEL_BADGE[stakeholder.level]}`}>
              {stakeholder.level}
            </span>
          )}
          <span className="text-sm font-medium text-gray-800 truncate">{stakeholder.name}</span>
        </div>
        {(stakeholder.job_title || stakeholder.entity) && (
          <p className="text-[10px] text-gray-400 truncate">
            {[stakeholder.job_title, stakeholder.entity].filter(Boolean).join(' · ')}
          </p>
        )}
      </div>
      {assignmentCount > 0 && (
        <span className="text-[10px] bg-brand/10 text-teal-700 px-1.5 py-0.5 rounded-full flex-shrink-0">
          {assignmentCount}
        </span>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Assignment() {
  const { slug } = useParams<{ slug: string }>()
  const qc = useQueryClient()
  const [draggingId, setDraggingId] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [assignments, setAssignments] = useState<LocalAssignment[]>([])
  const [initialised, setInitialised] = useState(false)
  const saveRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { data: stakeholders = [], isLoading: loadingStakeholders } = useQuery<Stakeholder[]>({
    queryKey: ['stakeholders', slug],
    queryFn: () => stakeholdersApi.list(slug!),
    enabled: !!slug,
  })

  const { data: registry, isLoading: loadingRegistry } = useQuery({
    queryKey: ['value-chain-registry', slug],
    queryFn: () => projectsApi.getValueChainRegistry(slug!),
    enabled: !!slug,
    retry: false,
  })

  const { data: savedAssignments = [], isLoading: loadingAssignments } = useQuery({
    queryKey: ['stakeholder-node-assignments', slug],
    queryFn: () => stakeholderNodeAssignmentsApi.list(slug!),
    enabled: !!slug,
  })

  // Find awaiting_assignment run (to keep the "Begin Interviews" path available)
  const { data: runs = [] } = useQuery({
    queryKey: ['runs', slug],
    queryFn: () => projectsApi.listRuns(slug!),
    enabled: !!slug,
  })
  const awaitingRun = runs.find(r => r.status === 'awaiting_assignment')

  const saveMutation = useMutation({
    mutationFn: (items: LocalAssignment[]) =>
      stakeholderNodeAssignmentsApi.save(slug!, items),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stakeholder-node-assignments', slug] })
    },
  })

  const advanceMutation = useMutation({
    mutationFn: (runId: number) => projectsApi.advanceOrchestrationRun(slug!, runId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['runs', slug] })
    },
  })

  // Initialise local state from saved assignments
  useEffect(() => {
    if (!initialised && !loadingAssignments) {
      setAssignments(savedAssignments.map(a => ({
        stakeholder_id: a.stakeholder_id,
        node_key: a.node_key,
      })))
      setInitialised(true)
    }
  }, [savedAssignments, loadingAssignments, initialised])

  function persist(next: LocalAssignment[]) {
    setAssignments(next)
    // Debounce saves to avoid hammering the API on rapid changes
    if (saveRef.current) clearTimeout(saveRef.current)
    saveRef.current = setTimeout(() => {
      saveMutation.mutate(next)
    }, 400)
  }

  function handleDrop(stakeholderId: number, nodeKey: NodeKey) {
    // Prevent duplicate assignment to the same node
    const alreadyAssigned = assignments.some(
      a => a.stakeholder_id === stakeholderId && a.node_key === nodeKey,
    )
    if (alreadyAssigned) return
    persist([...assignments, { stakeholder_id: stakeholderId, node_key: nodeKey }])
  }

  function handleRemove(stakeholderId: number, nodeKey: NodeKey) {
    persist(assignments.filter(
      a => !(a.stakeholder_id === stakeholderId && a.node_key === nodeKey),
    ))
  }

  const tree = useMemo(() => {
    if (!registry?.activities) return [L0_NODE]
    return buildTree(registry.activities)
  }, [registry])

  const filteredStakeholders = useMemo(() => {
    const q = search.toLowerCase()
    const sorted = [...stakeholders].sort((a, b) => {
      const order = { L0: 0, L1: 1, L2: 2, L3: 3, C: 4, '': 5 }
      return (order[a.level] ?? 4) - (order[b.level] ?? 4)
    })
    return q
      ? sorted.filter(s =>
          s.name.toLowerCase().includes(q) ||
          s.job_title.toLowerCase().includes(q) ||
          s.entity.toLowerCase().includes(q),
        )
      : sorted
  }, [stakeholders, search])

  const isLoading = loadingStakeholders || loadingRegistry || loadingAssignments

  const assignedNodeCount = new Set(assignments.map(a => a.node_key)).size
  const assignedStakeholderCount = new Set(assignments.map(a => a.stakeholder_id)).size

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Stakeholder Assignment</h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Drag stakeholders onto value chain nodes. The PMO uses these assignments for review routing and approvals.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {saveMutation.isPending && (
            <span className="text-xs text-gray-400">Saving…</span>
          )}
          {!saveMutation.isPending && assignments.length > 0 && (
            <span className="text-xs text-gray-400">
              {assignedStakeholderCount} stakeholder{assignedStakeholderCount !== 1 ? 's' : ''} across {assignedNodeCount} node{assignedNodeCount !== 1 ? 's' : ''}
            </span>
          )}
          {awaitingRun && (
            <button
              onClick={() => advanceMutation.mutate(awaitingRun.id)}
              disabled={advanceMutation.isPending || assignments.length === 0}
              className="px-3 py-1.5 rounded text-xs font-medium bg-teal-600 hover:bg-teal-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {advanceMutation.isPending ? 'Starting…' : 'Begin Discovery Interviews →'}
            </button>
          )}
        </div>
      </div>

      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}

      {!isLoading && (
        <div className="flex gap-4" style={{ height: 'calc(100vh - 220px)' }}>
          {/* Left: stakeholder roster */}
          <div className="w-72 flex-shrink-0 bg-surface-card rounded-xl flex flex-col">
            <div className="p-3 border-b border-gray-100">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-2">Stakeholders</p>
              <input
                type="text"
                placeholder="Search name, title, entity…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full bg-white text-gray-900 text-sm rounded-lg px-3 py-1.5 border border-gray-200 focus:outline-none focus:border-brand"
              />
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {filteredStakeholders.map(s => (
                <StakeholderCard
                  key={s.id}
                  stakeholder={s}
                  assignmentCount={assignments.filter(a => a.stakeholder_id === s.id).length}
                  isDragging={draggingId === s.id}
                  onDragStart={() => setDraggingId(s.id)}
                  onDragEnd={() => setDraggingId(null)}
                />
              ))}
              {filteredStakeholders.length === 0 && (
                <p className="text-xs text-gray-400 px-2 py-3">No stakeholders found.</p>
              )}
            </div>
          </div>

          {/* Right: value chain tree */}
          <div className="flex-1 bg-surface-card rounded-xl overflow-y-auto p-3">
            <p className="text-xs text-gray-400 uppercase tracking-wide mb-3 px-2">Value Chain</p>
            {!registry && (
              <div className="px-2">
                <p className="text-xs text-amber-500 mb-3">
                  Value chain mapping has not yet completed. Only the L0 Governance node is available until the mapper crew runs.
                </p>
              </div>
            )}
            {tree.map(node => (
              <TreeNodeRow
                key={node.key}
                node={node}
                depth={0}
                assignments={assignments}
                stakeholders={stakeholders}
                draggingId={draggingId}
                onDrop={handleDrop}
                onRemove={handleRemove}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
