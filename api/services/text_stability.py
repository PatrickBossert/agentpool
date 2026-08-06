# api/services/text_stability.py
"""Is this a refinement of the same thing, or a different thing?

Alex rebuilds the whole value chain on every run - step 0 reads the registry only to
preserve ids, then he re-ingests every document and re-emits all ~78 labels from scratch.
Typographic drift is therefore inevitable, not exceptional: on 6 August one run turned
'x' into 'x', an en dash into a hyphen, an em dash into a hyphen and an arrow into the word
"to", all while meaning exactly the same thing.

Treating those as redefinitions is what blocked the registry for two days. Treating them as
identical is what lets the one real change through - the same run dropped the pound sign
from 'Capital & Revenue Financial Control (£350M)'.

So: normalise how text is typed, never what it says. Currency symbols, ampersands, digits
and words all survive normalisation; only the characters a writer would consider
interchangeable are folded together.
"""
from __future__ import annotations
import re
import unicodedata

# Characters that differ only in how they were typed. Deliberately narrow - every entry
# here is a pair a person would read aloud identically.
_FOLD = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-",  # hyphen, non-breaking, figure, en
    "—": "-", "―": "-", "−": "-",                  # em, horizontal bar, minus
    "×": "x",                                                # multiplication sign
    "‘": "'", "’": "'", "‛": "'",                  # single quotes
    "“": '"', "”": '"',                                 # double quotes
    "…": "...",                                              # ellipsis
    " ": " ", " ": " ", " ": " ", " ": " ",   # spaces
}

# An arrow and the word it is read as. Folded to a single token so "Reactive -> Data-Led"
# and "Reactive to Data-Led" compare equal.
_ARROWS = ("→", "⟶", "⇒", "->", "=>")


def normalise_typography(text: str) -> str:
    """The text as it would be read aloud: typography folded, meaning untouched."""
    s = unicodedata.normalize("NFKC", str(text))
    for src, dst in _FOLD.items():
        s = s.replace(src, dst)
    for arrow in _ARROWS:
        s = s.replace(arrow, " to ")
    s = re.sub(r"[\s\-]+", " ", s)      # dashes and runs of space both collapse to one space
    return s.strip().casefold()


def is_substantive_change(old: str, new: str) -> bool:
    """True when the two strings mean different things, not merely look different.

    An empty side is never substantive: a missing label is a gap for another check to
    report, not a redefinition.
    """
    if not str(old).strip() or not str(new).strip():
        return False
    return normalise_typography(old) != normalise_typography(new)
