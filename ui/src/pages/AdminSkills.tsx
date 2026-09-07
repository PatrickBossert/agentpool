// ui/src/pages/AdminSkills.tsx
import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, Check, X, Download, Upload, BookOpen, Clock, Sprout, RotateCcw,
  Repeat, ChevronDown, ChevronRight, Globe,
} from 'lucide-react'
import { skillsApi, type AgentSkill } from '../api/skills'
import { describeError } from '../utils/describeError'
import { CREW_AGENTS } from '../components/agentStatus'

const ALL_AGENTS = Array.from(
  new Set(Object.values(CREW_AGENTS).flat()),
).sort()

const SOURCE_LABEL: Record<string, string> = {
  manual:   'Manual',
  baseline: 'Factory default',
  import:   'Imported',
  review:   'Revision review',
  chat:     'Agent chat',
  // Written by `propose_skill` when an agent generalises the correction it has just made in
  // response to a send-back. Without this key the card showed the raw column value.
  revision: 'Proposed after a revision',
}

function AgentPill({ name }: { name: string }) {
  return (
    <span className="inline-block px-2 py-0.5 rounded-full bg-teal-50 border border-teal-200 text-teal-700 text-[10px] font-semibold">
      {name}
    </span>
  )
}

function AgentSelector({
  value,
  onChange,
}: {
  value: string[]
  onChange: (agents: string[]) => void
}) {
  function toggle(agent: string) {
    onChange(
      value.includes(agent)
        ? value.filter(a => a !== agent)
        : [...value, agent],
    )
  }
  return (
    <div className="border border-gray-200 rounded-lg p-2 max-h-40 overflow-y-auto space-y-0.5">
      {ALL_AGENTS.map(a => (
        <label key={a} className="flex items-center gap-2 cursor-pointer hover:bg-gray-50 rounded px-1 py-0.5">
          <input
            type="checkbox"
            checked={value.includes(a)}
            onChange={() => toggle(a)}
            className="rounded border-gray-300 text-teal-600 focus:ring-teal-500"
          />
          <span className="text-xs text-gray-700">{a}</span>
        </label>
      ))}
    </div>
  )
}

function FlagCard({ reason, suggestion }: { reason: string; suggestion: string | null }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 space-y-1">
      <p className="text-[10px] font-bold text-amber-700 uppercase tracking-widest flex items-center gap-1">
        <AlertTriangle size={10} /> Client-specific content detected
      </p>
      <p className="text-xs text-amber-800 leading-relaxed">{reason}</p>
      {suggestion && (
        <div className="mt-1.5 pt-1.5 border-t border-amber-200">
          <p className="text-[10px] text-amber-600 font-semibold mb-0.5">Suggested reword:</p>
          <p className="text-xs text-amber-700 italic leading-relaxed">{suggestion}</p>
        </div>
      )}
    </div>
  )
}

/** "Seen once" / "Seen 3 times" - the count the queue is ordered by, in words. */
function occurrenceLabel(occurrences: number): string {
  const n = Math.max(1, occurrences || 1)
  return n === 1 ? 'Seen once' : `Seen ${n} times`
}

/**
 * The evidence behind the count, fetched only when a reviewer asks for it.
 *
 * A count on its own says how strong the signal is; it does not say what the signal is made
 * of. The occurrences carry the engagement, the output that was corrected, and the wording
 * the agent used that time - which is how a reviewer tells one rule recurring from an agent
 * repeating itself about one script. Loaded on disclosure rather than with the list, so a
 * queue of twenty proposals is still one request.
 */
function EvidencePanel({ skill }: { skill: AgentSkill }) {
  const [open, setOpen] = useState(false)
  const { data: occurrences = [], isLoading, error } = useQuery({
    queryKey: ['skills', 'occurrences', skill.id],
    queryFn: () => skillsApi.occurrences(skill.id),
    enabled: open,
  })

  return (
    <div className="rounded-lg border border-gray-200 bg-surface px-3 py-2">
      <button
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-700 hover:text-gray-900 transition-colors"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        {open ? 'Hide the evidence' : 'Show the evidence'}
      </button>

      {open && (
        <div className="mt-2 space-y-2">
          {isLoading && <p className="text-[11px] text-gray-600">Loading…</p>}
          {error && (
            <p role="alert" className="text-[11px] text-red-600">
              {describeError(error, 'Could not load where this rule came from.')}
            </p>
          )}
          {!isLoading && !error && occurrences.length === 0 && (
            <p className="text-[11px] text-gray-600">
              No sightings recorded. This skill predates the proposal path, or was written by hand.
            </p>
          )}
          {occurrences.map(o => (
            <div key={o.id} className="border-l-2 border-brand-light pl-2.5 space-y-0.5">
              <p className="text-[10px] font-semibold text-gray-700">
                {o.source_project || 'Engagement not recorded'}
                {o.source_ref && ` · ${o.source_ref}`}
                {o.proposed_by_agent && ` · ${o.proposed_by_agent}`}
                {o.created_at && ` · ${o.created_at.slice(0, 10)}`}
              </p>
              <p className="text-[11px] text-gray-600 leading-relaxed italic">{o.description}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function EditableSkillCard({
  skill,
  onApprove,
  onReject,
}: {
  skill: AgentSkill
  onApprove: (id: number, name: string, description: string, agents: string[]) => void
  onReject: (id: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(skill.name)
  const [description, setDescription] = useState(skill.description)
  const [agents, setAgents] = useState(skill.agents)

  // The consequence sentence is bound to the Approve button by `aria-describedby`, not left
  // beside it. CLAUDE.md records a note asserted per section satisfying every control in that
  // section: proximity is not association, and an association the DOM holds is one a test can
  // read back from the button rather than infer from the layout.
  const noteId = `skill-${skill.id}-approve-consequence`
  const holders = (editing ? agents : skill.agents)
  const agentPhrase = holders.length > 0 ? holders.join(', ') : 'the agent it is assigned to'
  const origin = skill.source_project || 'the engagement it came from'

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 space-y-1.5">
          <div className="flex flex-wrap gap-1">
            {(editing ? agents : skill.agents).map(a => <AgentPill key={a} name={a} />)}
            {(editing ? agents : skill.agents).length === 0 && (
              <span className="text-[10px] text-gray-500 italic">No agents assigned</span>
            )}
          </div>
          {editing ? (
            <input
              className="w-full border border-gray-300 rounded-lg px-2 py-1 text-sm font-semibold text-gray-800 mt-1 focus:outline-none focus:ring-2 focus:ring-teal-400"
              value={name}
              onChange={e => setName(e.target.value)}
            />
          ) : (
            <p className="text-sm font-semibold text-gray-800">{name}</p>
          )}
        </div>
        <span className="text-[10px] text-gray-500 whitespace-nowrap flex-shrink-0">
          {skill.created_at.slice(0, 10)}
        </span>
      </div>

      {editing ? (
        <textarea
          className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs text-gray-700 leading-relaxed resize-none focus:outline-none focus:ring-2 focus:ring-teal-400"
          value={description}
          onChange={e => setDescription(e.target.value)}
          rows={3}
        />
      ) : (
        <p className="text-xs text-gray-600 leading-relaxed">{description}</p>
      )}

      {editing && (
        <div className="space-y-1">
          <p className="text-[10px] font-semibold text-gray-700 uppercase tracking-widest">Assign to agents</p>
          <AgentSelector value={agents} onChange={setAgents} />
        </div>
      )}

      {skill.flag_reason && !editing && (
        <FlagCard reason={skill.flag_reason} suggestion={skill.flag_suggestion} />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 rounded-full border border-brand/40 bg-brand/15 px-2 py-0.5 text-[10px] font-semibold text-gray-800">
          <Repeat size={10} /> {occurrenceLabel(skill.occurrences)}
        </span>
        {skill.proposed_by_agent && (
          <span className="text-[10px] text-gray-500">
            Proposed by {skill.proposed_by_agent}
            {skill.source_ref && ` on ${skill.source_ref}`}
          </span>
        )}
      </div>

      {!editing && <EvidencePanel skill={skill} />}

      <p
        id={noteId}
        className="flex items-start gap-1.5 rounded-lg border border-brand/40 bg-brand/10 px-3 py-2 text-[11px] text-gray-800 leading-relaxed"
      >
        <Globe size={12} className="mt-0.5 flex-shrink-0 text-brand-dark" />
        <span>
          Approving is a change to {agentPhrase} on <strong>every engagement</strong>, not only{' '}
          {origin}. The rule joins that agent&rsquo;s instructions on its next run everywhere.
          Rejecting leaves the instructions as they are.
        </span>
      </p>

      <div className="flex items-center gap-2 justify-between">
        <span className="text-[10px] text-gray-500">
          {SOURCE_LABEL[skill.source] ?? skill.source}
          {skill.source_project && ` · ${skill.source_project}`}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setEditing(e => !e)}
            className="text-xs text-gray-600 hover:text-gray-800 transition-colors px-2 py-1 rounded"
          >
            {editing ? 'Cancel edit' : 'Edit'}
          </button>
          <button
            onClick={() => onReject(skill.id)}
            className="flex items-center gap-1 text-xs text-red-400 hover:text-red-600 transition-colors px-2 py-1 rounded border border-red-200 hover:border-red-300"
          >
            <X size={11} /> Reject
          </button>
          <button
            onClick={() => onApprove(skill.id, name, description, agents)}
            aria-describedby={noteId}
            className="flex items-center gap-1 text-xs text-white bg-brand-dark hover:bg-brand transition-colors px-3 py-1 rounded font-semibold"
          >
            <Check size={11} /> Approve everywhere
          </button>
        </div>
      </div>
    </div>
  )
}

function LibrarySkillCard({
  skill,
  onEdit,
  onDelete,
}: {
  skill: AgentSkill
  onEdit: (id: number, name: string, description: string, agents: string[]) => void
  onDelete: (id: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(skill.name)
  const [description, setDescription] = useState(skill.description)
  const [agents, setAgents] = useState(skill.agents)

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 space-y-1.5">
          <div className="flex flex-wrap gap-1">
            {(editing ? agents : skill.agents).map(a => <AgentPill key={a} name={a} />)}
            {(editing ? agents : skill.agents).length === 0 && (
              <span className="text-[10px] text-gray-500 italic">Unassigned</span>
            )}
          </div>
          {editing ? (
            <input
              className="w-full border border-gray-300 rounded-lg px-2 py-1 text-sm font-semibold text-gray-800 mt-1 focus:outline-none focus:ring-2 focus:ring-teal-400"
              value={name}
              onChange={e => setName(e.target.value)}
            />
          ) : (
            <p className="text-sm font-semibold text-gray-800">{name}</p>
          )}
        </div>
        {!editing && skill.source === 'baseline' && (
          <span className="text-[10px] text-gray-500 whitespace-nowrap flex-shrink-0 mt-0.5">
            Factory default
          </span>
        )}
      </div>

      {editing ? (
        <>
          <textarea
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs text-gray-700 leading-relaxed resize-none focus:outline-none focus:ring-2 focus:ring-teal-400"
            value={description}
            onChange={e => setDescription(e.target.value)}
            rows={3}
          />
          <div className="space-y-1">
            <p className="text-[10px] font-semibold text-gray-700 uppercase tracking-widest">Assign to agents</p>
            <AgentSelector value={agents} onChange={setAgents} />
          </div>
        </>
      ) : (
        <p className="text-xs text-gray-600 leading-relaxed">{description}</p>
      )}

      <div className="flex items-center gap-2 justify-end">
        {editing ? (
          <>
            <button
              onClick={() => { setEditing(false); setName(skill.name); setDescription(skill.description); setAgents(skill.agents) }}
              className="text-xs text-gray-600 hover:text-gray-800 px-2 py-1 rounded"
            >
              Cancel
            </button>
            <button
              onClick={() => { onEdit(skill.id, name, description, agents); setEditing(false) }}
              className="text-xs text-white bg-teal-600 hover:bg-teal-700 px-3 py-1 rounded font-semibold"
            >
              Save
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => setEditing(true)}
              className="text-xs text-gray-600 hover:text-gray-800 px-2 py-1 rounded transition-colors"
            >
              Edit
            </button>
            <button
              onClick={() => { if (confirm(`Delete skill "${skill.name}"?`)) onDelete(skill.id) }}
              className="text-xs text-red-500 hover:text-red-700 px-2 py-1 rounded transition-colors"
            >
              Delete
            </button>
          </>
        )}
      </div>
    </div>
  )
}

export default function AdminSkills() {
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState<'queue' | 'library'>('queue')
  const [libraryAgent, setLibraryAgent] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { data: pending = [], isLoading: loadingQueue } = useQuery({
    queryKey: ['skills', 'pending'],
    queryFn: () => skillsApi.list({ status: 'pending' }),
  })

  const { data: approved = [], isLoading: loadingLibrary } = useQuery({
    queryKey: ['skills', 'approved'],
    queryFn: () => skillsApi.list({ status: 'approved' }),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof skillsApi.update>[1] }) =>
      skillsApi.update(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['skills'] }),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => skillsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['skills'] }),
  })

  const seedMut = useMutation({
    mutationFn: (force: boolean) => skillsApi.seed(force),
    onSuccess: (data, force) => {
      qc.invalidateQueries({ queryKey: ['skills'] })
      alert(force
        ? `Force-reseeded baseline skills. ${data.seeded} skills written.`
        : `Seeded ${data.seeded} new factory default skills.`)
    },
  })

  function handleApprove(id: number, name: string, description: string, agents: string[]) {
    updateMut.mutate({ id, data: { status: 'approved', name, description, agents } })
  }

  function handleReject(id: number) {
    updateMut.mutate({ id, data: { status: 'rejected' } })
  }

  function handleEdit(id: number, name: string, description: string, agents: string[]) {
    updateMut.mutate({ id, data: { name, description, agents } })
  }

  async function handleExport() {
    const data = await skillsApi.exportSkills()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'agent_skills_export.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = async (ev) => {
      try {
        const items = JSON.parse(ev.target?.result as string)
        const result = await skillsApi.importSkills(items)
        qc.invalidateQueries({ queryKey: ['skills'] })
        alert(`Imported ${result.imported} skills. ${result.skipped} already existed.`)
      } catch {
        alert('Invalid JSON file.')
      }
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
    reader.readAsText(file)
  }

  const filteredApproved = libraryAgent
    ? approved.filter(s => s.agents.includes(libraryAgent))
    : approved

  return (
    <div className="min-h-screen bg-surface p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-primary">Agent Skills Library</h1>
          <p className="text-sm text-gray-600 mt-0.5">
            Review suggested skills, manage agent assignments, and export for new instances.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => seedMut.mutate(false)}
            disabled={seedMut.isPending}
            className="flex items-center gap-1.5 text-xs text-gray-700 hover:text-gray-900 border border-gray-300 hover:border-gray-400 px-3 py-1.5 rounded-lg transition-colors"
          >
            <Sprout size={13} />
            {seedMut.isPending ? 'Seeding…' : 'Seed defaults'}
          </button>
          <button
            onClick={() => {
              if (confirm('This will replace all baseline skills with the current factory defaults. Continue?'))
                seedMut.mutate(true)
            }}
            disabled={seedMut.isPending}
            className="flex items-center gap-1.5 text-xs text-gray-700 hover:text-gray-900 border border-gray-300 hover:border-gray-400 px-3 py-1.5 rounded-lg transition-colors"
          >
            <RotateCcw size={13} /> Reseed baseline
          </button>
          <button
            onClick={handleExport}
            className="flex items-center gap-1.5 text-xs text-gray-700 hover:text-gray-900 border border-gray-300 hover:border-gray-400 px-3 py-1.5 rounded-lg transition-colors"
          >
            <Download size={13} /> Export JSON
          </button>
          <label className="flex items-center gap-1.5 text-xs text-gray-700 hover:text-gray-900 border border-gray-300 hover:border-gray-400 px-3 py-1.5 rounded-lg transition-colors cursor-pointer">
            <Upload size={13} /> Import JSON
            <input
              ref={fileInputRef}
              type="file"
              accept=".json"
              className="hidden"
              onChange={handleImportFile}
            />
          </label>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        <button
          onClick={() => setActiveTab('queue')}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'queue'
              ? 'text-teal-700 border-b-2 border-teal-600 -mb-px'
              : 'text-gray-600 hover:text-gray-800'
          }`}
        >
          <Clock size={14} />
          Review queue
          {pending.length > 0 && (
            <span className="ml-1 bg-amber-100 text-amber-700 text-[10px] font-bold px-1.5 py-0.5 rounded-full">
              {pending.length}
            </span>
          )}
        </button>
        <button
          onClick={() => setActiveTab('library')}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'library'
              ? 'text-teal-700 border-b-2 border-teal-600 -mb-px'
              : 'text-gray-600 hover:text-gray-800'
          }`}
        >
          <BookOpen size={14} />
          Library
          <span className="ml-1 text-[10px] text-gray-500">{approved.length}</span>
        </button>
      </div>

      {/* Queue tab.
          The order is the server's - GET /admin/skills sends the queue occurrences-descending,
          so a rule an agent has proposed three times arrives above one proposed once. Nothing
          here re-sorts it. Two places deciding one ordering is how they come to disagree, and
          the page is not the half holding the count. */}
      {activeTab === 'queue' && (
        <div className="space-y-3">
          {updateMut.isError && (
            <p
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
            >
              {describeError(updateMut.error, 'Could not update the skill. Please try again.')}
            </p>
          )}
          {loadingQueue ? (
            <p className="text-sm text-gray-600 text-center py-8">Loading…</p>
          ) : pending.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-12 text-center">
              <div className="w-10 h-10 rounded-full bg-green-50 flex items-center justify-center">
                <Check size={18} className="text-green-600" />
              </div>
              <p className="text-sm text-gray-600">No skills awaiting review.</p>
            </div>
          ) : (
            pending.map(skill => (
              <EditableSkillCard
                key={skill.id}
                skill={skill}
                onApprove={handleApprove}
                onReject={handleReject}
              />
            ))
          )}
        </div>
      )}

      {/* Library tab */}
      {activeTab === 'library' && (
        <div className="space-y-4">
          {/* Filter */}
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-700 font-medium">Filter by agent:</label>
            <select
              value={libraryAgent}
              onChange={e => setLibraryAgent(e.target.value)}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-700 focus:outline-none focus:ring-2 focus:ring-teal-400"
            >
              <option value="">All agents</option>
              {ALL_AGENTS.map(a => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </div>

          {loadingLibrary ? (
            <p className="text-sm text-gray-600 text-center py-8">Loading…</p>
          ) : filteredApproved.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-12 text-center">
              <p className="text-sm text-gray-600">No approved skills yet. Seed the defaults or approve queue items.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3">
              {filteredApproved.map(skill => (
                <LibrarySkillCard
                  key={skill.id}
                  skill={skill}
                  onEdit={handleEdit}
                  onDelete={(id) => deleteMut.mutate(id)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
