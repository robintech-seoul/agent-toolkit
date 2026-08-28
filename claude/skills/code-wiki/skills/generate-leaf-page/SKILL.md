---
name: generate-leaf-page
description: Generates a wiki page (Markdown) for a leaf source folder — i.e. a source folder with no surviving sub-directories after applying ignore patterns. Reads the folder's loose source files plus any non-code context (READMEs, configs) and produces a page matching `templates/page-leaf.md`. Invoked by `/code-wiki:build`, `/code-wiki:sync`, and `/code-wiki:rebuild`.
---

# generate-leaf-page

Use this skill to generate one leaf folder's wiki page. The caller (a code-wiki command) passes the folder details and the page's target path; you produce the page content and write it.

## When to use

Whenever a leaf folder needs a fresh wiki page — initial build, source change ripple, or forced regeneration. **Do not invoke this skill for parent folders** (use `generate-parent-page` instead).

A leaf folder is a folder whose `is_leaf` field from `bin/walk-tree.py` is true: it has at least one loose source file and no surviving child directories.

## Inputs (passed by the caller)

The caller provides these as a JSON-shaped argument:

```
{
  "folder_abs": "/abs/path/to/source-root/sub/leaf",
  "folder_relpath": "sub/leaf",                   // relative to project root
  "source_root": "src",                            // the configured source root this folder belongs to
  "loose_files": ["main.py", "helper.py"],        // basenames of non-ignored files in the folder
  "target_wiki_relpath": "wiki/src/sub/leaf/index.md",
  "wiki_language": "en",
  "language_hints": ["python"],
  "per_file_pages": {                              // optional; from config.yaml
    "enabled": true,
    "min_loc": 800,
    "max_files_per_folder": 20
  }
}
```

`per_file_pages` is optional. If absent, default to `enabled: true, min_loc: 800, max_files_per_folder: 20` per the spec.

If anything is missing or contradictory (e.g. `target_wiki_relpath` doesn't match `folder_relpath`), stop and ask the caller for clarification rather than guess.

## Process

### 1. Read all relevant files

Read every file in `loose_files`. Also read non-code context that informs understanding but does **not** get its own wiki page:

- `README.md`, `README.rst`, `README` — descriptive prose written by humans
- `*.toml`, `*.yaml`, `*.yml`, `*.json` if they are clearly config (e.g. `package.json`, `pyproject.toml`, app config files)
- `Makefile`, `Dockerfile`, `*.dockerfile`

For binary files or extremely large files (>50 KB), summarize from name/extension only and note in the page's "Notes" section if relevant.

### 2. Identify the folder's role

In one or two sentences, what is this folder responsible for? Avoid generic answers like "various utilities" — anchor the role to specific types, functions, or domain concepts you saw.

### 3. Compute source links

For each file you reference in the page, compute the relative markdown link from `target_wiki_relpath` to `<folder_relpath>/<filename>`. Use `bin/lib/wiki_path.py:relative_link()` (the caller may invoke this for you and provide pre-computed links; otherwise compute it correctly — see SPEC §3 for the formula).

### 4. Identify cross-references

Scan source files for imports or calls into other folders. If those targets exist in the wiki tree, link to their wiki pages (you don't have the full wiki tree at this point — use folder names from imports and trust that other wikis exist; broken links are caught by `/code-wiki:lint`).

### 4b. Decide which files (if any) get per-file pages

If `per_file_pages.enabled` is `false`, skip this step entirely.

Otherwise apply the threshold logic:

1. **Big-file rule**: any file whose line count is ≥ `per_file_pages.min_loc` (default 800) is a per-file candidate. Always spawn a per-file page for these.

2. **Crowded-folder rule**: if the folder has more than `per_file_pages.max_files_per_folder` (default 20) files, the leaf wiki cannot meaningfully detail every file in its "Files" section. In that case:
   - Pick the **most central** files for per-file pages — typically the ones with the largest public surface area (most exports / most sites that reference them) or that other files import from.
   - For the remaining files, list them as one-liners only in the "Files" section.
   - Use judgment: aim for ~5–10 per-file pages even in very large folders. Don't spawn 20 per-file pages just because the folder has 21 files.

For each per-file candidate, invoke `generate-perfile-page`:

```
Skill(skill="code-wiki:generate-perfile-page", args="""
  {
    "file_abs":           "<folder_abs>/<filename>",
    "file_relpath":       "<folder_relpath>/<filename>",
    "target_wiki_relpath": "<target_wiki_relpath's directory>/<filename without extension>.md",
    "wiki_language":      "<from inputs>",
    "language_hints":     [<from inputs>]
  }
""")
```

The per-file page lives **next to** `index.md` in the same wiki directory (e.g. `wiki/src/auth/index.md` + `wiki/src/auth/login.md`), not in a sub-directory.

### 5. Produce the page

Match the structure of `templates/page-leaf.md`:

```
# <folder name>

<2–4 line summary>

## Files

- [`<file>`](relative/path/to/source) — <one-line description>
- ...

## Concepts

<Domain concepts, types, key abstractions defined here. Skip if none.>

## Dependencies

<Significant imports/calls into other folders. Cross-link to other wikis where applicable.>

## Notes

<Gotchas, non-obvious patterns. Skip if none.>
```

The H1 title is the folder's basename (e.g. `auth` for `src/auth/`). Use a consistent code-style (`backticks`) for filenames in lists.

### 6. Write the file

Use the `Write` tool to write the produced markdown to `target_wiki_relpath`.

## Output format requirements

- **Language**: Match `wiki_language`. If `en`, write in English; if `ko`, write in Korean; etc. Section headings stay in the same language as the body for consistency.
- **Length**: 50–300 lines is typical. Substantially shorter than 20 lines means the folder probably wasn't worth wikifying; substantially longer than 500 means the per-file decision logic should have spawned more per-file pages — re-evaluate Step 4b.
- **Sections**: Omit empty sections. An empty "Notes" section is noise.
- **Files section**: Every loose source file (excluding non-code context like READMEs/configs) gets a one-line entry. Non-code context informs the prose but is not listed. **Files that got their own per-file page** are linked from the "Files" section to their per-file page (not directly to the source).

## Quality criteria

What makes a good leaf wiki page:

✓ **Specific**: "Validates JWT tokens via `validateToken` (auth.ts:32)" rather than "handles authentication"
✓ **Anchored**: Every claim cites a file or function
✓ **Honest about uncertainty**: If a function's behavior depends on context you can't see, say so in Notes
✓ **Synthesized**, not enumerated: The summary is more than a concatenation of file headers
✓ **Wiki-first linking**: When mentioning another module, link to its wiki page if one exists

What to avoid:

✗ Vague filler: "This module provides various utilities"
✗ Restating obvious code: "The `User` class has fields `id` and `name`"
✗ Adding sections from the template just because they're listed (skip empty ones)
✗ Speculation about untested behavior

## Examples

### Bad page (anti-pattern)

```markdown
# auth

This folder contains various authentication utilities.

## Files
- `login.py` — login functionality
- `logout.py` — logout functionality

## Concepts
There are several concepts in this folder including authentication and users.

## Dependencies
This folder depends on other folders.

## Notes
None.
```

Why bad: vague, redundant with the code, empty sections present, no concrete information.

### Good page

```markdown
# auth

Login and logout flows for the demo service. Both call into `users.models.User`
and use `utils.helpers.hash_password` to compare credentials.

## Files

- [`login.py`](../../../src/auth/login.py) — `login(username, password) -> User | None`. Hashes password, returns a `User` on match.
- [`logout.py`](../../../src/auth/logout.py) — `logout(user) -> None`. Currently just prints; placeholder for session teardown.

## Dependencies

- `users.models.User` — return type of login (see [users](../users/index.md))
- `utils.helpers.hash_password` — credential hashing (see [utils](../utils/index.md))

## Notes

`login` accepts any non-empty username/password — there is no real credential store yet. The `users.crud._STORE` is in-memory and lost on restart.
```

Why good: specific function signatures, wiki-to-wiki cross-links, honest note about placeholder behavior, no empty sections.

## Failure modes — surface, don't paper over

- Missing input (`folder_abs` doesn't exist, target dir not under `wiki/`) → abort and report to caller.
- File reads fail (permissions, missing) → emit a partial page and note the gap in "Notes" rather than crash.
- Unexpected file types (e.g. binary mixed with code) → list them by name with a "(binary, not analyzed)" note.
- A file's purpose is unclear from its content → say so in Notes ("`X.py` defines `Y` whose role is not obvious from this folder alone — likely consumed by the parent module"), don't invent a purpose.
