# SP11b — Six Capitals Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the portfolio_manager agent's 3-dimension scoring (value, feasibility, strategic fit) with 8-dimension IIRC Six Capitals + Safety + Performance scoring, and update the Value Propositions UI to show a radar chart instead of individual score columns.

**Architecture:** The agent task description is rewritten with 8 fixed-weight dimensions and no HITL weight prompt. The JSON output schema gains 8×3 fields (score, rationale, unit per dimension) replacing the old 3×2 fields. The TypeScript type and React page are updated to match — the table simplifies to 5 columns and the expanded row renders a Recharts RadarChart alongside 8 rationale rows.

**Tech Stack:** Python/CrewAI (agent), pytest (backend tests), TypeScript/React (frontend), Recharts RadarChart (already in `ui/package.json`), TanStack Query

---

## File Map

| File | Change |
|---|---|
| `agents/value_design/portfolio_manager.py` | Full task description rewrite |
| `tests/test_projects_api.py:101–134` | Update fixture to new 8-dimension schema |
| `ui/src/types.ts:219–234` | Replace PortfolioItem interface |
| `ui/src/pages/ValuePropositions.tsx` | Full rewrite — simplified table + RadarChart expanded row |

---

## Task 1: Update test fixture to new schema

**Files:**
- Modify: `tests/test_projects_api.py:101–134`

The test `test_portfolio_register_returns_data` currently uses the old 3-dimension fixture. Update it to the new 8-dimension schema so any schema validation is exercised by the test.

The API endpoint is schema-agnostic (it passes JSON through), so the test will still pass — but the fixture and assertions must match the new schema.

- [ ] **Step 1: Open the test file and locate the fixture**

  Read `tests/test_projects_api.py` lines 100–135 to see the current fixture (shown for reference):

  ```python
  register = [
      {
          "rank": 1,
          "id": "VP-001",
          "title": "Modernise Asset Management",
          "change_articulation": "Replaces manual inspection logs with IoT-driven data.",
          "impacted_stakeholder_groups": ["Operations", "Safety"],
          "value_estimate": "High",
          "score_value": 8.0,
          "score_feasibility": 7.0,
          "score_strategic_fit": 9.0,
          "score_value_rationale": "Direct cost reduction.",
          "score_feasibility_rationale": "APIs exist.",
          "score_strategic_fit_rationale": "Core strategy.",
          "total_score": 80.0,
          "weights_used": {"value": 5, "feasibility": 3, "strategic_fit": 2},
      }
  ]
  ```

- [ ] **Step 2: Replace the fixture with the new 8-dimension schema**

  Replace the entire `register` list (lines ~105–122) and the two assertions (lines ~132–134) with:

  ```python
      register = [
          {
              "rank": 1,
              "id": "VP-001",
              "title": "Modernise Asset Management",
              "change_articulation": "Replaces manual inspection logs with IoT-driven data.",
              "impacted_stakeholder_groups": ["Operations", "Safety"],
              "value_estimate": "High",
              "score_financial": 7.0,
              "score_financial_rationale": "Reduces OpEx by automating inspections.",
              "score_financial_unit": "NPV £M",
              "score_manufactured": 6.5,
              "score_manufactured_rationale": "Extends asset life through predictive maintenance.",
              "score_manufactured_unit": "Asset replacement value £M",
              "score_intellectual": 5.5,
              "score_intellectual_rationale": "Generates proprietary sensor datasets.",
              "score_intellectual_unit": "R&D £M / IP count",
              "score_human": 6.0,
              "score_human_rationale": "Upskills maintenance staff in data analysis.",
              "score_human_unit": "FTE-days / skills uplift",
              "score_social_relationship": 5.5,
              "score_social_relationship_rationale": "Improves regulator confidence through transparency.",
              "score_social_relationship_unit": "NPS / beneficiary count",
              "score_natural": 6.0,
              "score_natural_rationale": "Reduces unnecessary site visits and emissions.",
              "score_natural_unit": "CO₂e t / water ML / land ha",
              "score_safety": 8.0,
              "score_safety_rationale": "Early fault detection reduces RIDDOR-reportable incidents.",
              "score_safety_unit": "RIDDOR rate / safety risk score",
              "score_performance": 7.5,
              "score_performance_rationale": "Increases asset availability by reducing unplanned outages.",
              "score_performance_unit": "Throughput % / availability %",
              "total_score": 68.5,
              "weights_used": {
                  "financial": 20,
                  "manufactured": 10,
                  "intellectual": 5,
                  "human": 5,
                  "social_relationship": 5,
                  "natural": 20,
                  "safety": 20,
                  "performance": 15,
              },
          }
      ]
  ```

  And update the assertions:

  ```python
      assert resp.status_code == 200
      data = resp.json()
      assert len(data) == 1
      assert data[0]["id"] == "VP-001"
      assert data[0]["score_financial"] == 7.0
      assert data[0]["weights_used"]["safety"] == 20
  ```

- [ ] **Step 3: Run the test to verify it passes**

  ```bash
  pytest tests/test_projects_api.py::test_portfolio_register_returns_data -v
  ```

  Expected output: `PASSED`

- [ ] **Step 4: Run the full portfolio-register test group**

  ```bash
  pytest tests/test_projects_api.py -k "portfolio_register" -v
  ```

  Expected: 3 passed (empty, returns_data, unknown_project)

- [ ] **Step 5: Commit**

  ```bash
  git add tests/test_projects_api.py
  git commit -m "test: update portfolio register fixture to 8-dimension Six Capitals schema"
  ```

---

## Task 2: Rewrite portfolio_manager agent task description

**Files:**
- Modify: `agents/value_design/portfolio_manager.py`

Replace the entire `create_portfolio_manager_task` function. The key changes:
- Remove the HITL weight prompt (old steps 2–4)
- Replace 3-dimension scoring with 8-dimension IIRC Six Capitals + Safety + Performance
- Add the dimension reference table and fixed weights to the prompt
- Update the JSON schema in the prompt to the new shape
- Update ExcelOutputTool column list
- Renumber steps (old 12 steps → new 10 steps)

No tests for agent prompts — correctness is verified by running the crew. Commit immediately after.

- [ ] **Step 1: Replace `create_portfolio_manager_task` in its entirety**

  Open `agents/value_design/portfolio_manager.py`. Replace the `create_portfolio_manager_task` function (lines 26–96) with:

  ```python
  def create_portfolio_manager_task(agent: Agent, context_tasks: list[Task]) -> Task:
      return Task(
          description=(
              "Score and rank the value propositions into a prioritised portfolio register "
              "using the IIRC Six Capitals framework plus Safety and Performance dimensions.\n\n"
              "Steps:\n"
              "1. Use SQLiteStateTool with operation='read', key='propositions', "
              "agent_name='portfolio_manager' to retrieve the approved value propositions.\n"
              "2. Score each proposition on all 8 dimensions below using a 0–10 scale where "
              "5 = neutral (no change from baseline), 0 = maximum depletion/risk/degradation, "
              "10 = transformational positive contribution. "
              "Provide one sentence of rationale and one reference unit per dimension.\n\n"
              "Dimension reference table (key | meaning | reference unit):\n"
              "  financial           | Net financial value relative to investment cost "
              "| NPV £M / IRR %\n"
              "  manufactured        | Impact on physical assets and infrastructure condition "
              "| Asset replacement value £M\n"
              "  intellectual        | Knowledge, IP, and data assets generated or consumed "
              "| R&D investment £M / IP count\n"
              "  human               | Workforce capability, capacity, and wellbeing "
              "| FTE-days / skills uplift\n"
              "  social_relationship | Stakeholder trust, community benefit, and partnerships "
              "| NPS / beneficiary count\n"
              "  natural             | Net environmental impact (depletion or regeneration) "
              "| CO₂e t / water ML / land ha\n"
              "  safety              | Risk reduction and ALARP compliance improvement "
              "| RIDDOR rate / safety risk score\n"
              "  performance         | Operational throughput, availability, and capacity "
              "| Throughput % / availability %\n\n"
              "3. Apply these fixed infrastructure weights (they sum to 100 — do not change them):\n"
              "   financial=20, manufactured=10, intellectual=5, human=5, "
              "social_relationship=5, natural=20, safety=20, performance=15\n"
              "4. Compute total_score using the formula:\n"
              "   total_score = (score_financial*20 + score_manufactured*10 "
              "+ score_intellectual*5 + score_human*5 + score_social_relationship*5 "
              "+ score_natural*20 + score_safety*20 + score_performance*15) / 100 * 10\n"
              "   Round to 1 decimal place. Result is on a 0–100 scale.\n"
              "   Example: scores 7,6,5,8,6,4,9,8 → "
              "(140+60+25+40+30+80+180+120)/100*10 = 67.5\n"
              "5. Rank propositions by total_score descending (rank 1 = highest). "
              "Break ties alphabetically by title.\n"
              "6. Build a JSON array where each item follows this schema exactly:\n"
              "   {\n"
              "     \"rank\": 1,\n"
              "     \"id\": \"VP-001\",\n"
              "     \"title\": \"...\",\n"
              "     \"change_articulation\": \"...\",\n"
              "     \"impacted_stakeholder_groups\": [...],\n"
              "     \"value_estimate\": \"High|Medium|Low\",\n"
              "     \"score_financial\": 7.5,\n"
              "     \"score_financial_rationale\": \"...\",\n"
              "     \"score_financial_unit\": \"NPV £M\",\n"
              "     \"score_manufactured\": 6.0,\n"
              "     \"score_manufactured_rationale\": \"...\",\n"
              "     \"score_manufactured_unit\": \"Asset replacement value £M\",\n"
              "     \"score_intellectual\": 5.5,\n"
              "     \"score_intellectual_rationale\": \"...\",\n"
              "     \"score_intellectual_unit\": \"R&D £M / IP count\",\n"
              "     \"score_human\": 8.0,\n"
              "     \"score_human_rationale\": \"...\",\n"
              "     \"score_human_unit\": \"FTE-days / skills uplift\",\n"
              "     \"score_social_relationship\": 6.5,\n"
              "     \"score_social_relationship_rationale\": \"...\",\n"
              "     \"score_social_relationship_unit\": \"NPS / beneficiary count\",\n"
              "     \"score_natural\": 4.0,\n"
              "     \"score_natural_rationale\": \"...\",\n"
              "     \"score_natural_unit\": \"CO\\u2082e t / water ML / land ha\",\n"
              "     \"score_safety\": 9.0,\n"
              "     \"score_safety_rationale\": \"...\",\n"
              "     \"score_safety_unit\": \"RIDDOR rate / safety risk score\",\n"
              "     \"score_performance\": 8.5,\n"
              "     \"score_performance_rationale\": \"...\",\n"
              "     \"score_performance_unit\": \"Throughput % / availability %\",\n"
              "     \"total_score\": 74.5,\n"
              "     \"weights_used\": {\"financial\": 20, \"manufactured\": 10, "
              "\"intellectual\": 5, \"human\": 5, \"social_relationship\": 5, "
              "\"natural\": 20, \"safety\": 20, \"performance\": 15}\n"
              "   }\n"
              "7. Use SQLiteStateTool with operation='write', key='portfolio_register', "
              "agent_name='portfolio_manager' to save the JSON array.\n"
              "8. Use ExcelOutputTool with:\n"
              "    - rows: the portfolio register list\n"
              "    - columns: [\"rank\", \"id\", \"title\", \"value_estimate\", "
              "\"score_financial\", \"score_manufactured\", \"score_intellectual\", "
              "\"score_human\", \"score_social_relationship\", \"score_natural\", "
              "\"score_safety\", \"score_performance\", \"total_score\"]\n"
              "    - filename: 'portfolio_register.xlsx'\n"
              "    - agent_name: 'portfolio_manager'\n"
              "9. Use HumanInputTool with prompt: 'Portfolio register scored and saved to "
              "outputs/portfolio_register.xlsx. Please review the rankings. "
              "Reply \"approved\" to proceed, or provide notes.'\n"
              "10. If revision notes are received, revise scores or ranking and repeat "
              "steps 7–9. Maximum 3 revision cycles.\n"
          ),
          expected_output=(
              "A JSON portfolio register saved to outputs/portfolio_register.json "
              "and an Excel file at outputs/portfolio_register.xlsx, "
              "each containing all value propositions ranked by IIRC Six Capitals weighted score. "
              "Confirmed approved by a human reviewer."
          ),
          agent=agent,
          context=context_tasks,
      )
  ```

- [ ] **Step 2: Verify the file parses (no syntax errors)**

  ```bash
  python3 -c "import ast; ast.parse(open('agents/value_design/portfolio_manager.py').read()); print('OK')"
  ```

  Expected: `OK`

- [ ] **Step 3: Commit**

  ```bash
  git add agents/value_design/portfolio_manager.py
  git commit -m "feat: rewrite portfolio_manager task to IIRC Six Capitals 8-dimension scoring"
  ```

---

## Task 3: Replace PortfolioItem TypeScript type

**Files:**
- Modify: `ui/src/types.ts:219–234`

Replace the old 3-dimension PortfolioItem interface with the new 8-dimension one. This will cause TypeScript errors in `ValuePropositions.tsx` (which still references old fields) — that's expected and will be fixed in Task 4.

- [ ] **Step 1: Replace the PortfolioItem interface**

  In `ui/src/types.ts`, replace lines 219–234 (the entire `PortfolioItem` interface) with:

  ```ts
  export interface PortfolioItem {
    rank: number
    id: string
    title: string
    change_articulation: string
    impacted_stakeholder_groups: string[]
    value_estimate: 'High' | 'Medium' | 'Low'

    score_financial: number
    score_financial_rationale: string
    score_financial_unit: string

    score_manufactured: number
    score_manufactured_rationale: string
    score_manufactured_unit: string

    score_intellectual: number
    score_intellectual_rationale: string
    score_intellectual_unit: string

    score_human: number
    score_human_rationale: string
    score_human_unit: string

    score_social_relationship: number
    score_social_relationship_rationale: string
    score_social_relationship_unit: string

    score_natural: number
    score_natural_rationale: string
    score_natural_unit: string

    score_safety: number
    score_safety_rationale: string
    score_safety_unit: string

    score_performance: number
    score_performance_rationale: string
    score_performance_unit: string

    total_score: number
    weights_used: {
      financial: number
      manufactured: number
      intellectual: number
      human: number
      social_relationship: number
      natural: number
      safety: number
      performance: number
    }
  }
  ```

- [ ] **Step 2: Verify TypeScript errors exist in ValuePropositions.tsx**

  ```bash
  cd ui && npx tsc --noEmit 2>&1 | grep "ValuePropositions"
  ```

  Expected: errors referencing `score_value`, `score_feasibility`, `score_strategic_fit` — confirms the type change is effective and Task 4 is needed.

- [ ] **Step 3: Commit the type (with known downstream errors)**

  ```bash
  git add ui/src/types.ts
  git commit -m "feat: replace PortfolioItem with 8-dimension Six Capitals schema"
  ```

---

## Task 4: Rewrite ValuePropositions.tsx with radar chart

**Files:**
- Modify: `ui/src/pages/ValuePropositions.tsx` (full rewrite)

Replace the page with a 5-column table and an expanded row containing a Recharts RadarChart (8 axes, domain 0–10, dashed neutral ring at 5) beside a rationale list. Remove the amber banner.

`recharts` is already in `ui/package.json` — no install needed.

- [ ] **Step 1: Replace ValuePropositions.tsx in full**

  Write the entire file:

  ```tsx
  // ui/src/pages/ValuePropositions.tsx
  import { Fragment, useState } from 'react'
  import { useParams, useNavigate } from 'react-router-dom'
  import { useQuery } from '@tanstack/react-query'
  import {
    RadarChart,
    PolarGrid,
    PolarAngleAxis,
    Radar,
    ResponsiveContainer,
  } from 'recharts'
  import { projectsApi } from '../api/endpoints'
  import type { PortfolioItem } from '../types'

  const DIMENSIONS = [
    { key: 'financial' as const,           label: 'Financial' },
    { key: 'manufactured' as const,        label: 'Manufactured' },
    { key: 'intellectual' as const,        label: 'Intellectual' },
    { key: 'human' as const,               label: 'Human' },
    { key: 'social_relationship' as const, label: 'Social' },
    { key: 'natural' as const,             label: 'Natural' },
    { key: 'safety' as const,              label: 'Safety' },
    { key: 'performance' as const,         label: 'Performance' },
  ]

  type DimKey = typeof DIMENSIONS[number]['key']

  function getScore(item: PortfolioItem, key: DimKey): number {
    const map: Record<DimKey, number> = {
      financial: item.score_financial,
      manufactured: item.score_manufactured,
      intellectual: item.score_intellectual,
      human: item.score_human,
      social_relationship: item.score_social_relationship,
      natural: item.score_natural,
      safety: item.score_safety,
      performance: item.score_performance,
    }
    return map[key]
  }

  function getUnit(item: PortfolioItem, key: DimKey): string {
    const map: Record<DimKey, string> = {
      financial: item.score_financial_unit,
      manufactured: item.score_manufactured_unit,
      intellectual: item.score_intellectual_unit,
      human: item.score_human_unit,
      social_relationship: item.score_social_relationship_unit,
      natural: item.score_natural_unit,
      safety: item.score_safety_unit,
      performance: item.score_performance_unit,
    }
    return map[key]
  }

  function getRationale(item: PortfolioItem, key: DimKey): string {
    const map: Record<DimKey, string> = {
      financial: item.score_financial_rationale,
      manufactured: item.score_manufactured_rationale,
      intellectual: item.score_intellectual_rationale,
      human: item.score_human_rationale,
      social_relationship: item.score_social_relationship_rationale,
      natural: item.score_natural_rationale,
      safety: item.score_safety_rationale,
      performance: item.score_performance_rationale,
    }
    return map[key]
  }

  function radarData(item: PortfolioItem) {
    return DIMENSIONS.map(({ key, label }) => ({
      dimension: label,
      score: getScore(item, key),
      neutral: 5,
    }))
  }

  function valueEstimateColour(v: string) {
    if (v === 'High') return 'text-brand-green'
    if (v === 'Medium') return 'text-amber-400'
    return 'text-slate-400'
  }

  export default function ValuePropositions() {
    const { slug } = useParams<{ slug: string }>()
    const navigate = useNavigate()
    const [expandedId, setExpandedId] = useState<string | null>(null)

    const { data: items = [], isLoading } = useQuery<PortfolioItem[]>({
      queryKey: ['portfolio-register', slug],
      queryFn: () => projectsApi.portfolioRegister(slug!),
      enabled: !!slug,
    })

    function toggleRow(id: string) {
      setExpandedId((prev) => (prev === id ? null : id))
    }

    if (isLoading) {
      return (
        <div className="p-6">
          <p className="text-sm text-slate-500">Loading…</p>
        </div>
      )
    }

    return (
      <div className="p-6">
        <h2 className="text-lg font-semibold text-slate-100 mb-1">Value Propositions</h2>
        <p className="text-slate-400 text-sm mb-6">Scored and ranked by the Portfolio Manager agent.</p>

        {items.length === 0 ? (
          <div className="bg-surface-card rounded-xl p-8 text-center max-w-lg">
            <p className="text-slate-300 text-sm font-medium mb-2">No value propositions yet</p>
            <p className="text-slate-500 text-xs leading-relaxed mb-4">
              The Portfolio Manager agent scores and ranks propositions after the Value Design crew
              completes. Run the pipeline from the Dashboard.
            </p>
            <button
              onClick={() => navigate(`/${slug}`)}
              className="px-4 py-2 bg-brand hover:bg-brand-dark text-white text-sm rounded"
            >
              Run Pipeline →
            </button>
          </div>
        ) : (
          <div className="bg-surface-card rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-xs text-slate-500 uppercase tracking-wide">
                  <th className="text-left px-4 py-3 w-10">#</th>
                  <th className="text-left px-4 py-3 w-16">ID</th>
                  <th className="text-left px-4 py-3">Title</th>
                  <th className="text-left px-4 py-3 w-20">Est.</th>
                  <th className="text-right px-4 py-3 w-16">Total</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <Fragment key={item.id}>
                    <tr
                      onClick={() => toggleRow(item.id)}
                      className="border-b border-slate-800 hover:bg-slate-800/40 cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-3 text-slate-500">{item.rank}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">{item.id}</td>
                      <td className="px-4 py-3 text-slate-200 font-medium">{item.title}</td>
                      <td className={`px-4 py-3 text-xs font-semibold ${valueEstimateColour(item.value_estimate)}`}>
                        {item.value_estimate}
                      </td>
                      <td className="px-4 py-3 text-right font-semibold text-brand">
                        {item.total_score.toFixed(1)}
                      </td>
                    </tr>
                    {expandedId === item.id && (
                      <tr key={`${item.id}-detail`} className="border-b border-slate-800 bg-slate-900/40">
                        <td colSpan={5} className="px-6 py-4">
                          <p className="text-sm text-slate-300 leading-relaxed mb-4">
                            {item.change_articulation}
                          </p>
                          <p className="text-xs text-slate-500 mb-4">
                            <span className="font-semibold text-slate-400">Stakeholders: </span>
                            {item.impacted_stakeholder_groups.join(', ')}
                          </p>
                          <div className="flex gap-6">
                            <div className="w-56 shrink-0">
                              <ResponsiveContainer width="100%" height={220}>
                                <RadarChart data={radarData(item)}>
                                  <PolarGrid stroke="#334155" />
                                  <PolarAngleAxis
                                    dataKey="dimension"
                                    tick={{ fill: '#94a3b8', fontSize: 10 }}
                                  />
                                  <Radar
                                    name="neutral"
                                    dataKey="neutral"
                                    stroke="#475569"
                                    strokeDasharray="3 3"
                                    fill="none"
                                    dot={false}
                                  />
                                  <Radar
                                    name="score"
                                    dataKey="score"
                                    stroke="#14b8a6"
                                    fill="#14b8a6"
                                    fillOpacity={0.3}
                                    dot={false}
                                  />
                                </RadarChart>
                              </ResponsiveContainer>
                            </div>
                            <div className="flex-1 space-y-2">
                              {DIMENSIONS.map(({ key, label }) => (
                                <div key={key} className="flex gap-2 text-xs">
                                  <span className="w-24 shrink-0 font-semibold text-slate-400">
                                    {label}
                                  </span>
                                  <span className="w-8 shrink-0 text-center font-mono text-brand">
                                    {getScore(item, key).toFixed(1)}
                                  </span>
                                  <span className="text-slate-500 leading-relaxed">
                                    ({getUnit(item, key)}) — {getRationale(item, key)}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                          <p className="text-xs text-slate-600 mt-4">
                            Weights — Financial ×{item.weights_used.financial}, Natural ×{item.weights_used.natural}, Safety ×{item.weights_used.safety}, Performance ×{item.weights_used.performance}, Manufactured ×{item.weights_used.manufactured}, Intellectual ×{item.weights_used.intellectual}, Human ×{item.weights_used.human}, Social ×{item.weights_used.social_relationship}
                          </p>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    )
  }
  ```

- [ ] **Step 2: Verify TypeScript compiles with no errors**

  ```bash
  cd ui && npx tsc --noEmit 2>&1
  ```

  Expected: no output (zero errors). If errors appear, fix them before proceeding.

- [ ] **Step 3: Run the full backend test suite to confirm no regressions**

  ```bash
  pytest tests/test_projects_api.py tests/test_project_service.py -q
  ```

  Expected: all tests pass.

- [ ] **Step 4: Commit**

  ```bash
  git add ui/src/pages/ValuePropositions.tsx
  git commit -m "feat: update Value Propositions page with Six Capitals radar chart"
  ```

---

## Self-Review

**Spec coverage check:**
- [x] Section 1 (8 dimensions + units) → Task 2 agent prompt
- [x] Section 2 (fixed weights, formula) → Task 2 agent prompt
- [x] Section 3 (agent rewrite, Excel columns, HITL review kept) → Task 2
- [x] Section 4 (JSON schema, old fields removed) → Task 1 (test fixture) + Task 2 (prompt schema)
- [x] Section 5 (PortfolioItem type) → Task 3
- [x] Section 5 (table 5 cols, RadarChart, rationale list, footer, remove banner) → Task 4
- [x] Section 6 (test fixture update) → Task 1

**Placeholder scan:** No TBDs. All code blocks are complete.

**Type consistency:** `DimKey` used in `getScore`, `getUnit`, `getRationale` — all consistent. `weights_used` keys in type match keys in fixture and agent prompt. `score_social_relationship` key consistent across all four files.
