// ui/src/api/voices.ts
//
// The first frontend reader of `GET /projects/{slug}/voices`. Until now the door had none:
// `accent_options`, `accent_options_partial` and `library_has_more` were all served and all
// unread, which is how a picker comes to present a first page as a complete answer.
//
// **Nothing here declares a fact about a voice.** Not which voices exist, not which accents
// exist, not which voice is which sex. All three are the provider's metadata and arrive on the
// payload - `accent` and `gender` on every entry, `accent_options` for the dropdown. This
// branch exists because five copies of Avery's voice had grown and disagreed, and Task 4 built
// a Python source guard that refuses a sixth. That guard walks Python: it cannot see this file.
// A curated list here would be the same defect, on the one side nothing is watching.
import { apiClient } from './client'

/** One voice, in the shape the door gives both listings after absorbing their differences. */
export interface CatalogueVoice {
  voice_id: string
  name: string
  /** The provider's own label. Null where they say nothing - never a guess made here. */
  accent: string | null
  /** `male` | `female` | `neutral`, as `labels.gender` on their payload. */
  gender: string | null
  /** A sample the provider already hosts. Preview plays this and synthesises nothing. */
  preview_url: string | null
  description: string | null
  category: string | null
  /**
   * What the voice costs, per the library listing. **Null is "this listing does not say",
   * never zero** - the account listing carries no rate at all, and rendering an absent rate
   * as free would be this file asserting a price.
   */
  rate: number | null
  fiat_rate: number | null
  /** Whether a free-tier account may use it. Null on the account listing, which omits it. */
  free_users_allowed: boolean | null
  /** Empty on every account voice observed so far; passed through rather than interpreted. */
  available_for_tiers: string[] | null
  /** Needed to copy a library voice into the account; null on voices already there. */
  public_owner_id: string | null
  verified_languages: unknown[]
  language?: string
  /** Library entries only: this voice is already in the account, so it needs no copying. */
  in_account?: boolean
  source: 'account' | 'library'
}

export interface VoiceCatalogue {
  /** The accent actually applied, which is the project's when the request omitted one. */
  accent: string
  accent_source: 'project' | 'request'
  filters: { gender: string | null; language: string | null; search: string | null }
  /** The union of both listings, and the only thing an accent control should offer. */
  accent_options: string[]
  /**
   * The options came off one bounded page of the library, or off a probe that failed. Either
   * way the list is not the whole accent vocabulary and must not be presented as one.
   */
  accent_options_partial: boolean
  account_accents: string[]
  library_accents: string[]
  account: CatalogueVoice[]
  /** Named when the account listing failed while the library succeeded. A partial answer is
   *  reported rather than hidden: five voices shown where ninety exist is diagnosed as
   *  "there are no Scottish voices". */
  account_error: string | null
  library: CatalogueVoice[]
  /** There is another page and no pagination to reach it. This is what lets a picker say
   *  "narrow your filters" rather than "that voice is not in the library". */
  library_has_more: boolean
  library_error: string | null
}

export interface AddedVoice {
  /** The **new** id the account assigned. Not the library id that was sent, and a project's
   *  configuration must hold this one. */
  voice_id?: string
  [key: string]: unknown
}

export const voicesApi = {
  /**
   * Both listings for this project.
   *
   * `accent` omitted and `accent` empty are different requests and the difference is
   * deliberate on the server: omitted means "use the project's `interview_accent`", empty
   * means "every accent". So `undefined` is not sent and `''` is, which is why this builds
   * the query rather than spreading an object.
   */
  list: async (
    slug: string,
    params: {
      accent?: string
      gender?: string
      language?: string
      search?: string
    } = {},
  ): Promise<VoiceCatalogue> => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) query.set(key, value)
    }
    const suffix = query.toString()
    const res = await apiClient.get<VoiceCatalogue>(
      `/projects/${slug}/voices${suffix ? `?${suffix}` : ''}`,
    )
    return res.data
  },

  /** Copy a Voice Library voice into the deployment's account. Platform tier on the server -
   *  one account serves every engagement, so this spends the consultancy's credit and changes
   *  what every other client's picker shows. */
  addFromLibrary: async (
    slug: string,
    body: { public_owner_id: string; voice_id: string; name: string },
  ): Promise<AddedVoice> => {
    const res = await apiClient.post<AddedVoice>(`/projects/${slug}/voices/library`, body)
    return res.data
  },
}
