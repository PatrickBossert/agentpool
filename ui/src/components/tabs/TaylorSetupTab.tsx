// ui/src/components/tabs/TaylorSetupTab.tsx
// Taylor's Setup tab: compact stakeholder list + invite chase rules (localStorage-backed)
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, ExternalLink, Mail, MessageCircle, Smartphone, MessageSquare, UserCheck, CheckSquare } from 'lucide-react'
import { stakeholdersApi } from '../../api/endpoints'
import type { Stakeholder } from '../../types'

const COMMS_ICON: Record<string, React.ReactNode> = {
  email: <Mail size={11} />,
  slack: <MessageCircle size={11} />,
  sms:   <Smartphone size={11} />,
}

const INVITE_CONFIG_KEY = 'agentpool-taylor-invite-config'

interface InviteConfig {
  chaseFrequencyDays: number
  maxChases: number
  escalationStyle: 'gentle' | 'moderate' | 'persistent'
  tone: string
}

function loadInviteConfig(slug: string): InviteConfig {
  try {
    const raw = localStorage.getItem(`${INVITE_CONFIG_KEY}-${slug}`)
    if (raw) return JSON.parse(raw) as InviteConfig
  } catch { /* ignore */ }
  return { chaseFrequencyDays: 3, maxChases: 3, escalationStyle: 'moderate', tone: 'Professional and respectful; reference the value chain mapping work and its importance to the programme.' }
}

export default function TaylorSetupTab({ slug }: { slug: string }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [importMsg, setImportMsg] = useState<string | null>(null)
  const [inviteConfig, setInviteConfig] = useState<InviteConfig>(() => loadInviteConfig(slug))
  const [configSaved, setConfigSaved] = useState(false)

  const { data: stakeholders = [] } = useQuery<Stakeholder[]>({
    queryKey: ['stakeholders', slug],
    queryFn: () => stakeholdersApi.list(slug),
  })

  async function handleCsvImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !slug) return
    try {
      const result = await stakeholdersApi.importCsv(slug, file)
      setImportMsg(`Created ${result.created} · Updated ${result.updated}${result.errors.length ? ` · ${result.errors.length} errors` : ''}`)
      qc.invalidateQueries({ queryKey: ['stakeholders', slug] })
    } catch {
      setImportMsg('Import failed — check CSV format.')
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function saveInviteConfig() {
    try {
      localStorage.setItem(`${INVITE_CONFIG_KEY}-${slug}`, JSON.stringify(inviteConfig))
      setConfigSaved(true)
      setTimeout(() => setConfigSaved(false), 2500)
    } catch { /* quota */ }
  }

  const filtered = stakeholders.filter(s => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      s.name.toLowerCase().includes(q) ||
      (s.organisation ?? '').toLowerCase().includes(q) ||
      (s.job_title ?? '').toLowerCase().includes(q)
    )
  })

  const selectCls = 'bg-white border border-gray-200 rounded px-2 py-1 text-xs text-gray-800 outline-none focus:border-brand'

  return (
    <div className="space-y-6">

      {/* Stakeholder list header */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
            Stakeholders · {stakeholders.length}
          </p>
          <div className="flex items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              onChange={handleCsvImport}
              className="hidden"
            />
            <button
              onClick={() => fileRef.current?.click()}
              className="text-[10px] text-gray-400 hover:text-gray-700 border border-gray-200 rounded px-2 py-0.5"
            >
              Import CSV
            </button>
            <button
              onClick={() => navigate(`/${slug}/stakeholders/new`)}
              className="flex items-center gap-1 text-[10px] font-medium text-brand hover:text-brand-dark border border-brand/30 rounded px-2 py-0.5 hover:bg-brand/5"
            >
              <Plus size={10} /> Add
            </button>
            <button
              onClick={() => navigate(`/${slug}/stakeholders`)}
              className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-700"
            >
              <ExternalLink size={10} /> All
            </button>
          </div>
        </div>

        {importMsg && (
          <p className="text-[10px] text-teal-600 mb-2">{importMsg}</p>
        )}

        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search stakeholders…"
          className="w-full bg-white border border-gray-200 rounded px-2.5 py-1.5 text-xs text-gray-800 placeholder-gray-400 outline-none focus:border-brand mb-2"
        />

        {filtered.length === 0 ? (
          <p className="text-xs text-gray-400 italic py-3">No stakeholders yet — add one or import a CSV.</p>
        ) : (
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {filtered.slice(0, 20).map(s => (
              <button
                key={s.id}
                onClick={() => navigate(`/${slug}/stakeholders/${s.id}/edit`)}
                className="w-full flex items-center gap-2 text-left px-2.5 py-2 rounded-lg border border-gray-100 hover:border-brand/30 hover:bg-brand/5 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-gray-800 truncate">{s.name}</p>
                  {(s.organisation || s.job_title) && (
                    <p className="text-[10px] text-gray-400 truncate">
                      {[s.job_title, s.organisation].filter(Boolean).join(' · ')}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  {s.is_participant && <span title="Participant" className="text-brand"><MessageSquare size={10} /></span>}
                  {s.is_reviewer && <span title="Reviewer" className="text-amber-500"><UserCheck size={10} /></span>}
                  {s.is_approver && <span title="Approver" className="text-emerald-600"><CheckSquare size={10} /></span>}
                  {s.comms_channel && COMMS_ICON[s.comms_channel] && (
                    <span className="text-gray-300">{COMMS_ICON[s.comms_channel]}</span>
                  )}
                </div>
              </button>
            ))}
            {filtered.length > 20 && (
              <p className="text-[10px] text-gray-400 text-center py-1">
                +{filtered.length - 20} more — <button onClick={() => navigate(`/${slug}/stakeholders`)} className="text-brand underline">view all</button>
              </p>
            )}
          </div>
        )}
      </div>

      {/* Invite chase rules */}
      <div className="border-t border-gray-100 pt-5">
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-3">Interview Invite Rules</p>

        <div className="space-y-3">
          <div className="flex gap-4">
            <div className="flex-1">
              <label className="block text-[10px] text-gray-500 mb-1">Chase every (days)</label>
              <input
                type="number"
                min={1}
                max={14}
                value={inviteConfig.chaseFrequencyDays}
                onChange={e => setInviteConfig(c => ({ ...c, chaseFrequencyDays: Math.max(1, Number(e.target.value)) }))}
                className="w-20 bg-white border border-gray-200 rounded px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
              />
            </div>
            <div className="flex-1">
              <label className="block text-[10px] text-gray-500 mb-1">Max chasers</label>
              <input
                type="number"
                min={1}
                max={10}
                value={inviteConfig.maxChases}
                onChange={e => setInviteConfig(c => ({ ...c, maxChases: Math.max(1, Number(e.target.value)) }))}
                className="w-20 bg-white border border-gray-200 rounded px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
              />
            </div>
            <div className="flex-1">
              <label className="block text-[10px] text-gray-500 mb-1">Escalation style</label>
              <select
                value={inviteConfig.escalationStyle}
                onChange={e => setInviteConfig(c => ({ ...c, escalationStyle: e.target.value as InviteConfig['escalationStyle'] }))}
                className={selectCls}
              >
                <option value="gentle">Gentle</option>
                <option value="moderate">Moderate</option>
                <option value="persistent">Persistent</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-[10px] text-gray-500 mb-1">Tone &amp; context for chasers</label>
            <textarea
              value={inviteConfig.tone}
              onChange={e => setInviteConfig(c => ({ ...c, tone: e.target.value }))}
              rows={3}
              placeholder="Describe the tone Taylor should use when chasing…"
              className="w-full bg-white border border-gray-200 rounded px-2.5 py-1.5 text-xs text-gray-900 placeholder-gray-400 outline-none focus:border-brand resize-y"
            />
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={saveInviteConfig}
              className="px-3 py-1.5 bg-brand hover:bg-brand-dark text-white text-xs font-medium rounded"
            >
              Save Rules
            </button>
            {configSaved && <span className="text-emerald-500 text-xs">Saved.</span>}
          </div>
        </div>
      </div>
    </div>
  )
}
