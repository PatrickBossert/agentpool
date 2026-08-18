# api/services/outbound_mail.py
"""The one place outbound mail is decided.

Every message this system sends leaves through `_post_to_resend` below, and every
message that belongs to a *project* leaves through `send_project_mail`, which reads
that project's `dev_mode` and decides the recipients. Anything that posts to
`api.resend.com/emails` from anywhere else is the defect this module exists to close -
`test_outbound_mail_seam.py` asserts that this file is the only one that does.

## Why the seam exists

`dev_mode` reads as "hold all outbound mail for this project". It covered two of the
five send paths, and the three it missed were the ones that email stakeholders rather
than the operator: the interview reminder sender, the transcript sender, and the
welcome email. The two it did cover each carried their own copy of the redirect and
their own dev-mode footer, which is how the other three came to be written without one -
there was no single thing to call.

`dev_mode` also defaults to true, so every project ships with mail notionally held.
Nothing sending looks exactly like the setting working, which is why the gap survived.

## One face per audience

The correspondent is resolved from the **audience**, not from whichever agent composed
the message. A participant who receives programme updates from one person, interview
requests from a second, and a thank-you from a third experiences the org chart rather
than a correspondent; so stakeholders and participants hear from whoever holds
stakeholder management, and project governance hears from PAM.

Both names are resolved through `agents/identity.py` at send time. The permanent
`agent_id` with a mutable display name exists precisely so that renaming either does not
break this - a hard-coded "Jordan" here would repeat the mistake `DEV_MODE_ADDRESS`
made in `pam_report_job`, which is also fixed here.

Separating the correspondent from the composer means the seam owns the identity while
any agent remains the author: `_notify` still writes the governance notices and
`REMINDER_TEMPLATES` still writes the reminders, and neither decides whose name is on
the envelope.

## Name and role: the two halves of a From line

RFC 5322 gives `From` two independent fields, and this module uses them as two different
kinds of thing:

    From: "Jordan Williams" <stakeholder-manager@taskreimagination.ai>

The **display name is the person** and is mutable - it is read from `agents/identity.py`
at send time, and it becomes settable per project in future work, so an engagement that
renames the stakeholder manager sends as `"Fiona Grant" <stakeholder-manager@...>`.

The **address is the role**, keyed on the permanent `agent_id` and never on the display
name. A reply reaches whoever does stakeholder engagement, not a particular person, which
is why the address must survive the agent being renamed, re-personed, or replaced - and
why a thread from a year ago still routes correctly. It is the same reason `accounts@`
and `admissions@` outlive the people behind them.

The consequence that matters operationally: **one mailbox per role, ever.** Two today.
Per-project display names add none, and a coding-agent crew would add one for the crew's
role rather than one per engagement.

The local part is the `agent_id` with underscores written as hyphens - `stakeholder_manager`
becomes `stakeholder-manager`, `pam` stays `pam`. Underscores are legal in a local part but
hyphens are what people expect to type, and mail providers vary in how happily they accept
an underscore. It is a **rule applied to the id**, not a table of ids to addresses: a second
registry is exactly what `agents/identity.py` exists to avoid, and one that could drift from
the ids it mirrors would put the wrong role on somebody's mail.

The domain is parsed out of `FROM_EMAIL` rather than configured separately, so a deployment
that moves domain moves every address with it and cannot half-move.

## No reply_to, and now not much of a gap

None is set, and a role address does not make one honest yet. Nothing can receive today:
the domain is not verified in Resend, there is no inbound routing, no mailbox, and no
threading token that could associate an arbitrary reply with a project and a person. A
`reply_to` pointing at an address that bounces is worse than none.

The scheme changes the shape of that gap, though. A reply goes to `From` by default, so
once the mailboxes exist a role-keyed `From` is *already* the right reply target and a
`reply_to` would only be needed to say something different. Inbound routing remains out of
scope here - this change makes the address scheme ready for it and nothing more.

Two correspondents rather than five is what makes inbound tractable when it is built -
two mailboxes, two triage jobs, one owner each.

## The name a participant recognises

A participant knows the engagement as "GS Asset Management", not as `sp-gs-am`. The slug is
an operator's handle - a filename, a database name, a URL segment - and a stakeholder has no
reason to meet it. `client_name` in `ProjectSettings` is the participant-facing name, and
this module heads participant mail with it: `"GS Asset Management - Your interview
transcript"`.

Composed here rather than at the call sites for the reason everything else in this module is:
the seam is the one place mail is composed, and a prefix applied at four call sites is a
prefix three of them will eventually be written without.

**Only participant mail is prefixed.** Governance mail goes to reviewers, approvers and
governors, who know the engagement by its internal name and act across several of them at
once - Pamela's daily report is already subject-lined `sp-gs-am status report - 18 Aug 2026`,
and that slug is the useful discriminator in that inbox rather than a leak. Platform mail has
no project at all, so it has no name to carry. `SUBJECT_PREFIXED_AUDIENCES` holds the
decision, so adding an audience does not silently opt it in.

**An empty `client_name` omits the prefix entirely** - the subject is sent exactly as
composed. That is the default for every project that exists today, so it is the common path
rather than an edge case, and the two alternatives are both worse:

- `"- Your interview transcript"` is what any unconditional `f"{name} - {subject}"` produces,
  and it looks like a bug to the person receiving it.
- Falling back to `project_registry.display_name` reads as the safe option and is the trap:
  `POST /projects` registers a new project with `display_name=req.client_slug`, so for every
  project created so far the registry name **is** the slug. That fallback would put
  `sp-gs-am - Your interview transcript` in front of a participant while looking like it
  had solved the problem.

Omitting it loses nothing a participant needs: the correspondent's name is on the `From`
line and the body says what the message is about.

## A reply that knows which project and which person it answers

Several engagements share one mailbox per role - that is the point of a role address - so a
reply arriving at `stakeholder-manager@` says nothing about which project or which person it
belongs to. The routing key travels in the address itself:

    From: "Jordan Williams" <stakeholder-manager+3sNq7kZ2vRt8fUwYbXcD1g@taskreimagination.ai>

A reply goes to `From` by default, so it lands on the plus-addressed form with no cooperation
from the sender and nothing to parse out of prose. The subject line was the other candidate and
is much weaker: subjects are edited, translated, truncated and prefixed with `Re:` by six
different clients, while an address is copied verbatim by all of them.

**The token is derived, not stored.** Two requirements pull against each other - the same
person must get the same address on every message, so a year-old reply still routes; and the
raw token must never be stored, so a copy of the database yields no working address. A random
token satisfies the second and fails the first, because a digest cannot be read back out to
rebuild an address. So the token is `HMAC(k, slug || stakeholder_id || issue)`, reproducible
from the key alone, and the database holds only its sha256 digest plus the state - live,
revoked, and which `issue` is current. Digest lookup is a single indexed equality, the same
property `invite_service` chose sha256 over bcrypt for and for the same reason: this resolves
on an unauthenticated inbound path.

`k` is derived from `JWT_SECRET` by one HMAC with a fixed label rather than being a setting of
its own. A second secret would have to have a default, and a default secret means anyone
holding this source can mint a working reply address for any project.

The consequence to know, and the trap inside it: **rotating `JWT_SECRET` changes what every
token derives to, while the digests already stored do not change.** Addresses already sent keep
routing - resolution is a digest lookup and knows nothing of the key - and each person's address
is re-keyed the next time they are written to, retiring their previous one at that moment. What
must not happen is the middle case: a mint that trusted the stored `issue`, re-derived under the
new key and returned the result without recording it would put a `From` address on somebody's
mail whose digest is in no row at all. Nothing would fail - the message sends, the participant
replies, and the reply is dropped as unknown. `mint_reply_token` compares the derived digest
against the stored one for exactly this.

What the token discloses, which is nothing: it is 128 bits of HMAC output, so a participant who
forwards their invitation tells the recipient neither the engagement's name nor its slug nor
who else is on it. Same rule as `[[account-existence-never-disclosed]]`, reached the same way.

**Removal.** The token is bound to the person on the project, not to any assignment they hold,
so retiring an assignment leaves it alone - a reply to last month's message must still reach
the right person even though the work that prompted it has been retired. Removal from the
project is different, and `resolve_reply_token` re-reads the stakeholder row every time rather
than trusting a hook in the delete path: `dev_mode` was a setting three send paths were written
without, and a revocation hook is the same shape of promise. `stakeholders.id` is `AUTOINCREMENT`,
so a removed id is never handed to somebody else and a stale token can only ever resolve to
nobody. `revoke_reply_token` is the separate, deliberate door for stopping an address that is
being abused; the next message to that person mints a fresh one.

**The constraint that rests on, stated as a constraint and not as a guarantee:** that
AUTOINCREMENT sequence lives in `data/<slug>.db`, and the digests live in `system.db`.
Nothing prunes `reply_tokens` - `svc_unregister_project` removes the registry row and leaves
them - so **deleting and recreating a project's database file restarts its stakeholder ids at
1 while the old digests survive**, and an address issued to the first person is then resolved
against a second one wearing their id. Nothing in the code prevents this, because nothing in
the code sees an `rm`. If a project database is ever deleted and rebuilt under the same slug,
its `reply_tokens` rows must go with it.

## The `Message-ID`, recorded before anything needs it

The whole scheme rests on inbound routing preserving the `+tag`, and some providers normalise
it away. That cannot be tested here - `taskreimagination.ai` is not a verified sender domain in
Resend, so nothing sends and nothing receives - so the fallback is prepared rather than
speculated about: `send_project_mail` records the provider's id for every message sent about a
named person, and `In-Reply-To` matched against `sent_messages` is the route if the assumption
turns out false. It has to start now, because the id of a message already sent cannot be
recovered later.

Recorded only for mail that names a stakeholder. Governance mail is addressed to a list of
reviewers rather than to one person, so there is no person for a reply to be about.

## The welcome email is not project correspondence

`send_platform_mail` exists for it. It emails a new *login*, not a stakeholder or a
governor, it carries no slug, and the account it announces may not belong to any
project at all. Consulting some project's `dev_mode` would mean inventing a project the
message does not have, and picking a correspondent would put a persona's name on
credentials the platform issued. It sends from `FROM_EMAIL` exactly as configured, name
and address both: no role owns it, so it carries no role address either, and `noreply@`
is the honest thing for a message nobody should answer. It still leaves through this
module, so the "one place that posts to Resend" property holds; it simply is not
redirected and is not signed by an agent.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
from email.utils import formataddr, parseaddr

import httpx

from agents.identity import AGENT_IDENTITY
from api.config import get_settings

log = logging.getLogger(__name__)

# The two audiences a project's mail can have, and the agent whose face it carries.
# Values are `agent_id`s from agents/identity.py - permanent keys, never display names.
STAKEHOLDERS = "stakeholders"
GOVERNANCE = "governance"

AUDIENCE_CORRESPONDENT: dict[str, str] = {
    STAKEHOLDERS: "stakeholder_manager",
    GOVERNANCE: "pam",
}

# The audiences whose subjects are headed with the project's participant-facing name.
# Membership rather than a rule applied uniformly: a governor reading across four
# engagements wants the slug they file by, and a participant must never see it. A new
# audience is opted in deliberately or not at all - see the module docstring.
SUBJECT_PREFIXED_AUDIENCES: frozenset[str] = frozenset({STAKEHOLDERS})


def correspondent_for(audience: str) -> str:
    """The `agent_id` whose name appears on mail to this audience.

    Raises rather than defaulting: a new audience with no correspondent decided is a
    design question, and quietly picking one would put an arbitrary person's name on
    somebody's mail.
    """
    try:
        return AUDIENCE_CORRESPONDENT[audience]
    except KeyError:
        raise ValueError(
            f"no correspondent is defined for audience {audience!r} - "
            f"known audiences are {sorted(AUDIENCE_CORRESPONDENT)}"
        ) from None


def sending_domain() -> str:
    """The domain every project address is minted on, read from `FROM_EMAIL`.

    Parsed rather than configured separately so that a deployment cannot half-move: one
    setting names the domain, and a second setting that disagreed with it would send
    project mail from somewhere the operator had already stopped using.

    Raises when `FROM_EMAIL` carries no address. That is a misconfiguration under which
    nothing could send anyway - Resend rejects a malformed `from` - and the alternative is
    minting `stakeholder-manager@` with an empty domain and finding out from a 4xx.
    """
    address = parseaddr(get_settings().from_email)[1]
    # `rpartition` alone would answer the whole string when there is no `@` at all -
    # `parseaddr("TaskReimagination.ai")` returns exactly that - so the separator is
    # checked rather than only the tail.
    local, at, domain = address.rpartition("@")
    if not (local and at and domain):
        raise RuntimeError(
            f"FROM_EMAIL does not contain a sending domain: {get_settings().from_email!r}"
        )
    return domain


def role_address(audience: str) -> str:
    """The address mail to this audience is sent from, and replies to it would reach.

    Keyed on the correspondent's permanent `agent_id`, never on the display name: the
    address belongs to the role, and must not move when the person behind it is renamed
    or replaced. See the module docstring for why that is the whole point.

    Derived by rule - underscores become hyphens - rather than looked up in a table. A
    table of ids to addresses would be a second registry mirroring `agents/identity.py`,
    and this project has spent a week deleting those.
    """
    return f"{correspondent_for(audience).replace('_', '-')}@{sending_domain()}"


# 16 bytes of HMAC output, base64url with the padding stripped: 22 characters from
# [A-Za-z0-9_-], every one of them legal in a local part unquoted. 128 bits is far past
# guessable, and the length is what keeps `stakeholder-manager+<token>` at 42 characters
# against RFC 5321's 64-octet ceiling on a local part. The whole digest would spend 43 of
# those 64, which fits behind `stakeholder-manager` and does not fit behind
# `value_proposition_generator` - and the correspondent for a new audience is added to
# `agents/identity.py`, where nobody is counting characters.
_REPLY_TOKEN_BYTES = 16
_REPLY_TOKEN_CHARS = 22
_REPLY_TOKEN_RE = re.compile(rf"^[A-Za-z0-9_-]{{{_REPLY_TOKEN_CHARS}}}$")

# The label that separates the reply-token key from every other use of JWT_SECRET. A
# constant, and changing it retires every reply address in flight.
_REPLY_TOKEN_LABEL = b"agentpool/reply-token/v1"


def _reply_token_key() -> bytes:
    """The key reply tokens are derived under, one HMAC away from `JWT_SECRET`.

    Domain-separated rather than used directly, so that a reply token and a session
    signature are not two products of the same key: the reply token travels in plain text
    on the outside of an envelope, and a scheme where that value shares a key with the
    thing that authenticates a login is a scheme one implementation mistake away from
    being interesting. Derived rather than configured separately for the reason in the
    module docstring - a second secret needs a default, and a default secret is a forgeable
    address for every deployment that never changed it.
    """
    return hmac.new(
        get_settings().jwt_secret.encode(), _REPLY_TOKEN_LABEL, hashlib.sha256
    ).digest()


def _derive_reply_token(slug: str, stakeholder_id: int, issue: int) -> str:
    """The opaque token for this person, on this project, at this issue.

    NUL-separated rather than concatenated: `("ab", 1)` and `("a", 21)` would otherwise
    derive the same token from `"ab1"` and `"a21"`, and a slug is operator-supplied text.
    """
    message = f"{slug}\x00{stakeholder_id}\x00{issue}".encode()
    digest = hmac.new(_reply_token_key(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:_REPLY_TOKEN_BYTES]).rstrip(b"=").decode()


def _hash_reply_token(raw: str) -> str:
    """The digest stored for a reply token - see `invite_service` for why not bcrypt."""
    return hashlib.sha256(raw.encode()).hexdigest()


async def mint_reply_token(slug: str, stakeholder_id: int) -> str:
    """The reply token for this person on this project, minting one if there is none.

    **Idempotent while the token is live**, which is the property a thread depends on: the
    same person is written to from the same address every time, so a participant replying
    to a message from three months ago routes exactly as one replying to this morning's.

    A revoked pair is not resurrected. Minting past a revocation bumps `issue`, which
    derives a *different* token and overwrites the stored digest, so the revoked address
    stays dead and the person gets a new one. That is deliberate: the send path calls this
    on every message, and a mint that cleared `revoked_at` in place would quietly undo an
    operator's revocation with the next reminder.

    Does not check that the project or the stakeholder exists. A row for a person who is
    not there is inert - `resolve_reply_token` asks the project's own database - and a
    second existence check here would be a weaker copy of the one that can actually be
    trusted, on the path where a failure means mail does not go out.
    """
    from api.database import fetch_reply_token, get_system_connection, upsert_reply_token

    async with get_system_connection() as conn:
        row = await fetch_reply_token(
            conn, project_slug=slug, stakeholder_id=stakeholder_id
        )
        if row and row["revoked_at"] is None:
            raw = _derive_reply_token(slug, stakeholder_id, row["issue"])
            if _hash_reply_token(raw) == row["token_hash"]:
                return raw
            # The key has changed under us - `JWT_SECRET` was rotated - so the token this
            # row's `issue` now derives to is not the one whose digest is stored. Returning
            # it unrecorded would put a `From` address on somebody's mail that resolves to
            # nothing, silently, with no error anywhere: the send succeeds, the participant
            # replies, and the reply is dropped as unknown. Re-key at the same issue
            # instead, which retires the previous address at the moment a replacement is
            # actually issued rather than the moment the secret changed.
            await upsert_reply_token(
                conn,
                project_slug=slug,
                stakeholder_id=stakeholder_id,
                token_hash=_hash_reply_token(raw),
                issue=row["issue"],
            )
            return raw

        issue = (row["issue"] + 1) if row else 1
        raw = _derive_reply_token(slug, stakeholder_id, issue)
        await upsert_reply_token(
            conn,
            project_slug=slug,
            stakeholder_id=stakeholder_id,
            token_hash=_hash_reply_token(raw),
            issue=issue,
        )
    return raw


async def revoke_reply_token(slug: str, stakeholder_id: int) -> bool:
    """Stop this person's reply address routing. Returns whether one was live.

    The deliberate door, separate from removal: an address being abused is stopped without
    the person being taken off the engagement. The next message to them mints a fresh
    address, so revoking costs them nothing but the thread.
    """
    from api.database import get_system_connection, mark_reply_token_revoked

    async with get_system_connection() as conn:
        return await mark_reply_token_revoked(
            conn, project_slug=slug, stakeholder_id=stakeholder_id
        )


async def resolve_reply_token(raw: str) -> tuple[str, int] | None:
    """The project and person a reply token names, or None.

    **None is the only failure**, and it is the same None for every reason there is:
    malformed, never minted, revoked, project gone, person removed. A caller cannot tell
    an unknown token from one that was withdrawn yesterday, which is what stops the
    inbound endpoint becoming an oracle for which tokens exist.

    The stakeholder row is re-read on every resolution rather than being trusted from
    minting time, so removing somebody from a project stops their address without anything
    having to remember to say so. See the module docstring for why that is not a hook in
    the delete path.
    """
    from api.database import (
        fetch_project,
        fetch_reply_token_by_hash,
        fetch_stakeholder,
        get_connection,
        get_db_path,
        get_system_connection,
    )

    if not isinstance(raw, str) or not _REPLY_TOKEN_RE.match(raw):
        return None

    async with get_system_connection() as conn:
        row = await fetch_reply_token_by_hash(conn, token_hash=_hash_reply_token(raw))
    if row is None:
        return None

    slug, stakeholder_id = row["project_slug"], row["stakeholder_id"]
    try:
        if not get_db_path(slug).exists():
            return None
        async with get_connection(slug) as project_conn:
            project = await fetch_project(project_conn, slug=slug)
            if project is None:
                return None
            stakeholder = await fetch_stakeholder(
                project_conn, stakeholder_id=stakeholder_id, project_id=project["id"]
            )
    except Exception:
        # An unreadable project database is not a licence to route a reply into it.
        log.exception("reply token: could not read the project for %r", slug)
        return None
    if stakeholder is None:
        return None
    return slug, stakeholder_id


def reply_address(audience: str, token: str) -> str:
    """`role+token@domain` - the address a reply about one person arrives at."""
    local, _, domain = role_address(audience).partition("@")
    return f"{local}+{token}@{domain}"


def token_from_address(address: str) -> str | None:
    """The reply token in a recipient address, or None if it carries none.

    Lives beside the function that mints the address rather than in the inbound handler,
    which is the whole reason it is here: a parser written where the reply arrives is a
    second, independent statement of the same format, free to drift from the one that
    produced it. Task 3 calls this.

    Shape is checked, not just presence - a bare `stakeholder-manager@`, an empty tag, a
    tag of the wrong length or a tag carrying characters the derivation cannot emit all
    answer None, so a malformed address never reaches a digest lookup.
    """
    local = parseaddr(address or "")[1].partition("@")[0]
    _, plus, tag = local.partition("+")
    if not plus or not _REPLY_TOKEN_RE.match(tag):
        return None
    return tag


def sender_for(audience: str, reply_token: str | None = None) -> str:
    """`Display Name <role@domain>` for this audience's correspondent.

    The two halves are independent and are meant to be: the name is the person, read from
    the identity map on every send so renaming an agent stays a one-file change, and the
    address is the role, so renaming the agent does not move the mailbox.

    `reply_token` adds a third, independent thing to the address without moving the
    mailbox: the tag says which project and person a reply is about, and the part before
    the `+` is still the role, so mail continues to arrive in the one place the role's
    mail arrives. A message about nobody in particular carries no tag.

    `formataddr` rather than an f-string, because the display name is about to become
    project-settable: a name carrying a comma or a non-ASCII character has to be quoted or
    encoded, and hand-assembling the header would emit a `From` that splits into two
    recipients at the comma.
    """
    display = AGENT_IDENTITY[correspondent_for(audience)].display_name
    address = (
        reply_address(audience, reply_token) if reply_token else role_address(audience)
    )
    return formataddr((display, address))


def _normalise(addresses: list[str] | tuple[str, ...]) -> list[str]:
    """Strip, drop anything that is not an address, and de-duplicate in order.

    Resend rejects the whole request when one entry in `to` is malformed, so a single
    stray username would cost every other recipient their message. Order is preserved
    because the dev-mode footer quotes this list back and a stable order makes two runs
    comparable.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in addresses:
        addr = (raw or "").strip()
        if "@" not in addr:
            if addr:
                log.warning("discarding recipient %r: not an address", addr)
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(addr)
    return out


def _dev_mode_footer(intended: list[str]) -> list[str]:
    return [
        "",
        " - development mode - ",
        "dev_mode is enabled for this project, so this message was redirected to you.",
        "It would have gone to: " + (", ".join(intended) or "nobody"),
    ]


async def _project_config(slug: str) -> dict | None:
    """This project's `config_json`, or None when there is no readable project.

    None is deliberately distinct from `{}`: "there is no project here" and "the project
    has no settings" answer differently for `dev_mode`, which fails closed, and the caller
    must be able to tell them apart. Every failure - no database, no row, unreadable JSON -
    collapses to None, because from here they are the same fact.
    """
    # Imported here rather than at module scope: api.database imports a good deal of the
    # application, and this module is imported by routers that are themselves imported
    # during database setup.
    from api.database import fetch_project, get_connection, get_db_path

    try:
        if not get_db_path(slug).exists():
            log.warning("outbound mail: no database for %r", slug)
            return None
        async with get_connection(slug) as conn:
            project = await fetch_project(conn, slug=slug)
        if not project:
            log.warning("outbound mail: no project %r", slug)
            return None
        return json.loads(project.get("config_json") or "{}")
    except Exception:
        log.exception("outbound mail: could not read the config for %r", slug)
        return None


def config_holds_mail(config: dict | None) -> bool:
    """Whether this config's `dev_mode` is holding outbound mail.

    Fails closed in every direction it can fail. `dev_mode` lives inside `config_json`
    rather than as a column on `projects`, so an absent key reads as true; a slug with no
    database, or a read that raised - both of which arrive here as None - also read as
    true. Holding mail that should have gone out is recoverable; a live send to sixty real
    stakeholders is not.
    """
    if config is None:
        return True
    return bool(config.get("dev_mode", True))


def config_client_name(config: dict | None) -> str:
    """The participant-facing name of the engagement, or "" when there is none.

    Empty is a real answer and the common one - it is the shipped default - so it is
    returned rather than replaced by something that looks like a name. A whitespace-only
    setting is empty too: the field is free text on a settings form.
    """
    if config is None:
        return ""
    return str(config.get("client_name") or "").strip()


async def project_holds_mail(slug: str) -> bool:
    """Whether this project's `dev_mode` is holding outbound mail. See `config_holds_mail`."""
    return config_holds_mail(await _project_config(slug))


def compose_subject(audience: str, subject: str, client_name: str) -> str:
    """Head a participant-facing subject with the name the participant knows us by.

    Returns `subject` untouched for an audience that is not prefixed and for an engagement
    with no `client_name`. The second case is the default for every existing project, and
    the reason the empty check is here rather than at the caller: an unconditional
    `f"{client_name} - {subject}"` sends `"- Your interview transcript"`, which reads as a
    bug to the person holding it.

    The slug is not a parameter, and that is the point - there is nothing here that could
    fall back to it.
    """
    if audience not in SUBJECT_PREFIXED_AUDIENCES or not client_name:
        return subject
    return f"{client_name} - {subject}"


async def _post_to_resend(
    *, sender: str, to: list[str], subject: str, body: str
) -> str | None:
    """The only call to Resend in this codebase. Raises on failure.

    Returns the provider's id for the accepted message, or None when the response carried
    none. None is not a failure - the message went - so it must not be treated as one; it
    only means the `In-Reply-To` fallback has nothing to match this message on.
    """
    settings = get_settings()
    if not settings.resend_api_key:
        raise RuntimeError("RESEND_API_KEY is not configured")
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(
            "https://api.resend.com/emails",
            json={"from": sender, "to": to, "subject": subject, "text": body},
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Resend returned {resp.status_code}: {resp.text[:200]}")
    try:
        message_id = resp.json().get("id")
    except Exception:
        return None
    return str(message_id) if message_id else None


async def send_project_mail(
    *,
    slug: str,
    audience: str,
    to: list[str],
    subject: str,
    body: str,
    stakeholder_id: int | None = None,
) -> bool:
    """Send one project message. The one place a project's recipients are decided.

    `to` is what the caller *intends*; what is actually sent to is this function's
    decision. When the project holds mail, every intended recipient is replaced by the
    single redirect address and the message gains a footer naming the list it would have
    reached - which is what makes a redirected message readable rather than mysterious.

    `subject` is likewise what the caller composed; the participant-facing name in front of
    it is this function's, for the audiences that get one. The project is read once and
    both decisions are taken from that one read.

    `stakeholder_id` names the one person this message is *about*, and is what makes a
    reply to it routable: the sender address is plus-addressed with that person's reply
    token. Pass it for a message to a single participant and omit it for a message to a
    list, where there is no one person a reply could be about.

    It is deliberately not derived from `to`. An address is not an identity here -
    stakeholder ids restart at 1 in every project file, the same address can sit on two
    projects, and under `dev_mode` the recipient is the operator rather than the
    participant. A message held by `dev_mode` still carries the participant's token, so an
    operator reading it in the redirect mailbox sees the message that would have gone out.

    `slug` is required and is never defaulted. `project_llm_mode("")` finding no database
    and answering "standard" is how a sensitive project's answers reached a hosted model,
    and the same shape here would be a live send: a forgotten slug must not become
    "no project, so no hold".

    Returns True when a message was posted and False when there was nobody to send to.
    Raises whatever Resend or the transport raises - each caller already knows whether a
    failed notification may fail its operation, and this function must not decide that
    for them.
    """
    intended = _normalise(to)
    if not intended:
        # Redirecting nothing must not invent a recipient: a project with no eligible
        # audience sends no mail whether or not it holds mail.
        return False

    config = await _project_config(slug)

    if config_holds_mail(config):
        recipients = [get_settings().dev_mode_address]
        body = "\n".join([body, *_dev_mode_footer(intended)])
    else:
        recipients = intended

    reply_token = (
        await mint_reply_token(slug, stakeholder_id) if stakeholder_id is not None else None
    )

    message_id = await _post_to_resend(
        sender=sender_for(audience, reply_token),
        to=recipients,
        subject=compose_subject(audience, subject, config_client_name(config)),
        body=body,
    )

    if stakeholder_id is not None and message_id:
        # After the send, and never allowed to undo it: the message has gone, so a failure
        # to write the bookkeeping row costs the `In-Reply-To` fallback for this one
        # message and nothing else. Raising here would report a successful send as failed,
        # and the reminder sender would send it again.
        from api.database import get_system_connection, record_sent_message

        try:
            async with get_system_connection() as conn:
                await record_sent_message(
                    conn,
                    provider_message_id=message_id,
                    project_slug=slug,
                    stakeholder_id=stakeholder_id,
                )
        except Exception:
            log.exception("could not record the sent message id for %r", slug)
    return True


async def send_platform_mail(*, to: str, subject: str, body: str) -> bool:
    """Send one platform message - correspondence from the product, not from a project.

    No project mode is consulted and no correspondent signs it, because neither exists
    for this message; see the module docstring. It leaves through `_post_to_resend` like
    everything else, so the single-egress property still holds.

    Returns True when a message was posted, False when the address was unusable.
    """
    recipients = _normalise([to])
    if not recipients:
        return False
    await _post_to_resend(
        sender=get_settings().from_email, to=recipients, subject=subject, body=body
    )
    return True
