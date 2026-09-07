// ui/src/hooks/useAgentIdentity.ts
//
// What one project calls an agent, and what face it shows for them.
//
// Patrick uploaded a portrait for Jordan on `sp-gs-am` on 7 September. The file was downscaled
// and stored, `project_agent_config.image_url` recorded the URL, that URL served 200 - and every
// face on the dashboard was unchanged, because nine display sites read `AGENT_AVATAR_IMAGE`, a
// static map, and nothing outside the Setup section ever read the configured value.
//
// This is the one place that gap is closed. Every site that draws a name or a face asks here.
import { useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'

import { agentConfigApi } from '../api/agentConfig'
import { AGENT_IDS, AGENT_HUMAN_NAME, AGENT_AVATAR_IMAGE } from '../components/agentStatus'

/** An agent as this project shows them: the name to print, and the portrait to draw. */
export interface AgentIdentity {
  /** The name a human reads - 'Jordan Williams', or whatever this project renamed them to. */
  name: string
  /**
   * The portrait, or `null` when there is none to draw and the caller should render initials.
   *
   * `''` is a portrait this project **deliberately cleared** and is deliberately falsy, so the
   * existing `imageSrc ? <img/> : <initials/>` at every call site does the right thing with it
   * without a second rule being written.
   */
  imageUrl: string | null
}

/**
 * Resolve an agent's name and face for one project.
 *
 * Returns a lookup keyed by the **display** name the front end is arranged by - 'Stakeholder
 * Manager' - because that is the form all nine call sites hold. `AGENT_IDS` in `agentStatus.ts`
 * is the bridge to the permanent snake id the configuration is keyed on, and it is the only one:
 * a second name-to-id map here would be free to drift from it with nothing comparing the two,
 * and a wrong id is not a 404 anybody sees - any id that *exists* configures a different agent.
 *
 * **The override first, the static map second - never the server's resolved value.** The batch
 * answers `resolved` too and it is the wrong thing to render here: `AGENT_IDENTITY`'s default
 * image is `/agents/jordan-williams.jpg`, while Vite serves `ui/public` under the base
 * `/dashboard`, so drawing the resolved default would 404 for every agent *without* an override
 * and turn a bug about one face into a bug about eighteen. `AGENT_AVATAR_IMAGE` is the only map
 * that knows the base, so it stays the fallback. The two agree about which file they mean -
 * `tests/test_persona_transcription.py` holds them equal - so this is a difference of address
 * rather than of content.
 *
 * **"Present" means "not NULL", never "truthy"** - `agent_config_service._override`'s rule, and
 * the reason this uses `??` rather than `||`. A project that has cleared an agent's portrait has
 * said something, and `||` would reinstate the static map over that decision.
 *
 * `slug` is optional so a page with no project to resolve against - `Team.tsx`, which lists the
 * roll across the whole deployment - can call this and get the static answer rather than
 * inventing a project. The query does not run without one.
 */
export function useAgentIdentity(slug?: string): (agentName: string) => AgentIdentity {
  const { data } = useQuery({
    queryKey: ['agent-config-all', slug],
    queryFn: () => agentConfigApi.getAll(slug as string),
    enabled: !!slug,
    // The roll changes when somebody saves the Setup section, which invalidates this key, and
    // not otherwise. Refetching it on every window focus would be eighteen agents' worth of
    // JSON to answer a question nobody asked again.
    staleTime: 5 * 60 * 1000,
  })

  return useCallback(
    (agentName: string): AgentIdentity => {
      const overrides = data?.agents[AGENT_IDS[agentName]]?.overrides
      return {
        name: overrides?.display_name ?? AGENT_HUMAN_NAME[agentName] ?? agentName,
        imageUrl: overrides?.image_url ?? AGENT_AVATAR_IMAGE[agentName] ?? null,
      }
    },
    [data],
  )
}
