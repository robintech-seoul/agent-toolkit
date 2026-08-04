# claude/plugins

Product tooling for Claude Code — anything tied to a specific RobinTech product
(Robin-Cloud operations, console workflows, internal services).

| Plugin | Invoked as | What it does |
|---|---|---|
| [`robin-cloud-onboarding`](./robin-cloud-onboarding) | `/robin-cloud-onboarding:onboard` | Onboard a repo to Robin-Cloud end-to-end — generate Dockerfiles + a keyless CI workflow + nginx, then drive the console setup (GitHub App, ECR, deploy config, DB, custom domain + TLS) with verified checkpoints. No cluster access needed. |

`robin-logs` still lives in
[`robintech-seoul/claude-plugins`](https://github.com/robintech-seoul/claude-plugins)
and lands here when the rest of that marketplace is folded into this one.

If the thing you are adding works on any codebase and does not know about a
RobinTech product, it belongs in [`../skills`](../skills) instead.

See the [repo README](../../README.md) for the plugin directory layout and how
to register it in the marketplace manifest.
