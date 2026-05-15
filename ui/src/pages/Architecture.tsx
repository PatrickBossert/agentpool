// ui/src/pages/Architecture.tsx
// Hidden internal reference page — not linked in nav.
// Access at /dashboard/architecture

const Section = ({ id, title, children }: { id: string; title: string; children: React.ReactNode }) => (
  <section id={id} className="mb-12">
    <h2 className="text-xl font-semibold text-brand mb-4 border-b border-slate-700 pb-2">{title}</h2>
    {children}
  </section>
)

const Card = ({ title, children, accent }: { title: string; children: React.ReactNode; accent?: string }) => (
  <div className={`bg-surface-raised rounded-lg border ${accent ?? 'border-slate-700'} p-4 mb-3`}>
    <h3 className="font-medium text-white mb-2">{title}</h3>
    {children}
  </div>
)

const Tag = ({ children, color = 'slate' }: { children: React.ReactNode; color?: 'teal' | 'violet' | 'amber' | 'slate' | 'green' }) => {
  const colors = {
    teal:   'bg-teal-900/50 text-teal-300 border-teal-700',
    violet: 'bg-violet-900/50 text-violet-300 border-violet-700',
    amber:  'bg-amber-900/50 text-amber-300 border-amber-700',
    slate:  'bg-slate-800 text-slate-300 border-slate-600',
    green:  'bg-green-900/50 text-green-300 border-green-700',
  }
  return (
    <span className={`inline-block text-xs px-2 py-0.5 rounded border mr-1 mb-1 ${colors[color]}`}>
      {children}
    </span>
  )
}

const KV = ({ k, v }: { k: string; v: string }) => (
  <div className="flex gap-2 text-sm py-0.5">
    <span className="text-slate-400 w-36 shrink-0">{k}</span>
    <span className="text-slate-200 font-mono">{v}</span>
  </div>
)

const TableRow = ({ cells }: { cells: (string | React.ReactNode)[] }) => (
  <tr className="border-t border-slate-700 hover:bg-slate-800/40">
    {cells.map((c, i) => (
      <td key={i} className="px-3 py-2 text-sm text-slate-300 align-top">{c}</td>
    ))}
  </tr>
)

const Th = ({ children }: { children: React.ReactNode }) => (
  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide">{children}</th>
)

export default function Architecture() {
  return (
    <div className="min-h-screen bg-surface text-white px-6 py-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-10">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-brand text-2xl">⬡</span>
          <h1 className="text-3xl font-bold text-white">Architecture Reference</h1>
          <span className="ml-2 text-xs bg-amber-900/50 text-amber-300 border border-amber-700 px-2 py-0.5 rounded">internal</span>
        </div>
        <p className="text-slate-400 text-sm">
          FutureMomentum — application architecture, agent inventory, data model, and tool access reference.
          Not linked from nav. Access at <code className="text-brand">/dashboard/architecture</code>.
        </p>
      </div>

      {/* TOC */}
      <nav className="bg-surface-card rounded-lg border border-slate-700 p-4 mb-10">
        <p className="text-xs text-slate-400 mb-2 uppercase tracking-wide">Contents</p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-1">
          {[
            ['#stack', 'Application Stack'],
            ['#pipeline', 'Orchestration Pipeline'],
            ['#crews', 'Crews'],
            ['#agents', 'Agents'],
            ['#tools', 'Agent Tools'],
            ['#data', 'Data Model'],
            ['#api', 'API Endpoints'],
            ['#frontend', 'Frontend Routes'],
            ['#integrations', 'External Integrations'],
          ].map(([href, label]) => (
            <a key={href} href={href} className="text-sm text-brand hover:text-brand-light underline-offset-2 hover:underline">
              {label}
            </a>
          ))}
        </div>
      </nav>

      {/* ── Application Stack ── */}
      <Section id="stack" title="Application Stack">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-800/60">
              <tr><Th>Service</Th><Th>Port</Th><Th>Technology</Th><Th>Role</Th></tr>
            </thead>
            <tbody>
              <TableRow cells={['Caddy reverse proxy', ':80', 'Caddy', 'Routes /api/* → FastAPI, /dashboard* → React, / → landing HTML']} />
              <TableRow cells={['FastAPI backend', ':8000', 'Python / FastAPI / uvicorn', 'REST API, crew dispatch, DB management, auth']} />
              <TableRow cells={['Chainlit app', ':8001', 'Python / Chainlit', 'Streaming crew execution UI']} />
              <TableRow cells={['React dashboard', ':3000', 'React / Vite / Tailwind', 'Main consultant UI (served under /dashboard)']} />
              <TableRow cells={['LiteLLM proxy', ':4000', 'LiteLLM', 'LLM routing — Claude Opus/Sonnet/Haiku + local qwen3']} />
              <TableRow cells={['ChromaDB', ':8002', 'ChromaDB (Docker)', 'Vector store — project docs + sector knowledge']} />
              <TableRow cells={['n8n', ':5678', 'n8n (Docker)', 'Webhook relay, HITL review events, Slack notifications']} />
              <TableRow cells={['Cloudflare Tunnel', '(managed)', 'cloudflared', 'Exposes :80 publicly at https://futuremomentum.ai']} />
              <TableRow cells={['llama.cpp', ':10000', 'llama.cpp / Unsloth', 'Local LLM endpoint (sensitive mode, Qwen3-4B)']} />
            </tbody>
          </table>
        </div>
        <p className="text-xs text-slate-500 mt-2">All services started by <code className="text-slate-300">start.sh</code>; Docker manages ChromaDB + n8n.</p>
      </Section>

      {/* ── Orchestration Pipeline ── */}
      <Section id="pipeline" title="Orchestration Pipeline">
        <p className="text-sm text-slate-400 mb-4">
          PAM (Programme Architecture Manager) orchestrates all specialist crews in two phases, with a human gate between them.
        </p>
        <div className="flex flex-col gap-3">
          {/* Trigger */}
          <div className="bg-surface-card rounded-lg border border-violet-700/50 p-4">
            <div className="text-xs text-violet-400 mb-1 uppercase tracking-wide">Trigger</div>
            <div className="font-mono text-sm text-white">POST /projects/{'{slug}'}/orchestrate</div>
            <p className="text-sm text-slate-400 mt-1">Also triggerable from Slack: <code className="text-slate-300">/run {'{'}{'{slug}'}{'}'}</code> → n8n → FastAPI</p>
          </div>

          {/* Phase 1 */}
          <div className="bg-surface-card rounded-lg border border-teal-700/50 p-4">
            <div className="text-xs text-teal-400 mb-1 uppercase tracking-wide">Phase 1 — Mapping</div>
            <ol className="text-sm text-slate-300 space-y-1 list-decimal ml-4">
              <li>Create <code>orchestration_runs</code> record (status: <Tag color="amber">running</Tag>)</li>
              <li>PAM dispatches <strong>Discovery Mapping Crew</strong> (Value Chain Mapper only)</li>
              <li>Produces: value chain Mermaid diagram + value_chain_tree (L1→L3 node hierarchy)</li>
              <li>Status advances to <Tag color="amber">awaiting_assignment</Tag></li>
            </ol>
          </div>

          {/* Human gate */}
          <div className="bg-surface-card rounded-lg border border-amber-700/50 p-4">
            <div className="text-xs text-amber-400 mb-1 uppercase tracking-wide">Human Gate — Stakeholder Assignment</div>
            <p className="text-sm text-slate-300">
              Consultant reviews the value chain, assigns stakeholders to value chain nodes via the
              Assignment page. <code className="text-slate-300">POST /projects/{'{slug}'}/assignment/{'{run_id}'}</code> stores assignments
              and triggers Phase 2.
            </p>
          </div>

          {/* Phase 2 */}
          <div className="bg-surface-card rounded-lg border border-teal-700/50 p-4">
            <div className="text-xs text-teal-400 mb-1 uppercase tracking-wide">Phase 2 — Delivery (PAM-orchestrated)</div>
            <ol className="text-sm text-slate-300 space-y-1 list-decimal ml-4">
              <li><em>If interview_method='agent':</em> <strong>Discovery Interviews Crew</strong> (voice/agent interviews → synthesis)</li>
              <li><strong>Value Design Crew</strong> — value propositions + portfolio scoring</li>
              <li><strong>Architecture Crew</strong> — current-state architecture + initiatives</li>
              <li><strong>Delivery Crew</strong> — phased roadmap HTML</li>
              <li><strong>Business Plan Crew</strong> — Word doc, PowerPoint deck, financial model</li>
            </ol>
            <p className="text-sm text-slate-400 mt-2">PAM uses <code className="text-slate-300">RunCrewTool</code> to dispatch each sub-crew sequentially. Slack notifications fire at each stage.</p>
          </div>

          {/* HITL reviews */}
          <div className="bg-surface-card rounded-lg border border-slate-600 p-4">
            <div className="text-xs text-slate-400 mb-1 uppercase tracking-wide">HITL Review Gates (optional, per settings)</div>
            <p className="text-sm text-slate-300">
              <code>HumanInputTool</code> pauses a crew, posts review event to n8n webhook → Slack DM to reviewer.
              Reviewer approves/rejects via Reviews page. Crew polls DB for response (24h timeout).
            </p>
          </div>
        </div>
      </Section>

      {/* ── Crews ── */}
      <Section id="crews" title="Crews">
        {[
          {
            name: 'Discovery Mapping Crew',
            file: 'agents/crews/discovery_mapping_crew.py',
            agents: ['Value Chain Mapper'],
            produces: 'value_chain Mermaid diagram, value_chain_tree (L1→L3 JSON)',
            trigger: 'PAM Phase 1',
          },
          {
            name: 'Discovery Interviews Crew',
            file: 'agents/crews/discovery_interviews_crew.py',
            agents: ['Interview Script Designer', 'Interview Coordinator', 'Stakeholder Interviewer', 'Synthesis Analyst'],
            produces: 'interview_sessions, interview_transcripts, activity_insights, requirements, value_levers',
            trigger: 'PAM Phase 2 (if interview_method=agent)',
          },
          {
            name: 'Value Design Crew',
            file: 'agents/crews/value_design_crew.py',
            agents: ['Value Proposition Generator (Opus)', 'Portfolio Manager (Haiku)'],
            produces: 'value_propositions (JSON), portfolio register, portfolio.xlsx',
            trigger: 'PAM Phase 2',
          },
          {
            name: 'Architecture Crew',
            file: 'agents/crews/architecture_crew.py',
            agents: ['Enterprise Architect', 'Initiative Identifier'],
            produces: 'architecture_register (data/tech/org layers), initiatives (JSON)',
            trigger: 'PAM Phase 2',
          },
          {
            name: 'Delivery Crew',
            file: 'agents/crews/delivery_crew.py',
            agents: ['Roadmap Generator'],
            produces: 'roadmap (JSON + interactive HTML), roadmap_data.json (for Gantt)',
            trigger: 'PAM Phase 2',
          },
          {
            name: 'Business Plan Crew',
            file: 'agents/crews/business_plan_crew.py',
            agents: ['Business Plan Generator (Opus)'],
            produces: 'business_plan.docx, business_plan.pptx, financial_model.xlsx (NPV/IRR/payback)',
            trigger: 'PAM Phase 2',
          },
          {
            name: 'PAM Mapping Crew',
            file: 'agents/crews/pam_crew.py',
            agents: ['PAM (Programme Architecture Manager)'],
            produces: 'Runs Discovery Mapping; sets status to awaiting_assignment',
            trigger: 'POST /orchestrate',
          },
          {
            name: 'PAM Resume Crew',
            file: 'agents/crews/pam_crew.py',
            agents: ['PAM (Programme Architecture Manager)'],
            produces: 'Orchestrates Phase 2 pipeline end-to-end',
            trigger: 'POST /assignment/{run_id}',
          },
        ].map((c) => (
          <Card key={c.name} title={c.name}>
            <div className="text-xs text-slate-500 font-mono mb-2">{c.file}</div>
            <div className="text-sm mb-1">
              <span className="text-slate-400">Agents: </span>
              {c.agents.map((a) => <Tag key={a} color="teal">{a}</Tag>)}
            </div>
            <div className="text-sm mb-1">
              <span className="text-slate-400">Produces: </span>
              <span className="text-slate-300">{c.produces}</span>
            </div>
            <div className="text-sm">
              <span className="text-slate-400">Triggered by: </span>
              <span className="text-slate-300">{c.trigger}</span>
            </div>
          </Card>
        ))}
      </Section>

      {/* ── Agents ── */}
      <Section id="agents" title="Agents">
        <p className="text-sm text-slate-400 mb-4">All agents are CrewAI agents backed by LiteLLM. Default model is Claude Sonnet unless noted.</p>

        {[
          {
            group: 'Discovery Phase',
            color: 'border-teal-700/40',
            agents: [
              {
                name: 'Value Chain Mapper',
                file: 'agents/discovery/value_chain_mapper.py',
                role: 'Produce a complete Mermaid value chain diagram from documents, links, and sector research.',
                tools: ['DocumentIngestionTool', 'ChromaQueryTool (project+sector)', 'TavilySearchTool', 'WebFetchTool', 'MermaidRenderTool', 'SQLiteStateTool', 'HumanInputTool'],
                output: 'value_chain (Mermaid), value_chain_summary (JSON), value_chain_tree (L1→L3 hierarchy)',
              },
              {
                name: 'Requirements Capture Specialist',
                file: 'agents/discovery/requirements_capture.py',
                role: 'Conduct a structured stakeholder interview to surface modernisation requirements.',
                tools: ['HumanInputTool', 'SQLiteStateTool'],
                output: 'interview_transcript (JSON Q&A pairs, 5–10 exchanges)',
              },
              {
                name: 'Requirements Analyst',
                file: 'agents/discovery/requirements_analyst.py',
                role: 'Synthesise interview transcripts and documents into a prioritised requirements register.',
                tools: ['DocumentIngestionTool', 'ChromaQueryTool (project+sector)', 'SQLiteStateTool', 'HumanInputTool'],
                output: 'requirements (JSON: REQ-001… with priority, value_chain_activity, acceptance_criteria)',
              },
              {
                name: 'Value Lever Analyst',
                file: 'agents/discovery/value_lever_analyst.py',
                role: 'Identify highest-impact value levers connecting requirements to sector benchmarks.',
                tools: ['ChromaQueryTool (sector)', 'TavilySearchTool', 'SQLiteStateTool', 'HumanInputTool'],
                output: 'value_levers (JSON: lever, description, value_impact, effort, related_requirements)',
              },
            ],
          },
          {
            group: 'Discovery Interviews Phase',
            color: 'border-cyan-700/40',
            agents: [
              {
                name: 'Interview Script Designer',
                file: 'agents/discovery/interview_script_designer.py',
                role: 'Produce one structured interview script per value chain node with pre-scripted branches and evasion signals.',
                tools: ['SQLiteStateTool', 'HumanInputTool'],
                output: 'interview_scripts (JSON keyed by node_label; 4–6 sections, 8–14 questions each)',
              },
              {
                name: 'Interview Coordinator',
                file: 'agents/discovery/interview_coordinator.py',
                role: 'Plan stakeholder interview programme; configure voice settings per locale using ElevenLabs voice IDs.',
                tools: ['SQLiteStateTool', 'HumanInputTool', 'InterviewSessionTool'],
                output: 'interview_plan (JSON: session_token, voice_config, node_label per stakeholder)',
              },
              {
                name: 'Stakeholder Interviewer',
                file: 'agents/discovery/stakeholder_interviewer.py',
                role: 'Orchestrate self-serve voice interview sessions and collect completed transcripts.',
                tools: ['SQLiteStateTool', 'HumanInputTool', 'InterviewSessionTool'],
                output: 'interview_transcripts (JSON: stakeholder_id, name, node_labels, qa_pairs)',
              },
              {
                name: 'Synthesis Analyst',
                file: 'agents/discovery/synthesis_analyst.py',
                role: 'Synthesise interview transcripts into activity insights, requirements, and value levers.',
                tools: ['SQLiteStateTool', 'HumanInputTool'],
                output: 'activity_insights (per L3 node), requirements register, value_levers',
              },
            ],
          },
          {
            group: 'Value Design Phase',
            color: 'border-violet-700/40',
            agents: [
              {
                name: 'Value Proposition Generator',
                file: 'agents/value_design/value_proposition_generator.py',
                role: 'Synthesise Discovery outputs into evidence-backed value propositions with business case. Uses Claude Opus.',
                tools: ['SQLiteStateTool', 'HumanInputTool'],
                output: 'value_propositions (JSON: VP-001… with description, business_outcome, supporting_requirements, activity_refs, beneficiaries)',
              },
              {
                name: 'Portfolio Manager',
                file: 'agents/value_design/portfolio_manager.py',
                role: 'Score value propositions across 8 IIRC capitals dimensions and produce a prioritised portfolio. Uses Claude Haiku.',
                tools: ['SQLiteStateTool', 'HumanInputTool', 'ExcelOutputTool'],
                output: 'portfolio (JSON with 8-dimension radar scores), portfolio.xlsx',
              },
            ],
          },
          {
            group: 'Architecture Phase',
            color: 'border-amber-700/40',
            agents: [
              {
                name: 'Enterprise Architect',
                file: 'agents/architecture/enterprise_architect.py',
                role: 'Extract current-state enterprise architecture layers from uploaded documents.',
                tools: ['ChromaQueryTool (project)', 'MermaidRenderTool', 'SQLiteStateTool', 'HumanInputTool'],
                output: 'architecture_register (JSON: data_layer, technology_layer, org_layer)',
              },
              {
                name: 'Initiative Identifier',
                file: 'agents/architecture/initiative_identifier.py',
                role: 'Identify transformation initiatives by mapping value propositions to architecture gaps.',
                tools: ['SQLiteStateTool', 'HumanInputTool'],
                output: 'initiatives (JSON: id, title, description, value_propositions_addressed, effort_estimate, cost_estimate, initiative_type, capability_uplifts)',
              },
            ],
          },
          {
            group: 'Delivery Phase',
            color: 'border-green-700/40',
            agents: [
              {
                name: 'Roadmap Generator',
                file: 'agents/delivery/roadmap_generator.py',
                role: 'Produce a phased delivery roadmap grouped by value stream and stakeholder group.',
                tools: ['SQLiteStateTool', 'HumanInputTool', 'HtmlRoadmapTool'],
                output: 'roadmap (JSON timeline), roadmap.html (interactive Mermaid), roadmap_data.json (for Gantt)',
              },
            ],
          },
          {
            group: 'Business Plan Phase',
            color: 'border-rose-700/40',
            agents: [
              {
                name: 'Business Plan Generator',
                file: 'agents/business_plan/business_plan_generator.py',
                role: 'Produce a comprehensive business case with executive summary, financials, risk/benefits, and implementation roadmap. Uses Claude Opus.',
                tools: ['SQLiteStateTool', 'HumanInputTool', 'WordOutputTool', 'PowerPointOutputTool', 'FinancialModelTool'],
                output: 'business_plan.docx (Word), business_plan.pptx (PowerPoint), financial_model.xlsx (5yr NPV/IRR/payback)',
              },
            ],
          },
          {
            group: 'Orchestration',
            color: 'border-brand/40',
            agents: [
              {
                name: 'PAM — Programme Architecture Manager',
                file: 'agents/pam/pam_agent.py',
                role: 'Top-level orchestrator. Dispatches and sequences all specialist crews across Phase 1 and Phase 2.',
                tools: ['RunCrewTool', 'SlackNotifyTool', 'SQLiteStateTool'],
                output: 'Orchestration log; downstream crew outputs; Slack progress messages',
              },
            ],
          },
        ].map((group) => (
          <div key={group.group} className="mb-6">
            <h3 className="text-sm font-semibold text-slate-300 mb-2">{group.group}</h3>
            {group.agents.map((a) => (
              <div key={a.name} className={`bg-surface-raised rounded-lg border ${group.color} p-4 mb-2`}>
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium text-white">{a.name}</span>
                  <span className="text-xs text-slate-500 font-mono shrink-0">{a.file}</span>
                </div>
                <p className="text-sm text-slate-400 my-1">{a.role}</p>
                <div className="text-sm mb-1">
                  <span className="text-slate-500 text-xs">Tools: </span>
                  {a.tools.map((t) => <Tag key={t} color="violet">{t}</Tag>)}
                </div>
                <div className="text-sm">
                  <span className="text-slate-500 text-xs">Output: </span>
                  <span className="text-slate-300 text-xs">{a.output}</span>
                </div>
              </div>
            ))}
          </div>
        ))}
      </Section>

      {/* ── Agent Tools ── */}
      <Section id="tools" title="Agent Tools">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-800/60">
              <tr><Th>Tool</Th><Th>File</Th><Th>What it does</Th><Th>External service</Th></tr>
            </thead>
            <tbody>
              {[
                ['DocumentIngestionTool', 'agents/tools/document_ingestion.py', 'Ingest .txt/.md/.pdf from projects/{slug}/docs/ into ChromaDB. 1000-char chunks, 200-char overlap.', 'ChromaDB :8002'],
                ['ChromaQueryTool', 'agents/tools/chroma_query.py', 'Query ChromaDB collections ({slug}_docs or sector_{sector}). Returns top-k chunks.', 'ChromaDB :8002'],
                ['TavilySearchTool', 'agents/tools/tavily_search.py', 'Web search for sector benchmarks and transformation patterns.', 'Tavily Search API'],
                ['WebFetchTool', 'agents/tools/web_fetch_tool.py', 'Fetch and extract plain text from URLs (used for discovery_links).', 'HTTP/S'],
                ['MermaidRenderTool', 'agents/tools/mermaid_render.py', 'Save Mermaid syntax to outputs/{filename}.md for front-end rendering.', 'None (local)'],
                ['SQLiteStateTool', 'agents/tools/sqlite_state.py', 'Read/write structured JSON state per (slug, agent_name, key). Persists agent outputs across crew tasks.', 'SQLite per-project DB'],
                ['HumanInputTool', 'agents/tools/human_input.py', 'Pause crew execution. POST HITL event to n8n webhook. Poll DB for reviewer decision (24h timeout).', 'n8n webhook → Slack'],
                ['RunCrewTool', 'agents/tools/run_crew.py', 'Dispatch a named sub-crew (discovery, value_design, architecture, delivery, business_plan, discovery_interviews) and await completion.', 'None (internal async)'],
                ['SlackNotifyTool', 'agents/tools/slack_notify.py', 'POST crew_notification event to n8n webhook → Slack channel message.', 'n8n webhook → Slack'],
                ['InterviewSessionTool', 'agents/tools/interview_session_tool.py', 'CRUD interview_sessions table. Operations: create, get_status, get_transcripts, mark_abandoned.', 'SQLite per-project DB'],
                ['ExcelOutputTool', 'agents/tools/excel_output.py', 'Export JSON data to .xlsx (portfolio output).', 'None (openpyxl local)'],
                ['HtmlRoadmapTool', 'agents/tools/html_roadmap.py', 'Render roadmap JSON to interactive Mermaid-timeline HTML. Also writes roadmap_data.json.', 'None (local)'],
                ['WordOutputTool', 'agents/tools/word_output.py', 'Export content to .docx (business plan).', 'None (python-docx local)'],
                ['PowerPointOutputTool', 'agents/tools/powerpoint_output.py', 'Export slides to .pptx (business plan deck).', 'None (python-pptx local)'],
                ['FinancialModelTool', 'agents/tools/financial_model.py', 'Generate 5-year financial projections (revenue, costs, NPV, IRR, payback period). Export to .xlsx.', 'None (openpyxl local)'],
              ].map((row) => <TableRow key={row[0] as string} cells={row} />)}
            </tbody>
          </table>
        </div>
      </Section>

      {/* ── Data Model ── */}
      <Section id="data" title="Data Model">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-300 mb-2">Per-project SQLite — <code className="text-slate-400">./data/{'{'}{'{slug}'}{'}'}.db</code></h3>
            {[
              { table: 'projects', desc: 'Project metadata', cols: 'id, slug, llm_mode, sector, config_json, status' },
              { table: 'orchestration_runs', desc: 'PAM pipeline executions', cols: 'id, project_id, status, started_at, completed_at' },
              { table: 'crew_runs', desc: 'Individual crew executions', cols: 'id, project_id, crew_name, status, result_json, orchestration_run_id' },
              { table: 'agent_outputs', desc: 'Output file artifacts', cols: 'id, project_id, agent_name, output_type, file_path, version, review_status' },
              { table: 'human_reviews', desc: 'HITL review records', cols: 'id, output_id, crew_run_id, reviewer, decision, prompt, notes' },
              { table: 'client_documents', desc: 'Uploaded source documents', cols: 'id, project_id, filename, file_path, content_type, ingested' },
              { table: 'stakeholders', desc: 'Stakeholder master register', cols: 'id, project_id, name, email, job_title, value_streams, interview_status, interview_invited_at' },
              { table: 'stakeholder_assignments', desc: 'PAM Phase 1 node assignments', cols: 'id, orchestration_run_id, stakeholder_id, level, node_label' },
              { table: 'interview_sessions', desc: 'Voice interview sessions', cols: 'id, project_id, stakeholder_id, session_token, status, transcript_json, ratings_json' },
              { table: 'campaigns', desc: 'Interview campaign tracking', cols: 'id, project_id, value_stream_name, campaign_name, interview_start, interview_close' },
              { table: 'interview_responses', desc: 'Imported interview data', cols: 'id, stakeholder_id, campaign_id, raw_data' },
              { table: 'reminder_emails', desc: 'Email reminder queue', cols: 'id, project_id, campaign_id, stakeholder_id, subject, body, escalation_level, status' },
              { table: 'node_template_assignments', desc: 'Interview template → node mapping', cols: 'id, project_id, node_label, interview_template_id, questionnaire_template_id' },
            ].map(({ table, desc, cols }) => (
              <div key={table} className="border-b border-slate-800 py-2">
                <div className="flex items-baseline gap-2">
                  <code className="text-teal-300 text-sm">{table}</code>
                  <span className="text-slate-500 text-xs">{desc}</span>
                </div>
                <div className="text-xs text-slate-600 font-mono mt-0.5">{cols}</div>
              </div>
            ))}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-slate-300 mb-2">System SQLite — <code className="text-slate-400">./data/system.db</code></h3>
            {[
              { table: 'users', desc: 'System user accounts', cols: 'id, username, hashed_pw, role, project_slug' },
              { table: 'interview_templates', desc: 'Reusable interview/questionnaire templates', cols: 'id, name, description, type, schema_json' },
            ].map(({ table, desc, cols }) => (
              <div key={table} className="border-b border-slate-800 py-2">
                <div className="flex items-baseline gap-2">
                  <code className="text-violet-300 text-sm">{table}</code>
                  <span className="text-slate-500 text-xs">{desc}</span>
                </div>
                <div className="text-xs text-slate-600 font-mono mt-0.5">{cols}</div>
              </div>
            ))}

            <h3 className="text-sm font-semibold text-slate-300 mt-6 mb-2">ChromaDB — <code className="text-slate-400">localhost:8002</code></h3>
            {[
              { coll: '{slug}_docs', desc: 'Project-scoped ingested documents (per project)' },
              { coll: 'sector_{sector}', desc: 'Shared sector knowledge base (pre-loaded)' },
            ].map(({ coll, desc }) => (
              <div key={coll} className="border-b border-slate-800 py-2">
                <div className="flex items-baseline gap-2">
                  <code className="text-amber-300 text-sm">{coll}</code>
                  <span className="text-slate-500 text-xs">{desc}</span>
                </div>
              </div>
            ))}

            <h3 className="text-sm font-semibold text-slate-300 mt-6 mb-2">Per-project config — <code className="text-slate-400">projects/{'{slug}'}/config.yaml</code></h3>
            <div className="text-xs text-slate-500 space-y-0.5 font-mono">
              {['llm_mode (standard|sensitive|fallback)', 'sector', 'stakeholder_groups []', 'value_stream_labels []', 'roadmap_time_axis', 'crews_enabled []', 'review_gates (bool)', 'slack_channel', 'discovery_brief', 'discovery_links []', 'interview_method (none|agent|manual)'].map((f) => (
                <div key={f} className="text-slate-500">{f}</div>
              ))}
            </div>
          </div>
        </div>
      </Section>

      {/* ── API Endpoints ── */}
      <Section id="api" title="API Endpoints">
        <p className="text-xs text-slate-500 mb-3">Base URL: <code className="text-slate-300">https://futuremomentum.ai/api</code> (locally: <code className="text-slate-300">http://localhost:8000</code>). JWT Bearer required except /auth/login and public interview routes.</p>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-800/60">
              <tr><Th>Method</Th><Th>Path</Th><Th>Purpose</Th></tr>
            </thead>
            <tbody>
              {[
                ['POST', '/auth/login', 'Authenticate (username+password form → JWT)'],
                ['POST', '/auth/users', 'Create user (admin only)'],
                ['GET', '/projects', 'List all projects'],
                ['POST', '/projects', 'Create project'],
                ['GET', '/projects/{slug}/status', 'Project status + latest orchestration run'],
                ['POST', '/projects/{slug}/orchestrate', 'Trigger PAM Phase 1 (async)'],
                ['GET', '/projects/{slug}/assignment/{run_id}', 'Get stakeholder assignments'],
                ['POST', '/projects/{slug}/assignment/{run_id}', 'Submit assignments → triggers Phase 2'],
                ['PATCH', '/projects/{slug}/orchestration-runs/{run_id}/advance', 'Manually advance run status'],
                ['GET/PATCH', '/projects/{slug}/settings', 'Project settings (LLM mode, sector, etc.)'],
                ['GET', '/projects/{slug}/runs', 'All orchestration + crew run history'],
                ['POST', '/projects/{slug}/run', 'Run a single crew directly'],
                ['GET', '/projects/{slug}/outputs', 'List output artifacts'],
                ['GET', '/projects/{slug}/outputs/{id}/content', 'View output content (Mermaid/HTML)'],
                ['GET', '/projects/{slug}/outputs/{id}/download', 'Download output file'],
                ['GET', '/projects/{slug}/documents', 'List uploaded documents'],
                ['POST', '/projects/{slug}/documents/upload', 'Upload source document'],
                ['GET', '/projects/{slug}/reviews', 'List HITL review items'],
                ['POST', '/projects/{slug}/review', 'Submit HITL review decision'],
                ['PATCH', '/projects/{slug}/reviews/{id}', 'Update review decision'],
                ['GET', '/projects/{slug}/stakeholders', 'List stakeholders'],
                ['POST', '/projects/{slug}/stakeholders', 'Create stakeholder'],
                ['POST', '/projects/{slug}/stakeholders/import', 'Bulk import from CSV'],
                ['PUT', '/projects/{slug}/stakeholders/{id}', 'Update stakeholder'],
                ['DELETE', '/projects/{slug}/stakeholders/{id}', 'Delete stakeholder'],
                ['GET', '/projects/{slug}/campaigns', 'List interview campaigns'],
                ['POST', '/projects/{slug}/campaigns', 'Create campaign'],
                ['GET', '/projects/{slug}/campaigns/{id}/export-targets', 'Export interview target CSV'],
                ['POST', '/projects/{slug}/campaigns/{id}/mark-invited', 'Mark stakeholders as invited'],
                ['POST', '/projects/{slug}/campaigns/{id}/import-progress', 'Import completion CSV'],
                ['POST', '/projects/{slug}/campaigns/{id}/import-results', 'Import results JSON/CSV'],
                ['POST', '/projects/{slug}/campaigns/{id}/generate-reminders', 'Generate reminder emails'],
                ['GET', '/projects/{slug}/reminder-emails', 'List pending reminder emails'],
                ['PATCH', '/projects/{slug}/reminder-emails/{id}', 'Approve or dismiss reminder'],
                ['POST', '/projects/{slug}/reminder-emails/send', 'Dispatch approved reminders via Resend'],
                ['GET', '/projects/{slug}/interview-summary', 'Interview completion dashboard stats'],
                ['GET', '/api/interviews/sessions/{slug}', 'List interview sessions (monitor panel)'],
                ['GET', '/api/interviews/{token}', 'Get session for voice interview (public)'],
                ['PATCH', '/api/interviews/{token}/complete', 'Mark session complete with ratings'],
                ['POST', '/api/interviews/{token}/speak', 'ElevenLabs TTS proxy'],
                ['GET', '/api/templates', 'List interview templates'],
                ['POST', '/api/templates', 'Create template'],
                ['PATCH', '/api/templates/{id}', 'Update template'],
                ['DELETE', '/api/templates/{id}', 'Delete template'],
                ['GET', '/projects/{slug}/value-chain', 'Get value chain output'],
                ['GET', '/projects/{slug}/roadmap', 'Get roadmap output'],
                ['GET', '/projects/{slug}/financial-summary', 'Business plan financial metrics'],
                ['GET', '/projects/{slug}/portfolio-register', 'Portfolio register (Value Propositions page)'],
                ['GET', '/projects/{slug}/roadmap-data', 'Roadmap JSON for Gantt chart'],
                ['WS', '/ws/{slug}', 'WebSocket — real-time crew log streaming'],
              ].map((row) => <TableRow key={row[0] + row[1]} cells={row} />)}
            </tbody>
          </table>
        </div>
      </Section>

      {/* ── Frontend Routes ── */}
      <Section id="frontend" title="Frontend Routes">
        <p className="text-xs text-slate-500 mb-3">All routes served under <code className="text-slate-300">basename=/dashboard</code>. Protected routes require JWT in AuthContext.</p>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-800/60">
              <tr><Th>Path</Th><Th>Component</Th><Th>Auth</Th><Th>Notes</Th></tr>
            </thead>
            <tbody>
              {[
                ['/login', 'Login', 'Public', 'JWT login form'],
                ['/interview/:sessionToken', 'VoiceInterview', 'Public', 'Self-serve voice interview portal (ElevenLabs + SpeechRecognition)'],
                ['/', 'Dashboard', 'Protected', 'Project list or selected project overview'],
                ['/:slug', 'Dashboard', 'Protected', 'Project dashboard with neural agent tree'],
                ['/:slug/discovery', 'Discovery', 'Protected', 'Discovery Interviews tab + Layer Map tab'],
                ['/:slug/value-chain', 'ValueChain', 'Protected', 'Setup tab (config) + Diagram tab (Mermaid)'],
                ['/:slug/value-propositions', 'ValuePropositions', 'Protected', 'Portfolio register with IIRC radar chart'],
                ['/:slug/roadmap', 'Roadmap', 'Protected', 'Timeline tab + Gantt tab + Initiative Register tab'],
                ['/:slug/business-plan', 'BusinessPlan', 'Protected', 'Financial metrics + output download cards'],
                ['/:slug/reviews', 'Reviews', 'Protected', 'HITL review queue + reminder email approval'],
                ['/:slug/runs', 'Runs', 'Protected', 'Orchestration + crew run history accordion'],
                ['/:slug/stakeholders', 'Stakeholders', 'Protected', 'Stakeholder registry list'],
                ['/:slug/stakeholders/new', 'StakeholderForm', 'Protected', 'Add stakeholder'],
                ['/:slug/stakeholders/:id/edit', 'StakeholderForm', 'Protected', 'Edit stakeholder'],
                ['/:slug/assignment', 'Assignment', 'Protected', 'Assign stakeholders to value chain nodes (PAM gate)'],
                ['/:slug/documents', 'Documents', 'Protected', 'Upload and manage source documents'],
                ['/:slug/templates', 'Templates', 'Protected', 'Interview template library'],
                ['/:slug/settings', 'Settings', 'Protected', 'Project configuration'],
                ['/:slug/report', 'Report', 'Protected', 'Client-ready PDF report (5 sections, print-optimised)'],
                ['/architecture', 'Architecture', 'Protected', 'This page'],
              ].map((row) => <TableRow key={row[0]} cells={row} />)}
            </tbody>
          </table>
        </div>
      </Section>

      {/* ── External Integrations ── */}
      <Section id="integrations" title="External Integrations">

        <Card title="n8n Automation" accent="border-orange-700/50">
          <KV k="URL" v="http://localhost:5678" />
          <KV k="Web UI" v="http://localhost:5678 (browser)" />
          <KV k="Auth method" v="Username + password (set during first-run setup)" />
          <KV k="Webhook path" v="/webhook/agentpool  (N8N_WEBHOOK_URL env var)" />
          <div className="mt-3 text-sm text-slate-300">
            <p className="text-slate-400 text-xs mb-1">Workflows:</p>
            <div className="space-y-1">
              <div><Tag color="amber">FutureMomentum Notifications</Tag> <span className="text-slate-400 text-xs">— Webhook → Switch on event_type → Slack HITL DM or Slack Channel Notify</span></div>
              <div><Tag color="amber">FutureMomentum Slack Run Command</Tag> <span className="text-slate-400 text-xs">— Slack /run slash command → POST /orchestrate → Slack confirm</span></div>
            </div>
          </div>
        </Card>

        <Card title="Slack" accent="border-purple-700/50">
          <KV k="Access method" v="OAuth2 via n8n (not direct API)" />
          <KV k="n8n credential name" v="AgentPool Slack (OAuth2)" />
          <KV k="HITL reviews" v="DM to reviewer's Slack ID (reviewer_slack_id field)" />
          <KV k="Crew notifications" v="Message to project's slack_channel (config.yaml)" />
          <KV k="Slash command" v="/run {slug}  →  triggers PAM Phase 1" />
        </Card>

        <Card title="Resend (Email)" accent="border-teal-700/50">
          <KV k="API endpoint" v="https://api.resend.com/emails  (POST)" />
          <KV k="Auth method" v="Bearer token (RESEND_API_KEY env var)" />
          <KV k="From address" v="FutureMomentum <noreply@futuremomentum.ai>" />
          <KV k="Use case" v="Stakeholder interview reminder emails (gentle / firm / urgent escalation)" />
          <KV k="Triggered by" v="POST /projects/{slug}/reminder-emails/send" />
          <p className="text-xs text-slate-500 mt-2">Domain futuremomentum.ai must be verified in Resend dashboard before emails deliver.</p>
        </Card>

        <Card title="Anthropic / Claude API" accent="border-rose-700/50">
          <KV k="Access method" v="Via LiteLLM proxy  (http://localhost:4000)" />
          <KV k="Auth method" v="ANTHROPIC_API_KEY env var (passed to LiteLLM)" />
          <KV k="Models used" v="claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5-20251001" />
          <KV k="Routing" v="standard mode → Claude; sensitive mode → local qwen3; fallback → Claude then local" />
          <KV k="PAM agent" v="Always Claude Opus (regardless of llm_mode)" />
        </Card>

        <Card title="ChromaDB (Vector Store)" accent="border-emerald-700/50">
          <KV k="Host" v="localhost:8002  (Docker container)" />
          <KV k="Auth method" v="None (local) or CHROMA_API_KEY env var (Cloud)" />
          <KV k="Access method" v="HTTP client via chromadb Python SDK" />
          <KV k="Collections" v="{slug}_docs (per project),  sector_{sector} (shared)" />
        </Card>

        <Card title="Tavily Search" accent="border-slate-600">
          <KV k="API endpoint" v="Tavily Search API (managed by tavily-python SDK)" />
          <KV k="Auth method" v="TAVILY_API_KEY env var" />
          <KV k="Used by" v="TavilySearchTool — sector research during Discovery and Value Lever analysis" />
        </Card>

        <Card title="ElevenLabs (TTS)" accent="border-yellow-700/50">
          <KV k="Access method" v="ElevenLabs REST API, proxied through FastAPI /api/interviews/{token}/speak" />
          <KV k="Auth method" v="ELEVENLABS_API_KEY env var" />
          <KV k="Used by" v="VoiceInterview page — agent speech synthesis during voice interviews" />
        </Card>

        <Card title="Deepgram (STT)" accent="border-blue-700/50">
          <KV k="Access method" v="Deepgram WebSocket API (temporary token fetched from /api/interviews/{token}/deepgram-token)" />
          <KV k="Auth method" v="DEEPGRAM_API_KEY env var (used server-side to issue short-lived tokens)" />
          <KV k="Used by" v="VoiceInterview page — stakeholder speech-to-text during voice interviews" />
        </Card>

        <Card title="Cloudflare Tunnel" accent="border-slate-600">
          <KV k="Public URL" v="https://futuremomentum.ai" />
          <KV k="Auth method" v="CLOUDFLARE_TUNNEL_TOKEN env var (outbound-only, no inbound ports needed)" />
          <KV k="Dashboard URL" v="Cloudflare Zero Trust dashboard" />
          <KV k="Access policy" v="Cloudflare Access — email OTP protects /dashboard/*; bypass for /api/* and /dashboard/interview/*" />
        </Card>

        <Card title="LiteLLM Proxy" accent="border-slate-600">
          <KV k="URL" v="http://localhost:4000" />
          <KV k="Config file" v="litellm_config.yaml" />
          <KV k="Models configured" v="claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5-20251001, qwen3-4b (local)" />
          <KV k="Local LLM backend" v="llama.cpp at localhost:10000 (OpenAI-compatible API)" />
        </Card>
      </Section>

      <div className="text-center text-slate-600 text-xs py-8 border-t border-slate-800">
        FutureMomentum internal architecture reference — not for distribution
      </div>
    </div>
  )
}
