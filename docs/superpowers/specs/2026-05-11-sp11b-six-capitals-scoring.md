# SP11b — Six Capitals Scoring Design

## Overview

Replace the portfolio_manager agent's 3-dimension scoring (value impact, feasibility, strategic fit) with an 8-dimension IIRC Six Capitals framework plus Safety and Performance. The Six Capitals collectively represent the resource cost/benefit lens; Safety and Performance are standalone operational dimensions critical to infrastructure projects.

The Value Propositions page already exists (shipped in SP11a). This sprint updates the agent prompt, output schema, TypeScript type, and UI to reflect the new scoring model.

---

## 1. Scoring Dimensions

All dimensions use a 0–10 scale where **5 = neutral (no change)**. Scores below 5 indicate depletion or degradation; scores above 5 indicate generation or improvement. The agent is instructed on the meaning and reference unit for each dimension.

| # | Dimension | Key | What the score means | Reference unit |
|---|---|---|---|---|
| 1 | Financial | `financial` | Net financial value relative to investment cost | NPV £M / IRR % |
| 2 | Manufactured | `manufactured` | Impact on physical assets and infrastructure condition | Asset replacement value £M |
| 3 | Intellectual | `intellectual` | Knowledge, IP, and data assets generated or consumed | R&D investment £M / IP count |
| 4 | Human | `human` | Workforce capability, capacity, and wellbeing | FTE-days / skills uplift |
| 5 | Social & Relationship | `social_relationship` | Stakeholder trust, community benefit, and partnerships | NPS / beneficiary count |
| 6 | Natural | `natural` | Net environmental impact (depletion or regeneration) | CO₂e t / water ML / land ha |
| 7 | Safety | `safety` | Risk reduction and ALARP compliance improvement | RIDDOR rate / safety risk score |
| 8 | Performance | `performance` | Operational throughput, availability, and capacity | Throughput % / availability % |

**Scoring guidance per dimension (baked into agent prompt):**
- 0 = severe depletion / maximum risk / zero performance benefit
- 5 = no change from baseline
- 10 = transformational positive contribution / full ALARP compliance / maximum throughput gain

---

## 2. Weights

Fixed infrastructure-appropriate defaults. No HITL weight prompt — weights are not adjustable per run in SP11b (future sprint may add project-level weight configuration).

| Dimension | Weight |
|---|---|
| Financial | 20 |
| Natural | 20 |
| Safety | 20 |
| Performance | 15 |
| Manufactured | 10 |
| Intellectual | 5 |
| Human | 5 |
| Social & Relationship | 5 |
| **Total** | **100** |

**Total score formula:**
```
total_score = (Σ score_i × weight_i / 100) × 10
```
Result is on a 0–100 scale, rounded to 1 decimal place.

---

## 3. Agent — `agents/value_design/portfolio_manager.py`

### Changes

The `create_portfolio_manager_task` function task description is rewritten:

1. Read approved propositions via SQLiteStateTool (unchanged).
2. **Remove** the HumanInputTool weight prompt (steps 2–4 in current task).
3. Score each proposition on all 8 dimensions (0–10, 5=neutral). Provide one-sentence rationale and one reference unit per dimension. Use the infrastructure unit reference table from the prompt.
4. Compute `total_score` using the fixed weights above.
5. Rank propositions by `total_score` descending; break ties alphabetically by title.
6. Build a JSON array using the new schema (Section 4).
7. Write via SQLiteStateTool + ExcelOutputTool (unchanged, column list updated).
8. HITL review step: unchanged — user still reviews and can request revisions.

### Excel columns (updated)
```
["rank", "id", "title", "value_estimate",
 "score_financial", "score_manufactured", "score_intellectual",
 "score_human", "score_social_relationship", "score_natural",
 "score_safety", "score_performance", "total_score"]
```

---

## 4. Output Schema

`portfolio_register.json` — array of objects with this shape:

```json
{
  "rank": 1,
  "id": "VP-001",
  "title": "...",
  "change_articulation": "...",
  "impacted_stakeholder_groups": ["..."],
  "value_estimate": "High",

  "score_financial": 7.5,
  "score_financial_rationale": "...",
  "score_financial_unit": "NPV £M",

  "score_manufactured": 6.0,
  "score_manufactured_rationale": "...",
  "score_manufactured_unit": "Asset replacement value £M",

  "score_intellectual": 5.5,
  "score_intellectual_rationale": "...",
  "score_intellectual_unit": "R&D £M / IP count",

  "score_human": 8.0,
  "score_human_rationale": "...",
  "score_human_unit": "FTE-days / skills uplift",

  "score_social_relationship": 6.5,
  "score_social_relationship_rationale": "...",
  "score_social_relationship_unit": "NPS / beneficiary count",

  "score_natural": 4.0,
  "score_natural_rationale": "...",
  "score_natural_unit": "CO₂e t / water ML / land ha",

  "score_safety": 9.0,
  "score_safety_rationale": "...",
  "score_safety_unit": "RIDDOR rate / safety risk score",

  "score_performance": 8.5,
  "score_performance_rationale": "...",
  "score_performance_unit": "Throughput % / availability %",

  "total_score": 74.5,
  "weights_used": {
    "financial": 20,
    "manufactured": 10,
    "intellectual": 5,
    "human": 5,
    "social_relationship": 5,
    "natural": 20,
    "safety": 20,
    "performance": 15
  }
}
```

Old fields removed: `score_value`, `score_feasibility`, `score_strategic_fit` and their rationale counterparts.

---

## 5. Frontend

### `ui/src/types.ts` — PortfolioItem

Replace the old interface with:

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

### `ui/src/pages/ValuePropositions.tsx`

**Table columns** (simplified from 8 to 5):
```
# | ID | Title | Value Est. | Total
```

**Expanded row** (replaces current 3-column rationale grid):

Left panel — Recharts `RadarChart`:
- 8 axes: Financial, Manufactured, Intellectual, Human, Social, Natural, Safety, Performance
- Domain: 0–10
- Reference ring at value 5 (neutral)
- Single `Radar` polygon per item, brand teal fill (`fill="#14b8a6"`, `fillOpacity={0.3}`)

Right panel — rationale list:
- 8 rows: `[Dimension label] (unit) — score badge — one-sentence rationale`
- Styled with existing `text-slate-*` tokens

Footer line:
```
Weights — Financial ×20, Natural ×20, Safety ×20, Performance ×15, Manufactured ×10, Intellectual ×5, Human ×5, Social ×5
```

**Remove** the amber "coming soon" banner.

---

## 6. Tests

### `tests/test_projects_api.py`

Update fixture in `test_portfolio_register_returns_data` to use the new 8-dimension schema fields. Remove old `score_value`, `score_feasibility`, `score_strategic_fit` fields. Assert on `data[0]["score_financial"]` instead of `data[0]["score_value"]`.

---

## 7. Files Affected

### Modified
- `agents/value_design/portfolio_manager.py` — task description rewrite
- `ui/src/types.ts` — PortfolioItem interface replacement
- `ui/src/pages/ValuePropositions.tsx` — table + expanded row with radar chart
- `tests/test_projects_api.py` — fixture update

### New
None.

---

## 8. Out of Scope

- Financial capital quantification via CapEx/OpEx modelling (SP11b uses the 0–10 score; the reference unit is informational only)
- Per-project configurable weights (future sprint)
- Weight prompt / HITL weight adjustment
- Any changes to other agents or crews
- SP10c/10d discovery crew split
