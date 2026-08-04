# Onboard your project to Robin-Cloud

Deploy your app on **[Robin-Cloud](https://robin-cloud.com)** with an AI agent doing
the heavy lifting. The **`robin-cloud-onboarding`** Claude Code plugin reads your
repo, writes the deployment files, walks you through the console, ships it, and — if
anything breaks — reads the logs and fixes it. You don't need any cluster access.

---

## What you get

- **Keyless CI** — deploys straight from GitHub Actions with **zero secrets** in your
  repo (no AWS keys, no tokens). GitHub's OIDC identity is exchanged for short-lived,
  project-scoped credentials at build time.
- **Managed containers** on Kubernetes (k3s), with **automatic HTTPS/TLS**.
- **Your own domain** — point a DNS record and you're live on it.
- **Self-healing onboarding** — the agent verifies every step and debugs failures
  from your app's logs.

## How it works, in one breath

You run one command in your repo. The agent then:

1. **Analyzes** your project — finds each deployable piece (frontend, admin, API…),
   its stack, build command, and port.
2. **Generates** the repo files — a `Dockerfile` per piece, a keyless CI workflow,
   nginx config, `.dockerignore`.
3. **Guides the console** — hands you exact clicks (create project, connect GitHub,
   create image repos, deploy config, database, domain) and confirms each worked.
4. **Deploys and verifies** — watches the build, curls your site, reads the logs, and
   fixes common failures until it's green.

## Before you start

| You need | Where |
|---|---|
| A Robin-Cloud console account | https://robin-cloud.com (new signups need an invite code) |
| Your repo on GitHub + `gh` CLI logged in | `gh auth login` |
| A **log API key** (lets the agent read logs without cluster access) | console → Settings → **"로그 API 키"** → issue → `export ROBIN_LOG_API_KEY=rblog_…` |
| [Claude Code](https://claude.com/claude-code) | in your repo |

## Step 1 — Install the plugin

```bash
/plugin marketplace add robintech-seoul/agent-toolkit
/plugin install robin-cloud-onboarding@robintech
```

## Step 2 — Run it

In your project repo:

```
/robin-cloud-onboarding:onboard
```

*(or just say: "onboard this repo to Robin-Cloud")*

The agent takes it from there. **Your part** is the console clicks it hands you, one
at a time; **its part** is writing the files, running the build, and verifying.

## What the agent writes in your repo

- `<component>/Dockerfile` — one per image (a static SPA served by nginx, a Python/
  Node server, …), built for the platform and listening on the standard port.
- `<component>/nginx.conf` — for frontends.
- `.github/workflows/deploy-robin-cloud.yml` — the **keyless** deploy pipeline.
- `.dockerignore`.

## What you'll do in the console

The agent tells you exactly when and what. In order:

1. **Create the project.**
2. **Connect GitHub** — click "GitHub App으로 연결," install it on your repo, approve.
3. **Create image (ECR) repos** — one per component.
4. **Save the deploy config** — ports and which path each piece is served at.
5. **Create a database** and set your secrets (if you have a server).
6. **(Optional) Point your domain.**

## If something breaks

You don't debug alone. The agent pulls your pod logs over HTTPS (the same log API
key from setup — no `kubectl` needed) and recognizes the usual culprits — a database
URL using the wrong driver, a missing secret, an un-run migration, a port mismatch —
and fixes them, then re-checks until your app answers `200`.

## Good to know

- **URLs have no port.** Everything runs on port 8080 *inside* the cluster; you reach
  it over normal **HTTPS** — `https://yourdomain/`, never `:8080`.
- **Custom domain?** Point its DNS **A record to `3.35.86.196`** (the Robin-Cloud
  gateway), then set it as the ingress host in the deploy config — TLS is issued
  automatically. (A `*.robintech.cloud` subdomain already points there.)
- **A second app at a subpath** (e.g. an admin at `/admin`) is reached **with a
  trailing slash**: `https://yourdomain/admin/`.

---

*Questions or a stuck onboarding? The agent's runbook lives in
[`skills/onboard/SKILL.md`](./skills/onboard/SKILL.md); the templates it adapts are
in [`templates/`](./templates).*
