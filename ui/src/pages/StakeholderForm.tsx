// ui/src/pages/StakeholderForm.tsx
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { stakeholdersApi, projectsApi } from '../api/endpoints'
import { COUNTRY_DATA, COUNTRY_OPTIONS } from '../utils/countryData'
import type { Stakeholder } from '../types'

type FormData = Omit<Stakeholder, 'id' | 'created_at'>

const EMPTY: FormData = {
  name: '',
  job_title: '',
  organisation: '',
  email: '',
  slack_handle: '',
  stakeholder_groups: [],
  project_role: 'recipient',
  value_streams: [],
  value_chain_stage: '',
  activity: '',
  disposition: 'neutral',
  location: '',
  country_code: '',
  timezone: '',
  preferred_language: '',
  currency: '',
  interview_status: null,
  interview_invited_at: null,
  interview_completed_at: null,
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-4 mt-6 first:mt-0">
      {children}
    </h3>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-xs text-slate-400 block mb-1">{label}</label>
      {children}
    </div>
  )
}

const INPUT = 'w-full bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-sky-600'
const SELECT = `${INPUT} cursor-pointer`

function MultiCheckbox({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: string[]
  value: string[]
  onChange: (v: string[]) => void
}) {
  function toggle(opt: string) {
    onChange(value.includes(opt) ? value.filter((v) => v !== opt) : [...value, opt])
  }
  return (
    <div>
      <label className="text-xs text-slate-400 block mb-2">{label}</label>
      {options.length === 0 ? (
        <p className="text-xs text-slate-600">
          None configured — add them in Settings first.
        </p>
      ) : (
        <div className="flex flex-wrap gap-x-6 gap-y-1.5">
          {options.map((opt) => (
            <label key={opt} className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={value.includes(opt)}
                onChange={() => toggle(opt)}
                className="accent-sky-500"
              />
              {opt}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

export default function StakeholderForm() {
  const { slug, id } = useParams<{ slug: string; id?: string }>()
  const navigate = useNavigate()
  const isEdit = !!id
  const [form, setForm] = useState<FormData>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Fetch settings to populate multi-select options
  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  // Fetch existing stakeholder when editing
  const { data: existing } = useQuery<Stakeholder[]>({
    queryKey: ['stakeholders', slug],
    queryFn: () => stakeholdersApi.list(slug!),
    enabled: !!slug && isEdit,
  })

  useEffect(() => {
    if (isEdit && existing && id) {
      const found = existing.find((s) => s.id === Number(id))
      if (found) {
        const { id: _id, created_at: _ca, ...rest } = found
        setForm(rest)
      }
    }
  }, [isEdit, existing, id])

  function set<K extends keyof FormData>(key: K, value: FormData[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function handleCountryChange(code: string) {
    const info = COUNTRY_DATA[code]
    set('country_code', code)
    if (info) {
      set('location', info.name)
      if (!form.timezone) set('timezone', info.timezone)
      if (!form.currency) set('currency', info.currency)
      if (!form.preferred_language) set('preferred_language', info.language)
    }
  }

  async function handleSave() {
    if (!form.name.trim()) {
      setError('Name is required.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      if (isEdit && id) {
        await stakeholdersApi.update(slug!, Number(id), form)
      } else {
        await stakeholdersApi.create(slug!, form)
      }
      navigate(`/${slug}/stakeholders`)
    } catch {
      setError('Save failed. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const groupOptions = settings?.stakeholder_groups ?? []
  const vsOptions = settings?.value_stream_labels ?? []

  return (
    <div className="p-6 max-w-2xl">
      <div className="mb-6">
        <button
          onClick={() => navigate(`/${slug}/stakeholders`)}
          className="text-sm text-slate-400 hover:text-slate-200 mb-2 block"
        >
          ← Back to Stakeholders
        </button>
        <h2 className="text-lg font-semibold text-slate-100">
          {isEdit ? 'Edit Stakeholder' : 'Add Stakeholder'}
        </h2>
      </div>

      <div className="space-y-4">
        {/* Identity */}
        <SectionHeading>Identity</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Name *">
            <input value={form.name} onChange={(e) => set('name', e.target.value)} className={INPUT} />
          </Field>
          <Field label="Job Title">
            <input value={form.job_title} onChange={(e) => set('job_title', e.target.value)} className={INPUT} />
          </Field>
          <Field label="Organisation">
            <input value={form.organisation} onChange={(e) => set('organisation', e.target.value)} className={INPUT} />
          </Field>
        </div>

        {/* Contact */}
        <SectionHeading>Contact</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Email">
            <input value={form.email} onChange={(e) => set('email', e.target.value)} className={INPUT} />
          </Field>
          <Field label="Slack Handle">
            <input value={form.slack_handle} onChange={(e) => set('slack_handle', e.target.value)} className={INPUT} placeholder="@handle" />
          </Field>
          <Field label="Preferred Language">
            <input value={form.preferred_language} onChange={(e) => set('preferred_language', e.target.value)} className={INPUT} />
          </Field>
        </div>

        {/* Project Role */}
        <SectionHeading>Project Role</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Role">
            <select value={form.project_role} onChange={(e) => set('project_role', e.target.value as FormData['project_role'])} className={SELECT}>
              <option value="recipient">Recipient</option>
              <option value="governing">Governing</option>
              <option value="actor">Actor</option>
            </select>
          </Field>
          <Field label="Disposition">
            <select value={form.disposition} onChange={(e) => set('disposition', e.target.value as FormData['disposition'])} className={SELECT}>
              <option value="champion">Champion</option>
              <option value="supporter">Supporter</option>
              <option value="neutral">Neutral</option>
              <option value="skeptic">Skeptic</option>
              <option value="blocker">Blocker</option>
            </select>
          </Field>
        </div>
        <MultiCheckbox
          label="Stakeholder Groups"
          options={groupOptions}
          value={form.stakeholder_groups}
          onChange={(v) => set('stakeholder_groups', v)}
        />

        {/* Value Chain Alignment */}
        <SectionHeading>Value Chain Alignment</SectionHeading>
        <MultiCheckbox
          label="Value Streams (L1)"
          options={vsOptions}
          value={form.value_streams}
          onChange={(v) => set('value_streams', v)}
        />
        <div className="grid grid-cols-2 gap-4">
          <Field label="Value Chain Stage (L2)">
            <input value={form.value_chain_stage} onChange={(e) => set('value_chain_stage', e.target.value)} className={INPUT} placeholder="e.g. Billing" />
          </Field>
          <Field label="Activity (L3)">
            <input value={form.activity} onChange={(e) => set('activity', e.target.value)} className={INPUT} placeholder="e.g. Invoice processing" />
          </Field>
        </div>

        {/* Location */}
        <SectionHeading>Location</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Country">
            <select
              value={form.country_code}
              onChange={(e) => handleCountryChange(e.target.value)}
              className={SELECT}
            >
              <option value="">— Select country —</option>
              {COUNTRY_OPTIONS.map(({ code, name }) => (
                <option key={code} value={code}>{name}</option>
              ))}
            </select>
          </Field>
          <Field label="Timezone">
            <input value={form.timezone} onChange={(e) => set('timezone', e.target.value)} className={INPUT} placeholder="e.g. Europe/London" />
          </Field>
          <Field label="Currency">
            <input value={form.currency} onChange={(e) => set('currency', e.target.value)} className={INPUT} placeholder="e.g. GBP" />
          </Field>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-8 border-t border-slate-800 pt-4 flex items-center justify-between">
        {error ? <p className="text-sm text-red-400">{error}</p> : <span />}
        <div className="flex gap-3">
          <button onClick={() => navigate(`/${slug}/stakeholders`)} className="text-sm text-slate-400 hover:text-slate-200 px-3 py-1.5">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm rounded"
          >
            {saving ? 'Saving…' : 'Save Stakeholder'}
          </button>
        </div>
      </div>
    </div>
  )
}
