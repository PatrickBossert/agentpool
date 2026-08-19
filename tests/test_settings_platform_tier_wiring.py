"""The Settings page's platform-tier gating, guarded from the side that can see the server.

Two properties live here, and neither is expressible in the frontend suite alone.

**1. The frontend fixture is the server's tuple.** `_PLATFORM_TIER_SETTINGS` cannot be
imported by vitest, so the nine names are written down twice - once in Python, once in
`ui/src/__tests__/fixtures/platformTierSettings.ts`. Review proved what an unguarded second
copy costs: adding a tenth member to the tuple left the whole frontend suite green at 654,
because nothing on that side knew the list had moved. The names may still be written twice;
they may no longer *disagree*.

**2. Every control on the page asks the server whether its field is locked.** The gating was
correct and hand-threaded, which is not the same property. With `disabled={locked(field)}`
applied only to the controls somebody remembered, a tenth platform-tier field rendered fully
editable - the page offering a control the server refuses, which is the exact failure
`/my-permissions` exists to prevent. `fieldProps` makes the asking structural; this walk makes
skipping it fail.

Written here rather than in vitest because the first property needs the Python tuple, and the
second is a source property that vitest cannot see any better than a reader can - this file is
the same technique `tests/test_deployment_modes.py` uses to hold the frontend's mode lists
equal to `EGRESS_GRANTS`.
"""
import re
from pathlib import Path

import pytest

from api.routers.projects import _PLATFORM_TIER_SETTINGS

UI = Path(__file__).resolve().parents[1] / "ui" / "src"
FIXTURE = UI / "__tests__" / "fixtures" / "platformTierSettings.ts"
SETTINGS_PAGE = UI / "pages" / "Settings.tsx"


def _fixture_list(name: str) -> list[str]:
    """The named `export const NAME = [...]` array, read as source.

    Extracted structurally rather than by searching for the nine names it is expected to
    hold: a search keyed on the expected values catches a *missing* member and is blind to an
    *extra* one, which is the dangerous direction here - a field the fixture believes is
    platform-tier and the server does not.
    """
    source = FIXTURE.read_text()
    match = re.search(rf"export const {name} = \[(.*?)\]", source, re.S)
    assert match, f"{name} is no longer a literal array in {FIXTURE.name}"
    return re.findall(r"'([^']+)'", match.group(1))


def test_the_frontend_fixture_is_the_servers_platform_tier_tuple():
    """Equal, and in order - the endpoint answers `list(_PLATFORM_TIER_SETTINGS)`, so a set
    comparison would pass against a fixture that had been rebuilt by hand and happened to
    name the same nine."""
    assert _fixture_list("PLATFORM_TIER_SETTINGS") == list(_PLATFORM_TIER_SETTINGS), (
        f"{FIXTURE} has drifted from api.routers.projects._PLATFORM_TIER_SETTINGS. The "
        "frontend tests stand in for the server using that fixture, so while they disagree "
        "the Settings page's gating is being tested against a list nothing serves."
    )


def test_the_fields_with_no_control_are_all_platform_tier_fields():
    """The exclusion list cannot excuse a field that is not on the tuple at all - otherwise a
    renamed member could be quietly parked there and the split test would stop covering it."""
    unknown = [
        f for f in _fixture_list("PLATFORM_TIER_FIELDS_WITH_NO_CONTROL")
        if f not in _PLATFORM_TIER_SETTINGS
    ]
    assert not unknown, f"{unknown} are excused from having a control and are not platform-tier"


# Anything that takes a value from the operator. `role="switch"` is here because this page's
# toggles are buttons, and a button that sets a settings field is a control whatever element
# it is built from - the review's probe (stripping an id) had to be caught on the toggle as
# readily as on an input.
_CONTROL_OPENERS = ("<input", "<select", "<textarea", "<TagInput")

# The one control that legitimately does not call fieldProps: TagInput's internal input edits
# the pending tag rather than a settings field, and wears the id and disabled its *caller*
# derived. Named rather than pattern-matched, so adding a second exemption is a visible edit.
_EXEMPT_MARKER = "fieldProps: taken from the call site"


def _control_blocks(source: str) -> list[tuple[int, str]]:
    """Every control tag in the file, as (line number, text up to the end of its attributes)."""
    blocks: list[tuple[int, str]] = []
    for match in re.finditer("|".join(re.escape(o) for o in _CONTROL_OPENERS), source):
        start = match.start()
        depth, i = 0, start
        while i < len(source):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
            elif source[i] == ">" and depth == 0:
                break
            i += 1
        blocks.append((source.count("\n", 0, start) + 1, source[start:i]))
    return blocks


def test_every_settings_control_asks_the_server_whether_its_field_is_locked():
    """No control renders without `fieldProps`, which is where `id` and `disabled` both come
    from.

    This is the guard the review's finding earned. The gating was right for the three
    controls it had been wired onto and absent everywhere else, and nothing failed - the page
    looked gated, and a field the server refused was editable. `fieldProps` cannot be
    forgotten silently now: a control that skips it has no id either, so it is invisible to
    the page's own tests, and this walk names the line.
    """
    source = SETTINGS_PAGE.read_text()
    offenders = [
        f"{SETTINGS_PAGE.name}:{line}  {block.splitlines()[0].strip()}"
        for line, block in _control_blocks(source)
        if "{...fieldProps(" not in block and _EXEMPT_MARKER not in source[:source.index(block)][-400:]
    ]
    assert not offenders, (
        "these controls render without asking whether their field is platform-tier, so a "
        "field the server refuses would be offered as editable:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("field", [f for f in _PLATFORM_TIER_SETTINGS])
def test_every_platform_tier_field_is_declared_on_the_frontend_settings_type(field):
    """A platform-tier field absent from `ProjectSettings` in types.ts survives a save only as
    an untyped extra key the `{ ...DEFAULTS, ...settings }` spread happens to copy.

    That is this whole task's hazard, and closing it for `force_local_inference` left it open
    for `dev_mode` one field over - which is why this is parametrised over the tuple rather
    than asserted for the two fields anybody happened to think of. A dropped key is the
    model's *default* on the server: `false` for the override, which widens where prompts go,
    and `true` for `dev_mode`, which silently switches the outbound-mail hold back on.
    """
    declared = (UI / "types.ts").read_text()
    block = declared[declared.index("export interface ProjectSettings {"):]
    block = block[:block.index("\n}")]
    assert re.search(rf"^\s*{field}\??:", block, re.M), (
        f"{field} is platform-tier and is not declared on ProjectSettings in ui/src/types.ts, "
        "so it rides on the object spread alone and any typed request body drops it"
    )
    assert not re.search(rf"^\s*{field}\?:", block, re.M), (
        f"{field} is declared optional. Optional is how it goes missing: tsc has nothing to "
        "say about an omitted optional key, and an omitted key is the model default on the "
        "server rather than the value the project holds."
    )
