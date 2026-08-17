# agents/tools/run_crew.py
"""RunCrewTool — runs a named sub-crew and waits for it to complete."""
from crewai.tools import BaseTool


def _crew_names() -> tuple[str, ...]:
    """The crews PAM may dispatch, read from the graph rather than typed here a second time.

    The description used to name `discovery` and `architecture`, neither of which any crew
    provides, and omitted `assessment_design`, `stakeholder_management`, `requirements` and
    `capabilities`, all of which do - see `agents/graph.py` for the incident this replaces.

    Imported lazily, inside this function rather than at module level: `agents/graph.py`
    imports `api.services.run_service` at module level and assembles at import time, and
    `get_tools_for_agent` imports this module *inside* a function precisely to avoid
    re-entering a partially initialised module. A module-level import here would risk the
    same trap in reverse.
    """
    from agents.graph import build_graph
    return tuple(sorted(build_graph().crews))


class RunCrewTool(BaseTool):
    name: str = "RunCrewTool"
    description: str = (
        "Run a named crew for the current project and wait for it to complete. "
        "crew_name must be one of: " + ", ".join(_crew_names())
    )
    slug: str
    orchestration_run_id: int

    def _run(self, crew_name: str) -> str:
        return "Error: RunCrewTool requires async execution (_arun only)."

    async def _arun(self, crew_name: str) -> str:
        run_id: int | None = None
        try:
            from api.database import (
                get_connection,
                fetch_project,
                insert_crew_run,
                update_crew_run_status,
            )
            from api.services.run_service import build_and_run_crew

            async with get_connection(self.slug) as conn:
                project = await fetch_project(conn, slug=self.slug)
                run_id = await insert_crew_run(
                    conn,
                    project_id=project["id"],
                    crew_name=crew_name,
                    status="running",
                    orchestration_run_id=self.orchestration_run_id,
                )
            result = await build_and_run_crew(self.slug, crew_name, run_id)
            async with get_connection(self.slug) as conn:
                await update_crew_run_status(conn, run_id=run_id, status="completed")
            return str(result)
        except Exception as e:
            if run_id is not None:
                try:
                    from api.database import get_connection, update_crew_run_status
                    async with get_connection(self.slug) as conn:
                        await update_crew_run_status(conn, run_id=run_id, status="failed")
                except Exception:
                    pass
            return f"Error running {crew_name}: {e}"
