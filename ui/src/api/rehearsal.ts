// ui/src/api/rehearsal.ts
//
// The script a rehearsal interview is conducted from: the committed default, or one of this
// project's own.
//
// `GET /api/interviews/test/script-options` and `GET /api/interviews/test/script`.
import { apiClient } from './client'

/** One script this project offers for rehearsal. Reference, description, and review state. */
export interface RehearsalScriptOption {
  /** The permanent id - `SC-005`. What a consultant cites, and what the door is asked for. */
  script_id: string
  /** The activity it interviews about, which is what a consultant actually recognises. */
  node_label: string
  /**
   * `pending`, `reviewed`, `changes_requested` or `approved`.
   *
   * Shown, never filtered on. The list is deliberately not approved-only: measured on the live
   * engagement, exactly one of 86 scripts is approved and it is a van technician's interview,
   * while every script that suits a strategy audience is `pending`. A rehearsal is not a client
   * deliverable, so the state informs the choice rather than restricting it.
   */
  review_status: string
}

/**
 * The sentinel for "the committed sample script".
 *
 * An empty string, and sent by being **omitted** rather than by being sent empty - the server
 * reads a blank `script_id` as the default, so the two spellings agree. It is not in the
 * server's list: the default is a product constant rather than one of the project's scripts,
 * so the option is rendered here and no id travels for it.
 */
export const DEFAULT_REHEARSAL_SCRIPT = ''

export const rehearsalApi = {
  options: (slug: string): Promise<RehearsalScriptOption[]> =>
    apiClient
      .get('/api/interviews/test/script-options', { params: { slug } })
      .then((r) => r.data.scripts ?? []),
}
