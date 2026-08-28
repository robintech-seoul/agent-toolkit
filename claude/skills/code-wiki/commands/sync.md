---
description: Incrementally update the wiki to reflect source changes since the last ingest. Diffs git from `last_ingested_sha` to HEAD and regenerates only affected pages plus their ancestors.
argument-hint: (no arguments)
allowed-tools: Bash(python3 *), Bash(git *), Bash(rm *), Bash(rmdir *), Bash(mkdir *), Read, Write, Skill, Agent
---

The user wants to sync the wiki with current source. No arguments.

## Step 1: Preconditions

1. **Git repo?** Run `git rev-parse HEAD`. If it fails, abort:
   > "code-wiki:sync requires a git repository. (For non-git workflows, use `/code-wiki:rebuild`.)"

2. **Wiki initialized?** Verify `wiki/config.yaml` exists. If not:
   > "wiki/config.yaml not found. Run `/code-wiki:init` first."

3. **State present?** Check `.code-wiki/state.json`.
   - If missing, run **soft-bootstrap** first:
     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/bin/state-bootstrap.py" --project-root "$(pwd)"
     ```
     - If it succeeds (typical path: a fresh clone with committed `wiki/`), continue.
     - If it errors with "wiki/ has not been committed", surface the message and abort (suggest `/code-wiki:build` instead).

## Step 2: Compute dirty work-set

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/scan-changes.py" --project-root "$(pwd)" \
  > /tmp/code-wiki-scan.json
```

The output JSON has shape:

```json
{
  "from_sha": "...",
  "to_sha":   "...",
  "pages":      [<work items, leaf or parent, in bottom-up order — same shape as walk-tree>],
  "deletions":  ["wiki/src/old/index.md", ...],
  "dirty_topics": ["wiki/topics/auth.md", ...]
}
```

If `pages`, `deletions`, and `dirty_topics` are all empty, report:
> "Wiki is up to date. (No source changes between `<from_sha>` and `<to_sha>`.)"
…and exit. Do not call state-update for a no-op.

## Step 3: Apply deletions

For each path in `scan_output.deletions`, delete the file and any now-empty parent directory under `wiki/`:

```bash
rm -f "<wiki_path>"
# After rm, prune empty ancestors up to (but not including) wiki/ itself.
```

Do not delete topic pages here — those are tracked separately in `dirty_topics`.

## Step 4: Build the dispatch plan

Extract the `pages` array from the scan output and feed it to `orchestrate.py`,
which groups items into topological waves and pre-renders Skill args:

```bash
python3 -c "import json,sys; json.dump(json.load(sys.stdin)['pages'], sys.stdout)" \
    < /tmp/code-wiki-scan.json \
  | python3 "${CLAUDE_PLUGIN_ROOT}/bin/orchestrate.py" \
      --project-root "$(pwd)" \
      --operation sync \
      --concurrency 10 \
  > /tmp/code-wiki-plan.json
```

If `pages` was empty (only deletions / dirty_topics), skip Step 5 entirely.

## Step 5: Execute the plan — per-page agents, one batch at a time

Same shape as `/code-wiki:build` Step 3. Briefly:

- **One agent per Skill call** — never hand-loop with `Skill` in this command.
  A non-trivial fraction of agents stop after the first `Skill` return; per-page
  dispatch sidesteps that failure mode.
- **Iterate `waves` in order** — wave N waits for wave N-1 (parent depends on
  child wikis being on disk).
- **Within a wave, iterate `batches` in order** — each batch's items are
  dispatched in parallel; wait for every agent in the batch (`<task-notification>`
  per agent) before starting the next batch. Batches are pre-split by
  `concurrency`; you never need to compute the split yourself.

For each wave → each batch → each item, dispatch a background `Agent` with the prompt:

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

When all agents in a batch return, verify each `wiki_path` on disk before moving
to the next batch. Treat any agent's `ok: false` *or* missing-on-disk as a
generation failure (log it, continue the sync).

`<item.args_json>` from the plan is already valid JSON; only its inner `"`
characters need escaping as `\"` when you interpolate into the Skill call.

## Step 6: Handle dirty topics

If `scan_output.dirty_topics` is non-empty, surface them to the user:

> "These topic pages reference sources that changed and may be stale: `<list>`. Run `/code-wiki:topic <name>` to regenerate each. (Automatic topic regeneration is a v2 feature.)"

Do not regenerate topic pages in v1 sync — that's deferred to T19's `/code-wiki:topic` command. Do still record them in the state-update report so users see them in the log.

## Step 7: Update state.json and log.md

Build the report from the scan output:

```json
{
  "operation": "sync",
  "ingested_sha": "<scan_output.to_sha>",
  "pages": <scan_output.pages, filtered to those whose wiki file actually exists post-skill>,
  "deletions": <scan_output.deletions>
}
```

```bash
echo '<report json>' \
  | python3 "${CLAUDE_PLUGIN_ROOT}/bin/state-update.py" --project-root "$(pwd)"
```

If state-update exits non-zero, surface stderr and warn the user that state may be inconsistent.

## Step 8: Report

```
Synced wiki: <from_sha> .. <to_sha>
- regenerated leaves:  <count>
- regenerated parents: <count>
- deleted pages:       <count>
- waves:               <W> (max parallel within a wave = <max wave size>)
- dirty topics needing manual regen: <list, or "none">
```

## Failure modes

- `state-bootstrap` errors → surface verbatim. If it's "wiki/ not committed", suggest build.
- `scan-changes` exit 2 (no last_ingested_sha) → suggest `/code-wiki:build`.
- `orchestrate.py` exit 2 (unresolved deps) → surface stderr and abort the regenerate phase; deletions and dirty-topic reporting can still proceed.
- Skill produces no file → record in summary, do not fail the sync.
- Agent never reports back → check disk; treat existing-non-empty as success, otherwise as failure.
- `state-update` errors → state may be stale; surface the error and recommend `/code-wiki:lint --fix` after the user fixes the underlying issue.

## What this command does NOT do

- Generate new topic pages (use `/code-wiki:topic`).
- Modify `wiki/CLAUDE.md` or `wiki/config.yaml`.
- Touch source files.
- Commit anything.
