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
  held_by_ids: string[]
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
  crew_ids: string[]
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
  cluster: string
  // Names and ids travel together. The page shows the name and links on the id, and neither is
  // derivable from the other: discovery_mapping reads as "Value Chain Mapping", so a link built
  // by slugifying the label would point at nothing.
  depends_on: string[]
  depends_on_ids: string[]
  agents: string[]
  agent_ids: string[]
  triggers: string[]
  trigger_ids: string[]
}

// One orchestrator and the crews it owns. There is one today; the shape is plural because a
// second PMO is a data addition rather than a rewrite, and a view built around a single hard
// centre would have to be rebuilt to accept one.
export interface DataArchitectureCluster {
  cluster_id: string
  label: string
  note: string
  orchestrator_id: string
  orchestrator: string
  // The crews grouped by how deep in the pipeline they sit: one band is a set of crews that
  // could run at the same moment, because everything any of them waits on is in an earlier
  // band. This is what the ring is laid out from - a band is one position clockwise, however
  // many crews share it - because a flat list cannot say that two crews are parallel.
  crew_bands: string[][]
  // The same crews, flattened: the graph's own topological order, which the tables read. It is
  // crew_bands flattened in agents/graph.py, so the two cannot disagree.
  crew_ids: string[]
  // The crews the orchestrator can itself start - narrower than crew_ids, because three crews
  // are reachable only by a REST call or an approval cascade.
  dispatches: string[]
}

// Derived in agents/graph.py from what each crew writes and reads, never drawn by hand.
//   information - waits on it, and reads an artefact it wrote
//   sequencing  - waits on it, and reads nothing it wrote; ordering alone
//   inherited   - reads an artefact it wrote without waiting on it directly
export interface DataArchitectureCrewEdge {
  source: string
  target: string
  kind: 'information' | 'sequencing' | 'inherited'
  artefacts: string[]
  declared: boolean
  crosses_clusters: boolean
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
  via: string
  // Who is declared to read it. For a store handed to every agent by the dispatch path this is
  // empty, and handed_to_every_agent says so.
  read_by: string[]
  read_by_ids: string[]
  // Who *can* reach it: everyone holding the tool the read arrives through. A Chroma collection
  // is an argument to ChromaQueryTool, so this is wider than read_by and the difference is the
  // point - the declared list is the instructed readers, not the population with access.
  reachable_by: string[]
  reachable_by_ids: string[]
  handed_to_every_agent: boolean
}

export interface DataArchitecture {
  slug: string
  llm_mode: string
  inference: DataArchitectureInference
  tools: DataArchitectureToolRow[]
  declared_not_held: DataArchitectureUnheldTool[]
  agents: DataArchitectureAgent[]
  crews: DataArchitectureCrew[]
  clusters: DataArchitectureCluster[]
  crew_edges: DataArchitectureCrewEdge[]
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
