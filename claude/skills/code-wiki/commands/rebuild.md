---
description: Force regeneration of the wiki — entire tree (no args) or a sub-tree (path arg). Use after schema changes or when the wiki is structurally broken; for normal incremental updates, prefer `/code-wiki:sync`.
argument-hint: [<path>]
allowed-tools: Bash(python3 *), Bash(git *), Bash(rm *), Bash(rmdir *), Bash(mkdir *), Read, Write, Skill, Agent
---

The user wants to force-regenerate part or all of the wiki. The argument may be a path scoped under one of the configured source roots.

`$ARGUMENTS`

## Step 1: Preconditions

Same as `/code-wiki:build`:

1. `wiki/config.yaml` must exist (else suggest `/code-wiki:init`).
2. The project must be a git repo (capture HEAD SHA).

If `$ARGUMENTS` is empty: this is a **full rebuild** — equivalent to `/code-wiki:build --force`. Skip the path-validation step and proceed.

If `$ARGUMENTS` contains a path: this is a **scoped rebuild**. The path must be relative to the project root and must lie inside one of the configured source roots; the next step (walk-tree) validates this and surfaces a clear error if it doesn't.

## Step 2: Compute the work list

Run walk-tree with optional scoping:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/walk-tree.py" \
    --project-root "$(pwd)" \
    ${SCOPE:+--scope-path "$SCOPE"} \
  > /tmp/code-wiki-worklist.json
```

Where `$SCOPE` is the path argument if provided, empty otherwise.

The output is the same JSON array as `/code-wiki:build` produces, optionally narrowed:
- **No arg**: every folder under every source root, bottom-up.
- **With arg**: the scoped sub-tree's folders (leaves and parents), plus the ancestor chain of the scope up to the source root, bottom-up.

If walk-tree errors with "not inside any configured source root", surface verbatim.

## Step 3: Build the dispatch plan

Pipe the work list into `orchestrate.py` to get a wave-grouped, per-page plan
with pre-rendered Skill args:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/orchestrate.py" \
    --project-root "$(pwd)" \
    --operation rebuild \
    --concurrency 10 \
    --worklist /tmp/code-wiki-worklist.json \
  > /tmp/code-wiki-plan.json
```

Note: do **not** pass `--skip-existing` here. Rebuild's whole purpose is to
overwrite existing pages.

If `orchestrate.py` exits non-zero (cycle, malformed work list, missing config),
surface its stderr verbatim and abort.

## Step 4: Execute the plan — per-page agents, one batch at a time

Same shape as `/code-wiki:build` Step 3:

- **One agent per Skill call.** Never hand-loop `Skill` from this command —
  the agent that loops is empirically flaky after the first Skill return.
- **Iterate `waves` in order.** Wave N waits for wave N-1 to finish.
- **Within a wave, iterate `batches` in order.** Each batch's items dispatch
  in parallel; the next batch starts only after every agent in the current
  batch has reported back (`<task-notification>` per agent). Batches are
  pre-split by `concurrency`; you don't need to compute the split.

For each wave → each batch → each item, dispatch a background `Agent` whose prompt is:

```
Generate exactly one wiki page. Invoke the `<item.skill>` skill ONCE with these
args, then verify the output and report.

```
Skill(skill="<item.skill>", args="<item.args_json>")
```

After the skill returns, verify `<project_root>/<item.wiki_path>` exists
non-empty. Output as your final message:

```json
{"wiki_path": "<item.wiki_path>", "ok": true|false, "reason": "..."}
```

Do not commit. Do not modify `wiki/CLAUDE.md` or `wiki/config.yaml`.
```

`<item.args_json>` from the plan is already valid JSON; only escape its
inner `"` as `\"` when interpolating into the Skill call. The Skill writes the
target wiki path unconditionally — that's the rebuild semantics.

When all agents in a batch return, verify each `wiki_path` on disk before
moving to the next batch. Treat `ok: false` *or* missing-on-disk as a generation
failure for that item (log it, continue the rebuild).

## Step 5: Cleanup deletions (full rebuild only)

For full rebuild, also clean up wiki pages that no longer correspond to any
current source folder. After all agents finish, compare:

- The set of `wiki_path` values produced by walk-tree.
- The set of existing wiki page files under each source root's wiki sub-directory.

Any wiki file that exists on disk but is NOT in the walk-tree output corresponds
to a folder that has been removed. Add these to a `deletions` list and
`rm -f` them, then prune now-empty parent directories up to (but not including)
`wiki/` itself.

For scoped rebuild, **do not** perform this cleanup — the scope may not cover
the whole tree.

## Step 6: Update state.json and log.md

Build the report from the work list captured in Step 2:

```json
{
  "operation": "rebuild",
  "ingested_sha": "<HEAD>",
  "pages": <contents of /tmp/code-wiki-worklist.json, possibly filtered to drop items whose wiki file was not actually written>,
  "deletions": <list from Step 5 cleanup, or [] for scoped rebuild>
}
```

```bash
echo '<json>' \
  | python3 "${CLAUDE_PLUGIN_ROOT}/bin/state-update.py" --project-root "$(pwd)"
```

For a scoped rebuild, state-update will preserve untouched pages' state entries unchanged — only the regenerated pages get new content_hash values and refreshed source_to_wiki entries.

## Step 7: Topic regeneration (scoped)

If a topic page's recorded `source_files` intersects the regenerated paths, surface a notice that the topic may now be stale and suggest the user run `/code-wiki:topic <name>` for affected topics. (Automatic topic regeneration during rebuild is deferred to v2.)

## Step 8: Report

```
Rebuilt wiki:
- scope:               <path or "(full)">
- pages regenerated:   <count>
- waves:               <W> (max parallel within a wave = <max wave size>)
- pages deleted:       <count>
- last_ingested_sha:   <sha>
```

## Failure modes

- Invalid scope (not inside any source root) → walk-tree surfaces the error; relay to user.
- `orchestrate.py` exit 2 (unresolved deps) → surface stderr and abort.
- Skill produces no file → log and continue (do not fail the whole rebuild).
- Agent never reports back → check disk; treat existing-non-empty as success, otherwise as failure.
- state-update fails → surface stderr; rebuild output may be inconsistent.

## When to use this vs. sync vs. build

- **`/code-wiki:build`**: first-time generation; aborts if `wiki/<source-root>/` already has content.
- **`/code-wiki:sync`**: incremental, git-diff based; the everyday command.
- **`/code-wiki:rebuild`**: ignore state, force regeneration. Use after schema/template changes, when wiki is structurally broken, or to refresh prose quality.
- **`/code-wiki:rebuild <path>`**: same, but only that subtree + ancestors. Useful for iterating on prose for a specific module without re-running the whole repo.
