// ui/src/types.ts

export interface Project {
  id: number
  slug: string
  llm_mode: string
  sector: string
  status: string
}

export interface CrewRun {
  id: number
  project_id: number
  crew_name: string
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed'
  result_json: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface OrchestrationRun {
  id: number
  status: string  // 'running' | 'completed' | 'failed'
  started_at: string | null
  completed_at: string | null
}

export interface ProjectStatus {
  project_slug: string
  project_status: string
  crew_runs: CrewRun[]
  latest_orchestration_run: OrchestrationRun | null
}

export interface AgentOutput {
  id: number
  agent_name: string
  output_type: string
  file_path: string
  version: number
  review_status: string
  created_at: string
}

export interface ClientDocument {
  id: number
  project_id: number
  filename: string
  original_name: string
  file_path: string
  content_type: string
  size_bytes: number
  ingested: boolean
  uploaded_at: string
}

export interface Review {
  id: number
  output_id: number
  decision: string
  notes: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface UserPayload {
  sub: string
  role: string
  exp: number
}
