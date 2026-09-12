// ui/src/__tests__/VoicePicker.test.tsx
//
// The picker offers what the server lists, and says when a list is a page rather than an
// answer.
//
// Three properties here are not visible on the screen and are the reason this file exists:
//
//   1. **No voice fact is declared in TypeScript.** Task 4 built a Python source guard that
//      refuses a sixth copy of "which voice is which"; it walks Python and cannot see this
//      side. So the accent options, the languages offered, the sexes offered, and every voice
//      shown are asserted to be the ones the payload carried - and for **all three** dropdowns
//      a payload naming a value this codebase has never heard of is driven through, since a
//      hardcoded list would still pass a test built from the values that list would contain.
//      The accent half was written that way from the start; the sex half was not, and a
//      hardcoded `['female', 'male']` passed the whole suite until the two cases below were
//      added. The language half is the newest, and includes the **default**: `en` is never
//      written here, only read off the response.
//   2. **Preview plays the provider's own URL and synthesises nothing.** The cheap
//      implementation and the expensive one are identical to a listener, so only a test can
//      tell them apart.
//   3. **A bounded page is reported as one.** `library_has_more` reaching nothing is how a
//      picker comes to read as "that voice does not exist".
//
// **The picker opens on the language, unfiltered by accent** (sp64). It used to open on the
// project's `interview_accent`, defaulting to `british`, which showed 6 of the account's 41
// voices - an axis that should broaden used as one that narrows. Both halves are asserted on
// what is *sent*, and the control - narrowing and then clearing again - is what separates a
// picker that applies the accent from one that ignores it entirely.
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import VoicePicker from '../components/tabs/VoicePicker'
import { voicesApi } from '../api/voices'
import type { CatalogueVoice, VoiceCatalogue } from '../api/voices'

vi.mock('../api/voices', () => ({
  voicesApi: { list: vi.fn(), addFromLibrary: vi.fn() },
}))

function voice(over: Partial<CatalogueVoice> & { voice_id: string }): CatalogueVoice {
  return {
    name: 'A Voice',
    accent: null,
    gender: null,
    preview_url: null,
    description: null,
    category: null,
    rate: null,
    fiat_rate: null,
    free_users_allowed: null,
    available_for_tiers: null,
    public_owner_id: null,
    verified_languages: [],
    source: 'account',
    ...over,
  }
}

// Deliberately not british. A fixture built from the accent everything defaults to could not
// tell a picker that renders the payload from one that renders a list of its own.
const ACCOUNT_VOICE = voice({
  voice_id: 'acct-1', name: 'Mairi Fraser', accent: 'hebridean', gender: 'female',
  preview_url: 'https://provider.example/preview/acct-1.mp3', category: 'premade',
  available_for_tiers: [],
})

const LIBRARY_VOICE = voice({
  voice_id: 'lib-1', name: 'Ronan Doyle', accent: 'irish', gender: 'male',
  preview_url: 'https://provider.example/preview/lib-1.mp3', source: 'library',
  rate: 0.4, fiat_rate: 12, free_users_allowed: false, public_owner_id: 'owner-9',
  in_account: false,
})

function catalogue(over: Partial<VoiceCatalogue> = {}): VoiceCatalogue {
  return {
    accent: '',
    // Deliberately not `en`. The server owns the default, so a fixture spelling it would
    // agree with a picker that had hardcoded the same word - the failure this file exists to
    // catch, on the newest axis.
    language: 'kernowek',
    filters: { gender: null, search: null },
    // The default is the unanswerable case, so every test that says nothing about the sex of
    // the current voice is driving the "open unfiltered" branch.
    voice_sex: null,
    accent_options: ['hebridean', 'irish'],
    accent_options_partial: false,
    language_options: ['kernowek', 'sindarin'],
    language_options_partial: false,
    account_accents: ['hebridean'],
    library_accents: ['irish'],
    account_languages: ['kernowek'],
    library_languages: ['sindarin'],
    account: [ACCOUNT_VOICE],
    account_error: null,
    library: [LIBRARY_VOICE],
    library_has_more: false,
    library_error: null,
    ...over,
  }
}

function renderPicker(props: Partial<Parameters<typeof VoicePicker>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onChoose = props.onChoose ?? vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <VoicePicker
        slug="acme"
        currentVoiceId={null}
        onChoose={onChoose}
        onClose={vi.fn()}
        {...props}
      />
    </QueryClientProvider>,
  )
  return { onChoose }
}

/** The listing has arrived. Waiting on a control is not the same thing: the accent and sex
 *  dropdowns render immediately with only their own "clear the filter" entry, so an assertion
 *  made before this passes against an empty list rather than against the payload - and
 *  `fireEvent.change` to an option that does not exist yet is silently a no-op. */
const loaded = () => screen.findByTestId('voice-acct-1')

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(voicesApi.list).mockResolvedValue(catalogue())
})

describe('the voice picker - nothing about a voice is declared here', () => {
  it('offers exactly the accents the server listed, and no others', async () => {
    renderPicker()
    await loaded()
    const select = screen.getByLabelText('Accent')
    const offered = within(select).getAllByRole('option').map((o) => o.textContent)
    // "Every accent" is the picker's own control for clearing the filter, not a claim about
    // any accent existing. Everything else came off accent_options.
    expect(offered).toEqual(['Every accent', 'hebridean', 'irish'])
  })

  it('offers exactly the sexes present in the listing', async () => {
    // On its own this case **cannot** hold the property its name states, and the two below
    // exist because of that. The base fixture's voices are female and male, which are the two
    // words anybody hardcoding a list would hardcode - so `return ['female', 'male']` in
    // `gendersIn` passes this assertion exactly. It was driven and it did. A fixture built
    // from the values the wrong implementation would guess is a fixture that cannot see it.
    renderPicker()
    await loaded()
    const select = screen.getByLabelText('Voice sex')
    expect(within(select).getAllByRole('option').map((o) => o.textContent))
      .toEqual(['Any', 'female', 'male'])
  })

  it('offers a sex the payload carries that this codebase never names', async () => {
    // The picker's half of the design's "the filter is applied to the API's `labels.gender`,
    // not to a list in this codebase". The server half is held in Python; that guard walks
    // Python and cannot see this side, so this is where the picker's half lives or nowhere.
    //
    // `neutral` is not hypothetical: `ui/src/api/voices.ts` says the field is
    // `male | female | neutral`, so a curated two-item list drops a value the provider
    // already returns - on the control whose only job is to offer what the provider sent.
    vi.mocked(voicesApi.list).mockResolvedValue(catalogue({
      account: [{ ...ACCOUNT_VOICE, gender: 'neutral' }],
      library: [{ ...LIBRARY_VOICE, gender: 'female' }],
    }))
    renderPicker()
    await loaded()
    const select = screen.getByLabelText('Voice sex')
    expect(within(select).getAllByRole('option').map((o) => o.textContent))
      .toEqual(['Any', 'female', 'neutral'])
  })

  it('offers no sex the listing does not carry', async () => {
    // The other direction, and the one a "does it offer neutral" case alone would miss: an
    // implementation that offered its own list *plus* whatever arrived would pass that one
    // while still putting `male` in front of an operator on an all-female listing, where
    // choosing it returns nothing and reads as a broken picker.
    vi.mocked(voicesApi.list).mockResolvedValue(catalogue({
      account: [ACCOUNT_VOICE],
      library: [{ ...LIBRARY_VOICE, gender: 'female' }],
    }))
    renderPicker()
    await loaded()
    const select = screen.getByLabelText('Voice sex')
    expect(within(select).getAllByRole('option').map((o) => o.textContent))
      .toEqual(['Any', 'female'])
  })

  it('asks the server for a sex rather than filtering the page it already has', async () => {
    // The library answer is one bounded page. Narrowing it here would hide every voice of
    // that sex beyond the page - the same trap `library_has_more` exists to report - so the
    // filter has to reach the provider's own query parameter.
    renderPicker()
    await loaded()
    fireEvent.change(screen.getByLabelText('Voice sex'), { target: { value: 'male' } })

    await waitFor(() =>
      expect(voicesApi.list).toHaveBeenCalledWith(
        'acme', expect.objectContaining({ gender: 'male' }),
      ))
  })

  it('keeps offering every sex once one has been chosen', async () => {
    // A listing narrowed to male reports male, so options derived from the narrowed answer
    // would offer exactly the choice already made and there would be no way back. The picker
    // asks a second, unfiltered question for the options - the same argument the server makes
    // for probing the library's accents unfiltered.
    renderPicker()
    await loaded()
    vi.mocked(voicesApi.list).mockImplementation(async (_slug, params) =>
      params?.gender
        ? catalogue({ account: [], library: [LIBRARY_VOICE] })
        : catalogue(),
    )
    fireEvent.change(screen.getByLabelText('Voice sex'), { target: { value: 'male' } })

    await waitFor(() =>
      expect(
        within(screen.getByLabelText('Voice sex')).getAllByRole('option').map((o) => o.textContent),
      ).toEqual(['Any', 'female', 'male']))
  })

  it('offers exactly the languages the server listed, and no others', async () => {
    // The accent dropdown's rule on the axis that arrived with it. Driven from a fixture
    // naming two codes this codebase has never heard of, because a list hardcoded to the
    // languages anybody would guess - `en`, `fr` - would pass a test built from those.
    renderPicker()
    await loaded()
    const select = screen.getByLabelText('Language')
    expect(within(select).getAllByRole('option').map((o) => o.textContent))
      .toEqual(['Every language', 'kernowek', 'sindarin'])
  })

  it('opens on the language the server applied, without declaring what it is', async () => {
    // The default lives in Python. A picker that wrote `en` here would agree with the server
    // by coincidence and disagree the day the default moves - and it would be a voice fact
    // restated in TypeScript, which is the one thing this file exists to refuse.
    renderPicker()
    await loaded()
    expect(screen.getByLabelText('Language')).toHaveValue('kernowek')
    expect(await screen.findByTestId('language-preset')).toHaveTextContent('kernowek')
  })

  it('sends no accent and no language of its own on the first request', async () => {
    // sp64, asserted on what is **sent**. The picker opens unfiltered by accent - there is no
    // project setting to inherit any more - and names no language, which is how the server is
    // asked to apply its own default. An `accent: ''` here would be a request carrying an
    // empty filter, and a `language: 'en'` would be this file declaring the default.
    renderPicker()
    await loaded()
    expect(vi.mocked(voicesApi.list).mock.calls[0][1]).toEqual({
      accent: undefined, language: undefined, gender: undefined, search: undefined,
    })
  })

  it('narrows to a chosen accent and broadens again when it is cleared', async () => {
    // The control. Without it, "the first request carries no accent" is satisfied just as
    // well by a picker that ignores the accent dropdown entirely.
    renderPicker()
    await loaded()

    fireEvent.change(screen.getByLabelText('Accent'), { target: { value: 'irish' } })
    await waitFor(() =>
      expect(voicesApi.list).toHaveBeenCalledWith(
        'acme', expect.objectContaining({ accent: 'irish' })))

    fireEvent.change(screen.getByLabelText('Accent'), { target: { value: '' } })
    await waitFor(() => {
      const last = vi.mocked(voicesApi.list).mock.calls.at(-1)?.[1]
      expect(last?.accent).toBeUndefined()
    })
  })

  it('narrows to a chosen language and asks for every language when cleared', async () => {
    // The same control on the axis that has a default, where clearing means something the
    // accent's clearing does not: `''` is a request for **every** language and is sent, while
    // `undefined` would be a request for the server's default. Collapsing the two would make
    // the default unclearable, which is the shape of the defect sp64 removed.
    renderPicker()
    await loaded()

    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'sindarin' } })
    await waitFor(() =>
      expect(voicesApi.list).toHaveBeenCalledWith(
        'acme', expect.objectContaining({ language: 'sindarin' })))

    fireEvent.change(screen.getByLabelText('Language'), { target: { value: '' } })
    await waitFor(() => {
      const last = vi.mocked(voicesApi.list).mock.calls.at(-1)?.[1]
      expect(last?.language).toBe('')
    })
    // And the note about the applied language goes, because nothing is being applied.
    await waitFor(() => expect(screen.queryByTestId('language-preset')).toBeNull())
  })
})

describe('the voice picker - it opens on the interviewer\'s own sex, and lets you leave', () => {
  /** The listing narrowed to `female` holds the account voice; unnarrowed it holds both. */
  function listingKnowingTheVoiceIs(sex: string | null) {
    vi.mocked(voicesApi.list).mockImplementation(async (_slug, params) =>
      params?.gender
        ? catalogue({ voice_sex: sex, account: [ACCOUNT_VOICE], library: [] })
        : catalogue({ voice_sex: sex }))
  }

  it('tells the door which voice this agent already has', async () => {
    // Without this the server answers `voice_sex: null` and the filter never pre-sets - so the
    // whole feature fails silently, looking exactly like a provider that gave no label.
    renderPicker({ currentVoiceId: 'acct-1' })
    await loaded()
    expect(vi.mocked(voicesApi.list).mock.calls[0][1])
      .toMatchObject({ current_voice_id: 'acct-1' })
  })

  it('opens filtered to the sex of the voice it already has', async () => {
    // The assertion is on the query the picker SENDS. A filter applied to the rendered list
    // looks identical on screen and is a different feature - and a worse one, since the library
    // half of the answer is one bounded page, so narrowing here would hide every voice of that
    // sex beyond it.
    //
    // The sex is the server's answer about that voice, not a table in this codebase mapping an
    // agent to a sex: `interviewer_selection.py` refuses such a table in writing, because a
    // project that gives an interviewer a voice of the other sex has said something.
    listingKnowingTheVoiceIs('female')
    renderPicker({ currentVoiceId: 'acct-1' })

    await waitFor(() => expect(voicesApi.list).toHaveBeenCalledWith(
      'acme', expect.objectContaining({ gender: 'female' }),
    ))
    // And it shows what it asked for, rather than sitting on a spinner.
    expect(await screen.findByTestId('voice-acct-1')).toBeInTheDocument()
  })

  it('lets the filter be cleared, and then asks for every sex', async () => {
    // The control. Without it a picker that hardcoded a permanent filter passes the case above
    // - and a consultant giving Laura a male voice is making a legitimate choice that this
    // picker must not be the thing to forbid.
    listingKnowingTheVoiceIs('female')
    renderPicker({ currentVoiceId: 'acct-1' })
    await waitFor(() => expect(voicesApi.list).toHaveBeenCalledWith(
      'acme', expect.objectContaining({ gender: 'female' }),
    ))
    expect(screen.getByLabelText('Voice sex')).toHaveValue('female')

    fireEvent.change(screen.getByLabelText('Voice sex'), { target: { value: '' } })

    // The *next* request, not merely some earlier one: the assertion is that clearing reaches
    // the wire, so the last thing sent must carry no sex at all.
    await waitFor(() => {
      const [, params] = vi.mocked(voicesApi.list).mock.calls.at(-1)!
      expect(params?.gender).toBeUndefined()
    })
    expect(await screen.findByTestId('voice-lib-1')).toBeInTheDocument()
    expect(screen.queryByTestId('sex-preset')).toBeNull()
  })

  it('opens unfiltered, never empty, when the sex could not be established', async () => {
    // `voice_sex` is null for four different reasons - no voice, no label, a label that is not
    // one of the two the listing can be filtered by, and a lookup that failed - and all four
    // mean the same thing here. Showing nothing because a lookup failed is the worst outcome
    // available: it is indistinguishable from an account holding no voices, and it sends a
    // consultant to diagnose a picker that is working.
    listingKnowingTheVoiceIs(null)
    renderPicker({ currentVoiceId: 'acct-1' })
    await loaded()
    expect(await screen.findByTestId('voice-lib-1')).toBeInTheDocument()

    expect(vi.mocked(voicesApi.list).mock.calls.every(([, p]) => p?.gender === undefined))
      .toBe(true)
  })

  it('opens unfiltered when the listing carries no voice of that sex', async () => {
    // The same "never empty" rule reached by a route where every part is working. `voice_sex`
    // is a fact about one voice; the listing is narrowed by the project's accent, so it may
    // hold no voice of that sex at all - and pre-setting the filter anyway would empty the
    // picker on a perfectly correct answer.
    vi.mocked(voicesApi.list).mockResolvedValue(catalogue({
      voice_sex: 'male',
      account: [ACCOUNT_VOICE],
      library: [{ ...LIBRARY_VOICE, gender: 'female' }],
    }))
    renderPicker({ currentVoiceId: 'acct-1' })
    await loaded()

    expect(vi.mocked(voicesApi.list).mock.calls.every(([, p]) => p?.gender === undefined))
      .toBe(true)
    expect(screen.getByLabelText('Voice sex')).toHaveValue('')
    expect(screen.getByTestId('voice-lib-1')).toBeInTheDocument()
  })
})

describe('the voice picker - a page is not an answer', () => {
  it('says the library listing is a first page when the server says there is more', async () => {
    vi.mocked(voicesApi.list).mockResolvedValue(catalogue({ library_has_more: true }))
    renderPicker()
    expect(await screen.findByTestId('library-has-more')).toBeInTheDocument()
  })

  it('says nothing of the sort when the listing is complete', async () => {
    // The other half. A notice that renders unconditionally would pass the test above while
    // telling every operator their complete listing is truncated.
    renderPicker()
    await loaded()
    expect(screen.queryByTestId('library-has-more')).toBeNull()
  })

  it('warns that the accent list may be incomplete when the probe was truncated', async () => {
    vi.mocked(voicesApi.list).mockResolvedValue(catalogue({ accent_options_partial: true }))
    renderPicker()
    expect(await screen.findByText(/not the whole of it/i)).toBeInTheDocument()
  })

  it('warns on the language list too, which comes off the same walk', async () => {
    // The server serves one truncation flag under two names. A notice gated on the accent
    // field alone would be silently right today and silently wrong the moment they part.
    vi.mocked(voicesApi.list).mockResolvedValue(catalogue({
      accent_options_partial: false, language_options_partial: true,
    }))
    renderPicker()
    expect(await screen.findByText(/not the whole of it/i)).toBeInTheDocument()
  })

  it('reports a half-failed answer rather than presenting it as the whole', async () => {
    // A picker silently showing the account's few where the library's many should be is
    // diagnosed as "there are no Irish voices", and somebody reconfigures a project that was
    // never wrong.
    vi.mocked(voicesApi.list).mockResolvedValue(
      catalogue({ library: [], library_error: 'ElevenLabs answered 502' }),
    )
    renderPicker()
    expect(await screen.findByText(/ElevenLabs answered 502/)).toBeInTheDocument()
  })
})

describe('the voice picker - preview and choosing', () => {
  it('plays the URL the provider already hosts, and calls nothing to make it', async () => {
    renderPicker()
    await loaded()
    fireEvent.click(screen.getByRole('button', { name: 'Preview Mairi Fraser' }))

    const audio = await screen.findByTestId('voice-preview')
    expect(audio).toHaveAttribute('src', ACCOUNT_VOICE.preview_url)
    // Nothing was asked to synthesise anything. The only calls this component may make are
    // listings, and this asserts on the module rather than on the absence of audio - the
    // expensive implementation and the cheap one sound identical.
    expect(voicesApi.addFromLibrary).not.toHaveBeenCalled()
    expect(vi.mocked(voicesApi.list).mock.calls.every(([, p]) => !('text' in (p ?? {}))))
      .toBe(true)
  })

  it('hands back the voice id, not the name, when an account voice is chosen', async () => {
    const { onChoose } = renderPicker()
    await loaded()
    fireEvent.click(screen.getByRole('button', { name: /use this voice/i }))
    expect(onChoose).toHaveBeenCalledWith('acct-1', 'Mairi Fraser')
  })

  it('hands back the NEW id the account assigned when a library voice is copied', async () => {
    // The account gives a copied voice a new id, and the project's configuration must hold
    // that one - the library id is not usable in its place, and storing it would look like
    // success and fail at synthesis.
    vi.mocked(voicesApi.addFromLibrary).mockResolvedValue({ voice_id: 'new-account-id' })
    const { onChoose } = renderPicker()
    await loaded()
    fireEvent.click(screen.getByRole('button', { name: /add to account and use/i }))

    await waitFor(() =>
      expect(voicesApi.addFromLibrary).toHaveBeenCalledWith('acme', {
        public_owner_id: 'owner-9', voice_id: 'lib-1', name: 'Ronan Doyle',
      }))
    await waitFor(() => expect(onChoose).toHaveBeenCalledWith('new-account-id', 'Ronan Doyle'))
  })

  it('refuses to guess an id when the copy answers without one', async () => {
    // Falling back to the library id here is the tempting wrong answer: it would select
    // something, report success, and produce an interview with no voice at all.
    vi.mocked(voicesApi.addFromLibrary).mockResolvedValue({})
    const { onChoose } = renderPicker()
    await loaded()
    fireEvent.click(screen.getByRole('button', { name: /add to account and use/i }))

    expect(await screen.findByText(/did not say what id it was given/i)).toBeInTheDocument()
    expect(onChoose).not.toHaveBeenCalled()
  })

  it('shows the rate the library gave, and does not invent one for an account voice', async () => {
    // Absent is not zero. The account listing carries no rate, and rendering that as free
    // would be the picker asserting a price on the screen whose job is to report one.
    renderPicker()
    const account = await loaded()
    expect(within(account).getByText(/Rate not given by this listing/)).toBeInTheDocument()
    const library = screen.getByTestId('voice-lib-1')
    expect(within(library).getByText(/Rate 0\.4/)).toBeInTheDocument()
    expect(within(library).getByText(/Paid tiers only/)).toBeInTheDocument()
  })
})
