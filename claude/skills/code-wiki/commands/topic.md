---
description: Explicitly create or refresh a topic page that traces a cross-cutting concern (auth, logging, payment flow, etc.) end-to-end across the codebase.
argument-hint: <topic-name> [--description "..."]
allowed-tools: Bash(python3 *), Read, Write, Skill
---

The user wants to create a topic page. Arguments:

`$ARGUMENTS`

The first non-flag token is the topic name (kebab-case). An optional `--description "..."` provides a 1-line description; if absent, infer from the topic name or ask the user.

## Step 1: Preconditions

1. **Wiki initialized?** Verify `wiki/config.yaml` exists. If not:
   > "wiki/config.yaml not found. Run `/code-wiki:init` and `/code-wiki:build` first."

2. **Wiki has content?** Verify at least one `wiki/<source-root>/index.md` exists. If `wiki/` is otherwise empty:
   > "Wiki has no generated pages. Run `/code-wiki:build` first."

3. **Topic name format**: must be lowercase kebab-case (`[a-z0-9-]+`). Reject otherwise with a hint:
   > "Topic names should be lowercase kebab-case, e.g. 'auth-flow' or 'request-pipeline'."

## Step 2: Check for existing topic page

If `wiki/topics/<name>.md` already exists, ask:
> "`wiki/topics/<name>.md` already exists. Overwrite? (yes / no)"

If declined, stop. Suggest the user pick a different name or run `/code-wiki:rebuild wiki/topics/<name>.md` (note: rebuild's path scoping doesn't currently apply to topic pages — for v1, the user can simply delete the file and re-run topic).

## Step 3: Read configuration

Read `wiki/config.yaml` for `wiki_language` and `language_hints`.

## Step 4: Invoke the topic skill

```
Skill(skill="code-wiki:generate-topic-page", args="""
  {
    "topic_name":    "<name>",
    "description":   "<from --description, or empty>",
    "wiki_language": "<from config>",
    "language_hints": [<from config>]
  }
""")
```

The skill (in Shape A — explicit invocation) will:
1. Discover relevant wikis by scanning all `wiki/<source-root>/**/index.md` for matches against the topic name.
2. Read those wikis and follow their source links.
3. Read concrete source files to reconstruct the actual end-to-end flow.
4. Produce `wiki/topics/<name>.md` matching `templates/page-topic.md`, with a substantive **Flow** section.
5. Return a JSON summary identifying the source files and wiki pages it incorporated.

If the skill aborts ("no wiki pages reference this topic" or similar), surface its message and stop. Suggest one of:
- The user generates the wiki first if they haven't.
- The user picks a name that actually appears in the codebase.

If the skill warns ("topic appears in only one location"), relay the warning and proceed only if the user explicitly confirms. A topic page over a single-location concern is usually wasted effort.

## Step 5: Update state.json

The skill returns a JSON summary like:
```json
{
  "topic_name": "auth",
  "wiki_path":  "wiki/topics/auth.md",
  "source_files": ["src/api/auth/auth.ts", "packages/lib/auth.ts"],
  "referenced_wikis": ["wiki/src/api/auth/index.md", "wiki/packages/lib/index.md"]
}
```

Build a state-update report:

```json
{
  "operation": "topic",
  "pages": [
    {
      "wiki_path":         "<from skill output>",
      "kind":              "topic",
      "source_files":      <from skill output>,
      "child_wikis":       [],
      "referenced_wikis":  <from skill output>
    }
  ]
}
```

```bash
echo '<json>' | python3 "${CLAUDE_PLUGIN_ROOT}/bin/state-update.py" --project-root "$(pwd)"
```

This registers the topic in state. After this, `/code-wiki:sync` will detect when any of the recorded `source_files` changes and surface the topic in `dirty_topics` for refresh.

## Step 6: Report

```
Created topic: wiki/topics/<name>.md
- key components:    <count>
- source touchpoints: <count>

Run /code-wiki:sync after changing any of the touched source files; the topic will be flagged as dirty.
```

## Failure modes

- Skill cannot find relevant wikis → relay verbatim, suggest building or different name.
- File system permission errors → relay; user fixes.
- state-update fails → topic is on disk but not tracked. Suggest re-running `/code-wiki:lint --fix` or manually re-running this command after the issue is resolved.

## What this command does NOT do

- Auto-detect topics. Topic creation is user-driven (or query-suggested).
- Auto-update topic pages on every source change. Sync flags them as dirty; the user re-runs this command.
- Modify wiki/CLAUDE.md or wiki/config.yaml.
- Touch source files.
