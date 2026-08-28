# code-wiki

A Claude Code plugin that builds and maintains a hierarchical, LLM-generated wiki over a codebase. Point it at one or more source-root directories and it generates a markdown wiki mirroring the tree structure: leaf folders summarize their files, parent folders synthesize their children, and topic pages capture cross-cutting concerns. Following [Karpathy's llm-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) adapted to source code.

> **Status**: pre-release (v0.1.1). The 7 commands work end-to-end on small fixtures; broader real-world testing pending. v0.1.1 hardens `build`/`sync`/`rebuild` for large repos with a wave-grouped, per-page agent dispatch pattern (see `bin/orchestrate.py`).

## Concept

Most "wiki for code" tools either re-derive insights on every query (RAG) or expect humans to write the wiki by hand. code-wiki takes a third path:

- The **wiki is a persistent artifact** — committed to your repo alongside the code.
- The **LLM owns wiki maintenance** — generation, cross-references, consistency, drift detection.
- **You own the schema** — `wiki/CLAUDE.md` defines the style/voice; `wiki/config.yaml` defines what to wikify and how.

Generation is **bottom-up**: leaf folders are wikified first from their own source files; parent folders are then synthesized from their children's wikis (plus their own loose files). The result is navigable both as a hierarchy (mirroring the source tree) and as a topic graph (via lazy-generated pages under `wiki/topics/`).

The wiki being committed means the synthesis cost is paid once and shared across the team — clones don't have to regenerate.

## Install

This plugin ships in the [RobinTech agent toolkit](https://github.com/robintech-seoul/agent-toolkit) marketplace, **`robintech`**.

```
/plugin marketplace add robintech-seoul/agent-toolkit
/plugin install code-wiki@robintech
```

Then install the Python dependencies (the plugin's bin scripts use them):

```bash
pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"
# or, if you prefer per-user:
pip install --user -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"
```

Dependencies: `mistune>=3` (markdown parsing), `pyyaml>=6` (config), `pytest>=8` (only needed if running the plugin's own tests).

## Quick-start

In any git repository:

```
/code-wiki:init
```

You'll be asked for source roots, wiki language (default `en`), and optional language hints. This creates:

```
project-root/
├── wiki/                       ← committed; team-shared
│   ├── CLAUDE.md               # style guide (user-curated)
│   └── config.yaml             # configuration (user-curated)
└── .code-wiki/                 ← gitignored; local-only
```

Then build the initial wiki:

```
/code-wiki:build
```

This generates `wiki/<source-root-path>/.../index.md` for every non-ignored source folder, bottom-up. Once built, ask questions:

```
/code-wiki:query "How does authentication work?"
```

The plugin reads the wiki to answer (and may propose filing the answer as a topic page if it crosses multiple modules).

After source changes, sync incrementally:

```
/code-wiki:sync
```

This diffs git from the last ingest to HEAD, regenerates only affected pages plus their ancestors, and updates state.

## Command reference

| Command | What it does |
|---|---|
| `/code-wiki:init` | Scaffold `wiki/`, `.code-wiki/`, `.gitignore`. Asks for source roots and language. Aborts if `wiki/` already exists. |
| `/code-wiki:build` | Generate the entire wiki from scratch, bottom-up. `--force` overwrites existing content. |
| `/code-wiki:sync` | Incremental update from git diff. Soft-bootstraps state if missing (typical fresh-clone path). |
| `/code-wiki:rebuild [path]` | Force regenerate. No-arg = everything; with a path = that subtree + ancestors. |
| `/code-wiki:lint [--fix]` | Run 10 health checks (broken links, phantom pages, stale content, etc.). `--fix` removes phantom pages. |
| `/code-wiki:query <q>` | Wiki-first Q&A. May read targeted source files. May propose topic pages for cross-cutting answers. |
| `/code-wiki:topic <name>` | Explicitly create a topic page that traces a cross-cutting concern (auth, logging, payment, etc.) end-to-end. |

## Example output

A leaf wiki page generated for a Python `auth/` folder might look like:

```markdown
# auth

Login and logout flows. Both functions exchange `User` records with the
[users](../users/index.md) module and rely on [utils](../utils/index.md)
for credential hashing.

## Files

- [`login.py`](../../../src/auth/login.py) — `login(username, password) -> User | None`.
  Hashes the password via `hash_password`, then returns a `User(id=1, ...)`
  if both fields are non-empty. Returns `None` otherwise.
- [`logout.py`](../../../src/auth/logout.py) — `logout(user) -> None`. Prints a
  status line. Currently a placeholder for session teardown.

## Dependencies

- `users.models.User` — return type for login (see [users](../users/index.md)).
- `utils.helpers.hash_password` — credential hashing (see [utils](../utils/index.md)).

## Notes

`login` is intentionally permissive in this fixture: any non-empty
username/password pair is accepted and always produces `User(id=1, ...)`.
There is no real credential store yet.
```

A topic page for `auth` might trace the request through both API and lib layers:

```markdown
# auth

Authentication flow spanning the HTTP layer (`apps/api/src/routes/auth.ts`)
and the cryptographic primitives (`packages/lib/auth.ts`).

## Flow

A login request enters at `apps/api/src/routes/auth.ts` (the `POST /login`
handler), which validates the request body and calls `signToken(claims)`
from `packages/lib/auth.ts:14`. `signToken` serializes the claims with an
expiration, hashes them via `naiveHash`, and returns the concatenated token.

Validation occurs at `validateToken(token)` (`packages/lib/auth.ts:30`),
which decodes the base64 payload, recomputes the hash, and rejects if hashes
mismatch or `exp` has passed. Both `POST /logout` and `GET /users/me` call
this validator.
```

## Configuration

`wiki/config.yaml` is the source of truth for what gets wikified:

```yaml
version: 1

# One or more source roots. The path itself is used as the wiki subdirectory
# (no separate `name:` field). Source roots cannot nest in each other.
source_roots:
  - path: src                # → wiki/src/
  - path: packages/server    # → wiki/packages/server/
  - path: apps/web/src       # → wiki/apps/web/src/

# Wiki output language. Free-form; the LLM uses it as a hint.
wiki_language: en

# Optional hints to bias LLM interpretation.
language_hints:
  - typescript
  - react

# gitignore-style globs evaluated relative to each source root.
ignore_patterns:
  - "**/node_modules/**"
  - "**/__pycache__/**"
  - "**/dist/**"
  - "**/build/**"
  - "**/*.lock"

# Per-file pages: spawn a dedicated wiki for files that are large enough or
# live in folders too crowded for a single leaf page to detail every file.
per_file_pages:
  enabled: true
  min_loc: 800
  max_files_per_folder: 20
```

The plugin **never auto-edits this file** — it's user-curated. Same for `wiki/CLAUDE.md` (the style guide).

## Directory layout

```
project-root/
├── wiki/                                ← committed
│   ├── CLAUDE.md                        # style guide
│   ├── config.yaml                      # configuration
│   ├── <source-root-path>/              # mirrors source tree
│   │   ├── index.md                     # folder wiki
│   │   ├── <subfolder>/index.md
│   │   └── <bigfile>.md                 # per-file wiki (when triggered)
│   └── topics/
│       └── <name>.md                    # topic pages (lazy)
└── .code-wiki/                          ← gitignored
    ├── state.json                       # ingest state, content/source hashes
    └── log.md                           # operation log
```

`init` adds `.code-wiki/` to `.gitignore` automatically.

## Troubleshooting

**"wiki/config.yaml not found"**
You haven't initialized in this repo yet. Run `/code-wiki:init`.

**"wiki/ already exists" on init**
init is intentionally non-destructive. If you want to start over, manually `rm -rf wiki/` and re-run.

**"wiki/ has not been committed; run /code-wiki:build first"** (during sync after clone)
Sync's soft-bootstrap needs at least one commit touching `wiki/` to infer `last_ingested_sha`. If you cloned a repo where `wiki/` is committed but you somehow get this error, check whether `wiki/` is actually tracked (`git ls-files wiki/`).

**"Source root nests inside another"**
Two configured source roots cannot have one as a prefix of the other (e.g. `src` and `src/api`). Pick one — either the broader or the more specific.

**Generation produces low-signal pages**
Consider:
- Editing `wiki/CLAUDE.md` to add concrete style guidance.
- Adding `language_hints` in `config.yaml` (e.g. `["django", "rest"]`).
- Running `/code-wiki:rebuild <path>` after the changes to regenerate that subtree.

**`/code-wiki:lint` reports many `length-too-short`**
Your folders may be too granular. Either accept the info findings or restructure source.

**State has gone weird (impossible findings, missing entries)**
Delete `.code-wiki/state.json` and run `/code-wiki:sync`. The plugin will soft-bootstrap state from the committed `wiki/`.

## v2 roadmap

Not in v1, planned for v2:

- **Auto-sync via git hooks** — `pre-push` hook runs `sync` automatically.
- **Auto topic regeneration during sync** — currently sync only flags topics as dirty; the user re-runs `/code-wiki:topic <name>` manually.
- **Wiki-language auto-detection** — currently asked at init (default `en`).
- **Topic-page user-edit preservation** — currently regeneration overwrites freely (per design); v2 may add markers for hand-edited sections.
- **Performance** — parallel sibling generation, incremental hashing.
- **Non-git workflows** — fall back to file mtimes when not in a git repo.
- **Wiki location override** — currently `wiki/` is hardcoded; a small bootstrap file could allow `docs/wiki/` etc.

## Design docs

- [SPEC.md](SPEC.md) — full v1 specification (concept model, page templates, sync algorithm, lint rules, etc.).
- [PLAN.md](PLAN.md) — implementation plan (component breakdown, dependency graph, risks).
- [TASKS.md](TASKS.md) — 27 implementation tasks with acceptance criteria.

## License

Same license as the parent [`agent-toolkit`](https://github.com/robintech-seoul/agent-toolkit) repository.
