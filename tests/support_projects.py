# tests/support_projects.py
"""Test support for the approver every engagement is created with.

`POST /projects` and `create_project` both require an approver's name and address, and both
write a stakeholder row carrying `is_approver` before they answer. That is the point of the
field - a project with nobody who can approve anything is the dead end it closes - but it
means **no project in this suite is born with an empty roster any more**, and a handful of
tests are about precisely that state.

Those tests are not wrong and are not retired here. The empty-roster state is still perfectly
reachable in production: a consultant who removes the approver on the Stakeholders tab is in
it, as is one who replaces them. What changed is that the state has to be *arranged* rather
than assumed, so `remove_creation_approver` arranges it and the original assertion is kept.
The alternative - softening `== []` to `== 1` - would have turned each of those tests into an
assertion about this fixture instead of about the property it was written for.

Lives in a support module rather than in `api/database.py` for the reason CLAUDE.md gives
about `insert_interview_session`: a helper with no production caller drifts from production,
and being test-only is what a file named `support_*` says on the tin.
"""

# The approver every project-creating fixture in this suite names. Deliberately at a
# `.test` domain (RFC 6761 reserves it, so it can never resolve) and deliberately not
# anybody's real-looking address, since creation mints a live invite token against it.
APPROVER_NAME = "Approver Fixture"
APPROVER_EMAIL = "approver@fixture.test"


def project_payload(slug: str, **overrides) -> dict:
    """A minimal valid `POST /projects` body: the two fields with no default, plus the
    approver. Useful for a new test; the existing ones carry the keys inline."""
    return {
        "client_slug": slug,
        "sector": "rail",
        "approver_name": APPROVER_NAME,
        "approver_email": APPROVER_EMAIL,
        **overrides,
    }


async def remove_creation_approver(slug: str) -> int:
    """Delete the approver stakeholder creation wrote, restoring an empty roster.

    Returns the number of rows removed, so a caller can assert the premise it is arranging
    was actually there - a helper that silently removed nothing would leave the test it
    serves passing for the wrong reason, which is the shape of half the findings in
    CLAUDE.md.

    The project database only. The invite token in `system.db` is deliberately left alone:
    nothing these callers assert reads `auth_tokens`, and a test that scrubbed it would be
    quietly testing a state the product cannot produce - removing a stakeholder through the
    real door cancels the invite, but it is the *roster* these tests need empty.
    """
    from api.database import fetch_project, get_connection

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        assert project is not None, f"no project {slug} - creation did not happen"
        cur = await conn.execute(
            "DELETE FROM stakeholders WHERE project_id=? AND lower(email)=?",
            (project["id"], APPROVER_EMAIL),
        )
        await conn.commit()
        return cur.rowcount
