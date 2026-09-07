// ui/src/components/tabs/InstrumentDesignSetup.tsx
//
// How this engagement's interview instruments are configured: the disciplines every section is
// tagged with, and the standards the questionnaires are built against.
//
// It was the top of `MayaSetupTab`. The Interaction Designer reads the disciplines when she
// writes her scripts, which is what made the filename read as her configuration - but the
// vertical axis a client's maturity is grouped by survives any change of designer. The rename
// test puts it on Setup.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import { projectsApi } from '../../api/endpoints'
import type { ProjectSettings } from '../../types'

/**
 * The vertical axis Casey groups maturity themes by, edited where the instruments are
 * designed.
 *
 * Closed on purpose: a discipline off this list is refused when the scripts are written, the
 * way an unknown value chain id already is. An open field would put the project back to
 * clustering 178 distinct section titles, which is what this replaced.
 */
function DisciplineEditor({ slug, settings }: { slug: string; settings?: ProjectSettings }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')
  const disciplines = settings?.disciplines ?? []

  const save = useMutation({
    // The endpoint replaces the whole settings object, so the rest is round-tripped rather
    // than sent as a partial - a partial would blank every field it omitted.
    mutationFn: (next: string[]) =>
      projectsApi.updateSettings(slug, { ...(settings as ProjectSettings), disciplines: next }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings', slug] }),
  })

  const add = () => {
    const value = draft.trim().toLowerCase()
    // Silently dropping a duplicate would read as the add having failed.
    if (!value || disciplines.includes(value)) return
    setDraft('')
    save.mutate([...disciplines, value])
  }

  return (
    <div>
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">
        Disciplines
      </p>
      <p className="text-[11px] text-gray-400 mb-3">
        Every interview section is tagged with one of these. Casey groups vertical themes -
        maturity within a discipline - by the tag, so a discipline missing here is a theme
        that cannot be found.
      </p>

      <ul className="flex flex-wrap gap-1.5 mb-2" data-testid="discipline-list">
        {disciplines.map((d) => (
          <li
            key={d}
            className="flex items-center gap-1.5 rounded bg-gray-50 border border-gray-100 pl-2.5 pr-1.5 py-1"
          >
            <span className="text-[11px] text-gray-700">{d}</span>
            <button
              type="button"
              aria-label={`Remove ${d}`}
              className="text-gray-300 hover:text-gray-600 transition-colors"
              onClick={() => save.mutate(disciplines.filter((x) => x !== d))}
            >
              <X size={11} />
            </button>
          </li>
        ))}
      </ul>

      <div className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') add()
          }}
          placeholder="Add a discipline"
          aria-label="Add a discipline"
          className="flex-1 max-w-[14rem] bg-white border border-gray-200 rounded px-2 py-1 text-xs text-gray-900 outline-none focus:border-brand"
        />
        <button
          type="button"
          onClick={add}
          disabled={save.isPending || !settings}
          className="flex items-center gap-1 px-2.5 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 text-[11px] rounded transition-colors disabled:opacity-50"
        >
          <Plus size={11} /> Add
        </button>
      </div>
    </div>
  )
}

export default function InstrumentDesignSetup({ slug }: { slug: string }) {
  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug),
  })

  const standardsRefs = settings?.standards_references

  return (
    <div className="space-y-5">
      {/* Standards context. Read-only here and edited one crew upstream, where the rest of the
          discovery brief is - so the pointer names the tab it is actually on rather than an
          agent's name. */}
      {standardsRefs && (
        <div className="rounded-lg bg-brand/5 border border-brand/20 px-3 py-2.5">
          <p className="text-[10px] font-bold text-teal-600 uppercase tracking-widest mb-1">Standards &amp; Frameworks</p>
          <p className="text-[11px] text-teal-700 leading-relaxed">{standardsRefs}</p>
          <p className="text-[10px] text-teal-600 mt-1">Edit on the Value Chain Mapping crew&rsquo;s Setup tab.</p>
        </div>
      )}

      <DisciplineEditor slug={slug} settings={settings} />
    </div>
  )
}
