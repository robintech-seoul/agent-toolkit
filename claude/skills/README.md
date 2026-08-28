# claude/skills

General-purpose skills for Claude Code — they work on any codebase, in any
stack, and know nothing about RobinTech products. Anyone can install one and get
value from it on their own repo.

| Skill | Invoked as | What it does |
|---|---|---|
| [`arch-explorer`](./arch-explorer) | `/arch-explorer:build` | Map a codebase into a single self-contained HTML file you can drill through — boxes are modules, labeled arrows are the interfaces between them, each expanding to full signatures and `file:line` sources. |
| [`code-wiki`](./code-wiki) | `/code-wiki:init`, `/code-wiki:build`, `/code-wiki:sync`, … | Build and maintain a hierarchical, LLM-generated wiki over a codebase — leaf folders summarize their files, parents synthesize their children, topic pages capture cross-cutting concerns, and `sync` keeps it current as the source changes. |

Product-specific tooling goes in [`../plugins`](../plugins) instead. See the
[repo README](../../README.md) for the directory layout and how to register a
new entry in the marketplace manifest.
