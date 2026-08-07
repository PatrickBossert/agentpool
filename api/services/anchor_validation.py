# api/services/anchor_validation.py
"""Checks on where Casey's themes anchor. Pure: themes and registry in, warnings out.

Two kinds of finding, and the second is the one that matters. A per-theme mismatch is an
individual mistake. A distribution skew is the signature of the bias this whole design
exists to remove - and when it happens, no individual theme looks wrong. Every L3 anchor
can be perfectly defensible while the set is badly skewed. Per-item validation cannot catch
an emergent property; only looking at the population can.
"""
from __future__ import annotations

# Starting values, not derived ones. Stated in one place each so the implementation does not
# invent its own, and so they can be tuned once evidence exists rather than by argument.
L3_SKEW_THRESHOLD = 0.70
L3_SKEW_MIN_THEMES = 5
SKEW_RERAISE_DELTA = 0.10

# A theme naming any of these is about how the organisation governs itself, which is an L0
# or L1 conversation whatever activity prompted it.
_GOVERNANCE_TERMS = ("governance", "assurance", "compliance", "accountability", "oversight")


def _levels(registry: dict) -> dict[str, str]:
    return {
        str(a["id"]): str(a.get("level", ""))
        for a in (registry.get("activities") or [])
        if isinstance(a, dict) and a.get("id") is not None
    }


def _is_governance(theme: dict) -> bool:
    text = f"{theme.get('theme', '')} {theme.get('description', '')}".casefold()
    return any(term in text for term in _GOVERNANCE_TERMS)


def validate_theme_anchors(themes: list, registry: dict) -> list[dict]:
    """Warnings about where this set of themes anchors.

    An empty registry accepts anything - a project with no value chain yet must not be
    blocked, and there is nothing to judge an anchor against.
    """
    levels = _levels(registry)
    warnings: list[dict] = []
    l3_only = 0
    counted = 0

    for theme in themes or []:
        if not isinstance(theme, dict):
            continue
        counted += 1
        tid = str(theme.get("id", ""))
        anchors = [str(a) for a in (theme.get("anchors") or [])]

        if levels:
            unknown = [a for a in anchors if a not in levels]
            if unknown:
                warnings.append({
                    "subject": tid, "code": "unknown_anchor", "measure": None,
                    "detail": (
                        f"theme {tid} anchors to {', '.join(sorted(unknown))}, which "
                        f"{'are' if len(unknown) > 1 else 'is'} not in the registry. An "
                        f"anchor that resolves to nothing cannot carry the theme "
                        f"downstream."
                    ),
                })

        known = [levels[a] for a in anchors if a in levels]
        if known and all(lvl == "L3" for lvl in known):
            l3_only += 1

        if theme.get("kind") == "vertical" and known and all(
            lvl not in ("L0", "L1") for lvl in known
        ):
            warnings.append({
                "subject": tid, "code": "anchor_level_mismatch", "measure": None,
                "detail": (
                    f"theme {tid} is vertical - about maturity within a discipline - but "
                    f"anchors only at {', '.join(sorted(set(known)))}. Maturity is judged "
                    f"at L0 or L1; anchored lower it cannot be ranked across the chain."
                ),
            })
        elif _is_governance(theme) and known and all(lvl == "L3" for lvl in known):
            warnings.append({
                "subject": tid, "code": "anchor_level_mismatch", "measure": None,
                "detail": (
                    f"theme {tid} is about governance or assurance but anchors only at L3. "
                    f"A governance theme hung on a single activity is one nobody can act on "
                    f"at governance level."
                ),
            })

    if counted >= L3_SKEW_MIN_THEMES:
        proportion = l3_only / counted
        if proportion > L3_SKEW_THRESHOLD:
            warnings.append({
                "subject": None, "code": "l3_skew", "measure": round(proportion, 4),
                "detail": (
                    f"{l3_only} of {counted} themes ({proportion:.0%}) anchor exclusively "
                    f"at L3. Individually each may be sound; as a set this skews the value "
                    f"propositions built from them toward L3 efficiency, losing the "
                    f"governance, functional and decision altitudes entirely."
                ),
            })
    return warnings
