# tests/test_provider_quota.py
"""A quota reader that cannot see the quota must say so, not report healthy.

Both readers are blocked on a key's permissions rather than on code, measured 17 September
2026: ElevenLabs answers **401** to `/v1/user/subscription` with a key that synthesises
perfectly, and Deepgram answers **403** to `/balances` with a key that transcribes perfectly.
So the branch that runs today, on this deployment, is the refused one - which makes it the
branch most worth driving.

Every property is driven **both ways**. "A refusal is reported" is satisfied by a reader that
reports everything; "a healthy account is not" by one that reports nothing.

No network: `httpx.get` is replaced at its source, so no test here can reach a provider.
"""
from __future__ import annotations

import pytest

from api.config import get_settings
from api.services import provider_quota
from api.services.provider_quota import check_speech_quota, check_transcription_usage


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _answers(monkeypatch, *replies):
    """Queue `(status, body)` per call, so a two-request reader can be driven end to end."""
    queue = list(replies)
    calls: list[str] = []

    def _fake(url, headers=None, timeout=None):
        calls.append(url)
        status, body = queue.pop(0)

        class _R:
            status_code = status
            text = body if isinstance(body, str) else ""
            def json(self):
                if isinstance(body, str):
                    raise ValueError("not json")
                return body
        return _R()

    monkeypatch.setattr("httpx.get", _fake)
    return calls


# ── ElevenLabs ────────────────────────────────────────────────────────────────

def test_a_key_refused_the_allowance_falls_through_to_what_it_can_read(monkeypatch):
    """The live condition, and the reader must not stop at the refusal.

    Measured: the account's Editor role is served `/v1/usage/character-stats` and refused
    `/v1/user/subscription`, which names the missing permission as `user_read`. So consumption
    is knowable today and the allowance is not - and a reader that gave up at the 401 would
    report nothing while a perfectly good number sat one request away.

    Asserted on **both** requests being made, because a fallback that is never reached is the
    defect this replaces.
    """
    calls = _answers(
        monkeypatch,
        (401, {"detail": {"status": "missing_permissions", "message": "missing the permission user_read"}}),
        (200, {"usage": {"All": [100.0, 250.0]}}),
    )
    r = check_speech_quota()
    assert len(calls) == 2 and "character-stats" in calls[1]
    assert r.ok is True
    assert "350 characters" in r.diagnosis
    assert "not the allowance remaining" in r.diagnosis
    assert "user_read" in r.diagnosis


def test_a_key_refused_both_reports_the_permission_and_the_remedy(monkeypatch):
    """Neither endpoint available - the only case where nothing can be said about spend."""
    _answers(monkeypatch,
             (401, {"detail": {"status": "missing_permissions"}}),
             (401, {"detail": {"status": "missing_permissions"}}))
    r = check_speech_quota()
    assert r.ok is False
    assert "user_read" in r.diagnosis and "not a bad key" in r.diagnosis


def test_the_consumption_window_is_passed_not_read(monkeypatch):
    """The clock is an argument. Three tests on this project died to a `new Date()` default."""
    from api.services.provider_quota import _CONSUMPTION_WINDOW_DAYS, _speech_consumption

    calls = _answers(monkeypatch, (200, {"usage": {"All": [1.0]}}))
    _speech_consumption("k", now_ms=1_000_000_000_000)
    assert "end_unix=1000000000000" in calls[0]
    expected = 1_000_000_000_000 - _CONSUMPTION_WINDOW_DAYS * 24 * 3600 * 1000
    assert f"start_unix={expected}" in calls[0]


def test_an_account_with_room_is_healthy_and_is_not_reported(monkeypatch):
    """The control. Without it, a reader that refused everything would pass every test above."""
    _answers(monkeypatch, (200, {"character_count": 1_000, "character_limit": 100_000,
                                 "tier": "creator"}))
    r = check_speech_quota()
    assert r.ok is True
    assert "1%" in r.diagnosis


def test_an_account_near_its_limit_is_reported_before_it_stops_working(monkeypatch):
    _answers(monkeypatch, (200, {"character_count": 95_000, "character_limit": 100_000,
                                 "tier": "creator"}))
    r = check_speech_quota()
    assert r.ok is False
    assert "95%" in r.diagnosis
    assert "Interviews stop speaking" in r.diagnosis


@pytest.mark.parametrize("body", [
    {"character_count": 5, "character_limit": 0},      # division by zero
    {"character_count": "lots", "character_limit": 10},
    {"tier": "creator"},                                # the fields absent entirely
    "not json at all",
])
def test_an_unusable_answer_is_reported_rather_than_guessed(monkeypatch, body):
    """A provider that changes its shape must not produce a confident wrong percentage."""
    _answers(monkeypatch, (200, body))
    assert check_speech_quota().ok is False


def test_a_network_failure_is_reported_not_raised(monkeypatch):
    """Called from inside `except` blocks - raising would replace the original failure."""
    def _boom(*_a, **_k):
        raise OSError("no route to host")
    monkeypatch.setattr("httpx.get", _boom)
    r = check_speech_quota()
    assert r.ok is False and "OSError" in r.diagnosis


def test_no_key_is_reported_rather_than_read(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    get_settings.cache_clear()
    called = _answers(monkeypatch)
    r = check_speech_quota()
    assert r.ok is False and "not set" in r.diagnosis
    assert called == [], "asked the provider without a key"


# ── Deepgram ──────────────────────────────────────────────────────────────────

def test_usage_is_read_through_the_account_and_never_called_a_balance(monkeypatch):
    """The honest half: this reads consumption, because the key may not read a balance.

    Asserted on the sentence, because the whole risk of this reader is a later change - or a
    reader in a hurry - presenting hours consumed as credit remaining.
    """
    calls = _answers(
        monkeypatch,
        (200, {"projects": [{"project_id": "p1"}]}),
        (200, {"start": "2026-09-10", "end": "2026-09-17",
               "results": [{"hours": 1.5}, {"hours": 0.25}]}),
    )
    r = check_transcription_usage()
    assert r.ok is True
    assert "1.75 hours" in r.diagnosis
    assert "not a remaining balance" in r.diagnosis
    assert calls[1].endswith("/projects/p1/usage")


def test_a_key_refused_the_usage_scope_names_the_authorisation_it_needs(monkeypatch):
    _answers(monkeypatch,
             (200, {"projects": [{"project_id": "p1"}]}),
             (403, {"category": "INSUFFICIENT_PERMISSIONS"}))
    r = check_transcription_usage()
    assert r.ok is False
    assert "Admin or Owner" in r.diagnosis
    assert "Transcription is unaffected" in r.diagnosis


def test_an_unreachable_account_does_not_ask_for_usage(monkeypatch):
    """One failed request, not two: there is no project id to ask about."""
    calls = _answers(monkeypatch, (401, {"err": "bad key"}))
    r = check_transcription_usage()
    assert r.ok is False and len(calls) == 1


# ── The registry ──────────────────────────────────────────────────────────────

def test_both_readers_are_registered_and_anthropic_deliberately_is_not():
    """Anthropic's absence is a decision, so it is asserted rather than left to be noticed.

    It publishes no balance endpoint, and a probe would have to spend tokens to ask how many
    remain. Its rate-limit headers ride every response instead.
    """
    from api.services.health_checks import HEALTH_CHECKS

    keys = {c.key for c in HEALTH_CHECKS}
    assert {"vector_store", provider_quota.SPEECH_QUOTA, provider_quota.TRANSCRIPTION_USAGE} <= keys
    assert not any("anthropic" in k or "claude" in k for k in keys)


def test_every_registered_probe_takes_a_slug_and_answers_a_health_result(monkeypatch):
    """The registry's contract, driven over every member rather than asserted of one.

    A quota is a property of the account and a store is a property of the project, so two of
    the three ignore the slug - but a probe that could not be *called* with one would break the
    caller that hands every member the failing project's slug.
    """
    from api.services.health_checks import HEALTH_CHECKS, HealthResult

    _answers(monkeypatch, *[(0, "unreachable")] * 6)
    for check in HEALTH_CHECKS:
        assert isinstance(check.probe("any-slug"), HealthResult), check.key


def test_the_registry_holds_the_same_members_whichever_module_is_imported_first():
    """The defect this nearly shipped with, and it degraded rather than failing.

    `HealthResult` lived in `health_checks`, which imports the probe modules to build its
    registry - so a probe module importing `HealthResult` back closed a cycle. Assembled behind
    a `try/except ImportError`, that gave **three members when `health_checks` was imported
    first and one when `provider_quota` was**: an alert path whose membership depended on which
    module a caller happened to touch first, with two checks silently absent.

    Driven in a subprocess per order, because within one process the first import wins and the
    second is a cache hit - a same-process test would pass against the broken version.
    """
    import subprocess
    import sys

    def members(first: str) -> list[str]:
        code = (
            f"import {first}\n"
            "import api.services.health_checks as h\n"
            "print(','.join(c.key for c in h.HEALTH_CHECKS))"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr[-500:]
        return sorted(out.stdout.strip().split(","))

    assert members("api.services.health_checks") == members("api.services.provider_quota")
    assert "speech_quota" in members("api.services.provider_quota")
