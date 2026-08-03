# api/services/value_chain_recovery.py
"""Recovering the three-chain value chain, and correcting its party model.

The migrated model holds the right three chains and every task label. Its party model is
wrong, and wrong in a way that is recorded elsewhere - `value_chain_summary_v12.json` says:

    "property_maintainer": "ISS (FM subcontractor)",
    "fleet_maintainer":    "DXI (Fleet maintenance subcontractor)",

while the model labels its fleet chain "Maintainer: ISS" and attributes
"Fleet Maintenance Delivery (ISS)" to partnerDXI - the label and the party disagreeing
inside one activity. Correcting against a recorded fact is not a judgement, so it happens
here rather than being handed back to the agent, which has now got it wrong twice.

`correct_parties` and `registry_from_model` are pure, matching value_chain_model.py's own
rule, so the transform can be tested without a project. Only `recover` touches disk.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from api.config import get_settings
from api.database import (
    fetch_agent_outputs,
    fetch_project,
    get_connection,
    insert_agent_output,
    set_current_output,
)
from api.services.value_chain_store import AGENT_NAME, save_model

# The migrated model's party ids are placeholders whose labels repeat the id. These are the
# real parties, from value_chain_summary_v12.json.
_PARTIES = {
    "sp": {
        "id": "GSUK",
        "label": "Scottish Power Group Services UK (GS UK)",
        "description": "Custodian of all Scottish Power non-power assets - property and fleet.",
    },
    "partnerISS": {
        "id": "ISS",
        "label": "ISS (FM subcontractor)",
        "description": "Facilities management subcontractor delivering property maintenance.",
    },
    "partnerDXI": {
        "id": "DXI",
        "label": "DXI (fleet maintenance subcontractor)",
        "description": "Fleet maintenance subcontractor. DXI maintains the fleet, not ISS.",
    },
}

# The chains, named. The migrated labels carry real detail - the size of the estate, who
# maintains what - so the detail moves to the description rather than being discarded.
_CHAIN_NAMES = {"1": "Property", "2": "Fleet", "3": "Support Services"}

# Circled numerals used as ordering prefixes on activity labels. An explicit set rather
# than a "leading non-alphanumeric" rule, which would eat a legitimate bracket or quote.
_PREFIXES = "①②③④⑤⑥⑦⑧⑨⑩ "

# A trailing parenthesis naming a party is noise - the party is in the contribution. Only
# stripped when it actually names one, so "Asset Register (Tririga)" survives.
_PARTY_TOKENS = ("ISS", "DXI", "Fleet Alliance", "GS UK")


def _dashes(text: str) -> str:
    """Em dashes to the project's spaced hyphen. These strings render in the UI, so the
    house rule applies to them as much as to authored copy - they arrived from a source
    document and this is the one point at which they are rewritten."""
    return text.replace(" — ", " - ").replace("—", " - ")


def _clean_label(label: str) -> str:
    cleaned = _dashes(label).lstrip(_PREFIXES).strip()
    if cleaned.endswith(")") and "(" in cleaned:
        head, _, tail = cleaned.rpartition("(")
        if any(token in tail for token in _PARTY_TOKENS):
            cleaned = head.strip()
    return cleaned


def correct_parties(model: dict) -> dict:
    """The model with real party names, corrected chain labels and cleaned activity labels.

    Party **ids** change, so every reference to one is remapped in the same pass -
    contributions, tasks, propositions and links alike. Activity and task ids are not
    touched: they are the stable IDs this whole exercise exists to protect.
    """
    out = deepcopy(model)
    remap = {old: new["id"] for old, new in _PARTIES.items()}

    out["parties"] = [
        {
            **{k: v for k, v in party.items() if k not in ("id", "label", "description")},
            **_PARTIES.get(party["id"], party),
        }
        for party in model.get("parties", [])
    ]

    for array in ("contributions", "tasks", "propositions", "links"):
        for item in out.get(array, []):
            for field in ("party_id", "from_party_id", "to_party_id"):
                if field in item and item[field] in remap:
                    item[field] = remap[item[field]]

    for segment in out.get("segments", []):
        detail = segment.get("label", "")
        if segment["id"] == "2":
            # The one factual correction: ISS does not maintain the fleet.
            detail = detail.replace("ISS", "DXI")
        segment["description"] = _dashes(segment.get("description") or detail)
        segment["label"] = _CHAIN_NAMES.get(segment["id"], segment.get("label", ""))

    for activity in out.get("activities", []):
        activity["label"] = _clean_label(activity.get("label", ""))

    return out


def registry_from_model(model: dict) -> dict:
    """The ID ledger this model implies: L1 segments, L2 activities, L3 tasks.

    Built from the model **after** its labels are corrected. Built before, it would register
    "⑤ Fleet Maintenance Delivery (ISS)" as the permanent meaning of 2.5, and the write-path
    check would then refuse every future write of the corrected label.
    """
    entries: list[dict] = []
    for segment in model.get("segments", []):
        entries.append(
            {"id": segment["id"], "label": segment.get("label", ""), "level": "L1",
             "active": True}
        )
    for activity in model.get("activities", []):
        entries.append(
            {"id": activity["id"], "label": activity.get("label", ""), "level": "L2",
             "active": True, "parent_id": activity.get("segment_id")}
        )
    for task in model.get("tasks", []):
        entries.append(
            {"id": task["id"],
             "label": task.get("label") or task.get("description") or task["id"],
             "level": "L3", "active": True, "parent_id": task.get("activity_id")}
        )
    return {"schema_version": 2, "activities": entries}


async def recover(slug: str, *, saved_by: str, source_version: int = 1) -> dict:
    """Make the corrected three-chain model current and rebuild the registry from it.

    The registry written here replaces whatever is current rather than merging with it. The
    same id string denotes different activities in the two structures, so no ledger can hold
    both meanings - choosing one voids the other.
    """
    outputs_dir = Path(get_settings().projects_dir) / slug / "outputs"
    source = outputs_dir / f"value_chain_model_v{source_version}.json"
    if not source.exists():
        raise ValueError(f"no value chain model version {source_version} for {slug!r}")

    model = correct_parties(json.loads(source.read_text()))
    # save_model validates before writing, so an invalid recovery leaves nothing behind.
    await save_model(slug, model, saved_by=saved_by,
                     summary=f"recovered the three-chain model from version {source_version}")

    registry = registry_from_model(model)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            raise ValueError(f"project {slug!r} not found")
        existing = [
            o for o in await fetch_agent_outputs(conn, project_id=project["id"])
            if o["output_type"] == "value_chain_registry"
        ]
        version = max((o["version"] for o in existing), default=0) + 1
        path = outputs_dir / f"value_chain_registry_v{version}.json"
        path.write_text(json.dumps(registry, indent=2))
        output_id = await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name=AGENT_NAME,
            output_type="value_chain_registry",
            file_path=str(path),
            version=version,
        )
        await set_current_output(
            conn, project_id=project["id"],
            output_type="value_chain_registry", output_id=output_id,
        )

    return model
