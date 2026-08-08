# tests/test_interview_concurrency.py
"""Properties that only exist when interviews overlap.

Asserted against behaviour rather than against call sites. A test that asserts
asyncio.to_thread was called cannot tell whether the event loop was actually freed,
which is the entire property.
"""
import asyncio
import time
import pytest


@pytest.mark.asyncio
async def test_indexing_does_not_delay_other_sessions(monkeypatch):
    """One session completing must not stall the others.

    index_answers is stubbed with a blocking sleep standing in for a slow or unreachable
    Chroma. If it runs on the event loop, the concurrent waiter is served only after it
    finishes; if it runs in a thread, the waiter is served immediately.
    """
    from api.services import interview_answer_service as svc

    def slow_index(slug, rows):
        time.sleep(0.5)          # blocking, exactly as a Chroma round trip is
        return len(rows)

    monkeypatch.setattr(svc, "index_answers", slow_index)

    async def waiter(t0):
        await asyncio.sleep(0.01)
        return time.perf_counter() - t0

    t0 = time.perf_counter()
    _, waited = await asyncio.gather(
        svc._index_in_background("s", [{"id": 1}]),
        waiter(t0),
    )
    assert waited < 0.2, (
        f"a concurrent session waited {waited:.2f}s while another completed - "
        "indexing is still on the event loop"
    )
