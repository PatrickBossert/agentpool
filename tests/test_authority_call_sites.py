# tests/test_authority_call_sites.py
"""Every gate asks the same question, in the same way.

A rule enforced at one door and not another is this project's documented recurring failure -
CLAUDE.md records the two review doors, where wiring only one turned the other's flows into
no-ops. These assert on the roles each endpoint demands, because the roles are the rule and
the status code is only its shadow.
"""
from unittest.mock import AsyncMock, patch
import pytest

from tests.test_approve_gate import seeded_ledger_script  # noqa: F401
from tests.test_interview_script_edit import seeded_scripts  # noqa: F401


@pytest.mark.asyncio
async def test_reviewing_demands_a_review_role(client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    with patch("api.routers.script_reviews.caller_roles",
               new=AsyncMock(return_value=set())) as roles:
        r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                              json={"decision": "reviewed"})
    assert r.status_code == 403, r.text
    roles.assert_awaited()


@pytest.mark.asyncio
async def test_approving_demands_the_approver_role_specifically(client, seeded_ledger_script):
    """A reviewer may review and may not approve - the two are different rights, and a
    caller holding only the first must be refused the second."""
    slug, script_id = seeded_ledger_script
    with patch("api.routers.script_reviews.caller_roles",
               new=AsyncMock(return_value={"reviewer"})):
        r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                              json={"decision": "approved"})
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_editing_a_script_demands_a_review_role(client, seeded_scripts):
    slug = seeded_scripts
    before = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    with patch("api.routers.projects.caller_roles", new=AsyncMock(return_value=set())):
        r = await client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                               json={"script": {**before["SC-001"], "node_label": "Nope"}})
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_permissions_reports_the_same_roles_the_gates_read(client, seeded_ledger_script):
    slug, _ = seeded_ledger_script
    with patch("api.routers.permissions.caller_roles",
               new=AsyncMock(return_value={"reviewer"})):
        r = await client.get(f"/projects/{slug}/my-permissions")
    # can_grant_roles asks caller_may_grant_project_roles rather than this patched set, and
    # can_issue_invite_links asks the platform tier off the token. The client fixture's token
    # is the platform administrator, so both are True here - see test_my_permissions.py.
    # writable_knowledge_tiers is unpatched for the same reason and holds no organisation
    # tier, because this fixture's project is seeded with no project_registry row and so
    # belongs to no organisation - tests/test_knowledge_tier_authority.py drives the rule.
    assert r.json() == {
        "can_review": True, "can_approve": False, "can_grant_roles": True,
        "can_issue_invite_links": True,
        "can_change_platform_tier_settings": True,
        "writable_knowledge_tiers": ["sector", "project"],
    }
