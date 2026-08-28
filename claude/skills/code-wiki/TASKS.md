# Task List: code-wiki v1

Detailed implementation tasks broken down per `PLAN.md`. **27 tasks** across 6 phases. Each task is sized **S** (1–2 files) or **M** (3–5 files); none larger.

**Conventions**:
- Tasks numbered T1–T27 in dependency order (later tasks may depend on earlier ones; explicit dependencies listed per task).
- All paths relative to `/Users/seokhyunkim/workspace/claude-plugins/`.
- Plugin lives at `code-wiki/`. Marketplace manifest at `.claude-plugin/marketplace.json` (repo root).
- Python tests live at `code-wiki/tests/`, run via `pytest code-wiki/tests/`.
- Python deps: `mistune`, `pyyaml`, `pytest` listed in `code-wiki/requirements.txt`.

**Task ordering note** (vs. PLAN.md): `fixtures` (originally T23) is moved earlier to **T9** so the skills (T10, T11, T20) can be developed and iterated against real fixtures rather than ad-hoc throwaway dirs. The lint task (originally T20 with 10 rules) is split into **T22 (5 graph-integrity rules) + T23 (5 content/state rules)** to keep each task at M scope.

---

## Phase 1 — Foundation (T1–T8)

### T1: Plugin scaffolding

**Description**: Create the plugin's directory skeleton, manifest, marketplace entry, and Python deps file.

**Acceptance criteria**:
- `code-wiki/.claude-plugin/plugin.json` exists with name, description, version `0.1.0`, author (matching gastory's author block).
- `code-wiki/README.md` exists as a 1-paragraph stub (full content in T26).
- `code-wiki/requirements.txt` lists `mistune>=3`, `pyyaml>=6`, `pytest>=8`.
- `.claude-plugin/marketplace.json` (repo root) includes a `code-wiki` plugin entry alongside `gastory`.
- `code-wiki/.gitignore` excludes `__pycache__/`, `*.pyc`, `.pytest_cache/`.

**Verification**:
- `python3 -c "import json; json.load(open('code-wiki/.claude-plugin/plugin.json'))"` exits 0.
- `python3 -c "import json; m=json.load(open('.claude-plugin/marketplace.json')); assert any(p['name']=='code-wiki' for p in m['plugins'])"` exits 0.

**Dependencies**: None.

**Files**:
- `code-wiki/.claude-plugin/plugin.json`
- `code-wiki/README.md`
- `code-wiki/requirements.txt`
- `code-wiki/.gitignore`
- `.claude-plugin/marketplace.json` (edit)

**Scope**: S

---

### T2: Page format templates

**Description**: Create the four wiki page templates (leaf, parent, per-file, topic) per SPEC §6.

**Acceptance criteria**:
- `code-wiki/templates/page-leaf.md` matches SPEC §6 leaf template exactly.
- `code-wiki/templates/page-parent.md` matches the 3-section parent template (Overview, Sub-modules with prose synthesis, Loose files, Architecture, Related Topics) and includes the "Generation strategy" note.
- `code-wiki/templates/page-perfile.md` matches per-file template.
- `code-wiki/templates/page-topic.md` matches topic template (with **Flow** section).

**Verification**: Visual diff against SPEC §6. Section headings match.

**Dependencies**: None.

**Files**:
- `code-wiki/templates/page-leaf.md`
- `code-wiki/templates/page-parent.md`
- `code-wiki/templates/page-perfile.md`
- `code-wiki/templates/page-topic.md`

**Scope**: S

---

### T3: Init-time templates (CLAUDE.md + config.yaml)

**Description**: Default content that `init` copies into the user's `wiki/` directory.

**Acceptance criteria**:
- `code-wiki/templates/wiki-CLAUDE.md` contains style/voice guidance: page length norms, link rules (prefer wiki>source), tone (factual, no opinions), structure preservation, topic creation criteria.
- `code-wiki/templates/config-default.yaml` matches SPEC §5 schema with sensible defaults (empty `source_roots:` placeholder, language `en`, standard `ignore_patterns`, `per_file_pages.min_loc: 800`, `max_files_per_folder: 20`).
- Both templates include comments documenting each section.

**Verification**: Visual review against SPEC §5/6.

**Dependencies**: None.

**Files**:
- `code-wiki/templates/wiki-CLAUDE.md`
- `code-wiki/templates/config-default.yaml`

**Scope**: S

---

### T4: bin/lib — config & state

**Description**: Python modules for loading, validating, and atomically writing `config.yaml` and `state.json`.

**Acceptance criteria**:
- `bin/lib/config.py`:
  - `load(project_root) -> Config` reads `wiki/config.yaml`.
  - Enforces source-root rules: must be relative, non-empty, not `.`, not `wiki`, not `.code-wiki`, must exist as a directory at runtime, no source root may be a prefix of another.
  - Schema validation: required fields present, types correct.
- `bin/lib/state.py`:
  - `load(project_root) -> State | None` reads `.code-wiki/state.json`, returns `None` if missing.
  - `save(project_root, state)` writes atomically (write to `.tmp` + `os.replace`).
  - Schema validation on load; raise `StateCorrupted` with bootstrap suggestion if invalid.
- pytest tests for both modules.

**Verification**: `pytest code-wiki/tests/test_config.py code-wiki/tests/test_state.py` all green. Round-trip + invalid-input rejection covered.

**Dependencies**: T1.

**Files**:
- `code-wiki/bin/lib/__init__.py`
- `code-wiki/bin/lib/config.py`
- `code-wiki/bin/lib/state.py`
- `code-wiki/tests/__init__.py`
- `code-wiki/tests/test_config.py`
- `code-wiki/tests/test_state.py`

**Scope**: M

---

### T5: bin/lib — fs (walking, ignore, leaf detection)

**Description**: Filesystem traversal respecting `ignore_patterns`, with leaf/parent classification.

**Acceptance criteria**:
- `bin/lib/fs.py`:
  - `walk_source_root(root, ignore_patterns) -> Iterator[FolderInfo]` yields folders in **bottom-up** order. `FolderInfo` has `path`, `is_leaf`, `loose_files` (files directly in folder, ignored ones excluded), `child_dirs`.
  - Ignore patterns are gitignore-style globs evaluated relative to the source root.
  - Empty folders (after applying ignores) are skipped.
- pytest tests over synthetic dir trees with known structure.

**Verification**: `pytest code-wiki/tests/test_fs.py` all green. Test cases: nested tree, ignored subfolder, ignored file, empty folder pruning.

**Dependencies**: T1.

**Files**:
- `code-wiki/bin/lib/fs.py`
- `code-wiki/tests/test_fs.py`

**Scope**: M

---

### T6: bin/lib — git & hashing

**Description**: Git operations and content hashing primitives.

**Acceptance criteria**:
- `bin/lib/git.py`:
  - `current_sha(project_root) -> str` (`git rev-parse HEAD`).
  - `diff(project_root, from_sha, to_sha) -> List[Tuple[Status, Path, Optional[Path]]]` returns each change with status `A|M|D|R` and (for renames) old + new path.
  - `last_touched(project_root, path) -> Optional[str]` returns the SHA of the last commit modifying `path`, or `None`.
  - Raises `NotAGitRepo` if not in a git repository.
- `bin/lib/hashing.py`:
  - `sha256_file(path) -> str` (hex digest of file content).
  - `sha256_text(content: str) -> str` (used for normalized markdown hashing).
- pytest tests inside a temp git repo (use `pytest` fixtures; create + commit + diff).

**Verification**: `pytest code-wiki/tests/test_git.py code-wiki/tests/test_hashing.py` all green.

**Dependencies**: T1.

**Files**:
- `code-wiki/bin/lib/git.py`
- `code-wiki/bin/lib/hashing.py`
- `code-wiki/tests/test_git.py`
- `code-wiki/tests/test_hashing.py`

**Scope**: M

---

### T7: bin/lib — wiki_path & links

**Description**: Path math (source ↔ wiki ↔ relative links) and markdown link extraction.

**Acceptance criteria**:
- `bin/lib/wiki_path.py`:
  - `source_to_wiki(src_path, source_root, project_root) -> wiki_path` (e.g. `src/a/b.ts` → `wiki/src/a/b.md` for per-file or `wiki/src/a/index.md` for folder).
  - `wiki_to_source(wiki_path) -> source_path` (inverse, returns folder for `index.md`).
  - `relative_link(from_wiki, to_target) -> str` produces a markdown-friendly relative path with correct `../` count.
  - `is_index(wiki_path) -> bool`.
- `bin/lib/links.py`:
  - `parse_outbound(md_content) -> List[Link]` extracts all markdown links via `mistune`. Each `Link` has `target`, `kind` (`wiki|source|external`), `display`.
  - Classification: target inside `wiki/` → `wiki`, target inside a configured source root → `source`, http(s) → `external`.
- pytest tests: round-trip path conversions, sample wiki page parsing.

**Verification**: `pytest code-wiki/tests/test_wiki_path.py code-wiki/tests/test_links.py` all green. Off-by-one cases covered (single-level, deep nesting).

**Dependencies**: T1.

**Files**:
- `code-wiki/bin/lib/wiki_path.py`
- `code-wiki/bin/lib/links.py`
- `code-wiki/tests/test_wiki_path.py`
- `code-wiki/tests/test_links.py`

**Scope**: M

---

### T8: `/code-wiki:init` (Python + markdown)

**Description**: Bootstrap the plugin in a user's project. Interactive language prompt; aborts if `wiki/` exists.

**Acceptance criteria**:
- `bin/init.py`:
  - Args: `--source-roots <comma-separated>`, `--language <code>`, `--language-hints <comma-separated>`.
  - Aborts with clear error if `wiki/` already exists.
  - Validates source roots (uses `lib/config.py` validation logic).
  - Creates `wiki/` with `CLAUDE.md` and `config.yaml` from templates (filled in with user inputs).
  - Creates `.code-wiki/` (empty).
  - Appends `.code-wiki/` to `.gitignore` (creating file if absent; idempotent).
  - Prints next-step instructions.
- `commands/init.md`:
  - Interactive flow: asks for source roots, language (default `en`), optional language hints.
  - Calls `bin/init.py` with collected args.
  - Reports success or error.

**Verification**:
- Run `/code-wiki:init` in a fresh empty git repo. Confirm `wiki/CLAUDE.md`, `wiki/config.yaml`, `.code-wiki/`, and `.gitignore` entry exist.
- Re-run `init` in same repo: aborts.
- Pass invalid source roots (`.`, `wiki`, nested pair): rejected with errors.

**Dependencies**: T2, T3, T4, T5.

**Files**:
- `code-wiki/bin/init.py`
- `code-wiki/commands/init.md`

**Scope**: M

---

### Checkpoint 1 — Foundation

- [ ] `pytest code-wiki/tests/` all green.
- [ ] `/code-wiki:init` works in a fresh git repo: scaffolds wiki/, .code-wiki/, .gitignore.
- [ ] Source-root validation rejects `.`, `wiki`, `.code-wiki`, nested pairs.
- [ ] Plugin appears in `marketplace.json`.

---

## Phase 2 — Fixtures & first build (T9–T13)

### T9: Fixture repos

**Description**: Three synthetic git fixtures used to develop and regression-test the skills (T10/T11/T20) and all subsequent commands.

**Acceptance criteria**:
- `code-wiki/fixtures/minimal/`: ~10 source files, single source root (`src/`), 2 levels deep. Initialized as a git repo with at least 2 commits.
- `code-wiki/fixtures/monorepo/`: 3 source roots (`apps/web/src`, `apps/api/src`, `packages/lib`). Each contains 5–10 files. At least 2 commits.
- `code-wiki/fixtures/mixed/`: code + READMEs + a config file + a non-code asset directory (e.g. `static/`). At least 2 commits.
- Each fixture has its own `README.md` describing its shape and intended use.
- A small script `code-wiki/fixtures/init-fixtures.sh` (or `.py`) that creates the git repos from the source files (so they're reproducible).
- Source code is realistic enough to exercise leaf/parent generation: at least one fixture has a folder with both subfolders and loose files (for parent's "Loose files" section); at least one has an auth-related module spread across 2+ folders (for topic Flow analysis later).

**Verification**:
- Each fixture is a valid git repo (`git -C fixtures/<name> log` shows commits).
- Code is syntactically valid (Python: `python3 -m py_compile` on .py files; or just visually for placeholder code).
- The `init-fixtures.sh` script reproduces fixtures identically when re-run.

**Dependencies**: None (fixtures are independent of plugin code).

**Files**:
- `code-wiki/fixtures/minimal/...`
- `code-wiki/fixtures/monorepo/...`
- `code-wiki/fixtures/mixed/...`
- `code-wiki/fixtures/init-fixtures.sh`
- `code-wiki/fixtures/README.md` (overview of all 3 fixtures)

**Scope**: M

---

### T10: `skills/generate-leaf-page`

**Description**: SKILL.md describing how to generate a leaf folder wiki page from source files. Iterated against fixtures from T9.

**Acceptance criteria**:
- Skill specifies inputs (folder path, source files in folder, language, language_hints, ignore_patterns) and output (markdown file at the appropriate wiki path).
- References `templates/page-leaf.md`.
- Includes 2 concrete examples (good vs bad page) showing what makes a page useful.
- Specifies link computation via `bin/lib/wiki_path.py`.
- Specifies that non-code files (READMEs, configs) are read for context but do not get their own pages.

**Verification**: Dry-run on `fixtures/minimal/src/<a leaf folder>`. Output is markdown matching the template. Source links resolve.

**Dependencies**: T2, T7, T9.

**Files**:
- `code-wiki/skills/generate-leaf-page/SKILL.md`

**Scope**: S

---

### T11: `skills/generate-parent-page` (3-step composition)

**Description**: SKILL.md orchestrating loose-files synthesis + children-wikis synthesis + overall-role synthesis into one parent page.

**Acceptance criteria**:
- Skill specifies inputs (folder path, loose source files, list of direct child wiki paths) and output (markdown matching `templates/page-parent.md`).
- Documents the 3 internal sub-syntheses and their composition into the page's Overview.
- Mermaid diagram inclusion is explicitly LLM-judgment (only when prose alone is insufficient).
- Sub-modules section produces narrative paragraphs per child, not just one-liners.

**Verification**: Dry-run on `fixtures/mixed/` parent folder (which has both subfolders and loose files). Verify each section is populated and the Sub-modules section reads as prose, not just bullets.

**Dependencies**: T2, T7, T9, T10.

**Files**:
- `code-wiki/skills/generate-parent-page/SKILL.md`

**Scope**: M

---

### T12: `bin/walk-tree.py`

**Description**: Emit ordered work list (bottom-up) for build/rebuild.

**Acceptance criteria**:
- Args: `--source-root <path>` (repeatable) or reads from config.
- Output (stdout): JSON list of work items: `{path, kind: "leaf"|"parent", source_root, source_files, child_wikis}`.
- Order: every leaf precedes its parent; siblings in any deterministic order (alphabetical).
- Honors `ignore_patterns`.
- pytest tests covering ordering on synthetic trees and on `fixtures/minimal/`.

**Verification**: `pytest code-wiki/tests/test_walk_tree.py` all green. Run on a fixture and inspect ordering.

**Dependencies**: T4, T5, T7, T9.

**Files**:
- `code-wiki/bin/walk-tree.py`
- `code-wiki/tests/test_walk_tree.py`

**Scope**: M

---

### T13: `/code-wiki:build`

**Description**: End-to-end build: walk source roots → invoke skills → write state.

**Acceptance criteria**:
- `commands/build.md`:
  - Validates `wiki/` exists with config.yaml; aborts if not (suggest `init`).
  - Calls `bin/walk-tree.py` to get work list.
  - For each work item: invokes leaf or parent skill; writes the resulting page to its wiki path.
  - After all generation: invokes `bin/state-update.py` to record `source_to_wiki`, `source_hashes`, `content_hashes`, `last_ingested_sha`.
  - Appends a build entry to `.code-wiki/log.md`.
  - `--force` flag overrides existing wiki content (otherwise aborts if any source-root subdirectory is non-empty).
- `bin/state-update.py`:
  - Args: JSON of generated pages (path, source_files, child_wikis).
  - Reads or initializes state.json; updates entries; writes atomically.

**Verification**:
- Run `/code-wiki:init` then `/code-wiki:build` in `fixtures/minimal/`.
- Inspect: every non-ignored folder has a wiki page; state.json populated; log.md has entry.

**Dependencies**: T9, T10, T11, T12.

**Files**:
- `code-wiki/commands/build.md`
- `code-wiki/bin/state-update.py`
- `code-wiki/tests/test_state_update.py`

**Scope**: M

---

### Checkpoint 2 — First wiki

- [ ] `/code-wiki:build` produces a wiki on `fixtures/minimal/`.
- [ ] Generated pages match templates (sections present, links valid).
- [ ] Pages reflect actual source content (spot-check 2 leaves + 1 parent).
- [ ] state.json fully populated; log.md has build entry.

---

## Phase 3 — Sync & rebuild (T14–T17)

### T14: `bin/scan-changes.py`

**Description**: Compute dirty set from state + current HEAD diff.

**Acceptance criteria**:
- Args: project root.
- Reads state.json, computes `git diff <last_ingested_sha>..HEAD`.
- Outputs JSON: `{dirty_leaves: [...], dirty_parents: [...], dirty_topics: [...], deletions: [...]}`.
- Handles all 4 statuses: A (add), M (modify), D (delete), R (rename).
- Filters by ignore_patterns and source-root membership.
- Computes ancestor propagation: every dirty leaf's parents up to source root added to `dirty_parents`, in order from deepest to shallowest.
- Identifies dirty topics by checking each topic's recorded source references against the change set.
- pytest tests with mock state + diff scenarios.

**Verification**: `pytest code-wiki/tests/test_scan_changes.py` all green. Cover A/M/D/R + ancestor propagation + topic invalidation.

**Dependencies**: T4, T5, T6.

**Files**:
- `code-wiki/bin/scan-changes.py`
- `code-wiki/tests/test_scan_changes.py`

**Scope**: M

---

### T15: `bin/state-bootstrap.py`

**Description**: Reconstruct state.json from a committed `wiki/`.

**Acceptance criteria**:
- Args: project root.
- Walks `wiki/`, parses each page via `lib/links.py`, classifies pages as leaf/parent/topic.
- Reconstructs `source_to_wiki`, `child_wikis`, `referenced_wikis` (for topics).
- Computes `content_hash` for each wiki page; computes `source_hashes` for each referenced source file.
- Sets `last_ingested_sha` from `git log -1 --format=%H -- wiki/`.
- If no commit touches `wiki/`, errors with: "wiki/ has not been committed; run /code-wiki:build first."
- Writes state.json atomically.

**Verification**:
- `pytest code-wiki/tests/test_state_bootstrap.py`.
- End-to-end: build wiki → commit → snapshot state → delete state.json → run bootstrap → diff state (`source_to_wiki`, `child_wikis`, `last_ingested_sha` should match; content_hashes will match if pages weren't touched).

**Dependencies**: T4, T6, T7.

**Files**:
- `code-wiki/bin/state-bootstrap.py`
- `code-wiki/tests/test_state_bootstrap.py`

**Scope**: M

---

### T16: `/code-wiki:sync`

**Description**: Incremental wiki update orchestration.

**Acceptance criteria**:
- `commands/sync.md`:
  - Verifies git repo (else abort with message).
  - Reads config; aborts if `wiki/` missing.
  - If state.json missing: invokes `bin/state-bootstrap.py`; if bootstrap fails (no wiki commits), surfaces error.
  - Calls `bin/scan-changes.py` for dirty set.
  - Iterates dirty leaves (regenerate via leaf skill, or delete page if folder is empty after applying changes).
  - Iterates dirty parents in deepest-to-shallowest order (regenerate via parent skill, reading freshly-regenerated children).
  - Iterates dirty topics (regenerate via topic skill).
  - Calls `bin/state-update.py` to update state.
  - Appends sync entry to log.md (counts of created/updated/deleted pages).
- Edge cases handled:
  - Brand-new source folder (creates leaf wiki, registers in mapping).
  - Source folder fully deleted (deletes wiki page, removes mapping).
  - Rename = delete + add semantically.

**Verification**:
- Run 4 scenarios on `fixtures/minimal/` (add/modify/delete/rename source file). Inspect: only affected pages regenerated; ancestors propagated; state.json updated.
- Soft-bootstrap scenario: build → commit wiki → delete state.json → sync (no source changes) → no spurious regenerations.

**Dependencies**: T10, T11, T14, T15.

**Files**:
- `code-wiki/commands/sync.md`

**Scope**: M

---

### T17: `/code-wiki:rebuild`

**Description**: Force regeneration with optional path scoping.

**Acceptance criteria**:
- `commands/rebuild.md`:
  - No arg: equivalent to `build --force` over all source roots.
  - With path arg: regenerate that subtree's leaves and parents + ancestors up to source root + any affected topics.
  - Validates that path is inside a configured source root; rejects otherwise.
  - Updates state.json correctly (path's pages get new content_hashes; rest untouched).

**Verification**: Build minimal fixture → `/code-wiki:rebuild fixtures/minimal/src/<sub>` → confirm only that subtree + ancestors regenerated; state.json content_hashes for untouched pages unchanged.

**Dependencies**: T13, T16.

**Files**:
- `code-wiki/commands/rebuild.md`

**Scope**: S

---

### Checkpoint 3 — Sync correctness

- [ ] All 4 diff scenarios produce correct dirty sets.
- [ ] Soft-bootstrap reconstructs state without spurious regenerations.
- [ ] Rebuild with path scoping works.

---

## Phase 4 — Query & topic (T18–T20)

### T18: `/code-wiki:query`

**Description**: Wiki-first Q&A with optional source drill-down + topic candidate proposal.

**Acceptance criteria**:
- `commands/query.md`:
  - Reads `wiki/CLAUDE.md` and traverses wiki tree starting from root index files.
  - Synthesizes answer with markdown-link citations to wiki pages and source files actually used.
  - Source reads guided strictly by wiki hierarchy (no enumeration of source tree). The instruction is explicit and verifiable by inspecting which files Claude opens.
  - When topic candidate criteria match (≥3 distinct leaf wiki pages cited from ≥2 sub-trees, non-trivial answer):
    - Reads each existing topic page's title + first 200 chars to check overlap (per resolved decision §10.6 in PLAN.md).
    - If no overlap: prompts user "File as `wiki/topics/<suggested-name>.md`? [y/N]".
    - If user accepts: invokes the topic skill with the question + answer + cited pages; writes topic; updates state via `bin/state-update.py`.

**Verification**:
- Ask 3 questions on a fixture: (a) narrow (single-folder), (b) cross-cutting (≥2 modules), (c) trivial.
- Confirm: (a) cites 1-2 wikis, no topic prompt; (b) cites multiple wikis, topic prompt fires; (c) short answer, no topic prompt.
- Confirm no full source scan occurred (inspect tool calls).

**Dependencies**: Phase 2 done.

**Files**:
- `code-wiki/commands/query.md`

**Scope**: M

---

### T19: `skills/generate-topic-page` (with Flow analysis)

**Description**: SKILL.md for generating a topic page with end-to-end Flow analysis from source.

**Acceptance criteria**:
- Skill takes inputs: topic name, optional 1-line description, list of relevant wiki paths (or auto-discovers via topic name search across wiki).
- Reads relevant wiki pages first, then **reads concrete source files** referenced by them to reconstruct actual control flow / data flow.
- Output matches `templates/page-topic.md`: Overview, Key Components, Source Touchpoints, **Flow** (narrative trace), Patterns & Conventions, Open Questions.
- Flow section traces through entry points to side effects, citing source files with line ranges.
- Marks ambiguities in Open Questions rather than guessing.

**Verification**: Generate "auth" topic on a fixture with auth-related code. Manually inspect Flow section: does it accurately describe the auth path end-to-end?

**Dependencies**: T2, T7, T9.

**Files**:
- `code-wiki/skills/generate-topic-page/SKILL.md`

**Scope**: M

---

### T20: `/code-wiki:topic`

**Description**: Explicit topic page creation.

**Acceptance criteria**:
- `commands/topic.md`:
  - Args: topic name (required), optional description.
  - If `wiki/topics/<name>.md` exists: prompts before overwriting.
  - Invokes generate-topic-page skill.
  - Updates state.json with topic's `source_files` and `referenced_wikis` so sync can keep it current.
  - Appends to log.md.

**Verification**:
- Create topic on a fixture.
- Touch a referenced source file, run sync, confirm topic regenerated.
- Touch an unrelated source file, run sync, confirm topic NOT regenerated.

**Dependencies**: T19, T14.

**Files**:
- `code-wiki/commands/topic.md`

**Scope**: S

---

### Checkpoint 4 — Query & topic

- [ ] Query reads only wiki + targeted sources, never full scan.
- [ ] Topic candidate detection prompts on cross-cutting questions.
- [ ] Topic page Flow section is meaningful (manual review).
- [ ] Sync correctly tracks topic source dependencies.

---

## Phase 5 — Lint & per-file (T21–T24)

### T21: `bin/lint.py` — graph-integrity rules

**Description**: First half of lint — 5 rules concerning the wiki/source graph integrity.

**Acceptance criteria**:
- `bin/lint.py` skeleton with rule-registration framework (each rule is a function returning `List[Finding]`).
- Implements 5 rules:
  - `broken-link-wiki` (Error): wiki→wiki link to non-existent page.
  - `broken-link-source` (Error): wiki→source link to non-existent file.
  - `phantom-wiki` (Error): wiki page whose corresponding source folder no longer exists.
  - `missing-wiki` (Warning): source folder under a source root, not ignored, has no wiki page.
  - `orphan-wiki` (Warning): wiki page with no inbound links and no corresponding source folder.
- Output (stdout): JSON list of findings.
- pytest tests for each rule using `fixtures/broken/` (created within this task).

**Verification**: `pytest code-wiki/tests/test_lint_graph.py` all green. Run on broken fixture, confirm findings cover all 5 rules.

**Dependencies**: T4, T5, T7.

**Files**:
- `code-wiki/bin/lint.py`
- `code-wiki/tests/test_lint_graph.py`
- `code-wiki/fixtures/broken/...` (small fixture for testing)

**Scope**: M

---

### T22: `bin/lint.py` — content/state rules + `--fix`

**Description**: Second half of lint — 5 rules about content quality and state consistency, plus the `--fix` flag.

**Acceptance criteria**:
- Adds 5 more rules to `bin/lint.py`:
  - `stale-wiki` (Warning): source file's content hash differs from `state.json`'s `source_hashes` entry. Skipped with warning if state.json missing.
  - `length-too-short` (Info): leaf wiki < 20 lines.
  - `length-too-long` (Info): leaf wiki > 3000 lines.
  - `topic-source-drift` (Warning): topic page's listed sources have changed.
  - `config-invalid` (Error): `config.yaml` schema or referenced source roots invalid.
- Implements `--fix` flag (conservative): only `phantom-wiki` removal and content-hash refresh post-regeneration. Other findings emit warnings only.
- Extends `fixtures/broken/` to trigger these 5 rules.
- pytest tests for each rule.

**Verification**: `pytest code-wiki/tests/test_lint_content.py` all green. Run with `--fix` on broken fixture, confirm phantom-wiki entries removed.

**Dependencies**: T21.

**Files**:
- `code-wiki/bin/lint.py` (edit)
- `code-wiki/tests/test_lint_content.py`
- `code-wiki/fixtures/broken/...` (extend)

**Scope**: M

---

### T23: `/code-wiki:lint`

**Description**: Markdown command that invokes bin/lint.py and presents findings.

**Acceptance criteria**:
- `commands/lint.md`:
  - Calls `bin/lint.py`, parses JSON output.
  - Pretty-prints findings grouped by severity (Error / Warning / Info).
  - `--fix` passes through to `bin/lint.py`.

**Verification**: Run on broken fixture; output formatting clean. Run with `--fix`; phantom-wiki findings disappear afterward.

**Dependencies**: T21, T22.

**Files**:
- `code-wiki/commands/lint.md`

**Scope**: S

---

### T24: Per-file pages (`skills/generate-perfile-page` + leaf integration)

**Description**: Per-file page generation skill + decision logic baked into leaf skill.

**Acceptance criteria**:
- `skills/generate-perfile-page/SKILL.md` describes single-file page generation per `templates/page-perfile.md`.
- `skills/generate-leaf-page/SKILL.md` (T10) updated to:
  - Detect files matching `per_file_pages.min_loc` (default 800) or folders with >`max_files_per_folder` files.
  - For matching files: spawn per-file pages and link them from the leaf page's "Files" section.
  - For non-matching files: one-line entry in leaf page.
- Honors `per_file_pages.enabled: false` to disable entirely.

**Verification**: Build wiki on a fixture containing (a) a 1000-LOC file, (b) a folder with 25 small files. Confirm: (a) per-file page exists and is linked from leaf; (b) most central files get per-file pages, rest are one-liners.

**Dependencies**: T10, T2.

**Files**:
- `code-wiki/skills/generate-perfile-page/SKILL.md`
- `code-wiki/skills/generate-leaf-page/SKILL.md` (edit)

**Scope**: M

---

### Checkpoint 5 — Lint & per-file

- [ ] All 10 lint rules detect their target on broken fixture.
- [ ] `--fix` removes phantom wikis only.
- [ ] Per-file pages spawn correctly for large files and large folders.

---

## Phase 6 — Polish (T25–T27)

### T25: README.md (full version)

**Description**: Replace stub with comprehensive user documentation.

**Acceptance criteria**:
- Sections: Overview, Concept (1-paragraph llm-wiki summary), Install (marketplace flow + `pip install -r requirements.txt`), Quick-start (3 commands: init → build → query), Command reference (all 7 commands with examples), Configuration (`config.yaml` annotated), Troubleshooting (common errors + fixes), v2 roadmap.
- Example outputs (a fragment of generated wiki).
- Links to SPEC.md and PLAN.md for deeper context.

**Verification**: Hand the README to someone unfamiliar with the plugin; they can follow it from install to first query.

**Dependencies**: All commands done (T8, T13, T16, T17, T18, T20, T23).

**Files**:
- `code-wiki/README.md` (rewrite)

**Scope**: M

---

### T26: Marketplace finalization

**Description**: Polish marketplace.json description and verify install flow.

**Acceptance criteria**:
- `marketplace.json` `code-wiki` entry has a clear, inviting one-line description (matching gastory's tone).
- Install flow tested: from another directory, `add` this marketplace → `install code-wiki` → commands appear.

**Verification**: Manual install from a fresh test repo.

**Dependencies**: T25.

**Files**:
- `.claude-plugin/marketplace.json` (edit)

**Scope**: XS

---

### T27: REGRESSION.md (manual checklist)

**Description**: Pre-release verification checklist.

**Acceptance criteria**:
- Lists ordered scenarios covering all 7 commands.
- Covers all 4 sync diff scenarios (A/M/D/R).
- Covers soft-bootstrap path.
- Covers per-file page generation.
- Covers topic Flow analysis.
- Covers `lint --fix` on phantom wikis.
- Includes the dogfood scenario: build wiki on `claude-plugins/` itself.
- Each item is binary pass/fail.

**Verification**: Walk the checklist once on `fixtures/minimal/`. All items pass.

**Dependencies**: All preceding tasks.

**Files**:
- `code-wiki/REGRESSION.md`

**Scope**: S

---

### Checkpoint 6 — Release gate

- [ ] All §15 success criteria from SPEC.md met.
- [ ] `REGRESSION.md` walked clean on all 3 fixtures.
- [ ] Dogfood: wiki built on `claude-plugins/` itself.
- [ ] Marketplace install flow verified.
- [ ] README is complete and correct.

---

## Summary

| Phase | Tasks | Sizes |
|---|---|---|
| 1 — Foundation | T1–T8 (8) | 5×M, 3×S |
| 2 — Fixtures & first build | T9–T13 (5) | 4×M, 1×S |
| 3 — Sync & rebuild | T14–T17 (4) | 3×M, 1×S |
| 4 — Query & topic | T18–T20 (3) | 2×M, 1×S |
| 5 — Lint & per-file | T21–T24 (4) | 3×M, 1×S |
| 6 — Polish | T25–T27 (3) | 1×M, 1×S, 1×XS |

**Total**: 27 tasks. ~18×M, ~8×S, 1×XS. No L+ tasks.

Estimated effort (very rough, assumes focused agent sessions):
- M tasks: ~1.5h each → ~27h
- S tasks: ~30min each → ~4h
- Total: ~31 hours of agent work + iteration on prompt quality.

---

## Verification (this task list)

- [x] Every task has acceptance criteria.
- [x] Every task has a verification step.
- [x] Task dependencies are identified and ordered correctly.
- [x] No task touches more than ~5 files.
- [x] Checkpoints exist between major phases.
- [x] **Human reviewed and approved the task list.**
