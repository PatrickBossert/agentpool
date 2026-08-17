// ui/src/api/dataArchitecture.ts
//
// The declarations behind the Data Architecture & Privacy page, resolved for one project's
// own llm_mode by api/services/data_architecture_service.py.
//
// The types below describe what that endpoint returns and nothing more. The page renders them
// and adds no facts of its own - the copy it used to carry was hand-typed, named Anthropic
// forty-four times, and had gone stale in four separate directions.
import { apiClient } from './client'

export interface DataArchitectureRead {
  source: string
  medium: string
  via: string
  note: string
  shared_beyond_this_project: boolean
}

export interface DataArchitectureToolRow {
  tool: string
  reaches: string
  sends: string
  destination: string
  leaves_deployment: boolean
  gated_by_mode: boolean
  held_by: string[]
}

export interface DataArchitectureUnheldTool {
  tool: string
  reaches: string
  sends: string
  destination: string
}

export interface DataArchitectureInference {
  reaches: string
  sends: string
  destination: string
  leaves_deployment: boolean
  gated_by_mode: boolean
}

export interface DataArchitectureAgent {
  agent_id: string
  display_name: string
  tier: string
  crews: string[]
  tools: string[]
  writes: string[]
  destinations: { label: string; leaves_deployment: boolean }[]
  sources: DataArchitectureRead[]
}

export interface DataArchitectureCrew {
  crew_id: string
  display_name: string
  purpose: string
  note: string
  defect: string | null
  depends_on: string[]
  agents: string[]
  triggers: string[]
}

export interface DataArchitectureDispatchPath {
  trigger: string
  label: string
  note: string
  defect: string | null
  injects_dispatch_reads: boolean
}

export interface DataArchitectureSharedSource {
  source: string
  medium: string
  read_by: string[]
}

export interface DataArchitecture {
  slug: string
  llm_mode: string
  inference: DataArchitectureInference
  tools: DataArchitectureToolRow[]
  declared_not_held: DataArchitectureUnheldTool[]
  agents: DataArchitectureAgent[]
  crews: DataArchitectureCrew[]
  dispatch_paths: DataArchitectureDispatchPath[]
  dispatch_reads: DataArchitectureRead[]
  shared_sources: DataArchitectureSharedSource[]
  scope: {
    crew_count: number
    agents_in_no_crew: { agent_id: string; display_name: string }[]
  }
}

export const dataArchitectureApi = {
  get: (slug: string): Promise<DataArchitecture> =>
    apiClient
      .get<DataArchitecture>(`/projects/${slug}/data-architecture`)
      .then((r) => r.data),
}
