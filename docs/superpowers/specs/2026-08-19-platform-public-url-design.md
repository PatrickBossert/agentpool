# A platform setting an administrator can change - starting with PUBLIC_URL

**Date:** 2026-08-19
**Status:** draft for review

## Why

`PUBLIC_URL` is the address this deployment answers on. It is read in five places and every
one of them puts it in front of a person:

| Reader | What it builds |
|---|---|
| `interview_service.py:39` | the interview link a participant clicks |
| `campaign_service.py:392` | the interview link in a reminder |
| `admin_service.py:76` | the login link in a welcome email |
| `pam_report_job.py:112` | the daily report link for governance |
| `commit_notify_service.py:63` | the dashboard link in a commit notice |

It is settable only by editing `.env` and restarting the API. On a licensed private-server
deployment the person who needs to change it - after a domain is verified, a hostname moves,
or a client is given a vanity address - is an administrator with a browser, not somebody with
shell access to the box. Today a wrong `PUBLIC_URL` sends every participant to a dead link and
the fix requires a redeploy.

## What it is not

**Not per project.** Two of the five readers - the welcome email and the password-reset link -
have no project to read a per-project value from, so a per-project setting could not serve
them and the environment variable would have to stay as a second source for the same fact.
One deployment answers on one address.

## The one-row table

`platform_settings` in `system.db`, a singleton keyed `id = 1`, with **declared columns** -
not a key/value store. An open key/value table becomes a junk drawer of undeclared strings,
and this codebase has spent a branch deleting exactly that shape at the knowledge tiers. A
new platform setting is a migration and a column, so nothing undeclared can be stored.

`scheduler_heartbeat` is the established precedent for a singleton row here.

## Precedence, and why the environment variable stays

Resolution order, first non-empty wins:

1. `platform_settings.public_url`
2. `PUBLIC_URL` from the environment
3. the `api/config.py` default

The environment variable is not retired. It is the **bootstrap**: a fresh deployment sends
correct links before anybody has opened the admin page, and `.env.example` keeps documenting
it. Deleting it would make a new deployment's first welcome email point at `localhost:3000`.

The stored value wins because it is the one somebody deliberately set through a door with an
audit trail, and because an operator who changes it in the browser must not have it silently
overridden by a stale `.env` on the box.

## Reading it

`platform_public_url()` in a service, with a module-level cache and an explicit
`forget_platform_settings()` on write - the shape `project_llm_mode` and `forget_project_mode`
already use in `chroma_client.py`. The five callers stop reading `settings.public_url`
directly.

**It must be synchronous**, and this is not a preference. `interview_service.interview_url` -
the function that builds the link a participant actually clicks - is a plain `def`, so an
`async` accessor could not be called from it without restructuring its callers. That is the
same constraint `project_llm_mode` is under, and it resolves the same way: open a plain
`sqlite3` connection rather than reaching for the async pool. Note what that inherits -
`project_llm_mode` documents that such a connection sets no `busy_timeout` and can raise
`database is locked` under contention, which is precisely the read failure the fallback above
exists to absorb.

A read failure **falls back rather than raises**, unlike the mode seam. The failure modes are
not comparable: a wrong `llm_mode` sends client material to the wrong country, while a
`PUBLIC_URL` that falls back to the environment sends a correct link built the old way. Making
a link builder raise would take down interview invitations for a system-database hiccup.

## Who may change it

**`sysadmin` alone**, through a door under `/admin`.

This is narrower than it first appears to warrant, and the reason is not seniority. Whoever
sets `PUBLIC_URL` decides where every interview invitation and every welcome email points -
a participant clicks it and signs in. That is a credential-phishing vector, so it belongs
beside the platform-tier settings `_PLATFORM_TIER_SETTINGS` already refuses to a
`project_admin`, and a tier tighter still, because it is not scoped to one engagement.

Validation refuses anything that is not an absolute `http`/`https` URL, refuses embedded
credentials, and stores the value without a trailing slash - four of the five readers already
call `.rstrip('/')`, which is the same rule expressed five times because nothing enforced it
once.

## A latent defect this closes

`run_service.py:478` and `:769` read `config.get("public_url", "")` and pass it to the
stakeholder-management crew as `public_interview_url_base`. **`public_url` is not declared on
`ProjectSettings`, so `PATCH /{slug}/settings` cannot set it** - the value is always `""` and
Jordan has always been handed an empty interview URL base. A read with no writer, the same
shape as `insert_interview_session` and `runAgent` in the tech-debt list.

Both sites are repointed at `platform_public_url()`, which gives the crew a real address for
the first time. This is in scope because it is the same fact, and leaving it would mean the
deployment's address is settable in one place and read from another that nothing can write.

## Testing

- The precedence chain, each step **witnessed alone**: stored value wins over environment;
  environment wins over default; a blank stored value does not shadow the environment. A
  shared resolver lets one step's test cover another's.
- **Assert the URL that reaches the transport**, not a helper's return value. The property is
  what a participant receives, and this project's CLAUDE.md records "a radio tested as
  rendered, not as sent" among its recurring defects.
- A non-sysadmin is refused. An `org_admin` is the caller that matters, not an anonymous one -
  anonymous is refused by the dependency before the rule is reached, so it proves nothing.
- Validation refusals are asserted by their own sentence, not by a substring the call supplied.
- The cache is invalidated on write: a PATCH followed by a read returns the new value in the
  same process.

## Out of scope

Moving other settings into the table - `dev_mode`'s redirect address is the obvious next
candidate and belongs with test mode, not here. Per-project vanity domains. Retiring
`PUBLIC_URL` from the environment.
