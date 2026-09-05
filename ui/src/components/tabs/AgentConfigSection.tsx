// ui/src/components/tabs/AgentConfigSection.tsx
//
// What this project calls an agent, shows for it, and gives it to speak with - one section,
// rendered for every agent from its permanent `agent_id`.
//
// **One section, not eighteen copies.** The rule "an override where the project set one, the
// default otherwise" is the same for every agent and for every field, so it is written once.
// A per-agent Setup tab holding its own copy is how five statements of Avery's voice came to
// exist with two of them wrong, and how his interviewing preferences ended up in
// `localStorage` where no server can read them - a setting that never leaves the browser
// cannot reach an interview.
//
// **A value and its provenance are two different things.** An administrator looking at "Avery
// Singh" has to know whether that is a decision this project made or a default it inherited,
// because the two behave differently the next time the default changes. That is the property
// sp58's platform-URL panel established for the deployment address, and it is the same
// property here.
//
// **The form edits overrides, never resolved values.** Saving a resolved default would freeze
// it as this project's own choice, and the agent would silently stop following a rename in
// `agents/identity.py` with nothing on the screen to say why. So a blank control means "no
// override" and sends `null`.
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Mic, RotateCcw, Save } from 'lucide-react'

import { agentConfigApi, type AgentConfigOverrides } from '../../api/agentConfig'
import { projectsApi } from '../../api/endpoints'
import { describeError } from '../../utils/describeError'
import { AGENT_IDS } from '../agentStatus'
import VoicePicker from './VoicePicker'

/** The five fields a text box can express, and what each one is for.
 *
 *  `model_id` is here rather than in some "advanced" corner, and it is labelled for what it
 *  is: the **speech synthesis** model. It is not one of the six LLM model ids on the Settings
 *  page, which decide where this engagement's prompts are sent and are refused to a
 *  project_admin with a 403. Two different things in this product are called a model id and
 *  one of them is a security control - a field labelled just "Model" here would be read as
 *  that one by the consultant who set it a screen away.
 */
const TEXT_FIELDS: {
  field: keyof AgentConfigOverrides
  label: string
  help: string
}[] = [
  {
    field: 'display_name',
    label: 'Display name',
    help: 'What a participant reads, and what this agent signs its correspondence with.',
  },
  {
    field: 'image_url',
    label: 'Image',
    help: 'A path under the dashboard, such as /agents/avery-singh.jpg. Shown to a participant on the interview page.',
  },
  {
    field: 'language',
    label: 'Language',
    help: 'The language this agent speaks and listens in, as a two-letter code - en, fr, de.',
  },
  {
    field: 'country_code',
    label: 'Country',
    help: 'Paired with the language for speech recognition, so a participant is heard as en-GB rather than en-US.',
  },
  {
    field: 'model_id',
    label: 'Speech synthesis model',
    help: "The voice provider's own model, not one of the language models on the Settings page. It exists so a voice in another language is not spoken through an English model.",
  },
]

/** Whether this field is a choice or an inheritance, said on the screen rather than implied.
 *
 *  A default rendered into a filled-in box is indistinguishable from a saved value, and the
 *  difference matters: clear the box and the agent follows whatever the default becomes, leave
 *  a copy of today's default in it and the agent is pinned to it for ever.
 */
function Provenance({ overridden, fallback }: { overridden: boolean; fallback: string }) {
  return (
    <span
      data-testid="provenance"
      className={
        overridden
          ? 'px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-brand/10 text-teal-700'
          : 'px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-600'
      }
    >
      {overridden ? 'set for this project' : `default${fallback ? ` - ${fallback}` : ''}`}
    </span>
  )
}

export default function AgentConfigSection({
  slug,
  agentName,
}: {
  slug: string
  /** The role key the rest of the front end is arranged by, such as 'Stakeholder Interviewer'. */
  agentName: string
}) {
  const agentId = AGENT_IDS[agentName]
  const qc = useQueryClient()
  const [draft, setDraft] = useState<AgentConfigOverrides | null>(null)
  const [picking, setPicking] = useState(false)
  // The name of a voice chosen in this session, shown beside the id it stores. Display only:
  // the id is what the project holds, and naming a stored id would mean listing every voice
  // in the account on every Setup tab.
  const [chosenVoiceName, setChosenVoiceName] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const { data: config } = useQuery({
    queryKey: ['agent-config', slug, agentId],
    queryFn: () => agentConfigApi.get(slug, agentId),
    enabled: !!slug && !!agentId,
  })

  // Whether the server would accept the save, asked rather than inferred - the same predicate
  // `PUT /{slug}/agents/{agent_id}/config` refuses with. A control that always 403s is worse
  // than a control that says why it is greyed out.
  const { data: permissions } = useQuery({
    queryKey: ['my-permissions', slug],
    queryFn: () => projectsApi.getMyPermissions(slug),
    enabled: !!slug,
  })
  // An unanswered question locks. A control enabled for the moment the answer takes is a
  // control that can be changed and then refused, which is the failure the gating prevents.
  const mayAdminister = permissions?.can_administer_project ?? false

  useEffect(() => {
    if (config) setDraft(config.overrides)
  }, [config])

  const save = useMutation({
    mutationFn: (overrides: AgentConfigOverrides) =>
      agentConfigApi.put(slug, agentId, overrides),
    onSuccess: (updated) => {
      qc.setQueryData(['agent-config', slug, agentId], updated)
      setDraft(updated.overrides)
      setError(null)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    },
    onError: (err) => setError(describeError(err, 'The configuration could not be saved.')),
  })

  if (!agentId) return null
  if (!config || !draft) {
    return <p className="text-xs text-gray-400">Loading this agent's configuration…</p>
  }

  // A blank box means "no override", not "an empty name". The table draws that distinction and
  // this control cannot express both, so it expresses the one an administrator needs: clearing
  // a field returns the agent to its default. An empty-string override stays reachable through
  // the API for anything that genuinely wants one.
  const set = (field: keyof AgentConfigOverrides, value: string) =>
    setDraft({ ...draft, [field]: value === '' ? null : value })

  const voiceId = draft.voice_id ?? config.defaults.voice_id
  const inputCls =
    'w-full bg-white border border-gray-200 rounded px-2.5 py-1.5 text-xs text-gray-900 outline-none focus:border-brand disabled:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed'

  return (
    <div className="space-y-4" data-testid={`agent-config-${agentId}`}>
      <p className="text-[11px] text-gray-500 leading-relaxed">
        What this project calls {config.defaults.display_name}, shows for them, and gives them
        to speak with. Each field falls back to the agent's own default until this project sets
        one, so leaving a box empty is a decision to follow the default rather than a gap.
      </p>

      {!mayAdminister && (
        <p
          data-testid="agent-config-locked"
          className="text-[11px] text-gray-500 bg-gray-50 border border-gray-200 rounded px-2 py-1.5"
        >
          Only somebody who administers this project may change these. You are seeing what the
          agent resolves to today.
        </p>
      )}

      <div className="grid grid-cols-2 gap-3">
        {TEXT_FIELDS.map(({ field, label, help }) => (
          <div key={field}>
            <div className="flex items-center gap-2 mb-1">
              <label
                htmlFor={`${agentId}-${field}`}
                className="text-[10px] font-bold text-gray-400 uppercase tracking-widest"
              >
                {label}
              </label>
              <Provenance
                overridden={draft[field] !== null}
                fallback={config.defaults[field] ?? ''}
              />
            </div>
            <input
              id={`${agentId}-${field}`}
              type="text"
              disabled={!mayAdminister}
              value={draft[field] ?? ''}
              placeholder={config.defaults[field] ?? ''}
              onChange={(e) => set(field, e.target.value)}
              className={inputCls}
            />
            <p className="text-[10px] text-gray-400 mt-1 leading-relaxed">{help}</p>
          </div>
        ))}
      </div>

      <div>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
            Voice
          </span>
          <Provenance
            overridden={draft.voice_id !== null}
            fallback={config.defaults.voice_id ?? 'none - this agent does not speak'}
          />
        </div>
        <div className="flex items-center gap-2">
          <span data-testid="voice-id" className="font-mono text-[11px] text-gray-700">
            {voiceId ?? 'none'}
          </span>
          {chosenVoiceName && (
            <span className="text-[11px] text-gray-500">{chosenVoiceName}</span>
          )}
          <button
            type="button"
            disabled={!mayAdminister}
            onClick={() => setPicking((open) => !open)}
            className="flex items-center gap-1 px-2 py-1 border border-gray-200 rounded text-[11px] text-gray-700 disabled:opacity-40"
          >
            <Mic size={11} aria-hidden="true" />
            {picking ? 'Close the voice picker' : 'Choose a voice'}
          </button>
          {draft.voice_id !== null && (
            <button
              type="button"
              disabled={!mayAdminister}
              onClick={() => {
                setDraft({ ...draft, voice_id: null })
                setChosenVoiceName(null)
              }}
              className="flex items-center gap-1 px-2 py-1 border border-gray-200 rounded text-[11px] text-gray-700 disabled:opacity-40"
            >
              <RotateCcw size={11} aria-hidden="true" />
              Use the default voice
            </button>
          )}
        </div>
      </div>

      {picking && (
        <VoicePicker
          slug={slug}
          currentVoiceId={voiceId}
          onChoose={(id, name) => {
            setDraft({ ...draft, voice_id: id })
            setChosenVoiceName(name)
            setPicking(false)
          }}
          onClose={() => setPicking(false)}
        />
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={!mayAdminister || save.isPending}
          onClick={() => save.mutate(draft)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-brand hover:bg-brand-dark text-white text-xs font-medium rounded disabled:opacity-40"
        >
          <Save size={12} aria-hidden="true" />
          Save configuration
        </button>
        {saved && <span className="text-emerald-500 text-xs">Saved.</span>}
        {error && <span className="text-red-500 text-xs">{error}</span>}
      </div>
    </div>
  )
}
