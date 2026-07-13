// ui/src/pages/Stakeholders.tsx
import { useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { stakeholdersApi } from '../api/endpoints'
import type { Stakeholder, StakeholderImportResult } from '../types'

const ROLE_COLOURS: Record<string, string> = {
  actor: 'bg-brand/10 text-teal-700',
  governing: 'bg-amber-100 text-amber-700',
  recipient: 'bg-gray-100 text-gray-600',
}

const DISPOSITION_COLOURS: Record<string, string> = {
  champion: 'bg-emerald-100 text-emerald-700',
  supporter: 'bg-teal-100 text-teal-700',
  neutral: 'bg-gray-100 text-gray-600',
  skeptic: 'bg-orange-100 text-orange-700',
  blocker: 'bg-red-100 text-red-700',
}

function Badge({ text, colours }: { text: string; colours: string }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${colours}`}>{text}</span>
  )
}

export default function Stakeholders() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [importMsg, setImportMsg] = useState<string | null>(null)

  const { data: stakeholders = [], isLoading } = useQuery<Stakeholder[]>({
    queryKey: ['stakeholders', slug],
    queryFn: () => stakeholdersApi.list(slug!),
    enabled: !!slug,
  })

  const filtered = stakeholders.filter((s) => {
    const q = search.toLowerCase()
    return (
      s.name.toLowerCase().includes(q) ||
      s.organisation.toLowerCase().includes(q) ||
      s.email.toLowerCase().includes(q)
    )
  })

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !slug) return
    try {
      const result: StakeholderImportResult = await stakeholdersApi.importCsv(slug, file)
      const errMsg = result.errors.length > 0 ? ` (${result.errors.length} rows skipped)` : ''
      setImportMsg(`Imported: ${result.created} created, ${result.updated} updated${errMsg}`)
      qc.invalidateQueries({ queryKey: ['stakeholders', slug] })
    } catch {
      setImportMsg('Import failed. Check the file format.')
    }
    if (fileRef.current) fileRef.current.value = ''
    setTimeout(() => setImportMsg(null), 5000)
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Stakeholders</h2>
        <div className="flex items-center gap-3">
          {importMsg && (
            <span className="text-xs text-emerald-600">{importMsg}</span>
          )}
          <label
            htmlFor="csv-import"
            className="cursor-pointer text-xs text-gray-600 hover:text-gray-900 border border-gray-200 hover:border-gray-400 rounded px-3 py-1.5 transition-colors"
          >
            Import CSV
          </label>
          <input
            id="csv-import"
            ref={fileRef}
            type="file"
            accept=".csv"
            onChange={handleImport}
            className="sr-only"
          />
          <button
            onClick={() => navigate(`/${slug}/stakeholders/new`)}
            className="text-xs bg-brand hover:bg-brand-dark text-white rounded px-3 py-1.5 transition-colors"
          >
            + Add Stakeholder
          </button>
        </div>
      </div>

      {/* Search */}
      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by name, organisation, or email…"
        className="w-full max-w-sm bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 placeholder:text-gray-400 outline-none focus:border-brand"
      />

      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}

      {!isLoading && stakeholders.length === 0 && (
        <p className="text-sm text-gray-400">
          No stakeholders yet. Add one or import a CSV.
        </p>
      )}

      {filtered.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-gray-50">
                <th className="px-4 py-2 text-left text-gray-500 font-medium">Name / Title</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Organisation</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Role</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Disposition</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Value Streams</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Email</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr key={s.id} className="border-t border-gray-200 hover:bg-gray-50">
                  <td className="px-4 py-2.5">
                    <p className="text-gray-900 font-medium">{s.name}</p>
                    {s.job_title && <p className="text-gray-400 mt-0.5">{s.job_title}</p>}
                  </td>
                  <td className="px-3 py-2.5 text-gray-600">{s.organisation}</td>
                  <td className="px-3 py-2.5">
                    <Badge text={s.project_role} colours={ROLE_COLOURS[s.project_role] ?? ROLE_COLOURS.recipient} />
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge text={s.disposition} colours={DISPOSITION_COLOURS[s.disposition] ?? DISPOSITION_COLOURS.neutral} />
                  </td>
                  <td className="px-3 py-2.5 text-gray-600 max-w-[180px] truncate">
                    {s.value_streams.join(', ') || '—'}
                  </td>
                  <td className="px-3 py-2.5 text-gray-600">{s.email || '—'}</td>
                  <td className="px-3 py-2.5">
                    <button
                      onClick={() => navigate(`/${slug}/stakeholders/${s.id}/edit`)}
                      className="text-brand hover:text-brand-dark transition-colors"
                    >
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
