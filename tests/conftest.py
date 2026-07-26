# tests/conftest.py
import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pathlib import Path

# asyncio_mode = strict (see pytest.ini) — all async tests must use @pytest.mark.asyncio

# Point to a temp directory so tests never touch real project data
os.environ.setdefault("DATABASE_DIR", "/tmp/agentpool_test")
os.environ.setdefault("PROJECTS_DIR", "/tmp/agentpool_test_projects")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("LITELLM_PROXY_URL", "http://localhost:4000")
os.environ.setdefault("LLAMACPP_BASE_URL", "http://localhost:10000")
os.environ.setdefault("CHROMA_HOST", "localhost")
os.environ.setdefault("CHROMA_PORT", "8002")  # pydantic coerces str→int
# Blank all credential-gated settings so unit tests behave identically whether
# or not the developer has real services configured in .env. pydantic-settings
# reads .env directly, so without these a populated .env changes test outcomes:
# a real CHROMA_API_KEY flips ingest_service to CloudClient, a real
# RESEND_API_KEY makes "no key" paths attempt real sends, and so on.
os.environ.setdefault("CHROMA_API_KEY", "")
os.environ.setdefault("RESEND_API_KEY", "")
os.environ.setdefault("TAVILY_API_KEY", "")
os.environ.setdefault("ELEVENLABS_API_KEY", "")
os.environ.setdefault("DEEPGRAM_API_KEY", "")
os.environ.setdefault("N8N_WEBHOOK_URL", "")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")

Path("/tmp/agentpool_test").mkdir(exist_ok=True)
Path("/tmp/agentpool_test_projects").mkdir(exist_ok=True)


@pytest_asyncio.fixture
async def client():
    from api.main import app
    from api.auth import create_access_token
    # Use a sysadmin token so all project-scoped endpoints pass auth checks
    token = create_access_token("admin", "sysadmin", "test-secret")
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as ac:
        yield ac
