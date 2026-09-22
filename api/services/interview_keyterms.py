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
#
# **This bound is about the URL, and the URL was never the binding constraint.** It reads as
# though it settles how much vocabulary may be sent, and it does not - see the token budget
# below, which is the one Deepgram actually enforces and which binds first on every real corpus
# measured so far. Both are kept because they bound different things: a project whose terms are
# all acronyms spends few tokens and could otherwise send thousands of them.
MAX_KEYTERMS = 100

# **Deepgram's own limit, and it is a limit on tokens rather than on terms.** Exceeding it is
# answered `Keyterm limit exceeded. The maximum number of tokens across all keyterms is 500.`
# with HTTP 400 - https://developers.deepgram.com/docs/keyterm, read 17 September 2026.
#
# On a **streaming** connection that 400 lands on the handshake, so the browser never gets an
# open socket and cannot read the status: it sees `error` then `close`, `openDeepgramSocket`
# answers `null`, and two of those in a row latch Deepgram off for the rest of the interview.
# Nothing is transcribed, nothing appears in the provider's usage, and the interview completes
# on the browser's recogniser reporting success. That is not hypothetical - it is what the live
# `sp-gs-am` vocabulary did, at an estimated 918 tokens against this 500.
DEEPGRAM_KEYTERM_TOKEN_LIMIT = 500

# What is actually spent, and the gap is the point rather than timidity.
#
# Deepgram does not document its tokeniser, and its own issue tracker carries a user asking what
# a token is and getting no answer (deepgram-python-sdk#503), so `estimate_keyterm_tokens` below
# is an estimate of something unpublished. An estimate that runs *under* the truth buys a
# silently dead recogniser, which is the failure this whole constant exists to stop; one that
# runs over costs a few terms off the end of a list that is already ordered by value. The
# headroom is which of those two a wrong guess becomes.
#
# It also lands where Deepgram's own guidance points - the documentation recommends focusing on
# "the most important 20-50 terms", and this budget spends on about thirty-three of the live
# corpus's.
KEYTERM_TOKEN_BUDGET = 350

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

    The rule is **positional, not a word list**. Every sentence capitalises its first word, so
    the first word of a capitalised run that *begins* a sentence is dropped and the rest of the
    run kept - that is what removes "How", "What", "Please" and "Thank" without anybody having
    to list them, and it is what stops "If ISS", "Does GS UK" and "Before I" reaching the
    recogniser. A run of two or more capitalised words is kept whole wherever else it sits,
    because ordinary English does not capitalise two words in a row, and a lone capitalised word
    is kept when it appears mid-sentence, because nothing but a proper noun puts it there.

    **This applied to lone words only until sp66's final review**, and the docstring claimed the
    general rule while the code implemented the special case: 16 of the 100 slots on the live
    `sp-gs-am` scripts were openers glued to the name beside them, and keyterm prompting biases
    towards the literal phrase, so each was worse than useless.

    The cost of the rule is stated rather than hidden, and the fix moved it by one word: a
    multi-word name that **only ever** opens a sentence arrives one word short - "SP Energy
    Networks" as "Energy Networks" - because nothing positional can tell that from "If
    Iberdrola". That is still the safe direction, a missing word against a junk term holding a
    place on a capped list, and the same name used once mid-sentence is picked up whole.
    """
    counts: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    order: dict[str, int] = {}

    # **A word this corpus also writes in lower case is an ordinary word**, whatever a sentence
    # did to its first letter. Corpus-driven rather than a stopword list, for the reason this
    # module already gives about vocabulary: a list of English words committed here is a second
    # declaration free to rot, and one tuned to this client's prose would be worse.
    #
    # It earns its place under a cost-ordered budget. Previously the junk sat at the tail of a
    # list nothing reached; now cheap terms are taken first, so "Thank", "Assess", "Identify",
    # "Surface" and "Quantify" - all of which appear lower case in these very scripts - would be
    # bought *ahead* of the labels. Measured on the live corpus: 1,023 prose candidates, of which
    # these are among the cheapest.
    #
    # One exemption: a multi-word run, which is already strong evidence - ordinary English does
    # not capitalise two words in a row mid-sentence.
    #
    # **There was a second, for ALL-CAPS tokens, and it was wrong.** The reasoning was that an
    # acronym's lower-case form is a different word, so `SAP` and `ISO` needed protecting from
    # the test. Measured on the live corpus, the test protects them by itself: not one of SAP,
    # ISO, KPI, TCO, PMO, DVSA, ICE, RIBA, ROI, GRC, TUPE or ISS appears in lower case anywhere
    # in it, while NOT, WHAT, HOW, AND and WHEN - which the scripts capitalise in headings -
    # all do. The exemption admitted exactly those five and nothing else, and under cost
    # ordering they are one token each and bought **first**: five of the cheapest slots spent
    # on words the recogniser has never once got wrong. An exemption that protects nothing it
    # was written for is a way in for what it was not.
    lowercased = {m.group(0).casefold() for m in _WORD.finditer(text or "") if m.group(0).islower()}

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
            # **The first word of a sentence is capitalised because the sentence started**, so
            # it is dropped from whatever run it opens - not only when it is the whole run.
            #
            # That was the rule as written and it was applied to `len(run) == 1` alone, which
            # left every question beginning "If ISS...", "Does GS UK...", "Before I..." handing
            # the recogniser the opener glued to the name beside it. Keyterm prompting biases
            # towards the literal phrase, so "If ISS" boosts nothing *and* takes a place on a
            # capped list: 16 of the hundred slots on the live sp-gs-am scripts.
            #
            # A run of one leaves nothing behind and is skipped exactly as before.
            if run_start == 0:
                run = run[1:]
            if not run:
                continue
            term = _strip_possessive(" ".join(run))
            if not _acceptable(term):
                continue
            if len(run) == 1 and term.casefold() in lowercased:
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


def estimate_keyterm_tokens(term: str) -> int:
    """A deliberate **over**-estimate of what one term costs against Deepgram's 500.

    Deepgram publishes the limit and not the tokeniser, so this cannot be exact and must not try
    to be: the two directions of error are not symmetric. Under-counting sends a request that is
    refused on the handshake, which reaches a participant as an interview transcribed by a
    recogniser that has never heard of the client and reaches an operator as nothing at all.
    Over-counting drops a term or two off the end of a list already ordered by value.

    So it counts the way the most granular plausible tokeniser would: every run of letters and
    digits costs a token per four characters, and every punctuation mark costs one of its own -
    which is what a byte-pair tokeniser does with `(GS UK)` and with `EV-Specific`. A bare word
    never costs less than one.

    Pure, and driven directly, so what it claims about a term is checkable without a socket.
    """
    pieces = [p for p in re.split(r"[^0-9A-Za-z]+", term) if p]
    punctuation = sum(1 for c in term if not c.isalnum() and not c.isspace())
    return punctuation + sum(max(1, -(-len(p) // 4)) for p in pieces) or 1


def build_keyterms(labels: Iterable[str], script_text: str) -> list[str]:
    """The project's vocabulary, cheapest terms first so the budget buys the most of it.

    **Ordered by token cost, not by source, and that is a correction.** Registry labels used to
    lead outright, on the reasoning that declared vocabulary outranks inferred - which is sound
    about *provenance* and is the wrong question. Keyterm prompting biases the recogniser
    towards a literal phrase, so what matters is whether a term is **spoken and misheard**.

    Measured on the live `sp-gs-am` corpus, 22 September 2026: the 350-token budget was spent
    entirely on **33 registry labels averaging 10.6 tokens each**, and one of them costs as much
    as five proper nouns. Nobody says *"Regulatory Compliance and Record Retention (Asbestos and
    Statutory)"* out loud; the interviewee says *Fraikin*, *Tririga*, *FRACAS*, *DVSA* and *SAP*
    constantly, and the recogniser mangles every one. All five were dropped by that ordering,
    and three of them are among the four words the owner reported mangled after a real interview.

    So terms are taken cheapest-first, with the source used only to break ties in favour of the
    declared vocabulary. A long label still gets in if the budget reaches it - it is simply no
    longer allowed to spend five short terms' worth of budget ahead of them.

    Deduplicated case-insensitively, keeping the first spelling seen, and **bounded twice**: by
    the number of terms, which is about the URL, and by an estimated token count, which is about
    Deepgram's `500 tokens across all keyterms`. The second binds first on every real corpus
    measured, and it is the one whose absence killed transcription outright.

    The order is total and derived from the inputs alone, so two calls on the same project answer
    the same list - a recogniser configured differently on each question would be worse than one
    configured on none.
    """
    # (cost, source_rank, position, term) - a total order over the inputs alone. `source_rank`
    # keeps a declared label ahead of an inferred term of the same price, so the original
    # principle survives wherever it costs nothing; `position` keeps the sort stable and makes
    # two calls on one project identical.
    candidates: list[tuple[int, int, int, str]] = []
    position = 0
    for rank, source in ((0, labels), (1, terms_in_prose(script_text))):
        for term in source:
            term = " ".join((term or "").split())
            if not _acceptable(term):
                continue
            candidates.append((estimate_keyterm_tokens(term), rank, position, term))
            position += 1
    candidates.sort()

    chosen: list[str] = []
    seen: set[str] = set()
    spent = 0
    for cost, _rank, _pos, term in candidates:
        key = term.casefold()
        if key in seen:
            continue
        if len(chosen) >= MAX_KEYTERMS:
            break
        # Skipped rather than ending the walk, so one expensive term cannot cost every cheaper
        # one behind it. Under a cost ordering that can only happen at the very end of the list,
        # but the guard is kept: it is what makes the bound safe whatever the order becomes.
        if spent + cost > KEYTERM_TOKEN_BUDGET:
            continue
        seen.add(key)
        spent += cost
        chosen.append(term)

    return chosen


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
