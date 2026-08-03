# tests/test_value_chain_recovery.py
"""Recovering the three-chain model, and correcting the party model on the way through.

The migrated model holds the right three chains and every task label; its party model is
wrong in a way recorded elsewhere. `value_chain_summary_v12.json` states it plainly:

    "property_maintainer": "ISS (FM subcontractor)",
    "fleet_maintainer":    "DXI (Fleet maintenance subcontractor)",

The migrated model then labels its fleet chain "Maintainer: ISS" while attributing
"Fleet Maintenance Delivery (ISS)" to the party partnerDXI - the label and the party
disagreeing inside one activity. The correction is against a recorded fact, so it belongs
here rather than in the agent's hands.
"""
import pytest

from api.services.value_chain_model import validate_model
from api.services.value_chain_recovery import correct_parties, registry_from_model


def _v1_like() -> dict:
    """The shape of the migrated model: placeholder party labels, circled-number prefixes,
    and one activity whose label names a different party from the one that owns it."""
    return {
        "model_version": 1,
        "parties": [
            {"id": "sp", "label": "sp", "colour": "#1a5276"},
            {"id": "partnerISS", "label": "partnerISS", "colour": "#c0392b"},
            {"id": "partnerDXI", "label": "partnerDXI", "colour": "#27ae60"},
        ],
        "segments": [
            {"id": "1", "label": "PROPERTY VALUE CHAIN - ~86 Facility Locations | "
                                 "Custodian: GS UK · Maintainer: ISS"},
            {"id": "2", "label": "FLEET VALUE CHAIN - Vehicles & Plant | "
                                 "Custodian: GS UK · Maintainer: ISS"},
            {"id": "3", "label": "SUPPORT ACTIVITIES - Scottish Power Group Services"},
        ],
        "activities": [
            {"id": "1.1", "segment_id": "1", "label": "① Strategic Planning & Standards"},
            {"id": "1.5", "segment_id": "1", "label": "⑤ Works Delivery (FM Execution — ISS)"},
            {"id": "2.5", "segment_id": "2", "label": "⑤ Fleet Maintenance Delivery (ISS)"},
            {"id": "3.1", "segment_id": "3", "label": "Technology & Digital"},
        ],
        "contributions": [
            {"activity_id": "1.1", "party_id": "sp", "column": 10, "attribution": "stated"},
            {"activity_id": "1.5", "party_id": "partnerISS", "column": 50,
             "attribution": "stated"},
            {"activity_id": "2.5", "party_id": "partnerDXI", "column": 50,
             "attribution": "stated"},
            {"activity_id": "3.1", "party_id": "sp", "column": 10, "attribution": "stated"},
        ],
        "tasks": [
            {"id": "1.1.1", "activity_id": "1.1", "party_id": "sp", "label": "Set strategy"},
            {"id": "2.5.1", "activity_id": "2.5", "party_id": "partnerDXI",
             "label": "Service vehicles"},
        ],
        "propositions": [],
        "links": [
            {"from_activity_id": "1.1", "from_party_id": "sp",
             "to_activity_id": "1.5", "to_party_id": "partnerISS"},
        ],
    }


def test_party_ids_are_remapped_everywhere_they_are_referenced():
    out = correct_parties(_v1_like())
    ids = {p["id"] for p in out["parties"]}
    assert ids == {"GSUK", "ISS", "DXI"}
    # The remap is only correct if nothing still points at the old ids. Asserting the party
    # list alone would pass while every contribution, task and link dangled.
    for array in ("contributions", "tasks", "propositions", "links"):
        for item in out.get(array, []):
            for field in ("party_id", "from_party_id", "to_party_id"):
                if field in item:
                    assert item[field] in ids, f"{array} still points at {item[field]}"


def test_every_party_gains_a_label_that_is_not_its_id():
    out = correct_parties(_v1_like())
    for party in out["parties"]:
        assert party["label"] and party["label"] != party["id"]


def test_fleet_maintenance_loses_the_iss_suffix_and_stays_with_dxi():
    out = correct_parties(_v1_like())
    activity = next(a for a in out["activities"] if a["id"] == "2.5")
    assert "ISS" not in activity["label"]
    assert activity["label"] == "Fleet Maintenance Delivery"
    assert next(
        c for c in out["contributions"] if c["activity_id"] == "2.5"
    )["party_id"] == "DXI"


def test_the_property_activity_naming_iss_keeps_iss():
    # 1.5 is property FM execution and ISS really does perform it, so the suffix is
    # stripped as noise while the attribution is untouched. A rule that stripped "(ISS)"
    # and also moved the party would be wrong here and right on 2.5.
    out = correct_parties(_v1_like())
    assert next(
        c for c in out["contributions"] if c["activity_id"] == "1.5"
    )["party_id"] == "ISS"


def test_circled_prefixes_are_stripped_without_eating_the_label():
    out = correct_parties(_v1_like())
    labels = {a["id"]: a["label"] for a in out["activities"]}
    assert labels["1.1"] == "Strategic Planning & Standards"
    # An activity that never had a prefix is untouched.
    assert labels["3.1"] == "Technology & Digital"


def test_chain_labels_become_names_with_the_detail_kept_as_description():
    out = correct_parties(_v1_like())
    by_id = {s["id"]: s for s in out["segments"]}
    assert by_id["1"]["label"] == "Property"
    assert by_id["2"]["label"] == "Fleet"
    assert by_id["3"]["label"] == "Support Services"
    # The detail is moved, not discarded - it is the only record of the estate's size.
    assert "86" in by_id["1"]["description"]


def test_the_fleet_chain_no_longer_names_iss_as_its_maintainer():
    out = correct_parties(_v1_like())
    fleet = next(s for s in out["segments"] if s["id"] == "2")
    assert "ISS" not in fleet.get("description", "")
    assert "DXI" in fleet["description"]


def test_activity_and_task_ids_are_untouched():
    before = _v1_like()
    out = correct_parties(before)
    assert [a["id"] for a in out["activities"]] == [a["id"] for a in before["activities"]]
    assert [t["id"] for t in out["tasks"]] == [t["id"] for t in before["tasks"]]


def test_the_input_is_not_mutated():
    before = _v1_like()
    correct_parties(before)
    assert before["parties"][0]["id"] == "sp"


def test_the_recovered_model_validates():
    assert validate_model(correct_parties(_v1_like())) == []


def test_the_registry_is_built_from_the_model_at_the_right_levels():
    registry = registry_from_model(correct_parties(_v1_like()))
    by_id = {e["id"]: e for e in registry["activities"]}
    assert by_id["1"]["level"] == "L1"
    assert by_id["2.5"]["level"] == "L2"
    assert by_id["2.5"]["parent_id"] == "2"
    assert by_id["2.5.1"]["level"] == "L3"
    assert by_id["2.5.1"]["parent_id"] == "2.5"
    assert all(e["active"] for e in registry["activities"])


def test_the_registry_carries_the_corrected_labels_not_the_originals():
    # Order matters. Building the registry before the corrections registers
    # "⑤ Fleet Maintenance Delivery (ISS)" as the permanent meaning of 2.5, and the
    # write-path check then refuses every future write of the corrected label.
    registry = registry_from_model(correct_parties(_v1_like()))
    entry = next(e for e in registry["activities"] if e["id"] == "2.5")
    assert entry["label"] == "Fleet Maintenance Delivery"


def test_the_registry_and_the_model_agree_with_each_other():
    from api.services.value_chain_model import validate_against_registry

    model = correct_parties(_v1_like())
    assert validate_against_registry(model, registry_from_model(model)) == []


def test_em_dashes_are_normalised_to_the_house_spaced_hyphen():
    # These strings render in the UI, so the project's dash rule binds them. They came
    # from a source document and this is the one point at which they are rewritten.
    model = _v1_like()
    model["activities"][1]["label"] = "⑤ Works Delivery — FM Execution"
    out = correct_parties(model)
    assert "—" not in out["activities"][1]["label"]
    assert all("—" not in s["description"] for s in out["segments"])


# ---------------------------------------------------------------------------
# recover() end to end. The pure transforms above are covered thoroughly; this is the part
# that touches disk and the database, and the only part that will be run against real data.
# ---------------------------------------------------------------------------

import json
import shutil
from pathlib import Path

from api.config import get_settings

SLUG = "vc-recovery-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "utilities",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean_project():
    def wipe():
        settings = get_settings()
        Path(settings.database_dir, f"{SLUG}.db").unlink(missing_ok=True)
        proj = Path(settings.projects_dir, SLUG)
        if proj.exists():
            shutil.rmtree(proj)
    wipe()
    yield
    get_settings.cache_clear()
    wipe()


async def _seed_source() -> Path:
    """Seed the migrated model the way production holds it: a file AND an output row.

    Seeding only the file is not the same situation. save_model numbers versions from the
    database, so with no row it computes version 1 and writes over value_chain_model_v1.json
    - the very file recover() read from. A test seeded that way cannot detect a recovery
    that rebuilds the registry from the source rather than from the corrected model, because
    by then the source file holds the corrected model too.
    """
    from api.services.value_chain_store import save_model

    await save_model(SLUG, _v1_like(), saved_by="migration", summary="migrated")
    return Path(get_settings().projects_dir) / SLUG / "outputs" / "value_chain_model_v1.json"


@pytest.mark.asyncio
async def test_recover_makes_the_corrected_model_current(client):
    from api.services.value_chain_recovery import recover
    from api.services.value_chain_store import load_model

    await client.post("/projects", json=PROJECT)
    await _seed_source()

    await recover(SLUG, saved_by="patrick")

    current = await load_model(SLUG)
    assert {p["id"] for p in current["parties"]} == {"GSUK", "ISS", "DXI"}
    assert next(a for a in current["activities"] if a["id"] == "2.5")["label"] == (
        "Fleet Maintenance Delivery"
    )


@pytest.mark.asyncio
async def test_recover_records_a_registry_output_that_is_current(client):
    from api.database import fetch_agent_outputs, fetch_project, get_connection
    from api.services.value_chain_recovery import recover

    await client.post("/projects", json=PROJECT)
    await _seed_source()

    await recover(SLUG, saved_by="patrick")

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        outputs = [
            o for o in await fetch_agent_outputs(conn, project_id=project["id"])
            if o["output_type"] == "value_chain_registry"
        ]
    assert len(outputs) == 1
    assert outputs[0]["is_current"]
    registry = json.loads(Path(outputs[0]["file_path"]).read_text())
    # The corrected label, not the original - the ordering guarantee, asserted through the
    # file that actually lands on disk rather than through the pure function alone.
    entry = next(e for e in registry["activities"] if e["id"] == "2.5")
    assert entry["label"] == "Fleet Maintenance Delivery"


@pytest.mark.asyncio
async def test_the_recovered_model_passes_the_write_path_check_against_its_own_registry(client):
    """The whole chain: recovery, then the check an agent's next write must survive.

    This is what the recovery is for - Alex is about to enrich this model, and every write
    he makes is compared against the registry recovery leaves behind.
    """
    from api.database import fetch_agent_outputs, fetch_project, get_connection
    from api.services.value_chain_model import validate_against_registry
    from api.services.value_chain_recovery import recover

    await client.post("/projects", json=PROJECT)
    await _seed_source()

    model = await recover(SLUG, saved_by="patrick")

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        registry_output = next(
            o for o in await fetch_agent_outputs(conn, project_id=project["id"])
            if o["output_type"] == "value_chain_registry"
        )
    registry = json.loads(Path(registry_output["file_path"]).read_text())

    assert validate_against_registry(model, registry) == []
    # And the structure it replaced is refused, which is the point: the same id means
    # different things in the two, so no ledger can hold both.
    reused = {**model, "activities": [
        {**a, "label": "Something Else"} if a["id"] == "2.5" else a
        for a in model["activities"]
    ]}
    assert validate_against_registry(reused, registry) != []


@pytest.mark.asyncio
async def test_a_missing_source_version_raises_rather_than_writing_anything(client):
    from api.database import fetch_agent_outputs, fetch_project, get_connection
    from api.services.value_chain_recovery import recover

    await client.post("/projects", json=PROJECT)

    with pytest.raises(ValueError, match="version 1"):
        await recover(SLUG, saved_by="patrick")

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        outputs = await fetch_agent_outputs(conn, project_id=project["id"])
    assert outputs == []


@pytest.mark.asyncio
async def test_an_invalid_source_leaves_no_registry_behind(client):
    """save_model raises before the registry is written, so a failed recovery is not
    half-applied. A registry written for a model that was never saved would be an ID
    ledger for a chain that does not exist, and every later write would be checked
    against it."""
    from api.database import fetch_agent_outputs, fetch_project, get_connection
    from api.services.value_chain_recovery import recover

    await client.post("/projects", json=PROJECT)
    broken = _v1_like()
    broken["contributions"][0]["column"] = 999  # splits activity 1.1 from nothing...
    broken["contributions"].append(
        {"activity_id": "1.1", "party_id": "partnerISS", "column": 10,
         "attribution": "stated"}
    )  # ...now 1.1 is split across columns 999 and 10
    outputs_dir = Path(get_settings().projects_dir) / SLUG / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "value_chain_model_v1.json").write_text(json.dumps(broken))

    with pytest.raises(ValueError, match="split across columns"):
        await recover(SLUG, saved_by="patrick")

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        outputs = [
            o for o in await fetch_agent_outputs(conn, project_id=project["id"])
            if o["output_type"] == "value_chain_registry"
        ]
    assert outputs == []
