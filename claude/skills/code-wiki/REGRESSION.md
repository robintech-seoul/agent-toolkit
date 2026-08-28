# code-wiki regression checklist

Manual scenarios to walk before any release. Each item is binary pass/fail. Run the full list against `fixtures/minimal/` (and selectively against `fixtures/monorepo/` and `fixtures/mixed/` for items marked **monorepo** / **mixed**).

Prerequisite: run `code-wiki/fixtures/init-fixtures.sh` so each fixture is a fresh git repo with 2 commits. Each scenario assumes a clean fixture state — `rm -rf <fixture>/wiki <fixture>/.code-wiki` between scenarios where needed.

## Init

- [ ] Run `/code-wiki:init` on a fresh fixture. Confirm `wiki/CLAUDE.md`, `wiki/config.yaml`, `.code-wiki/`, and `.gitignore` entry are created.
- [ ] Re-run `/code-wiki:init`. Aborts with "wiki/ already exists".
- [ ] Try `/code-wiki:init` with a `.` source root → rejected with clear error.
- [ ] Try `/code-wiki:init` with a nested pair (e.g. `src` and `src/api`) → rejected.
- [ ] Try `/code-wiki:init` with `wiki` as a source root → rejected.

## Build

- [ ] After `/code-wiki:init`, run `/code-wiki:build`. Every non-ignored source folder under each source root has a corresponding `wiki/<source-root-path>/.../index.md`.
- [ ] Generated leaf pages match the structure of `templates/page-leaf.md` (Files, Concepts, Dependencies, Notes sections — empty ones omitted).
- [ ] Generated parent pages match `templates/page-parent.md` (Overview, Sub-modules with prose synthesis, Loose files when applicable, Architecture, Related Topics).
- [ ] All wiki↔wiki and wiki↔source links resolve (cross-check via `/code-wiki:lint`).
- [ ] `state.json` populated with `wiki_pages`, `source_to_wiki`, `source_hashes`, and a non-null `last_ingested_sha`.
- [ ] `.code-wiki/log.md` has a `## <ts> build` entry with non-zero `created` count.
- [ ] Re-running `/code-wiki:build` without `--force` aborts.
- [ ] `/code-wiki:build --force` overwrites without aborting.

## Sync — the four diff scenarios

After a clean build, each of the following on the fixture:

- [ ] **Modify** an existing source file → `/code-wiki:sync` regenerates the file's leaf wiki AND its ancestors (parent up to source root), but no unrelated sibling wikis.
- [ ] **Add** a new source file (and folder) → sync creates a new leaf wiki and re-synthesizes the parent.
- [ ] **Delete** a source file → if it was the only file in its folder, sync removes the leaf wiki; if other files remain, the leaf is regenerated; the parent is regenerated.
- [ ] **Rename** a source file → sync treats as delete + add; old wiki entries removed, new ones created where applicable; parent regenerated.

## Soft-bootstrap

- [ ] Build wiki, commit `wiki/` to git, then `rm -rf .code-wiki`. Run `/code-wiki:sync`. Soft-bootstrap reconstructs `state.json` (without re-running LLM generation) and reports "Wiki is up to date" if no source changed since the last wiki commit.
- [ ] In the same scenario but with one source file modified after the wiki commit, sync correctly identifies the dirty leaf and regenerates it.

## Rebuild

- [ ] `/code-wiki:rebuild` (no arg) regenerates everything — same effect as `build --force`.
- [ ] `/code-wiki:rebuild src/auth` (path scoped) regenerates only `src/auth` and its ancestors up to the source root; `src/users`, `src/utils` etc. are untouched.
- [ ] `/code-wiki:rebuild not-a-source-root` rejected with clear error.

## Query

- [ ] Ask a narrow question (single-folder concern, e.g. "What does `auth/login.py` return?"). Answer cites 1–2 wiki pages; no topic prompt fires.
- [ ] Ask a cross-cutting question (e.g. "How does authentication work?" on **monorepo**). Answer cites ≥3 wiki pages from ≥2 sub-trees; topic prompt fires; user can decline and the answer is delivered cleanly.
- [ ] Same question, accept the topic prompt → `wiki/topics/<name>.md` is created with a substantive Flow section; `state.json` records the topic's source_files and referenced_wikis.
- [ ] Re-ask the same question after the topic exists. Topic prompt does NOT fire (existing topic detected via title + first 200 chars).
- [ ] Inspect the tool calls (Claude Code transcript): every source file Claude opened during query was reachable via a wiki page citation. No standalone source-tree enumeration occurred.

## Topic

- [ ] `/code-wiki:topic auth` on **monorepo** produces `wiki/topics/auth.md` with Overview, Key Components, Source Touchpoints, Flow, Patterns & Conventions, Open Questions.
- [ ] The Flow section contains a concrete trace (entry → middle → side effect), citing real source files with line ranges where applicable.
- [ ] After creating the topic, modify a referenced source file and run `/code-wiki:sync`. The topic appears in `dirty_topics`. Run `/code-wiki:topic auth` to refresh.
- [ ] After creating the topic, modify an *unrelated* source file and run `/code-wiki:sync`. The topic does NOT appear in `dirty_topics`.
- [ ] `/code-wiki:topic <existing-name>` prompts before overwriting.

## Lint

Set up a deliberately broken state on a fresh fixture (combine multiple breakages):
- Add a wiki page whose folder doesn't exist (`mkdir -p wiki/src/ghost && echo "# ghost" > wiki/src/ghost/index.md`) — phantom-wiki.
- Edit a wiki page to include a link to `./nowhere.md` — broken-link-wiki.
- Edit a wiki page to include a link to `../../src/missing.py` — broken-link-source.
- Delete a source file without syncing (so state.source_hashes mismatches the now-missing/changed file) — stale-wiki.
- Modify a source file referenced by a topic page without re-running topic — topic-source-drift.
- Create `wiki/orphan/index.md` with no links to it and no source folder — orphan-wiki.
- Add a folder under `src/` with no corresponding wiki page — missing-wiki.
- Edit a leaf wiki to fewer than 20 lines — length-too-short.
- (Optional) Pad a leaf wiki to >3000 lines — length-too-long.
- Corrupt `wiki/config.yaml` (e.g. set `version: 99`) and run lint separately — config-invalid (stops other rules).

Then:

- [ ] `/code-wiki:lint` reports findings for each of the 10 rules.
- [ ] Findings are grouped by severity (Error / Warning / Info) in the printed output.
- [ ] `/code-wiki:lint --fix` removes phantom wiki pages and prunes empty parent dirs; updates `state.json`. Other findings are NOT auto-modified.
- [ ] Re-running `/code-wiki:lint` after `--fix` shows zero phantom-wiki findings.

## Per-file pages

- [ ] On a fixture with a file ≥800 LOC (artificially pad one for testing if needed), `/code-wiki:build` produces a per-file wiki at `wiki/<source-root>/<...>/<filename>.md` next to the leaf's `index.md`. The leaf page links to it.
- [ ] On a fixture with a folder containing >20 files, build produces ~5–10 per-file pages for the most central files; remaining files appear as one-liners only in the leaf wiki.
- [ ] Editing `per_file_pages.enabled: false` in `wiki/config.yaml` and running `/code-wiki:rebuild` removes per-file generation; only `index.md` is produced.

## Dogfood

- [ ] Build wiki on `claude-plugins/` itself: from the repo root, run `/code-wiki:init` with `code-wiki, gastory` as source roots, then `/code-wiki:build`. Spot-check 3 wiki pages for accuracy: leaf `wiki/code-wiki/bin/lib/index.md`, parent `wiki/code-wiki/index.md`, leaf `wiki/gastory/commands/index.md` (or similar).
- [ ] Run `/code-wiki:lint` on the dogfooded wiki. Zero errors expected; warnings/info are acceptable.

## Marketplace install

- [ ] From a fresh test repo (not this one), run `/plugin marketplace add robintech-seoul/agent-toolkit` and `/plugin install code-wiki@robintech`. Confirm all 7 commands appear in `/help`.
- [ ] After install, `pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"` succeeds.

## Pass criteria

A release is green when **every** non-optional checkbox above passes on `fixtures/minimal/`, plus the marked monorepo/mixed scenarios pass on their respective fixtures, plus the dogfood scenario passes on `claude-plugins/`.

If any item fails, file the regression and block the release until fixed.
