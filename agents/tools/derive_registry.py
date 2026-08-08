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
from agents.tools._db import current_output_path, insert_agent_output_sync

_REGISTRY_STEM = "value_chain_registry"


def _latest_registry(slug: str) -> Path | None:
    """The registry the ledger marks current, or None on a first run.

    Looking only at the base filename made every run behave as if it were the first -
    activities dropped from the tree were silently forgotten instead of being preserved as
    active=false. Resolving by the highest number on disk fixed that and introduced a
    second fault: a stale higher-numbered file shadows the current one. The ledger knows
    which version is current, including after a revert, so ask it.
    """
    return current_output_path(slug, _REGISTRY_STEM)


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
        # SQLiteStateTool renames its write to a _vN suffix before this tool ever runs (it is
        # called "immediately after" the tree write, but as a separate tool call), so the bare
        # path is already gone by the time we get here. Every existing test wrote the tree
        # straight to the bare path and so never exercised this - resolving through the ledger
        # is the actual fix, not just a guard-satisfying rename.
        tree_path = current_output_path(self.slug, "value_chain_tree")
        registry_path = outputs_dir / f"{_REGISTRY_STEM}.json"

        if tree_path is None:
            return "Error: value_chain_tree.json not found — write the tree first (step 10)."

        try:
            tree = json.loads(tree_path.read_text())
        except json.JSONDecodeError as e:
            return f"Error: value_chain_tree.json is not valid JSON — {e}"

        # Load existing registry to preserve any historical inactive entries.
        # This must look at the latest *versioned* file, not the base name —
        # see _latest_registry.
        old_entries: dict[str, dict] = {}
        previous = _latest_registry(self.slug)
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
                # An id that is already registered keeps the label the ledger holds. Alex
                # regenerates every label on every run, so taking the tree's wording here
                # would let a regeneration quietly rewrite the ledger - which is how
                # 'Financial Control (£350M)' became 'Financial Control (350M)'. A label is
                # changed deliberately, through the validation loop, not as a side effect of
                # rebuilding. A genuinely new id takes its label from the tree.
                registered = old_entries.get(node_id)
                label = (
                    registered.get("label")
                    if registered and registered.get("label")
                    else node.get("label", "")
                )
                entry: dict = {
                    "id": node_id,
                    "label": label,
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

        # Sort by the ID's numeric parts, sharing value_chain_model's implementation so the
        # registry, the collision messages and the migration never disagree about what
        # "1.10" means relative to "1.9". The local version raised ValueError on any
        # non-numeric part and fell back to [0], which put every role node (0.A, 0.S, 1.C,
        # 1.F, 2.F) on the same key, ahead of the root and in arbitrary order relative to
        # each other. id_order maps a non-numeric part to 10**9 instead, so a role node
        # trails its numbered siblings rather than interleaving with them.
        from api.services.value_chain_model import id_order

        new_activities.sort(key=lambda a: id_order(a["id"]))

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
                # Not "state". This tool and SQLiteStateTool both write the
                # value_chain_registry_vN family, and recording them under different types
                # made one filename family answer to two ledgers - which is why 'state'
                # carried two is_current rows, why it could never be pruned, and why
                # deleting rows of one type demoted files belonging to the other.
                output_type="value_chain_registry",
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
        saved = _latest_registry(self.slug) or registry_path
        return msg + f" — saved to {saved}"
