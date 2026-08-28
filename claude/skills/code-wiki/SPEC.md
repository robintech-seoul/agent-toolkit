# Spec: code-wiki (v1)

A Claude Code plugin that builds and maintains a hierarchical, LLM-generated wiki over a codebase, following Karpathy's llm-wiki pattern adapted to source code.

---

## 1. Objective

**What**: A plugin that lets a developer point Claude Code at one or more source root directories and generate a persistent, continuously-maintained markdown wiki that mirrors the directory structure and synthesizes understanding bottom-up.

**Why**: Codebases grow faster than humans can document them. RAG over raw files re-derives the same insights on every query. A persistent wiki — owned and maintained by the LLM but versioned by the team — captures synthesis once and keeps it current at near-zero human cost. For onboarding, code review context, and architectural reasoning, a fresh, navigable wiki beats grepping the source.

**Primary user**: A software engineer working in a Claude Code session in a git repository who wants Claude to maintain a navigable knowledge layer over their codebase.

**User stories**:
- As a developer joining a new repo, I run `/code-wiki:build` once and then read `wiki/` to understand the system top-down.
- As a developer modifying code, I run `/code-wiki:sync` after my changes and the affected wiki pages are regenerated automatically.
- As a developer asking Claude a system-level question, I run `/code-wiki:query "how does authentication work?"` and Claude reads the wiki (not raw source) to answer faster and more coherently.
- As a team, we commit `wiki/` so the synthesis cost is shared and the wiki is part of the repo's living documentation.

**Non-goals (v1)**:
- Automatic ingest on git operations (hooks). v2.
- Cross-language semantic understanding beyond what an LLM reading source can do (no AST, no LSP integration).
- Non-git repositories.
- Automatic translation of wiki language.
- Web UI / rendering. The wiki is plain markdown read in any markdown viewer.

---

## 2. Concept Model

**Three layers** (from Karpathy's llm-wiki, adapted):

1. **Source layer** (raw, immutable from the wiki's perspective): user-owned source code directories.
2. **Wiki layer** (LLM-owned, committed): markdown pages mirroring source tree + topic pages.
3. **Schema layer** (`wiki/CLAUDE.md` + `wiki/config.yaml`): conventions and configuration that govern how the wiki operates.

**Hierarchical map-reduce**:

- A **leaf folder** (no subdirectories) → one wiki page (`index.md`) summarizing all files in that folder. May spawn additional per-file pages at LLM discretion.
- A **parent folder** (has subdirectories) → one wiki page that:
  - **Synthesizes** its direct children's wiki pages (primary role).
  - **Describes** its own loose files (files directly in the parent folder, not in any child folder).
  - May link to wikis or sources anywhere in the tree if relevant, but prefers links to direct children for navigability.
- The recursion runs from leaves up to each source root.
- Multiple source roots → independent trees under `wiki/<source-root-name>/`.

**Topic pages** (cross-cutting concerns like "auth", "logging", "payment flow"):

- Generated **lazily**: when `/code-wiki:query` produces an answer that synthesizes ≥3 leaf wikis and the LLM judges it reusable, it offers to file the answer as `wiki/topics/<name>.md`.
- Or generated **explicitly** via `/code-wiki:topic <name>`.
- Topic pages link freely to any wiki/source location.

---

## 3. Architecture

### Directory layout (in user's project repo)

```
project-root/
├── wiki/                       ← committed; team-shared
│   ├── CLAUDE.md               # prose-form style/voice guide
│   ├── config.yaml             # source roots, ignore patterns, language hints
│   ├── <source-root-path>/     # mirrored tree per source root; the path itself is used as the subdirectory
│   │   ├── index.md            # folder wiki
│   │   ├── <subfolder>/
│   │   │   └── index.md
│   │   └── <bigfile>.md        # optional per-file wiki
│   └── topics/                 # cross-cutting concerns (lazy)
│       └── auth.md
└── .code-wiki/                 ← gitignored; local/per-machine
    ├── state.json              # last_ingested_sha, file→wiki mapping, content hashes
    └── log.md                  # append-only operation log
```

**Source root subdirectory naming**: the configured source root path is used directly as the wiki subdirectory. Examples:
- source root `src` → `wiki/src/...`
- source root `apps/web/src` → `wiki/apps/web/src/...`
- source root `packages/server` → `wiki/packages/server/...`

This means two source roots with the same basename (e.g. `apps/web/src` and `apps/api/src`) automatically live at distinct wiki paths and never collide.

**Source root validation** (enforced at `init` and on every `config.yaml` read):
- Source root must not be empty, `.`, or absolute.
- Source root must not be `wiki`, `.code-wiki`, or any path inside them.
- Source roots must not nest inside each other (e.g. `src` and `src/api` cannot both be source roots).
- Each source root must exist as a directory at the time of operation.

`wiki/` is hardcoded at project root (no relocation in v1) — `config.yaml` lives inside `wiki/` so wiki location can't itself be configured (chicken-and-egg). v2 may add a bootstrap file at project root if needed.

### `.gitignore`

`init` appends a single line to project `.gitignore`:

```
.code-wiki/
```

### Source link format

All links from wiki pages to source files use **standard markdown relative paths** computed relative to the wiki page's containing directory. Example: from `wiki/src/api/auth/index.md` (located in directory `wiki/src/api/auth/`), a link to `src/api/auth/auth.ts` is `[auth.ts](../../../../src/api/auth/auth.ts)` — four `../` to escape `wiki/src/api/auth/` to the project root, then descend into `src/api/auth/auth.ts`. Computed centrally by `bin/lib/wiki_path.py:relative_link()`.

Pros: clickable in GitHub, VS Code, Obsidian, and any markdown renderer; no custom tooling required.

---

## 4. Commands

All commands are slash commands invoked in a Claude Code session in the user's project root.

### `/code-wiki:init`

Bootstrap the plugin in the current project.

**Behavior**:
1. Detect if `wiki/` already exists. If so, abort with message ("already initialized; remove `wiki/` to re-init").
2. Ask the user:
   - "What directories contain source code? (comma-separated, relative to project root)" — e.g. `src/, lib/`
   - "Wiki language? [en]" — accept any value; default `en`.
   - "Optional language/framework hints? (e.g. typescript, react)" — free text.
3. Validate that each source root path exists and is a directory.
4. Create `wiki/` with `CLAUDE.md` (template) and `config.yaml` (filled in from answers).
5. Create `.code-wiki/` (empty for now).
6. Append `.code-wiki/` to `.gitignore` (create if missing).
7. Print next-step instructions: "Run `/code-wiki:build` to generate the initial wiki."

### `/code-wiki:build`

Generate the entire wiki from scratch.

**Behavior**:
1. Read `wiki/config.yaml`.
2. For each source root:
   - Walk the tree depth-first.
   - At each leaf folder, generate `wiki/<source-root-path>/<relative-path>/index.md`.
   - Bubble up: when all children of a folder are done, generate the parent's `index.md` synthesizing them.
3. Compute content hash for each generated page.
4. Build `source_to_wiki` mapping by recording which sources each leaf wiki references.
5. Set `last_ingested_sha` to current `git rev-parse HEAD`.
6. Write `.code-wiki/state.json`.
7. Append a build entry to `.code-wiki/log.md`.

**Behavior on existing wiki**: If a source root's subdirectory under `wiki/` already has content, abort by default unless user passes `--force` (in which case existing pages are overwritten).

### `/code-wiki:sync`

Incremental update based on git diff.

**Behavior**:
1. If `.code-wiki/state.json` is missing, **soft-bootstrap** first:
   - Find latest commit touching `wiki/`: `git log -1 --format=%H -- wiki/`.
   - If none, abort with "wiki/ has not been committed; run `/code-wiki:build` first."
   - Walk `wiki/` and parse every page's source links to reconstruct `source_to_wiki` mapping.
   - Compute content hashes.
   - Write a fresh `state.json` with the inferred `last_ingested_sha`.
2. Compute changed source files: `git diff --name-status <last_ingested_sha>..HEAD`.
3. Apply ignore patterns from `config.yaml` and source-root membership.
4. For each changed file:
   - **Modified**: mark its leaf wiki dirty.
   - **Added**: identify the leaf folder; if no wiki yet, mark it dirty (or create if folder is brand new); else mark dirty.
   - **Deleted**: remove the file's reference from its leaf wiki; if leaf becomes empty (no remaining files in folder), delete the wiki page.
   - **Renamed**: treat as delete + add.
5. Regenerate dirty leaf wikis.
6. For each ancestor of a dirty leaf, mark it dirty and regenerate (parents synthesize their children's content, so any child change ripples up).
7. For each topic page, check if any of its referenced source files were touched. If yes, regenerate the topic page.
8. Update content hashes and `last_ingested_sha` in `state.json`.
9. Append a sync entry to `log.md` (counts of created/updated/deleted pages).

### `/code-wiki:rebuild [path]`

Force regeneration regardless of state.

**Behavior**:
- No argument → equivalent to `build --force` over all source roots.
- With `path` argument (e.g. `src/auth/`) → regenerate that subtree only, then re-synthesize ancestors up to the source root.
- Topic pages are not affected unless they reference sources within `path`, in which case they are regenerated.

### `/code-wiki:lint`

Health check. Reports problems but does not modify files (unless `--fix` is passed; v1 fix only handles trivial cases).

**Checks**:
1. **Broken links**: wiki→wiki and wiki→source links that no longer resolve.
2. **Orphan pages**: wiki pages with no inbound links from any other wiki and no corresponding source folder.
3. **Stale pages**: source files referenced by a wiki page have changed (by content hash) since the wiki's last regeneration. Requires state.json — skipped with warning if missing.
4. **Missing wikis**: source folders that are not ignored but have no corresponding wiki page.
5. **Phantom wikis**: wiki pages whose corresponding source folder no longer exists.
6. **Length sanity**: leaf wikis < 20 lines or > 500 lines flagged for review (likely too sparse or overgrown).
7. **Topic source drift**: topic pages whose listed source references no longer match content hashes.

`--fix` (v1, conservative): only deletes phantom wikis and updates content hashes after regeneration. Other fixes require explicit `sync`/`rebuild`.

### `/code-wiki:query <question>`

Answer a question by reading the wiki, with optional source drill-down.

**Behavior**:
1. Read `wiki/CLAUDE.md` and the wiki tree (start from root index files; descend as relevance dictates).
2. **Wiki-first, source-on-demand**: if the wiki content alone is sufficient to answer the question accurately, do not read source files. If the wiki points to specifics that need verification or detail (a function signature, an exact constant, a flow not fully captured), the LLM may read targeted source files referenced by the relevant wikis.
3. **No full source scan, ever**: source reads must always be guided by the wiki hierarchy — i.e. the LLM identifies which wikis are relevant first, then opens at most the source files those wikis point to. Never enumerate the source tree directly to answer a query.
4. Synthesize answer with citations (markdown links to wiki pages and source files used).
5. **Topic candidate detection**: if the answer cites ≥3 distinct leaf wiki pages from different parts of the tree AND the question is non-trivial (>1 sentence to answer), prompt the user:
   > "This answer synthesizes [N] wiki pages and may be reusable. File as `wiki/topics/<suggested-name>.md`? [y/N]"
6. If user accepts, generate the topic page (see `topic` command) and append to log.

### `/code-wiki:topic <name>`

Explicitly create a topic page that captures how a cross-cutting concern actually flows through the codebase.

**Behavior**:
1. If `wiki/topics/<name>.md` exists, ask before overwriting.
2. Treat `<name>` as the topic; ask for a 1-line description if not obvious.
3. Search the wiki for relevant content (read leaf and parent wikis matching the topic).
4. **Source analysis**: read the source files referenced by the matched wikis to reconstruct the actual end-to-end flow (entry points, control flow, data flow, side effects). The wiki tells us *where* the topic lives; the source tells us *how* it actually executes. Both are required for a useful topic page.
5. Synthesize a topic page with sections:
   - **Overview** — what the topic is and where it lives.
   - **Key Components** — links to wiki pages, with the role of each in this topic.
   - **Source Touchpoints** — links to source files with where the topic's logic appears.
   - **Flow** — narrative trace of how the topic actually executes, end-to-end (e.g. "request enters at X, validates at Y, persists via Z, emits event W"). This is the section that makes a topic page valuable beyond what static links can convey.
   - **Patterns & Conventions** — recurring shapes, common gotchas, design decisions visible across the touchpoints.
   - **Open Questions** — known unknowns or design ambiguities surfaced during the analysis.
6. Record the topic's source and wiki references in `state.json` so `sync` can keep it current.

---

## 5. Configuration: `wiki/config.yaml`

```yaml
# Schema version; bumped if format changes.
version: 1

# Source roots to wikify. Each root produces an independent tree at wiki/<path>/.
# The path itself is used as the wiki subdirectory; no separate name field.
source_roots:
  - path: src                # → wiki/src/
  - path: packages/server    # → wiki/packages/server/
  - path: apps/web/src       # → wiki/apps/web/src/

# Wiki output language (free-form; LLM uses as a hint).
wiki_language: en

# Hints to bias the LLM's interpretation. Optional.
language_hints:
  - typescript
  - react

# Files/folders to skip during ingestion. gitignore-style globs, evaluated relative to each source root.
ignore_patterns:
  - "**/node_modules/**"
  - "**/__pycache__/**"
  - "**/.git/**"
  - "**/dist/**"
  - "**/build/**"
  - "**/*.min.js"
  - "**/*.lock"

# Heuristics for deciding when to spawn per-file wiki pages within a leaf folder.
per_file_pages:
  enabled: true
  min_loc: 800               # files with ≥800 lines of code are candidates
  max_files_per_folder: 20   # in folders with >20 files, prefer per-file split
```

`init` writes a default config with the user's answers filled in. The user is free to edit `config.yaml` afterward; subsequent `sync`/`rebuild` reads the current config.

---

## 6. Wiki Page Format

### Leaf folder template (`wiki/<root>/<...>/index.md`)

```markdown
# <folder name>

<2–4 line summary: what this folder does, its responsibility within the parent module>

## Files

- [`<file>`](relative/path/to/source) — <one-line description>
- ...

## Concepts

<Domain concepts, types, key abstractions defined here. Skip if none.>

## Dependencies

<Significant imports/calls into other folders or external packages. Cross-link to other wikis where applicable.>

## Notes

<Gotchas, non-obvious patterns, things a future reader should know. Skip if none.>
```

### Parent folder template

A parent wiki has **three distinct synthesis outputs** combined into one page:

1. **Loose files synthesis** — what the parent's own (non-subdirectory) source files do.
2. **Children synthesis** — a narrative summary of what the children's wikis collectively contain (not just a link list).
3. **Overall role synthesis** — how (1) and (2) together define the parent's role in the system.

```markdown
# <folder name>

## Overview

<1–3 paragraph synthesis of the parent's overall role, combining children + loose files into a coherent narrative. This is the "Overall role synthesis" — the highest-level statement of what this folder is.>

## Sub-modules

<Narrative synthesis of the children's wikis. For each child, give a meaningful paragraph (not a one-liner) describing what it contains, its responsibility, and how it relates to its siblings. The bullet list below is for navigation; the prose above it is for understanding.>

- [<child>](./child/index.md) — <one-line index>
- ...

## Loose files

<Only present if the parent folder has files directly in it (not in any sub-folder).>

<Brief narrative synthesis of what these loose files do collectively — the "Loose files synthesis".>

- [`<file>`](relative/path) — <one-line description>

## Architecture

<How sub-modules and loose files interact: data flow, dependency direction, layering. Include a mermaid diagram if and only if the LLM judges that a diagram materially clarifies the structure (i.e. when there are multiple components with non-trivial relationships). Skip diagrams when prose suffices.>

## Related Topics

<Links to topic pages relevant to this module, if any.>
```

**Generation strategy**: Parent wiki generation uses three coordinated prompts internally — one to synthesize the loose files (similar to the leaf-page prompt over just those files), one to synthesize the children's wikis (reading children's `index.md` content), and a third to combine the two outputs into the overall Overview. The page templates above are the unified output format.

### Per-file wiki template (`wiki/<root>/<...>/<filename>.md`)

```markdown
# <filename>

<Purpose: what this file is responsible for.>

## Public surface

- `<function/class/export>` — <signature + one-line description>
- ...

## Internals

<Key logic, algorithms, state. Cross-link to related wikis.>

## Source

[`<filename>`](relative/path/to/source)
```

### Topic page template (`wiki/topics/<name>.md`)

```markdown
# <topic>

<2–4 line overview.>

## Key Components

- [<wiki page>](../path/to/wiki) — <role in this topic>
- ...

## Source Touchpoints

- [`<file>`](relative/path/to/source) — <where this topic shows up>
- ...

## Patterns & Conventions

<How this topic is implemented across the codebase.>

## Open Questions

<Known unknowns; intentional design ambiguities.>
```

### Per-file page heuristic (decision logic for the LLM)

When generating a leaf folder wiki, also generate a per-file wiki for each file matching:

- LOC ≥ `per_file_pages.min_loc` (default 200), **OR**
- Folder has more than `per_file_pages.max_files_per_folder` files (default 20), in which case the LLM picks the most central N files for per-file pages and lists the rest only by one-liner in the leaf wiki.

Files below threshold get a one-line entry in the leaf wiki's "Files" section.

---

## 7. State: `.code-wiki/state.json`

```json
{
  "version": 1,
  "last_ingested_sha": "abc123def456...",
  "wiki_pages": {
    "wiki/src/api/auth/index.md": {
      "kind": "leaf",
      "source_files": [
        "src/api/auth/auth.ts",
        "src/api/auth/middleware.ts"
      ],
      "child_wikis": [],
      "content_hash": "sha256:..."
    },
    "wiki/src/api/index.md": {
      "kind": "parent",
      "source_files": ["src/api/index.ts"],
      "child_wikis": [
        "wiki/src/api/auth/index.md",
        "wiki/src/api/users/index.md"
      ],
      "content_hash": "sha256:..."
    },
    "wiki/topics/auth.md": {
      "kind": "topic",
      "source_files": [
        "src/api/auth/auth.ts",
        "src/middleware/session.ts",
        "src/db/users.ts"
      ],
      "referenced_wikis": [
        "wiki/src/api/auth/index.md",
        "wiki/src/middleware/index.md"
      ],
      "content_hash": "sha256:..."
    }
  },
  "source_to_wiki": {
    "src/api/auth/auth.ts": [
      "wiki/src/api/auth/index.md",
      "wiki/topics/auth.md"
    ]
  },
  "source_hashes": {
    "src/api/auth/auth.ts": "sha256:..."
  }
}
```

**Notes**:
- `source_to_wiki` maps each source file to the wikis that reference it (leaf wiki + any topic pages). Used by `sync` to identify ripple targets.
- `source_hashes` tracks the source content at last ingestion. Used by `lint` to detect drift.
- Hashes use SHA-256 of file contents.

---

## 8. Sync Algorithm (detailed)

```
INPUT: state.json (or none → soft-bootstrap)
INPUT: current HEAD

1. Load state.json. If missing:
   a. Find inferred SHA via `git log -1 --format=%H -- wiki/`.
   b. Walk wiki/ and parse all source links to rebuild source_to_wiki.
   c. Compute content hashes for each wiki page.
   d. Compute source hashes for all referenced source files.
   e. Save state.json. last_ingested_sha = inferred SHA.

2. Compute changed paths: `git diff --name-status <last_ingested_sha>..HEAD`.
   Filter by source_roots membership and ignore_patterns.

3. Build dirty set:
   - For each changed file in source_to_wiki: add all mapped wikis to dirty set.
   - For each new file in a tracked source root: identify its leaf folder; add that folder's leaf wiki to dirty set (creating mapping if folder is new).
   - For each deleted file: queue removal from referencing wikis.

4. Process leaf wikis first (kind == "leaf"):
   - Re-read the folder's current contents (after applying changes).
   - If folder is now empty: delete the wiki page.
   - Else: regenerate the page from current source.
   - Update content_hash and source_files in state.

5. Propagate to ancestors:
   - For each leaf wiki regenerated, walk up the tree adding each ancestor parent wiki to dirty set.
   - Process ancestors in order from deepest to shallowest (so children are fresh when parent is synthesized).
   - Regenerate each parent wiki by re-reading direct children's wikis + own loose files.

6. Process topic pages:
   - For each topic in state, if any of its source_files are in the changed set, regenerate.

7. Update last_ingested_sha = current HEAD.

8. Write state.json.

9. Append summary to log.md:
   ```
   ## 2026-05-01T14:32:11Z sync
   - Range: abc123..def456 (12 files changed)
   - Leaves regenerated: 3
   - Parents regenerated: 5
   - Topics regenerated: 1
   - Pages deleted: 0
   ```
```

**Edge cases**:
- Source root itself deleted from filesystem → abort with error; user must update config.
- Config changed (new source root added) → `sync` detects the new root has no wikis and creates them as if from scratch for that root only.

---

## 9. Lint Rules (detailed)

| Rule | What it checks | Severity |
|---|---|---|
| `broken-link-wiki` | Markdown link to another wiki page that doesn't exist | Error |
| `broken-link-source` | Markdown link to a source file that doesn't exist | Error |
| `orphan-wiki` | Wiki page with no inbound links and no corresponding source folder | Warning |
| `phantom-wiki` | Wiki page whose source folder no longer exists | Error |
| `missing-wiki` | Source folder (under a source root, not ignored) without a wiki page | Warning |
| `stale-wiki` | Source file's content hash differs from `state.json`'s `source_hashes` entry | Warning |
| `length-too-short` | Leaf wiki < 20 lines | Info |
| `length-too-long` | Leaf wiki > 3000 lines | Info |
| `topic-source-drift` | Topic page references a source file whose content has changed | Warning |
| `config-invalid` | `config.yaml` schema or referenced source roots invalid | Error |

Output format: grouped by severity, with one line per finding (`<rule>: <wiki path> — <detail>`).

---

## 10. Topic Page Lazy Generation

**Trigger conditions during `/code-wiki:query`** (all must hold):

1. The answer cites ≥3 distinct leaf wiki pages.
2. The cited pages span ≥2 different sub-trees (not all under one folder) — i.e. genuinely cross-cutting.
3. The question is substantive (the answer would be more than a single sentence).
4. No existing topic page already covers the same scope (LLM checks `wiki/topics/`).

When all conditions hold, prompt:
> "This answer synthesizes [N] pages across [M] modules. File as `wiki/topics/<suggested-name>.md` so future queries can reuse it? [y/N]"

The user accepts → generate the topic page using the topic template.
The user declines → record nothing (no penalty for declining).

**Explicit creation via `/code-wiki:topic <name>`** has no threshold — it always generates.

---

## 11. Plugin Project Structure (this repo)

```
claude-plugins/                     ← this marketplace repo
├── code-wiki/
│   ├── .claude-plugin/
│   │   └── plugin.json             # Claude Code plugin manifest
│   ├── commands/
│   │   ├── init.md
│   │   ├── build.md
│   │   ├── sync.md
│   │   ├── rebuild.md
│   │   ├── lint.md
│   │   ├── query.md
│   │   └── topic.md
│   ├── skills/                     # shared logic, if any (e.g., page generation patterns)
│   │   └── ...
│   ├── templates/                  # markdown templates referenced by commands
│   │   ├── wiki-CLAUDE.md
│   │   ├── config.yaml
│   │   ├── page-leaf.md
│   │   ├── page-parent.md
│   │   ├── page-perfile.md
│   │   └── page-topic.md
│   ├── SPEC.md                     ← this file
│   └── README.md                   # user-facing intro
└── marketplace.json                # updated to include code-wiki
```

---

## 12. Code Style (for plugin command files)

A slash command markdown file is a prompt that runs in the user's session. Style rules:

- **Frontmatter** with `description` (one line) and `argument-hint` if applicable.
- **Imperative voice**, second-person ("Read the config", "Generate the page").
- **Structured steps** numbered, each step verifiable. No vague "use your judgment" without anchoring.
- **Reference templates** by relative path rather than inlining long markdown.
- **Fail loudly**: every step states the failure mode explicitly ("If config.yaml is missing, abort with: `Run /code-wiki:init first.`").
- **No silent assumptions**: surface every assumption as a check.

Example skeleton (`commands/sync.md`):

```markdown
---
description: Incremental wiki update based on git diff since last ingest
---

# /code-wiki:sync

Update the wiki to reflect changes between `state.json`'s `last_ingested_sha` and the current `HEAD`.

## Preconditions

1. Verify the project is a git repository: `git rev-parse --git-dir`. If not, abort: "code-wiki:sync requires a git repository."
2. Read `wiki/config.yaml`. If missing, abort: "Run /code-wiki:init first."
3. Read `.code-wiki/state.json`. If missing, perform soft-bootstrap (see template `bootstrap.md`).

## Steps

1. ...
```

---

## 13. Testing Strategy

The plugin has no traditional unit/integration test suite (it's prompt-driven markdown). Verification strategy:

- **Fixture repos**: maintain 2–3 small sample repositories under `code-wiki/fixtures/` representing typical shapes (single-language flat tree, monorepo with multiple source roots, mixed code+non-code folders). Manual verification: run `init` → `build` → inspect output.
- **Regression checklist**: a markdown checklist of scenarios to manually walk before each release (e.g., "create a new file under leaf, run sync, verify only that leaf+ancestors regenerate").
- **Lint self-check**: run `/code-wiki:lint` on the wiki produced by build over each fixture; expect zero errors.
- **Soft-bootstrap test**: build a wiki, commit, delete `.code-wiki/`, run `sync` with no source changes, verify state is reconstructed and no spurious regenerations occur.

v2 will explore golden-output snapshot tests if the prompts stabilize.

---

## 14. Boundaries

**Always**:
- Validate `config.yaml` and source-root existence before any operation.
- Append every operation to `log.md` with timestamp, command, and summary.
- Use git diff (not file mtime) for sync.
- Honor `ignore_patterns` consistently across all commands.
- Treat auto-generated wiki content (`wiki/<source-root-path>/...` and `wiki/topics/...`) as fully owned by the plugin: regenerate freely without trying to preserve user hand-edits. The plugin assumes users do not hand-edit auto-generated content.

**Ask first**:
- Overwriting an existing source root's subdirectory under `wiki/` (`build` requires `--force`).
- Deleting a wiki page (sync prompts if a leaf folder becomes empty after source deletions).
- Filing a query answer as a topic page (lazy creation always prompts).

**Never**:
- Modify source files. The plugin is read-only on the source layer.
- Modify `wiki/CLAUDE.md` or `wiki/config.yaml` after `init`. These are user-curated schema files; only the user edits them.
- Run `git commit` or `git push` on the user's behalf.
- Install git hooks (v2 only, opt-in).
- Touch files outside `wiki/`, `.code-wiki/`, and `.gitignore`.
- Skip `ignore_patterns` (no "I'll just include this one anyway" exceptions).
- Write a wiki page in a language other than `wiki_language`.
- Generate topic pages from `build` or `rebuild`. Topic pages are produced only by `topic` (explicit) or `query` (accepted lazy creation) or `sync` (regenerating an existing topic when its sources change).
- Perform a full source scan in `query` — source reads must always be guided by the wiki hierarchy.

---

## 15. Success Criteria

A v1 release is considered complete when:

- [ ] All 7 commands execute end-to-end on each of the fixture repos with no errors.
- [ ] `init` correctly scaffolds `wiki/`, `.code-wiki/`, and updates `.gitignore`.
- [ ] `build` produces a wiki where every non-ignored source folder under each source root has a corresponding wiki page.
- [ ] `sync` correctly handles add/modify/delete/rename of source files and propagates to ancestor wikis.
- [ ] `sync` performs soft-bootstrap when `state.json` is missing, in under 30 seconds for a 1k-file repo.
- [ ] `query` reads from the wiki (verified by inspection of which files Claude opens) and offers topic creation when criteria match.
- [ ] `lint` reports the 10 rule classes correctly on a deliberately-broken fixture.
- [ ] `topic` produces a coherent cross-cutting page from explicit invocation.
- [ ] `rebuild` with no args regenerates everything; with a path, regenerates only that subtree + ancestors.
- [ ] Plugin is registered in `marketplace.json` and installable via the marketplace flow.
- [ ] `code-wiki/README.md` documents installation, the 7 commands, and a quick-start example.

---

## 16. Resolved Decisions

The following questions were raised during spec drafting and have been resolved:

1. **Per-file page placement** — co-located in the same directory as the leaf `index.md`; no subdirectory. Example: `wiki/src/auth/index.md` + `wiki/src/auth/auth.md`. Naming collision (subdirectory with the same name as a file) is treated as a config/source-tree pathology and is not handled specially in v1.

2. **Source-root naming** — no `name:` field. The source root path itself is used as the wiki subdirectory path. Two source roots that share a basename but differ in path live at distinct wiki paths automatically. See §3 for validation rules.

3. **Topic page user-edits** — not preserved. The plugin assumes the user does not hand-edit auto-generated wiki content. All regeneration overwrites freely. The schema files `wiki/CLAUDE.md` and `wiki/config.yaml` are the only user-curated files inside `wiki/` and the plugin never auto-modifies them after `init`.

4. **Soft-bootstrap with stale `wiki/`** — the inferred `last_ingested_sha` (last commit touching `wiki/`) may predate later source-only commits. The subsequent `sync` will then process more changes than strictly minimal, regenerating the affected leaves and ancestors. This always converges correctly and the extra work is bounded by the normal sync ripple algorithm. No special handling required.

5. **Page generation prompt strategy** — parent generation uses three coordinated prompts: (a) loose-files synthesis over the parent's own files, (b) children-wikis synthesis reading direct children's `index.md`, (c) overall-role synthesis combining (a) and (b) into the page's Overview. Leaf generation uses a single prompt over the folder's source files. Per-file generation uses a focused prompt over a single file. Topic generation uses a multi-stage prompt: relevant-wiki collection → source touchpoint analysis → flow synthesis.

6. **Concurrent sync runs** — out of scope. Standard git merge conflict handling applies to wiki files; the plugin does not coordinate. Documenting this as a known accepted behavior.

7. **Wiki link cycles** — not flagged by lint. Markdown link graphs naturally tolerate cycles (e.g. topic A references topic B and vice versa is valid).

---

## 17. Verification Checklist (per-spec, pre-implementation)

- [x] Spec covers all six core areas (objective, tech, commands, structure, style, testing, boundaries).
- [ ] Human reviewed and approved the spec.
- [x] Success criteria are specific and testable.
- [x] Boundaries (Always / Ask first / Never) are defined.
- [x] Spec is saved to the repository (`code-wiki/SPEC.md`).
