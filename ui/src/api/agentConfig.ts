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

export const agentConfigApi = {
  get: async (slug: string, agentId: string): Promise<AgentConfig> => {
    const res = await apiClient.get<AgentConfig>(
      `/projects/${slug}/agents/${agentId}/config`,
    )
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
}
