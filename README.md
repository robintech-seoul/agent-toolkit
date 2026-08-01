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

To try a change before pushing, add the local checkout as a marketplace:

```bash
claude plugin marketplace add /path/to/agent-toolkit
```
