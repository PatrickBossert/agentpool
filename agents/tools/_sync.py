# agents/tools/_sync.py
"""Running one coroutine to completion from inside a synchronous CrewAI tool.

One copy, two callers - `InterviewSessionTool` and `SkillProposalTool` - because the two
calling contexts a tool actually sees are not obvious and a second copy would be free to get
the second one wrong. It was a private helper in `interview_session_tool.py` until a tool in
another file needed the same thing.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor


def await_sync(coro):
    """Run one coroutine to completion from synchronous code, with or without a live loop.

    In production there is no loop: CrewAI dispatches through `crew.kickoff_async()`, which
    runs the crew under `asyncio.to_thread`, so a tool executes on a worker thread and
    `asyncio.run` is exactly right. **That is not the only caller**, though - tests drive
    `_run` from inside an async test, where `asyncio.run` raises "cannot be called from a
    running event loop". A tool that works from one calling context and explodes in another is
    a trap laid for whoever next dispatches a crew differently, so the loop case runs the
    coroutine on a thread of its own rather than being refused.

    One coroutine, awaited once, in both arms - it is never scheduled twice, which would be a
    second database read rather than a repeat of the first.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
