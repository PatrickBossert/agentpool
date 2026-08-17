# api/services/user_identity.py
"""Who a login is, read through the lens of one project.

`users` holds no name. Its columns are id, username, role, hashed_pw, project_slug,
created_at, email and is_sys_admin, and an administrator staring at that list is looking at
usernames and addresses trying to work out who anybody is. The name and entity live on
`stakeholders`, reached through `project_memberships.stakeholder_id`.

`stakeholders` is per project, and that is not an inconvenience to be reconciled away - it is
the model. sp37 says a stakeholder *is* a person on an engagement: role nuance lives on the
stakeholder rather than the node, which is exactly what lets one programme serve two L1
entities while the answers differ. So a person on two engagements has two rows, and they need
not agree: "Jane Smith / Group Finance" on one, "J. Smith / Retail Bank" on the other, and
neither is wrong.

Asking "what is this account's name" therefore has no answer. Asking "what is this account's
name *on this project*" has exactly one. This module only ever answers the second question,
which is why nothing here reconciles, marks a conflict, or chooses between candidates - there
is never more than one candidate. The project is supplied by the caller and authorised before
this is reached; it is never inferred from the memberships themselves, because inferring it
is what would put a name from an engagement the caller may not see in front of them.

Two absences, and both are rendered as absence rather than guessed at:

  no membership          the account is not on this project. It is not in the list at all,
                         except for a sysadmin account shown to a sysadmin caller - see
                         `svc_list_users` for why those stay visible.
  NULL stakeholder_id    a membership `insert_project_membership` wrote - the /admin access
                         grant. It is access, not identity; there is no person record behind
                         it, and there is nothing to show.

The existence of an account is neither confirmed nor denied by any of this. Every account
annotated here is one the caller was already entitled to be shown - the project-scoped list is
a strict subset of the unscoped one - so a person block is added to rows that already exist
and never causes a row to appear.
"""
from api.database import (
    fetch_stakeholder_identities,
    get_connection,
    get_db_path,
)


async def project_identities(
    slug: str, stakeholder_ids: list[int]
) -> dict[int, dict]:
    """The name and entity of these stakeholder rows on this project, keyed by stakeholder id.

    The slug is required and is the whole scope: the caller has already established that this
    project is one they may administer, and no other project's database is opened. That is
    sp45's shape - do not fetch what you must not reveal, rather than fetch and filter - and
    it is why this function takes a slug rather than a set of memberships to work the slug
    out from.

    Missing ids are simply absent from the result. A stakeholder row deleted while a
    membership still points at it is an absence, not an error, and the caller renders it the
    same way it renders a membership that never had one.
    """
    if not stakeholder_ids:
        return {}
    # `get_connection` creates the file it is handed, so a membership naming a project whose
    # database has been removed would otherwise leave an empty database behind on every load
    # of the user list. Every other reader of a project by slug guards the same way.
    if not get_db_path(slug).exists():
        return {}
    async with get_connection(slug) as conn:
        return await fetch_stakeholder_identities(conn, stakeholder_ids=stakeholder_ids)


def person_block(identity: dict | None) -> dict | None:
    """One user row's `person` field: the name and entity, or None.

    None means "no person record on this project" and covers both absences above. It is a
    single null rather than a block of empty strings so that a client cannot render a blank
    name as though it were a recorded one.
    """
    if identity is None:
        return None
    name = (identity.get("name") or "").strip()
    entity = (identity.get("entity") or "").strip()
    if not name and not entity:
        return None
    return {"name": name or None, "entity": entity or None}
