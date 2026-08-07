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


# Symbol-and-word pairs a reader treats as identical. Currency symbols expand to their code
# rather than vanishing: dropping "£" from "£350M" loses information, writing "GBP350M"
# does not, and only the first should be a finding.
_WORDS = {
    "&": " and ",
    "£": " gbp ", "$": " usd ", "€": " eur ", "¥": " jpy ",
    "%": " percent ",
    "+": " plus ",
    "@": " at ",
}


def normalise_typography(text: str) -> str:
    """The words and numbers, with punctuation discarded.

    Run 28 produced fifty-nine label changes against the registry and not one was a
    redefinition. Fifty-two were '&' becoming 'and'; the rest dropped a slash or a colon,
    turned '×' into 'x', or wrote 'GBP350M' for '£350M'. Alex regenerates every label on
    every run, so punctuation drift is what he does, and a check that fires on it produces
    fifty-nine false positives and no true ones.

    So: compare the token sequence. Two labels differ when their words or their numbers
    differ, never when only their punctuation does. '£350M' against '350M' still differs -
    the currency expands rather than disappearing - which is the one real defect this rule
    was written to catch.
    """
    s = unicodedata.normalize("NFKC", str(text))
    for src, dst in _FOLD.items():
        s = s.replace(src, dst)
    for arrow in _ARROWS:
        s = s.replace(arrow, " to ")
    s = s.casefold()
    for src, dst in _WORDS.items():
        s = s.replace(src, dst)
    # Letters and digits tokenise separately, so "GBP350M" and "£350M" agree once the
    # symbol has expanded - the space a symbol leaves behind must not itself be a
    # difference.
    tokens = re.findall(r"[a-z]+|[0-9]+", s)
    # "and" is a connector, not content. A slash carries it silently, an ampersand carries
    # it as a symbol, and Alex writes it as a word - "(Asbestos / Statutory)" and
    # "(Asbestos and Statutory)" name the same pair. "or" is deliberately NOT dropped: it
    # changes what a label claims.
    return " ".join(t for t in tokens if t != "and")


def is_substantive_change(old: str, new: str) -> bool:
    """True when the two strings mean different things, not merely look different.

    An empty side is never substantive: a missing label is a gap for another check to
    report, not a redefinition.
    """
    if not str(old).strip() or not str(new).strip():
        return False
    return normalise_typography(old) != normalise_typography(new)
