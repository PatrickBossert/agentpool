# api/services/interview_keyterms.py
"""The words a project uses about itself, assembled for the speech recogniser.

A general-purpose recogniser has never heard of the client, its programmes or its value
chain, so the terms that matter most in an interview are the ones it is least likely to get
right - a client name comes back as an ordinary English word that sounds like it, and the
answer reads as nonsense to whoever analyses it afterwards. Deepgram takes a list of terms to
bias towards; this builds that list **from the engagement**, so no two projects send the same
one and nothing here names a client.

Two sources, and they are different kinds of evidence:

  `value_chain_ledger.label`  - the project's own registry of what it does. An id means one
                                activity for the life of the project, so a label is as close
                                to a declared vocabulary as this system has. Taken whole.
  the `interview_scripts`     - ordinary English carrying the occasional proper noun. Taken
  artefact                      by extraction, never whole: boosting "How" and "the" boosts
                                nothing, because boosting everything is the same as boosting
                                nothing.

Both halves are pure functions over text so the rules can be driven directly rather than
through a database and a file - the repair CLAUDE.md prescribes every time a guard's reach
has turned out to be described rather than established.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

# A vocabulary of everything boosts nothing, and the list travels in a WebSocket URL that also
# carries a JWT. A hundred terms is roughly three kilobytes encoded, comfortably inside every
# URL limit, and far more project vocabulary than one interview can use.
MAX_KEYTERMS = 100

# A ledger label is the project's own words, but a *sentence* is not a term. Anything longer
# than this is prose that happened to be filed as a label, and biasing towards a whole sentence
# tells the recogniser nothing it can act on.
MAX_TERM_WORDS = 8
MAX_TERM_CHARS = 80

# A single boosted word has to be long enough to be distinctive. Acronyms are the exception and
# are the most valuable terms on the list - SPT, SPD, RIIO - so they get their own, lower floor.
MIN_WORD_CHARS = 5
MIN_ACRONYM_CHARS = 3

# A safety net, not the mechanism. The mechanism is positional: a capitalised word at the start
# of a sentence is capitalised because it starts a sentence, so a *lone* one is never taken.
# These are the words that survive that rule by appearing capitalised mid-sentence, and they say
# nothing about any engagement.
_TOO_COMMON = frozenset({
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "English", "British", "European", "Internet", "Company", "Limited", "Group",
})

# A sentence ends at . ! ? or a line break. Script text is assembled from many separate fields -
# a welcome message, a question, a probing instruction - and each of those begins a sentence of
# its own, which is why the fields are joined with newlines before they get here.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|[\r\n]+")

# A word, possibly hyphenated or carrying digits (RIIO-T3, ED2), possibly possessive.
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9&'’\-]*")

_ACRONYM = re.compile(r"^[A-Z][A-Z0-9\-]{1,}$")


def _is_capitalised(word: str) -> bool:
    return word[:1].isupper()


def _strip_possessive(term: str) -> str:
    return re.sub(r"['’]s$", "", term).strip("-'’&")


def _acceptable(term: str) -> bool:
    """Is this worth sending to the recogniser as a term?"""
    term = term.strip()
    if not term or len(term) > MAX_TERM_CHARS:
        return False
    words = term.split()
    if len(words) > MAX_TERM_WORDS:
        return False
    if len(words) > 1:
        # A multi-word phrase is distinctive by being a phrase; the per-word floors do not apply.
        return any(len(w) >= MIN_ACRONYM_CHARS for w in words)
    word = words[0]
    if word in _TOO_COMMON:
        return False
    if _ACRONYM.match(word):
        return len(word) >= MIN_ACRONYM_CHARS
    return len(word) >= MIN_WORD_CHARS and any(c.isalpha() for c in word)


def terms_in_prose(text: str) -> list[str]:
    """Proper nouns and acronyms in ordinary prose, most frequent first.

    The rule is **positional, not a word list**. Every sentence capitalises its first word, so a
    capitalised run that begins a sentence and is one word long is discarded outright - that is
    what removes "How", "What", "Please" and "Thank" without anybody having to list them. A run
    of two or more capitalised words is kept wherever it sits, because ordinary English does not
    capitalise two words in a row, and a lone capitalised word is kept when it appears
    mid-sentence, because nothing but a proper noun puts it there.

    The cost of the rule is stated rather than hidden: a proper noun that only ever opens a
    sentence is missed. That is the safe direction - a missing term costs one word's accuracy,
    a junk term costs a place on a capped list.
    """
    counts: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    order: dict[str, int] = {}

    for sentence in _SENTENCE_SPLIT.split(text or ""):
        words = [(m.group(0), m.start()) for m in _WORD.finditer(sentence)]
        index = 0
        while index < len(words):
            if not _is_capitalised(words[index][0]):
                index += 1
                continue
            run_start = index
            while index < len(words) and _is_capitalised(words[index][0]):
                index += 1
            run = [w for w, _ in words[run_start:index]]
            # Sentence-initial and alone: it is capitalised because the sentence started.
            if run_start == 0 and len(run) == 1:
                continue
            term = _strip_possessive(" ".join(run))
            if not _acceptable(term):
                continue
            key = term.casefold()
            counts[key] += 1
            if key not in first_seen:
                first_seen[key] = term
                order[key] = len(order)

    return [
        first_seen[key]
        for key, _ in sorted(counts.items(), key=lambda kv: (-kv[1], order[kv[0]]))
    ]


def build_keyterms(labels: Iterable[str], script_text: str) -> list[str]:
    """The project's vocabulary: its registry labels first, then its scripts' proper nouns.

    Registry labels lead because they are declared rather than inferred - a node label *is* what
    an id means for the life of the project, so it is the one vocabulary this system can be sure
    belongs to the engagement. Script terms follow in order of how often the scripts use them.

    Deduplicated case-insensitively, keeping the first spelling seen, and capped. The order is
    total and derived from the inputs alone, so two calls on the same project answer the same
    list - a recogniser configured differently on each question would be worse than one
    configured on none.
    """
    chosen: list[str] = []
    seen: set[str] = set()

    def take(term: str) -> None:
        term = " ".join((term or "").split())
        if not _acceptable(term):
            return
        key = term.casefold()
        if key in seen:
            return
        seen.add(key)
        chosen.append(term)

    for label in labels:
        take(label)
    for term in terms_in_prose(script_text):
        take(term)

    return chosen[:MAX_KEYTERMS]


def harvest_strings(value: object) -> list[str]:
    """Every string anywhere in a decoded JSON document, in document order.

    The scripts artefact is a map of title to script, and a script carries text in a dozen
    named places - welcome message, framing, section titles, question text, probing
    instructions, closing message - which change as Maya's output changes. Naming the fields
    here would make this file a second declaration of that shape, free to fall behind the
    first; harvesting every string cannot.
    """
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(harvest_strings(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(harvest_strings(item))
    return found
