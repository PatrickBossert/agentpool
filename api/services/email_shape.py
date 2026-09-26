# api/services/email_shape.py
"""Does this string look like an address something could be delivered to?

**One declaration, deliberately, and it is not the first attempt at one.** The scope that
asked for this said there was *no* email validator anywhere in the product. There were two,
already disagreeing with each other:

  api/services/stakeholder_access.py   ^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$
  api/routers/interviews.py:698        ^[^@\\s]{1,64}@[^@\\s]{1,255}\\.[^@\\s]{1,63}$

so "add the first such check" would in fact have been the third copy of a rule that had
already drifted once. This module is the first one's regex, unchanged, with
`has_deliverable_email` delegating to it - so the stakeholder door and `ProjectCreate` cannot
come to disagree about what an approver's address is. `interviews.py`'s copy is left alone
and recorded as a finding rather than quietly widened: it guards an orphaned door (see
*Known issues* in CLAUDE.md) and its length bounds are a real, if unstated, decision that
tightening this one would reverse for every caller at once.

**What this deliberately does not do.** It is a shape check, not a deliverability check: no
DNS, no MX lookup, no provider call. A well-formed address at a domain that does not exist
passes here and bounces later. That is the whole of the claim, and the reason the claim is
worth making anyway is the failure it removes: a typo'd approver on a fresh engagement is a
dead end that *looks* closed - the stakeholder row is there, the role is set, the roster
renders - and nobody discovers it until a gate has been waiting for a day.

It is a pure function over a given string so it can be driven directly in both directions,
which is what CLAUDE.md's "a guard's reach must be established, not described" asks of a
guard. Nothing here reads a database, a setting, or a request.
"""
import re

# The address must have exactly one run of non-space, non-@ characters, then an @, then a
# domain carrying at least one dot with non-empty labels either side. Taken verbatim from
# stakeholder_access.py, where it had been the rule the stakeholder write doors enforce since
# sp41; moving it did not change what any existing caller accepts.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def looks_like_email(email: str) -> bool:
    """Whether `email` is non-blank and has the shape of an address.

    Leading and trailing whitespace is stripped before the match, because every caller here
    stores a stripped address and a check that accepted " a@b.c " while the column held
    "a@b.c" would be answering a question about a string nobody keeps.

    Tolerates a non-string (None from an absent JSON key, most often) by answering False
    rather than raising: every caller is asking "may I rely on this address?", and for a
    missing one the answer is no.
    """
    if not isinstance(email, str):
        return False
    return bool(_EMAIL_RE.match(email.strip()))
