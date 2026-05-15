# Multi-Tenant RBAC Design Spec

**Date:** 2026-05-15
**Sprint:** SP17a

---

## Goal

Add a three-role access control system with organisation and project scoping. A sysadmin manages organisations and all users. An org_admin manages users and projects within their organisation. A reviewer can view project progress and submit HITL feedback on assigned projects but cannot change configuration.

---

## Architecture

All identity and membership data lives in `system.db`. Project data continues in per-slug SQLite files. The bridge between them is `project_registry`, which maps a project slug to an organisation.

Role enforcement is split: the backend checks JWTs and membership tables on every request; the frontend reads the role from the decoded JWT to show/hide nav items and gate routes.

---

## Data Model

### `users` table — add `email` column

```sql
ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT '';
```

Existing `role` values of `consultant` are migrated to `sysadmin` via a one-time UPDATE run inside `init_system_db`. The `project_slug` column is retained but deprecated — `project_memberships` replaces it.

### New tables in `system.db`

```sql
CREATE TABLE IF NOT EXISTS organisations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT    UNIQUE NOT NULL,
    name        TEXT    NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS org_memberships (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id      INTEGER NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    role        TEXT    NOT NULL CHECK(role IN ('org_admin', 'member')),
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, org_id)
);

CREATE TABLE IF NOT EXISTS project_registry (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT    UNIQUE NOT NULL,
    org_id       INTEGER NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    display_name TEXT    NOT NULL DEFAULT '',
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS project_memberships (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_slug TEXT    NOT NULL,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, project_slug)
);
```

---

## Role Hierarchy

| Capability | `sysadmin` | `org_admin` | `reviewer` |
|---|---|---|---|
| Create / manage organisations | ✓ | — | — |
| Create projects | ✓ | own org only | — |
| Create / invite users | ✓ | own org only | — |
| Modify / delete users | ✓ | own org only | — |
| Assign roles | ✓ | own org only | — |
| View project progress | ✓ | own org's projects | assigned projects |
| Submit HITL feedback | ✓ | own org's projects | assigned projects |
| Change project settings / run pipeline | ✓ | own org's projects | — |

---

## JWT

The JWT payload expands to include `org_id` for org-scoped users:

```python
# sysadmin
{"sub": "alice", "role": "sysadmin", "exp": ...}

# org_admin
{"sub": "bob", "role": "org_admin", "org_id": 3, "exp": ...}

# reviewer
{"sub": "carol", "role": "reviewer", "exp": ...}
```

`create_access_token` gains an optional `org_id: int | None` parameter. The env-var admin issues a `sysadmin` token (currently issues `consultant` — fixed in `api/routers/auth.py`).

---

## FastAPI Auth Dependencies

Defined in `api/auth.py`:

```python
def require_sysadmin(payload: dict = Depends(get_token_payload)) -> dict:
    if payload.get("role") != "sysadmin":
        raise HTTPException(403, "Sysadmin required")
    return payload

def require_org_admin_or_above(payload: dict = Depends(get_token_payload)) -> dict:
    if payload.get("role") not in ("sysadmin", "org_admin"):
        raise HTTPException(403, "Org admin or above required")
    return payload

def require_any_auth(payload: dict = Depends(get_token_payload)) -> dict:
    return payload  # just validates token
```

Project-level access is checked in a helper (not a dependency, since it needs the slug):

```python
async def check_project_access(slug: str, payload: dict, conn: aiosqlite.Connection) -> None:
    """Raises 403 if the user cannot access this project."""
    role = payload.get("role")
    if role == "sysadmin":
        return
    user_id = await get_user_id_by_username(conn, payload["sub"])
    if role == "org_admin":
        org_id = payload.get("org_id")
        row = await fetch_project_registry(conn, slug=slug)
        if row and row["org_id"] == org_id:
            return
    if role == "reviewer":
        if await has_project_membership(conn, user_id=user_id, slug=slug):
            return
    raise HTTPException(403, "Access denied")
```

`check_project_access` is called from `get_system_connection` context in every project-scoped endpoint.

---

## Access Enforcement on Existing Endpoints

| Endpoint | New auth requirement |
|---|---|
| `GET /projects` | `require_any_auth`; results filtered by role/membership |
| `POST /projects` | `require_org_admin_or_above`; org_admin auto-registers to their org |
| `GET /{slug}/status` + all content GETs | `require_any_auth` + `check_project_access` |
| `PATCH /{slug}/settings` | `require_org_admin_or_above` + `check_project_access` |
| `POST /orchestrate` | `require_org_admin_or_above` + `check_project_access` |
| `GET/PATCH /{slug}/reviews` | `require_any_auth` + `check_project_access` |
| `POST /{slug}/assignment` | `require_org_admin_or_above` + `check_project_access` |
| `POST /{slug}/reminder-emails/send` | `require_org_admin_or_above` + `check_project_access` |
| `GET /{slug}/stakeholders` etc. | `require_any_auth` + `check_project_access` |

Endpoints that are intentionally open (no auth needed):
- `GET /{slug}/branding/image` — needed by VoiceInterview (unauthenticated public page)
- `GET /interview/:sessionToken` — public voice interview page

---

## New API Endpoints

All live in `api/routers/admin.py`, registered at prefix `/auth`.

### Organisations (sysadmin only)

```
GET    /auth/orgs                     list all organisations
POST   /auth/orgs                     create organisation {slug, name}
PATCH  /auth/orgs/{org_id}            update {name}
DELETE /auth/orgs/{org_id}            delete (fails if projects remain)
```

### Org membership (sysadmin or that org's admin)

```
GET    /auth/orgs/{org_id}/members              list members
POST   /auth/orgs/{org_id}/members              add user {user_id, role}
PATCH  /auth/orgs/{org_id}/members/{user_id}    change role
DELETE /auth/orgs/{org_id}/members/{user_id}    remove from org
```

### Project registry

```
GET    /auth/projects                           list registry entries
                                                  sysadmin: all
                                                  org_admin: own org
POST   /auth/projects                           register slug→org {slug, org_id, display_name}
                                                  sysadmin only
DELETE /auth/projects/{slug}                    unregister (sysadmin only)
```

### Users

```
GET    /auth/users                     list users
                                         sysadmin: all
                                         org_admin: own org's users only
POST   /auth/users                     create user + send notification email
                                         {username, email, password, role, org_id?}
                                         sysadmin or org_admin
PATCH  /auth/users/{user_id}           update {email, role, password}
                                         sysadmin or same-org admin
DELETE /auth/users/{user_id}           delete user
                                         sysadmin or same-org admin
```

### Project access grants (reviewer assignments)

```
GET    /auth/users/{user_id}/projects             list project memberships
POST   /auth/users/{user_id}/projects/{slug}      grant reviewer access
DELETE /auth/users/{user_id}/projects/{slug}      revoke reviewer access
```

---

## Email Notification

On `POST /auth/users`, after inserting the user record, send one email via Resend:

- **To:** the new user's email address
- **Subject:** `"Your FutureMomentum account has been created"`
- **Body:** username, temporary password (plaintext, one-time only — user should change on first login), login URL (`PUBLIC_URL/dashboard/login`)

Uses existing `RESEND_API_KEY` and `FROM_EMAIL` from config. If `RESEND_API_KEY` is empty, the user is still created and the email is silently skipped (same pattern as reminder emails).

Password is included in this one welcome email. It is never stored in plaintext — only the bcrypt hash is persisted.

---

## Frontend

### AuthContext changes

Expose `role` and `orgId` from the decoded JWT:

```typescript
interface AuthState {
  token: string | null
  username: string | null
  role: 'sysadmin' | 'org_admin' | 'reviewer' | null
  orgId: number | null
}
```

JWT is decoded client-side on login (base64 payload, no verification needed — server already verified it).

### New routes in router.tsx

```typescript
/admin                    AdminDashboard    (sysadmin only)
/admin/orgs/new           OrgForm           (sysadmin only)
/admin/orgs/:orgId        OrgDetail         (sysadmin only)
/admin/users              UserList          (sysadmin or org_admin)
/admin/users/new          UserForm          (sysadmin or org_admin)
/admin/users/:userId/edit UserForm          (sysadmin or org_admin)
/org                      OrgPanel          (org_admin only)
```

Protected by a new `AdminRoute` component that checks `role`:

```typescript
function AdminRoute({ children, allow }: { children: ReactNode, allow: Role[] }) {
  const { role } = useAuth()
  if (!role || !allow.includes(role)) return <Navigate to="/" replace />
  return <>{children}</>
}
```

### New pages

**`AdminDashboard`** (`/admin`) — sysadmin only. Two panels:
- Organisations table: slug, name, member count, project count. "New Org" button.
- Users table: username, email, role badge, org. "New User" button.

**`OrgDetail`** (`/admin/orgs/:orgId`) — sysadmin only.
- Members table: username, email, role badge. "Add Member" inline form, remove button.
- Linked projects table: slug, display name. "Link Project" form.

**`UserList`** (`/admin/users`) — sysadmin sees all; org_admin sees their org's users.
- Table: username, email, role, org. Edit / delete actions.

**`UserForm`** (`/admin/users/new` and `/admin/users/:userId/edit`) — create or update a user.
- Fields: username, email, password (create only), role selector, org assignment, project access grants (multi-select, visible when role is `reviewer`).

**`OrgPanel`** (`/org`) — org_admin only.
- Same structure as OrgDetail but scoped: only their org's members and their org's projects. No org rename/delete controls.

### Nav changes (`AppLayout`)

- Sysadmin: show "Admin" nav item (links to `/admin`), above Settings.
- Org admin: show "Team" nav item (links to `/org`), above Settings.
- Reviewer: no admin nav item.

---

## Database Helpers (system.db)

New async helpers added to `api/database.py`:

```python
# Organisations
insert_organisation(conn, *, slug, name) -> int
fetch_all_organisations(conn) -> list[dict]
fetch_organisation(conn, *, org_id) -> dict | None
update_organisation(conn, *, org_id, name) -> None
delete_organisation(conn, *, org_id) -> None

# Org memberships
insert_org_membership(conn, *, user_id, org_id, role) -> bool
fetch_org_members(conn, *, org_id) -> list[dict]
update_org_membership_role(conn, *, user_id, org_id, role) -> None
delete_org_membership(conn, *, user_id, org_id) -> None
fetch_user_org(conn, *, user_id) -> dict | None  # returns first org for user

# Project registry
insert_project_registry(conn, *, slug, org_id, display_name) -> None
fetch_project_registry(conn, *, slug) -> dict | None
fetch_org_projects(conn, *, org_id) -> list[dict]
fetch_all_registry(conn) -> list[dict]
delete_project_registry(conn, *, slug) -> None

# Project memberships
insert_project_membership(conn, *, user_id, project_slug) -> bool
delete_project_membership(conn, *, user_id, project_slug) -> None
fetch_user_project_memberships(conn, *, user_id) -> list[dict]
has_project_membership(conn, *, user_id, project_slug) -> bool

# Updated user helpers
update_user(conn, *, user_id, email, role, hashed_pw=None) -> None
fetch_user_by_id(conn, *, user_id) -> dict | None
fetch_all_users(conn) -> list[dict]
fetch_users_by_org(conn, *, org_id) -> list[dict]
delete_user(conn, *, user_id) -> None
```

---

## Migration Strategy

`init_system_db` (called on every connection) becomes idempotent and handles:
1. `CREATE TABLE IF NOT EXISTS` for all four new tables
2. `ALTER TABLE users ADD COLUMN email` (skipped if column exists — checked via PRAGMA)
3. `UPDATE users SET role='sysadmin' WHERE role='consultant'` (idempotent — no-op after first run)

No data loss. No destructive operations.

---

## Out of Scope

- Email invitation flow (user-follows-link to set their own password) — Option B, deferred
- Password change UI for end users — future sprint
- Audit log of admin actions — future sprint
- SSO / OAuth login — future sprint
- Per-org ChromaDB namespacing — future sprint
