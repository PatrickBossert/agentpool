"""The root and the role nodes must survive derivation.

This is the regression the whole L0 design exists for: a node reaches the registry only if
it is in the tree, and the only registry that ever held an L0 was the one Maya hand-wrote,
bypassing derivation entirely. Registries v2 to v5, written by value_chain_mapper, hold
none.

Also covers ordering. The tool's own sort did [int(p) for p in id.split(".")] with a
fallback of [0] on ValueError, so every role id - 0.A, 0.S, 1.C, 1.F, 2.F - collapsed to
the same key and sorted ahead of the root.
"""
import json
import pytest
import pytest_asyncio
from pathlib import Path
from api.config import get_settings
from api.database import get_connection

TREE = [{"id": "0", "label": "GS-UK", "level": "L0", "children": [
    {"id": "0.A", "label": "Audit", "level": "L0"},
    {"id": "0.S", "label": "Corporate Services frontline", "level": "L0"},
    {"id": "1", "label": "Property", "level": "L1", "children": [
        {"id": "1.C", "label": "Property customer", "level": "L1"},
        {"id": "1.F", "label": "Property frontline", "level": "L1"},
        {"id": "1.1", "label": "Strategic Planning", "level": "L2", "children": [
            {"id": "1.1.1", "label": "Asset Hierarchy", "level": "L3"},
        ]},
        {"id": "1.2", "label": "Portfolio Optimisation", "level": "L2"},
    ]},
    {"id": "2", "label": "Fleet", "level": "L1", "children": [
        {"id": "2.F", "label": "Fleet frontline", "level": "L1"},
    ]},
]}]


@pytest_asyncio.fixture
async def registry_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "registry-l0-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "value_chain_tree.json").write_text(json.dumps(TREE))
    yield slug, outputs
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_root_and_role_nodes_reach_the_registry(registry_project):
    slug, outputs = registry_project
    from agents.tools.derive_registry import DeriveRegistryTool, _latest_registry

    result = DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")
    assert not result.startswith("Error"), result

    by_id = {a["id"]: a for a in
             json.loads(_latest_registry(slug).read_text())["activities"]}

    assert by_id["0"]["level"] == "L0"
    assert "parent_id" not in by_id["0"], "the root has no parent"
    for role_id, parent in [("0.A", "0"), ("0.S", "0"), ("1.C", "1"),
                            ("1.F", "1"), ("2.F", "2")]:
        assert role_id in by_id, f"{role_id} missing from the registry"
        assert by_id[role_id]["parent_id"] == parent
    assert by_id["1"]["parent_id"] == "0", "every L1 descends from the L0"
    assert by_id["1.1.1"]["parent_id"] == "1.1"


@pytest.mark.asyncio
async def test_role_ids_sort_after_their_numbered_siblings(registry_project):
    """id_order maps a non-numeric part to 10**9, so a role node trails its parent's
    numbered children rather than jumping ahead of them."""
    slug, outputs = registry_project
    from agents.tools.derive_registry import DeriveRegistryTool, _latest_registry

    DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")
    ids = [a["id"] for a in json.loads(_latest_registry(slug).read_text())["activities"]]

    assert ids[0] == "0", f"the root must sort first, got {ids[:4]}"
    assert ids.index("0.A") < ids.index("1"), "0.A belongs to the root's block"
    assert ids.index("1") < ids.index("1.1") < ids.index("1.1.1") < ids.index("1.2")
    assert ids.index("1.2") < ids.index("1.C") < ids.index("1.F"), \
        "role nodes trail the numbered siblings, not interleave with them"
    assert ids.index("1.F") < ids.index("2") < ids.index("2.F")


@pytest.mark.asyncio
async def test_the_tool_does_not_synthesise_a_missing_root(registry_project):
    """The design is explicit that DeriveRegistryTool must NOT invent a root it cannot also
    put in the tree. value_chain_tree is Alex's key, so the repair write would be refused by
    the ownership boundary - synthesising here would leave the registry holding an anchor
    the tree and the value chain UI cannot display."""
    slug, outputs = registry_project
    from agents.tools.derive_registry import DeriveRegistryTool, _latest_registry

    rootless = TREE[0]["children"][2:]          # the bare L1 list, no root
    (outputs / "value_chain_tree.json").write_text(json.dumps(rootless))
    DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")

    ids = {a["id"] for a in json.loads(_latest_registry(slug).read_text())["activities"]}
    assert "0" not in ids, "the registry must not invent a root the tree does not have"
    assert "1" in ids and "2" in ids


@pytest.mark.asyncio
async def test_a_role_node_dropped_from_the_tree_is_retired_not_forgotten(registry_project):
    """Same succession rule as any other id: the ledger may retire, never forget."""
    slug, outputs = registry_project
    from agents.tools.derive_registry import DeriveRegistryTool, _latest_registry

    DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")

    import copy
    trimmed = copy.deepcopy(TREE)
    prop = trimmed[0]["children"][2]
    prop["children"] = [c for c in prop["children"] if c["id"] != "1.F"]
    (outputs / "value_chain_tree.json").write_text(json.dumps(trimmed))
    DeriveRegistryTool(slug=slug)._run(agent_name="value_chain_mapper")

    by_id = {a["id"]: a for a in
             json.loads(_latest_registry(slug).read_text())["activities"]}
    assert "1.F" in by_id, "a dropped role node must be preserved, not deleted"
    assert by_id["1.F"]["active"] is False
