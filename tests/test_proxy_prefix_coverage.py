"""The two reverse proxies must forward every route the API actually mounts.

Three separate faults kept the dashboard from ever reaching the API in a deployed build, and
none of them was visible to a unit suite or to a local `vite dev`:

1. ``ui/src/api/client.ts`` used an absolute ``http://localhost:8000`` base, so every call went
   to the viewer's own machine and bypassed both proxies.
2. The ``Caddyfile`` forwarded ``/api/*`` and ``/ws/*`` only, while twenty of twenty-two routers
   mount under ``/projects``, ``/auth``, ``/admin``, ``/system``, or ``/agent-skill-notes``.
3. Those two conventions disagree, so no single rewrite could serve both.

Faults 1 and 3 are one-time repairs. Fault 2 recurs on its own: mounting a router under a new
prefix is a one-line change in ``api/main.py`` that leaves every existing test green while
making the new endpoints unreachable in production - the request falls through to the static
file server, which answers the landing page with a **200**, so even a smoke test that only
checks the status code sees nothing wrong.

So this module asserts the property at the level where it holds: it takes the real path of every
route on the real ``app``, and checks that the Caddyfile and the Vite dev proxy would each
forward that path to the API. Not the prefix list, not a constant - the paths themselves, run
through an implementation of each proxy's own matching rule. A ``/projects/*`` matcher, for
instance, fails here, because it does not match the bare ``POST /projects``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import starlette.routing
from fastapi.routing import APIRoute, APIWebSocketRoute

from api.main import app

REPO_ROOT = Path(__file__).resolve().parents[1]
CADDYFILE = REPO_ROOT / "Caddyfile"
VITE_CONFIG = REPO_ROOT / "ui" / "vite.config.ts"

# The upstream both proxies must send API traffic to. Caddy also proxies /dashboard* to
# localhost:3000, and a block pointing there does not count as coverage - that is the SPA, and
# an API path answered by it is exactly the failure this module exists to catch.
API_UPSTREAM = "localhost:8000"

# FastAPI mounts these itself, and they are deliberately *not* proxied: the dashboard never
# calls them, and publishing an interactive API console on the public origin buys nothing but
# a map of the surface for anyone who asks. They are named here rather than filtered by route
# class so that the exemption is a decision on the record; test_exempt_paths_are_all
# _framework_supplied then refuses to let an application route join the list.
FRAMEWORK_PATHS = frozenset({"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"})


def _concrete(path: str) -> str:
    """Substitute a sample value for each path parameter.

    Neither proxy inspects the value, so any non-empty segment will do - but ``{slug}`` is not
    a path either matcher would ever see, and matching against the literal braces would be
    asserting on a string no request carries.
    """
    return re.sub(r"\{[^}]*\}", "sample", path)


def api_route_paths() -> list[str]:
    """Every concrete path the application itself serves, framework routes excluded."""
    return sorted(
        {
            _concrete(route.path)
            for route in app.routes
            if getattr(route, "path", None) and route.path not in FRAMEWORK_PATHS
        }
    )


def websocket_route_paths() -> list[str]:
    return sorted(
        {_concrete(route.path) for route in app.routes if isinstance(route, APIWebSocketRoute)}
    )


# --------------------------------------------------------------------------------------
# Caddyfile
# --------------------------------------------------------------------------------------


def _caddy_api_matchers(text: str) -> list[str]:
    """Path matchers of every ``handle`` block whose body proxies to the API upstream.

    A deliberately small Caddyfile reader: track the brace depth, remember the matcher of each
    open ``handle``, and record it when a ``reverse_proxy`` line inside names the API.
    """
    matchers: list[str] = []
    stack: list[str | None] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.endswith("{"):
            head = line[:-1].strip()
            opened = re.fullmatch(r"handle\s+(\S+)", head)
            stack.append(opened.group(1) if opened else None)
            continue
        if line == "}":
            if stack:
                stack.pop()
            continue
        if line.startswith("reverse_proxy") and API_UPSTREAM in line:
            for matcher in reversed(stack):
                if matcher is not None:
                    matchers.append(matcher)
                    break
    return matchers


def _caddy_matches(matcher: str, path: str) -> bool:
    """Caddy's path matcher: an exact match, with ``*`` standing for any run of characters."""
    pattern = "".join(
        ".*" if piece == "*" else re.escape(piece) for piece in re.split(r"(\*)", matcher)
    )
    return re.fullmatch(pattern, path, re.IGNORECASE) is not None


# --------------------------------------------------------------------------------------
# Vite dev server
# --------------------------------------------------------------------------------------


def _braced_block(text: str, after: str) -> str:
    """The contents of the first ``{...}`` block following *after*."""
    start = text.index("{", text.index(after))
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    raise AssertionError(f"unterminated block after {after!r} in {VITE_CONFIG}")


def _vite_proxy_entries(text: str) -> dict[str, str]:
    """``server.proxy`` as a mapping of context string to the source text of its target."""
    # Whole-line comments only. A blanket "//" strip would eat the rest of every line from
    # inside 'http://localhost:8000', which is how the first draft of this parser reported
    # that the config had no proxy entries at all.
    body = re.sub(r"^[ \t]*//[^\n]*$", "", _braced_block(text, "proxy:"), flags=re.M)
    entries: dict[str, str] = {}
    depth = 0
    quoted = False
    buffer = ""
    for char in body + ",":
        if char == "'":
            quoted = not quoted
        elif quoted:
            pass
        elif char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
        if char == "," and depth == 0 and not quoted:
            entry = re.fullmatch(r"\s*'(/[^']*)'\s*:\s*(.*)", buffer, re.S)
            if entry:
                entries[entry.group(1)] = entry.group(2).strip()
            buffer = ""
            continue
        buffer += char
    return entries


def _vite_matches(context: str, path: str) -> bool:
    """Vite forwards a request when its path starts with the context string."""
    return path.startswith(context)


# --------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------


def test_the_route_enumeration_is_not_empty():
    """Guard the guard: an enumeration that came back empty would pass everything below.

    Deliberately not an exact list of prefixes. A test that has to be edited every time a
    router is added teaches the habit of editing this file until it goes green, which is the
    last habit to encourage next to ``FRAMEWORK_PATHS``. The coverage tests themselves are
    what should fail when a new prefix appears, and their message says what to do about it.
    """
    paths = api_route_paths()
    assert len(paths) > 100, paths
    prefixes = {path.lstrip("/").split("/")[0] for path in paths}
    assert {"projects", "auth"} <= prefixes, prefixes


def test_caddyfile_forwards_every_api_route():
    matchers = _caddy_api_matchers(CADDYFILE.read_text())
    assert matchers, f"no handle block in {CADDYFILE} proxies to {API_UPSTREAM}"

    unmatched = [
        path for path in api_route_paths() if not any(_caddy_matches(m, path) for m in matchers)
    ]
    assert not unmatched, (
        f"{len(unmatched)} API paths reach no handle block in the Caddyfile and would be "
        f"answered by the static landing page with a 200: {unmatched[:10]}. "
        f"Matchers found: {matchers}"
    )


def test_vite_dev_proxy_forwards_every_api_route():
    entries = _vite_proxy_entries(VITE_CONFIG.read_text())
    assert entries, f"no server.proxy entries found in {VITE_CONFIG}"

    misdirected = [
        context for context, target in entries.items() if API_UPSTREAM not in target
    ]
    assert not misdirected, f"proxy entries not pointed at {API_UPSTREAM}: {misdirected}"

    unmatched = [
        path
        for path in api_route_paths()
        if not any(_vite_matches(context, path) for context in entries)
    ]
    assert not unmatched, (
        f"{len(unmatched)} API paths are not forwarded by the Vite dev proxy and would be "
        f"answered by the SPA fallback: {unmatched[:10]}. Contexts found: {sorted(entries)}"
    )


def test_websocket_routes_are_proxied_with_the_upgrade_enabled():
    """A WebSocket path forwarded without ``ws: true`` is answered as a plain request."""
    entries = _vite_proxy_entries(VITE_CONFIG.read_text())
    paths = websocket_route_paths()
    assert paths, "no WebSocket routes found - this test would assert nothing"

    for path in paths:
        contexts = [context for context in entries if _vite_matches(context, path)]
        assert contexts, f"{path} is not forwarded by the Vite dev proxy at all"
        assert any("ws: true" in entries[context] for context in contexts), (
            f"{path} is forwarded by {contexts} but none of them sets ws: true, so the dev "
            f"proxy would answer the handshake instead of upgrading it"
        )


def test_exempt_paths_are_all_framework_supplied():
    """Nothing the application serves can be excused by joining ``FRAMEWORK_PATHS``.

    Without this, the cheapest way to make the two tests above pass is to add the offending
    prefix to the exemption set, which is precisely the outcome they exist to prevent. Routes
    FastAPI creates for itself are plain Starlette ``Route`` objects; everything registered
    through ``include_router`` is an ``APIRoute`` or ``APIWebSocketRoute``.
    """
    by_path = {getattr(route, "path", None): route for route in app.routes}

    missing = sorted(FRAMEWORK_PATHS - set(by_path))
    assert not missing, f"exemption has rotted - these paths no longer exist: {missing}"

    for path in sorted(FRAMEWORK_PATHS):
        route = by_path[path]
        assert type(route) is starlette.routing.Route, (
            f"{path} is exempted from proxy coverage but is a {type(route).__name__}, not a "
            f"framework-supplied route - application endpoints must be proxied, not excused"
        )
        assert not isinstance(route, (APIRoute, APIWebSocketRoute))


@pytest.mark.parametrize("path", sorted(FRAMEWORK_PATHS))
def test_framework_doc_routes_are_deliberately_not_published(path):
    """Pins the decision, so re-exposing /docs on the public origin has to be deliberate."""
    matchers = _caddy_api_matchers(CADDYFILE.read_text())
    matching = [matcher for matcher in matchers if _caddy_matches(matcher, path)]
    assert not matching, (
        f"{path} is now forwarded to the API by {matching}. FastAPI's interactive docs were "
        f"deliberately left on the public origin's static handler; if that has changed on "
        f"purpose, remove it from FRAMEWORK_PATHS and say why."
    )
