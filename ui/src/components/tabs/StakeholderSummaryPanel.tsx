// ui/src/components/tabs/StakeholderSummaryPanel.tsx
//
// Who is on this engagement: how many, who they are, what roles they hold, and a way to bring
// more of them in from a CSV.
//
// It was the upper half of `TaylorSetupTab`. Replace the Interview Coordinator tomorrow and
// this list does not move an inch - it is the engagement's roster, not her configuration -
// which is why it is on Status rather than Agents.
//
// Status is otherwise read-only, and CSV import is the one thing here that writes. It is on
// this tab deliberately: a roster is what the engagement *is*, and adding people to it is not
// configuring how the engagement runs. The full editor is the Stakeholders page, which the
// header links to.
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

export default function StakeholderSummaryPanel({ slug }: { slug: string }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [importMsg, setImportMsg] = useState<string | null>(null)

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

  const filtered = stakeholders.filter(s => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      s.name.toLowerCase().includes(q) ||
      (s.organisation ?? '').toLowerCase().includes(q) ||
      (s.job_title ?? '').toLowerCase().includes(q)
    )
  })

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

    </div>
  )
}
