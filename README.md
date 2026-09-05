# RobinTech agent toolkit

Agent tooling RobinTech builds and uses. One repo, one marketplace, organized by
the agent it targets — so adding support for another agent later does not mean
another marketplace to install.

```
claude/
├── plugins/   product tooling — tied to a RobinTech product
└── skills/    general-purpose skills — work on any codebase, any stack
```

Everything under `claude/` installs through a single Claude Code marketplace,
**`robintech`**. Support for other agents gets its own top-level directory
alongside `claude/`.

## Install

```bash
# add the marketplace once, then install what you want from it
/plugin marketplace add robintech-seoul/agent-toolkit
/plugin install arch-explorer@robintech
```

(or via the CLI: `claude plugin marketplace add robintech-seoul/agent-toolkit`
then `claude plugin install arch-explorer@robintech`.)

## What's here

| | What it does |
|---|---|
| [`arch-explorer`](./claude/skills/arch-explorer) | Map a codebase into a single self-contained HTML file you can drill through — boxes are modules, labeled arrows are the interfaces between them, each expanding to full signatures and `file:line` sources. |
| [`code-wiki`](./claude/skills/code-wiki) | Build and maintain a hierarchical, LLM-generated wiki over a codebase — leaf folders summarize their files, parents synthesize their children, topic pages capture cross-cutting concerns, and `sync` keeps it current as the source changes. Committed to the repo, so the synthesis cost is paid once per team. |
| [`mvp-builder`](./claude/skills/mvp-builder) | Take an idea to an MVP through a gated pipeline — spec → your approval → design/review loops → your approval → build. Ledger-based delta review, machine gates on every phase, built-in agent-skills (`--full`) or lightweight prompts (`--lite`). |
| [`robin-cloud-onboarding`](./claude/plugins/robin-cloud-onboarding) | Onboard a repo to [Robin-Cloud](https://robin-cloud.com) end-to-end — generate Dockerfiles + a keyless CI workflow + nginx, then drive the console setup (GitHub App, ECR, deploy config, DB, custom domain + TLS) with verified checkpoints. No cluster access needed. |

## Adding to the marketplace

Claude Code installs **plugins**, so everything here — including a lone skill —
ships as a plugin directory listed in
[`.claude-plugin/marketplace.json`](./.claude-plugin/marketplace.json) with a
relative `source`. Put it under `claude/plugins/` if it is tied to a product,
`claude/skills/` if it works anywhere.

```
claude/skills/<name>/
├── .claude-plugin/plugin.json      # name, version, description, keywords
├── README.md                       # what it does + install/use
└── skills/<command>/SKILL.md       # frontmatter: name, description
```

The plugin name and the `SKILL.md` name combine into how it is invoked —
`arch-explorer/skills/build/` becomes `/arch-explorer:build`. A plugin can carry
several skills; keep unrelated ones in separate plugins so installing one does
not pull the others into every session.

`SKILL.md`'s `description` is what Claude matches against when deciding whether
a skill applies, so write it to cover the phrasings a user would actually use.

The marketplace manifest has to sit at `.claude-plugin/marketplace.json` in the
repo root — Claude Code fixes that path — but its `source` values are relative,
which is what lets the plugins themselves live under `claude/`.

## The published site

[`index.html`](./index.html) at the repo root is the GitHub Pages landing page —
it lists each plugin and links to its guide. A plugin with a user-facing guide
keeps it at `<plugin>/index.html`, reached at
`…github.io/agent-toolkit/claude/plugins/<plugin>/`. Add a card to the root page
when you add a plugin.

The empty `.nojekyll` marker turns off Jekyll so files are served as-is; the
tradeoff is that a directory without an `index.html` 404s instead of falling
back to its README.

## Developing

To try a change before pushing, add the local checkout as a marketplace:

```bash
claude plugin marketplace add /path/to/agent-toolkit
```
