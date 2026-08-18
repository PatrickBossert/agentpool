# tests/test_retired_integrations.py
"""Chainlit and n8n are retired, and nothing may quietly bring either back.

The guard the brief asked for, and it is cheap because a retirement fails in a particular way:
not at the point of removal, which the suite catches, but weeks later when a file that was
never touched turns out to import a module that no longer exists, or a settings key is read
that no longer has a default. Two slices on this project have already spent their review budget
on exactly that shape.

Every check reads the working tree rather than the import graph. An import-based guard can only
see modules something already imports, which is precisely the set that cannot be broken - the
file nobody imports is the one that rots. Documentation is exempt: the specs and plans are a
record of what was built and when, and rewriting history to hide a retired integration would
make the record useless. This module and `docs/` are therefore the only places the names may
appear, plus the sentences that say the integrations are gone, which are enumerated below.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

_SEARCHED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".sh", ".yml", ".yaml", ".toml", ".txt"}
_SKIPPED_DIRECTORIES = {
    ".git", "venv", ".venv", "node_modules", "__pycache__", ".pytest_cache",
    "data", "docs", "dist", "build", ".superpowers", ".worktrees", ".pids",
}

# Files allowed to name a retired integration, and what they are allowed to say about it. Each
# is a place where the *absence* is the subject: the guard itself, the tests that assert the
# absence, and the four modules that explain to a reader why something is missing. Listing them
# by name rather than exempting a directory keeps the exemption reviewable - a new file cannot
# join by being in the right folder.
_EXPLAINS_THE_ABSENCE = {
    "tests/test_retired_integrations.py",
    "tests/test_human_input.py",
    "tests/test_registry.py",
    "tests/test_crew_charter.py",
    "tests/test_agent_egress.py",
    "tests/test_data_architecture_page.py",
    "agents/tools/human_input.py",
    "agents/tools/registry.py",
    "agents/egress.py",
    "agents/charter.py",
    "api/services/data_architecture_service.py",
    "ui/src/pages/Architecture.tsx",
    "ui/src/pages/DataArchitecture.tsx",
    "start.sh",
    "stop.sh",
    "docker-compose.yml",
    ".gitignore",
    "CLAUDE.md",
    "README.md",
}

# The names that must not reappear. `slack_channel` and `slack_handle` are deliberately absent:
# both are project and stakeholder data that outlived the integration, and matching on a bare
# "slack" would catch them - see the report, which records `slack_channel` as a setting nothing
# now reads.
RETIRED_NAMES = {
    "chainlit": re.compile(r"chainlit", re.IGNORECASE),
    "ChainlitHumanInputTool": re.compile(r"ChainlitHumanInputTool"),
    "hitl_tool": re.compile(r"\bhitl_tool\b"),
    "SlackNotifyTool": re.compile(r"SlackNotifyTool"),
    "n8n": re.compile(r"n8n", re.IGNORECASE),
    "N8N_WEBHOOK_URL": re.compile(r"N8N_WEBHOOK_URL"),
    "n8n_webhook_url": re.compile(r"n8n_webhook_url"),
}


def _searched_files() -> list[Path]:
    found: list[Path] = []
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIPPED_DIRECTORIES for part in path.relative_to(REPO).parts):
            continue
        if path.suffix in _SEARCHED_SUFFIXES or path.name in {"Caddyfile", ".env.example", ".gitignore"}:
            found.append(path)
    return found


@pytest.mark.parametrize("name", sorted(RETIRED_NAMES))
def test_no_source_file_names_a_retired_integration(name):
    """One parametrisation per name, so a reintroduction says which one it is.

    The failure message carries the file and the line, because the useful half of this guard is
    not that it fails but that it tells the next person where the reference came back.
    """
    pattern = RETIRED_NAMES[name]
    files = _searched_files()
    assert files, "no files were searched - this guard has stopped exercising anything"

    offenders: list[str] = []
    for path in files:
        relative = str(path.relative_to(REPO))
        if relative in _EXPLAINS_THE_ABSENCE:
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()[:120]}")

    assert not offenders, (
        f"{name} is retired and these still name it:\n  " + "\n  ".join(offenders)
    )


def test_the_search_would_actually_find_something():
    """Guard the guard: the file walk and the patterns both have to work.

    Without this, a `_SKIPPED_DIRECTORIES` entry that swallowed the repository, or a suffix set
    that matched no file, would make every test above pass by searching nothing - the shape of
    a vacuous green this project has recorded more than once. Asserted against a file the
    exemption list names, so it exercises the exemption too.
    """
    files = _searched_files()
    relative = {str(path.relative_to(REPO)) for path in files}

    assert "agents/tools/human_input.py" in relative
    assert "ui/src/pages/DataArchitecture.tsx" in relative
    assert "docker-compose.yml" in relative
    assert len(files) > 200, f"only {len(files)} files searched - the walk is not reaching the tree"

    exempt = (REPO / "agents" / "tools" / "human_input.py").read_text()
    assert RETIRED_NAMES["n8n"].search(exempt), (
        "the module that explains the retired notification no longer mentions n8n, so the "
        "pattern above is matching nothing and every test in this file is vacuous"
    )


def test_the_modules_the_integrations_lived_in_are_gone():
    """Stated as paths, because a guard on names alone would pass on an orphaned file.

    A module nothing imports and nothing names is invisible to the search above: it would be
    skipped only by luck of its own contents. These are the four the retirement removed.
    """
    for relative in (
        "chainlit_app",
        "agents/tools/chainlit_human_input.py",
        "agents/tools/slack_notify.py",
        "workflows",
    ):
        assert not (REPO / relative).exists(), f"{relative} is back"


def test_no_declared_tool_class_is_missing_from_the_registry():
    """The two deletions held against each other, at the layer that would break.

    `agents/egress.py` declares one entry per tool class on disk and `tool_map` names the ones
    an agent holds. Removing `SlackNotifyTool` had to happen in both, and a removal in one alone
    fails somewhere less obvious - the declaration would raise `KeyError` mid-render on the
    privacy page, or the coverage guard would report an undeclared tool. This says it directly.
    """
    from agents.egress import TOOL_EGRESS, tool_classes_on_disk
    from agents.graph import build_graph

    held = {tool for node in build_graph().agents.values() for tool in node.tools}

    assert "SlackNotifyTool" not in TOOL_EGRESS
    assert "SlackNotifyTool" not in tool_classes_on_disk()
    assert "SlackNotifyTool" not in held
    assert "ChainlitHumanInputTool" not in TOOL_EGRESS
    assert "ChainlitHumanInputTool" not in tool_classes_on_disk()


def test_the_settings_object_has_no_webhook_url_left_on_it():
    """`api/config.py` is read through `get_settings()`, so the field's removal is asserted on
    the instance rather than on the class source - a `model_config` that accepted extras would
    otherwise let `settings.n8n_webhook_url` keep resolving from a stale `.env`."""
    from api.config import get_settings

    settings = get_settings()
    assert not hasattr(settings, "n8n_webhook_url")
