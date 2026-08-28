# Implementation Plan: code-wiki v1

Plan for building the `code-wiki` Claude Code plugin per `SPEC.md`. This document is the bridge between the spec and the task list — it identifies components, dependencies, ordering, risks, and verification checkpoints.

---

## 1. Overview

`code-wiki` is a hybrid Python + Markdown plugin:

- **Python (`bin/`)** owns deterministic infrastructure: filesystem walking, git operations, JSON state I/O, hash computation, ignore-pattern matching, source/wiki path mapping, lint rule evaluation.
- **Markdown (`commands/`, `skills/`)** owns LLM-driven work: page generation, query synthesis, topic flow analysis. These read/write JSON via the Python helpers.
- **Templates (`templates/`)** are the canonical page formats referenced by both layers.

This separation matters because LLM-driven steps are non-deterministic and hard to test, while filesystem/state operations need to be exact. Putting state machinery in Python lets us unit-test the dangerous parts and lets the markdown commands stay focused on prompts.

Plugin lives at `code-wiki/` in this marketplace repo, sibling to `gastory/`. Same conventions as gastory (`.claude-plugin/plugin.json`, `commands/*.md`, `bin/*.py`, `skills/*`, `templates/*`).

---

## 2. Architecture Decisions

| Decision | Rationale |
|---|---|
| Hybrid Python + Markdown | Determinism (state, git, paths) needs Python; LLM orchestration needs markdown. Mirrors gastory. |
| Centralize path math in `bin/lib/wiki_path.py` | Source ↔ wiki relative paths are off-by-one prone. One module, unit-tested, used everywhere. |
| State machinery is atomic (write-temp + rename) | Partial writes corrupt state and force costly rebuilds. |
| Soft-bootstrap parses real markdown (mistune), not regex | Generated wikis are markdown; regex is fragile against formatting variation. |
| Bin scripts are CLI tools with JSON I/O | Markdown commands shell out and parse JSON. Clear boundary, testable. |
| Skills encode prompt patterns; commands orchestrate skills | Skills are reusable (leaf gen used by both build and sync). Commands handle flow control. |
| No unit-test framework for markdown | Verification is fixture-based regression. Python `bin/lib/` has standard pytest. |
| Sync uses git diff exclusively | mtime is unreliable across clones. Spec says git is required for sync. |
| Bottom-up generation is sequential per branch but parallel across siblings | Latency matters; siblings have no inter-dependency. v1 may keep it sequential for simplicity if parallelism complicates error handling. |

---

## 3. Component Breakdown

### Layer 0 — Plugin scaffolding

| Component | What it does |
|---|---|
| `code-wiki/.claude-plugin/plugin.json` | Plugin manifest (name, description, version, author) |
| `code-wiki/README.md` | User-facing intro, install, quick-start |
| `.claude-plugin/marketplace.json` (root) | Adds code-wiki entry alongside gastory |

### Layer 1 — Templates

| Component | What it does |
|---|---|
| `templates/wiki-CLAUDE.md` | Default wiki/CLAUDE.md content scaffolded by `init` |
| `templates/config-default.yaml` | Default wiki/config.yaml scaffolded by `init` |
| `templates/page-leaf.md` | Leaf folder page template |
| `templates/page-parent.md` | Parent folder page template (3-section synthesis) |
| `templates/page-perfile.md` | Per-file page template |
| `templates/page-topic.md` | Topic page template (with Flow section) |

### Layer 2 — Python infrastructure (`bin/lib/`)

| Module | Responsibility |
|---|---|
| `lib/config.py` | Read, validate, write `wiki/config.yaml`. Enforce source-root rules (no `.`, no nesting, no `wiki`/`.code-wiki`). |
| `lib/state.py` | Read/write `.code-wiki/state.json` atomically. Schema validation. |
| `lib/fs.py` | Walk source roots respecting `ignore_patterns`. Classify folders as leaf vs parent. List loose files. |
| `lib/git.py` | `current_sha()`, `diff(from, to) -> [(status, path)]`, `last_touched(path) -> sha`. |
| `lib/hashing.py` | SHA-256 of file content; SHA-256 of normalized markdown content. |
| `lib/wiki_path.py` | source path ↔ wiki path mapping; compute relative path from a wiki page to a source file or another wiki page. |
| `lib/links.py` | Parse markdown to extract outbound links (wiki and source). Used by lint and soft-bootstrap. |

### Layer 3 — Python commands (`bin/`)

| Script | Responsibility |
|---|---|
| `bin/init.py` | Scaffold `wiki/`, `.code-wiki/`, `.gitignore`. Validate source roots. |
| `bin/walk-tree.py` | Emit ordered work list (bottom-up) for build/rebuild. |
| `bin/scan-changes.py` | Given state + HEAD, compute dirty set (leaves + ancestors + affected topics). |
| `bin/state-bootstrap.py` | Soft-bootstrap state from committed wiki content. |
| `bin/state-update.py` | Apply post-generation updates to state.json. |
| `bin/lint.py` | Run all 10 lint rules; emit findings as JSON. |

### Layer 4 — Markdown commands (`commands/`)

| Command | Orchestrates |
|---|---|
| `init.md` | calls `bin/init.py`, handles user prompts |
| `build.md` | calls `bin/walk-tree.py` → loops invoking leaf/parent skills → calls `bin/state-update.py` |
| `sync.md` | calls `bin/state-bootstrap.py` if needed → `bin/scan-changes.py` → loops invoking skills → `bin/state-update.py` |
| `rebuild.md` | thin wrapper over build, with path scoping |
| `lint.md` | calls `bin/lint.py`, formats output |
| `query.md` | reads wiki, optionally drills into source, proposes topic creation |
| `topic.md` | invokes generate-topic-page skill, updates state |

### Layer 5 — Skills (`skills/`)

| Skill | Used by |
|---|---|
| `generate-leaf-page` | build, rebuild, sync |
| `generate-parent-page` | build, rebuild, sync (composes 3 sub-syntheses) |
| `generate-perfile-page` | build, rebuild, sync (when per_file_pages thresholds match) |
| `generate-topic-page` | topic, query (lazy), sync (regen) |

The parent skill internally orchestrates three syntheses (loose-files / children / overall) but is exposed as one skill to keep the command flow simple.

### Layer 6 — Fixtures & docs

| Component | Purpose |
|---|---|
| `fixtures/minimal/` | Tiny single-source-root tree, smoke testing |
| `fixtures/monorepo/` | Multiple source roots, validates path handling |
| `fixtures/mixed/` | Code + non-code (READMEs, configs), validates inclusion logic |
| `REGRESSION.md` | Manual checklist walked before any release |
| `README.md` | User documentation (final form, post-Phase 6) |

---

## 4. Dependency Graph

```
Layer 0 (scaffolding) ──────────────────────────┐
                                                 │
Layer 1 (templates) ─────────────────────┐       │
                                          │       │
Layer 2 (lib/): config, state, fs ───┐    │       │
                lib/: git, hash ─────┼─┐  │       │
                lib/: wiki_path,     │ │  │       │
                      links ─────────┼─┤  │       │
                                     ▼ ▼  ▼       │
Layer 3 (bin/): init.py ◄────────────────┐       │
                walk-tree.py ◄───────────┤       │
                scan-changes.py ◄────────┤       │
                state-bootstrap.py ◄─────┤       │
                state-update.py ◄────────┤       │
                lint.py ◄────────────────┘       │
                                                 │
Layer 5 (skills): leaf, parent, perfile, topic   │
                  (depend only on templates)     │
                                                 │
Layer 4 (commands): init.md ◄── bin/init.py ◄────┘
                    build.md ◄── bin/walk-tree, state-update + leaf/parent skills
                    sync.md ◄── bin/scan-changes, state-bootstrap, state-update + skills
                    rebuild.md ◄── (build.md + scoping)
                    query.md ◄── (wiki + lint links + topic skill for lazy creation)
                    topic.md ◄── (topic skill + state-update)
                    lint.md ◄── bin/lint.py

Layer 6 (fixtures, docs): depend on everything above
```

**Critical path** (longest dependency chain):
`config.py` → `wiki_path.py` → `walk-tree.py` → `generate-parent-page skill` → `build.md` → `fixtures + verification`

This is what gates "first usable wiki" — Phase 2 checkpoint.

---

## 5. Implementation Phases & Checkpoints

### Phase 1: Foundation (~8 tasks)

Build the scaffolding, all templates, all `bin/lib/` modules, and the `init` end-to-end.

**Why first**: Every other phase depends on `bin/lib/` and templates. `init` is the smallest end-to-end vertical slice and exercises the lib modules.

**Parallelizable**: Templates (T2-T3) and Python lib modules (T4-T7) are independent.

**Checkpoint 1**: Running `/code-wiki:init` in a fresh git repo produces a valid `wiki/` (with `CLAUDE.md`, `config.yaml`), an empty `.code-wiki/`, and a `.gitignore` entry. Source-root validation rejects bad inputs (`.`, nesting, `wiki`).

### Phase 2: First wiki via `build` (~4 tasks)

The first end-to-end vertical slice that produces a real wiki. Most LLM-prompt risk lives here.

**Why second**: Validates the entire generation flow on the simplest case before adding sync complexity.

**Parallelizable**: leaf and parent skills can be drafted in parallel, but parent depends on leaf existing for testing.

**Checkpoint 2**: `/code-wiki:build` on `fixtures/minimal/` produces wiki pages that:
- Match the templates (sections present, links valid).
- Reflect actual source content (spot-check 2-3 leaves and their parents).
- Populate state.json with correct `source_to_wiki`, `source_hashes`, `content_hashes`, `last_ingested_sha`.

### Phase 3: `sync` and `rebuild` (~4 tasks)

The hardest correctness logic — dirty set propagation, soft-bootstrap, ancestor regeneration.

**Why third**: Builds on build's generation primitives; reuses the same skills.

**Parallelizable**: `scan-changes.py` and `state-bootstrap.py` are independent.

**Checkpoint 3**: All four diff scenarios (add/modify/delete/rename) on `fixtures/minimal/` produce correct dirty sets and post-sync wiki state. Soft-bootstrap (delete state.json → run sync with no source changes) reconstructs identical state.

### Phase 4: `query` and `topic` (~3 tasks)

Read-side operations + topic-page synthesis with flow analysis.

**Why fourth**: Independent of sync correctness; can land after Phase 3 stabilizes.

**Parallelizable**: query.md and topic.md are independent of each other.

**Checkpoint 4**: 
- `/code-wiki:query` answers a multi-module question by reading only wiki pages (verified by inspecting which files Claude opens), proposes topic creation when threshold met.
- `/code-wiki:topic auth` on the auth fixture produces a topic page whose Flow section accurately describes end-to-end authentication.

### Phase 5: `lint` + per-file pages (~3 tasks)

The remaining quality-of-life features.

**Why fifth**: Lint depends on a built wiki to test against; per-file pages are an enhancement to leaf generation.

**Parallelizable**: lint and per-file work are independent.

**Checkpoint 5**:
- `/code-wiki:lint` on a deliberately-broken fixture reports findings in all 10 rule classes.
- Building on a fixture with a 1000-LOC file produces a per-file page in addition to the leaf page.

### Phase 6: Fixtures, docs, marketplace (~4 tasks)

Polish and release prep.

**Checkpoint 6** (release gate): All §15 success criteria met. Manual `REGRESSION.md` walked clean.

---

## 6. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Generated wiki content is low-signal or repetitive** (LLM produces filler instead of real synthesis) | High | High | Iterate prompts on real fixtures early. Test on at least 2 distinct languages (e.g. TS + Python). Include explicit "what makes a good page" examples in skills. Track via regression checklist. |
| **Sync dirty-set propagation has off-by-one bugs** (rename, deep nesting) | Medium | High | Implement deterministic logic in Python (testable). Cover the 4 git diff statuses + nested cases in unit tests. Fixture scenarios for each. |
| **Source-link relative paths broken** (off-by-one `../`) | High | Medium | Centralize in `wiki_path.py`, unit-tested. Lint rule `broken-link-source` catches regressions. |
| **State.json corruption from interrupted writes** | Low | High | Atomic writes (temp+rename) in `state.py`. On load, schema-validate; if invalid, recommend soft-bootstrap. |
| **Soft-bootstrap parses generated wiki incorrectly** (link extraction errors) | Medium | Medium | Use `mistune` (or similar) markdown parser, not regex. Round-trip test: build → snapshot state → delete state → bootstrap → compare. |
| **Token-budget overflow on large folders/files** | Medium | Medium | Enforce per-file LOC threshold (`per_file_pages.min_loc`). For large leaf folders, summarize then chunk. Surface friendly error if a single page generation exceeds limits. |
| **Topic page flow analysis is shallow or wrong** (LLM hallucinates control flow) | High | Medium | Require the topic skill to read concrete source files (not just wikis). Cite line ranges. Mark `Open Questions` for ambiguous cases rather than guessing. |
| **Performance: full build on 1000+ folder repo is slow** | Medium | Medium | Defer optimization to v2 unless blocking. Spec doesn't promise speed. Document expected cost in README. |
| **Multiple source-root path collisions on case-insensitive filesystems** | Low | Low | Validate at `init` time using normalized paths. |
| **No traditional regression tests for prompts** | High | Medium | Manual `REGRESSION.md` checklist; golden-output snapshots for fixtures (commit expected wiki, diff after changes); v2 may add eval harness. |

---

## 7. Parallelization Map

Items that can be built concurrently within a phase:

- **Phase 1**:
  - All templates (T2, T3) ∥ all `bin/lib/` modules (T4-T7)
  - Within `bin/lib/`: `config`+`state` ∥ `fs` ∥ `git`+`hash` ∥ `wiki_path`+`links`
- **Phase 2**: leaf-page skill (T9) ∥ `walk-tree.py` (T11)
- **Phase 3**: `scan-changes.py` (T13) ∥ `state-bootstrap.py` (T14)
- **Phase 4**: `query.md` (T17) ∥ topic skill (T18)
- **Phase 5**: lint (T20-T21) ∥ per-file (T22)
- **Phase 6**: fixtures (T23) ∥ README (T24); marketplace (T25) and regression doc (T26) at the end

Sequential bottlenecks: `bin/lib/` must precede all `bin/*.py`; build must precede sync; build must precede lint regression test.

---

## 8. Verification Strategy

### Per-task verification

Each task carries:
- **Acceptance criteria** (what must be true for the task to be done).
- **Verify** (a concrete check — Python script, manual command, file inspection).

### Phase checkpoints

After each phase, a gating check (see §5). Do not start the next phase until checkpoint passes.

### Pre-release verification (Phase 6)

- Run `/code-wiki:init` → `/code-wiki:build` → `/code-wiki:lint` on each of 3 fixtures clean.
- Walk `REGRESSION.md` checklist — each scenario produces expected output.
- Build wiki on a real codebase outside fixtures (suggest: this `claude-plugins` repo itself) to dogfood.
- Confirm marketplace install flow.

### Tooling
- Python helpers: `pytest` for `bin/lib/` modules. Tests live in `code-wiki/tests/` (pytest auto-discovery).
- Markdown commands: no automated test; verified via fixture runs.
- Skills: same — no automated test; manual review of generated output.

---

## 9. Task List Summary

26 tasks across 6 phases. Detailed task definitions (with acceptance criteria, verification, files touched, scope) will be the next deliverable in the `tasks` phase.

| Phase | Tasks | Focus |
|---|---|---|
| 1 — Foundation | T1–T8 | Plugin scaffolding, templates, `bin/lib/`, `init` |
| 2 — First build | T9–T12 | Leaf + parent skills, walk-tree, build command |
| 3 — Sync & rebuild | T13–T16 | scan-changes, state-bootstrap, sync, rebuild |
| 4 — Query & topic | T17–T19 | query, topic skill (with Flow), topic command |
| 5 — Lint & per-file | T20–T22 | 10 lint rules, lint command, per-file pages |
| 6 — Polish | T23–T26 | Fixtures, README, marketplace, REGRESSION.md |

---

## 10. Resolved Decisions

All open questions confirmed by human review:

1. **Python dependencies** — Use `mistune` + `pyyaml` via `requirements.txt`. Document install in README.
2. **Test framework** — `pytest`.
3. **Fixtures** — Three synthetic fixtures: `minimal/`, `monorepo/`, `mixed/`. Synthetic for determinism.
4. **Dogfood** — Phase 6 includes building wiki on this `claude-plugins` repo as a sanity check.
5. **Parallel sibling generation** — Sequential in v1; revisit in v2 if performance is annoying.
6. **Topic overlap detection** — During query lazy creation, read every topic page's title + first 200 chars; LLM judges overlap.
7. **`init` re-run** — Always abort if `wiki/` exists. No `--force` flag. User must `rm -rf wiki/` to start over.

---

## 11. Verification Checklist (this plan)

- [x] All major components from SPEC §3-§11 mapped to a layer/file
- [x] Dependency graph identifies the critical path
- [x] Phases are sized so each ends in a working, demonstrable state
- [x] Risks are concrete with specific mitigations
- [x] Each phase has a checkpoint with a binary pass/fail
- [x] Parallelization opportunities identified
- [x] Open questions surfaced before tasks phase
- [ ] **Human reviewed and approved the plan**
