# agents/tools/derive_registry.py
"""
DeriveRegistryTool — reads value_chain_tree.json and writes value_chain_registry.json.

Calling this after writing the tree guarantees the registry is always complete and
consistent with the tree, without requiring the LLM to regenerate the same 75+ activity
IDs from memory.
"""
import json
from pathlib import Path
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_agent_output_sync


class DeriveRegistryToolInput(BaseModel):
    agent_name: str = Field(
        default="value_chain_mapper",
        description="Name of the calling agent (used for audit trail).",
    )


class DeriveRegistryTool(BaseTool):
    name: str = "DeriveRegistryTool"
    description: str = (
        "Derive and save the flat activity ID registry from value_chain_tree.json. "
        "Call this immediately after writing value_chain_tree to create a guaranteed-complete "
        "value_chain_registry without requiring you to regenerate all activity IDs from memory. "
        "Activities in the tree are marked active=true; activities that existed in a previous "
        "registry but are absent from the new tree are preserved as active=false."
    )
    args_schema: type[BaseModel] = DeriveRegistryToolInput
    slug: str

    def _run(self, agent_name: str = "value_chain_mapper") -> str:
        settings = get_settings()
        outputs_dir = Path(settings.projects_dir) / self.slug / "outputs"
        tree_path = outputs_dir / "value_chain_tree.json"
        registry_path = outputs_dir / "value_chain_registry.json"

        if not tree_path.exists():
            return "Error: value_chain_tree.json not found — write the tree first (step 10)."

        try:
            tree = json.loads(tree_path.read_text())
        except json.JSONDecodeError as e:
            return f"Error: value_chain_tree.json is not valid JSON — {e}"

        # Load existing registry to preserve any historical inactive entries
        old_entries: dict[str, dict] = {}
        if registry_path.exists():
            try:
                old_data = json.loads(registry_path.read_text())
                for entry in old_data.get("activities", []):
                    old_entries[entry["id"]] = entry
            except Exception:
                pass  # If old registry is corrupt, start fresh

        # Flatten the tree into a list of activity entries
        new_activities: list[dict] = []
        new_ids: set[str] = set()

        def _extract(nodes: list, parent_id: str | None = None) -> None:
            for node in nodes:
                node_id = str(node.get("id", ""))
                if not node_id:
                    continue
                new_ids.add(node_id)
                entry: dict = {
                    "id": node_id,
                    "label": node.get("label", ""),
                    "level": node.get("level", ""),
                    "active": True,
                }
                if parent_id is not None:
                    entry["parent_id"] = parent_id
                new_activities.append(entry)
                _extract(node.get("children", []), node_id)

        _extract(tree)

        # Append old entries that are no longer in the tree (mark them inactive)
        for entry_id, entry in old_entries.items():
            if entry_id not in new_ids:
                inactive = dict(entry)
                inactive["active"] = False
                new_activities.append(inactive)

        # Sort numerically by ID: "1" < "1.1" < "1.1.1" < "1.2" < ...
        def _sort_key(a: dict) -> list[int]:
            try:
                return [int(p) for p in a["id"].split(".")]
            except ValueError:
                return [0]

        new_activities.sort(key=_sort_key)

        registry = {"schema_version": 2, "activities": new_activities}
        try:
            registry_path.write_text(json.dumps(registry, indent=2))
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="state",
                file_path=str(registry_path),
            )
        except (OSError, ValueError) as e:
            return f"Error: failed to write registry — {e}"

        active_count = sum(1 for a in new_activities if a.get("active", True))
        inactive_count = len(new_activities) - active_count
        msg = f"Registry derived from tree: {active_count} active activities"
        if inactive_count:
            msg += f", {inactive_count} inactive (preserved from previous runs)"
        return msg + f" — saved to {registry_path}"
