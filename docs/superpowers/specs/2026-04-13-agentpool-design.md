# AgentPool — Digital Modernisation Agent Team
## Master Design Specification
**Date:** 2026-04-13  
**Status:** Approved for implementation planning  
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Purpose

Build a team of specialist AI agents on a Mac Mini (M2/M4 Pro, 16-24GB RAM) that automates and supports digital modernisation strategy and roadmap development across multiple client projects. Agents collaborate to produce value chains, requirements registers, value propositions, enterprise architecture artefacts, initiative registers, illustrated roadmaps, and full business plans.

---

## 2. Project Decomposition

The system is built in four sequential sub-projects:

| Sub-project | Name | Depends on |
|---|---|---|
| SP1 | Infrastructure Foundation | — |
| SP2 | Thin Shell Web Platform | SP1 |
| SP3 | Specialist Agent Pool | SP1 |
| SP4 | Integration & Orchestration | SP1, SP2, SP3 |

SP2 and SP3 can partially overlap once SP1 is stable.

---

## 3. Technology Stack

### Core Framework
- **Agent framework:** CrewAI (Python) — Crews, Agents, Tasks, Flows
- **LLM routing:** LiteLLM Proxy (:4000) — unified endpoint for all agents
- **Local LLM:** Qwen3 4B (thinking mode) via existing llama.cpp server (:10000)
- **Cloud LLM:** Anthropic Claude API (Opus 4.6 / Sonnet 4.6 / Haiku 4.5)
- **API bridge:** FastAPI (:8000)
- **HITL chat UI:** Chainlit (:8001)
- **Workflow/Slack/triggers:** n8n (:5678) via Docker Desktop
- **Vector store:** ChromaDB (:8002) via Docker Desktop
- **Structured state:** SQLite — one `.db` file per project
- **Web platform:** React + Vite + TypeScript + Tailwind (:3000)

### Existing services (unchanged)
- llama.cpp + Qwen3 4B: `localhost:10000`
- Gemma4 via OpenWebUI: `localhost:8080` (potential future LiteLLM route)

### Per-project LLM routing modes
- `standard` → Claude API
- `sensitive` → llama.cpp only (all data stays local)
- `fallback` → Claude API with llama.cpp fallback on unavailability/rate-limit

---

## 4. Directory Structure

```
~/agentpool/
  agents/           # CrewAI agent definitions (one file per agent)
  crews/            # Crew + Flow definitions
  tools/            # Shared agent tools (search, ingest, output, etc.)
  api/              # FastAPI application
  ui/               # React + Vite web platform
  chainlit_app/     # Chainlit HITL interface
  workflows/        # n8n exported workflow JSONs
  data/
    chroma/         # ChromaDB persistent storage
    {slug}.db       # SQLite per project
  projects/
    {client-slug}/
      config.yaml   # Per-client config
      docs/         # Uploaded client documents
      outputs/      # Agent-generated artefacts (versioned)
  models/
    qwen3-4b-q4_k_m.gguf   # (existing)
  docker-compose.yml        # n8n + ChromaDB
  litellm_config.yaml       # LiteLLM routing rules
  requirements.txt
```

---

## 5. Per-Project Config Schema

```yaml
client_slug: "acme-rail"
llm_mode: "standard"           # standard | sensitive | fallback
sector: "transport"
stakeholder_groups:
  - "Operations"
  - "Customer"
  - "Finance"
  - "Technology"
value_stream_labels:
  - "Asset Management"
  - "Passenger Experience"
  - "Corporate"
roadmap_time_axis: "quarters"  # quarters | years | horizons
crews_enabled:
  - discovery
  - value_design
  - architecture
  - delivery
review_gates: true
slack_channel: "#acme-rail-agents"
```

---

## 6. Agent Pool

### Orchestrator

#### Programme Architecture Manager (PAM)
- **Model:** Claude Opus 4.6
- **Interaction:** Checkpoint-driven — human approval required at each crew boundary
- **Role:** Master orchestrator. Invokes crews in dependency order, aggregates results, manages project state, sends Slack/n8n notifications, enforces review gates.
- **Tools:** Crew invocation, dependency graph management, timeline/sequencing logic, SQLite read/write, Slack notifications via n8n
- **Inputs:** Project brief + config.yaml
- **Outputs:** Full roadmap + business plan (assembled from all crew outputs)

---

### Crew 1 — Discovery

#### Value Chain Mapper
- **Model:** Claude Sonnet 4.6
- **Interaction:** Conversational HITL — iterates value chain stages and activities with human via Chainlit until approved
- **Tools:** Tavily web search, PDF/DOCX ingestion, Mermaid diagram generation, ChromaDB RAG (sector knowledge base), Chainlit stage/activity edit loop
- **Inputs:** Company brief, annual reports, sector context
- **Outputs:** Approved value chain (entities × stages × activities) + pain points per cell

#### Requirements Analyst
- **Model:** Claude Sonnet 4.6
- **Interaction:** Conversational HITL — conducts stakeholder interviews via Chainlit; delivers online questionnaires via n8n/email
- **Tools:** Chainlit chat, n8n questionnaire form delivery, transcript ingestion + structuring, ChromaDB requirements store
- **Inputs:** Approved value chain, stakeholder list
- **Outputs:** Structured requirements register

#### Value Lever Analyst
- **Model:** Claude Sonnet 4.6 (standard); Qwen3 4B via llama.cpp (sensitive projects)
- **Interaction:** Automated — bulk document batch processing; human review of output register
- **Tools:** PDF ingestion (annual reports), Tavily financial/market search, table/figure extraction, openpyxl Excel output
- **Note:** Primary candidate for local LLM routing. Document-heavy, repetitive extraction reduces token cost significantly via Qwen3 4B.
- **Inputs:** Annual reports, market data, financial filings
- **Outputs:** Value lever register with sizing estimates

---

### Crew 2 — Value Design

#### Value Proposition Generator
- **Model:** Claude Opus 4.6
- **Interaction:** Automated synthesis → human review gate before portfolio management
- **Tools:** Multi-source synthesis across Discovery outputs, financial estimation logic, python-docx proposition documents, ChromaDB proposition store
- **Inputs:** Value lever register, requirements register, value chain
- **Outputs:** Value proposition statements with change articulation and value estimates

#### Portfolio Manager
- **Model:** Claude Haiku 4.5
- **Interaction:** HITL — human defines and iterates ranking criteria; agent applies weighted scoring
- **Tools:** Chainlit ranking criteria dialogue, SQLite portfolio state, openpyxl portfolio register, weighted scoring engine, Slack notifications via n8n
- **Inputs:** Value propositions, human-defined ranking criteria
- **Outputs:** Prioritised portfolio register

---

### Crew 3 — Architecture

#### Enterprise Architect
- **Model:** Claude Sonnet 4.6
- **Interaction:** Automated extraction → human review of captured artefacts
- **Tools:** PDF/DOCX/XLSX ingestion, Mermaid architecture diagram generation, ChromaDB architecture register, structured extraction prompts for data/tech/org domains
- **Inputs:** Architecture documents, org charts, system inventories, technology registers
- **Outputs:** Current-state architecture register (data, technology, organisation layers)

#### Initiative Identifier
- **Model:** Claude Sonnet 4.6
- **Interaction:** Automated — gap analysis and complexity scoring; human review of output
- **Tools:** Capability mapping logic, gap analysis (propositions vs. architecture), complexity scoring rubric, initiative categorisation (enabling / operating model / business change)
- **Inputs:** Value propositions, architecture register, requirements register
- **Outputs:** Initiative register with category, complexity score, and capability gaps

---

### Crew 4 — Delivery Planning

#### Roadmap Generator
- **Model:** Claude Sonnet 4.6
- **Interaction:** Conversational HITL — format and articulation guidance; iterates until approved
- **Tools:** Dependency graph resolution, prioritisation scoring (value/effort/risk), Chainlit articulation format dialogue, HTML/SVG visual roadmap renderer, wave/horizon structuring
- **Visual roadmap output:** Interactive HTML timeline — value proposition icons placed across configurable time periods, organised into value stream rows (one per stakeholder group from config). Beneficiary dot markers per period. Exportable PNG/PDF.
- **Gantt output:** Separate Gantt chart for business plan (project management artefact, not stakeholder communication)
- **Inputs:** Initiative register, project constraints, client config (stakeholder groups, time axis)
- **Outputs:** Visual roadmap (HTML + PNG/PDF) + Gantt chart data

#### Business Plan Generator
- **Model:** Claude Opus 4.6
- **Interaction:** Conversational HITL — gathers business context upfront; iterative section-by-section review
- **Tools:** Chainlit context gathering + section review conversation, python-docx Word business plan, python-pptx executive slide deck, openpyxl cost/benefit model, full assembly of all prior crew outputs
- **Inputs:** All prior crew outputs + business context from conversation
- **Outputs:** Business plan (DOCX) + executive presentation (PPTX) + cost/benefit model (XLSX)

---

## 7. SP1 — Infrastructure Foundation

### Services & Ports

| Service | Port | Runtime |
|---|---|---|
| llama.cpp (existing) | 10000 | launchd (existing) |
| OpenWebUI / Gemma4 (existing) | 8080 | existing |
| LiteLLM Proxy | 4000 | Python service / launchd |
| FastAPI | 8000 | Python service / launchd |
| Chainlit | 8001 | Python service / launchd |
| n8n | 5678 | Docker Desktop |
| ChromaDB | 8002 | Docker Desktop |
| React dev server | 3000 | npm (dev) / nginx (prod) |

### LiteLLM Config (litellm_config.yaml)
Routes all agent LLM calls based on project `llm_mode`:
- `standard`: Claude Opus 4.6, Sonnet 4.6, Haiku 4.5 via Anthropic API
- `sensitive`: Qwen3 4B via `http://localhost:10000` (OpenAI-compatible)
- `fallback`: Claude API primary, llama.cpp on error/rate-limit

### Embedding
- Model: `nomic-embed-text` via llama.cpp
- All vector indexing stays local — no cloud embedding API calls
- One ChromaDB collection per project: `{client-slug}_docs`
- Shared sector knowledge base collection: `sector_knowledge`

### SQLite Schema (per project)
- `projects` — client config, LLM mode, status
- `crew_runs` — crew execution log + results
- `agent_outputs` — artefacts with version history
- `human_reviews` — review status, reviewer notes, timestamps
- `users` — user accounts + roles (consultant / client-readonly)

### FastAPI Endpoints (SP1)
```
POST   /projects                    Create new client project
POST   /projects/{id}/run           Trigger PAM or specific crew
GET    /projects/{id}/status        PAM state + crew progress
GET    /projects/{id}/outputs       List agent artefacts
WS     /ws/{id}                     Live agent log stream
```

### n8n Workflows
1. **Slack bot** — receive `/run {project}` commands, send crew status updates
2. **Webhook trigger** — external POST → FastAPI /run
3. **Scheduled runs** — cron-based crew execution
4. **Questionnaire delivery** — HTML forms to stakeholders via email/Slack
5. **Review notifications** — Slack DM when human review required

### Slack App Setup
Required bot scopes: `chat:write`, `commands`, `channels:read`, `im:write`  
Credentials stored in n8n Slack credential node (Bot Token + Signing Secret)

---

## 8. SP2 — Thin Shell Web Platform

### Stack
- **Frontend:** React 18 + Vite + TypeScript + Tailwind CSS
- **State:** React Query (async state + polling)
- **Routing:** React Router v6
- **Charts:** Recharts (cost/benefit views)
- **Roadmap canvas:** react-flow (extensible node-graph)
- **Backend:** FastAPI (shared with SP1, SP2 adds read/review endpoints)

### Authentication
- JWT-based, two roles from v1:
  - `consultant` — full access (you)
  - `client-readonly` — read-only access scoped to their project
- Simple admin UI to create client credentials

### V1 Views

#### Dashboard
- Project switcher sidebar (all client projects)
- Crew progress indicators (live via WebSocket)
- Review queue — pending human approvals with action buttons
- Recent agent outputs with status badges
- Quick-links to Chainlit and n8n UIs

#### Value Chain View
- Entity rows × stage columns grid
- Expandable activity lists per cell
- Pain points and opportunities surfaced per cell
- Approve / Request changes action
- Export to DOCX / PDF

#### Roadmap View
- **Visual tab:** Value stream rows × time axis (configurable: quarters/years/horizons per project config). Value proposition icons positioned on timeline. Beneficiary dot markers per period. Export to PNG/PDF.
- **Gantt tab:** Project management Gantt for business plan. Initiative bars across timeline with dependencies.

#### Document Library
- Upload section: PDF/DOCX/XLSX → triggers ChromaDB ingestion pipeline
- Source documents (client uploads)
- Generated outputs (agent artefacts, versioned)
- Download in original format

### FastAPI Endpoints (SP2 additions)
```
GET    /projects                         List all projects
GET    /projects/{id}/value-chain        Structured value chain output
GET    /projects/{id}/roadmap            Roadmap data model
GET    /projects/{id}/documents          Document library
POST   /projects/{id}/documents/upload   Ingest new document
POST   /projects/{id}/review             Submit human review decision
```

### Extensibility
Future views (SP2+ phases) are each a new React route + FastAPI endpoint. No structural platform changes required:
- Value Propositions, Capabilities, Architecture Register, Initiative Register, Stakeholder CRM, Business Plan, Operating Model, People & Change

---

## 9. SP3 — Specialist Agent Pool

Build all 9 agents + PAM as defined in Section 6. Each agent is implemented as:
1. A CrewAI `Agent` definition with role, goal, backstory, and tool list
2. A set of `Task` definitions (one per agent responsibility)
3. A `Crew` grouping agents into the four crew categories
4. HITL callbacks where interaction mode requires it

### Shared Tool Registry
Tools available for injection into any agent:
- `TavilySearchTool` — web and financial search
- `DocumentIngestionTool` — PDF/DOCX/XLSX → ChromaDB chunks
- `ChromaQueryTool` — RAG retrieval from project collection
- `MermaidRenderTool` — generate Mermaid diagram strings
- `ExcelOutputTool` — openpyxl write to XLSX
- `WordOutputTool` — python-docx write to DOCX
- `PowerPointOutputTool` — python-pptx write to PPTX
- `SQLiteStateTool` — read/write project state
- `HumanInputTool` — Chainlit HITL callback

---

## 10. SP4 — Integration & Orchestration

End-to-end flows connecting all sub-projects:

1. **Project creation flow:** n8n webhook / Slack command → FastAPI → create project config → initialise ChromaDB collection + SQLite DB → notify Slack
2. **Crew execution flow:** PAM trigger → Crew 1 (Discovery) → human review gate → Crew 2 (Value Design) → gate → Crew 3 (Architecture) → gate → Crew 4 (Delivery) → gate → Business Plan
3. **HITL flow:** Agent requests input → Chainlit session opens → human responds → agent continues → output written to SQLite + file system → platform view updates via WebSocket
4. **Document ingestion flow:** Upload via platform → FastAPI → chunking → nomic-embed-text → ChromaDB → available to all agents in project
5. **Notification flow:** Crew completion / review required → FastAPI → n8n webhook → Slack DM to consultant channel

---

## 11. Build Order & Key Dependencies

```
SP1 (weeks 1-3)
  └─ llama.cpp: already running
  └─ Docker: n8n + ChromaDB containers
  └─ LiteLLM proxy configured + tested
  └─ FastAPI skeleton + SQLite schema
  └─ Chainlit shell
  └─ Slack app created + n8n credential connected

SP2 (weeks 3-5, can start after SP1 FastAPI is up)
  └─ React scaffold + routing
  └─ Dashboard + WebSocket live status
  └─ Document Library + upload/ingest pipeline
  └─ Value Chain View (read + review)
  └─ Roadmap View (visual + Gantt tabs)
  └─ JWT auth (consultant + client-readonly)

SP3 (weeks 4-8, can start after SP1)
  └─ Shared tool registry
  └─ Crew 1 agents (Discovery) — PAM + Value Chain Mapper first
  └─ Crew 2 agents (Value Design)
  └─ Crew 3 agents (Architecture)
  └─ Crew 4 agents (Delivery Planning)

SP4 (weeks 7-9, after SP1+SP2+SP3 cores are stable)
  └─ End-to-end flow testing
  └─ n8n workflow wiring
  └─ Review gate integration
  └─ First full client project run
```

---

## 12. Open Questions / Decisions Deferred

- Gemma4 (OpenWebUI :8080) — available as optional third LiteLLM route for future use cases; not used in v1
- Roadmap icon library — client-specific icons vs. generic set; deferred to SP3 Roadmap Generator implementation
- Business plan template — section structure TBD in SP3; gathered conversationally per engagement
- Client read-only access — URL structure for client-scoped views TBD in SP2
