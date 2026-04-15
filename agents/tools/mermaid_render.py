# agents/tools/mermaid_render.py
from pathlib import Path
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_agent_output_sync


class MermaidRenderToolInput(BaseModel):
    mermaid_md: str = Field(
        description="Mermaid diagram markdown content (including the ```mermaid fence)."
    )
    filename: str = Field(
        description="Output filename without extension (e.g. 'value_chain' → value_chain.md)."
    )
    agent_name: str = Field(
        default="value_chain_mapper",
        description="Name of the agent producing this diagram (used for output tracking).",
    )


class MermaidRenderTool(BaseTool):
    name: str = "MermaidRenderTool"
    description: str = (
        "Save a Mermaid diagram to the project outputs directory. "
        "Pass the full Mermaid markdown (including the ```mermaid fence) and a filename. "
        "The diagram will be rendered in the React UI automatically."
    )
    args_schema: type[BaseModel] = MermaidRenderToolInput
    slug: str

    def _run(self, mermaid_md: str, filename: str, agent_name: str = "value_chain_mapper") -> str:
        settings = get_settings()
        outputs_dir = Path(settings.projects_dir) / self.slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        file_path = outputs_dir / f"{filename}.md"
        try:
            file_path.write_text(mermaid_md)
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="value_chain",
                file_path=str(file_path),
            )
        except (OSError, ValueError) as e:
            return f"Error: save failed — {e}"
        return f"Diagram saved to {file_path}"
