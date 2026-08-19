"""Tests for the single interview-URL builder.

The emailed link is the entire mechanism for the dispatch campaign in sub-project A: if the
URL is wrong, nothing else matters. Three call sites used to build this string independently
and two of them were wrong (missing basename, wrong setting). This file pins the helper's
output and then greps the tree for any hand-built version of the same string, so a
regression is caught even if a new call site is added later.
"""
import pytest
from api.config import get_settings
from api.services import platform_settings as ps


def test_the_url_carries_the_dashboard_basename(tmp_path, monkeypatch):
    """The SPA is served under /dashboard (vite base, router basename). A link without it
    404s, and the emailed link is the whole mechanism for the dispatch campaign.

    interview_url() now goes through platform_public_url(), which carries its own
    module-level cache independent of get_settings.cache_clear() - so this test also
    points DATABASE_DIR at an empty tmp_path (no system.db to read a stored value from)
    and forgets that cache on both sides, the same isolation
    tests/test_platform_settings.py's autouse fixture applies to every test in that file.
    Without it, whichever test in the suite happens to populate the cache first pins the
    answer for every test after it, including this one.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_URL", "https://example.test")
    get_settings.cache_clear()
    ps.forget_platform_settings()
    from api.services.interview_service import interview_url
    assert interview_url("abc123") == "https://example.test/dashboard/interview/abc123"
    ps.forget_platform_settings()
    get_settings.cache_clear()


def test_every_builder_uses_the_helper():
    """Three call sites built this string independently and two were wrong.

    The one file exempted from this scan is the one that defines interview_url() itself -
    its own f-string is the sanctioned single build site, not a regression.
    """
    from pathlib import Path
    import re
    definition_file = Path("api/services/interview_service.py")
    offenders = []
    for path in (Path("api"), Path("agents")):
        for f in path.rglob("*.py"):
            if f == definition_file:
                continue
            for i, line in enumerate(f.read_text().splitlines(), 1):
                if re.search(r'f".*/interview/\{', line):
                    offenders.append(f"{f}:{i}")
    assert not offenders, f"interview URL built by hand at {offenders}"
