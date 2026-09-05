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


# Anything on this page that takes a value from the operator. `<button` is here because the
# toggles are buttons, and a button that sets a settings field is a control whatever element
# it is built from - **which the first version of this list did not say and did not do.** It
# named the four tag-like openers, while the comment beside it claimed the switches were
# covered, so `force_local_inference` - the control this whole task exists to add - was never
# examined: stripping `fieldProps` from a toggle left this walk green, the frontend suite
# green at 660 and tsc clean.
#
# The reach is therefore no longer described in prose. `test_the_walk_sees_every_kind_of
# _control_this_page_builds` drives one of each kind through the walk, so the claim is
# established rather than asserted.
_CONTROL_OPENERS = ("<input", "<select", "<textarea", "<TagInput", "<button")

# A control that legitimately takes no field: a button that acts rather than edits, or an
# input whose value is not a settings field. Written immediately above the control as
# `{/* not-a-settings-control: why */}`, so an exemption is a visible edit with a reason
# attached rather than an absence.
_EXEMPT = "not-a-settings-control:"

# How far back to look for that marker. One JSX comment plus the attributes of the tag it
# precedes; big enough to survive reformatting, small enough that a marker on one control
# cannot excuse the next one.
_MARKER_WINDOW = 300


def settings_control_offenders(source: str) -> list[str]:
    """Controls in `source` that render without asking whether their field is locked.

    A pure function over source text so the coverage test below can drive synthetic controls
    through it. The walk that only ever ran against the real page was the walk that could not
    be asked what it saw.
    """
    offenders: list[str] = []
    pattern = "|".join(re.escape(o) for o in _CONTROL_OPENERS)
    for match in re.finditer(pattern, source):
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
        block = source[start:i]
        if "{...fieldProps(" in block:
            continue
        if _EXEMPT in source[max(0, start - _MARKER_WINDOW):start]:
            continue
        line = source.count("\n", 0, start) + 1
        offenders.append(f"{SETTINGS_PAGE.name}:{line}  {block.splitlines()[0].strip()}")
    return offenders


def test_every_settings_control_asks_the_server_whether_its_field_is_locked():
    """No control renders without `fieldProps`, which is where `id` and `disabled` both come
    from.

    This is the guard the review's finding earned. The gating was right for the three
    controls it had been wired onto and absent everywhere else, and nothing failed - the page
    looked gated, and a field the server refused was editable. `fieldProps` cannot be
    forgotten silently now: a control that skips it has no id either, so it is invisible to
    the page's own tests, and this walk names the line.
    """
    offenders = settings_control_offenders(SETTINGS_PAGE.read_text())
    assert not offenders, (
        "these controls render without asking whether their field is platform-tier, so a "
        "field the server refuses would be offered as editable:\n  " + "\n  ".join(offenders)
    )


# One of each kind the page actually builds. Parametrised over the kinds rather than written
# for the shapes I thought of - the same correction the declaration test below needed, and
# the one this walk failed: `<button` was missing while the comment said otherwise.
_KINDS = {
    "input": '<input {...fieldProps(\'sector\')} value={x} />',
    "select": '<select {...fieldProps(\'llm_mode\')}>\n<option value="a">a</option>\n</select>',
    "textarea": '<textarea {...fieldProps(\'discovery_brief\')} value={x} />',
    "TagInput": '<TagInput {...fieldProps(\'stakeholder_groups\')} value={x} onChange={f} />',
    "button-as-switch": (
        '<button type="button" role="switch" {...fieldProps(\'review_gates\')}\n'
        '  aria-checked={x} onClick={() => f()}>\n<span />\n</button>'
    ),
}


@pytest.mark.parametrize("kind", sorted(_KINDS))
def test_the_walk_sees_every_kind_of_control_this_page_builds(kind):
    """Each kind, gated and ungated, driven through the walk itself.

    The gated form must produce no offender and the ungated form must produce exactly one -
    both halves, because a walk that reported everything would also pass the first assertion
    of a one-sided test, and a walk that reported nothing would pass the second.
    """
    gated = _KINDS[kind]
    assert settings_control_offenders(gated) == [], (
        f"the walk reports a correctly gated {kind} as an offender"
    )

    ungated = gated.replace("{...fieldProps(", "{...notFieldProps(", 1)
    assert len(settings_control_offenders(ungated)) == 1, (
        f"the walk cannot see an ungated {kind} - it is invisible to this guard, which is "
        "how the force_local_inference toggle went unexamined"
    )


def test_an_exemption_marker_excuses_only_the_control_it_precedes():
    """The marker is scoped, so one exemption cannot shelter the control after it."""
    source = (
        "{/* not-a-settings-control: acts rather than edits */}\n"
        "<button type=\"button\" onClick={go}>Go</button>\n"
        + "\n" * (_MARKER_WINDOW + 50) +
        "<input value={x} />"
    )
    offenders = settings_control_offenders(source)
    assert len(offenders) == 1 and "<input" in offenders[0], (
        f"expected only the distant input to be reported, got {offenders}"
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


def _declared_settings_fields() -> dict[str, bool]:
    """Every field on `ProjectSettings` in types.ts, mapped to whether it is optional."""
    block = (UI / "types.ts").read_text()
    block = block[block.index("export interface ProjectSettings {"):]
    block = block[:block.index("\n}")]
    return {
        name: optional == "?"
        for name, optional in re.findall(r"^\s{2}(\w+)(\??):", block, re.M)
    }


def test_the_declaration_walk_reads_the_interface():
    """Guard the guard. An empty mapping would excuse every field below, and the assertions
    that follow are all of the form "this field is not missing and not optional" - which two
    empty sets satisfy perfectly."""
    declared = _declared_settings_fields()
    assert declared.get("llm_mode") is False, "the walk cannot see a required field"
    assert declared.get("client_name") is True, "the walk cannot see an optional field"


def _typescript_defaults() -> dict[str, object]:
    """`DEFAULTS` in Settings.tsx, as a dict of the literal values it holds.

    Only the literal scalars and empty arrays are read - anything else raises rather than
    being guessed at, because a default this walk silently skipped would be a default nothing
    holds equal to anything.
    """
    source = SETTINGS_PAGE.read_text()
    block = source[source.index("const DEFAULTS: ProjectSettings = {"):]
    block = block[block.index("{") + 1:block.index("\n}")]

    values: dict[str, object] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("*") or line.startswith("/*"):
            continue
        name, _, raw = line.partition(":")
        raw = raw.strip().rstrip(",").strip()
        if raw in ("true", "false"):
            values[name.strip()] = raw == "true"
        elif raw == "[]":
            values[name.strip()] = []
        elif raw.startswith("'") and raw.endswith("'"):
            values[name.strip()] = raw[1:-1]
        elif re.fullmatch(r"-?\d+", raw):
            values[name.strip()] = int(raw)
        else:
            raise AssertionError(
                f"DEFAULTS.{name.strip()} is {raw!r}, which this walk cannot read. Either "
                "write it as a literal or teach this function the shape - do not leave a "
                "default that nothing compares."
            )
    return values


def test_the_frontend_defaults_are_the_models_defaults():
    """`DEFAULTS` in Settings.tsx equals `ProjectSettings`'s own defaults, field by field.

    Load-bearing, and this branch made it more so. `get_project_settings` returns the raw
    `config_json`, so a field absent from a project's stored config is filled in from
    `DEFAULTS` and sent on the next save - while `_refuse_platform_tier_setting_changes`
    compares the submitted body against the **Pydantic** default. The two agree today and
    nothing held them there.

    If they drift, the failure is asymmetric and neither half is loud. A `project_admin`'s
    save of a field they never touched becomes a 403 naming a field they have never heard of.
    An `org_admin`'s is accepted, and silently rewrites that field to the frontend's idea of
    its default - which for `dev_mode` means the outbound-mail hold, and for
    `force_local_inference` means where this engagement's prompts go.

    Compared only over the fields `DEFAULTS` actually declares: it is not required to carry
    every settings field (the branding fields are absent by design, and the page renders them
    with their own `??` fallbacks). What it may not do is declare one and disagree.
    """
    from api.models import ProjectSettings

    model = ProjectSettings(sector="").model_dump()
    disagreements = {
        name: (value, model[name])
        for name, value in _typescript_defaults().items()
        if name in model and model[name] != value
    }
    assert not disagreements, (
        "ui/src/pages/Settings.tsx's DEFAULTS disagree with api/models.py's ProjectSettings "
        f"defaults - {{field: (typescript, python)}} {disagreements}. An unloaded or "
        "partially-stored field is sent from the first and judged against the second."
    )


def test_every_platform_tier_field_has_a_frontend_default():
    """A platform-tier field missing from `DEFAULTS` is sent as `undefined` and dropped from
    the JSON body entirely - which is the dropped-key hazard this whole task is about,
    arriving through the defaults rather than through the type."""
    defaults = _typescript_defaults()
    missing = [f for f in _PLATFORM_TIER_SETTINGS if f not in defaults]
    assert not missing, (
        f"{missing} are platform-tier and absent from Settings.tsx's DEFAULTS, so a save made "
        "before the settings load - or of a project whose config never stored them - omits "
        "them, and an omitted key is the server's default rather than the project's value"
    )


@pytest.mark.parametrize("field", sorted(_typescript_defaults()))
def test_every_field_the_page_promises_to_send_is_declared_required(field):
    """`DEFAULTS` is the Settings page's promise that a field travels on **every** save; the
    type is what makes that promise survive a refactor. A field named by one and not the other
    rides the untyped `{ ...DEFAULTS, ...settings }` spread alone.

    Parametrised over `DEFAULTS` rather than over the fields anybody thought of, because that
    is exactly how this hazard has already been missed twice: `force_local_inference` was
    closed and `dev_mode` was found undeclared **one field over**, and `interviewer_selection`
    and `interview_accent` were then found undeclared with no control at all - the second of
    them silently resetting a Scottish engagement to british on any unrelated save.

    Optional is refused as firmly as absent, and for a sharper reason: `tsc` has nothing to say
    about an omitted optional key, so `interview_accent?: string` looks like a declaration,
    passes the compiler, and drops on the first typed body anybody builds. `locale` was in
    exactly that state and is now required.

    Wider than `_PLATFORM_TIER_SETTINGS`, which the test above is keyed on, and deliberately:
    the two new fields are **not** platform-tier - they decide the tone of a conversation, not
    where this engagement's material is sent - so that tuple could never have covered them.
    """
    declared = _declared_settings_fields()
    assert field in declared, (
        f"Settings.tsx sends {field} on every save and ui/src/types.ts does not declare it on "
        "ProjectSettings, so it survives only as an untyped extra key the object spread "
        "happens to copy. An omitted key is the model default on the server, not the value "
        "the project holds."
    )
    assert not declared[field], (
        f"{field} is declared optional on ProjectSettings. Optional is how a field goes "
        "missing - tsc says nothing about an omitted optional key, and the server then reads "
        "its own default over whatever the project had chosen."
    )


@pytest.mark.parametrize("field", ["interviewer_selection", "interview_accent"])
def test_the_interview_programme_settings_are_carried_by_the_defaults(field):
    """Named, and the naming is the point.

    The test above is keyed on `DEFAULTS` itself, so it is blind to a field being taken *out*
    of `DEFAULTS` - remove the entry and the declaration together and nothing complains,
    because the parametrisation simply shrinks. That is the one direction a walk over its own
    input cannot see, and these two are the fields that were found in exactly that state:
    real on the server, absent from the page, absent from the type, carried only by an
    untyped spread.

    They are the only two named here because they are the only two this branch found there.
    A third belongs on this list only with the same evidence behind it.
    """
    assert field in _typescript_defaults(), (
        f"{field} has been removed from Settings.tsx's DEFAULTS. It is a real ProjectSettings "
        "field with a control on this page, and dropping it from the defaults also drops it "
        "from the test above, which is parametrised over them."
    )
