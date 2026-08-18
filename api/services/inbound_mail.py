# api/services/inbound_mail.py
"""The first inbound surface in this application, and the only one that writes.

Every other endpoint here is reached by an operator holding a session or a participant
holding a link. This one is reached by a mail provider, over the public internet, with no
credential of any kind - and what it does with what it is handed is **write a participant's
words into a client engagement's database**. That combination is what the whole of this
module is arranged around, and it is worth naming plainly: an unverified endpoint of this
shape lets anyone who learns the URL put sentences in a client's mouth, on the record, in a
place a consultant will later read and act on.

**The signature closes half of that and is not the mitigation for the other half.** It proves
Resend posted the message; it says nothing about who wrote it. Possession of a reply address
is not authorship, and on this deployment those two come apart *today* rather than after the
domain verifies - see `sender_is_the_stakeholder`, which is why every reply carries its real
sender to the surface and a mismatch is shown rather than smoothed over.

## Nothing here has met a mail server

`taskreimagination.ai` is not a verified sender domain in Resend, so nothing sends and
nothing receives. Every payload this module has ever parsed was synthesised by
`tests/test_inbound_replies.py`, and every signature it has ever verified was made with a
test key. What is asserted is that this code does what it says with a payload of the shape
Resend documents; what is **not** asserted, and cannot be until the domain is verified, is
that Resend's payload has that shape.

Three assumptions are therefore recorded rather than built around:

1. **Inbound routing preserves the `+tag`** in the recipient address. The whole scheme
   rests on it, some providers normalise it away, and if it turns out false the fallback is
   `In-Reply-To` matched against `sent_messages` - which `send_project_mail` has been
   filling since Task 2 precisely so the fallback has data to work with. That match is
   deliberately **not** implemented here: whether the delivered `Message-ID` header equals
   Resend's response id, wraps it as `<id@domain>`, or is unrelated cannot be established
   without a verified domain, and a matcher written on a guess would either never fire or
   fire on the wrong message. `in_reply_to` is *stored* so that the question can be
   answered by looking at real traffic on the first day there is any.
2. **Resend permits arbitrary local parts on a verified domain.** Verification is
   per-domain, so this is likely; if it is false, no plus-addressed message ever goes out
   and this endpoint simply never has anything to route.
3. **The inbound event's `type` string.** This is the one where a guess would be actively
   harmful, and it is handled by not guessing - see "Why the event type is a deny-list".

## The order things happen in, which is the security property

1. **Bound the body before reading it.** A signature cannot be checked without the bytes,
   so "verify first" cannot literally mean "before reading" - and reading an unbounded body
   in order to verify it is itself the denial of service. `Content-Length` is checked, then
   the body is read and its real length checked again, because a chunked request carries no
   length to check.
2. **Verify the signature.** Before parsing, before any lookup, before anything touches a
   database. A request that fails here is refused with 401 and nothing else happens.
3. **Parse, resolve, store.** Only now, and only for content the provider signed.

An unsigned caller can distinguish 413 from 401 from 415, and that is accepted: those
answers are about our own limits, not about any address, token, account or engagement. The
disclosure the endpoint must not make is a different one, below.

## The endpoint is not an oracle

A verified payload gets exactly one answer - `{"status": "accepted"}`, 200 - whether the
token resolved to a live participant, named a project that has been deleted, named a person
who was removed from it yesterday, was revoked, was never minted, or was not there at all.
`resolve_reply_token` already collapses all of those to `None` (see `outbound_mail`), and
this module must not undo that by answering differently for any of them. The router returns
a module-level constant for this reason: a response assembled per-branch is a response that
grows a branch.

That is the same rule as `[[account-existence-never-disclosed]]`, applied to a different
identifier. Patrick stated it as a hard requirement rather than a preference, and it binds
status codes and timing as much as bodies.

**The residual, stated rather than hidden:** a token whose *shape* is wrong falls out at
`token_from_address` without a database lookup, while a well-formed one costs an indexed
equality on `reply_tokens` and, if that hits, two reads of a project file. So a very patient
attacker can distinguish "well-formed and known" from "well-formed and unknown" by timing.
Closing that would mean a constant-time path through two SQLite files, which is not
achievable here; what is achievable is that nothing *observable in the response* differs,
and that is what is asserted.

## Why the event type is a deny-list and never an allow-list

Resend posts outbound lifecycle events - `email.sent`, `email.delivered`, `email.bounced` -
to a webhook as well as inbound mail, and the inbound event's exact type string cannot be
confirmed from here. An allow-list built on a guess would drop **every real reply**,
silently, for ever, and would look exactly like "no one has replied yet". A deny-list of the
outbound types cannot make that mistake: an unknown type is treated as possibly-inbound and
has to earn its way in by carrying a resolvable token in a recipient field.

## Only recipient fields are scanned, and this is load-bearing

`from` and `reply_to` are never looked at. An outbound `email.delivered` event carries **our
own plus-addressed `From`** - `stakeholder-manager+<token>@` - so a scan that included it
would resolve our own message back to the participant it was sent to and file it as their
reply. Every message the system sent would arrive back as a reply from the person it was
written to. The deny-list above stops the events we know about; the recipient-only rule
stops the ones we do not.

## Governance replies have no route, and this records that rather than closing it

Only participant mail carries a `+tag`: `send_project_mail` mints one from
`stakeholder_id`, and governance mail is addressed to a list of reviewers with no single
person a reply could be about. So a governor who answers Pamela's daily report - and the
report does invite an answer - sends to a bare `pam@`. If inbound routing is configured for
that mailbox, the message reaches here, `token_from_address` returns None, and it is dropped
with a log line: **it is lost, quietly, and nobody is told.** If inbound routing is not
configured for it, it sits in an unread mailbox instead, which is the same outcome with a
different shape.

Closing it is a design question rather than a line of code, and it is not this task's: a
governance reply is about a *report*, not about a person, so the token would have to key on
something else - the run, the report, or the engagement - and that decision belongs with
whoever decides what PAM does with one. What is fixed here is that the failure is visible in
a log rather than invisible, and `test_a_message_carrying_no_tag_at_all_is_dropped` pins the
current behaviour so a future change to it is deliberate.

## What is accepted, and what is refused

| Bound | Value | Why |
|-------|-------|-----|
| Request body | 1 MiB | Enough for a long reply with quoted history; far below anything worth mounting an attack with. Refused with 413, before the body is read. |
| Content type | `application/json` only | Refused with 415, after the signature. |
| Stored body | 20 000 characters | A reply longer than that is a document, and the row records that it was cut. |
| Subject | 500 characters | |
| Attachments | **Never stored**, counted only | The count is what a reader needs in order to ask the sender for the file; storing arbitrary bytes from an unauthenticated caller is a different feature with a different threat model. |
| Recipients scanned | 50 addresses | A payload listing ten thousand recipients must not become ten thousand digest lookups. |
| Signature age | 5 minutes | Svix's own tolerance. A captured payload replayed later is refused. |

**Text only, never HTML.** `data.html` is reduced to text if there is no `data.text`, and
the markup is discarded rather than stored. Storing markup that a browser later renders is
how an unauthenticated endpoint becomes a way of running script in a consultant's session,
and the surface for this shows text.

**Nothing reaches a RAG store.** The knowledge-tier design makes writing to a project's
Chroma collections a deliberate act carrying authority for the destination tier, and a
webhook has none - no user, no role, and content that came from outside the engagement.
`test_inbound_replies.py` asserts this structurally, because "we did not call it" is a
property that a future edit adds a call to without noticing.

## Signature verification

Resend signs with Svix, which is the Standard Webhooks scheme: the signed content is
`{id}.{timestamp}.{body}`, HMAC-SHA256 under the secret's base64-decoded bytes, and the
`svix-signature` header carries one or more space-separated `v1,<base64>` entries so that a
secret can be rotated with both keys live. Implemented here in twenty lines rather than
taken as a dependency, because it is twenty lines and `svix` is not in `requirements.txt`.

**The verified message id is what dedupes.** `svix-id` is part of the signed content, so it
is the provider's word rather than the payload's, and Svix retries a delivery under the same
id - so a reply that arrived while the API was restarting is stored once rather than once
per retry. `inbound_replies.provider_event_id` is UNIQUE for that.

**An unset secret refuses everything.** Not "verification off": this is the one setting
whose absence has to close the door. It answers 503 rather than 401 so that an operator who
has just wired the webhook up in Resend's dashboard can tell "no secret configured here"
from "the secret does not match", which are two different repairs. That is a fact about our
own configuration and about no account, address or engagement.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import html as html_module
import logging
import re
import time
from collections.abc import Mapping
from email.utils import getaddresses, parseaddr

from api.config import get_settings
from api.services.outbound_mail import resolve_reply_token, token_from_address

log = logging.getLogger(__name__)

# See the table in the module docstring for why each of these is the number it is.
MAX_BODY_BYTES = 1_048_576
MAX_STORED_BODY_CHARS = 20_000
MAX_SUBJECT_CHARS = 500
MAX_IN_REPLY_TO_CHARS = 998
MAX_RECIPIENTS_SCANNED = 50
MAX_HEADERS_SCANNED = 200
SIGNATURE_TOLERANCE_SECONDS = 300

ACCEPTED_CONTENT_TYPE = "application/json"

# The recipient fields a reply's own address can appear in. `from` and `reply_to` are
# deliberately absent - see the module docstring; including them would file every message
# this system sends as a reply to itself.
_RECIPIENT_FIELDS = ("to", "cc", "bcc")
_RECIPIENT_HEADER_NAMES = frozenset({
    "to", "cc", "delivered-to", "x-original-to", "x-envelope-to", "envelope-to",
})

# Events that are certainly *not* a reply, because they are the provider telling us about
# mail we sent. A deny-list, never an allow-list: see the module docstring.
_OUTBOUND_EVENT_TYPES = frozenset({
    "email.sent", "email.scheduled", "email.canceled", "email.delivered",
    "email.delivery_delayed", "email.bounced", "email.complained", "email.failed",
    "email.opened", "email.clicked",
})

# Outcomes, for the log line and for tests. Never for a response body - every one of them
# is answered identically on the wire. See "The endpoint is not an oracle".
STORED = "stored"
DUPLICATE = "duplicate"
UNROUTABLE = "unroutable"
IGNORED = "ignored"


class InboundRefused(Exception):
    """A request refused before anything was stored. Carries the status to answer with."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ── Signature ────────────────────────────────────────────────────────────────


def _header(headers: Mapping[str, str], *names: str) -> str:
    """One header by any of its spellings, case-insensitively.

    Both the `svix-*` and the `webhook-*` spellings are accepted. They are the same scheme
    under two names - Svix publishes it as Standard Webhooks and emits either depending on
    how the endpoint was created - and an endpoint that understood only one would refuse
    every payload from a provider that had chosen the other, with no way to tell that from a
    wrong secret.
    """
    lowered = {str(key).lower(): value for key, value in headers.items()}
    for name in names:
        value = lowered.get(name)
        if value:
            return str(value).strip()
    return ""


def _secret_key(secret: str) -> bytes:
    """The signing key's bytes, from the `whsec_`-prefixed base64 the dashboard issues."""
    raw = secret[len("whsec_"):] if secret.startswith("whsec_") else secret
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise InboundRefused(503, "inbound mail is not configured") from None


def verify_signature(
    *,
    headers: Mapping[str, str],
    body: bytes,
    secret: str | None = None,
    now: float | None = None,
) -> str:
    """Check the provider's signature over this exact body. Returns the message id.

    Raises `InboundRefused` and stores nothing on any failure. The **id is returned rather
    than read again by the caller** because it is only trustworthy as a product of this
    function: it is part of the signed content, so a caller that fetched it from the headers
    itself would be trusting the same string for a different reason.
    """
    configured = get_settings().resend_webhook_secret if secret is None else secret
    if not configured:
        log.error(
            "inbound mail: RESEND_WEBHOOK_SECRET is not set, so every inbound request is "
            "refused. Nothing can be accepted until it is configured."
        )
        raise InboundRefused(503, "inbound mail is not configured")
    key = _secret_key(configured)
    if not key:
        log.error("inbound mail: RESEND_WEBHOOK_SECRET decoded to an empty key")
        raise InboundRefused(503, "inbound mail is not configured")

    message_id = _header(headers, "webhook-id", "svix-id")
    timestamp = _header(headers, "webhook-timestamp", "svix-timestamp")
    signatures = _header(headers, "webhook-signature", "svix-signature")
    if not (message_id and timestamp and signatures):
        raise InboundRefused(401, "unsigned request")

    try:
        sent_at = int(timestamp)
    except ValueError:
        raise InboundRefused(401, "unsigned request") from None
    if abs((time.time() if now is None else now) - sent_at) > SIGNATURE_TOLERANCE_SECONDS:
        # A captured payload replayed tomorrow carries a perfectly valid signature; the
        # timestamp is the only thing that makes it stale, and it is signed alongside the
        # body so it cannot be edited without breaking the signature.
        raise InboundRefused(401, "unsigned request")

    signed = message_id.encode() + b"." + timestamp.encode() + b"." + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()

    for entry in signatures.split():
        version, _, candidate = entry.partition(",")
        # Several entries are normal during a secret rotation, and an unknown version is
        # skipped rather than refused so that a future v2 alongside v1 does not break this.
        if version != "v1" or not candidate:
            continue
        if hmac.compare_digest(candidate, expected):
            return message_id
    raise InboundRefused(401, "unsigned request")


# ── Reading a payload ────────────────────────────────────────────────────────


def sender_is_the_stakeholder(from_address: str, stakeholder_email: str) -> bool:
    """Whether the person who wrote this is the person the token routed it to.

    **The token proves possession of an address, never authorship**, and the two come apart
    on the path this deployment is actually on today. `dev_mode` defaults to true and
    `send_project_mail` mints and stamps the reply token in *both* branches - deliberately,
    so an operator reading a held message sees the message that would have gone out - so
    every participant message currently lands in `DEV_MODE_ADDRESS` carrying a live routing
    token for a named client individual. An operator who hits Reply in that mailbox, or
    anyone a participant forwards to, resolves to that individual. The signature does not
    help: it proves Resend posted the message, never who wrote it.

    So the sender is compared and the answer travels with the row. It is not a refusal - a
    reply forwarded from a colleague's address is still worth reading, and dropping it would
    lose real correspondence - it is a caveat the surface must show, because the alternative
    is a consultant reading somebody else's words as a client's.

    Empty either side answers False. A stakeholder with no address on file cannot be
    confirmed as the author of anything, and "we could not check" must not present as "we
    checked and it matched".
    """
    from_key = parseaddr(from_address or "")[1].strip().lower()
    stakeholder_key = (stakeholder_email or "").strip().lower()
    return bool(from_key) and from_key == stakeholder_key


def _as_list(value: object) -> list[str]:
    """A header or address field as a list of strings, whichever shape it arrived in."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def recipient_addresses(data: Mapping[str, object]) -> list[str]:
    """Every address this message was addressed *to*, in the order they should be tried.

    Explicit fields first, then the raw headers, because a provider that normalises `to`
    may still carry the address the message was actually delivered to in `Delivered-To` or
    `X-Original-To` - which is the shape of the failure that would otherwise silently drop
    every reply.
    """
    raw: list[str] = []
    for field in _RECIPIENT_FIELDS:
        raw.extend(_as_list(data.get(field)))
    envelope = data.get("envelope")
    if isinstance(envelope, Mapping):
        raw.extend(_as_list(envelope.get("to")))

    headers = data.get("headers")
    if isinstance(headers, (list, tuple)):
        for header in list(headers)[:MAX_HEADERS_SCANNED]:
            if not isinstance(header, Mapping):
                continue
            name = str(header.get("name") or "").lower()
            if name in _RECIPIENT_HEADER_NAMES:
                raw.extend(_as_list(header.get("value")))
    elif isinstance(headers, Mapping):
        for name, value in list(headers.items())[:MAX_HEADERS_SCANNED]:
            if str(name).lower() in _RECIPIENT_HEADER_NAMES:
                raw.extend(_as_list(value))

    addresses: list[str] = []
    seen: set[str] = set()
    for _, address in getaddresses(raw):
        key = address.lower()
        if address and key not in seen:
            seen.add(key)
            addresses.append(address)
        if len(addresses) >= MAX_RECIPIENTS_SCANNED:
            break
    return addresses


_TAG_RE = re.compile(r"<[^>]*>")
_BLOCK_RE = re.compile(r"(?is)<(script|style)\b.*?</\1>")
_BREAK_RE = re.compile(r"(?i)<br\s*/?>|</p\s*>|</div\s*>|</tr\s*>")


def html_to_text(html: str) -> str:
    """A rough plain-text rendering, for a reply that carried no text part.

    Rough is the right level of effort. This is not a rendering engine; it exists so that a
    participant writing from a client that sends HTML only is read at all rather than
    arriving blank. The markup itself is discarded - see the module docstring on why none of
    it is stored.
    """
    text = _BLOCK_RE.sub(" ", html)
    text = _BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html_module.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def reply_body(data: Mapping[str, object]) -> tuple[str, bool]:
    """The text to store and whether it was cut short."""
    text = data.get("text")
    body = text.strip() if isinstance(text, str) and text.strip() else ""
    if not body:
        html = data.get("html")
        body = html_to_text(html) if isinstance(html, str) else ""
    if len(body) > MAX_STORED_BODY_CHARS:
        return body[:MAX_STORED_BODY_CHARS], True
    return body, False


def _in_reply_to(data: Mapping[str, object]) -> str:
    """The `In-Reply-To` header, stored and not yet acted on - see the module docstring."""
    value = data.get("in_reply_to")
    if not isinstance(value, str) or not value.strip():
        headers = data.get("headers")
        value = ""
        if isinstance(headers, (list, tuple)):
            for header in list(headers)[:MAX_HEADERS_SCANNED]:
                if isinstance(header, Mapping) and str(
                    header.get("name") or ""
                ).lower() == "in-reply-to":
                    value = str(header.get("value") or "")
                    break
        elif isinstance(headers, Mapping):
            for name, header_value in list(headers.items())[:MAX_HEADERS_SCANNED]:
                if str(name).lower() == "in-reply-to":
                    value = str(header_value or "")
                    break
    return value.strip()[:MAX_IN_REPLY_TO_CHARS]


async def _route(data: Mapping[str, object]) -> tuple[str, int] | None:
    """The project and person this message is addressed to, or None.

    None for every reason there is, and the caller may not learn which - see "The endpoint
    is not an oracle".
    """
    tried: set[str] = set()
    for address in recipient_addresses(data):
        token = token_from_address(address)
        # De-duplicated on the token rather than the address, because `To` and `Delivered-To`
        # routinely carry the same one: each distinct token costs a system-database
        # connection, and fifty addresses naming one token was fifty opens.
        if token is None or token in tried:
            continue
        tried.add(token)
        resolved = await resolve_reply_token(token)
        if resolved is not None:
            return resolved
    return None


async def store_inbound_reply(*, provider_event_id: str, payload: Mapping[str, object]) -> str:
    """File one verified webhook payload. Returns an outcome, for the log line only.

    The outcome is **never** put on the wire. Every one of them is answered with the same
    200 and the same body, which is what stops this endpoint reporting which reply tokens
    exist. It is returned because a webhook that silently does nothing is undiagnosable, and
    because the tests need to assert the distinction the response deliberately hides.
    """
    event_type = str(payload.get("type") or "")
    if event_type in _OUTBOUND_EVENT_TYPES:
        # Our own message coming back to us. It carries our plus-addressed `From`, so a
        # handler that scanned senders would file it as the recipient's own reply.
        log.info("inbound mail: ignoring outbound event %s", event_type)
        return IGNORED

    data = payload.get("data")
    if not isinstance(data, Mapping):
        data = payload if isinstance(payload, Mapping) else {}

    routed = await _route(data)
    if routed is None:
        # Deliberately says nothing about which token, in a log an operator shares.
        log.info(
            "inbound mail: %s carried no recipient address that resolves to a project and "
            "a person - dropped", provider_event_id,
        )
        return UNROUTABLE
    slug, stakeholder_id = routed

    body, truncated = reply_body(data)
    subject = str(data.get("subject") or "")[:MAX_SUBJECT_CHARS]
    attachments = data.get("attachments")
    attachment_count = len(attachments) if isinstance(attachments, (list, tuple)) else 0
    sender = ""
    from_addresses = getaddresses(_as_list(data.get("from")))
    if from_addresses:
        sender = from_addresses[0][1][:320]

    from api.database import fetch_project, get_connection, insert_inbound_reply

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if project is None:
            # resolve_reply_token already read this project; losing it between then and now
            # is a race, not a routing decision, and it is answered the same way.
            log.info("inbound mail: %s named a project that is gone", provider_event_id)
            return UNROUTABLE
        reply_id = await insert_inbound_reply(
            conn,
            project_id=project["id"],
            stakeholder_id=stakeholder_id,
            provider_event_id=provider_event_id,
            event_type=event_type,
            from_address=sender,
            subject=subject,
            body=body,
            truncated=truncated,
            attachment_count=attachment_count,
            in_reply_to=_in_reply_to(data),
        )
    if reply_id is None:
        log.info("inbound mail: %s was already stored - redelivery", provider_event_id)
        return DUPLICATE
    log.info(
        "inbound mail: stored reply %s on %s from stakeholder %s",
        reply_id, slug, stakeholder_id,
    )
    return STORED
