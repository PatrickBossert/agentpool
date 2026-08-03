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
from agents.tools._db import insert_agent_output_sync, latest_output_path

_REGISTRY_STEM = "value_chain_registry"


def _latest_registry(outputs_dir: Path) -> Path | None:
    """Return the most recent registry file, or None if there is no previous one.

    Looking only at the base filename made every run behave as if it were the
    first — activities dropped from the tree were silently forgotten instead of
    being preserved as active=false. See latest_output_path for why.
    """
    return latest_output_path(outputs_dir / f"{_REGISTRY_STEM}.json")


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

        # Load existing registry to preserve any historical inactive entries.
        # This must look at the latest *versioned* file, not the base name —
        # see _latest_registry.
        old_entries: dict[str, dict] = {}
        previous = _latest_registry(outputs_dir)
        if previous is not None:
            try:
                old_data = json.loads(previous.read_text())
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

        # This tool writes through insert_agent_output_sync rather than SQLiteStateTool, so
        # the write-path validator never sees it - which made this the one door through
        # which the ID ledger could still be rewritten. An id present in both the old
        # registry and the new tree silently took the tree's label, which is how a single
        # id came to mean one activity on one run and a different one on the next.
        #
        # Same rule as the tool's own check, one implementation: the ledger may grow and
        # may retire, but may not redefine or forget.
        from api.services.value_chain_model import validate_registry_succession

        problems = validate_registry_succession(
            {"activities": list(old_entries.values())}, registry
        )
        if problems:
            return (
                "Error: the registry was not written - the tree redefines IDs the registry "
                "has already assigned. Give the new thing an unused number and derive "
                "again: " + "; ".join(problems)
            )

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
        # Report where the file actually landed — insert_agent_output_sync has
        # renamed it to a versioned path by this point.
        saved = _latest_registry(outputs_dir) or registry_path
        return msg + f" — saved to {saved}"
