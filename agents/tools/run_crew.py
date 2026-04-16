# agents/tools/run_crew.py
"""RunCrewTool — runs a named sub-crew and waits for it to complete."""
from crewai.tools import BaseTool


class RunCrewTool(BaseTool):
    name: str = "RunCrewTool"
    description: str = (
        "Run a named crew for the current project and wait for it to complete. "
        "crew_name must be one of: discovery, value_design, architecture, delivery, business_plan"
    )
    slug: str
    orchestration_run_id: int

    def _run(self, crew_name: str) -> str:
        raise NotImplementedError("Use _arun for async execution.")

    async def _arun(self, crew_name: str) -> str:
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
                conn, project_id=project["id"], crew_name=crew_name, status="running"
            )
        try:
            result = await build_and_run_crew(self.slug, crew_name, run_id)
            async with get_connection(self.slug) as conn:
                await update_crew_run_status(conn, run_id=run_id, status="completed")
            return str(result)
        except Exception as e:
            async with get_connection(self.slug) as conn:
                await update_crew_run_status(conn, run_id=run_id, status="failed")
            return f"Error running {crew_name}: {e}"
