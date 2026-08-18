// ui/src/components/tabs/JordanSetupTab.tsx
// Jordan's Setup section: who speaks for which value chain activity.
//
// This is the mapping the Interview Coordinator plans sessions from, and until this shipped
// there was no way to make it. The page that looked like the way - /:slug/assignment - wrote
// `stakeholder_node_assignments`, keyed on 'L2:Some Label', which no agent has ever read;
// the table agents do read, `stakeholder_assignments`, had no writer at all. Both are one
// table now, keyed on the value chain node id, and this is its only door.
//
// It is in a Setup tab because the mapping is configuration, not an event inside a run. The
// old page was reachable only from a run sitting in `awaiting_assignment`, so the work could
// not be done before the first orchestration - which is the defect this fixes.
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ChevronDown, ChevronRight, ExternalLink, Plus, Search, X } from 'lucide-react'

import { projectsApi } from '../../api/endpoints'
import { describeError } from '../../utils/describeError'
import type { Stakeholder, StakeholderAssignment, ValueChainRegistryActivity } from '../../types'

interface TreeNode {
  id: string
  label: string
  level: string
  children: TreeNode[]
}

type Pair = { stakeholder_id: number; node_id: string }

const LEVEL_BADGE: Record<string, string> = {
  L0: 'bg-purple-100 text-purple-700',
  L1: 'bg-brand/10 text-brand',
  L2: 'bg-gray-100 text-gray-600',
  L3: 'bg-gray-50 text-gray-500',
}

/**
 * Every registered id, nested.
 *
 * Two rules, in order, and no third: the registry's own `parent_id`, then - for a node that
 * declares none - the id's own prefix, because the id *is* the spine. That second rule is
 * what puts `0.A` (audit) and `0.S` (corporate services frontline) under `0`, the
 * organisation. They carry no parent_id, and CLAUDE.md names them as the hardest
 * stakeholders to place, so leaving them loose at the top of an 86-node list was the one
 * outcome worth avoiding.
 *
 * Nothing is invented. The page this replaces synthesised a virtual `L0:Governance` node
 * that appeared in no registry, so anything dropped on it was assigned to a node no agent
 * could resolve; `0` is a real registered id with a real label.
 */
export function buildTree(activities: ValueChainRegistryActivity[]): TreeNode[] {
  const active = activities.filter((a) => a.active)
  const byId = new Map<string, TreeNode>()
  active.forEach((a) => byId.set(a.id, { id: a.id, label: a.label, level: a.level, children: [] }))

  const parentOf = new Map<string, string>()
  active.forEach((a) => {
    if (a.parent_id && byId.has(a.parent_id)) {
      parentOf.set(a.id, a.parent_id)
      return
    }
    const cut = a.id.lastIndexOf('.')
    const prefix = cut > 0 ? a.id.slice(0, cut) : ''
    if (prefix && byId.has(prefix)) parentOf.set(a.id, prefix)
  })

  const roots: TreeNode[] = []
  byId.forEach((node, id) => {
    // A malformed registry must not produce an infinitely deep render. Walking to the top
    // costs nothing at this size and turns a cycle into a root rather than a hung tab.
    const seen = new Set<string>([id])
    let cursor = parentOf.get(id)
    while (cursor && !seen.has(cursor)) {
      seen.add(cursor)
      cursor = parentOf.get(cursor)
    }
    const parent = cursor ? undefined : parentOf.get(id)
    if (parent) byId.get(parent)!.children.push(node)
    else roots.push(node)
  })

  const byIdOrder = (a: TreeNode, b: TreeNode) =>
    a.id.localeCompare(b.id, undefined, { numeric: true, sensitivity: 'base' })
  byId.forEach((node) => node.children.sort(byIdOrder))
  return roots.sort(byIdOrder)
}

function flatten(nodes: TreeNode[]): TreeNode[] {
  return nodes.flatMap((n) => [n, ...flatten(n.children)])
}

function key(p: Pair): string {
  return `${p.stakeholder_id}::${p.node_id}`
}

function sameMapping(a: Pair[], b: Pair[]): boolean {
  if (a.length !== b.length) return false
  const left = a.map(key).sort()
  const right = b.map(key).sort()
  return left.every((k, i) => k === right[i])
}

// ── The picker, mounted for one node at a time ────────────────────────────────
//
// One <select> per node would be 86 selects holding 62 options each on the live project.
// This renders for whichever node the user is adding to, and nowhere else.
function StakeholderPicker({
  stakeholders,
  onPick,
  onClose,
}: {
  stakeholders: Stakeholder[]
  onPick: (id: number) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const matches = q
    ? stakeholders.filter((s) =>
        [s.name, s.job_title, s.entity, s.organisation].some((f) => (f ?? '').toLowerCase().includes(q)),
      )
    : stakeholders

  return (
    <div className="mt-1.5 rounded-lg border border-brand/30 bg-white p-2">
      <div className="flex items-center gap-2 mb-1.5">
        <Search size={11} className="text-gray-300 flex-shrink-0" />
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search name, title, entity…"
          aria-label="Search stakeholders to assign"
          className="flex-1 bg-white border border-gray-200 rounded px-2 py-1 text-[11px] text-gray-900 outline-none focus:border-brand"
        />
        <button
          type="button"
          onClick={onClose}
          aria-label="Close the stakeholder picker"
          className="text-gray-300 hover:text-gray-600 transition-colors"
        >
          <X size={12} />
        </button>
      </div>
      <div className="max-h-44 overflow-y-auto space-y-0.5">
        {matches.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => onPick(s.id)}
            // Named for the action rather than left to its text content: a person's name
            // also appears on the chip that removes them, and two controls a click apart
            // that answer to the same name is how a test ends up asserting the wrong one.
            aria-label={`Assign ${s.name}`}
            className="w-full text-left px-2 py-1 rounded hover:bg-brand/5 flex items-center gap-1.5"
          >
            {s.level && (
              <span className={`text-[9px] font-bold px-1 py-0.5 rounded flex-shrink-0 ${LEVEL_BADGE[s.level] ?? 'bg-gray-50 text-gray-500'}`}>
                {s.level}
              </span>
            )}
            <span className="text-[11px] text-gray-800 truncate">{s.name}</span>
            <span className="text-[10px] text-gray-400 truncate">
              {[s.job_title, s.entity].filter(Boolean).join(' · ')}
            </span>
            {s.is_synthetic && (
              <span className="ml-auto text-[9px] text-amber-600 flex-shrink-0">seeded</span>
            )}
          </button>
        ))}
        {matches.length === 0 && (
          <p className="text-[11px] text-gray-400 px-2 py-2">
            Nobody left to assign here.
          </p>
        )}
      </div>
    </div>
  )
}

// ── One node ──────────────────────────────────────────────────────────────────

function NodeRow({
  node,
  depth,
  visible,
  assignments,
  peopleById,
  openIds,
  onToggle,
  pickerNodeId,
  onOpenPicker,
  onAssign,
  onRemove,
}: {
  node: TreeNode
  depth: number
  visible: Set<string>
  assignments: Pair[]
  peopleById: Map<number, Stakeholder>
  openIds: Set<string>
  onToggle: (id: string) => void
  pickerNodeId: string | null
  onOpenPicker: (id: string | null) => void
  onAssign: (stakeholderId: number, nodeId: string) => void
  onRemove: (stakeholderId: number, nodeId: string) => void
}) {
  if (!visible.has(node.id)) return null

  const here = assignments.filter((a) => a.node_id === node.id)
  const assignedHere = here
    .map((a) => peopleById.get(a.stakeholder_id))
    .filter((s): s is Stakeholder => s !== undefined)
  const assignedIds = new Set(here.map((a) => a.stakeholder_id))
  const shownChildren = node.children.filter((c) => visible.has(c.id))
  const isOpen = openIds.has(node.id)

  return (
    <div data-testid={`node-${node.id}`} style={{ marginLeft: depth * 12 }}>
      <div className="flex items-center gap-1.5 py-1">
        <button
          type="button"
          onClick={() => onToggle(node.id)}
          disabled={shownChildren.length === 0}
          aria-label={isOpen ? `Collapse ${node.id}` : `Expand ${node.id}`}
          className="w-3.5 text-gray-300 flex-shrink-0 disabled:opacity-0"
        >
          {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
        <span className={`text-[9px] font-bold px-1 py-0.5 rounded flex-shrink-0 ${LEVEL_BADGE[node.level] ?? 'bg-gray-50 text-gray-500'}`}>
          {node.level}
        </span>
        <span className="text-[10px] font-mono text-gray-400 flex-shrink-0">{node.id}</span>
        <span className="text-[11px] text-gray-700 flex-1 truncate">{node.label}</span>
        {here.length > 0 && (
          <span className="text-[10px] bg-brand/10 text-brand px-1.5 py-0.5 rounded-full flex-shrink-0">
            {here.length}
          </span>
        )}
        <button
          type="button"
          onClick={() => onOpenPicker(pickerNodeId === node.id ? null : node.id)}
          aria-label={`Assign a stakeholder to ${node.id}`}
          className="flex items-center gap-1 text-[10px] text-brand hover:text-brand-dark border border-brand/30 rounded px-1.5 py-0.5 hover:bg-brand/5 flex-shrink-0"
        >
          <Plus size={10} /> Assign
        </button>
      </div>

      {assignedHere.length > 0 && (
        <div className="flex flex-wrap gap-1 pb-1 pl-[4.25rem]">
          {assignedHere.map((s) => (
            <span
              key={s.id}
              className="flex items-center gap-1 text-[10px] bg-white border border-gray-200 text-gray-700 rounded-full px-2 py-0.5"
            >
              {s.name}
              <button
                type="button"
                onClick={() => onRemove(s.id, node.id)}
                aria-label={`Remove ${s.name} from ${node.id}`}
                className="text-gray-400 hover:text-red-500 transition-colors"
              >
                <X size={9} />
              </button>
            </span>
          ))}
        </div>
      )}

      {pickerNodeId === node.id && (
        <div className="pl-[4.25rem] pb-1">
          <StakeholderPicker
            stakeholders={[...peopleById.values()].filter((s) => !assignedIds.has(s.id))}
            onPick={(id) => onAssign(id, node.id)}
            onClose={() => onOpenPicker(null)}
          />
        </div>
      )}

      {isOpen &&
        shownChildren.map((child) => (
          <NodeRow
            key={child.id}
            node={child}
            depth={depth + 1}
            visible={visible}
            assignments={assignments}
            peopleById={peopleById}
            openIds={openIds}
            onToggle={onToggle}
            pickerNodeId={pickerNodeId}
            onOpenPicker={onOpenPicker}
            onAssign={onAssign}
            onRemove={onRemove}
          />
        ))}
    </div>
  )
}

// ── The section ───────────────────────────────────────────────────────────────

export default function JordanSetupTab({ slug }: { slug: string }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Pair[] | null>(null)
  const [query, setQuery] = useState('')
  const [unassignedOnly, setUnassignedOnly] = useState(false)
  const [openIds, setOpenIds] = useState<Set<string>>(new Set())
  const [pickerNodeId, setPickerNodeId] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  const { data: assignmentData, isLoading } = useQuery({
    queryKey: ['assignment', slug],
    queryFn: () => projectsApi.getAssignment(slug),
  })

  // Same key and the same `retry: false` as StakeholderForm's own query - the registry 404s
  // until Alex has run, and two observers of one key must not disagree about retrying.
  const { data: registry } = useQuery({
    queryKey: ['value-chain-registry', slug],
    queryFn: () => projectsApi.getValueChainRegistry(slug),
    retry: false,
  })

  const { data: runs = [] } = useQuery({
    queryKey: ['runs', slug],
    queryFn: () => projectsApi.listRuns(slug),
  })
  const awaitingRun = runs.find((r) => r.status === 'awaiting_assignment')

  const saved: Pair[] = useMemo(
    () =>
      (assignmentData?.assignments ?? []).map((a: StakeholderAssignment) => ({
        stakeholder_id: a.stakeholder_id,
        node_id: a.node_id,
      })),
    [assignmentData],
  )

  // Seeded from the server once, and re-seeded whenever the server's answer changes - which
  // after a save is the mapping just written, so the draft and the stored rows converge
  // rather than the draft being thrown away mid-edit.
  useEffect(() => {
    if (!assignmentData) return
    setDraft((current) => (current === null || sameMapping(current, saved) ? saved : current))
  }, [assignmentData, saved])

  const assignments = draft ?? saved
  const dirty = draft !== null && !sameMapping(draft, saved)

  const save = useMutation({
    mutationFn: (items: Pair[]) => projectsApi.saveAssignment(slug, items),
    onSuccess: () => {
      setSaveError(null)
      queryClient.invalidateQueries({ queryKey: ['assignment', slug] })
    },
    onError: (err) => setSaveError(describeError(err, 'The mapping could not be saved.')),
  })

  const tree = useMemo(() => buildTree(registry?.activities ?? []), [registry])
  const allNodes = useMemo(() => flatten(tree), [tree])
  const knownIds = useMemo(() => new Set(allNodes.map((n) => n.id)), [allNodes])

  const peopleById = useMemo(
    () =>
      new Map<number, Stakeholder>(
        (assignmentData?.stakeholders ?? []).map((s: Stakeholder) => [s.id, s]),
      ),
    [assignmentData],
  )

  const countByNode = useMemo(() => {
    const counts = new Map<string, number>()
    assignments.forEach((a) => counts.set(a.node_id, (counts.get(a.node_id) ?? 0) + 1))
    return counts
  }, [assignments])

  // A node is shown when it matches, or when a descendant does - hiding an ancestor would
  // hide every match beneath it.
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const shown = new Set<string>()
    const walk = (node: TreeNode): boolean => {
      const descendantShown = node.children.map(walk).some(Boolean)
      const matchesQuery = !q || node.id.toLowerCase().includes(q) || node.label.toLowerCase().includes(q)
      const matchesFilter = !unassignedOnly || (countByNode.get(node.id) ?? 0) === 0
      if (descendantShown || (matchesQuery && matchesFilter)) {
        shown.add(node.id)
        return true
      }
      return false
    }
    tree.forEach(walk)
    return shown
  }, [tree, query, unassignedOnly, countByNode])

  // Opened by default: the roots, and every ancestor of an activity somebody is already
  // assigned to. A mapping of eighty-odd rows folded three levels down reads as no mapping
  // at all, and the first thing anyone opening this tab needs to know is what is already
  // there.
  const defaultOpen = useMemo(() => {
    const open = new Set(tree.map((n) => n.id))
    const ancestors = new Map<string, string>()
    const walk = (node: TreeNode) =>
      node.children.forEach((child) => {
        ancestors.set(child.id, node.id)
        walk(child)
      })
    tree.forEach(walk)
    saved.forEach((a) => {
      let cursor = ancestors.get(a.node_id)
      while (cursor && !open.has(cursor)) {
        open.add(cursor)
        cursor = ancestors.get(cursor)
      }
    })
    return open
  }, [tree, saved])

  // Filtering is useless if the matches stay folded away, so a live filter expands the tree.
  const filtering = query.trim() !== '' || unassignedOnly
  const effectiveOpen = useMemo(() => {
    if (filtering) return new Set(allNodes.map((n) => n.id))
    return openIds.size > 0 ? openIds : defaultOpen
  }, [filtering, allNodes, openIds, defaultOpen])

  const toggle = (id: string) =>
    setOpenIds((current) => {
      const next = new Set(current.size > 0 ? current : defaultOpen)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  function assign(stakeholderId: number, nodeId: string) {
    setPickerNodeId(null)
    setDraft((current) => {
      const base = current ?? saved
      if (base.some((a) => a.stakeholder_id === stakeholderId && a.node_id === nodeId)) return base
      return [...base, { stakeholder_id: stakeholderId, node_id: nodeId }]
    })
  }

  function remove(stakeholderId: number, nodeId: string) {
    setDraft((current) =>
      (current ?? saved).filter((a) => !(a.stakeholder_id === stakeholderId && a.node_id === nodeId)),
    )
  }

  const coveredNodes = new Set(assignments.map((a) => a.node_id).filter((id) => knownIds.has(id))).size
  const placedPeople = new Set(assignments.map((a) => a.stakeholder_id))
  const unplaced = [...peopleById.values()].filter((s) => !placedPeople.has(s.id))
  const offRegistry = assignments.filter((a) => !knownIds.has(a.node_id))

  return (
    <div className="space-y-4">
      <p className="text-[11px] text-gray-400 leading-relaxed">
        Who speaks for which value chain activity. Jordan hands this to the Interview
        Coordinator, who plans one session per assignment, so an activity with nobody against
        it is an activity nobody is interviewed about. The mapping is made by hand - job
        titles do not carry enough detail to derive it - and several people on one activity is
        expected rather than a duplicate, frontline and corporate services especially.
      </p>

      {allNodes.length === 0 && (
        <p className="text-[11px] text-amber-600">
          No value chain registry yet. Alex maps the chain first; the activities to assign
          against appear here once he has run.
        </p>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1.5 flex-1 min-w-[12rem]">
          <Search size={12} className="text-gray-300 flex-shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter activities by id or name…"
            aria-label="Filter activities"
            className="flex-1 bg-white border border-gray-200 rounded px-2 py-1 text-xs text-gray-900 outline-none focus:border-brand"
          />
        </div>
        <label className="flex items-center gap-1.5 text-[11px] text-gray-500">
          <input
            type="checkbox"
            checked={unassignedOnly}
            onChange={(e) => setUnassignedOnly(e.target.checked)}
            className="accent-brand"
          />
          Only activities with nobody
        </label>
        <Link
          to={`/${slug}/stakeholders`}
          className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-700"
        >
          <ExternalLink size={10} /> Stakeholders
        </Link>
      </div>

      <div className="rounded-lg border border-gray-100 p-2 max-h-[26rem] overflow-y-auto">
        {tree.map((node) => (
          <NodeRow
            key={node.id}
            node={node}
            depth={0}
            visible={visible}
            assignments={assignments}
            peopleById={peopleById}
            openIds={effectiveOpen}
            onToggle={toggle}
            pickerNodeId={pickerNodeId}
            onOpenPicker={setPickerNodeId}
            onAssign={assign}
            onRemove={remove}
          />
        ))}
        {isLoading && <p className="text-[11px] text-gray-400 px-2 py-2">Loading…</p>}
      </div>

      {offRegistry.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
          <p className="flex items-center gap-1.5 text-[10px] font-bold text-amber-700 uppercase tracking-widest mb-1">
            <AlertTriangle size={11} /> Assigned to activities no longer in the registry
          </p>
          <p className="text-[11px] text-amber-700 mb-1.5">
            The id is kept - ids are a permanent contract - but a retired activity is not
            interviewed. Remove these, or wait for the node to come back.
          </p>
          <div className="flex flex-wrap gap-1">
            {offRegistry.map((a) => (
              <span
                key={key(a)}
                className="flex items-center gap-1 text-[10px] bg-white border border-amber-200 text-amber-800 rounded-full px-2 py-0.5"
              >
                <span className="font-mono">{a.node_id}</span>
                {peopleById.get(a.stakeholder_id)?.name ?? `Stakeholder ${a.stakeholder_id}`}
                <button
                  type="button"
                  onClick={() => remove(a.stakeholder_id, a.node_id)}
                  aria-label={`Remove ${peopleById.get(a.stakeholder_id)?.name ?? a.stakeholder_id} from ${a.node_id}`}
                  className="text-amber-400 hover:text-red-500 transition-colors"
                >
                  <X size={9} />
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      <p className="text-[11px] text-gray-400" data-testid="assignment-coverage">
        {assignments.length} assignment{assignments.length === 1 ? '' : 's'} · {coveredNodes} of{' '}
        {allNodes.length} activities covered · {unplaced.length} of {peopleById.size} people not
        yet placed
      </p>

      {unplaced.length > 0 && (
        <details className="text-[11px] text-gray-500">
          <summary className="cursor-pointer text-gray-400">
            Who is not placed yet ({unplaced.length})
          </summary>
          <ul className="mt-1.5 space-y-0.5">
            {unplaced.map((s) => (
              <li key={s.id} className="flex items-center gap-1.5">
                <span className="text-gray-700">{s.name}</span>
                <span className="text-gray-400">
                  {[s.job_title, s.entity].filter(Boolean).join(' · ')}
                </span>
                {s.is_synthetic && <span className="text-[9px] text-amber-600">seeded</span>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {saveError && <p className="text-[11px] text-red-500">{saveError}</p>}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => save.mutate(assignments)}
          disabled={!dirty || save.isPending}
          className="px-3 py-1.5 bg-brand hover:bg-brand-dark text-white text-xs font-medium rounded disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {save.isPending ? 'Saving…' : 'Save assignments'}
        </button>
        {dirty && !save.isPending && (
          <span className="text-[11px] text-amber-600">Unsaved changes.</span>
        )}
        {!dirty && save.isSuccess && <span className="text-[11px] text-emerald-600">Saved.</span>}

        {awaitingRun && (
          <AdvanceRunButton slug={slug} runId={awaitingRun.id} blocked={dirty} />
        )}
      </div>
    </div>
  )
}

/**
 * The one thing the retired page did that this section still has to offer: a run parked in
 * `awaiting_assignment` is waiting on exactly this mapping, and Runs.tsx links here for it.
 *
 * Refuses while the draft is unsaved, because advancing sends the crew the *stored* mapping
 * and an on-screen edit that never reached the database would be silently ignored.
 */
function AdvanceRunButton({ slug, runId, blocked }: { slug: string; runId: number; blocked: boolean }) {
  const queryClient = useQueryClient()
  const advance = useMutation({
    mutationFn: () => projectsApi.advanceOrchestrationRun(slug, runId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runs', slug] }),
  })

  return (
    <button
      type="button"
      onClick={() => advance.mutate()}
      disabled={blocked || advance.isPending}
      title={blocked ? 'Save the mapping first - the crew reads the stored rows.' : undefined}
      className="px-3 py-1.5 border border-brand/30 text-brand hover:bg-brand/5 text-xs font-medium rounded disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
    >
      {advance.isPending ? 'Starting…' : 'Begin discovery interviews'}
    </button>
  )
}
