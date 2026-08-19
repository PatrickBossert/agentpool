# tests/test_process_cache_teardown.py
"""`conftest.reset_process_caches` clears *after* each test as well as before.

A file of its own, holding one test, and both facts are load-bearing.

**Why a module-scoped fixture.** The window the after-`yield` clear protects is the one
between a test's own teardown and whatever runs next outside a test body. Nothing inside a
test body can see it, and a function-scoped fixture cannot either: fixtures finalise in
reverse order of setup, so anything a test requests is torn down *before* the autouse
fixture it depends on. A module-scoped fixture is set up first and finalised last, which
puts its teardown after the last function-scoped teardown in the module - exactly the
window.

**Why its own file.** A module-scoped fixture finalises when the module's *last* test ends.
Put this beside other tests and their before-clears would have wiped the probe long before
the assertion ran, so it would pass whether or not the after-clear existed - the vacuous
pass this branch has now found six times. One test in one module means the fixture
finalises immediately after it.

Established by mutation rather than by argument: remove the after-`yield` call in
`tests/conftest.py` and this errors with the probe still in the cache; restore it and it
passes. Before this file existed the whole suite passed either way, and the fixture's
docstring carried a paragraph saying so - which is the wrong resolution on a project whose
rule is that a property should fail rather than rot.
"""
from __future__ import annotations

import pytest

from api.services import chroma_client

PROBE = "process-cache-teardown-probe"


@pytest.fixture(scope="module")
def sees_the_teardown():
    yield
    assert PROBE not in chroma_client._MODE_CACHE, (
        f"conftest.reset_process_caches left {PROBE!r} in the mode cache after the last "
        "test in this module - it is clearing before each test but not after, so residue "
        "outlives the suite's own isolation and reaches anything that runs outside a test "
        f"body. Cache held: {chroma_client._MODE_CACHE}"
    )


def test_residue_does_not_outlive_the_test_that_left_it(sees_the_teardown):
    """Leave a slug resolved and let the fixture teardown be the assertion.

    Scoped to the one key this test wrote rather than asserting the whole cache is empty:
    an equality against `{}` fails on anything else's residue, which would report a defect
    in the after-clear for a reason having nothing to do with it.
    """
    chroma_client._MODE_CACHE[PROBE] = "sensitive"
    assert PROBE in chroma_client._MODE_CACHE, (
        "the probe must genuinely be in the cache, or the teardown assertion passes "
        "whatever the fixture does"
    )
