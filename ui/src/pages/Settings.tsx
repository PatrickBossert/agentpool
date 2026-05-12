import { useEffect, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import type { ProjectSettings } from '../types'

const KNOWN_CREWS = ['discovery', 'value_design', 'architecture', 'delivery', 'business_plan']

const DEFAULTS: ProjectSettings = {
  llm_mode: 'standard',
  sector: '',
  stakeholder_groups: [],
  value_stream_labels: [],
  roadmap_time_axis: 'quarters',
  crews_enabled: [...KNOWN_CREWS],
  review_gates: true,
  slack_channel: '',
  discovery_brief: '',
  discovery_links: [],
  discovery_document_ids: [],
  interview_method: 'none',
}

function TagInput({
  value,
  onChange,
}: {
  value: string[]
  onChange: (v: string[]) => void
}) {
  const [input, setInput] = useState('')

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && input.trim()) {
      e.preventDefault()
      if (!value.includes(input.trim())) {
        onChange([...value, input.trim()])
      }
      setInput('')
    }
  }

  return (
    <div className="flex flex-wrap gap-1 p-2 bg-slate-900 border border-slate-700 rounded min-h-[36px]">
      {value.map((tag) => (
        <span
          key={tag}
          className="flex items-center gap-1 bg-sky-900/60 text-sky-300 text-xs px-2 py-0.5 rounded-full"
        >
          {tag}
          <button
            type="button"
            onClick={() => onChange(value.filter((t) => t !== tag))}
            className="text-sky-400 hover:text-white leading-none"
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKey}
        placeholder="Add…"
        className="bg-transparent text-sm text-slate-300 outline-none min-w-[80px] flex-1"
      />
    </div>
  )
}

export default function Settings() {
  const { slug } = useParams<{ slug: string }>()
  const qc = useQueryClient()
  const [form, setForm] = useState<ProjectSettings>(DEFAULTS)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  useEffect(() => {
    if (settings) setForm({ ...DEFAULTS, ...settings })
  }, [settings])

  const mutation = useMutation({
    mutationFn: (data: ProjectSettings) => projectsApi.updateSettings(slug!, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', slug] })
      setSaved(true)
      setError(null)
      setTimeout(() => setSaved(false), 2000)
    },
    onError: () => setError('Save failed. Please try again.'),
  })

  if (!slug) return null

  function toggleCrew(crew: string) {
    setForm((f) => ({
      ...f,
      crews_enabled: f.crews_enabled.includes(crew)
        ? f.crews_enabled.filter((c) => c !== crew)
        : [...f.crews_enabled, crew],
    }))
  }

  return (
    <div className="p-6 max-w-2xl space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Settings — {slug}</h2>

      {/* General */}
      <section className="space-y-4">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest">General</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-slate-400 block mb-1">Sector</label>
            <input
              value={form.sector}
              onChange={(e) => setForm({ ...form, sector: e.target.value })}
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-sky-600"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">LLM Mode</label>
            <select
              value={form.llm_mode}
              onChange={(e) =>
                setForm({ ...form, llm_mode: e.target.value as ProjectSettings['llm_mode'] })
              }
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-sky-600"
            >
              <option value="standard">standard</option>
              <option value="sensitive">sensitive</option>
              <option value="fallback">fallback</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Roadmap Time Axis</label>
            <select
              value={form.roadmap_time_axis}
              onChange={(e) =>
                setForm({
                  ...form,
                  roadmap_time_axis: e.target.value as ProjectSettings['roadmap_time_axis'],
                })
              }
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-sky-600"
            >
              <option value="quarters">quarters</option>
              <option value="years">years</option>
              <option value="horizons">horizons</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Slack Channel</label>
            <input
              value={form.slack_channel}
              onChange={(e) => setForm({ ...form, slack_channel: e.target.value })}
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-sky-600"
            />
          </div>
        </div>
      </section>

      {/* Tag fields */}
      <section className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-slate-400 block mb-1">Stakeholder Groups</label>
          <TagInput
            value={form.stakeholder_groups}
            onChange={(v) => setForm({ ...form, stakeholder_groups: v })}
          />
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1">Value Stream Labels</label>
          <TagInput
            value={form.value_stream_labels}
            onChange={(v) => setForm({ ...form, value_stream_labels: v })}
          />
        </div>
      </section>

      {/* Crews */}
      <section>
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
          Crews Enabled
        </h3>
        <div className="flex flex-wrap gap-4">
          {KNOWN_CREWS.map((crew) => (
            <label key={crew} className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.crews_enabled.includes(crew)}
                onChange={() => toggleCrew(crew)}
              />
              {crew}
            </label>
          ))}
        </div>
      </section>

      {/* Review gates */}
      <section className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-200">Review Gates</p>
          <p className="text-xs text-slate-500">Pause pipeline for human review between crews</p>
        </div>
        <button
          type="button"
          onClick={() => setForm({ ...form, review_gates: !form.review_gates })}
          className={`relative inline-flex h-5 w-9 rounded-full transition-colors ${
            form.review_gates ? 'bg-sky-600' : 'bg-slate-700'
          }`}
        >
          <span
            className={`inline-block h-4 w-4 mt-0.5 rounded-full bg-white shadow transition-transform ${
              form.review_gates ? 'translate-x-4' : 'translate-x-0.5'
            }`}
          />
        </button>
      </section>

      {/* Discovery */}
      <section className="space-y-3">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest">Discovery</h3>
        <div>
          <label className="text-xs text-slate-400 block mb-2">Interview Method</label>
          <div className="flex flex-col gap-2">
            {(
              [
                ['none', 'None — skip interview phase'],
                ['agent', 'Agent interviews (platform conducts text-based interviews)'],
                ['listenlabs', 'ListenLabs (external campaign via ListenLabs API)'],
              ] as [ProjectSettings['interview_method'], string][]
            ).map(([value, label]) => (
              <label key={value} className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
                <input
                  type="radio"
                  name="interview_method"
                  value={value}
                  checked={form.interview_method === value}
                  onChange={() => setForm({ ...form, interview_method: value })}
                />
                {label}
              </label>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <div className="border-t border-slate-800 pt-4 flex items-center justify-between">
        {error ? <p className="text-sm text-red-400">{error}</p> : <span />}
        <button
          onClick={() => mutation.mutate(form)}
          disabled={mutation.isPending}
          className="px-4 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm rounded"
        >
          {saved ? 'Saved!' : mutation.isPending ? 'Saving…' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}
