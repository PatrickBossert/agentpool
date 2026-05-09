# api/services/stakeholder_service.py
"""Stakeholder registry — service layer."""
import csv
import io
from api.database import (
    get_connection,
    get_db_path,
    fetch_project,
    insert_stakeholder,
    fetch_stakeholders,
    fetch_stakeholder,
    update_stakeholder,
    delete_stakeholder,
)

VALID_ROLES = {"recipient", "governing", "actor"}
VALID_DISPOSITIONS = {"champion", "supporter", "neutral", "skeptic", "blocker"}


async def list_stakeholders(slug: str) -> list[dict] | None:
    """None = project not found."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_stakeholders(conn, project_id=project["id"])


async def create_stakeholder(slug: str, data: dict) -> dict | None:
    """None = project not found. Returns created stakeholder with id."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        sid = await insert_stakeholder(conn, project_id=project["id"], **data)
        return await fetch_stakeholder(conn, stakeholder_id=sid, project_id=project["id"])


async def update_stakeholder_svc(
    slug: str, stakeholder_id: int, data: dict
) -> dict | None:
    """None = not found (project or stakeholder)."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        ok = await update_stakeholder(conn, stakeholder_id=stakeholder_id, **data)
        if not ok:
            return None
        return await fetch_stakeholder(
            conn, stakeholder_id=stakeholder_id, project_id=project["id"]
        )


async def delete_stakeholder_svc(slug: str, stakeholder_id: int) -> bool | None:
    """None = project not found. False = stakeholder not found. True = deleted."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        # Verify ownership before delete
        row = await fetch_stakeholder(
            conn, stakeholder_id=stakeholder_id, project_id=project["id"]
        )
        if not row:
            return False
        return await delete_stakeholder(conn, stakeholder_id=stakeholder_id)


async def import_csv(slug: str, content: str) -> dict | None:
    """Parse CSV content and upsert rows by email.

    Returns {"created": N, "updated": M, "errors": [{"row": N, "reason": "..."}]}
    None = project not found.

    Multi-value columns (stakeholder_groups, value_streams): semicolon-separated.
    Upsert key: email. Blank email → always insert (no upsert).
    Invalid disposition → skip row with error.
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None

        created = 0
        updated = 0
        errors = []

        reader = csv.DictReader(io.StringIO(content))
        # Normalise header keys to lowercase stripped
        rows = []
        for raw_row in reader:
            rows.append({k.strip().lower(): (v or "").strip() for k, v in raw_row.items()})

        for i, row in enumerate(rows, start=1):
            # Validate disposition if provided
            disposition = row.get("disposition", "neutral") or "neutral"
            if disposition and disposition not in VALID_DISPOSITIONS:
                errors.append({"row": i, "reason": f"Invalid disposition '{disposition}'"})
                continue

            project_role = row.get("project_role", "recipient") or "recipient"
            if project_role and project_role not in VALID_ROLES:
                errors.append({"row": i, "reason": f"Invalid project_role '{project_role}'"})
                continue

            def split_semi(val: str) -> list[str]:
                return [v.strip() for v in val.split(";") if v.strip()] if val else []

            data = {
                "name": row.get("name", ""),
                "job_title": row.get("job_title", ""),
                "organisation": row.get("organisation", ""),
                "email": row.get("email", ""),
                "slack_handle": row.get("slack_handle", ""),
                "stakeholder_groups": split_semi(row.get("stakeholder_groups", "")),
                "project_role": project_role,
                "value_streams": split_semi(row.get("value_streams", "")),
                "value_chain_stage": row.get("value_chain_stage", ""),
                "activity": row.get("activity", ""),
                "disposition": disposition,
                "location": row.get("location", ""),
                "country_code": row.get("country_code", ""),
                "timezone": row.get("timezone", ""),
                "preferred_language": row.get("preferred_language", ""),
                "currency": row.get("currency", ""),
            }

            email = data["email"]
            # Upsert by email if present
            existing = None
            if email:
                async with conn.execute(
                    "SELECT id FROM stakeholders WHERE email=? AND project_id=?",
                    (email, project["id"]),
                ) as cur:
                    existing = await cur.fetchone()

            if existing:
                await update_stakeholder(conn, stakeholder_id=existing["id"], **data)
                updated += 1
            else:
                await insert_stakeholder(conn, project_id=project["id"], **data)
                created += 1

    return {"created": created, "updated": updated, "errors": errors}
