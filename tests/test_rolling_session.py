# tests/test_rolling_session.py
"""Thirty days, refreshed on use, so an active reviewer never logs in twice.

PAM's links are ordinary application URLs: they work while a session is live and bounce to
login when it is not. A reviewer who reads three scripts a week should never see the login
page again after the first time.

seeded_project_slug follows tests/test_my_permissions.py's fixture of the same name: the
client fixture in conftest.py is an async httpx client against the real app, so every call
here is awaited, and the db file is removed before and after rather than trusting a fresh
tmp_path - DATABASE_DIR is the process-wide /tmp/agentpool_test set in conftest.py, which
persists between runs.
"""
from pathlib import Path

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from jose import jwt

from api.auth import create_access_token, ACCESS_TOKEN_EXPIRE_HOURS
from api.config import get_settings
from api.database import get_connection

SLUG = "rolling-session-test"


@pytest_asyncio.fixture
async def seeded_project_slug():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)

    async with get_connection(SLUG) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (SLUG,))
        await conn.commit()

    yield SLUG

    db_path.unlink(missing_ok=True)
    get_settings.cache_clear()


def test_a_token_lasts_thirty_days():
    assert ACCESS_TOKEN_EXPIRE_HOURS == 24 * 30
    secret = get_settings().jwt_secret
    payload = jwt.decode(create_access_token("ana", "reviewer", secret), secret,
                         algorithms=["HS256"])
    remaining = datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - datetime.now(timezone.utc)
    assert 29 <= remaining.days <= 30


@pytest.mark.asyncio
async def test_an_authenticated_request_returns_a_refreshed_token(client, seeded_project_slug):
    """Rolling means re-issued on use. Without this the thirtieth day is a cliff, and it
    arrives while somebody is mid-review."""
    r = await client.get(f"/projects/{seeded_project_slug}/my-permissions")
    assert r.status_code == 200
    assert r.headers.get("X-Refreshed-Token"), "an authenticated response must roll the session"
