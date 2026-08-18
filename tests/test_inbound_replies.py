# tests/test_inbound_replies.py
"""A participant replies, and it reaches a human - through the first public write door here.

Every other endpoint in this application is reached by an operator holding a session or a
participant holding a link. `POST /api/inbound-mail/resend` is reached by a mail provider,
with no credential, and it writes a participant's words into a client engagement. So the
first half of this file is about refusing things, and it drives each refusal separately.

**Nothing here has met a mail server.** `taskreimagination.ai` is not a verified sender
domain in Resend, so nothing sends and nothing receives. Every payload below was synthesised
here and every signature was made with a test key. What is asserted is that this code does
what it says with a payload of the shape Resend documents; what is *not* asserted, and
cannot be until the domain is verified, is that Resend's payload has that shape - in
particular that inbound routing preserves the `+tag` at all. That assumption is recorded, in
this file's own docstring and in `api/services/inbound_mail.py`, rather than built around.

**The chain is driven whole, and each link is also driven alone.** `test_the_whole_chain_*`
starts at a real reminder send through the seam, reads the `From` address off the wire, posts
a reply addressed to exactly that address, and finishes by reading the reply back off the
project surface an operator uses. That is the only test here that would fail if the two ends
stopped meeting. The single-link tests around it exist because a shared resolver lets one
link's test cover another's, which has bitten this project twice.

**The refusals are asserted with the store, not only the status code.** A 401 that had
already written the row would satisfy any assertion about the response, so every refusal test
also asks the database what it holds.
"""
import base64
import hashlib
import hmac
import json
import shutil
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from api.config import get_settings
from api.services import inbound_mail, outbound_mail

SLUG = "ib-gs-am"
OTHER_SLUG = "ib-northbank"
_SLUGS = (SLUG, OTHER_SLUG)

CLIENT_NAME = "GS Asset Management"
PARTICIPANT = "harriet.okonkwo@example.test"
PARTICIPANT_NAME = "Harriet Okonkwo"
REMINDER_SUBJECT = "A quick reminder"

# A `whsec_`-prefixed base64 secret, the shape Resend's dashboard issues.
SECRET = "whsec_" + base64.b64encode(b"inbound-mail-test-signing-key").decode()
OTHER_SECRET = "whsec_" + base64.b64encode(b"a-different-signing-key-entirely").decode()


# ── Housekeeping ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean():
    """Remove this file's project databases and its rows in the shared system database.

    `DATABASE_DIR` is a fixed `/tmp/agentpool_test` that persists between runs, so a
    `reply_tokens` row outlives the project database it names. A leftover row would hand the
    second run a token minted at a different `issue` from the first - the poisoned-database
    trap CLAUDE.md describes, which is why this runs on both sides and is scoped to this
    file's slugs.
    """

    def _wipe():
        settings = get_settings()
        for slug in _SLUGS:
            for suffix in ("", "-wal", "-shm"):
                (Path(settings.database_dir) / f"{slug}.db{suffix}").unlink(missing_ok=True)
            project_dir = Path(settings.projects_dir) / slug
            if project_dir.exists():
                shutil.rmtree(project_dir)
        path = Path(settings.database_dir) / "system.db"
        if not path.exists():
            return
        conn = sqlite3.connect(str(path))
        try:
            for table in ("reply_tokens", "sent_messages"):
                if not conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone():
                    continue
                conn.executemany(
                    f"DELETE FROM {table} WHERE project_slug=?", [(s,) for s in _SLUGS]
                )
            conn.commit()
        finally:
            conn.close()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def secret(monkeypatch):
    """Configure the webhook secret for this test, as a deployment would."""
    monkeypatch.setattr(get_settings(), "resend_webhook_secret", SECRET)
    return SECRET


@pytest.fixture
def sent(monkeypatch):
    """Capture the outbound requests the seam actually builds, and return the list.

    Distinct provider ids per response, because `sent_messages` is keyed on them.
    """
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": f"ib-message-{len(captured)}"})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return httpx.AsyncClient(*args, **kwargs)

    monkeypatch.setattr(outbound_mail, "httpx", SimpleNamespace(AsyncClient=factory))
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_ib_test")
    return captured


# ── Building a signed request ────────────────────────────────────────────────

def sign(
    body: bytes,
    *,
    message_id: str = "msg_2ib_test",
    timestamp: int | None = None,
    secret_value: str = SECRET,
    over: bytes | None = None,
    content_type: str = "application/json",
) -> dict[str, str]:
    """Svix headers for this body. `over` signs different bytes - the tamper case."""
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    key = base64.b64decode(secret_value[len("whsec_"):])
    signed = message_id.encode() + b"." + stamp.encode() + b"." + (body if over is None else over)
    digest = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return {
        "svix-id": message_id,
        "svix-timestamp": stamp,
        "svix-signature": f"v1,{digest}",
        "content-type": content_type,
    }


def body_for(payload: dict) -> bytes:
    return json.dumps(payload).encode()


def inbound(recipient: str, **overrides) -> dict:
    """A payload of the shape Resend documents for an inbound message."""
    data = {
        "from": f"{PARTICIPANT_NAME} <{PARTICIPANT}>",
        "to": [recipient],
        "subject": f"Re: {CLIENT_NAME} - {REMINDER_SUBJECT}",
        "text": "Thursday afternoon suits me. Could we do 3pm?",
    }
    data.update(overrides)
    return {"type": "email.received", "created_at": "2026-08-18T09:00:00Z", "data": data}


async def deliver(client, payload: dict, *, headers: dict | None = None, **sign_kwargs):
    body = body_for(payload)
    return await client.post(
        "/api/inbound-mail/resend",
        content=body,
        headers=sign(body, **sign_kwargs) if headers is None else headers,
    )


# ── Fixture data ─────────────────────────────────────────────────────────────

async def _make_project(client, slug: str, **config_keys) -> None:
    r = await client.post(
        "/projects", json={"client_slug": slug, "llm_mode": "standard", "sector": "rail"}
    )
    assert r.status_code in (200, 201), r.text
    from api.database import fetch_project, get_connection

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        config = json.loads(project.get("config_json") or "{}")
        config.update({"dev_mode": False, "client_name": CLIENT_NAME, **config_keys})
        await conn.execute(
            "UPDATE projects SET config_json=? WHERE slug=?", (json.dumps(config), slug)
        )
        await conn.commit()


async def _set_config(slug: str, **keys) -> None:
    from api.database import fetch_project, get_connection

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        config = json.loads(project.get("config_json") or "{}")
        config.update(keys)
        await conn.execute(
            "UPDATE projects SET config_json=? WHERE slug=?", (json.dumps(config), slug)
        )
        await conn.commit()


async def _add_stakeholder(slug: str, name: str, email: str) -> int:
    from api.database import fetch_project, get_connection

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        cur = await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, project_role)"
            " VALUES (?,?,?,?)",
            (project["id"], name, email, "participant"),
        )
        await conn.commit()
        return cur.lastrowid


async def _participant(client, slug: str = SLUG, email: str = PARTICIPANT) -> int:
    await _make_project(client, slug)
    return await _add_stakeholder(slug, PARTICIPANT_NAME, email)


async def _approved_reminder(slug: str, stakeholder_id: int) -> None:
    from api.database import fetch_project, get_connection, insert_reminder_email

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        campaign = await conn.execute(
            "INSERT INTO campaigns (project_id, campaign_name) VALUES (?,?)",
            (project["id"], "Discovery"),
        )
        await conn.commit()
        email_id = await insert_reminder_email(
            conn, project_id=project["id"], campaign_id=campaign.lastrowid,
            stakeholder_id=stakeholder_id, subject=REMINDER_SUBJECT,
            body="Please complete your interview.", escalation_level="gentle",
        )
        await conn.execute(
            "UPDATE reminder_emails SET status='approved' WHERE id=?", (email_id,)
        )
        await conn.commit()


async def _send_reminders(slug: str) -> None:
    from api.services.campaign_service import send_reminder_emails_svc

    await send_reminder_emails_svc(slug)


async def _reply_address_from_the_wire(sent_requests: list[httpx.Request]) -> str:
    """The `From` address the seam actually put on the wire - what a reply would go to."""
    from email.utils import parseaddr

    return parseaddr(json.loads(sent_requests[0].content)["from"])[1]


async def _minted_address(slug: str, stakeholder_id: int) -> str:
    """A reply address for this person, without driving a send.

    Used only by the single-link tests. The chain test reads the address off the wire, which
    is the assertion that would actually fail if minting and sending stopped meeting.
    """
    token = await outbound_mail.mint_reply_token(slug, stakeholder_id)
    return outbound_mail.reply_address(outbound_mail.STAKEHOLDERS, token)


async def _stored(slug: str) -> list[dict]:
    from api.database import get_connection, get_db_path

    if not get_db_path(slug).exists():
        return []
    async with get_connection(slug) as conn:
        rows = await conn.execute_fetchall(
            "SELECT * FROM inbound_replies ORDER BY id"
        )
    return [dict(row) for row in rows]


# ── The chain, whole ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_whole_chain_from_a_sent_reminder_to_a_reply_on_the_surface(
    client, sent, secret,
):
    """Mint, send, reply arrives at the address that was sent from, resolve, store, surface.

    Deliberately not six tests. Minting, resolution, storage and the surface can each pass
    while the seam emits a plain role address and the endpoint parses one it was never sent -
    two ends that never meet is the failure this shape catches and no unit test of either end
    can see. Every link is *also* driven alone below, for the opposite reason.
    """
    stakeholder_id = await _participant(client)
    await _approved_reminder(SLUG, stakeholder_id)
    await _send_reminders(SLUG)

    reply_to = await _reply_address_from_the_wire(sent)
    assert "+" in reply_to, reply_to

    response = await deliver(client, inbound(reply_to))
    assert response.status_code == 200, response.text

    surfaced = await client.get(f"/projects/{SLUG}/inbound-replies")
    assert surfaced.status_code == 200, surfaced.text
    payload = surfaced.json()
    assert payload["unread"] == 1
    assert len(payload["replies"]) == 1
    reply = payload["replies"][0]
    assert reply["stakeholder_id"] == stakeholder_id
    assert reply["stakeholder_name"] == PARTICIPANT_NAME
    assert reply["body"] == "Thursday afternoon suits me. Could we do 3pm?"


# ── Link: the signature ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_unsigned_payload_is_refused_and_nothing_is_stored(client, secret):
    """The hole this endpoint would otherwise be: anyone who learns the URL writing into a
    client engagement. Asserted on the store as well as the status - a 401 returned after
    the row was written would satisfy a status-only test."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    response = await client.post(
        "/api/inbound-mail/resend",
        content=body_for(inbound(address)),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 401, response.text
    assert await _stored(SLUG) == []


@pytest.mark.asyncio
async def test_a_valid_signature_over_a_tampered_body_is_refused(client, secret):
    """The signature has to be over *these* bytes.

    A verifier that checked the header was well-formed, or signed the parsed object rather
    than the body, passes every other test in this file and fails only this one: the
    signature below is genuine, made with the real secret, over a different message.
    """
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    genuine = body_for(inbound(address, text="Thursday suits me."))
    tampered = body_for(inbound(address, text="Cancel the whole engagement."))

    response = await client.post(
        "/api/inbound-mail/resend", content=tampered, headers=sign(genuine, over=genuine)
    )

    assert response.status_code == 401, response.text
    assert await _stored(SLUG) == []


@pytest.mark.asyncio
async def test_the_signature_covers_the_bytes_that_arrived_not_the_json_they_mean(
    client, secret,
):
    """Found by power-checking, and it is the classic form of this defect.

    A verifier that signs `json.dumps(json.loads(body))` - the parsed object re-serialised,
    which is what "verify the payload" reads like - passes every other test in this file,
    because every payload here is produced by `json.dumps` and re-serialises to itself. The
    two bodies below mean the same thing and are different bytes, so only a verifier working
    on the bytes that actually arrived can tell them apart. It also parses before it
    verifies, which is the ordering this endpoint exists to get right.
    """
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    payload = inbound(address)
    compact = json.dumps(payload).encode()
    reformatted = json.dumps(payload, indent=2).encode()
    assert json.loads(compact) == json.loads(reformatted) and compact != reformatted

    response = await client.post(
        "/api/inbound-mail/resend", content=reformatted, headers=sign(compact, over=compact)
    )

    assert response.status_code == 401, response.text
    assert await _stored(SLUG) == []


@pytest.mark.asyncio
async def test_a_signature_made_with_another_secret_is_refused(client, secret):
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    body = body_for(inbound(address))

    response = await client.post(
        "/api/inbound-mail/resend", content=body, headers=sign(body, secret_value=OTHER_SECRET)
    )

    assert response.status_code == 401, response.text
    assert await _stored(SLUG) == []


@pytest.mark.asyncio
async def test_a_signed_payload_replayed_later_is_refused(client, secret):
    """The signature stays valid for ever; the timestamp is what goes stale, and it is
    signed alongside the body so it cannot be edited without breaking the signature."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    stale = await deliver(
        client, inbound(address),
        timestamp=int(time.time()) - inbound_mail.SIGNATURE_TOLERANCE_SECONDS - 60,
    )

    assert stale.status_code == 401, stale.text
    assert await _stored(SLUG) == []


@pytest.mark.asyncio
async def test_an_unset_secret_refuses_everything(client, monkeypatch):
    """Empty is not "verification off". It is the one setting whose absence must close the
    door, and it is what every deployment has today."""
    monkeypatch.setattr(get_settings(), "resend_webhook_secret", "")
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    body = body_for(inbound(address))

    response = await client.post(
        "/api/inbound-mail/resend", content=body, headers=sign(body)
    )

    assert response.status_code == 503, response.text
    assert await _stored(SLUG) == []


@pytest.mark.asyncio
async def test_the_standard_webhooks_header_spelling_is_accepted_too(client, secret):
    """Svix emits `svix-*` or `webhook-*` depending on how the endpoint was created. An
    implementation that understood one spelling would refuse every payload from a provider
    that chose the other, and it would look exactly like a wrong secret."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    body = body_for(inbound(address))
    headers = sign(body)
    renamed = {
        "webhook-id": headers["svix-id"],
        "webhook-timestamp": headers["svix-timestamp"],
        "webhook-signature": headers["svix-signature"],
        "content-type": "application/json",
    }

    response = await client.post("/api/inbound-mail/resend", content=body, headers=renamed)

    assert response.status_code == 200, response.text
    assert len(await _stored(SLUG)) == 1


@pytest.mark.asyncio
async def test_a_second_signature_beside_the_first_is_honoured(client, secret):
    """Svix sends several `v1,` entries during a secret rotation, and an unknown version
    alongside them is skipped rather than refused."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    body = body_for(inbound(address))
    headers = sign(body)
    headers["svix-signature"] = f"v2,not-a-signature {headers['svix-signature']}"

    response = await client.post("/api/inbound-mail/resend", content=body, headers=headers)

    assert response.status_code == 200, response.text
    assert len(await _stored(SLUG)) == 1


# ── Link: the endpoint is not an oracle ──────────────────────────────────────

@pytest.mark.asyncio
async def test_an_unresolvable_token_answers_exactly_as_a_resolvable_one(client, secret):
    """Byte for byte, and the same status. Anything that differed would make this endpoint a
    way of asking which reply tokens exist - `[[account-existence-never-disclosed]]` applied
    to a different identifier, and Patrick stated that as a hard requirement.

    The unknown token is well-formed: 22 characters from the derivation's own alphabet. A
    malformed one would fall out at the parser and prove less.
    """
    stakeholder_id = await _participant(client)
    known = await _minted_address(SLUG, stakeholder_id)
    unknown = outbound_mail.reply_address(outbound_mail.STAKEHOLDERS, "A" * 22)

    good = await deliver(client, inbound(known), message_id="msg_known")
    bad = await deliver(client, inbound(unknown), message_id="msg_unknown")

    assert good.status_code == bad.status_code == 200
    assert good.content == bad.content
    assert good.json() == {"status": "accepted"}
    # And the difference the response hides is real: only one of them was stored.
    assert len(await _stored(SLUG)) == 1


@pytest.mark.asyncio
async def test_a_reply_to_somebody_removed_from_the_project_is_dropped(client, secret):
    """`resolve_reply_token` re-reads the stakeholder row on every resolution rather than
    trusting a hook in the delete path, and this is the door that depends on it."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        await conn.execute("DELETE FROM stakeholders WHERE id=?", (stakeholder_id,))
        await conn.commit()

    response = await deliver(client, inbound(address))

    assert response.json() == {"status": "accepted"}
    assert await _stored(SLUG) == []


@pytest.mark.asyncio
async def test_a_reply_to_a_revoked_address_is_dropped(client, secret):
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    assert await outbound_mail.revoke_reply_token(SLUG, stakeholder_id) is True

    response = await deliver(client, inbound(address))

    assert response.json() == {"status": "accepted"}
    assert await _stored(SLUG) == []


@pytest.mark.asyncio
async def test_a_message_carrying_no_tag_at_all_is_dropped(client, secret):
    """The bare role address - and this is where governance replies currently go.

    Everything sent before Task 2 carries it, and so does **all governance mail today**:
    only participant mail is tagged, because a report addressed to a list of reviewers has
    no one person a reply could be about. A governor who answers Pamela's daily report, which
    invites an answer, lands here and is dropped with a log line.

    Pinned rather than fixed. Routing a governance reply means deciding what it is about -
    the run, the report, or the engagement - and that belongs with whoever decides what PAM
    does with one. This asserts the current behaviour so that changing it is deliberate.

    Driven for both correspondents, because a rule that happened to hold for one mailbox and
    not the other is exactly the gap this records.
    """
    await _participant(client)

    for audience in (outbound_mail.STAKEHOLDERS, outbound_mail.GOVERNANCE):
        response = await deliver(
            client,
            inbound(outbound_mail.role_address(audience)),
            message_id=f"msg_untagged_{audience}",
        )
        assert response.json() == {"status": "accepted"}
    assert await _stored(SLUG) == []


# ── Link: routing ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_reply_lands_on_the_project_that_minted_the_address_and_not_the_other(
    client, secret,
):
    """One mailbox serves every engagement, so "it was stored" is not the property - "it was
    stored *here*" is. Stakeholder ids restart at 1 in every project file, so both people
    below are id 1 and only the token tells them apart."""
    ours = await _participant(client, SLUG)
    theirs = await _participant(client, OTHER_SLUG, email="someone.else@example.test")
    assert ours == theirs == 1
    address = await _minted_address(OTHER_SLUG, theirs)

    await deliver(client, inbound(address))

    assert await _stored(SLUG) == []
    assert len(await _stored(OTHER_SLUG)) == 1


@pytest.mark.asyncio
async def test_our_own_delivery_notification_is_not_filed_as_the_participants_reply(
    client, secret,
):
    """Resend posts outbound lifecycle events to the same webhook, and this is the one shape
    the recipient-only rule cannot refuse on its own.

    A bounce or delivery report is *addressed back to the sender*, so our own plus-addressed
    address is in a recipient field rather than only in `from` - which is exactly what a
    reply looks like. Only the type deny-list tells them apart, and without it the system
    would file its own bounce notifications as replies from the people it failed to reach.

    Power-checking found this: with the address only in `from`, emptying `_OUTBOUND_EVENT_
    TYPES` changed nothing, because the recipient-only rule was doing all the work and the
    deny-list was asserting nothing.
    """
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    response = await deliver(client, {
        "type": "email.delivered",
        "data": {
            "from": address,
            "to": [address],
            "subject": REMINDER_SUBJECT,
            "text": "Delivered to harriet.okonkwo@example.test",
        },
    })

    assert response.json() == {"status": "accepted"}
    assert await _stored(SLUG) == []


@pytest.mark.asyncio
async def test_a_sender_that_happens_to_be_a_reply_address_is_still_not_scanned(
    client, secret,
):
    """The same rule, without the deny-list doing the work.

    The event type here is the inbound one, so only the recipient-field rule can refuse it.
    Without that separation, the deny-list test above would pass while `from` was scanned for
    every event whose type we do not recognise - which is every real inbound event, since the
    inbound type string is exactly what cannot be confirmed from here.
    """
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    response = await deliver(client, inbound(PARTICIPANT, **{"from": address}))

    assert response.json() == {"status": "accepted"}
    assert await _stored(SLUG) == []


@pytest.mark.asyncio
async def test_an_event_type_we_have_never_seen_is_still_routed(client, secret):
    """Deny-list, never allow-list.

    Resend's inbound event type cannot be confirmed without a verified domain. An allow-list
    built on a guess would drop every real reply for ever and look exactly like a quiet
    inbox; an unknown type has to earn its way in by carrying a resolvable token instead.
    """
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    payload = inbound(address)
    payload["type"] = "email.inbound.received.v2"
    await deliver(client, payload)

    assert len(await _stored(SLUG)) == 1


@pytest.mark.asyncio
async def test_the_address_is_found_in_delivered_to_when_to_was_rewritten(client, secret):
    """Some inbound routes rewrite `To` to the mailbox and keep the original elsewhere. If
    that is what Resend does, the `+tag` survives in `Delivered-To` and nothing else changes;
    if it strips it everywhere, `In-Reply-To` against `sent_messages` is the fallback and
    this endpoint stores that header from the first message for exactly that reason."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    await deliver(client, inbound(
        outbound_mail.role_address(outbound_mail.STAKEHOLDERS),
        headers=[{"name": "Delivered-To", "value": address}],
    ))

    rows = await _stored(SLUG)
    assert len(rows) == 1
    assert rows[0]["stakeholder_id"] == stakeholder_id


@pytest.mark.asyncio
async def test_a_redelivered_webhook_is_stored_once(client, secret):
    """Svix retries under the same message id when an endpoint is slow or restarting.
    Without the unique key, a reply that arrived during a deploy is read four times."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    first = await deliver(client, inbound(address), message_id="msg_retried")
    second = await deliver(client, inbound(address), message_id="msg_retried")

    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert len(await _stored(SLUG)) == 1


@pytest.mark.asyncio
async def test_the_dedupe_key_is_the_signed_id_and_not_the_payloads(client, secret):
    """`svix-id` is inside the signed content, so it is the provider's word. A dedupe key
    taken from the body would be a caller-supplied string, and a caller who could choose it
    could suppress a real reply by claiming an id that had already been used."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    await deliver(client, inbound(address, id="body-chosen-id"), message_id="msg_one")
    await deliver(client, inbound(address, id="body-chosen-id"), message_id="msg_two")

    assert len(await _stored(SLUG)) == 2


# ── Link: the bounds ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_oversized_body_is_refused(client, secret):
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    huge = inbound(address, text="x" * (inbound_mail.MAX_BODY_BYTES + 1))

    response = await deliver(client, huge)

    assert response.status_code == 413, response.status_code
    assert await _stored(SLUG) == []


async def _chunked_post(headers: dict[str, str], chunk: bytes, offered: int) -> tuple:
    """POST a chunked body, and report how many chunks were pulled off the wire.

    `httpx` sends an async iterator as `Transfer-Encoding: chunked` with no `Content-Length`,
    and its ASGI transport advances the iterator only when the application calls `receive` -
    so the number of chunks this generator yields *is* the number the application asked for.
    That is the measurement, and it is the one a test handing over complete bytes cannot make.
    """
    from httpx import ASGITransport, AsyncClient

    from api.main import app

    pulled = 0

    async def stream():
        nonlocal pulled
        for _ in range(offered):
            pulled += 1
            yield chunk

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as chunked_client:
        response = await chunked_client.post(
            "/api/inbound-mail/resend", content=stream(), headers=headers
        )
    return response, pulled


@pytest.mark.asyncio
async def test_a_chunked_body_is_stopped_while_it_is_still_arriving(secret):
    """The bound has to bound the *read*, not just the answer.

    The first version called `await request.body()` and checked `len(body)` afterwards.
    Starlette accumulates the whole stream with no cap of its own, so that proved the refusal
    and never the bound: a review drove this endpoint with a chunked request and got a 413
    after **512 MiB had been buffered**. A chunked request carries no `Content-Length` - the
    very case the length check was written for - so nothing fired until every byte was in
    memory, and it happens *before* signature verification, so the fail-closed 503 does not
    cover it either.

    The measurement is chunks pulled off the wire, because that is the property. A test that
    hands the function complete bytes asserts the 413 one layer from where it matters and
    passes against the defect.
    """
    chunk_size = inbound_mail.MAX_BODY_BYTES // 4
    response, pulled = await _chunked_post(
        {"content-type": "application/json"}, b"x" * chunk_size, offered=512
    )

    assert response.status_code == 413, response.text
    # Five chunks take the running total past the limit; the sixth is never asked for. The
    # ceiling is what matters: unbounded, this pulls all 512 - 128 MiB of them.
    assert pulled <= 6, pulled
    assert pulled * chunk_size <= inbound_mail.MAX_BODY_BYTES + chunk_size


@pytest.mark.asyncio
async def test_a_declared_oversize_is_refused_without_pulling_a_single_chunk(secret):
    """What the `Content-Length` pre-check is for, now that it is not pretending to be a
    bound. The streaming cap has to look before it can stop; this refuses an honest provider
    that declares an oversized body having read nothing at all.

    Reviewed as dead weight because removing it failed nothing - which was true, and the fix
    is a test rather than a deletion: the property is real and was simply unasserted.
    """
    response, pulled = await _chunked_post(
        {
            "content-type": "application/json",
            "content-length": str(inbound_mail.MAX_BODY_BYTES + 1),
        },
        b"x" * 1024,
        offered=512,
    )

    assert response.status_code == 413, response.text
    assert pulled == 0, pulled


@pytest.mark.asyncio
async def test_a_body_that_is_not_json_is_refused_after_the_signature(client, secret):
    body = b"this is not JSON at all"
    response = await client.post(
        "/api/inbound-mail/resend", content=body, headers=sign(body)
    )
    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_a_content_type_we_do_not_accept_is_refused(client, secret):
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    body = body_for(inbound(address))

    response = await client.post(
        "/api/inbound-mail/resend",
        content=body,
        headers=sign(body, content_type="text/html"),
    )

    assert response.status_code == 415, response.text
    assert await _stored(SLUG) == []


@pytest.mark.asyncio
async def test_a_very_long_reply_is_stored_shortened_and_says_so(client, secret):
    """Cut rather than refused: a participant who pastes a whole document has still replied,
    and the row records that what is shown is not the whole of it."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    await deliver(client, inbound(address, text="y" * (inbound_mail.MAX_STORED_BODY_CHARS + 500)))

    rows = await _stored(SLUG)
    assert len(rows[0]["body"]) == inbound_mail.MAX_STORED_BODY_CHARS
    assert rows[0]["truncated"] == 1


@pytest.mark.asyncio
async def test_attachments_are_counted_and_their_content_is_not_stored(client, secret):
    """Counted so a reader knows to ask for the file; not stored, because keeping arbitrary
    bytes from an unauthenticated caller is a different feature with a different threat
    model. The content is asserted absent from the whole row, not from one column."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    marker = "SECRET-ATTACHMENT-CONTENT"

    await deliver(client, inbound(address, attachments=[
        {"filename": "notes.pdf", "content": marker, "content_type": "application/pdf"},
        {"filename": "photo.png", "content": marker, "content_type": "image/png"},
    ]))

    rows = await _stored(SLUG)
    assert rows[0]["attachment_count"] == 2
    assert marker not in json.dumps(rows[0])


@pytest.mark.asyncio
async def test_a_reply_that_carried_only_html_is_stored_as_text(client, secret):
    """Read at all rather than arriving blank - and the markup is discarded, because this
    endpoint is unauthenticated and what it stores must not be something a browser will
    later render."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    await deliver(client, inbound(
        address,
        text="",
        html="<p>Thursday suits me.</p><p>Could we do 3&nbsp;pm?</p>"
             "<script>alert('x')</script>",
    ))

    rows = await _stored(SLUG)
    assert "Thursday suits me." in rows[0]["body"]
    assert "<p>" not in rows[0]["body"]
    assert "alert(" not in rows[0]["body"]


# ── Link: the surface ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_surface_names_who_actually_wrote_the_reply(client, secret):
    """The token proves possession of an address, never authorship, so the sender travels
    with the row and the surface shows it. `from_address` was stored and then dropped from
    the response, which left the panel attributing every reply to the stakeholder."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    await deliver(client, inbound(address))

    reply = (await client.get(f"/projects/{SLUG}/inbound-replies")).json()["replies"][0]
    assert reply["from_address"] == PARTICIPANT
    assert reply["sender_confirmed"] is True


@pytest.mark.asyncio
async def test_a_reply_from_the_dev_mode_mailbox_is_attributed_to_whoever_sent_it(
    client, sent, secret,
):
    """The reachable failure, driven the way it actually happens - today, not after the
    domain verifies.

    `dev_mode` defaults to true and `send_project_mail` mints and stamps the reply token in
    **both** branches, deliberately, so an operator reading a held message sees the message
    that would have gone out. So every participant message currently lands in
    `DEV_MODE_ADDRESS` carrying a live routing token for a named client individual. An
    operator who hits Reply there - or anyone a participant forwards to - resolves to that
    individual, and the signature does not help: it proves Resend posted the message and
    never who wrote it.

    The reply is stored rather than refused, because a forwarded answer is still real
    correspondence. What must not happen is it being presented as the participant's.
    """
    stakeholder_id = await _participant(client)
    await _set_config(SLUG, dev_mode=True)
    await _approved_reminder(SLUG, stakeholder_id)
    await _send_reminders(SLUG)

    held_to = json.loads(sent[0].content)["to"]
    operator = get_settings().dev_mode_address
    assert held_to == [operator], held_to
    reply_to = await _reply_address_from_the_wire(sent)
    assert "+" in reply_to, reply_to

    await deliver(client, inbound(reply_to, **{"from": operator}))

    reply = (await client.get(f"/projects/{SLUG}/inbound-replies")).json()["replies"][0]
    assert reply["stakeholder_name"] == PARTICIPANT_NAME
    assert reply["from_address"] == operator
    assert reply["sender_confirmed"] is False


@pytest.mark.asyncio
async def test_a_stakeholder_with_no_address_on_file_is_never_confirmed(client, secret):
    """"We could not check" must not present as "we checked and it matched".

    Both empty sides are driven. A comparison written as a bare `from_key == stakeholder_key`
    answers False for the first case and **True** for the second - two empty strings match -
    so a message with no sender at all, about a person with no address on file, would report
    as confirmed having compared nothing with nothing. Power-checking found that; the first
    case alone could not see it.
    """
    await _make_project(client, SLUG)
    stakeholder_id = await _add_stakeholder(SLUG, PARTICIPANT_NAME, "")
    address = await _minted_address(SLUG, stakeholder_id)

    await deliver(client, inbound(address), message_id="msg_no_email_on_file")
    await deliver(
        client, inbound(address, **{"from": ""}), message_id="msg_no_sender_either"
    )

    replies = (await client.get(f"/projects/{SLUG}/inbound-replies")).json()["replies"]
    assert len(replies) == 2
    assert [reply["sender_confirmed"] for reply in replies] == [False, False]


@pytest.mark.asyncio
async def test_the_senders_own_address_is_matched_however_it_was_written(client, secret):
    """A display name and a different case are the same person. A comparison that missed
    that would flag every genuine reply and teach a reader to ignore the flag."""
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)

    await deliver(client, inbound(
        address, **{"from": f"{PARTICIPANT_NAME} <{PARTICIPANT.upper()}>"}
    ))

    reply = (await client.get(f"/projects/{SLUG}/inbound-replies")).json()["replies"][0]
    assert reply["sender_confirmed"] is True


@pytest.mark.asyncio
async def test_marking_a_reply_read_clears_it_from_the_unread_count(client, secret):
    stakeholder_id = await _participant(client)
    address = await _minted_address(SLUG, stakeholder_id)
    await deliver(client, inbound(address))
    reply_id = (await client.get(f"/projects/{SLUG}/inbound-replies")).json()["replies"][0]["id"]

    marked = await client.post(f"/projects/{SLUG}/inbound-replies/{reply_id}/read")

    assert marked.status_code == 200, marked.text
    assert marked.json()["changed"] is True
    after = (await client.get(f"/projects/{SLUG}/inbound-replies")).json()
    assert after["unread"] == 0
    assert after["replies"][0]["read_at"] is not None
    # Reading it twice is not an error - two people may open the same panel.
    again = await client.post(f"/projects/{SLUG}/inbound-replies/{reply_id}/read")
    assert again.status_code == 200
    assert again.json()["changed"] is False


@pytest.mark.asyncio
async def test_a_reply_id_cannot_be_marked_read_through_another_project(client, secret):
    """A reply id is a small integer that means something different in every project file.

    **What holds this up is the file split, not the SQL**, and that is worth saying rather
    than implying: `get_connection(slug)` opens a different database, so the id simply is not
    there to update. Power-checking established it - taking `project_id` out of
    `mark_inbound_reply_read`'s WHERE clause fails nothing, because within one project file
    it is a constant. The property below is real and worth asserting; the clause is defence
    in depth and this test does not pretend to be its witness.
    """
    ours = await _participant(client, SLUG)
    await _participant(client, OTHER_SLUG, email="someone.else@example.test")
    await deliver(client, inbound(await _minted_address(SLUG, ours)))
    reply_id = (await client.get(f"/projects/{SLUG}/inbound-replies")).json()["replies"][0]["id"]

    crossed = await client.post(f"/projects/{OTHER_SLUG}/inbound-replies/{reply_id}/read")

    assert crossed.json()["changed"] is False
    assert (await client.get(f"/projects/{SLUG}/inbound-replies")).json()["unread"] == 1


@pytest.mark.asyncio
async def test_the_surface_refuses_a_caller_with_no_access_to_the_project(client, secret):
    """Client material, gated like every other read of it. The webhook is the public door;
    what it writes is not public."""
    from api.auth import create_access_token

    stakeholder_id = await _participant(client)
    await deliver(client, inbound(await _minted_address(SLUG, stakeholder_id)))
    outsider = create_access_token("nobody", "reviewer", get_settings().jwt_secret)

    response = await client.get(
        f"/projects/{SLUG}/inbound-replies", headers={"Authorization": f"Bearer {outsider}"}
    )

    assert response.status_code == 403, response.text


# ── Structural ───────────────────────────────────────────────────────────────

def test_the_inbound_path_never_writes_to_a_rag_store():
    """Writing to a project's Chroma collections is a deliberate act carrying authority for
    the destination tier, and a webhook has none - no user, no role, and content from outside
    the engagement.

    Asserted structurally rather than by not calling it, because "we did not call it" is
    exactly the property a later edit adds a call to without anyone noticing. `sector_*`
    sharpens it: that collection carries no slug and is shared across every engagement in a
    sector, so an inbound write landing there would put one client's words in another's
    retrieval.
    """
    root = Path(__file__).resolve().parent.parent
    forbidden = ("chroma", "ingest_service", "add_documents", "embed")
    for name in ("api/services/inbound_mail.py", "api/routers/inbound_mail.py"):
        text = (root / name).read_text().lower()
        # The docstrings say why there is no RAG write; strip them of the words they use to
        # say it, so the guard is about code and not about prose.
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        code = code.split('"""')
        code = "".join(code[i] for i in range(0, len(code), 2))
        offenders = [word for word in forbidden if word in code]
        assert offenders == [], f"{name} reaches for {offenders}"


def test_the_webhook_answers_one_constant_body():
    """The response is a module constant, and every branch returns that same object. A body
    assembled per branch is a body that grows a branch, and the branch it would grow is the
    one that tells an unauthenticated caller which reply tokens exist."""
    from api.routers import inbound_mail as router_module

    source = Path(router_module.__file__).read_text()
    returns = [
        line.strip() for line in source.splitlines()
        if line.strip().startswith("return ") and "ACCEPTED" not in line
        and "body" not in line and "{" in line
    ]
    assert router_module.ACCEPTED == {"status": "accepted"}
    assert all("status" not in line for line in returns), returns


# ── The migration ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def settings_dir(tmp_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    yield tmp_path
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_database_already_at_the_previous_version_gets_the_inbound_replies_table(
    settings_dir,
):
    """The `_SCHEMA_VERSION` bump is what makes this pass.

    Every project database on this deployment is stamped 10. The migration block is gated on
    `user_version < _SCHEMA_VERSION`, so a new `_migrate_*` added without the bump silently
    never runs on any of them - no error, no warning, just an endpoint that answers 200 and
    then fails to insert. A fresh database cannot see that, because a fresh database is
    below the gate anyway.
    """
    from api.database import get_connection

    slug = "ib-already-migrated"
    path = settings_dir / f"{slug}.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL,"
        " llm_mode TEXT, sector TEXT, config_json TEXT, status TEXT,"
        " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
    conn.execute("PRAGMA user_version = 10")
    conn.commit()
    conn.close()

    async with get_connection(slug) as db:
        rows = await db.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='inbound_replies'"
        )
    assert [dict(row)["name"] for row in rows] == ["inbound_replies"]
