---
description: Bootstrap code-wiki in the current project — creates wiki/ scaffolding, config.yaml, CLAUDE.md, and .gitignore entry.
argument-hint: [no arguments — interactive]
allowed-tools: Bash(python3 *), Read, Write
---

The user wants to initialize code-wiki in the current project (working directory).

## Step 1: Verify the working directory is the project root

The current working directory should be the user's project root — the directory you want the wiki built over. Confirm with the user:

> "I'll initialize code-wiki at: `<current working directory>`. This will create `wiki/` and `.code-wiki/` here. OK to proceed? (yes / no)"

If they decline, stop here.

## Step 2: Ask for source roots

> "Which directories contain source code? Enter comma-separated paths relative to the project root (e.g. `src` or `apps/web/src, packages/lib`)."

Validate the user's response:
- Reject empty input.
- Reject `.` as a source root (one cannot wikify the entire project; pick a sub-directory).
- Reject `wiki` and `.code-wiki` as source roots (reserved by code-wiki).
- The Python script will run final validation (existence as a directory, no nesting between roots) — surface its error message verbatim if validation fails.

## Step 3: Ask for wiki language

> "Wiki language? (default: `en`. Common values: `en`, `ko`, `ja`. Press enter to accept default.)"

If the user just presses enter or types nothing, use `en`.

## Step 4: Ask for optional language hints

> "Optional language/framework hints? Comma-separated. Examples: `typescript, react` or `django, python`. Press enter to skip."

These are passed to the LLM during wiki generation to help it choose appropriate vocabulary. Empty is fine.

## Step 5: Run the bootstrap script

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/init.py" \
    --project-root "$(pwd)" \
    --source-roots "<comma-separated source roots>" \
    --language "<language>" \
    --language-hints "<comma-separated hints, or empty>"
```

The script will:
- Abort if `wiki/` already exists.
- Validate source roots (existence, no nesting, reserved-name rules).
- Create `wiki/CLAUDE.md` (style guide; user-editable).
- Create `wiki/config.yaml` (populated with the user's answers).
- Create empty `.code-wiki/`.
- Append `.code-wiki/` to `.gitignore` (idempotent).

## Step 6: Report

On success, the script prints next-step guidance — relay it to the user verbatim. The expected next step is `/code-wiki:build`.

On error:
- "wiki/ already exists" → suggest the user remove it manually and re-run init.
- Source-root validation error → surface the script's message and ask the user for corrected input. Do not retry automatically.
- "plugin template missing" → the plugin install is incomplete; the user should reinstall.

Do not modify any files yourself; the Python script is the only writer. Your job here is to collect input, run the script, and report the outcome.
