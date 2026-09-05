import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Lock } from 'lucide-react'
import { projectsApi } from '../api/endpoints'
import type { ProjectSettings } from '../types'
import { describeError } from '../utils/describeError'
import { SUPPORTED_LOCALES } from '../utils/holidays'

const DEFAULT_PRIMARY_COLOR = '#0d9488'  // must match api/models.py default
const DEFAULT_TEXT_COLOR = '#1f2937'

const DEFAULTS: ProjectSettings = {
  llm_mode: 'standard',
  force_local_inference: false,
  // Matches api/models.py's default. It has no control on this page - it is here so the
  // form carries it, which is the only thing standing between a save and a silently
  // re-enabled mail hold.
  dev_mode: true,
  locale: 'GB',
  sector: '',
  stakeholder_groups: [],
  value_stream_labels: [],
  roadmap_time_axis: 'quarters',
  review_gates: true,
  slack_channel: '',
  discovery_brief: '',
  discovery_links: [],
  discovery_document_ids: [],
  interview_method: 'none',
  // Both match api/models.py's defaults, which test_the_frontend_defaults_are_the_models_
  // defaults holds them to. Neither is platform-tier: they decide the tone of a conversation,
  // not where this engagement's material is sent.
  interviewer_selection: 'random',
  interview_accent: 'british',
  elaboration_press_timeout_seconds: 8,
  anthropic_fast_model: 'anthropic/claude-haiku-4-5-20251001',
  anthropic_deep_model: 'anthropic/claude-opus-4-6',
  local_fast_model: 'gemma4:fast',
  local_fast_url: 'http://localhost:11434/v1',
  local_deep_model: 'qwen27b:reasoning',
  local_deep_url: 'http://localhost:11434/v1',
}

function TagInput({
  value,
  onChange,
  id,
  disabled,
}: {
  value: string[]
  onChange: (v: string[]) => void
  // Taken from fieldProps at the call site like every other control on this page, so a tag
  // field is gated by the same rule as an input rather than by being forgotten.
  id: string
  disabled: boolean
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
          {/* not-a-settings-control: removes one tag from the list its parent owns. It is
              still gated - `disabled` is the caller's fieldProps, threaded in as a prop -
              but the field is the parent's, not this button's. */}
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange(value.filter((t) => t !== tag))}
            className="text-teal-600 hover:text-gray-900 leading-none disabled:opacity-50 disabled:cursor-not-allowed"
          >
            ×
          </button>
        </span>
      ))}
      {/* not-a-settings-control: edits the pending tag, not a settings field. The id and
          disabled it wears are the caller's fieldProps, threaded in as props. */}
      <input
        id={id}
        disabled={disabled}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKey}
        placeholder="Add…"
        className="bg-transparent text-sm text-gray-700 outline-none min-w-[80px] flex-1 disabled:cursor-not-allowed"
      />
    </div>
  )
}

// The Models section's fields, hoisted so the inputs and the "why is this greyed out" note
// are driven from one array. Which of them are platform-tier is not decided here - the
// server answers that per field, and this is only the order they render in.
const MODEL_FIELDS: [keyof ProjectSettings, string][] = [
  ['anthropic_fast_model', 'Hosted fast model'],
  ['anthropic_deep_model', 'Hosted deep model'],
  ['local_fast_model', 'Local fast model'],
  ['local_fast_url', 'Local fast URL'],
  ['local_deep_model', 'Local deep model'],
  ['local_deep_url', 'Local deep URL'],
]

/** Why a platform-tier control is greyed out. One sentence in one place - a disabled control
 *  with no reason beside it reads as a bug, and the operator's next move is to report the
 *  page rather than to ask somebody.
 *
 *  `explains` names the fields this particular note accounts for, and it is not decoration.
 *  The first version of the test asserted a note existed somewhere in the control's enclosing
 *  `<section>`, which is a weaker property than it reads as: the General section already held
 *  notes for `sector` and `llm_mode`, so a newly locked `locale` was covered by a note that
 *  had nothing to do with it and the assertion passed with no explanation beside the greyed
 *  control. Naming the fields makes the association something the DOM carries rather than
 *  something proximity implies, and `every locked control has a note that names it` then
 *  fails for the field nobody accounted for.
 *
 *  The sentence still says what the fields have in common rather than listing them - which
 *  fields they are is the server's answer and changes without this file. */
function PlatformTierNote({ explains }: { explains: (keyof ProjectSettings)[] }) {
  return (
    <p
      data-explains={explains.join(' ')}
      className="text-xs text-gray-400 mt-1 flex items-center gap-1"
    >
      <Lock size={12} />
      Only an org admin or above may change where this engagement's data is sent.
    </p>
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

  const { data: settings, isError: settingsFailed, error: settingsError } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug!),
    enabled: !!slug,
  })

  // What the server would accept, asked rather than inferred. The platform-tier fields on
  // this body - llm_mode, force_local_inference, the model ids - are refused to a
  // project_admin, so the toggle below is read-only for one rather than an action that
  // always 403s. The rule is the server's (`is_org_admin_or_above`, the same predicate
  // patch_settings_endpoint decides with) and is never restated here.
  const { data: permissions } = useQuery({
    queryKey: ['my-permissions', slug],
    queryFn: () => projectsApi.getMyPermissions(slug!),
    enabled: !!slug,
  })
  const mayChangePlatformTierSettings = permissions?.can_change_platform_tier_settings ?? false
  // Which fields that covers is the server's answer too, never a list written here - see
  // MyPermissions.platform_tier_settings. `null` until it arrives, and an unanswered
  // question locks: a control enabled for the moment the answer takes is a control that can
  // be changed and then refused, which is the thing this gating exists to prevent.
  const platformTierFields = permissions ? new Set(permissions.platform_tier_settings) : null
  const locked = (field: keyof ProjectSettings) =>
    platformTierFields === null
    || (!mayChangePlatformTierSettings && platformTierFields.has(field))

  /**
   * The two attributes every control on this page wears, derived from the field it edits.
   *
   * This exists because threading `disabled={locked(field)}` onto controls **by hand** is
   * not the same property as gating them, and the difference was caught by review: with
   * `locked()` applied only to the three controls somebody remembered, adding a tenth field
   * to the server's tuple left its control fully editable while every test stayed green.
   * The claim "a new platform-tier field locks its control with no frontend change" was
   * false, and it was false in the direction that matters - the page offered a control the
   * server would refuse.
   *
   * So the asking is not optional here: a control gets its `id` from the same call that
   * decides its `disabled`, and a control with no id is a control nobody can find. The two
   * arrive together or not at all. `tests/test_settings_platform_tier_wiring.py` walks
   * this file and fails on any control that renders without calling this.
   *
   * `variant` exists for a field rendered as several controls - a radio group - where one
   * shared id would be a duplicate. The gate is still the field's.
   */
  const fieldProps = (field: keyof ProjectSettings, variant?: string) => ({
    id: variant ? `${field}-${variant}` : field,
    disabled: locked(field),
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
    // The server's own sentence. A project_admin who changes a platform-tier field is
    // refused with a 403 that *names the fields* - "force_local_inference may only be
    // changed by an org admin or above" - and "Save failed. Please try again." both hides
    // which field and reads as a transient fault the operator should retry.
    onError: (err) => setError(describeError(err, 'Save failed. Please try again.')),
  })

  if (!slug) return null

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
      <h2 className="text-lg font-semibold text-gray-900">Settings - {slug}</h2>

      {/* General */}
      <section className="space-y-4">
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest">General</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="sector" className="text-xs text-gray-600 block mb-1">Sector</label>
            <input
              {...fieldProps('sector')}
              value={form.sector}
              onChange={(e) => setForm({ ...form, sector: e.target.value })}
              className="w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand disabled:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed"
            />
            {locked('sector') && <PlatformTierNote explains={['sector']} />}
          </div>
          <div>
            <label htmlFor="llm_mode" className="text-xs text-gray-600 block mb-1">LLM Mode</label>
            <select
              {...fieldProps('llm_mode')}
              value={form.llm_mode}
              onChange={(e) =>
                setForm({ ...form, llm_mode: e.target.value as ProjectSettings['llm_mode'] })
              }
              className="w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand disabled:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed"
            >
              <option value="standard">standard</option>
              <option value="sensitive">sensitive</option>
              <option value="fallback">fallback</option>
            </select>
            {locked('llm_mode') && <PlatformTierNote explains={['llm_mode']} />}
          </div>
          <div>
            <label htmlFor="locale" className="text-xs text-gray-600 block mb-1">Project locale</label>
            <select
              {...fieldProps('locale')}
              value={form.locale ?? 'GB'}
              onChange={(e) => setForm({ ...form, locale: e.target.value })}
              className="w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand disabled:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed"
            >
              {SUPPORTED_LOCALES.map(l => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="roadmap_time_axis" className="text-xs text-gray-600 block mb-1">Roadmap Time Axis</label>
            <select
              {...fieldProps('roadmap_time_axis')}
              value={form.roadmap_time_axis}
              onChange={(e) =>
                setForm({
                  ...form,
                  roadmap_time_axis: e.target.value as ProjectSettings['roadmap_time_axis'],
                })
              }
              className="w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand disabled:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed"
            >
              <option value="quarters">quarters</option>
              <option value="years">years</option>
              <option value="horizons">horizons</option>
            </select>
          </div>
          <div>
            <label htmlFor="slack_channel" className="text-xs text-gray-600 block mb-1">Slack Channel</label>
            <input
              {...fieldProps('slack_channel')}
              value={form.slack_channel}
              onChange={(e) => setForm({ ...form, slack_channel: e.target.value })}
              className="w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand disabled:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed"
            />
          </div>
        </div>
      </section>

      {/* Local inference override. Platform tier, beside the mode it narrows.
          The label says what the flag does and, just as deliberately, what it does not:
          it moves the model calls and nothing else. An operator who reads "local" as
          "on-premises everything" would expect their Chroma Cloud documents to have
          moved, which is the misreading this whole setting exists to avoid - it is a
          narrowing of one capability, not a fourth deployment mode. The second sentence
          names the control that *does* move them, because the honest answer to "how do I
          keep the documents here too" is a different setting, not this one. */}
      <section className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-gray-900">Force local inference</p>
          <p className="text-xs text-muted leading-relaxed max-w-lg">
            Every agent on this project runs on the local models set under Models below,
            whatever the LLM mode says. It moves the model calls only - documents stay
            wherever the mode puts them, so a standard project keeps its documents in Chroma
            Cloud. Switching the mode to sensitive is what moves those.
          </p>
          {locked('force_local_inference') && <PlatformTierNote explains={['force_local_inference']} />}
        </div>
        <button
          type="button"
          role="switch"
          {...fieldProps('force_local_inference')}
          aria-label="Force local inference"
          aria-checked={form.force_local_inference}
          onClick={() =>
            setForm({ ...form, force_local_inference: !form.force_local_inference })
          }
          className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
            form.force_local_inference ? 'bg-brand' : 'bg-gray-300'
          }`}
        >
          <span
            className={`inline-block h-4 w-4 mt-0.5 rounded-full bg-white shadow transition-transform ${
              form.force_local_inference ? 'translate-x-4' : 'translate-x-0.5'
            }`}
          />
        </button>
      </section>

      {/* Tag fields */}
      <section className="grid grid-cols-2 gap-4">
        <div>
          <label htmlFor="stakeholder_groups" className="text-xs text-gray-600 block mb-1">Stakeholder Groups</label>
          <TagInput
            {...fieldProps('stakeholder_groups')}
            value={form.stakeholder_groups}
            onChange={(v) => setForm({ ...form, stakeholder_groups: v })}
          />
        </div>
        <div>
          <label htmlFor="value_stream_labels" className="text-xs text-gray-600 block mb-1">Value Stream Labels</label>
          <TagInput
            {...fieldProps('value_stream_labels')}
            value={form.value_stream_labels}
            onChange={(v) => setForm({ ...form, value_stream_labels: v })}
          />
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
          role="switch"
          {...fieldProps('review_gates')}
          aria-label="Review Gates"
          aria-checked={form.review_gates}
          onClick={() => setForm({ ...form, review_gates: !form.review_gates })}
          className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
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
                ['none', 'None - skip interview phase'],
                ['agent', 'Agent interviews (platform conducts voice interviews)'],
              ] as [ProjectSettings['interview_method'], string][]
            ).map(([value, label]) => (
              <label key={value} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input
                  {...fieldProps('interview_method', value)}
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

        <div>
          <label htmlFor="interviewer_selection" className="text-xs text-gray-600 block mb-1">
            Who conducts the interview
          </label>
          <select
            {...fieldProps('interviewer_selection')}
            value={form.interviewer_selection}
            onChange={(e) =>
              setForm({
                ...form,
                interviewer_selection: e.target
                  .value as ProjectSettings['interviewer_selection'],
              })
            }
            className="w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand disabled:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed"
          >
            <option value="random">Either interviewer, chosen per session</option>
            <option value="always_male">Always the male interviewer</option>
            <option value="always_female">Always the female interviewer</option>
          </select>
          <p className="text-xs text-muted mt-1">
            Decided once when a session is created and recorded on it, so a participant who
            returns to their link meets the same person. Which interviewer has which voice is
            read from the voice itself, never from a list held here.
          </p>
        </div>

        <div>
          <label htmlFor="interview_accent" className="text-xs text-gray-600 block mb-1">
            Interview accent
          </label>
          <input
            {...fieldProps('interview_accent')}
            type="text"
            value={form.interview_accent}
            onChange={(e) => setForm({ ...form, interview_accent: e.target.value })}
            placeholder="british"
            className="w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand disabled:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed"
          />
          {/* Deliberately names no accent. The five this deployment happens to reach were
              written out here in the first draft, inside the very sentence explaining that the
              vocabulary is the provider's - a voice fact restated in TypeScript, on the one
              side Task 4's Python guard cannot see, in the paragraph predicting it would go
              stale. The accents that exist are `accent_options` on the voices door, and the
              picker on each agent's Setup tab renders them; this page does not call that door
              and should not start, so it points at the place that does rather than keeping a
              copy that nothing compares. */}
          <p className="text-xs text-muted mt-1">
            The accent this project's voices are chosen from, in the voice provider's own word
            for it. Free text rather than a list, because the vocabulary is theirs and closing
            it here would go stale the first time they add one - the accents that actually
            exist are offered in the voice picker on each agent's Setup tab. Leave it empty to
            search every accent. It is not the country above: GB is the country of a Scottish
            engagement exactly as it is of a British one.
          </p>
        </div>

        <div>
          <label
            htmlFor="elaboration_press_timeout_seconds"
            className="text-xs text-gray-600 block mb-2"
          >
            Follow-up time limit (seconds)
          </label>
          <input
            {...fieldProps('elaboration_press_timeout_seconds')}
            type="number"
            min={1}
            max={60}
            value={form.elaboration_press_timeout_seconds}
            onChange={(e) =>
              setForm({
                ...form,
                elaboration_press_timeout_seconds: Number(e.target.value),
              })
            }
            className="w-24 bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand disabled:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed"
          />
          <p className="text-xs text-muted mt-1">
            How long Avery waits for a follow-up question before moving on. A local model in
            secure mode needs longer than the hosted one.
          </p>
        </div>
      </section>

      {/* Models */}
      <section className="mt-6">
        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest">Models</h3>
        <p className="text-xs text-muted mt-1 mb-3">
          Fast models handle coordination and live follow-ups. Deep models handle analysis
          across a whole campaign. Sensitive projects use the local pair and never the hosted
          ones.
        </p>
        {MODEL_FIELDS.map(([key, label]) => (
          <div key={key} className="mb-3">
            <label htmlFor={key} className="text-xs text-gray-600 block mb-1">{label}</label>
            <input
              {...fieldProps(key)}
              type="text"
              value={String(form[key] ?? '')}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-brand disabled:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed"
            />
          </div>
        ))}
        {/* Once for the section rather than once per input: six identical notes under six
            adjacent fields is noise, and they are locked by one rule for one reason. Asked
            of the same array the inputs are rendered from, so it cannot answer for a
            different set of fields than the ones on screen. */}
        {MODEL_FIELDS.some(([key]) => locked(key))
          && <PlatformTierNote explains={MODEL_FIELDS.map(([key]) => key)} />}
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
              {...fieldProps('brand_header_image_url')}
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={() => { setImageStatus(''); setImageError(false) }}
              className="text-sm text-gray-600 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-gray-100 file:text-gray-700 hover:file:bg-gray-200"
            />
            {/* not-a-settings-control: uploads the file the input beside it holds. It acts
                rather than edits - the field is the file input's. */}
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
                {...fieldProps('brand_primary_color')}
                type="color"
                value={form.brand_primary_color ?? DEFAULT_PRIMARY_COLOR}
                onChange={(e) => setForm({ ...form, brand_primary_color: e.target.value })}
                className="h-8 w-10 rounded border border-gray-200 bg-white cursor-pointer p-0.5 disabled:cursor-not-allowed"
              />
              <span className="text-xs text-gray-400 font-mono">{form.brand_primary_color ?? DEFAULT_PRIMARY_COLOR}</span>
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">Text Colour</label>
            <div className="flex items-center gap-2">
              <input
                {...fieldProps('brand_text_color')}
                type="color"
                value={form.brand_text_color ?? DEFAULT_TEXT_COLOR}
                onChange={(e) => setForm({ ...form, brand_text_color: e.target.value })}
                className="h-8 w-10 rounded border border-gray-200 bg-white cursor-pointer p-0.5 disabled:cursor-not-allowed"
              />
              <span className="text-xs text-gray-400 font-mono">{form.brand_text_color ?? DEFAULT_TEXT_COLOR}</span>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <div className="border-t border-gray-200 pt-4 flex items-center justify-between">
        {/* Save stays disabled until the settings arrive, so a load that *fails* disables it
            for good - correct, and mute. An operator looking at a permanently dead Save with
            no message has no way to tell a permission problem from a dropped connection, and
            the server's own sentence is the only thing that can say which: "Access denied to
            this project" and a network error are the same greyed button otherwise. */}
        {settingsFailed
          ? (
            <p className="text-sm text-red-400">
              {describeError(settingsError, 'Could not load these settings.')}
              {' '}Saving is disabled until they load - reload the page to try again.
            </p>
          )
          : error ? <p className="text-sm text-red-400">{error}</p> : <span />}
        {/* `!settings` is the whole of this task's own lesson applied one layer up, and the
            page had it on the permissions query and not on this one. Until `GET /settings`
            answers, `form` holds DEFAULTS - standard mode, no override, a blank sector,
            stock model ids and no dev_mode - and the body is a *whole* settings model, so an
            early click does not save nothing, it saves all of that over whatever the project
            really is. A platform-tier caller's is accepted: one click and a sensitive,
            forced engagement is standard and hosted, with nothing refused and nothing said.
            An unanswered question locks here too. */}
        {/* not-a-settings-control: submits the whole body. It edits no field, and its own
            disabled condition is about the form's readiness rather than about authority. */}
        <button
          onClick={() => mutation.mutate(form)}
          disabled={mutation.isPending || !settings}
          className="px-4 py-1.5 bg-brand hover:bg-brand-dark disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded"
        >
          {saved ? 'Saved!' : mutation.isPending ? 'Saving…' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}
