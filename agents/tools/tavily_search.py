# agents/tools/tavily_search.py
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings


class TavilySearchToolInput(BaseModel):
    query: str = Field(description="The search query.")
    max_results: int = Field(default=5, description="Maximum number of results to return.")


class TavilySearchTool(BaseTool):
    name: str = "TavilySearchTool"
    description: str = (
        "Search the web for current information about a topic. "
        "Use for market research, sector benchmarks, and technology trends."
    )
    args_schema: type[BaseModel] = TavilySearchToolInput

    def _run(self, query: str, max_results: int = 5) -> str:
        settings = get_settings()
        if not settings.tavily_api_key:
            return "Error: TAVILY_API_KEY not configured."
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=settings.tavily_api_key)
            response = client.search(query=query, max_results=max_results)
            results = response.get("results", [])
            if not results:
                return "No results found."
            return "\n\n".join(
                f"**{r.get('title', 'Untitled')}**\n{r.get('url', '')}\n{r.get('content', '')}"
                for r in results
            )
        except Exception as e:
            return f"Search error: {e}"
