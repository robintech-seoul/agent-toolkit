---
description: Run code-wiki's 10 lint rules against the current wiki and report findings. Pass --fix to apply conservative auto-fixes (removes phantom wikis only).
argument-hint: [--fix]
allowed-tools: Bash(python3 *), Read
---

The user wants to lint the wiki. Arguments:

`$ARGUMENTS`

## Step 1: Run the linter

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/lint.py" \
    --project-root "$(pwd)" \
    ${FIX:+--fix}
```

…where `$FIX=1` if `$ARGUMENTS` contains `--fix`, otherwise empty.

The script outputs a JSON array of findings on stdout. Capture it.

## Step 2: Pretty-print the findings

If the array is empty:
> "Wiki is clean — no lint findings."

Otherwise group by severity (`error` → `warning` → `info`) and print each group with its rule, path, and detail. Suggested format:

```
## Errors (<count>)

- [broken-link-wiki] wiki/src/index.md
  link to './nonexistent/index.md' — file does not exist

- [phantom-wiki] wiki/src/old/index.md
  corresponding source folder 'src/old' no longer exists or is fully ignored

## Warnings (<count>)

- [missing-wiki] src/new_module
  source folder has no wiki page at 'wiki/src/new_module/index.md'

## Info (<count>)

- [length-too-short] wiki/src/sparse/index.md
  only 12 lines; consider whether the folder warrants a wiki page
```

Sort findings within each group alphabetically by path.

## Step 3: Recommended next actions

After printing the findings, surface a short list of suggested follow-ups based on what was found:

- Errors with `broken-link-*` → "Fix the source/destination, or run `/code-wiki:rebuild <path>` to regenerate the page."
- Errors with `phantom-wiki` → "Run `/code-wiki:lint --fix` to remove these, or `/code-wiki:rebuild` to refresh the structural mapping."
- Warnings with `missing-wiki` → "Run `/code-wiki:sync` (preferred) or `/code-wiki:build` to fill in the missing pages."
- Warnings with `stale-wiki` → "Run `/code-wiki:sync` to regenerate the affected pages."
- Warnings with `topic-source-drift` → "Run `/code-wiki:topic <name>` for each affected topic to refresh."
- Info findings → no action required; cosmetic / advisory only.

If `--fix` was passed and the findings include `(auto-fixed: ...)` annotations, mention those explicitly:
> "Auto-fixed: removed N phantom wiki pages and updated state.json."

## Failure modes

- `bin/lint.py` exits non-zero (rare) → surface stderr and exit.
- Output is not JSON → likely a bug; surface raw stdout and ask the user to file an issue.

## What this command does NOT do

- Modify wiki pages, except phantom removal under `--fix`.
- Auto-regenerate pages. Use `/code-wiki:sync` or `/code-wiki:rebuild` for that.
- Run git operations.
