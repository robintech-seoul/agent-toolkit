# RobinTech agent toolkit

Agent tooling RobinTech builds and uses, for Claude Code and Codex. Everything
installs from this one repository through two marketplaces: **`robintech`**
for Claude Code and **`robintech-codex`** for Codex.

## What's here

| Tool | What it does | Commands | Claude Code | Codex |
|---|---|---|:-:|:-:|
| [`arch-explorer`](./claude/skills/arch-explorer) | Map a codebase into one self-contained HTML file you drill through: boxes are modules, labeled arrows are the interfaces between them, each expanding to signatures and `file:line`. Maps what a branch changed; opens either map with a chat panel that answers from the code-wiki — and, for a branch, from the session that mapped its changes. | `build` `diff` `open` | ✓ | — |
| [`code-wiki`](./claude/skills/code-wiki) | Build and maintain a hierarchical, LLM-generated wiki over a codebase. Leaf folders summarize their files, parents synthesize their children, topic pages capture cross-cutting concerns, and `sync` follows the source. Committed, so a team pays for it once. | `init` `build` `sync` `query` `topic` `lint` `rebuild` | ✓ | — |
| [`grounded`](./claude/skills/grounded) | Get a deep opinion on a hard question from the strongest model, written as a document, then fact-check it with a cheaper model in a separate context: the verifier extracts the facts the opinion rests on and confirms, refutes or flags each with cited evidence; Fable re-judges every refutation, revises, and a fresh verifier re-checks — up to three rounds. | `ask` `verify` | ✓ | — |
| [`mvp-builder`](./claude/skills/mvp-builder) | Take an idea to an MVP through a gated pipeline: spec → your approval → design/review loops → your approval → build, with ledger-based delta review and machine gates. | `start` `approve` `reject` `status` | ✓ | ✓ ([port](./codex/skills/mvp-builder)) |
| [`robin-cloud-onboarding`](./claude/plugins/robin-cloud-onboarding) | Onboard a repo to [Robin-Cloud](https://robin-cloud.com) end to end: Dockerfiles, a keyless CI workflow and nginx, then the console setup (GitHub App, ECR, deploy config, DB, custom domain + TLS) with a verified checkpoint after each step. | `onboard` | ✓ | — |

In Claude Code a command runs as `/<tool>:<command>`, e.g. `/arch-explorer:build`.
Each tool's README has the full usage.

## Install

### Claude Code

Add the marketplace once, then install the tools you want:

```bash
/plugin marketplace add robintech-seoul/agent-toolkit

/plugin install arch-explorer@robintech
/plugin install code-wiki@robintech
/plugin install grounded@robintech
/plugin install mvp-builder@robintech
/plugin install robin-cloud-onboarding@robintech
```

From a shell, the same is `claude plugin marketplace add robintech-seoul/agent-toolkit`
and `claude plugin install <tool>@robintech`.

To update:

```bash
claude plugin marketplace update robintech
claude plugin update <tool>@robintech
```

If a new command does not show up, start a new session.

### Codex

Only `mvp-builder` has a Codex version.

```bash
codex plugin marketplace add robintech-seoul/agent-toolkit
codex plugin add mvp-builder@robintech-codex
```

To update, run `codex plugin marketplace upgrade`, then the `codex plugin add`
line again. In a new Codex task, choose the `start`, `approve`, `reject` and
`status` skills. See
[MVP-Builder for Codex](./codex/skills/mvp-builder/README.md).

### What each tool needs

| Tool | Needs |
|---|---|
| arch-explorer | `python3` and `git`. `open`'s chat panel also needs the `code-wiki` plugin and the `claude` or `codex` CLI; without them the map opens without the chat. `diff --open` needs the `claude` CLI. |
| code-wiki | `python3` and its Python packages: `pip install mistune pyyaml` (see [its README](./claude/skills/code-wiki/README.md#install)). A git repository for `sync`. |
| grounded | Access to Fable (for `ask` and `verify`) and Sonnet (the verifier). |
| mvp-builder (Claude Code) | `bash` and `jq`; `npm` or `pytest` for the project it builds. |
| mvp-builder (Codex) | Python 3.10+, the Codex CLI signed in; macOS/Linux (WSL on Windows). |
| robin-cloud-onboarding | A Robin-Cloud console account and project; `gh` signed in with admin on the repo. |

### Try without installing

Load a plugin from a directory for one Claude Code session. It replaces an
installed plugin of the same name for that session only:

```bash
git clone https://github.com/robintech-seoul/agent-toolkit
claude --plugin-dir agent-toolkit/claude/skills/arch-explorer
```

## Using them together

`arch-explorer` and `code-wiki` share a repository without depending on each
other, and meet in `/arch-explorer:open`:

```
/code-wiki:init, /code-wiki:build   → wiki/        (commit it)
/arch-explorer:build                → docs/architecture/index.html
/arch-explorer:open                 → the map, with a chat panel answering from wiki/
/arch-explorer:diff --open          → a branch's change map, with a chat panel answering
                                      from the session that built it and from wiki/
```

`open` checks that both are current first, and offers to build, create or sync
whichever is missing or behind.

---

## Contributing

### Layout

```
.claude-plugin/marketplace.json   Claude Code catalog  (robintech)
.agents/plugins/marketplace.json  Codex catalog        (robintech-codex)
claude/
├── plugins/   tied to a RobinTech product
└── skills/    general-purpose: any codebase, any stack
codex/
└── skills/    Codex packages
index.html     GitHub Pages landing page
```

Each tool is one self-contained directory: everything it runs ships inside
it, so installing it pulls in nothing else.

### Claude Code packages

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

Bump `version` in `plugin.json` with every change users should receive:
`claude plugin update` reports "already at the latest version" while it is
unchanged.

### Codex packages

Codex packages use `.codex-plugin/plugin.json`, `skills/<name>/SKILL.md`, and a
root `.agents/plugins/marketplace.json` entry pointing to the package. Keep
platform-specific runtime files inside the package. See
[Codex packages](./codex/skills/README.md) and [AGENTS.md](./AGENTS.md).

### The published site

[`index.html`](./index.html) at the repo root is the GitHub Pages landing page —
it lists each plugin and links to its guide. A plugin with a user-facing guide
keeps it at `<plugin>/index.html`, reached at
`…github.io/agent-toolkit/claude/plugins/<plugin>/`. Add a card to the root page
when you add a plugin.

The empty `.nojekyll` marker turns off Jekyll so files are served as-is; the
tradeoff is that a directory without an `index.html` 404s instead of falling
back to its README.

### Developing

Try a change in one session with `claude --plugin-dir <path to the plugin>`,
or add the checkout as a marketplace:

```bash
claude plugin marketplace add /path/to/agent-toolkit
codex plugin marketplace add /path/to/agent-toolkit
```

Tests:

```bash
python3 -m unittest discover -s claude/skills/arch-explorer -t claude/skills/arch-explorer
python3 -m pytest claude/skills/code-wiki/tests
python3 -m unittest discover -s codex/skills/mvp-builder/tests
```
