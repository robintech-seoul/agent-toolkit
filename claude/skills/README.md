# claude/skills

General-purpose skills for Claude Code — they work on any codebase, in any
stack, and know nothing about RobinTech products. Anyone can install one and get
value from it on their own repo.

| Skill | Invoked as | What it does |
|---|---|---|
| [`arch-explorer`](./arch-explorer) | `/arch-explorer:build`, `:diff`, `:open` | Map a codebase into a single self-contained HTML file you can drill through — boxes are modules, labeled arrows are the interfaces between them, each expanding to full signatures and `file:line` sources. `diff` maps what a branch changed; `open` adds a chat panel that answers from the code-wiki. |
| [`code-wiki`](./code-wiki) | `/code-wiki:init`, `/code-wiki:build`, `/code-wiki:sync`, … | Build and maintain a hierarchical, LLM-generated wiki over a codebase — leaf folders summarize their files, parents synthesize their children, topic pages capture cross-cutting concerns, and `sync` keeps it current as the source changes. |
| [`grounded`](./grounded) | `/grounded:ask`, `:verify` | Deep opinions from the strongest model, fact-checked by a cheaper one that never saw the discussion — `ask` runs on Fable and writes the opinion as a document; `verify` hands only that document to a read-only Sonnet subagent that checks the facts it rests on with cited evidence, then Fable re-judges the refutations, revises, and loops a fresh verifier over the revision up to three times. |
| [`mvp-builder`](./mvp-builder) | `/mvp-builder:start`, `:approve`, `:reject`, `:status` | Take an idea to an MVP through a gated pipeline — spec → your approval → design/review loops → your approval → build. Ledger-based delta review, machine gates on every phase, built-in agent-skills (`--full`) or lightweight prompts (`--lite`). |

Product-specific tooling goes in [`../plugins`](../plugins) instead. See the
[repo README](../../README.md) for the directory layout and how to register a
new entry in the marketplace manifest.
