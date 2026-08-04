# robin-cloud-onboarding

Onboard **your** project to [Robin-Cloud](https://robin-cloud.com) end-to-end with
an AI agent — no cluster access required. The agent analyzes your repo, generates
the Dockerfiles + a **keyless CI workflow** (zero repo secrets) + nginx, then walks
you through the console setup (project, GitHub App, ECR, deploy-config, DB, custom
domain + TLS), verifying each step with tools you already have (`gh`, `curl`, `dig`).

Distilled from real onboardings — every landmine that bit us (vend-response
envelope, port 8080, `postgresql+asyncpg://`, subpath SPAs, custom-domain TLS,
ArgoCD apply lag) is encoded so your run avoids them.

## Install

```bash
/plugin marketplace add robintech-seoul/agent-toolkit
/plugin install robin-cloud-onboarding@robintech
```

## Use

In your project repo, with Claude Code:

```
/robin-cloud-onboarding:onboard     # or just: "onboard this repo to Robin-Cloud"
```

The `onboard` skill drives the flow. You do the console clicks it hands you; it
writes the repo files and confirms the effect after each step.

## What it produces in your repo

- `<component>/Dockerfile` — one per image (SPA → nginx:8080, Python → uvicorn:8080),
  built for `linux/amd64`, monorepo-aware (repo-root context).
- `<component>/nginx.conf` — SPA serving (root or subpath).
- `.github/workflows/deploy-robin-cloud.yml` — keyless deploy: GitHub OIDC → vend
  short-lived project-scoped ECR creds → build/push → request deploy. **No secrets.**
- `.dockerignore`.

Templates live in [`templates/`](./templates); the runbook is
[`skills/onboard/SKILL.md`](./skills/onboard/SKILL.md).

## Requirements

- A Robin-Cloud console account with a project (https://robin-cloud.com).
- `gh` authenticated + admin on the GitHub repo.
- The gateway/ingress IP for custom-domain A records is `3.35.86.196`.
