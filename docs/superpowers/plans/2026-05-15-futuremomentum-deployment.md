# FutureMomentum Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make FutureMomentum accessible externally — stakeholders reach voice interviews via public URL, consultants access the dashboard via Cloudflare Access email OTP — all running from a laptop with zero infrastructure overhead.

**Architecture:** Caddy reverse proxy on `:80` routes three zones: `/api/*` → FastAPI :8000, `/dashboard*` → Vite dev server :3000, `/` → static landing HTML. cloudflared tunnels `:80` to `futuremomentum.ai` via Cloudflare's edge (outbound-only, no inbound firewall changes). Cloudflare Access protects `/dashboard/*` with email OTP, bypassing `/dashboard/interview/*` for public stakeholder access. React SPA uses `base: '/dashboard'` in Vite + `basename: '/dashboard'` in React Router so all app routes live under the `/dashboard` prefix.

**Tech Stack:** Caddy 2, cloudflared, Cloudflare Zero Trust, React Router v6 `createBrowserRouter`, Vite, FastAPI.

---

## Pre-flight: Manual Cloudflare & Resend Setup

These are one-time steps done in web dashboards — not code. Complete them before running the smoke test in Task 7.

**Cloudflare Zero Trust tunnel:**
1. Go to [Cloudflare Zero Trust](https://one.dash.cloudflare.com) → Networks → Tunnels → Create Tunnel
2. Copy the tunnel token
3. Add public hostname: domain `futuremomentum.ai` → Service: `http://localhost:80`
4. Cloudflare auto-creates the required CNAME in DNS

**Cloudflare Access policy:**
1. Zero Trust → Access → Applications → Add Application → Self-hosted
2. App domain: `futuremomentum.ai/dashboard*`
3. Policy: Allow — email OTP — include your consultant email domain(s)
4. Add bypass rules:
   - `/dashboard/interview/*` — public (stakeholder voice interviews)
   - `/api/*` — public at Cloudflare layer (FastAPI enforces JWT)

**Resend SMTP:**
1. Create account at resend.com
2. Add domain `futuremomentum.ai` → copy the DKIM DNS record Resend generates
3. Add that TXT record in Cloudflare DNS (domain already managed there)
4. In n8n: Credentials → New → SMTP → Host: `smtp.resend.com`, Port: `465`, Security: SSL/TLS, Username: `resend`, Password: your Resend API key
5. Update interview invitation email body URL to: `https://futuremomentum.ai/dashboard/interview/{{session_token}}`

> **Note on interview URL:** The React SPA uses `base: '/dashboard'` in Vite and `basename: '/dashboard'` in React Router. This means all SPA routes — including the public interview page — are served under `/dashboard`. The stakeholder interview URL is therefore `https://futuremomentum.ai/dashboard/interview/:token` (not `/interview/:token`). The Cloudflare Access bypass rule for `/dashboard/interview/*` ensures this route remains publicly accessible.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `Caddyfile` | Create | Path-based routing: dashboard + API + landing |
| `landing/index.html` | Create | Static "Coming Soon" homepage served at `/` |
| `.env` | Modify | Add `CLOUDFLARE_TUNNEL_TOKEN` |
| `ui/vite.config.ts` | Modify | Add `base: '/dashboard'` |
| `ui/src/router.tsx` | Modify | Add `basename: '/dashboard'` to createBrowserRouter |
| `ui/src/pages/Dashboard.tsx` | Modify | Fix `window.open` URL for report |
| `start.sh` | Modify | Add Caddy and cloudflared process management |
| `ui/index.html` | Modify | Rebrand `<title>` from AgentPool → FutureMomentum |
| `chainlit_app/app.py` | Modify | Rebrand title + greeting strings |

---

## Task 1: Install Caddy and cloudflared

**Files:**
- Modify: `.env`

> This task has no automated tests — verification is done by running the binaries.

- [ ] **Step 1: Install Caddy via Homebrew**

```bash
brew install caddy
caddy version
```

Expected: output like `v2.x.x`

- [ ] **Step 2: Install cloudflared via Homebrew**

```bash
brew install cloudflare/cloudflare/cloudflared
cloudflared --version
```

Expected: output like `cloudflared version 20xx.x.x`

- [ ] **Step 3: Add tunnel token to .env**

Open `.env` and append:

```
CLOUDFLARE_TUNNEL_TOKEN=<paste token from Cloudflare Zero Trust dashboard>
```

> The token is obtained from the "Pre-flight" step above. Leave the placeholder text if you haven't created the tunnel yet — the cloudflared process will fail to authenticate but that's fine for local-only testing.

- [ ] **Step 4: Verify .env is gitignored**

```bash
git check-ignore -q .env && echo "IGNORED (good)" || echo "NOT IGNORED — add to .gitignore"
```

Expected: `IGNORED (good)`

- [ ] **Step 5: Commit**

```bash
git add .env   # git will reject this if .env is gitignored — that's correct
# Only commit if the token placeholder line was added to .env.example or similar
# If .env is gitignored, no commit needed for this task
git commit -m "chore: add CLOUDFLARE_TUNNEL_TOKEN placeholder to .env.example" --allow-empty
```

> If the project has a `.env.example`, add `CLOUDFLARE_TUNNEL_TOKEN=` there and commit that instead. If not, skip the commit — `.env` must not be committed.

---

## Task 2: Create Caddyfile

**Files:**
- Create: `Caddyfile`

> Caddy uses a declarative config format. No automated tests — verify by running `caddy validate`.

- [ ] **Step 1: Find the landing directory absolute path**

```bash
echo "$(pwd)/landing"
```

Note the output — you'll use it in the Caddyfile.

- [ ] **Step 2: Create the Caddyfile**

Create `Caddyfile` at the project root with this exact content (replace `/ABSOLUTE/PATH/TO/agentpool1` with the real path from Step 1):

```caddyfile
:80 {
	# API — FastAPI handles JWT auth
	handle /api/* {
		reverse_proxy localhost:8000
	}

	# Dashboard and all SPA routes (including public interview under /dashboard/interview/*)
	handle /dashboard* {
		reverse_proxy localhost:3000
	}

	# Homepage — static landing page
	handle {
		root * /ABSOLUTE/PATH/TO/agentpool1/landing
		file_server
	}
}
```

- [ ] **Step 3: Validate the Caddyfile**

```bash
caddy validate --config Caddyfile --adapter caddyfile
```

Expected: `Valid configuration`

- [ ] **Step 4: Commit**

```bash
git add Caddyfile
git commit -m "feat: add Caddyfile for local reverse proxy routing"
```

---

## Task 3: Create static landing page

**Files:**
- Create: `landing/index.html`

- [ ] **Step 1: Create landing directory and index.html**

```bash
mkdir -p landing
```

Create `landing/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>FutureMomentum — AI-powered transformation intelligence</title>
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        background: #0f172a;
        color: #e2e8f0;
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
      }
      .container { max-width: 480px; padding: 2rem; }
      h1 {
        font-size: 2rem;
        font-weight: 700;
        letter-spacing: -0.5px;
        margin-bottom: 0.75rem;
      }
      .accent { color: #0d9488; }
      p {
        color: #94a3b8;
        font-size: 1rem;
        line-height: 1.6;
      }
    </style>
  </head>
  <body>
    <div class="container">
      <h1>Future<span class="accent">Momentum</span></h1>
      <p>AI-powered transformation intelligence. Coming soon.</p>
    </div>
  </body>
</html>
```

- [ ] **Step 2: Verify Caddy serves the landing page**

```bash
# Start Caddy in the background
caddy run --config Caddyfile --adapter caddyfile &
sleep 1

# Fetch the landing page
curl -s http://localhost:80/ | grep -q "FutureMomentum" && echo "PASS" || echo "FAIL"

# Stop Caddy
kill %1
```

Expected: `PASS`

- [ ] **Step 3: Commit**

```bash
git add landing/index.html
git commit -m "feat: add static landing page for futuremomentum.ai homepage"
```

---

## Task 4: React SPA base path + router basename

**Files:**
- Modify: `ui/vite.config.ts`
- Modify: `ui/src/router.tsx`
- Modify: `ui/src/pages/Dashboard.tsx`

> Setting `base: '/dashboard'` in Vite changes ALL asset paths (JS, CSS, fonts) to be prefixed with `/dashboard`. `basename: '/dashboard'` in React Router tells it to strip that prefix before matching routes. Together they mean the browser URL `futuremomentum.ai/dashboard/login` maps to the `<Login />` component at path `/login` in the router config.

- [ ] **Step 1: Add base to vite.config.ts**

Current `ui/vite.config.ts`:
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    environmentOptions: { jsdom: { url: 'http://localhost' } },
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
})
```

Updated `ui/vite.config.ts`:
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({
  base: '/dashboard',
  plugins: [react()],
  test: {
    environment: 'jsdom',
    environmentOptions: { jsdom: { url: 'http://localhost' } },
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
})
```

- [ ] **Step 2: Add basename to createBrowserRouter in router.tsx**

Current `ui/src/router.tsx` (line 31):
```tsx
export const router = createBrowserRouter([
```

Updated:
```tsx
export const router = createBrowserRouter([
  // ... all routes unchanged ...
], { basename: '/dashboard' })
```

Full updated `ui/src/router.tsx`:

```tsx
// ui/src/router.tsx
import { createBrowserRouter, Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './context/AuthContext'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import ValueChain from './pages/ValueChain'
import Roadmap from './pages/Roadmap'
import RunDetail from './pages/RunDetail'
import Settings from './pages/Settings'
import BusinessPlan from './pages/BusinessPlan'
import Reviews from './pages/Reviews'
import Runs from './pages/Runs'
import Stakeholders from './pages/Stakeholders'
import StakeholderForm from './pages/StakeholderForm'
import Discovery from './pages/Discovery'
import ValuePropositions from './pages/ValuePropositions'
import Assignment from './pages/Assignment'
import VoiceInterview from './pages/VoiceInterview'
import Templates from './pages/Templates'
import Report from './pages/Report'

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
  },
  {
    path: '/interview/:sessionToken',
    element: <VoiceInterview />,
  },
  {
    path: '/:slug/report',
    element: (
      <ProtectedRoute>
        <Report />
      </ProtectedRoute>
    ),
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <Dashboard /> },
      { path: ':slug', element: <Dashboard /> },
      { path: ':slug/discovery', element: <Discovery /> },
      { path: ':slug/value-chain', element: <ValueChain /> },
      { path: ':slug/value-propositions', element: <ValuePropositions /> },
      { path: ':slug/roadmap', element: <Roadmap /> },
      { path: ':slug/stakeholders', element: <Stakeholders /> },
      { path: ':slug/stakeholders/new', element: <StakeholderForm /> },
      { path: ':slug/stakeholders/:id/edit', element: <StakeholderForm /> },
      { path: ':slug/business-plan', element: <BusinessPlan /> },
      { path: ':slug/reviews', element: <Reviews /> },
      { path: ':slug/runs', element: <Runs /> },
      { path: ':slug/documents', element: <Documents /> },
      { path: ':slug/runs/:runId', element: <RunDetail /> },
      { path: ':slug/assignment', element: <Assignment /> },
      { path: ':slug/templates', element: <Templates /> },
      { path: ':slug/settings', element: <Settings /> },
    ],
  },
], { basename: '/dashboard' })
```

- [ ] **Step 3: Fix window.open in Dashboard.tsx**

In `ui/src/pages/Dashboard.tsx`, line 79, change:

```tsx
onClick={() => window.open(`/${slug}/report`, '_blank')}
```

to:

```tsx
onClick={() => window.open(`/dashboard/${slug}/report`, '_blank')}
```

- [ ] **Step 4: Run existing UI tests to confirm nothing broke**

```bash
cd ui && npm test -- --run 2>&1 | tail -20
```

Expected: all tests pass (the tests use `jsdom` with `url: 'http://localhost'` so they run against root-relative URLs and aren't affected by the `base` config, which only affects the production build output).

- [ ] **Step 5: Manual smoke test — start Vite and verify routing**

```bash
cd ui && npm run dev -- --port 3000 &
sleep 3

# Dashboard root should redirect to /login
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/dashboard/
# Expected: 200 (Vite serves index.html for all SPA routes)

# Interview page should be accessible
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/dashboard/interview/test-token
# Expected: 200

kill %1
```

- [ ] **Step 6: Commit**

```bash
cd ..
git add ui/vite.config.ts ui/src/router.tsx ui/src/pages/Dashboard.tsx
git commit -m "feat: set /dashboard base path for React SPA and fix report window.open URL"
```

---

## Task 5: Update start.sh

**Files:**
- Modify: `start.sh`

> start.sh currently sources `.venv/bin/activate` which doesn't exist — the project uses Homebrew Python 3.13 globally. This task also fixes that and adds Caddy + cloudflared.

- [ ] **Step 1: Update start.sh**

Replace the entire contents of `start.sh` with:

```bash
#!/usr/bin/env bash
# start.sh — start all FutureMomentum services
set -e
cd "$(dirname "$0")"

# Load environment variables
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

mkdir -p .pids

echo "Starting Docker services (ChromaDB + n8n)..."
docker compose up -d

echo "Starting LiteLLM proxy on :4000..."
litellm --config litellm_config.yaml --port 4000 &
echo $! > .pids/litellm.pid

echo "Starting FastAPI on :8000..."
/opt/homebrew/bin/python3.13 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload &
echo $! > .pids/fastapi.pid

echo "Starting Chainlit on :8001..."
cd chainlit_app && /opt/homebrew/bin/chainlit run app.py --port 8001 &
echo $! > .pids/chainlit.pid
cd ..

echo "Starting React UI on :3000..."
cd ui && npm run dev -- --port 3000 &
echo $! > ../.pids/ui.pid
cd ..

echo "Starting Caddy on :80..."
caddy run --config Caddyfile --adapter caddyfile &
echo $! > .pids/caddy.pid

echo "Starting Cloudflare Tunnel..."
cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN" &
echo $! > .pids/cloudflared.pid

echo ""
echo "FutureMomentum services running:"
echo "  FastAPI:      http://localhost:8000/docs"
echo "  Chainlit:     http://localhost:8001"
echo "  React UI:     http://localhost:3000"
echo "  Caddy (local) http://localhost:80"
echo "  n8n:          http://localhost:5678"
echo "  ChromaDB:     http://localhost:8002"
echo "  LiteLLM:      http://localhost:4000"
echo "  Public URL:   https://futuremomentum.ai/dashboard"
```

- [ ] **Step 2: Make start.sh executable**

```bash
chmod +x start.sh
```

- [ ] **Step 3: Verify syntax**

```bash
bash -n start.sh && echo "PASS: no syntax errors"
```

Expected: `PASS: no syntax errors`

- [ ] **Step 4: Commit**

```bash
git add start.sh
git commit -m "feat: update start.sh — add Caddy + cloudflared, fix Python path, rebrand echo output"
```

---

## Task 6: Rebranding pass

**Files:**
- Modify: `ui/index.html`
- Modify: `chainlit_app/app.py`

> The Python package name, directory name, and import paths stay unchanged. Only user-visible strings are updated.

- [ ] **Step 1: Update ui/index.html title**

Current `ui/index.html` line 6:
```html
    <title>AgentPool</title>
```

Updated:
```html
    <title>FutureMomentum</title>
```

- [ ] **Step 2: Update Chainlit app title and greeting**

Read `chainlit_app/app.py` lines 1-50 to find the exact strings, then make the following changes:

Line 3 — module docstring:
```python
# Before:
AgentPool Chainlit HITL interface.

# After:
FutureMomentum Chainlit HITL interface.
```

Line 42 — greeting message (update the `AgentPool` reference):
```python
# Before:
            "**AgentPool** — Digital Modernisation Agent Team\n\n"

# After:
            "**FutureMomentum** — Digital Modernisation Agent Team\n\n"
```

- [ ] **Step 3: Verify no other AgentPool user-visible strings remain**

```bash
grep -rn "AgentPool\|agentpool" \
  ui/index.html \
  ui/src/ \
  chainlit_app/ \
  --include="*.html" --include="*.tsx" --include="*.ts" --include="*.py" \
  | grep -v "node_modules" | grep -v ".pyc"
```

Review the output. Any remaining hits in Python imports (`from agentpool...`), directory names, or package names are intentionally left unchanged. Only user-visible copy needs rebranding.

- [ ] **Step 4: Commit**

```bash
git add ui/index.html chainlit_app/app.py
git commit -m "feat: rebrand user-visible strings from AgentPool to FutureMomentum"
```

---

## Task 7: End-to-end smoke test

> This task verifies all the pieces work together locally before going live with the tunnel.

- [ ] **Step 1: Start all services**

```bash
./start.sh
```

Wait ~10 seconds for services to initialise.

- [ ] **Step 2: Verify Caddy routing**

```bash
# Landing page at root
curl -s http://localhost:80/ | grep -q "FutureMomentum" && echo "PASS: landing page" || echo "FAIL: landing page"

# Dashboard route served by Vite (returns 200 with the SPA shell)
curl -s -o /dev/null -w "%{http_code}" http://localhost:80/dashboard/ | grep -q "200" && echo "PASS: dashboard route" || echo "FAIL: dashboard route"

# Interview route served by Vite
curl -s -o /dev/null -w "%{http_code}" http://localhost:80/dashboard/interview/test-token | grep -q "200" && echo "PASS: interview route" || echo "FAIL: interview route"

# API route
curl -s -o /dev/null -w "%{http_code}" http://localhost:80/api/health | grep -q "200" && echo "PASS: API health" || echo "FAIL: API health"
```

Expected: all four `PASS`.

> If the API health check fails, try `curl http://localhost:8000/api/health` to confirm FastAPI is running separately, then check Caddy logs with `tail -f /tmp/caddy.log` or run `caddy run --config Caddyfile --adapter caddyfile` in the foreground to see errors.

- [ ] **Step 3: Verify React app loads in browser**

Open `http://localhost:80/dashboard` in a browser. You should see the FutureMomentum login page (or dashboard if already logged in). The browser URL bar should read `.../dashboard/login` after redirect — confirming the basename is working.

- [ ] **Step 4: Verify the report opens with correct URL**

Log in to the dashboard, open a project, click "Export Report". Verify the new tab opens at `/dashboard/:slug/report` (not `/:slug/report`).

- [ ] **Step 5: Verify tunnel (if CLOUDFLARE_TUNNEL_TOKEN is set)**

```bash
# Check cloudflared is running
cat .pids/cloudflared.pid | xargs ps -p | grep cloudflared && echo "PASS: tunnel running" || echo "FAIL: tunnel not running"
```

Then open `https://futuremomentum.ai/dashboard` in a browser. You should see the Cloudflare Access email OTP screen. Enter a permitted email, verify the OTP, and confirm the dashboard loads.

- [ ] **Step 6: Verify public interview URL is accessible without OTP**

Open `https://futuremomentum.ai/dashboard/interview/test-token` in a private browser window. It should load the voice interview page **without** triggering the Cloudflare Access OTP. If it asks for email, the bypass rule for `/dashboard/interview/*` is not configured — go back to the Pre-flight section.

- [ ] **Step 7: Stop services**

```bash
./stop.sh
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Caddy on :80 with path routing | Task 2 |
| cloudflared tunnel | Task 1 + Task 5 |
| Cloudflare Access on /dashboard/* | Pre-flight (manual) |
| Public interview bypass | Pre-flight (manual) |
| React base: '/dashboard' | Task 4 |
| BrowserRouter basename | Task 4 |
| window.open report URL fix | Task 4 |
| Static landing page | Task 3 |
| Resend SMTP setup | Pre-flight (manual) |
| start.sh additions | Task 5 |
| Rebranding (ui/index.html, chainlit) | Task 6 |
| CLOUDFLARE_TUNNEL_TOKEN in .env | Task 1 |

**Deviations from spec:**

1. **Interview URL is `/dashboard/interview/:token` not `/interview/:token`** — The React SPA with `base: '/dashboard'` and `basename: '/dashboard'` cannot serve routes outside the `/dashboard` prefix without a separate entry point. Moving the interview URL under `/dashboard` is the cleanest solution. The Cloudflare Access bypass rule for `/dashboard/interview/*` keeps it publicly accessible. Update the n8n email template accordingly.

2. **start.sh uses `/opt/homebrew/bin/python3.13` directly** — The original `source .venv/bin/activate` references a venv that doesn't exist. The project runs on Homebrew Python 3.13 with crewai installed globally via `pip3.13`. If the deployment machine differs, update the Python path.

3. **`docker-compose.yml` rebranding skipped** — Container labels are internal-only and don't affect user-visible behaviour. Not worth the merge risk.
