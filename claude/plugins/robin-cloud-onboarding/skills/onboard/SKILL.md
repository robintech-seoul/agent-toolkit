---
name: onboard
description: Onboard a project to Robin-Cloud end-to-end. Use when the user wants to deploy THEIR repo (any stack) to Robin-Cloud. Drives the whole flow — analyze the repo, generate Dockerfiles + a keyless CI workflow + nginx, then guide the console setup (create project, GitHub App connect, ECR repos, deploy-config with ports/ingress, DB, secrets, custom domain + TLS) with a verified checkpoint after each step. Assumes NO cluster access (kubectl/tunnel) — verifies via gh, curl, dig, and the console UI.
---

# Robin-Cloud onboarding

Take a customer's repository from "just code" to "running on Robin-Cloud with
keyless CI and HTTPS," driving every step and verifying it. Robin-Cloud runs
containers on k3s; onboarding = **repo files** (Dockerfiles, a keyless CI
workflow, nginx) + **console setup** (project, GitHub App, ECR, deploy-config,
DB, domain). You (the agent) write the repo files and drive the console via
clear instructions, then confirm the effect.

## Operating constraints (read first)

- **No cluster access.** The customer has no kubectl/tunnel. Verify only with
  tools they have: `gh` (their repo/Actions), `curl` (their domain/endpoints),
  `dig` (DNS), and by asking them to read a value off the console UI. Never
  assume kubectl.
- **You can't click the console.** For each console step, give a precise numbered
  instruction, then verify the observable result (a CI run, an HTTP 200, a DNS
  answer) before moving on. One step at a time — confirm, then continue.
- **Robin-Cloud invariants** (bake these into everything):
  - Every container **listens on 8080** (the deploy-config default containerPort).
  - Public entry is **HTTPS 443 only** — 8080 is internal; never put `:8080` in a URL.
  - Images build for **linux/amd64**; the CI workflow already sets this.
  - The gateway/ingress EIP is **`3.35.86.196`** (all Robin-Cloud domains point here).
- Templates live in `${CLAUDE_PLUGIN_ROOT}/templates/` — read them, don't reinvent.

## Prerequisites (confirm before starting)

1. A Robin-Cloud console account with access to a project (login at
   **https://robin-cloud.com**; new signups need an invite code — existing users
   skip it).
2. The repo is on GitHub and the user has `gh` authenticated + admin on the repo.
3. A **log API key** for post-deploy verification/debugging (this is how you read a
   crashing pod's logs without kubectl): console → Settings → **"로그 API 키"** →
   issue a key (`rblog_…`, shown once) → `export ROBIN_LOG_API_KEY=rblog_…`. A
   project OWNER can issue one for their own project. (The `robin-logs` plugin —
   `/plugin marketplace add robintech-seoul/claude-plugins` then
   `/plugin install robin-logs@robin-cloud` — wraps the same endpoints if you
   prefer a helper. It is optional; the raw `curl` calls below need nothing extra.)
4. Docker is available if you want to smoke-build locally (optional — CI builds anyway).

---

## Phase 0 — Analyze the repo

Do this before writing anything. Determine, by reading the repo:

- **Components** = things that get their own image (a frontend SPA, an admin SPA,
  an API server, …). Each maps to an ECR repo `<project>-<module>` and a deploy
  component. Check for a monorepo (pnpm/yarn/npm workspaces, `render.yaml`, a
  `packages`/`apps` layout).
- **Per component**: stack + build command + output + **the port it listens on**
  + entrypoint. Frontends: bundler (Vite base?), `dist` dir, which `VITE_*`/public
  env vars the code reads (`grep import.meta.env.VITE_`). Servers: framework, run
  command, health path, **DB driver** (async? → needs `+asyncpg`), migrations.
- **Shared/sibling imports**: does a frontend import a sibling package (alias like
  `@ds` → `../design-system`, or a workspace lib)? If so its Docker build context
  must be the **repo root** and must COPY those siblings.
- **How it talks to its API**: prefer keeping the frontend's API base **relative
  (`/api/v1`)** so it's same-origin behind one host — no CORS, no rebuild on domain change.

State what you found (components, stacks, ports, API base) and confirm with the user.

## Phase 1 — Generate repo files

Adapt the templates in `${CLAUDE_PLUGIN_ROOT}/templates/` to what you found:

- **Dockerfile per component** — `Dockerfile.vite-spa` (static SPA → nginx) /
  `Dockerfile.python-server` (uv/pip). Enforce: **listen 8080**, multi-stage,
  **build context = repo root** when a monorepo/shared pkg is involved.
- **nginx** per SPA — `nginx-root.conf` for a root SPA, `nginx-subpath.conf` for a
  subpath (see the subpath landmine below).
- **`.github/workflows/deploy-robin-cloud.yml`** — from `deploy-robin-cloud.yml`;
  fill `PROJECT`, the default branch, and one matrix entry + path-filter per
  component. It is self-contained (keyless, no external action) and already parses
  the vend **envelope (`.data.…`)**.
- **`.dockerignore`** at the repo root.

**Verify Phase 1 without deploying**: run each component's real build command
locally (e.g. `pnpm --filter <m> build`, `uv lock --check`) — if it passes, the
Dockerfile's build step will too. Commit on a branch; you'll merge to trigger CI.

## Phase 2 — Console: create project + connect GitHub

Instruct the user (verify each):

1. Console → **new project** named `<project>` (lowercase, RFC-1123). This only
   creates the record; infra comes later on "save deploy config."
2. Project → **"GitHub App으로 연결"** → install the App on this repo → approve the
   OAuth screen → it returns to the console showing "connected: owner/repo (branch)".
   - Must start from the **console button** (not the GitHub App page) — the signed
     state binds the repo to the project; a direct install has nothing to bind.
   - Stay logged in through the round-trip.

Verify: the connect card shows the repo + default branch.

## Phase 3 — Create ECR repos

Console (ECR card) → create one repo per component, named exactly
**`<project>-<module>`** (e.g. `acme-web`, `acme-api`). Robin-Cloud never
auto-creates them (D8). The deploy-config auto-discovery stays "not ready" until a
repo has an image (Phase 4).

## Phase 4 — First CI run (push images)

Merge the Phase-1 branch to the default branch (component dirs changed →
path-filter builds them). For a pure-config change that the filter misses, use
**Actions → Run workflow** (workflow_dispatch builds all).

Verify with the user's tools:
```bash
gh run list --limit 3
gh run view <run-id> --log-failed   # if red
```
Expected: vend HTTP 200 → `aws ecr get-login-password` OK → build/push → the deploy
bump returns **404 (tolerated — project not onboarded yet)**. Images now in ECR →
the console deploy-config auto-discovery flips to **ready**.

## Phase 5 — DB + secrets (server components)

If a component needs a database:
1. Console **DB card** → create it (in-cluster Postgres). It mints
   `POSTGRES_USER/PASSWORD/DB`.
2. Console **Secrets card** → set the server's config. **The DB URL for an async
   server MUST be** `postgresql+asyncpg://<user>:<pw>@<project>-db:5432/<db>` — a
   plain `postgresql://` pulls psycopg2 and crashes on startup. Also set app secrets
   (`SECRET_KEY`, provider keys, etc.). If the user can't read auto-generated creds,
   have them build the URL from the DB card values.
3. Frontends' public build values (e.g. `VITE_TOSS_PROVIDER`, `VITE_PORTONE_*`) are
   **build-args** in the workflow (repo Variables/Secrets), not runtime secrets.

## Phase 6 — Deploy config (ports + ingress) → save

Console **deploy-config** card, per component:
- **Port `8080`** (matches the images — no per-port tweaking).
- **Expose + ingress path**. Recommended single-host layout: **app → `/`**,
  **api/server → `/api`**, extra SPA → **`/<sub>`** (subpath needs the rebuild in
  the landmine below). Frontend at `/` keeps base=`/` working.
- Set the **ingress host** (a `*.robintech.cloud` subdomain works out of the box;
  a custom domain → Phase 8).

**Save.** This scaffolds the gitops chart and provisions the namespace/ingress.
Applying takes **up to ~3 min** (ArgoCD poll) — the customer has no way to force
it, so **wait and re-check**, don't assume it failed.

## Phase 7 — Verify it's live, then the deploy → logs → fix loop

First the outside view:
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/           # app → 200
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/<sub>/     # subpath SPA → 200
```

**Then always read the logs** — a frontend can 200 while the server crashloops, and
a customer has no kubectl, so the log API is your only window in. This is the loop
that catches and fixes the errors deploys actually hit:

```bash
API=https://robin-cloud.com/api/v1/projects/<project>
H="X-Log-Api-Key: $ROBIN_LOG_API_KEY"
# NB: these endpoints wrap the payload in {status, data:{…}} — read .data.*
# 1. list running pods/containers (a crashlooping one shows status here)
curl -sS -H "$H" "$API/log-sources" | jq '.data.sources'
# 2. tail one component's logs — .data.content is the log text
curl -sS -H "$H" "$API/logs?source=<pod>&tail=100" | jq -r '.data.content'
#    (or, if the optional robin-logs plugin is installed, /robin-logs:logs unwraps for you)
```

**Loop:** deploy → pull logs → match the tail against the table below → apply the fix
→ re-verify. A **secret/env fix** takes effect on the next pod restart (the console
re-rolls, or the next deploy); a **code/Dockerfile fix** needs a new push (CI
rebuilds). Re-pull logs until you see the healthy marker (e.g. uvicorn's
`Application startup complete`) and the `curl` returns 200.

### Symptom → cause → fix (from real onboardings)

| In the logs / status | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'psycopg2'` | `DATABASE_URL` uses the sync driver | set it to `postgresql+asyncpg://…` (Secrets card) |
| pod `0/1` forever, no crash, probe timeouts | image not listening on the deploy-config port | make the image listen **8080** (Dockerfile/nginx) → push |
| `password authentication failed` / `could not translate host name` | wrong DB creds/host in `DATABASE_URL` | rebuild the URL from the DB card values; host = `<project>-db`, port 5432 |
| `relation "…" does not exist` / migration errors | schema not migrated | run `alembic upgrade head` (init container / one-off) before serving |
| `KeyError`/`ValidationError` on a config/env at startup | a required secret is unset | add it in the Secrets card (grep the app for the env name) |
| provider "fail-closed" refusal (e.g. `mock not allowed in prod`) | prod requires the real provider | set the provider + its key (e.g. `PASS_PROVIDER=portone` + `PORTONE_API_SECRET`) |
| `ImagePullBackOff` | image/tag not in ECR (repo missing, or push failed) | create the `<project>-<module>` ECR repo; re-run the workflow |
| CI red at ECR login, `UnrecognizedClientException` | vend response read without `.data.` | the template already fixes this — confirm the workflow parses `.data.credentials.*` |

If `log-sources` is empty or the pod never appears, the deploy hasn't landed yet
(ArgoCD lag — wait ~3 min) or the ECR image is missing (check the CI run).

## Phase 8 — Custom domain + TLS (optional)

1. At the customer's DNS: **A record `<domain>` → `3.35.86.196`**. (Skip if using a
   `*.robintech.cloud` subdomain — the wildcard already points there.)
2. Console deploy-config → change the **ingress host** to `<domain>`, save.
3. cert-manager auto-issues a **Let's Encrypt** cert once DNS resolves + the ingress
   has the host (HTTP-01). Wait ~1–2 min after DNS propagates.

Verify:
```bash
dig +short <domain>                 # → 3.35.86.196
curl -s -o /dev/null -w '%{http_code}\n' https://<domain>/   # → 200, valid cert
```
Relative `/api/v1` means no CORS/rebuild on domain change. If real external
providers (Kakao/PASS/Toss) are enabled, add `<domain>` to their redirect/allow lists.

---

## Landmines (every one of these bit a real onboarding — check them)

- **Vend envelope** — `registry-credentials` returns `{status, data:{registry,
  credentials,repositories}}`. Read `.data.…`; reading `.registry`/`.credentials`
  gives `null` → creds become `"null"` → `aws ecr get-login-password` fails with
  `UnrecognizedClientException` ("security token invalid"). The template is correct.
- **Ports** — image not on 8080 → readiness probe fails → pod `0/1` forever. Make
  every image listen 8080; the deploy-config default is 8080.
- **DATABASE_URL** — async server needs `postgresql+asyncpg://…`; `postgresql://`
  → `ModuleNotFoundError: psycopg2` crashloop.
- **Subpath SPA** — a `base:'/'` SPA at `/sub` = white screen (its `/assets/*` load
  from the root app). Fix = **three** changes: Vite `base:'/sub/'` + router
  `basename` + Dockerfile copies `dist` to `/usr/share/nginx/html/sub` + the
  `nginx-subpath.conf`. Build ref then shows `/sub/assets/*`.
- **Trailing slash** — a subpath SPA is reached at `/sub/` (the conf 308-redirects
  bare `/sub`); tell users the trailing slash.
- **`:8080` in a URL** — 8080 is the container port; public is 443. `https://host:8080/…`
  = "can't connect." Always `https://host/…`.
- **ArgoCD lag** — deploy-config/domain edits apply within ~3 min (git poll). Don't
  re-save frantically; wait and re-verify.
- **Build context** — a monorepo frontend built with context = its own dir can't
  reach shared siblings (`../design-system`). Use context = repo root + `-f <m>/Dockerfile`.
- **Deploy bump 404 on the first run** is EXPECTED (project not onboarded yet). The
  image still pushes; deploy-config save + next push bumps for real.
- **GitHub connect** must start from the console button (signed state), while logged
  in, in one pass — a direct App install can't bind to a project.

## Verification cheatsheet (customer-side only)

```bash
gh run list --limit 3 ; gh run view <id> --log-failed        # CI
curl -sk -o /dev/null -w '%{http_code}\n' https://<host>/    # app up
dig +short <domain>                                          # DNS → 3.35.86.196
# pod logs (the only in-cluster window without kubectl; responses are .data.*):
API=https://robin-cloud.com/api/v1/projects/<project> ; H="X-Log-Api-Key: $ROBIN_LOG_API_KEY"
curl -sS -H "$H" "$API/log-sources" | jq '.data.sources'            # running pods/containers
curl -sS -H "$H" "$API/logs?source=<pod>&tail=100" | jq -r '.data.content'  # log tail
```
Pod status / crash reasons come from the log API above (or the `robin-logs`
plugin); secret values from the console UI — never assume kubectl.
