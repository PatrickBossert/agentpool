# FutureMomentum Deployment Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make FutureMomentum (formerly AgentPool) accessible to external stakeholders for voice interviews and to consultants for the dashboard, running from a laptop with zero infrastructure overhead.

**Architecture:** Caddy reverse proxy sits in front of all local services on port 80. cloudflared tunnels that single port through Cloudflare's edge to `futuremomentum.ai`. Cloudflare Access protects `/dashboard/*` with email OTP. The interview route `/interview/:token` is public. The homepage `/` serves a static placeholder.

**Tech Stack:** Caddy 2, cloudflared, Cloudflare Zero Trust, React (Vite base path), IONOS SMTP via n8n.

---

## Domain & DNS

`futuremomentum.ai` is already registered and managed in Cloudflare — no nameserver changes needed. The Cloudflare Tunnel setup automatically creates the CNAME record when a public hostname is added in Zero Trust.

**Planned URLs:**
- `https://futuremomentum.ai/` — static landing placeholder (public)
- `https://futuremomentum.ai/dashboard/*` — React SPA consultant dashboard (Cloudflare Access, email OTP)
- `https://futuremomentum.ai/interview/:token` — stakeholder voice interview (public, no login)
- `https://futuremomentum.ai/api/*` — FastAPI backend (JWT auth enforced by FastAPI, not Cloudflare)

---

## Components

### 1. Caddy reverse proxy

Caddy runs on `:80` locally and is the single port cloudflared exposes. Routing by path:

```
:80 {
  # API requests — FastAPI handles auth
  handle /api/* {
    reverse_proxy localhost:8000
  }
  # Interview and dashboard are both React SPA routes
  handle /interview/* {
    reverse_proxy localhost:5173
  }
  handle /dashboard* {
    reverse_proxy localhost:5173
  }
  # Homepage — static landing page
  handle {
    root * /path/to/agentpool1/landing
    file_server
  }
}
```

> Note: `/interview/:token` is a React route (rendered by the SPA), not a FastAPI endpoint. Only `/api/interviews/*` goes to FastAPI. Caddy proxies both `/interview/*` and `/dashboard*` to the Vite dev server.

Cloudflare terminates TLS externally, so Caddy only needs HTTP. The tunnel connection itself is encrypted by cloudflared regardless.

### 2. cloudflared (Cloudflare Tunnel daemon)

Installed via Homebrew (`brew install cloudflared`). Runs as a background process alongside the other services. Authenticates to Cloudflare using a tunnel token stored in `.env`.

```bash
cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN"
```

No inbound firewall ports are needed — cloudflared makes outbound-only connections. Works behind corporate firewalls, hotel wifi, and NAT.

**One-time Cloudflare setup (done in the dashboard, not in code):**
1. Cloudflare Zero Trust → Networks → Tunnels → Create tunnel → copy token
2. Add public hostname: `futuremomentum.ai` → Service: `http://localhost:80`
3. Cloudflare auto-creates the CNAME record in DNS

### 3. Cloudflare Access policy

Protects the consultant dashboard. Set up in Cloudflare Zero Trust → Access → Applications.

- **Application:** `futuremomentum.ai/dashboard*`
- **Policy:** Allow — email OTP — include `*@futureedge.consulting` (add other consultant emails as needed)
- **Bypass rules:**
  - `/interview/*` — public (stakeholders)
  - `/api/*` — public at Cloudflare layer (FastAPI enforces JWT)

Cloudflare Access injects a `CF-Access-Jwt-Assertion` header on authenticated requests. The React app does not need to validate this — it has its own JWT login flow and `ProtectedRoute`. The Access policy is a second layer of defence, not the primary auth mechanism.

### 4. React app — base path change

The React SPA moves from root to `/dashboard` base path. Two changes:

**`ui/vite.config.ts`:**
```ts
export default defineConfig({
  base: '/dashboard',
  // ... rest of config unchanged
})
```

**`ui/src/router.tsx`:**
```tsx
<BrowserRouter basename="/dashboard">
```

All `<Link>`, `useNavigate`, and relative hrefs continue to work unchanged — React Router resolves them relative to the basename. The `window.open(`/${slug}/report`, '_blank')` call in Dashboard.tsx needs updating to `/dashboard/${slug}/report`.

### 5. Static landing page

A minimal `landing/index.html` file served by Caddy at `/`. Placeholder content — room to evolve into a marketing page.

```
landing/
  index.html   ← "FutureMomentum.ai — Coming Soon"
```

### 6. IONOS SMTP via n8n

n8n already dispatches campaign reminder emails. A new SMTP credential is added in n8n's credential store for sending interview invitation emails.

**Credential settings (configured in n8n UI — not in code):**
- Type: SMTP
- Host: `smtp.ionos.co.uk`
- Port: `587`
- Security: STARTTLS
- Username: IONOS email address (e.g. `hello@futureedge.consulting`)
- Password: IONOS email account password

The interview invitation email body uses the stable public URL:
```
https://futuremomentum.ai/interview/{{session_token}}
```

### 7. start.sh additions

Two new processes join the existing service startup:

```bash
echo "Starting Caddy on :80..."
caddy run --config Caddyfile --adapter caddyfile &
echo $! > .pids/caddy.pid

echo "Starting Cloudflare Tunnel..."
cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN" &
echo $! > .pids/cloudflared.pid
```

`CLOUDFLARE_TUNNEL_TOKEN` is added to `.env`. The `stop.sh` script already kills all `.pids/*.pid` processes, so no changes needed there.

### 8. Rebranding pass

The internal name "AgentPool" is replaced with "FutureMomentum" in user-visible strings:

- `chainlit_app/app.py` — Chainlit app title
- `ui/index.html` — `<title>` tag
- `ui/src/` — any hardcoded "AgentPool" strings in UI copy
- `docker-compose.yml` — container labels (cosmetic)
- `README.md` if present

The Python package name, directory name, and import paths stay as-is — renaming the repo directory is unnecessary churn.

---

## What Stays Internal Only

These services are never exposed through the tunnel:
- ChromaDB `:8002`
- n8n `:5678`
- Chainlit `:8001`
- Ollama `:11434`
- LiteLLM `:4000`

---

## Security Notes

- The tunnel token in `.env` must not be committed to git. `.env` is already in `.gitignore`.
- Cloudflare Access email OTP means a stolen session cookie is useless without access to the consultant's email.
- The interview session token in the URL is the only credential stakeholders need — it is single-use by design (one stakeholder, one session).
- The local Ollama/LiteLLM never receive external traffic — they are fully air-gapped from the tunnel.

---

## Dependencies to Install

```bash
brew install caddy
brew install cloudflare/cloudflare/cloudflared
```

Both are available via Homebrew on macOS/Apple Silicon.

---

## Environment Variables Added to .env

```
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Zero Trust dashboard>
```
