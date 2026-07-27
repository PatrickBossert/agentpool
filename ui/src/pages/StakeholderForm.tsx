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
  mobile: '',
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
  level: '',
  entity: '',
  comms_channel: 'email',
  is_participant: false,
  is_reviewer: false,
  is_approver: false,
  interview_status: null,
  interview_invited_at: null,
  interview_completed_at: null,
}

const LEVEL_OPTIONS = [
  { value: '',   label: '- Select level -' },
  { value: 'L0', label: 'L0 - Executive / Board' },
  { value: 'L1', label: 'L1 - General Manager / VP' },
  { value: 'L2', label: 'L2 - Manager / Senior' },
  { value: 'L3', label: 'L3 - Operational / Analyst' },
]

// Languages supported by both ElevenLabs (TTS) and Deepgram (STT) — voice interview pipeline
const LANG_OPTIONS = [
  'Arabic', 'Chinese', 'Danish', 'English', 'Filipino', 'Finnish',
  'French', 'German', 'Hindi', 'Indonesian', 'Italian', 'Japanese',
  'Korean', 'Malay', 'Norwegian', 'Polish', 'Portuguese', 'Romanian',
  'Spanish', 'Swedish', 'Turkish', 'Ukrainian',
]

const FIXED_ENTITIES = ['Advisor', 'Auditor', 'Other']

// Extract distinct org/entity names from the registry L1 labels and L3 partner references
function orgsFromRegistry(activities: Array<{ id: string; label: string; level: string; active: boolean; parent_id?: string | null }>): string[] {
  const orgs: string[] = []
  let supportFull = ''
  let supportAbbrev = ''

  for (const a of activities) {
    if (!a.active || a.level !== 'L1') continue
    if (/SUPPORT/i.test(a.label)) {
      const m = a.label.match(/—\s*(.+)$/)
      if (m) {
        supportFull = m[1].trim()
        supportAbbrev = supportFull.match(/\(([^)]+)\)$/)?.[1] ?? ''
        orgs.push(supportFull)
      }
    }
  }

  for (const a of activities) {
    if (!a.active || a.level !== 'L1' || /SUPPORT/i.test(a.label)) continue
    const custodian = a.label.match(/Custodian:\s*([^·|]+)/)?.[1]?.trim()
    const maintainer = a.label.match(/Maintainer:\s*([^·|)\n]+)/)?.[1]?.trim()
    for (const org of [custodian, maintainer].filter((x): x is string => Boolean(x))) {
      const resolved = (supportAbbrev && org === supportAbbrev) ? supportFull : org
      if (!orgs.includes(resolved)) orgs.push(resolved)
    }
  }

  for (const a of activities) {
    if (!a.active || a.level !== 'L3') continue
    for (const pat of [/Fleet Alliance/i]) {
      const m = a.label.match(pat)
      if (m && !orgs.includes(m[0])) orgs.push(m[0])
    }
  }

  return orgs
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4 mt-6 first:mt-0">
      {children}
    </h3>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-xs text-gray-500 block mb-1">{label}</label>
      {children}
    </div>
  )
}

const INPUT = 'w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand'
const SELECT = `${INPUT} cursor-pointer`

function RoleCheckbox({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string
  hint: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer p-3 rounded-lg border border-gray-100 hover:border-brand/40 hover:bg-gray-50 transition-colors">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 accent-brand"
      />
      <span>
        <span className="text-sm font-medium text-gray-800 block">{label}</span>
        <span className="text-xs text-gray-400">{hint}</span>
      </span>
    </label>
  )
}

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
      <label className="text-xs text-gray-500 block mb-2">{label}</label>
      {options.length === 0 ? (
        <p className="text-xs text-gray-400">None configured - add them in Settings first.</p>
      ) : (
        <div className="flex flex-wrap gap-x-6 gap-y-1.5">
          {options.map((opt) => (
            <label key={opt} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input
                type="checkbox"
                checked={value.includes(opt)}
                onChange={() => toggle(opt)}
                className="accent-brand"
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

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  const { data: registry } = useQuery({
    queryKey: ['value-chain-registry', slug],
    queryFn: () => projectsApi.getValueChainRegistry(slug!),
    enabled: !!slug,
    retry: false,
  })

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

  // Default preferred_language to project locale for new stakeholders
  useEffect(() => {
    const loc = settings?.locale
    if (isEdit || !loc) return
    setForm(f => {
      if (f.preferred_language) return f
      const cc = loc.includes('-') ? loc.split('-').pop()!.toUpperCase() : loc.toUpperCase()
      const lang = COUNTRY_DATA[cc]?.language ?? ''
      return LANG_OPTIONS.includes(lang) ? { ...f, preferred_language: lang } : f
    })
  }, [settings, isEdit])

  function handleCountryChange(code: string) {
    const info = COUNTRY_DATA[code]
    setForm(f => ({
      ...f,
      country_code: code,
      location:  info?.name     ?? f.location,
      timezone:  info?.timezone ?? f.timezone,   // always override
      currency:  info?.currency ?? f.currency,
      preferred_language: f.preferred_language || (info?.language && LANG_OPTIONS.includes(info.language) ? info.language : f.preferred_language),
    }))
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

  // Registry-derived options
  const allActs = registry?.activities ?? []
  const l1Options = allActs.filter(a => a.level === 'L1' && a.active)
  const selectedL1Ids = l1Options.filter(a => form.value_streams.includes(a.label)).map(a => a.id)
  const l2Options = allActs.filter(a =>
    a.level === 'L2' && a.active &&
    (selectedL1Ids.length === 0 || (a.parent_id != null && selectedL1Ids.includes(a.parent_id)))
  )
  const selectedL2 = allActs.find(a => a.level === 'L2' && a.label === form.value_chain_stage)
  const l3Options = allActs.filter(a =>
    a.level === 'L3' && a.active &&
    (!selectedL2 || a.parent_id === selectedL2.id)
  )

  // Org names for entity dropdown
  const orgOptions = registry ? orgsFromRegistry(allActs) : []

  return (
    <div className="p-6 max-w-2xl">
      <div className="mb-6">
        <button
          onClick={() => navigate(`/${slug}/stakeholders`)}
          className="text-sm text-gray-400 hover:text-gray-700 mb-2 block"
        >
          ← Back to Stakeholders
        </button>
        <h2 className="text-lg font-semibold text-gray-900">
          {isEdit ? 'Edit Stakeholder' : 'Add Stakeholder'}
        </h2>
      </div>

      <div className="space-y-4">
        {/* Identity */}
        <SectionHeading>Identity</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Full Name *">
            <input value={form.name} onChange={(e) => set('name', e.target.value)} className={INPUT} />
          </Field>
          <Field label="Title / Job Title">
            <input value={form.job_title} onChange={(e) => set('job_title', e.target.value)} className={INPUT} />
          </Field>
          <Field label="Organisation">
            <input value={form.organisation} onChange={(e) => set('organisation', e.target.value)} className={INPUT} />
          </Field>
          <Field label="Level">
            <select
              value={form.level}
              onChange={(e) => set('level', e.target.value as FormData['level'])}
              className={SELECT}
            >
              {LEVEL_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </Field>
          <div className="col-span-2">
            <Field label="Entity">
              <select value={form.entity} onChange={(e) => set('entity', e.target.value)} className={SELECT}>
                <option value="">- Select entity -</option>
                {orgOptions.length > 0 && (
                  <optgroup label="Partner Organisations">
                    {orgOptions.map(o => <option key={o} value={o}>{o}</option>)}
                  </optgroup>
                )}
                <optgroup label="Consultants / Third Parties">
                  {FIXED_ENTITIES.map(e => <option key={e} value={e}>{e}</option>)}
                </optgroup>
              </select>
            </Field>
          </div>
        </div>

        {/* Engagement Roles */}
        <SectionHeading>Engagement Roles</SectionHeading>
        <p className="text-xs text-gray-400 -mt-2">
          A stakeholder may hold all three roles simultaneously. The PMO uses these to route review requests and approval gates.
        </p>
        <div className="grid grid-cols-1 gap-2 mt-2">
          <RoleCheckbox
            label="Participant"
            hint="Attends workshops, completes surveys, or takes part in discovery interviews"
            checked={form.is_participant}
            onChange={(v) => set('is_participant', v)}
          />
          <RoleCheckbox
            label="Reviewer"
            hint="Reviews deliverables and provides sign-off comments before a gate can close"
            checked={form.is_reviewer}
            onChange={(v) => set('is_reviewer', v)}
          />
          <RoleCheckbox
            label="Milestone Approver"
            hint="Has authority to formally approve milestone completion and unblock the next phase"
            checked={form.is_approver}
            onChange={(v) => set('is_approver', v)}
          />
        </div>

        {/* Contact */}
        <SectionHeading>Contact</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Email">
            <input value={form.email} onChange={(e) => set('email', e.target.value)} className={INPUT} type="email" />
          </Field>
          <Field label="Mobile (include country prefix)">
            <input
              value={form.mobile}
              onChange={(e) => set('mobile', e.target.value)}
              className={INPUT}
              placeholder="+44 7700 000000"
            />
          </Field>
          <Field label="Slack Handle">
            <input value={form.slack_handle} onChange={(e) => set('slack_handle', e.target.value)} className={INPUT} placeholder="@handle" />
          </Field>
          <Field label="Preferred Comms Channel">
            <select
              value={form.comms_channel}
              onChange={(e) => set('comms_channel', e.target.value as FormData['comms_channel'])}
              className={SELECT}
            >
              <option value="email">Email</option>
              <option value="slack">Slack</option>
              <option value="sms">SMS</option>
            </select>
          </Field>
          <Field label="Preferred Language">
            <select value={form.preferred_language} onChange={(e) => set('preferred_language', e.target.value)} className={SELECT}>
              <option value="">- Select language -</option>
              {LANG_OPTIONS.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </Field>
        </div>

        {/* Project Role */}
        <SectionHeading>Project Role</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Stakeholder Category">
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
        {l1Options.length === 0 ? (
          <p className="text-xs text-gray-400">Run the Value Chain Mapping crew first to populate these options.</p>
        ) : (
          <>
            <MultiCheckbox
              label="Value Chain (L1)"
              options={l1Options.map(a => a.label)}
              value={form.value_streams}
              onChange={(newL1s) => {
                // Recompute valid L2/L3 for the new L1 selection
                const newL1Ids = l1Options.filter(a => newL1s.includes(a.label)).map(a => a.id)
                const l2Still = allActs.find(a => a.level === 'L2' && a.label === form.value_chain_stage && a.parent_id != null && newL1Ids.includes(a.parent_id))
                const l3Still = l2Still && allActs.find(a => a.level === 'L3' && a.label === form.activity && a.parent_id === l2Still.id)
                setForm(f => ({
                  ...f,
                  value_streams: newL1s,
                  value_chain_stage: l2Still ? f.value_chain_stage : '',
                  activity: l3Still ? f.activity : '',
                }))
              }}
            />
            <div className="grid grid-cols-2 gap-4">
              <Field label="Stage (L2)">
                <select
                  value={form.value_chain_stage}
                  onChange={(e) => {
                    const newL2Label = e.target.value
                    const newL2 = allActs.find(a => a.level === 'L2' && a.label === newL2Label)
                    const l3Still = newL2 && allActs.find(a => a.level === 'L3' && a.label === form.activity && a.parent_id === newL2.id)
                    setForm(f => ({ ...f, value_chain_stage: newL2Label, activity: l3Still ? f.activity : '' }))
                  }}
                  className={SELECT}
                >
                  <option value="">- Select stage -</option>
                  {l2Options.map(a => <option key={a.id} value={a.label}>{a.label}</option>)}
                </select>
              </Field>
              <Field label="Activity (L3)">
                <select
                  value={form.activity}
                  onChange={(e) => set('activity', e.target.value)}
                  className={SELECT}
                >
                  <option value="">- Select activity -</option>
                  {l3Options.map(a => <option key={a.id} value={a.label}>{a.label}</option>)}
                </select>
              </Field>
            </div>
          </>
        )}


        {/* Location */}
        <SectionHeading>Location</SectionHeading>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Country">
            <select
              value={form.country_code}
              onChange={(e) => handleCountryChange(e.target.value)}
              className={SELECT}
            >
              <option value="">- Select country -</option>
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
      <div className="mt-8 border-t border-gray-200 pt-4 flex items-center justify-between">
        {error ? <p className="text-sm text-red-400">{error}</p> : <span />}
        <div className="flex gap-3">
          <button onClick={() => navigate(`/${slug}/stakeholders`)} className="text-sm text-gray-400 hover:text-gray-700 px-3 py-1.5">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-1.5 bg-brand hover:bg-brand-dark disabled:opacity-50 text-white text-sm rounded"
          >
            {saving ? 'Saving…' : 'Save Stakeholder'}
          </button>
        </div>
      </div>
    </div>
  )
}
