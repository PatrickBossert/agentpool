"""An id keeps its label and its description unless a human accepts a change of meaning.

Alex's brief says ids are permanent "even if labels are refined", but
validate_registry_succession refused any label change at all - so on 6 August run 25
rewrote five labels, DeriveRegistryTool refused to derive, and the registry stuck at v5
(4 August) while the tree moved to v12. The run still reported completed.

Four of those five rewrites were typographic (× to x, en dash to hyphen, em dash to hyphen,
an arrow to the word "to"). The fifth dropped the pound sign from "Capital & Revenue
Financial Control (£350M)". A rule that refuses all five teaches people to route around it;
a rule that notices only the fifth is one they will read.
"""
import json
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection
from api.services.text_stability import is_substantive_change, normalise_typography
from api.services.value_chain_model import validate_registry_succession


# ── the normaliser ────────────────────────────────────────────────────────────────

def test_typographic_variants_are_not_substantive():
    pairs = [
        ("Rm = Pf × Cf", "Rm = Pf x Cf"),
        ("Phases 0–7", "Phases 0-7"),
        ("Service — Battery Health", "Service - Battery Health"),
        ("Reactive → Data-Led", "Reactive to Data-Led"),
        ("Works  Programming", "Works Programming"),
        ("Asset Register", "asset register"),
        ("O’Brien Review", "O'Brien Review"),
        # From run 28, which produced 59 label changes and not one redefinition.
        ("Strategic Planning & Standards", "Strategic Planning and Standards"),
        ("Compliance (Asbestos / Statutory)", "Compliance (Asbestos and Statutory)"),
        ("Modelling (Bathtub Curve / 20-yr TCO)", "Modelling (Bathtub Curve 20-yr TCO)"),
        ("Risk: Rm = Pf × Cf", "Risk Rm = Pf x Cf"),
        ("Defect Capture & FRACAS (Mobile / Tririga)",
         "Defect Capture and FRACAS (Mobile Tririga)"),
        ("Capital & Revenue Financial Control (£350M)",
         "Capital and Revenue Financial Control (GBP350M)"),
    ]
    for old, new in pairs:
        assert not is_substantive_change(old, new), f"{old!r} -> {new!r}"


def test_dropping_a_currency_symbol_is_substantive():
    assert is_substantive_change(
        "Capital & Revenue Financial Control (£350M)",
        "Capital & Revenue Financial Control (350M)")


def test_a_different_activity_is_substantive():
    assert is_substantive_change("Works Delivery", "Asset Register & Data")


def test_a_changed_number_is_substantive():
    assert is_substantive_change("Phases 0-7", "Phases 0-9")


def test_a_currency_expands_rather_than_vanishing():
    """Dropping the pound sign loses information; writing GBP does not. Only the first is
    a finding, so the symbol has to survive normalisation as a token rather than as a
    character."""
    assert normalise_typography("£350M") == "gbp 350 m"
    assert is_substantive_change("(£350M)", "(350M)"), "a dropped currency is real"
    assert not is_substantive_change("(£350M)", "(GBP350M)"), "GBP350M says the same thing"


def test_words_and_numbers_still_decide():
    assert is_substantive_change("Works Delivery", "Asset Register and Data")
    assert is_substantive_change("Phases 0-7", "Phases 0-9")
    assert is_substantive_change("10-yr Rolling Plan", "20-yr Rolling Plan")


# ── the succession rule ───────────────────────────────────────────────────────────

def _reg(entries):
    return {"activities": entries}


def test_a_refined_label_is_no_longer_refused():
    current = _reg([{"id": "1.3.2", "label": "Phases 0–7", "level": "L3", "active": True}])
    proposed = _reg([{"id": "1.3.2", "label": "Phases 0-7", "level": "L3", "active": True}])
    assert validate_registry_succession(current, proposed) == []


def test_a_substantively_different_label_is_also_no_longer_refused():
    """It becomes a warning for a human, not a refusal - the tree validator raises it."""
    current = _reg([{"id": "1.3", "label": "Works Programming", "level": "L2",
                     "active": True}])
    proposed = _reg([{"id": "1.3", "label": "Asset Register", "level": "L2",
                      "active": True}])
    assert validate_registry_succession(current, proposed) == []


def test_a_level_change_is_still_refused():
    current = _reg([{"id": "1.3", "label": "Works", "level": "L2", "active": True}])
    proposed = _reg([{"id": "1.3", "label": "Works", "level": "L3", "active": True}])
    problems = validate_registry_succession(current, proposed)
    assert len(problems) == 1 and "L2" in problems[0] and "L3" in problems[0]


def test_a_dropped_id_is_still_refused():
    current = _reg([{"id": "1.3", "label": "Works", "level": "L2", "active": True}])
    problems = validate_registry_succession(current, _reg([]))
    assert len(problems) == 1 and "1.3" in problems[0]


# ── DeriveRegistryTool keeps the label it already registered ──────────────────────

TREE = [{"id": "0", "label": "GS-UK", "level": "L0", "children": [
    {"id": "1", "label": "Property", "level": "L1", "children": [
        {"id": "1.1", "label": "Financial Control (350M)", "level": "L2"},
        {"id": "1.2", "label": "A Brand New Stage", "level": "L2"},
    ]},
]}]


@pytest_asyncio.fixture
async def derive_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "derive-label-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "value_chain_tree.json").write_text(json.dumps(TREE))
    (outputs / "value_chain_registry_v1.json").write_text(json.dumps({
        "schema_version": 2,
        "activities": [
            {"id": "0", "label": "GS-UK", "level": "L0", "active": True},
            {"id": "1", "label": "Property", "level": "L1", "active": True,
             "parent_id": "0"},
            {"id": "1.1", "label": "Financial Control (£350M)", "level": "L2",
             "active": True, "parent_id": "1"},
        ],
    }))
    yield slug, outputs
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_derivation_keeps_the_registered_label_and_adds_new_ones(derive_project):
    """Stable by construction rather than by refusal: a regenerated label cannot quietly
    rewrite the ledger, and a genuinely new id takes the label the tree gives it."""
    slug, outputs = derive_project
    from agents.tools.derive_registry import DeriveRegistryTool, _latest_registry

    result = DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")
    assert not result.startswith("Error"), result

    by_id = {a["id"]: a for a in
             json.loads(_latest_registry(slug).read_text())["activities"]}
    assert by_id["1.1"]["label"] == "Financial Control (£350M)", \
        "an existing id keeps the label the registry already holds"
    assert by_id["1.2"]["label"] == "A Brand New Stage", \
        "a new id takes its label from the tree"


@pytest.mark.asyncio
async def test_derivation_now_succeeds_where_it_used_to_refuse(derive_project):
    """This is the live failure: registry stuck at v5 while the tree moved to v12.

    Asserted on content rather than on a new filename. insert_agent_output_sync derives the
    next version from the DATABASE, and a fixture that writes a registry file without a row
    leaves MAX(version) null - so the write legitimately lands back on _v1. The filename is
    not the evidence; the derived content is.
    """
    slug, outputs = derive_project
    from agents.tools.derive_registry import DeriveRegistryTool, _latest_registry

    result = DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")
    assert not result.startswith("Error"), result

    ids = {a["id"] for a in json.loads(_latest_registry(slug).read_text())["activities"]}
    assert "1.2" in ids, "the new stage never reached the registry - derivation was refused"


def test_or_is_not_dropped_because_it_changes_the_claim():
    """'and' is a connector three different notations carry silently; 'or' is content."""
    assert is_substantive_change("Repair or Replace", "Repair and Replace")
