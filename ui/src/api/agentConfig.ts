// ui/src/api/agentConfig.ts
//
// What this project calls an agent, shows for it, and gives it to speak with.
// `GET`/`PUT /projects/{slug}/agents/{agent_id}/config`.
import { apiClient } from './client'

/** The six overridable fields, in the order `AGENT_CONFIG_COLUMNS` names them. */
export interface AgentConfigFields {
  display_name: string
  image_url: string | null
  voice_id: string | null
  language: string
  country_code: string
  /**
   * The **speech synthesis** model - ElevenLabs' `model_id`, threaded through
   * `synthesise(text, voice_id, model_id)` so a French voice is not spoken through an English
   * model. It has nothing to do with `anthropic_fast_model` and its five siblings on
   * ProjectSettings, which decide where this engagement's prompts are sent and are refused to
   * a project_admin. Two different things in this product are called a model id and one of
   * them is a security control; label this one for what it is wherever it is rendered.
   */
  model_id: string
}

/** Every field a project may override, each `null` where it has recorded no opinion. */
export type AgentConfigOverrides = { [K in keyof AgentConfigFields]: string | null }

export interface AgentConfig {
  agent_id: string
  /** Whether this project has ever recorded a row for this agent at all. */
  configured: boolean
  /** What the agent is without this project - `agents/identity.py`. */
  defaults: AgentConfigFields
  /** What this project has said. `null` per field means "no override, use the default". */
  overrides: AgentConfigOverrides
  /** The one over the other, per field. What the interview actually uses. */
  resolved: AgentConfigFields
}

/** What the upload door answers: where the portrait now lives, and what it cost to store.
 *
 *  The two sizes are not decoration. The whole point of the upload path is that a large
 *  photograph quietly becomes a small one, and an administrator who is never told it happened
 *  uploads the same 8 MB file again next time.
 */
export interface PortraitUpload {
  /**
   * Same-origin, always - `/projects/{slug}/agents/{agent_id}/image`.
   *
   * **No `/api` prefix.** This router is mounted at `/projects`, and only `/api/templates` and
   * `/api/interviews` carry that prefix, so `/api/projects/...` is served by nothing. Store what
   * the door answers; never assemble this address here.
   */
  url: string
  /** Bytes actually stored, after the downscale. */
  bytes: number
  /** Bytes the browser sent. */
  original_bytes: number
}

/**
 * Every agent's configuration on one project, keyed by the permanent `agent_id`.
 *
 * Each entry is the identical object `GET .../{agent_id}/config` answers - the server builds it
 * with the same function - so nothing here needs its own idea of what "override beats default"
 * means. `tests/test_agent_config_bulk.py` holds the two responses equal for every agent on the
 * roll, which is what makes reading the batch as safe as reading the door eighteen times.
 */
export interface AgentConfigBundle {
  agents: Record<string, AgentConfig>
}

export const agentConfigApi = {
  get: async (slug: string, agentId: string): Promise<AgentConfig> => {
    const res = await apiClient.get<AgentConfig>(
      `/projects/${slug}/agents/${agentId}/config`,
    )
    return res.data
  },

  /**
   * Every agent's configuration on this project, in one request.
   *
   * The dashboard draws an agent's name and face in nine places, and each of those renders the
   * whole roll rather than one agent, so asking the per-agent door would be a hundred and
   * sixty-two calls to paint one screen. This is the read those sites share.
   */
  getAll: async (slug: string): Promise<AgentConfigBundle> => {
    const res = await apiClient.get<AgentConfigBundle>(`/projects/${slug}/agents/config`)
    return res.data
  },

  /**
   * Replace this project's overrides for one agent.
   *
   * A PUT, and the whole row: the server writes all six columns on every call, so a field
   * omitted here is **cleared** rather than left alone. Send the overrides you hold, never the
   * resolved values - saving a resolved default would freeze it as an override, and the agent
   * would then stop following a rename in `agents/identity.py` for reasons nobody could see.
   */
  put: async (
    slug: string,
    agentId: string,
    overrides: AgentConfigOverrides,
  ): Promise<AgentConfig> => {
    const res = await apiClient.put<AgentConfig>(
      `/projects/${slug}/agents/${agentId}/config`,
      overrides,
    )
    return res.data
  },

  /**
   * Store a portrait for this agent on this project, and get back the URL that serves it.
   *
   * **This does not save the configuration.** The server writes the file and answers a URL; the
   * row is written by `put` above, because `upsert_agent_config` replaces the whole row and a
   * partial write from the upload door would clear the agent's name, voice, language, country
   * and synthesis model. So the caller uploads first and then saves with the returned URL - in
   * that order, and never the other way round, or the row records an address for a file that
   * may never arrive.
   *
   * The `Content-Type` is left unset on purpose. A multipart body needs the boundary token in
   * the header, and only the thing assembling the body knows it - the same shape
   * `uploadBrandingImage` has used since it existed.
   */
  uploadImage: async (
    slug: string,
    agentId: string,
    file: File,
  ): Promise<PortraitUpload> => {
    const form = new FormData()
    form.append('file', file)
    const res = await apiClient.post<PortraitUpload>(
      `/projects/${slug}/agents/${agentId}/image`,
      form,
    )
    return res.data
  },
}
