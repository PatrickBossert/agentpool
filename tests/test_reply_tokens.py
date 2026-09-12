# tests/test_reply_tokens.py
"""A reply that knows which project and which person it answers.

Several engagements share one mailbox per role, so a reply arriving at
`stakeholder-manager@` carries nothing that says which project or which participant it
belongs to. The routing key travels in the address - `stakeholder-manager+<token>@domain` -
and this file is about that token: that it round-trips, that it discloses nothing, that it
is the same address on every message to the same person, and that every way of failing to
resolve one answers identically.

**Nothing here proves a reply is received.** `taskreimagination.ai` is not a verified
sender domain in Resend, so nothing sends and nothing receives; every assertion below is
against an `httpx.MockTransport` or the database. Two assumptions the design rests on are
therefore recorded and not tested: that Resend permits arbitrary local parts on a verified
domain, and that inbound routing preserves the `+tag` rather than normalising it away. The
second is the load-bearing one, which is why `sent_messages` records the provider's message
id from the first send - `In-Reply-To` is the fallback, and the id of a message already
sent cannot be recovered afterwards.

**The round trip is asserted through the address the seam actually puts on the wire.** A
test of `mint_reply_token` followed by a test of `resolve_reply_token` would pass with the
two never meeting, and with the send path emitting a plain role address the whole time.
Every routing assertion here starts from `From` as it was posted to Resend.

**Each participant path is driven on its own.** The reminder sender and the transcript
sender share one seam, and a shared seam is the shape that lets one path's test cover
another's.
"""
import json
import shutil
from email.utils import parseaddr
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from api.config import get_settings
from api.services import outbound_mail

# Slugs and a client name shaped like real ones, so "the address disclosed nothing" is a
# claim about strings that could plausibly have leaked rather than about placeholders.
SLUG = "rt-gs-am"
OTHER_SLUG = "rt-northbank"
CLIENT_NAME = "GS Asset Management"

_SLUGS = (SLUG, OTHER_SLUG, "rt-governance")

PARTICIPANT = "harriet.okonkwo@example.test"
PARTICIPANT_NAME = "Harriet Okonkwo"
REMINDER_SUBJECT = "A quick reminder"
TRANSCRIPT_SUBJECT = "Your interview transcript"


@pytest.fixture(autouse=True)
def clean():
    """Remove this file's project databases, directories, and system-database rows.

    The system database is shared and persists between runs - `DATABASE_DIR` is a fixed
    `/tmp/agentpool_test` - so `reply_tokens` rows outlive the project databases they name.
    A leftover row would hand the second run a token minted at a different `issue` from the
    first, which is precisely the poisoned-database trap CLAUDE.md describes. Cleared on
    both sides, and scoped to this file's slugs so it cannot disturb anything else.
    """

    def _wipe():
        settings = get_settings()
        for slug in _SLUGS:
            (Path(settings.database_dir) / f"{slug}.db").unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                (Path(settings.database_dir) / f"{slug}.db{suffix}").unlink(missing_ok=True)
            proj = Path(settings.projects_dir) / slug
            if proj.exists():
                shutil.rmtree(proj)
        _clear_system_rows()

    _wipe()
    yield
    _wipe()


def _clear_system_rows() -> None:
    import sqlite3

    path = Path(get_settings().database_dir) / "system.db"
    if not path.exists():
        return
    conn = sqlite3.connect(str(path))
    try:
        for table in ("reply_tokens", "sent_messages"):
            names = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not names:
                continue
            conn.executemany(
                f"DELETE FROM {table} WHERE project_slug=?", [(slug,) for slug in _SLUGS]
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def sent(monkeypatch):
    """Capture the real outbound requests, and return the list they land in.

    Each response carries a distinct provider id, because `sent_messages` is keyed on it:
    a fixture handing every send the same id would make one row look like the record of
    whichever message was asserted about.
    """
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": f"rt-message-{len(captured)}"})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return httpx.AsyncClient(*args, **kwargs)

    monkeypatch.setattr(outbound_mail, "httpx", SimpleNamespace(AsyncClient=factory))
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_rt_test")
    return captured


# ── Reading the wire ─────────────────────────────────────────────────────────

def payload(request: httpx.Request) -> dict:
    assert str(request.url) == "https://api.resend.com/emails", str(request.url)
    return json.loads(request.content)


def sender(request: httpx.Request) -> str:
    """The whole `From` header this request would have carried."""
    return payload(request)["from"]


def sender_address(request: httpx.Request) -> str:
    return parseaddr(sender(request))[1]


def token_on_the_wire(request: httpx.Request) -> str | None:
    """The reply token in the `From` address, parsed exactly as an inbound handler would."""
    return outbound_mail.token_from_address(sender_address(request))


def domain() -> str:
    return parseaddr(get_settings().from_email)[1].rpartition("@")[2]


# ── Fixture data ─────────────────────────────────────────────────────────────

async def _make_project(client, slug: str, **config_keys) -> None:
    await client.post("/projects", json={
        "client_slug": slug, "llm_mode": "standard", "sector": "rail",
    })
    await _set_config(slug, dev_mode=False, **config_keys)


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


async def _add_stakeholder(slug: str, name: str, email: str, **flags) -> int:
    from api.database import fetch_project, get_connection
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        cur = await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, project_role, "
            "is_reviewer, is_approver, is_governor) VALUES (?,?,?,?,?,?,?)",
            (project["id"], name, email, "governing",
             int(flags.get("reviewer", False)), int(flags.get("approver", False)),
             int(flags.get("governor", False))),
        )
        await conn.commit()
        return cur.lastrowid


async def _approved_reminder(slug: str, stakeholder_id: int) -> int:
    """One approved reminder for an existing stakeholder. Returns the reminder id."""
    from api.database import fetch_project, get_connection, insert_reminder_email
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        campaign_cur = await conn.execute(
            "INSERT INTO campaigns (project_id, campaign_name) VALUES (?,?)",
            (project["id"], "Discovery"),
        )
        await conn.commit()
        email_id = await insert_reminder_email(
            conn, project_id=project["id"], campaign_id=campaign_cur.lastrowid,
            stakeholder_id=stakeholder_id, subject=REMINDER_SUBJECT,
            body="Please complete your interview.", escalation_level="gentle",
        )
        await conn.execute(
            "UPDATE reminder_emails SET status='approved' WHERE id=?", (email_id,)
        )
        await conn.commit()
    return email_id


async def _send_reminders(slug: str) -> None:
    from api.services.campaign_service import send_reminder_emails_svc
    await send_reminder_emails_svc(slug)


async def _completed_session(slug: str, stakeholder_id: int, token: str) -> None:
    from api.database import fetch_project, get_connection
    from tests.support_interview_sessions import insert_interview_session
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        await insert_interview_session(
            conn, project_id=project["id"], orchestration_run_id=None,
            stakeholder_id=stakeholder_id, node_label="Goods-in Inspection",
            session_token=token,
        )
        await conn.execute(
            "UPDATE interview_sessions SET status='completed' WHERE session_token=?",
            (token,),
        )
        await conn.commit()


async def _send_transcript(client, token: str, email: str) -> None:
    r = await client.post(
        f"/api/interviews/{token}/email-transcript",
        json={"email": email, "qa_pairs": [{"question": "Q1", "answer": "A1"}]},
    )
    assert r.status_code == 200, r.text


async def _participant(client, slug: str, email: str = PARTICIPANT, **config) -> int:
    await _make_project(client, slug, client_name=CLIENT_NAME, **config)
    return await _add_stakeholder(slug, PARTICIPANT_NAME, email)


# ── The round trip, once per participant-facing path ─────────────────────────

@pytest.mark.asyncio
async def test_a_reminder_is_sent_from_an_address_that_resolves_to_its_participant(
    client, sent,
):
    """Mint, send, read the address off the wire, parse it, resolve it.

    The whole chain in one test, and deliberately not three: minting and resolution both
    passing while the send path emits a plain role address is the failure this shape
    catches, and it is the one a unit test of either half cannot see.
    """
    stakeholder_id = await _participant(client, SLUG)
    await _approved_reminder(SLUG, stakeholder_id)

    await _send_reminders(SLUG)

    token = token_on_the_wire(sent[0])
    assert token, sender_address(sent[0])
    assert await outbound_mail.resolve_reply_token(token) == (SLUG, stakeholder_id)


@pytest.mark.asyncio
async def test_a_transcript_is_sent_from_an_address_that_resolves_to_its_interviewee(
    client, sent,
):
    """The second participant path, driven on its own for the reason the file docstring
    gives: the two share a seam, and a shared seam lets one path's test cover another's."""
    stakeholder_id = await _participant(client, SLUG)
    await _completed_session(SLUG, stakeholder_id, "rt-transcript-session")

    await _send_transcript(client, "rt-transcript-session", PARTICIPANT)

    token = token_on_the_wire(sent[0])
    assert token, sender_address(sent[0])
    assert await outbound_mail.resolve_reply_token(token) == (SLUG, stakeholder_id)


@pytest.mark.asyncio
async def test_the_role_still_owns_the_mailbox_the_tag_only_says_who_it_is_about(
    client, sent,
):
    """One mailbox per role, ever. The tag must not have become a second mailbox.

    A scheme that put the token in the local part proper - `stakeholder-manager-<token>@` -
    would need a mailbox per participant, which is the failure the plus form exists to
    avoid. Asserted on the part before the `+`.
    """
    stakeholder_id = await _participant(client, SLUG)
    await _approved_reminder(SLUG, stakeholder_id)

    await _send_reminders(SLUG)

    local, _, sent_domain = sender_address(sent[0]).partition("@")
    assert local.partition("+")[0] == "stakeholder-manager", sender_address(sent[0])
    assert sent_domain == domain()


# ── Reuse: the same person, the same address, every message ──────────────────

@pytest.mark.asyncio
async def test_the_same_person_is_written_to_from_the_same_address_every_time(
    client, sent,
):
    """A thread stays coherent, and a reply to an old message still routes.

    Two separate sends, a fortnight apart in practice. A scheme that minted per message
    would put a different address on each and still pass every round-trip test above -
    this is the one that would fail.
    """
    stakeholder_id = await _participant(client, SLUG)
    await _approved_reminder(SLUG, stakeholder_id)
    await _send_reminders(SLUG)
    await _approved_reminder(SLUG, stakeholder_id)
    await _send_reminders(SLUG)

    assert len(sent) == 2
    assert sender_address(sent[0]) == sender_address(sent[1])
    # And the address from the first message still routes after the second went out.
    assert await outbound_mail.resolve_reply_token(token_on_the_wire(sent[0])) == (
        SLUG, stakeholder_id,
    )


@pytest.mark.asyncio
async def test_minting_the_same_token_twice_leaves_one_row(client):
    """Idempotence at the table, not only at the return value.

    A mint that inserted a row per call would keep answering with the same token - the
    derivation is deterministic - while growing a row per message sent, and the first
    revocation would then only kill one of them.
    """
    stakeholder_id = await _participant(client, SLUG)

    first = await outbound_mail.mint_reply_token(SLUG, stakeholder_id)
    second = await outbound_mail.mint_reply_token(SLUG, stakeholder_id)

    assert first == second
    assert await _reply_token_rows(SLUG) == 1


async def _reply_token_rows(slug: str) -> int:
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM reply_tokens WHERE project_slug=?", (slug,)
        ) as cur:
            return (await cur.fetchone())[0]


# ── Distinctness: one token per person per project ───────────────────────────

@pytest.mark.asyncio
async def test_two_people_on_one_project_are_written_to_from_different_addresses(
    client, sent,
):
    first = await _participant(client, SLUG)
    second = await _add_stakeholder(SLUG, "Devi Ramanathan", "devi@example.test")
    await _approved_reminder(SLUG, first)
    await _approved_reminder(SLUG, second)

    await _send_reminders(SLUG)

    assert len(sent) == 2
    tokens = {token_on_the_wire(r) for r in sent}
    assert len(tokens) == 2, tokens
    resolved = {await outbound_mail.resolve_reply_token(t) for t in tokens}
    assert resolved == {(SLUG, first), (SLUG, second)}


@pytest.mark.asyncio
async def test_the_same_person_on_two_engagements_gets_two_addresses(client, sent):
    """The case the whole design exists for: one mailbox, several projects at once.

    Both stakeholder rows are id 1 - ids restart at 1 in every project file - so a token
    derived from the id alone would collide and route both engagements' replies into
    whichever project was looked up first.
    """
    here = await _participant(client, SLUG)
    there = await _participant(client, OTHER_SLUG)
    assert here == there, "the point of this test is that the two ids are the same"

    await _approved_reminder(SLUG, here)
    await _send_reminders(SLUG)
    await _approved_reminder(OTHER_SLUG, there)
    await _send_reminders(OTHER_SLUG)

    # Stated before the comparison, because a token that ignored the slug would collide on
    # `reply_tokens.token_hash`, which is UNIQUE - so the second mint raises, the reminder
    # sender records a failure, and there is no second message to compare at all. The
    # constraint is a real second line of defence; it is not the property under test.
    assert len(sent) == 2, "the second engagement's reminder never went out"
    assert token_on_the_wire(sent[0]) != token_on_the_wire(sent[1])
    assert await outbound_mail.resolve_reply_token(token_on_the_wire(sent[0])) == (SLUG, here)
    assert await outbound_mail.resolve_reply_token(token_on_the_wire(sent[1])) == (
        OTHER_SLUG, there,
    )


# ── Opacity: the address teaches its reader nothing ──────────────────────────

@pytest.mark.asyncio
async def test_the_address_discloses_neither_the_engagement_nor_the_person(client, sent):
    """A participant forwards their invitation; the recipient learns nothing from it.

    The same rule as the account-existence one - what is not disclosed is not disclosed to
    anybody, including somebody holding a genuine message. Checked over the whole `From`
    header rather than only the tag, because the header is what gets forwarded.
    """
    stakeholder_id = await _participant(client, SLUG)
    await _approved_reminder(SLUG, stakeholder_id)

    await _send_reminders(SLUG)

    header = sender(sent[0]).lower()
    for secret in (SLUG, "gs-am", CLIENT_NAME, PARTICIPANT, PARTICIPANT_NAME,
                   "harriet", "okonkwo", str(stakeholder_id * 1000 + 999)):
        assert secret.lower() not in header, (secret, header)


def test_a_token_is_opaque_by_construction_and_not_merely_by_encoding():
    """A reversible encoding looks opaque and is not.

    base64 of `rt-gs-am:1` would satisfy every routing test in this file and would be
    readable to anyone who recognised the alphabet. The token is decoded here rather than
    only inspected as text, because the point is what it contains and not what it looks
    like - and it is a *different* token for the same person on the next issue, which no
    encoding of an identity could be.
    """
    import base64

    token = outbound_mail._derive_reply_token(SLUG, 1, 1)
    padded = token + "=" * (-len(token) % 4)
    assert SLUG.encode() not in base64.urlsafe_b64decode(padded)
    assert SLUG not in token
    assert token != outbound_mail._derive_reply_token(SLUG, 1, 2)


def test_the_local_part_stays_inside_the_rfc_5321_limit():
    """64 octets, and the tag spends a fixed 23 of them.

    Checked against every `agent_id` on the roll rather than the two audiences that send
    today, for the same reason the role-address rule is: the next correspondent is added to
    `agents/identity.py`, not here, and an address a mail server refuses would surface as a
    4xx on somebody's reminder.
    """
    from agents.identity import AGENT_IDENTITY

    token = outbound_mail._derive_reply_token(SLUG, 1, 1)
    for agent_id in AGENT_IDENTITY:
        local = f"{agent_id.replace('_', '-')}+{token}"
        assert len(local) <= 64, (agent_id, len(local))
    assert len(token) == 22, token


# ── Every failure answers the same way ───────────────────────────────────────

@pytest.mark.asyncio
async def test_a_token_that_was_never_minted_resolves_to_nothing(client):
    """And says nothing about whether it ever existed - there is one answer, not two."""
    never_minted = outbound_mail._derive_reply_token("no-such-project", 99, 1)

    assert await outbound_mail.resolve_reply_token(never_minted) is None


@pytest.mark.asyncio
async def test_a_malformed_tag_resolves_to_nothing_rather_than_raising(client):
    """An inbound endpoint is unauthenticated, so a token that raises is a way to 500 it.

    `None` and a non-string are in the list because a webhook payload is somebody else's
    JSON: a missing recipient field arrives as `None`, and unguarded that reaches
    `raw.encode()` and raises rather than answering. The shape check ahead of it - length
    and alphabet - is defence in depth rather than a tested property, since a malformed
    string would fall out of the digest lookup as None anyway; it is there so that rubbish
    never reaches the lookup at all.
    """
    for rubbish in ("", "   ", "not-a-token", "a" * 200, "../../etc/passwd",
                    "abcdefghijklmnopqrstu", "abcdefghijklmnopqrstuvw", "a b",
                    None, 12345, ["a"]):
        assert await outbound_mail.resolve_reply_token(rubbish) is None, rubbish


@pytest.mark.asyncio
async def test_a_revoked_address_stops_routing_and_the_next_message_carries_a_new_one(
    client, sent,
):
    """Revocation is the deliberate door, and it must survive the next send.

    The trap this closes: the send path mints on every message, so a `mint` that cleared
    `revoked_at` on the existing row would quietly undo the revocation with the next
    reminder while every other test still passed. Minting past a revocation issues a
    *different* address instead, and the revoked one stays dead.
    """
    stakeholder_id = await _participant(client, SLUG)
    await _approved_reminder(SLUG, stakeholder_id)
    await _send_reminders(SLUG)
    revoked_token = token_on_the_wire(sent[0])

    assert await outbound_mail.revoke_reply_token(SLUG, stakeholder_id) is True
    assert await outbound_mail.resolve_reply_token(revoked_token) is None

    await _approved_reminder(SLUG, stakeholder_id)
    await _send_reminders(SLUG)

    reissued = token_on_the_wire(sent[1])
    assert reissued != revoked_token
    assert await outbound_mail.resolve_reply_token(reissued) == (SLUG, stakeholder_id)
    assert await outbound_mail.resolve_reply_token(revoked_token) is None


@pytest.mark.asyncio
async def test_revoking_takes_the_dead_digest_out_of_the_table_entirely(client):
    """Not merely refused - absent. A refused row is one `WHERE` clause away from being
    honoured again by a later change; a digest that is not there cannot be."""
    import hashlib

    stakeholder_id = await _participant(client, SLUG)
    first = await outbound_mail.mint_reply_token(SLUG, stakeholder_id)
    await outbound_mail.revoke_reply_token(SLUG, stakeholder_id)
    await outbound_mail.mint_reply_token(SLUG, stakeholder_id)

    dead = hashlib.sha256(first.encode()).hexdigest()
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM reply_tokens WHERE token_hash=?", (dead,)
        ) as cur:
            assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_an_address_whose_person_has_been_removed_stops_routing(client, sent):
    """A token that outlives its person is a live address into a project.

    Nothing tells the token table that a stakeholder was deleted, and deliberately so - a
    hook in the delete path is a promise the next delete path is written without, which is
    exactly what `dev_mode` was. Resolution re-reads the person instead.

    Driven through the seam rather than the reminder sender because `reminder_emails`
    carries a foreign key to `stakeholders`, so a person with a reminder on file cannot be
    deleted at all. The address still comes off the wire.
    """
    stakeholder_id = await _participant(client, SLUG)
    await outbound_mail.send_project_mail(
        slug=SLUG, audience=outbound_mail.STAKEHOLDERS, to=[PARTICIPANT],
        subject="Your interview", body="An invitation.", stakeholder_id=stakeholder_id,
    )
    token = token_on_the_wire(sent[0])

    from api.services.stakeholder_service import delete_stakeholder_svc
    assert await delete_stakeholder_svc(SLUG, stakeholder_id) is True

    assert await outbound_mail.resolve_reply_token(token) is None


@pytest.mark.asyncio
async def test_an_address_for_a_project_that_no_longer_exists_stops_routing(client, sent):
    stakeholder_id = await _participant(client, SLUG)
    await _approved_reminder(SLUG, stakeholder_id)
    await _send_reminders(SLUG)
    token = token_on_the_wire(sent[0])

    (Path(get_settings().database_dir) / f"{SLUG}.db").unlink()

    assert await outbound_mail.resolve_reply_token(token) is None


@pytest.mark.asyncio
async def test_a_removed_persons_id_is_never_handed_to_somebody_else(client):
    """The assumption the removal answer rests on, asserted rather than trusted.

    `stakeholders.id` is `AUTOINCREMENT`, so SQLite will not reissue the id of a deleted
    row. Without that, a token pointing at a removed person would start resolving to
    whoever next occupied that integer - and would pass the removal test above, because at
    the moment of deletion there is nobody there.
    """
    first = await _participant(client, SLUG)
    from api.services.stakeholder_service import delete_stakeholder_svc
    await delete_stakeholder_svc(SLUG, first)

    second = await _add_stakeholder(SLUG, "Devi Ramanathan", "devi@example.test")

    assert second != first, "a reused stakeholder id would resurrect a dead reply address"


@pytest.mark.asyncio
async def test_every_way_of_failing_answers_with_the_same_nothing(client, sent):
    """One answer, not a family of them.

    An endpoint that answered differently for "never existed", "withdrawn" and "the person
    is gone" would be an oracle for which tokens exist and which engagements have lost
    people - readable by anybody who can post to it. Collected into one assertion so that a
    later change giving any single case its own answer fails here.
    """
    stakeholder_id = await _participant(client, SLUG)
    await _approved_reminder(SLUG, stakeholder_id)
    await _send_reminders(SLUG)
    revoked = token_on_the_wire(sent[0])
    await outbound_mail.revoke_reply_token(SLUG, stakeholder_id)

    removed_id = await _add_stakeholder(SLUG, "Devi Ramanathan", "devi@example.test")
    removed = await outbound_mail.mint_reply_token(SLUG, removed_id)
    from api.services.stakeholder_service import delete_stakeholder_svc
    await delete_stakeholder_svc(SLUG, removed_id)

    answers = [
        await outbound_mail.resolve_reply_token(revoked),
        await outbound_mail.resolve_reply_token(removed),
        await outbound_mail.resolve_reply_token(
            outbound_mail._derive_reply_token("no-such-project", 7, 1)
        ),
        await outbound_mail.resolve_reply_token("not-a-token"),
    ]
    assert answers == [None, None, None, None], answers


# ── The token is never stored, and never survives its key ────────────────────

@pytest.mark.asyncio
async def test_the_raw_token_is_never_written_to_the_database(client, sent):
    """Only its digest. A backup, a dump, or a stray SELECT yields no working address."""
    import hashlib

    stakeholder_id = await _participant(client, SLUG)
    await _approved_reminder(SLUG, stakeholder_id)
    await _send_reminders(SLUG)
    token = token_on_the_wire(sent[0])

    from api.database import get_system_connection
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT * FROM reply_tokens WHERE project_slug=?", (SLUG,)
        ) as cur:
            rows = [dict(r) async for r in cur]

    assert rows, "nothing was stored at all, so this test proves nothing"
    for row in rows:
        for value in row.values():
            assert token not in str(value), row
    assert rows[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()


@pytest.mark.asyncio
async def test_a_rotated_secret_re_keys_rather_than_minting_an_address_nobody_can_reply_to(
    client, sent, monkeypatch,
):
    """The trap in deriving the token from a rotatable secret, and it is a silent one.

    Rotating `JWT_SECRET` changes what every token derives to; the digests already stored
    do not change with it. A mint that trusted the stored `issue`, re-derived under the new
    key and handed the result to the send path would put a `From` address on a
    participant's mail whose digest is in no row at all - the message sends, they reply,
    and the reply is dropped as unknown, with nothing failing anywhere. This test was
    written expecting rotation to retire addresses outright and found that defect instead.

    What actually happens, and what is asserted: an address already sent keeps routing,
    because resolution is a digest lookup and knows nothing of the key; the next mint
    re-keys the row, which is the moment the previous address is retired; and the address
    the mint returns always resolves.
    """
    stakeholder_id = await _participant(client, SLUG)
    await _approved_reminder(SLUG, stakeholder_id)
    await _send_reminders(SLUG)
    before = token_on_the_wire(sent[0])

    monkeypatch.setattr(get_settings(), "jwt_secret", "a-rotated-secret")

    # Nothing has been re-issued yet, so the address in flight still routes.
    assert await outbound_mail.resolve_reply_token(before) == (SLUG, stakeholder_id)

    after = await outbound_mail.mint_reply_token(SLUG, stakeholder_id)

    assert after != before
    assert await outbound_mail.resolve_reply_token(after) == (SLUG, stakeholder_id)
    assert await outbound_mail.resolve_reply_token(before) is None
    assert await _reply_token_rows(SLUG) == 1


# ── Parsing the address back, which is the inbound handler's only entry ──────

def test_a_plain_role_address_carries_no_token():
    """`stakeholder-manager@domain` is a legitimate address and resolves to nobody."""
    assert outbound_mail.token_from_address(
        outbound_mail.role_address(outbound_mail.STAKEHOLDERS)
    ) is None


def test_an_address_with_a_malformed_tag_carries_no_token():
    """Shape is checked, not just presence, so rubbish never reaches a digest lookup."""
    for address in (
        "",
        "not-an-address",
        f"stakeholder-manager+@{domain()}",
        f"stakeholder-manager+short@{domain()}",
        f"stakeholder-manager+{'a' * 40}@{domain()}",
        f"stakeholder-manager+has.a.dot.in.it.and.is.22@{domain()}",
    ):
        assert outbound_mail.token_from_address(address) is None, address


def test_the_parser_reads_the_address_out_of_a_full_header():
    """An inbound payload quotes the recipient as a header, not as a bare address."""
    token = outbound_mail._derive_reply_token(SLUG, 1, 1)
    header = outbound_mail.sender_for(outbound_mail.STAKEHOLDERS, token)
    assert outbound_mail.token_from_address(header) == token


# ── Governance carries no token, because there is no one person ──────────────

@pytest.mark.asyncio
async def test_governance_mail_carries_no_reply_token(client, sent):
    """A notice to every reviewer is about nobody in particular, so there is nothing for a
    reply to be about - and inventing a person to tag it with would file the first
    reviewer's answer under whoever the tag happened to name."""
    await _make_project(client, "rt-governance", client_name=CLIENT_NAME)
    await _add_stakeholder("rt-governance", "Rev", "reviewer@example.test", reviewer=True)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit("rt-governance", "discovery_mapping")

    assert sender_address(sent[0]) == f"pam@{domain()}"
    assert token_on_the_wire(sent[0]) is None


# ── Held mail still carries it, and the provider's id is recorded ────────────

@pytest.mark.asyncio
async def test_a_message_held_by_dev_mode_still_carries_the_participants_token(
    client, sent,
):
    """The operator reading it in the redirect mailbox sees the message that would have
    gone out. Deriving the token from the recipient address would have produced the
    operator's, which is the reason it is taken from the row instead."""
    stakeholder_id = await _participant(client, SLUG)
    await _set_config(SLUG, dev_mode=True)
    await _approved_reminder(SLUG, stakeholder_id)

    await _send_reminders(SLUG)

    assert payload(sent[0])["to"] == [get_settings().dev_mode_address]
    assert await outbound_mail.resolve_reply_token(token_on_the_wire(sent[0])) == (
        SLUG, stakeholder_id,
    )


@pytest.mark.asyncio
async def test_the_provider_message_id_is_recorded_against_the_project_and_person(
    client, sent,
):
    """The `In-Reply-To` fallback, prepared before it is needed.

    If inbound routing turns out to strip the `+tag`, this table is the only way back to a
    project and a person - and only for messages sent after it started being kept, which is
    why it starts now rather than when the answer is known.
    """
    stakeholder_id = await _participant(client, SLUG)
    await _approved_reminder(SLUG, stakeholder_id)

    await _send_reminders(SLUG)

    from api.database import get_system_connection
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT * FROM sent_messages WHERE project_slug=?", (SLUG,)
        ) as cur:
            rows = [dict(r) async for r in cur]

    assert len(rows) == 1, rows
    assert rows[0]["stakeholder_id"] == stakeholder_id
    assert rows[0]["provider_message_id"] == "rt-message-1"


@pytest.mark.asyncio
async def test_a_message_about_nobody_records_no_message_id(client, sent):
    """Governance mail has no person for a reply to be about, so there is nothing to
    record and a row claiming otherwise would name an arbitrary reviewer."""
    await _make_project(client, "rt-governance", client_name=CLIENT_NAME)
    await _add_stakeholder("rt-governance", "Rev", "reviewer@example.test", reviewer=True)

    from api.services.commit_notify_service import notify_crew_awaiting_commit
    await notify_crew_awaiting_commit("rt-governance", "discovery_mapping")

    assert len(sent) == 1
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM sent_messages WHERE project_slug=?", ("rt-governance",)
        ) as cur:
            assert (await cur.fetchone())[0] == 0


# ── The two things nothing here can prove ────────────────────────────────────

def test_the_untestable_assumptions_are_recorded_where_the_scheme_is_read():
    """`taskreimagination.ai` is unverified in Resend: nothing sends and nothing receives.

    Two assumptions carry the design and neither can be checked from here - that arbitrary
    local parts are permitted on a verified domain, and that inbound routing preserves the
    `+tag`. This asserts only that they are written down beside the code that depends on
    them, so the first person to verify the domain meets them rather than rediscovering
    them. The `In-Reply-To` fallback that the second assumption needs is real code, tested
    above.
    """
    doc = outbound_mail.__doc__
    assert "not a verified sender domain" in doc or "not verified" in doc
    assert "In-Reply-To" in doc
    assert "+tag" in doc
