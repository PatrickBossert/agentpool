# SP15a — Client Report PDF

## Overview

A print-to-PDF report page that consolidates all pipeline outputs into a single polished client-facing document. The user clicks "Export Report" on the Dashboard, a new browser tab opens at `/:slug/report`, and a print dialog fires automatically. The client receives a professional A4 PDF covering value propositions, initiative register, and financial headline metrics — with references to the full deliverable files.

---

## Section 1 — Report Structure

The report renders as a full-page document styled for A4 print. Sections in order:

### 1. Cover Page
- Full-page, vertically centred
- Large **org name** (from ProjectSettings `org_name` or `client_name`)
- Project slug / name below
- Generation date (formatted: "14 May 2026")
- "Prepared by AgentPool" footer
- Thin teal horizontal rule separating title block from footer

### 2. Value Propositions
- One card per proposition: title, description, 8-dimension Six Capitals radar chart
- Reuses existing `RadarChart` component from `ui/src/components/RadarChart.tsx`
- Page break after section

### 3. Initiative Register
- Table grouped by value stream
- Columns: Initiative Name | Type | Cost Estimate | Capability Uplifts
- Unassigned bucket for initiatives with no value stream
- Same data as the Register tab on Roadmap page
- Page break after section

### 4. Financial Summary
- Six headline metrics in a 2×3 card grid: NPV, IRR, Payback Period, Total Investment, Total Benefits, Max Borrowing
- Same data as BusinessPlan.tsx
- Page break after section

### 5. Document Reference
- Clean list of deliverable files: Business Plan (DOCX), Executive Presentation (PPTX), Financial Model (XLSX)
- Shows version number and generation date for each
- Note: "Full documents available in the AgentPool Documents tab"

---

## Section 2 — Print CSS and Visual Design

### Dual rendering modes

**Screen mode** (browser preview):
- Dark app background, brand teal accents
- "Print / Save as PDF" button fixed top-right
- Nav and sidebar hidden — `Report.tsx` renders outside `AppLayout`

**Print mode** (`@media print`):
- White background, black body text
- Teal used only for headings and accents
- Print button hidden (`display: none`)
- `page-break-before: always` between sections
- Body 11pt, headings 16pt / 13pt, A4 sizing
- RadarChart renders as inline SVG — survives print faithfully (no canvas)
- Tables: clean borders, no alternating row shading

### Auto-print on load
```tsx
useEffect(() => {
  const timer = setTimeout(() => window.print(), 300)
  return () => clearTimeout(timer)
}, [])
```
300ms delay allows full render before dialog fires. User can cancel to preview.

---

## Section 3 — Files, Data Flow, Edge Cases

### New files

| File | Purpose |
|---|---|
| `ui/src/pages/Report.tsx` | Report page — cover, propositions, initiatives, financials, doc reference |
| `ui/src/pages/Report.css` | Print-specific styles (isolated from app styles) |

### Modified files

| File | Change |
|---|---|
| `ui/src/App.tsx` | Add `/:slug/report` route (outside AppLayout) |
| `ui/src/pages/Dashboard.tsx` | Add "Export Report" button near "View Last Run →" |

### Data flow

`Report.tsx` fires four parallel fetches on mount:

| Endpoint | Data used |
|---|---|
| `GET /projects/{slug}/settings` | org_name / client_name for cover page |
| `GET /projects/{slug}/financial-summary` | NPV, IRR, Payback, Investment, Benefits, Max Borrowing |
| `GET /projects/{slug}/portfolio-register` | Value propositions + 8-dimension IIRC scores |
| `GET /projects/{slug}/outputs` | Deliverable file list for Document Reference section |

### Edge cases

| Scenario | Behaviour |
|---|---|
| Pipeline never run | Each section shows muted "No data yet" placeholder — report still printable |
| Partial pipeline (e.g. discovery only) | Financial summary shows placeholder; completed sections render normally |
| RadarChart with no scores | Section hidden gracefully (same as ValuePropositions page) |
| No output files generated | Document Reference section shows "No deliverable files generated yet" |
| Not logged in | API calls return 401 — page shows "Unauthorised" and redirects to login |

### No backend changes
All data comes from existing endpoints. No new API routes, no DB migrations, no new backend tests.

---

## Task breakdown (2 tasks)

**Task 1 — Report.tsx + print CSS:** Build `Report.tsx` with all five sections, `Report.css` with print media query, wire `/:slug/report` route in `App.tsx`.

**Task 2 — Dashboard entry point + smoke test:** Add "Export Report" button to Dashboard.tsx. Open report in new tab. Smoke test in browser: cover page, each section renders, print dialog fires, PDF output looks correct.
