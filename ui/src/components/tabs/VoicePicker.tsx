// ui/src/components/tabs/VoicePicker.tsx
//
// The voices a project may choose from, offered exactly as the server lists them.
//
// **Nothing in this file knows anything about a voice.** Not which voices exist, not which
// accents exist, not which languages exist, not which voice is which sex. Every one of those
// is metadata the provider returns - `accent` and `gender` on each entry, `accent_options` and
// `language_options` for the dropdowns - and this component renders what it is handed. The
// branch this belongs to exists because five copies of one voice's identity had grown and two
// disagreed; Task 4 built a source guard that refuses a sixth, and that guard walks Python. A
// curated list here would be the same defect on the one side nothing is watching. That
// includes the language **default**: `en` is not written here, it is read off the response.
//
// **Two axes, and only one of them narrows.** `en` is the language; `british`, `irish`,
// `american` and `new zealand` are accents of it. The picker used to open filtered to the
// project's `interview_accent`, defaulting to `british`, and showed 6 of the account's 41
// voices - an axis that should broaden used as one that narrows. So it opens on the language,
// unfiltered by accent, and the accent is an opt-in narrowing with the dropdown it already
// had. The setting is retired; the accent an interview is conducted in is a property of the
// voice each interviewer is given, which is what this picker chooses.
//
// **Two listings, and both are needed.** Measured on 5 September: Irish exists only in the
// Voice Library and Scottish only in the account, and two of the four planned engagements are
// those. A picker showing one listing cannot configure them.
//
// **A page is not an answer.** `library_has_more` and `accent_options_partial` are the
// provider's own "there is more behind this", and they are rendered rather than dropped: a
// bounded page presented as complete reads as "that voice does not exist" instead of "narrow
// your filters", which sends an operator to reconfigure something that was never wrong.
//
// **The picker opens on the interviewer's own sex, and lets you leave.** The sex is `voice_sex`
// on the listing - the server's answer about the voice this agent already has - so Avery's
// picker opens on male voices because Avery's voice is male, not because anything here maps an
// agent to a sex. `interviewer_selection.py` refuses such a table in writing, since the sex is a
// property of the voice and the voice is a per-project setting: a project that gives Avery a
// female voice has said something, and a table here would contradict it while looking
// authoritative. It is a **default, not a lock** - the control clears - and an unanswerable
// lookup opens **unfiltered, never empty**.
import { useState, type ReactNode } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { AlertTriangle, Check, Play, Plus, X } from 'lucide-react'

import { voicesApi, type CatalogueVoice } from '../../api/voices'
import { describeError } from '../../utils/describeError'

/**
 * What a query parameter should be when a control holds `value`.
 *
 * `''` is the picker's own "clear the filter" entry on both dropdowns, and on the accent it
 * means the same thing as sending nothing - so it is not sent, and the first request carries
 * no accent at all rather than an empty one. The language is the other case and keeps the
 * distinction, because there the server *has* a default: `undefined` asks for it and `''` asks
 * for every language, which is why the language control passes its empty value through
 * explicitly rather than through here.
 */
function narrowing(value: string): string | undefined {
  return value || undefined
}

/** The genders present in a listing, read off the entries the provider returned. */
function gendersIn(voices: CatalogueVoice[]): string[] {
  return [...new Set(voices.map((v) => v.gender).filter((g): g is string => !!g))].sort()
}

/** What a listing says this voice costs, in that listing's own terms. */
function rateLabel(voice: CatalogueVoice): string {
  // Absent is not zero. The account listing carries no rate at all, so `null` means "this
  // listing does not say what the voice costs" - and showing that as free would be this file
  // asserting a price on a screen whose job is to report one.
  if (voice.rate === null || voice.rate === undefined) return 'Rate not given by this listing'
  return `Rate ${voice.rate}${voice.fiat_rate ? ` (${voice.fiat_rate})` : ''}`
}

/** What a listing says about whether this plan may use the voice. */
function availabilityLabel(voice: CatalogueVoice): string {
  if (voice.free_users_allowed !== null && voice.free_users_allowed !== undefined) {
    return voice.free_users_allowed ? 'Available on the free tier' : 'Paid tiers only'
  }
  if (voice.available_for_tiers && voice.available_for_tiers.length > 0) {
    return `Available on ${voice.available_for_tiers.join(', ')}`
  }
  return 'Availability not given by this listing'
}

const PILL = 'px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600 text-[10px]'

function VoiceRow({
  voice,
  inUse,
  busy,
  onPreview,
  onUse,
  onAdd,
}: {
  voice: CatalogueVoice
  inUse: boolean
  busy: boolean
  onPreview: (url: string) => void
  onUse: (voice: CatalogueVoice) => void
  onAdd: (voice: CatalogueVoice) => void
}) {
  // A library voice the account already holds needs no copying, and the server works that out
  // by comparing the ids the two calls returned rather than from any list held anywhere.
  const needsAdding = voice.source === 'library' && !voice.in_account
  return (
    <li
      data-testid={`voice-${voice.voice_id}`}
      className="flex items-start justify-between gap-3 border-b border-gray-100 py-2"
    >
      <div className="min-w-0">
        <p className="text-xs font-medium text-gray-800 truncate">
          {voice.name}
          {inUse && <span className="ml-2 text-[10px] text-teal-700">in use</span>}
        </p>
        <div className="flex flex-wrap items-center gap-1 mt-1">
          {voice.accent && <span className={PILL}>{voice.accent}</span>}
          {voice.gender && <span className={PILL}>{voice.gender}</span>}
          {voice.category && <span className={PILL}>{voice.category}</span>}
          <span className={PILL}>{rateLabel(voice)}</span>
          <span className={PILL}>{availabilityLabel(voice)}</span>
          {voice.source === 'library' && voice.in_account && (
            <span className={PILL}>already in your account</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <button
          type="button"
          disabled={!voice.preview_url}
          onClick={() => voice.preview_url && onPreview(voice.preview_url)}
          title={
            voice.preview_url
              ? 'Play the sample the provider already hosts'
              : 'This voice has no sample'
          }
          aria-label={`Preview ${voice.name}`}
          className="flex items-center gap-1 px-2 py-1 border border-gray-200 rounded text-[11px] text-gray-700 disabled:opacity-40"
        >
          <Play size={11} aria-hidden="true" />
          Preview
        </button>
        {needsAdding ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => onAdd(voice)}
            className="flex items-center gap-1 px-2 py-1 bg-slate-800 hover:bg-slate-700 text-teal-300 rounded text-[11px] disabled:opacity-40"
          >
            <Plus size={11} aria-hidden="true" />
            Add to account and use
          </button>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={() => onUse(voice)}
            className="flex items-center gap-1 px-2 py-1 bg-brand hover:bg-brand-dark text-white rounded text-[11px] disabled:opacity-40"
          >
            <Check size={11} aria-hidden="true" />
            Use this voice
          </button>
        )}
      </div>
    </li>
  )
}

function Notice({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-1.5 text-[11px] text-amber-700 bg-amber-50 border border-amber-100 rounded px-2 py-1.5">
      <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  )
}

export default function VoicePicker({
  slug,
  currentVoiceId,
  onChoose,
  onClose,
}: {
  slug: string
  currentVoiceId: string | null
  /** The id to store, and the name to show for it until the section is reloaded. */
  onChoose: (voiceId: string, name: string) => void
  onClose: () => void
}) {
  // `''` is "every accent", which is where the picker opens: there is no project setting to
  // inherit any more, so nothing is narrowed until somebody narrows it. It is not sent at all
  // rather than sent empty - the two mean the same thing to the door, and a request that
  // carries no accent is the honest statement of a picker that is applying none.
  const [accent, setAccent] = useState('')
  // `undefined` and `''` are different here, and this is the axis where they have to be.
  // `undefined` means the request omits `language`, which is the server being asked to apply
  // its own default; `''` means the consultant cleared it and wants every language. The
  // default is deliberately not written here - a language code in this file is a voice fact
  // declared in TypeScript, which is what the header refuses.
  const [language, setLanguage] = useState<string | undefined>(undefined)
  // `null` and `''` are as different here as they are for `accent`, and for the same kind of
  // reason: `null` means the consultant has not touched this control, so the interviewer's own
  // sex pre-sets it, and `''` means they cleared it and want every sex. Collapsing the two would
  // make the pre-set filter permanent, which is the difference between a default and a lock.
  const [gender, setGender] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Asked **without** the sex filter - the same argument the server makes for probing the
  // library's accents unfiltered. A listing narrowed to `female` reports female, so both the
  // dropdown's options and the "does this listing even offer that sex" question below have to
  // be asked of an unnarrowed answer or the choice already made is the only one on offer.
  // While nothing is narrowing, this shares its cache key with the query below, so the common
  // case is one request rather than two.
  const unfilteredByGender = useQuery({
    queryKey: ['voices', slug, accent, language ?? null, '', search],
    queryFn: () => voicesApi.list(slug, {
      accent: narrowing(accent),
      language,
      search: search || undefined,
      current_voice_id: currentVoiceId ?? undefined,
    }),
    retry: false,
  })

  const offeredSexes = unfilteredByGender.data
    ? gendersIn([...unfilteredByGender.data.account, ...unfilteredByGender.data.library])
    : []

  // The sex of the voice this agent already has, from the server rather than from the listing:
  // the listing is narrowed - by the language it opens on, and by an accent once one is chosen
  // - so a voice outside those is simply absent from it and "not found" would be
  // indistinguishable from "no label".
  //
  // Pre-set only when this listing actually offers that sex. `voice_sex` is a fact about one
  // voice, and a sex no voice here carries would narrow the picker to nothing - and an empty
  // picker is indistinguishable from an account holding no voices, which the design names as
  // the worst outcome available. `null` - a voice with no label, a label that is neither of the
  // two, no voice at all, or a lookup that failed - opens unfiltered for the same reason.
  const sexOfCurrentVoice = unfilteredByGender.data?.voice_sex ?? ''
  const presetGender = offeredSexes.includes(sexOfCurrentVoice) ? sexOfCurrentVoice : ''
  const appliedGender = gender ?? presetGender

  const results = useQuery({
    queryKey: ['voices', slug, accent, language ?? null, appliedGender, search],
    queryFn: () => voicesApi.list(slug, {
      accent: narrowing(accent),
      language,
      gender: narrowing(appliedGender),
      search: search || undefined,
      current_voice_id: currentVoiceId ?? undefined,
    }),
    retry: false,
  })

  const data = results.data
  // What the dropdown renders. The unfiltered listing where there is one, falling back to the
  // narrowed answer only when the unfiltered ask itself failed - where some options beat none.
  const genderOptions = unfilteredByGender.data
    ? offeredSexes
    : data
      ? gendersIn([...data.account, ...data.library])
      : []

  const add = useMutation({
    mutationFn: (voice: CatalogueVoice) =>
      voicesApi.addFromLibrary(slug, {
        public_owner_id: voice.public_owner_id ?? '',
        voice_id: voice.voice_id,
        name: voice.name,
      }),
    onSuccess: (added, voice) => {
      // The account assigns a **new** id, and the project's configuration must hold that one -
      // the library id is not usable in its place. Refusing to guess when the response does
      // not carry it: storing the library id would look like success and fail at synthesis.
      if (typeof added.voice_id === 'string' && added.voice_id) {
        onChoose(added.voice_id, voice.name)
      } else {
        setError(
          'The voice was copied but the provider did not say what id it was given, so it '
          + 'has not been selected. Reopen this picker and choose it from the account list.',
        )
      }
    },
    onError: (err) => setError(describeError(err, 'The voice could not be added.')),
  })

  // The language the server says it applied, until the consultant chooses one. `??` and not
  // `||`, so a cleared `''` is the consultant's answer and not a fall through to the default -
  // that collapse is exactly what would make the default unclearable.
  const appliedLanguage = language ?? data?.language ?? ''
  const selectCls =
    'bg-white border border-gray-200 rounded px-2 py-1 text-xs text-gray-800 outline-none focus:border-brand'

  return (
    <div className="border border-gray-200 rounded-lg bg-white p-3 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
          Choose a voice
        </p>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close the voice picker"
          className="text-gray-400 hover:text-gray-700"
        >
          <X size={14} aria-hidden="true" />
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor="voice-language" className="block text-[10px] text-gray-500 mb-0.5">
            Language
          </label>
          <select
            id="voice-language"
            value={appliedLanguage}
            onChange={(e) => setLanguage(e.target.value)}
            className={selectCls}
          >
            <option value="">Every language</option>
            {(data?.language_options ?? []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="voice-accent" className="block text-[10px] text-gray-500 mb-0.5">
            Accent
          </label>
          <select
            id="voice-accent"
            value={accent}
            onChange={(e) => setAccent(e.target.value)}
            className={selectCls}
          >
            <option value="">Every accent</option>
            {(data?.accent_options ?? []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="voice-gender" className="block text-[10px] text-gray-500 mb-0.5">
            Voice sex
          </label>
          <select
            id="voice-gender"
            value={appliedGender}
            onChange={(e) => setGender(e.target.value)}
            className={selectCls}
          >
            <option value="">Any</option>
            {genderOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1 min-w-[10rem]">
          <label htmlFor="voice-search" className="block text-[10px] text-gray-500 mb-0.5">
            Search
          </label>
          <input
            id="voice-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Name or description"
            className={`${selectCls} w-full`}
          />
        </div>
      </div>

      {gender === null && appliedGender !== '' && (
        <p data-testid="sex-preset" className="text-[11px] text-gray-500">
          Filtered to <span className="font-medium">{appliedGender}</span> voices, the sex of the
          voice this agent already has. Choose Any to see every voice - giving an interviewer a
          voice of another sex is a choice this project is free to make.
        </p>
      )}

      {language === undefined && appliedLanguage !== '' && (
        <p data-testid="language-preset" className="text-[11px] text-gray-500">
          Showing <span className="font-medium">{appliedLanguage}</span> voices from the Voice
          Library, which is where this picker starts. Choose Every language to look wider. The
          accent is separate and narrows nothing until you set it - British, Irish and American
          are all the same language.
        </p>
      )}

      {results.isError && (
        <Notice>{describeError(results.error, 'The voices could not be listed.')}</Notice>
      )}
      {error && <Notice>{error}</Notice>}
      {data?.account_error && (
        <Notice>
          The account's own voices could not be listed ({data.account_error}), so what is below
          is the Voice Library alone.
        </Notice>
      )}
      {data?.library_error && (
        <Notice>
          The Voice Library could not be listed ({data.library_error}), so what is below is this
          account's voices alone.
        </Notice>
      )}
      {/* The disjunction rather than either field, because the type says these two always
          agree and a claim about the future is not a thing to build a control on. */}
      {(data?.accent_options_partial || data?.language_options_partial) && (
        <Notice>
          The accent and language lists are drawn from one page of the Voice Library and are
          not the whole of it. An accent or language missing here may still exist.
        </Notice>
      )}

      {results.isLoading && <p className="text-xs text-gray-400">Asking for the voices…</p>}

      {data && (
        <>
          <div>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">
              In this account ({data.account.length})
            </p>
            {data.account.length === 0 ? (
              <p className="text-[11px] text-gray-400">
                No voice in this account matches these filters.
              </p>
            ) : (
              <ul>
                {data.account.map((voice) => (
                  <VoiceRow
                    key={`account-${voice.voice_id}`}
                    voice={voice}
                    inUse={voice.voice_id === currentVoiceId}
                    busy={add.isPending}
                    onPreview={setPreviewUrl}
                    onUse={(v) => onChoose(v.voice_id, v.name)}
                    onAdd={(v) => add.mutate(v)}
                  />
                ))}
              </ul>
            )}
          </div>

          <div>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">
              Voice Library ({data.library.length})
            </p>
            {data.library_has_more && (
              <p data-testid="library-has-more" className="text-[11px] text-gray-500 mb-1">
                This is the first page of the Voice Library and there are more behind it -
                narrow the accent, sex or search to see them. A voice missing from this list is
                not necessarily missing from the library.
              </p>
            )}
            {data.library.length === 0 ? (
              <p className="text-[11px] text-gray-400">
                No library voice matches these filters.
              </p>
            ) : (
              <ul>
                {data.library.map((voice) => (
                  <VoiceRow
                    key={`library-${voice.voice_id}`}
                    voice={voice}
                    inUse={voice.voice_id === currentVoiceId}
                    busy={add.isPending}
                    onPreview={setPreviewUrl}
                    onUse={(v) => onChoose(v.voice_id, v.name)}
                    onAdd={(v) => add.mutate(v)}
                  />
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      {/* The provider already hosts a sample for every voice, so preview plays that URL and
          synthesises nothing. Speaking a line through `synthesise` would spend characters on
          audio that exists and sound identical to a listener - which is why the server asserts
          on the wire that this path never reaches text-to-speech, and why this element carries
          the URL rather than a blob some call produced. */}
      {previewUrl && (
        <audio
          data-testid="voice-preview"
          src={previewUrl}
          controls
          autoPlay
          className="w-full h-8"
        />
      )}
    </div>
  )
}
