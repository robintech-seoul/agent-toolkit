---
description: Generate the entire wiki from scratch (bottom-up) — runs once at the start of a project, or after a structural reset. For incremental updates, use `/code-wiki:sync`.
argument-hint: [--force]
allowed-tools: Bash(python3 *), Bash(git *), Bash(mkdir *), Read, Write, Skill, Agent
---

The user wants to build the wiki from scratch. The arguments may include `--force`.

`$ARGUMENTS`

## Step 1: Preconditions

Run these checks in order. Stop on the first failure with a clear message.

1. **Wiki initialized?** Verify `wiki/config.yaml` exists in the project root. If not, abort:
   > "wiki/config.yaml not found. Run `/code-wiki:init` first."

2. **Git repo?** Run `git rev-parse HEAD` and capture the SHA. If it fails (not a git repo, or no commits), abort:
   > "code-wiki requires a git repository with at least one commit. Initialize git and commit your source first."

3. **Wiki already populated?** Check whether any source root's subdirectory under `wiki/` already has content. The source roots come from `wiki/config.yaml`'s `source_roots:` list — for each, look at `wiki/<source_root_path>/`.
   - If any of these directories exists and contains files, **and** `$ARGUMENTS` does NOT contain `--force`, abort:
     > "wiki/<source-root>/ already has content. Re-run with `--force` to overwrite, or use `/code-wiki:sync` for incremental updates."
   - With `--force`, proceed (existing files will be overwritten file-by-file as we regenerate).

## Step 2: Build the dispatch plan

Pipe the bottom-up work list from `walk-tree.py` straight into `orchestrate.py`,
which groups items into topological waves and pre-renders Skill args for each
item:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/walk-tree.py" --project-root "$(pwd)" \
  > /tmp/code-wiki-worklist.json

python3 "${CLAUDE_PLUGIN_ROOT}/bin/orchestrate.py" \
    --project-root "$(pwd)" \
    --operation build \
    --concurrency 10 \
    --worklist /tmp/code-wiki-worklist.json \
  > /tmp/code-wiki-plan.json
```

The plan has shape:

```json
{
  "operation": "build",
  "wiki_language": "...",
  "language_hints": [...],
  "concurrency": 10,
  "totals": {"items": N, "waves": W, "batches": B, "leaves": L, "parents": P, "skipped_existing": 0},
  "waves": [
    {
      "wave": 1,
      "size": <int>,
      "batches": [
        {
          "batch": 1,
          "size": <int, ≤ concurrency>,
          "items": [
            {
              "skill": "code-wiki:generate-leaf-page",
              "wiki_path": "wiki/.../index.md",
              "args_json": "{...}"
            },
            ...
          ]
        },
        ... more batches in this wave ...
      ]
    },
    {"wave": 2, "size": ..., "batches": [...]},
    ...
  ]
}
```

`batches` are pre-split by `concurrency`: a wave of 126 items with
`concurrency=10` becomes 13 batches (12 of size 10 + 1 of size 6). You don't
need to compute batch boundaries — just iterate them.

If `totals.items` is `0`, abort:
> "No source folders to wikify. Check `source_roots` and `ignore_patterns` in wiki/config.yaml."

If `orchestrate.py` exits non-zero (cycle, malformed work list, missing config), surface its stderr verbatim and abort.

## Step 3: Execute the plan — per-page agents, one batch at a time

This step is **non-negotiable about its dispatch shape**, because the alternative
(one agent looping over many items invoking `Skill` repeatedly) is empirically
flaky: a non-trivial fraction of agents stop after the first `Skill` return and
treat it as task completion. To stay reliable:

- **One agent per Skill call.** Each work item is dispatched as a single
  background agent whose entire job is "invoke this one Skill, verify the
  output, report a one-line JSON result, exit."
- **Iterate `waves` in order.** Wave N may not start until wave N-1 has
  finished — a parent's children must exist on disk before the parent runs.
- **Within a wave, iterate `batches` in order.** All `items` in a batch are
  dispatched in parallel; the next batch starts only after every agent in the
  current batch has reported back (`<task-notification>` per agent). Batches
  inside a wave have no inter-dependency; they exist purely as a concurrency
  cap so you never fire more than `plan.concurrency` agents at once.
- **Do NOT hand-loop with `Skill` from this command.** Always go through `Agent`
  dispatch. This guarantees one Skill call per agent context.

For each wave → each batch → each item, dispatch one background `Agent` whose
prompt is exactly:

```
Generate exactly one wiki page. Invoke the `<item.skill>` skill ONCE
with these args, then verify the output and report.

```
Skill(skill="<item.skill>", args="<item.args_json>")
```

After the skill returns, verify `<project_root>/<item.wiki_path>` exists
with non-empty content.

Output as your final message:

```json
{"wiki_path": "<item.wiki_path>", "ok": true|false, "reason": "..."}
```

Do not commit. Do not modify `wiki/CLAUDE.md` or `wiki/config.yaml`.
```

Note that `<item.args_json>` from the plan is already a valid JSON string;
you only need to escape its inner `"` characters as `\"` when interpolating
into the Skill call inside the prompt.

When all agents in a batch have returned (one `<task-notification>` per agent),
verify on disk that each `wiki_path` exists with non-empty content. Treat any
agent's `ok: false` *or* missing-on-disk as a generation failure for that item
— log it, but continue the build (it's best-effort).

When the current batch is fully verified, advance to the next batch in the
same wave. When the wave's batches are exhausted, advance to the next wave.
Repeat until all waves are done. Total agents you will dispatch =
`plan.totals.items`; total batches = `plan.totals.batches`.

### Resume after partial failure

If the build is interrupted and you re-run `/code-wiki:build --force`, add
`--skip-existing` to the orchestrate.py call so already-built pages are dropped
from the plan:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/orchestrate.py" \
    --project-root "$(pwd)" \
    --operation build \
    --concurrency 10 \
    --skip-existing \
    --worklist /tmp/code-wiki-worklist.json \
  > /tmp/code-wiki-plan.json
```

The plan will include only the missing pages, still in their correct waves.

## Step 4: Update state.json and log.md

Once the plan is fully executed, build the state-update report from the work
list captured in Step 2 (state-update needs the raw work-item shape, not the
dispatch plan):

```json
{
  "operation": "build",
  "ingested_sha": "<HEAD SHA from Step 1>",
  "pages": <contents of /tmp/code-wiki-worklist.json, possibly filtered to drop items whose wiki file was not actually written>,
  "deletions": []
}
```

Pass it to state-update:

```bash
echo '<report json>' \
  | python3 "${CLAUDE_PLUGIN_ROOT}/bin/state-update.py" --project-root "$(pwd)"
```

The script:
- Computes content hashes for each generated wiki page.
- Computes source hashes for each referenced source file.
- Updates `source_to_wiki` and `source_hashes`.
- Sets `last_ingested_sha`.
- Appends a build entry to `.code-wiki/log.md`.

If `state-update.py` exits non-zero, surface its stderr to the user — state
has not been written and the wiki may be inconsistent.

## Step 5: Report

Print a concise summary:

```
Built wiki at <project_root>/wiki/
- pages generated: <N>
- waves:           <W> (max parallel within a wave = <max wave size>, concurrency cap = <plan.concurrency>)
- source roots:    <list>
- last_ingested_sha: <sha>
Run /code-wiki:lint to check the result, or /code-wiki:query <q> to use it.
```

## Failure modes

- A skill invocation produces an empty or malformed page → note in summary, do not fail the whole build. The user can re-run with `/code-wiki:rebuild <path>` later.
- An agent never reports back → check disk; if the wiki file exists with non-empty content, count it as success; otherwise as failure.
- `walk-tree.py` errors → surface stderr verbatim and abort.
- `orchestrate.py` exits 2 (unresolved deps — typically a cycle or external child wiki missing) → surface stderr and abort.
- `state-update.py` errors → surface stderr verbatim. State may be stale; suggest re-running build.

## What this command does NOT do

- Generate topic pages. Those are produced by `/code-wiki:topic` (explicit) or `/code-wiki:query` (lazy).
- Modify `wiki/CLAUDE.md` or `wiki/config.yaml`. Those are user-curated.
- Touch source files.
- Commit anything. `wiki/` and `.code-wiki/` are written but not staged or committed.
