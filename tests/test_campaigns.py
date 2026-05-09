# tests/test_campaigns.py
"""Tests for campaign management, interview tracking, and reminder email endpoints."""
import csv
import io
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from api.config import get_settings
from api.database import get_connection, fetch_project, insert_stakeholder

SLUG = "campaigns-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}

STAKEHOLDER_BASE = {
    "name": "Alice",
    "email": "alice@corp.com",
    "country_code": "GB",
    "value_streams": ["Digital Transformation"],
}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _setup_project_and_stakeholder(client) -> tuple[int, int]:
    """Create project + stakeholder in Digital Transformation value stream.
    Returns (project_id, stakeholder_id).
    """
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(
            conn,
            project_id=project["id"],
            **STAKEHOLDER_BASE,
        )
    return project["id"], sid


@pytest.mark.asyncio
async def test_migration_creates_campaign_tables(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        for table in ("campaigns", "interview_responses", "reminder_emails"):
            async with conn.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
            ) as cur:
                row = await cur.fetchone()
            assert row is not None, f"{table} table should exist after migration"

        # interview_status column on stakeholders
        async with conn.execute("PRAGMA table_info(stakeholders)") as cur:
            cols = {row["name"] async for row in cur}
        assert "interview_status" in cols
        assert "interview_invited_at" in cols
        assert "interview_completed_at" in cols


@pytest.mark.asyncio
async def test_create_and_list_campaigns(client):
    await client.post("/projects", json=PROJECT)
    body = {
        "value_stream_name": "Digital Transformation",
        "listenlabs_campaign_id": "camp_abc",
        "campaign_name": "DT Stakeholder Survey",
        "interview_start": "2026-05-01",
        "interview_close": "2026-05-31",
    }
    r = await client.post(f"/projects/{SLUG}/campaigns", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["campaign_name"] == "DT Stakeholder Survey"
    assert data["listenlabs_campaign_id"] == "camp_abc"

    r2 = await client.get(f"/projects/{SLUG}/campaigns")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


@pytest.mark.asyncio
async def test_update_campaign(client):
    await client.post("/projects", json=PROJECT)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"campaign_name": "Old"})
    cid = r.json()["id"]

    r2 = await client.patch(
        f"/projects/{SLUG}/campaigns/{cid}",
        json={"campaign_name": "New Name", "listenlabs_campaign_id": "camp_xyz"},
    )
    assert r2.status_code == 200
    assert r2.json()["campaign_name"] == "New Name"
    assert r2.json()["listenlabs_campaign_id"] == "camp_xyz"


@pytest.mark.asyncio
async def test_delete_campaign(client):
    await client.post("/projects", json=PROJECT)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"campaign_name": "To Delete"})
    cid = r.json()["id"]

    r2 = await client.delete(f"/projects/{SLUG}/campaigns/{cid}")
    assert r2.status_code == 204

    r3 = await client.get(f"/projects/{SLUG}/campaigns")
    assert r3.json() == []


@pytest.mark.asyncio
async def test_export_targets_csv(client):
    await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation", "listenlabs_campaign_id": "c1"},
    )
    cid = r.json()["id"]

    r2 = await client.get(f"/projects/{SLUG}/campaigns/{cid}/export-targets")
    assert r2.status_code == 200
    assert "text/csv" in r2.headers["content-type"]

    reader = csv.DictReader(io.StringIO(r2.text))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["email"] == "alice@corp.com"
    assert rows[0]["country_code"] == "GB"
    assert rows[0]["value_stream"] == "Digital Transformation"
    assert rows[0]["campaign_id"] == "c1"


@pytest.mark.asyncio
async def test_mark_invited(client):
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"value_stream_name": "Digital Transformation"})
    cid = r.json()["id"]

    r2 = await client.post(f"/projects/{SLUG}/campaigns/{cid}/mark-invited")
    assert r2.status_code == 200
    assert r2.json()["marked"] == 1

    # Second call should mark 0 (already invited)
    r3 = await client.post(f"/projects/{SLUG}/campaigns/{cid}/mark-invited")
    assert r3.json()["marked"] == 0


@pytest.mark.asyncio
async def test_import_progress(client):
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"value_stream_name": "Digital Transformation"})
    cid = r.json()["id"]

    csv_content = "email,status\nalice@corp.com,completed\nunknown@x.com,completed\n"
    r2 = await client.post(
        f"/projects/{SLUG}/campaigns/{cid}/import-progress",
        files={"file": ("progress.csv", csv_content.encode(), "text/csv")},
    )
    assert r2.status_code == 200
    result = r2.json()
    assert result["updated"] == 1   # alice matched
    assert result["skipped"] == 1   # unknown@x.com unmatched

    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT interview_status FROM stakeholders WHERE id=?", (sid,)
        ) as cur:
            row = await cur.fetchone()
    assert row["interview_status"] == "completed"


@pytest.mark.asyncio
async def test_import_results_json(client):
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"value_stream_name": "Digital Transformation"})
    cid = r.json()["id"]

    results = [{"email": "alice@corp.com", "q1": "answer1", "q2": "answer2"}]
    r2 = await client.post(
        f"/projects/{SLUG}/campaigns/{cid}/import-results",
        files={"file": ("results.json", json.dumps(results).encode(), "application/json")},
    )
    assert r2.status_code == 200
    assert r2.json()["imported"] == 1
    assert r2.json()["unmatched"] == 0


@pytest.mark.asyncio
async def test_import_summary(client):
    await client.post("/projects", json=PROJECT)
    r = await client.post(f"/projects/{SLUG}/campaigns", json={"campaign_name": "X"})
    cid = r.json()["id"]

    summary_text = "Overall finding: stakeholders want faster delivery."
    r2 = await client.post(
        f"/projects/{SLUG}/campaigns/{cid}/import-summary",
        files={"file": ("summary.txt", summary_text.encode(), "text/plain")},
    )
    assert r2.status_code == 200

    r3 = await client.get(f"/projects/{SLUG}/campaigns")
    camp = next(c for c in r3.json() if c["id"] == cid)
    assert camp["findings_summary"] == summary_text


@pytest.mark.asyncio
async def test_generate_reminders_gentle(client):
    """Stakeholder invited 3 days ago → gentle template."""
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation", "campaign_name": "DT Survey"},
    )
    cid = r.json()["id"]

    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    async with get_connection(SLUG) as conn:
        await conn.execute(
            "UPDATE stakeholders SET interview_invited_at=?, interview_status='invited' WHERE id=?",
            (three_days_ago, sid),
        )
        await conn.commit()

    r2 = await client.post(f"/projects/{SLUG}/campaigns/{cid}/generate-reminders")
    assert r2.status_code == 200
    assert r2.json()["created"] == 1

    r3 = await client.get(f"/projects/{SLUG}/reminder-emails")
    emails = r3.json()
    assert len(emails) == 1
    assert emails[0]["escalation_level"] == "gentle"
    assert "Alice" in emails[0]["body"]


@pytest.mark.asyncio
async def test_generate_reminders_firm(client):
    """Stakeholder invited 10 days ago → firm template."""
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation", "campaign_name": "DT Survey"},
    )
    cid = r.json()["id"]

    ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    async with get_connection(SLUG) as conn:
        await conn.execute(
            "UPDATE stakeholders SET interview_invited_at=?, interview_status='invited' WHERE id=?",
            (ten_days_ago, sid),
        )
        await conn.commit()

    await client.post(f"/projects/{SLUG}/campaigns/{cid}/generate-reminders")

    r2 = await client.get(f"/projects/{SLUG}/reminder-emails")
    assert r2.json()[0]["escalation_level"] == "firm"


@pytest.mark.asyncio
async def test_generate_reminders_urgent(client):
    """Stakeholder invited 20 days ago → urgent template."""
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation", "campaign_name": "DT Survey"},
    )
    cid = r.json()["id"]

    twenty_days_ago = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    async with get_connection(SLUG) as conn:
        await conn.execute(
            "UPDATE stakeholders SET interview_invited_at=?, interview_status='invited' WHERE id=?",
            (twenty_days_ago, sid),
        )
        await conn.commit()

    await client.post(f"/projects/{SLUG}/campaigns/{cid}/generate-reminders")

    r2 = await client.get(f"/projects/{SLUG}/reminder-emails")
    assert r2.json()[0]["escalation_level"] == "urgent"


@pytest.mark.asyncio
async def test_generate_reminders_skips_uninvited(client):
    """Stakeholder with no interview_invited_at is skipped."""
    await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation"},
    )
    cid = r.json()["id"]
    # Do NOT mark invited — interview_invited_at is NULL

    r2 = await client.post(f"/projects/{SLUG}/campaigns/{cid}/generate-reminders")
    assert r2.json()["created"] == 0


@pytest.mark.asyncio
async def test_interview_summary(client):
    _, sid = await _setup_project_and_stakeholder(client)
    today = datetime.now(timezone.utc).date().isoformat()
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={
            "value_stream_name": "Digital Transformation",
            "interview_start": today,
            "interview_close": today,
        },
    )
    cid = r.json()["id"]

    # Mark stakeholder as completed
    csv_content = "email,status\nalice@corp.com,completed\n"
    await client.post(
        f"/projects/{SLUG}/campaigns/{cid}/import-progress",
        files={"file": ("p.csv", csv_content.encode(), "text/csv")},
    )

    r2 = await client.get(f"/projects/{SLUG}/interview-summary")
    assert r2.status_code == 200
    data = r2.json()
    assert data["total_stakeholders"] == 1
    assert data["total_completed"] == 1


@pytest.mark.asyncio
async def test_approve_reminder_email(client):
    _, sid = await _setup_project_and_stakeholder(client)
    r = await client.post(
        f"/projects/{SLUG}/campaigns",
        json={"value_stream_name": "Digital Transformation", "campaign_name": "DT Survey"},
    )
    cid = r.json()["id"]

    # Create a reminder via manual DB insert (to avoid date dependency)
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        await conn.execute(
            """INSERT INTO reminder_emails
               (project_id, campaign_id, stakeholder_id, subject, body, escalation_level)
               VALUES (?,?,?,?,?,?)""",
            (project["id"], cid, sid, "Test subject", "Test body", "gentle"),
        )
        await conn.commit()

    emails = (await client.get(f"/projects/{SLUG}/reminder-emails")).json()
    eid = emails[0]["id"]

    r2 = await client.patch(
        f"/projects/{SLUG}/reminder-emails/{eid}",
        json={"status": "approved", "body": "Updated body text"},
    )
    assert r2.status_code == 200

    emails2 = (await client.get(f"/projects/{SLUG}/reminder-emails")).json()
    # Approved items no longer appear in pending list
    assert len(emails2) == 0
