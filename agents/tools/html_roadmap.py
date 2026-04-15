# agents/tools/html_roadmap.py
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_agent_output_sync

_CATEGORY_COLOURS: dict[str, str] = {
    "enabling": "#3b82f6",
    "operating_model": "#f59e0b",
    "business_change": "#22c55e",
}

_HTML_HEADER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Delivery Roadmap</title>
<style>
  body { font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }
  h1 { font-size: 1.5rem; margin-bottom: 24px; }
  .value-stream { margin-bottom: 40px; }
  .vs-header { font-size: 1.1rem; font-weight: 700; background: #1e3a5f; color: white;
               padding: 8px 12px; margin: 0; border-radius: 4px 4px 0 0; }
  table.roadmap-grid { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #d1d5db; padding: 6px 8px; vertical-align: top;
           min-width: 120px; }
  th.row-label, td.row-label { font-weight: 600; background: #f9fafb; min-width: 140px;
                                white-space: nowrap; font-size: 0.85rem; }
  th.period-header { background: #f3f4f6; font-weight: 700; text-align: center;
                     font-size: 0.85rem; }
  .vp-chip { display: inline-block; background: #eff6ff; border: 1px solid #bfdbfe;
             border-radius: 4px; padding: 2px 6px; font-size: 0.78rem; margin: 2px; }
  .init-chip { display: inline-block; color: white; border-radius: 4px;
               padding: 3px 7px; font-size: 0.78rem; margin: 2px; }
  .complexity-badge { background: rgba(0,0,0,0.25); border-radius: 3px;
                      padding: 0 3px; font-size: 0.72rem; }
  .capability-label { background: #f0fdf4; color: #166534; }
  .benefits-label { background: #fefce8; color: #713f12; }
  .benefit-block { margin-bottom: 4px; }
  .lever-names { font-size: 0.78rem; display: block; color: #374151; }
  .estimate-badge { display: inline-block; border-radius: 4px; padding: 1px 6px;
                    font-size: 0.75rem; font-weight: 700; margin-top: 2px; }
  .badge-high { background: #dcfce7; color: #166534; }
  .badge-medium { background: #fef9c3; color: #713f12; }
  .badge-low { background: #fee2e2; color: #991b1b; }
</style>
</head>
<body>
<h1>Delivery Roadmap</h1>
"""

_HTML_FOOTER = "</body></html>"


class HtmlRoadmapToolInput(BaseModel):
    roadmap_data: dict[str, Any] = Field(
        description=(
            "Roadmap JSON object with keys: periods (list), value_streams (list), "
            "stakeholder_groups (list), initiatives (list), propositions (list)."
        )
    )
    filename: str = Field(
        default="roadmap.html",
        description="Output filename. .html extension added automatically if missing.",
    )
    agent_name: str = Field(
        description="Name of the agent producing this output (used for output tracking)."
    )


class HtmlRoadmapTool(BaseTool):
    name: str = "HtmlRoadmapTool"
    description: str = (
        "Render a roadmap_data JSON object as a self-contained HTML roadmap file "
        "in the project outputs directory. Returns the absolute file path to the saved file."
    )
    args_schema: type[BaseModel] = HtmlRoadmapToolInput
    slug: str

    def _run(
        self,
        roadmap_data: dict[str, Any],
        filename: str = "roadmap.html",
        agent_name: str = "",
    ) -> str:
        settings = get_settings()
        outputs_dir = Path(settings.projects_dir) / self.slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        if not filename.endswith(".html"):
            filename = f"{filename}.html"
        file_path = outputs_dir / filename

        try:
            html = self._render_html(roadmap_data)
            file_path.write_text(html, encoding="utf-8")
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="html",
                file_path=str(file_path),
            )
        except (OSError, ValueError, KeyError) as e:
            return f"Error: render failed — {e}"

        return str(file_path)

    def _render_html(self, roadmap_data: dict[str, Any]) -> str:
        periods: list[str] = roadmap_data["periods"]
        value_streams: list[str] = roadmap_data["value_streams"]
        stakeholder_groups: list[str] = roadmap_data.get("stakeholder_groups", [])
        initiatives: list[dict] = roadmap_data.get("initiatives", [])
        propositions: list[dict] = roadmap_data.get("propositions", [])

        parts: list[str] = [_HTML_HEADER]

        for vs in value_streams:
            vs_initiatives = [i for i in initiatives if vs in i.get("value_streams", [])]
            vs_propositions = [p for p in propositions if vs in p.get("value_streams", [])]

            parts.append(f'<div class="value-stream">')
            parts.append(f'<h2 class="vs-header">{vs}</h2>')
            parts.append('<table class="roadmap-grid"><thead><tr>')
            parts.append('<th class="row-label"></th>')
            for period in periods:
                parts.append(f'<th class="period-header">{period}</th>')
            parts.append('</tr></thead><tbody>')

            # One row per stakeholder group — shows VP titles for matching group + period
            for sg in stakeholder_groups:
                parts.append(f'<tr><td class="row-label">{sg}</td>')
                for period in periods:
                    cell_vps = [
                        p for p in vs_propositions
                        if sg in p.get("impacted_stakeholder_groups", [])
                        and p.get("realisation_period") == period
                    ]
                    cells = "".join(
                        f'<span class="vp-chip">{p["title"]}</span>'
                        for p in cell_vps
                    )
                    parts.append(f'<td class="vp-cell">{cells}</td>')
                parts.append("</tr>")

            # Capability Builds row — initiatives coloured by category
            parts.append('<tr><td class="row-label capability-label">Capability Builds</td>')
            for period in periods:
                cell_inits = [i for i in vs_initiatives if i.get("period") == period]
                cells = "".join(
                    '<span class="init-chip" style="background:{colour}">'
                    "{title} "
                    '<span class="complexity-badge">{score}</span>'
                    "</span>".format(
                        colour=_CATEGORY_COLOURS.get(i.get("category", ""), "#9ca3af"),
                        title=i["title"],
                        score=i.get("complexity_score", ""),
                    )
                    for i in cell_inits
                )
                parts.append(f'<td class="init-cell">{cells}</td>')
            parts.append("</tr>")

            # Benefits row — value lever names + estimate badge per VP realisation period
            parts.append('<tr><td class="row-label benefits-label">Benefits</td>')
            for period in periods:
                period_vps = [p for p in vs_propositions if p.get("realisation_period") == period]
                cells = ""
                for p in period_vps:
                    levers = " · ".join(p.get("value_levers", []))
                    estimate = p.get("value_estimate", "")
                    cells += (
                        '<div class="benefit-block">'
                        f'<span class="lever-names">{levers}</span>'
                        f'<span class="estimate-badge badge-{estimate.lower()}">{estimate}</span>'
                        "</div>"
                    )
                parts.append(f'<td class="benefits-cell">{cells}</td>')
            parts.append("</tr>")

            parts.append("</tbody></table></div>")

        parts.append(_HTML_FOOTER)
        return "".join(parts)
