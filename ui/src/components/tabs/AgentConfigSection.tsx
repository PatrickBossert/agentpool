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
import { FlaskConical, ImagePlus, Mic, RotateCcw, Save } from 'lucide-react'

import {
  agentConfigApi,
  type AgentConfigOverrides,
  type PortraitUpload,
} from '../../api/agentConfig'
import { projectsApi } from '../../api/endpoints'
import { describeError } from '../../utils/describeError'
import { useAgentIdentity } from '../../hooks/useAgentIdentity'
import { AGENT_IDS } from '../agentStatus'
import TestInterviewDialog from './TestInterviewDialog'
import VoicePicker from './VoicePicker'
import { voicesApi } from '../../api/voices'

/** The three types the upload door accepts, so the file dialog opens filtered to them.
 *
 *  A convenience and never a control: a person can defeat `accept` by typing a filename, and
 *  the server validates the declared type, the first four bytes, and then the decoded format
 *  regardless. Restated here rather than fetched because it is a hint about a dialog, not a
 *  rule - the rule lives in `api/services/image_intake.py` and is enforced there.
 */
const PORTRAIT_ACCEPT = 'image/png,image/jpeg,image/webp'

/** A file size an administrator can read at a glance. Decimal, as every operating system's
 *  file dialog reports it, so the number beside the filename matches the one they just saw. */
function readableSize(bytes: number): string {
  if (bytes < 1000) return `${bytes} bytes`
  if (bytes < 1000 * 1000) return `${(bytes / 1000).toFixed(0)} kB`
  return `${(bytes / (1000 * 1000)).toFixed(1)} MB`
}

/** A save that failed on the **upload** half rather than on the configuration half.
 *
 *  The two are told apart on the screen because they need different actions: a refused portrait
 *  means try another file, and a refused save means ask for authority. Without the distinction
 *  an administrator whose 12 MB photograph was rejected is told the configuration could not be
 *  saved, and goes looking for a permissions problem that is not there.
 */
class PortraitUploadFailed extends Error {}

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
    help: 'Shown to a participant on the interview page. Choose an image below and it is stored on this deployment; typing a path such as /agents/avery-singh.jpg still works.',
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
  // A portrait chosen but not yet sent. It is uploaded when the configuration is saved, not
  // when it is chosen, so that one action means one outcome: an administrator who picks the
  // wrong file and navigates away has changed nothing on the server.
  const [pendingImage, setPendingImage] = useState<File | null>(null)
  // The rehearsal dialog, mounted only once it is asked for. Mounting it always would fetch a
  // script and post a `/test/speak` the moment anybody opened the Agents tab.
  const [rehearsing, setRehearsing] = useState(false)
  // What the last upload actually cost, kept so the downscale is visible. An administrator who
  // is never told their 8 MB photograph became 74 kB uploads the same 8 MB file again.
  const [uploaded, setUploaded] = useState<PortraitUpload | null>(null)

  // `error` is read as well as `data`, and the pair is what separates "still arriving" from
  // "never arriving". Reading `data` alone made a failed read and a pending one render the
  // same sentence, and in production they were not the same thing at all: the API had been
  // up since before this door existed, answered 404 to every section, and an administrator
  // was told to wait for something that was never coming.
  const { data: config, error: loadError } = useQuery({
    queryKey: ['agent-config', slug, agentId],
    queryFn: () => agentConfigApi.get(slug, agentId),
    enabled: !!slug && !!agentId,
  })

  // A voice is stored as an id and read by a person. `Xb7hH8MSUJpSbSDYk0k2` tells an
  // administrator nothing about who they have chosen, and the id was the only thing on the
  // screen unless the voice happened to be picked in this same session.
  //
  // Asked with `accent: ''` - every accent, not the project's - because the stored voice need
  // not share the project's. The **account** listing is the right source: "Add to account and
  // use" copies a library voice in, so anything a project can have configured is in it.
  //
  // Its own query rather than the picker's: the picker's key carries the accent, gender and
  // search terms it is filtering by, so sharing it would make the name on this line depend on
  // what somebody last typed into a dropdown.
  const { data: catalogue } = useQuery({
    queryKey: ['voice-names', slug],
    queryFn: () => voicesApi.list(slug, { accent: '' }),
    enabled: !!slug,
    staleTime: 5 * 60_000,
  })

  const voiceName = (id: string | null | undefined): string | null => {
    if (!id) return null
    const all = [...(catalogue?.account ?? []), ...(catalogue?.library ?? [])]
    return all.find((v) => v.voice_id === id)?.name ?? null
  }

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

  // The name and face to rehearse under, asked of the one place that answers it for the whole
  // dashboard. Not re-derived from `config` here, though it is sitting right there: the rule is
  // "the override, then the static map, never the server's resolved value", because the
  // resolved default is `/agents/laura-nelson.jpg` while Vite serves `ui/public` under
  // `/dashboard` - so drawing the resolved value 404s for every agent without an override.
  // `useAgentIdentity` states that once, shares this page's existing query, and is where a
  // second copy of the rule would be free to drift from the first.
  const { name: humanName, imageUrl } = useAgentIdentity(slug)(agentName)

  useEffect(() => {
    if (config) setDraft(config.overrides)
  }, [config])

  // Two calls, in one order, and the order is the whole of Step 8b.
  //
  // The portrait goes first because its answer is an input to the second call: the upload door
  // stores the file and returns the URL that serves it, and `PUT .../config` is what writes
  // that URL onto the row. Saving first and uploading afterwards would record an address for a
  // file that may never arrive.
  //
  // **A failed upload stops the save.** Continuing would write whatever `image_url` the draft
  // was already holding - a stale address, or nothing at all - while the administrator was
  // looking at the filename they had just chosen, and the section would then render as though
  // the portrait had been accepted.
  const save = useMutation({
    mutationFn: async (overrides: AgentConfigOverrides) => {
      let next = overrides
      let portrait: PortraitUpload | null = null
      if (pendingImage) {
        try {
          portrait = await agentConfigApi.uploadImage(slug, agentId, pendingImage)
        } catch (err) {
          // describeError, imported rather than copied: the door's refusals say which type was
          // sent, or which limit was exceeded, and no fixed string can.
          throw new PortraitUploadFailed(
            describeError(err, 'The image could not be uploaded, so nothing was saved.'),
          )
        }
        next = { ...overrides, image_url: portrait.url }
      }
      return { config: await agentConfigApi.put(slug, agentId, next), portrait }
    },
    onSuccess: ({ config: updated, portrait }) => {
      qc.setQueryData(['agent-config', slug, agentId], updated)
      // The batch every face and name on the dashboard is drawn from. Without this the nine
      // display sites go on showing the old portrait until the page is reloaded - which is a
      // milder version of the exact defect this task repairs, and would read to an
      // administrator as the save not having worked.
      qc.invalidateQueries({ queryKey: ['agent-config-all', slug] })
      setDraft(updated.overrides)
      if (portrait) {
        setUploaded(portrait)
        setPendingImage(null)
      }
      setError(null)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    },
    onError: (err) =>
      setError(
        err instanceof PortraitUploadFailed
          ? `The image could not be uploaded, so nothing was saved - ${err.message}`
          : describeError(err, 'The configuration could not be saved.'),
      ),
  })

  if (!agentId) return null
  // Before the loading branch, deliberately: a failed read has data of `undefined` too, so
  // testing `!config` first would answer "loading" for ever. describeError is imported, not
  // copied, so a refusal that says which authority is missing reaches the administrator in
  // the server's own words rather than as a fixed string.
  if (loadError) {
    // The sentence is stated and the server's words are *appended*, which is the opposite of
    // how the save path uses describeError - and deliberately so. A refusal to save says
    // something a fixed string cannot ("Project administration required"), and stands alone.
    // A failed read is usually the transport talking: `Not Found` on its own is as unhelpful
    // as the endless "Loading…" it replaces, and reads as intentional rather than broken.
    // describeError stays the only place the server's sentence is extracted - passing an
    // empty fallback asks it for that sentence and nothing else.
    const detail = describeError(loadError, '')
    return (
      <p className="text-xs text-rose-400">
        This agent&rsquo;s configuration could not be loaded.
        {detail ? ` - ${detail}` : ''}
      </p>
    )
  }
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
            {field === 'image_url' && (
              // The selector sits beside the field it fills in, not in a corner of its own -
              // it is the ordinary way to set this value and the text box is the escape hatch.
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <label
                  htmlFor={`${agentId}-portrait`}
                  className={`flex items-center gap-1 px-2 py-1 border border-gray-200 rounded text-[11px] text-gray-700 ${
                    mayAdminister
                      ? 'cursor-pointer hover:border-brand'
                      : 'opacity-40 cursor-not-allowed'
                  }`}
                >
                  <ImagePlus size={11} aria-hidden="true" />
                  Choose image…
                </label>
                {/*
                  The native control, styled out of the way rather than replaced. `sr-only`
                  keeps it a real, focusable input in the accessibility tree - `display: none`
                  would take it out of both, leaving the keyboard and a screen reader with a
                  label pointing at nothing.

                  `accept` filters the dialog to the three types the door takes. It is a
                  convenience, never a control: a person can defeat it by typing a filename,
                  and the server checks the declared type, the first four bytes and the decoded
                  format regardless.
                */}
                <input
                  id={`${agentId}-portrait`}
                  type="file"
                  accept={PORTRAIT_ACCEPT}
                  disabled={!mayAdminister}
                  onChange={(e) => {
                    setPendingImage(e.target.files?.[0] ?? null)
                    setUploaded(null)
                  }}
                  className="sr-only"
                />
                {pendingImage ? (
                  <span data-testid="pending-portrait" className="text-[11px] text-gray-600">
                    {pendingImage.name} - {readableSize(pendingImage.size)}, uploaded when you
                    save this configuration.
                  </span>
                ) : (
                  uploaded && (
                    <span data-testid="stored-portrait" className="text-[11px] text-gray-600">
                      Stored - {readableSize(uploaded.original_bytes)} downscaled to{' '}
                      {readableSize(uploaded.bytes)}.
                    </span>
                  )
                )}
              </div>
            )}
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
            fallback={
              voiceName(config.defaults.voice_id)
              ?? config.defaults.voice_id
              ?? 'none - this agent does not speak'
            }
          />
        </div>
        <div className="flex items-center gap-2">
          {/* The name leads and the id follows it, quietly. `chosenVoiceName` is preferred over
              the catalogue for one reason: a voice picked a moment ago is named before the
              listing has been re-fetched, so the line answers immediately instead of showing
              an id that turns into a name a second later.

              The id remains on the screen rather than only in a tooltip - it is what the
              project stores, it is what a support conversation or a database row will quote,
              and hiding it would trade one unreadable line for one unquotable one. */}
          <span data-testid="voice-name" className="text-[11px] font-medium text-gray-800">
            {chosenVoiceName ?? voiceName(voiceId) ?? (voiceId ? 'Unknown voice' : 'none')}
          </span>
          {voiceId && (
            <span
              data-testid="voice-id"
              title="The identifier this project stores for the voice"
              className="font-mono text-[10px] text-gray-400"
            >
              {voiceId}
            </span>
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

      {/*
        Rehearsing an interview, for the agents that conduct one.

        **`is_interviewer` is read, never re-derived.** The roster lives once, in
        `interviewer_selection`, and both the per-agent and the bulk configuration doors already
        answer it - so a list of agent ids in TypeScript would be a second roster on the one
        side nothing is watching, and it would be wrong the first time an interviewer is added.

        **Not gated on `mayAdminister`**, unlike every control above it. `POST
        /api/interviews/test/speak` asks `check_project_access` and nothing else, so rehearsing
        is reading rather than configuring; greying this out would refuse somebody the server
        would have served.

        It used to live on Avery's own Setup tab, and that is precisely why the dialog could
        hardcode his photograph in five renders and his name in three lines and still look
        correct. One route, and it carries whose rehearsal it is.
      */}
      {config.is_interviewer && (
        <div className="border-t border-gray-100 pt-4 flex items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">
              Test interview
            </p>
            <p className="text-[11px] text-gray-500 leading-relaxed max-w-sm">
              Rehearse a short interview with {humanName} using the sample script. They ask real
              questions in the voice configured above and you answer aloud - a way to hear this
              configuration before a participant does.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setRehearsing(true)}
            className="flex items-center gap-1.5 flex-shrink-0 px-3 py-1.5 bg-brand hover:bg-brand-dark text-white text-xs font-medium rounded"
          >
            <FlaskConical size={12} aria-hidden="true" />
            Test interview
          </button>
        </div>
      )}

      {rehearsing && (
        <TestInterviewDialog
          slug={slug}
          agentId={agentId}
          displayName={humanName}
          imageUrl={imageUrl}
          // This agent's country, not the project's. It decides which BCP-47 tag the browser
          // listens in, and an interviewer configured for fr-FR being heard as en-GB is the
          // same class of disagreement between a person and their settings that this task is
          // about - one field along.
          locale={config.resolved.country_code}
          onClose={() => setRehearsing(false)}
        />
      )}
    </div>
  )
}
