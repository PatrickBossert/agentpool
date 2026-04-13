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

Path("/tmp/agentpool_test").mkdir(exist_ok=True)
Path("/tmp/agentpool_test_projects").mkdir(exist_ok=True)


@pytest_asyncio.fixture
async def client():
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
