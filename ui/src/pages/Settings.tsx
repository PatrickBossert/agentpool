import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import type { ProjectSettings } from '../types'

const DEFAULT_PRIMARY_COLOR = '#0d9488'  // must match api/models.py default
const DEFAULT_TEXT_COLOR = '#1f2937'

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
    <div className="flex flex-wrap gap-1 p-2 bg-white border border-gray-200 rounded min-h-[36px]">
      {value.map((tag) => (
        <span
          key={tag}
          className="flex items-center gap-1 bg-brand/10 text-teal-700 text-xs px-2 py-0.5 rounded-full"
        >
          {tag}
          <button
            type="button"
            onClick={() => onChange(value.filter((t) => t !== tag))}
            className="text-teal-600 hover:text-gray-900 leading-none"
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
        className="bg-transparent text-sm text-gray-700 outline-none min-w-[80px] flex-1"
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
  const [imageStatus, setImageStatus] = useState<string>('')
  const [imageError, setImageError] = useState(false)
  const [imageUploading, setImageUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

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

  async function handleImageUpload() {
    const file = fileInputRef.current?.files?.[0]
    if (!file || !slug) return
    setImageUploading(true)
    setImageStatus('')
    try {
      const data = await projectsApi.uploadBrandingImage(slug, file)
      setForm((f) => ({ ...f, brand_header_image_url: `${data.url}?t=${Date.now()}` }))
      setImageStatus('Image uploaded successfully.')
      setImageError(false)
    } catch {
      setImageStatus('Upload failed.')
      setImageError(true)
    } finally {
      setImageUploading(false)
    }
  }

  return (
    <div className="p-6 max-w-2xl space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">Settings — {slug}</h2>

      {/* General */}
      <section className="space-y-4">
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest">General</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-600 block mb-1">Sector</label>
            <input
              value={form.sector}
              onChange={(e) => setForm({ ...form, sector: e.target.value })}
              className="w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
            />
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">LLM Mode</label>
            <select
              value={form.llm_mode}
              onChange={(e) =>
                setForm({ ...form, llm_mode: e.target.value as ProjectSettings['llm_mode'] })
              }
              className="w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
            >
              <option value="standard">standard</option>
              <option value="sensitive">sensitive</option>
              <option value="fallback">fallback</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">Roadmap Time Axis</label>
            <select
              value={form.roadmap_time_axis}
              onChange={(e) =>
                setForm({
                  ...form,
                  roadmap_time_axis: e.target.value as ProjectSettings['roadmap_time_axis'],
                })
              }
              className="w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
            >
              <option value="quarters">quarters</option>
              <option value="years">years</option>
              <option value="horizons">horizons</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">Slack Channel</label>
            <input
              value={form.slack_channel}
              onChange={(e) => setForm({ ...form, slack_channel: e.target.value })}
              className="w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
            />
          </div>
        </div>
      </section>

      {/* Tag fields */}
      <section className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-gray-600 block mb-1">Stakeholder Groups</label>
          <TagInput
            value={form.stakeholder_groups}
            onChange={(v) => setForm({ ...form, stakeholder_groups: v })}
          />
        </div>
        <div>
          <label className="text-xs text-gray-600 block mb-1">Value Stream Labels</label>
          <TagInput
            value={form.value_stream_labels}
            onChange={(v) => setForm({ ...form, value_stream_labels: v })}
          />
        </div>
      </section>

      {/* Crews */}
      <section>
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">
          Crews Enabled
        </h3>
        <div className="flex flex-wrap gap-4">
          {KNOWN_CREWS.map((crew) => (
            <label key={crew} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
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
          <p className="text-sm font-medium text-gray-900">Review Gates</p>
          <p className="text-xs text-gray-400">Pause pipeline for human review between crews</p>
        </div>
        <button
          type="button"
          onClick={() => setForm({ ...form, review_gates: !form.review_gates })}
          className={`relative inline-flex h-5 w-9 rounded-full transition-colors ${
            form.review_gates ? 'bg-brand' : 'bg-gray-300'
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
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest">Discovery</h3>
        <div>
          <label className="text-xs text-gray-600 block mb-2">Interview Method</label>
          <div className="flex flex-col gap-2">
            {(
              [
                ['none', 'None — skip interview phase'],
                ['agent', 'Agent interviews (platform conducts voice interviews)'],
              ] as [ProjectSettings['interview_method'], string][]
            ).map(([value, label]) => (
              <label key={value} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
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

      {/* Interview Branding */}
      <section className="space-y-4">
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest">Interview Branding</h3>

        {/* Header image */}
        <div>
          <label className="text-xs text-gray-600 block mb-1">Header Image</label>
          {form.brand_header_image_url && (
            <img
              src={form.brand_header_image_url}
              alt="Brand header preview"
              className="mb-2 max-h-24 rounded border border-gray-200 object-contain"
            />
          )}
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={() => { setImageStatus(''); setImageError(false) }}
              className="text-sm text-gray-600 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-gray-100 file:text-gray-700 hover:file:bg-gray-200"
            />
            <button
              type="button"
              onClick={handleImageUpload}
              disabled={imageUploading}
              className="px-3 py-1 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 text-gray-700 text-xs rounded"
            >
              {imageUploading ? 'Uploading…' : 'Upload'}
            </button>
          </div>
          {imageStatus && (
            <p className={`text-xs mt-1 ${imageError ? 'text-red-400' : 'text-green-400'}`}>
              {imageStatus}
            </p>
          )}
        </div>

        {/* Colour pickers */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-600 block mb-1">Primary Colour</label>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={form.brand_primary_color ?? DEFAULT_PRIMARY_COLOR}
                onChange={(e) => setForm({ ...form, brand_primary_color: e.target.value })}
                className="h-8 w-10 rounded border border-gray-200 bg-white cursor-pointer p-0.5"
              />
              <span className="text-xs text-gray-400 font-mono">{form.brand_primary_color ?? DEFAULT_PRIMARY_COLOR}</span>
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">Text Colour</label>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={form.brand_text_color ?? DEFAULT_TEXT_COLOR}
                onChange={(e) => setForm({ ...form, brand_text_color: e.target.value })}
                className="h-8 w-10 rounded border border-gray-200 bg-white cursor-pointer p-0.5"
              />
              <span className="text-xs text-gray-400 font-mono">{form.brand_text_color ?? DEFAULT_TEXT_COLOR}</span>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <div className="border-t border-gray-200 pt-4 flex items-center justify-between">
        {error ? <p className="text-sm text-red-400">{error}</p> : <span />}
        <button
          onClick={() => mutation.mutate(form)}
          disabled={mutation.isPending}
          className="px-4 py-1.5 bg-brand hover:bg-brand-dark disabled:opacity-50 text-white text-sm rounded"
        >
          {saved ? 'Saved!' : mutation.isPending ? 'Saving…' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}
