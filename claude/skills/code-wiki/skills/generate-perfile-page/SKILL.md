---
name: generate-perfile-page
description: Generates a wiki page (Markdown) for a single source file when it is large or important enough to warrant its own page. Invoked from `generate-leaf-page` for files matching the leaf's per-file thresholds, or directly by build/sync/rebuild for known per-file pages.
---

# generate-perfile-page

Use this skill to produce one per-file wiki page at `wiki/<source-root>/<...>/<filename>.md` (note: same directory as the leaf's `index.md`, not a sub-directory).

## When to use

The leaf skill (`generate-leaf-page`) decides whether a file warrants a per-file page based on `config.yaml`'s `per_file_pages` thresholds:
- File LOC ≥ `min_loc` (default 800), OR
- The containing folder has more files than `max_files_per_folder` (default 20) AND this file is one of the central files chosen for spotlight.

When the leaf skill decides "yes," it invokes this skill once per qualifying file. Outside of leaf integration, sync and rebuild may also invoke this skill directly when a per-file page already exists in state and needs regeneration.

## Inputs (passed by the caller)

```
{
  "file_abs":           "/abs/path/to/source/file.py",
  "file_relpath":       "src/auth/login_handler.py",   // project-root-relative
  "target_wiki_relpath": "wiki/src/auth/login_handler.md",
  "wiki_language":      "en",
  "language_hints":     ["python"]
}
```

## Process

### Step 1: Read the file

Read the entire file at `file_abs`. Do not summarize from the filename.

### Step 2: Identify the public surface

What does this file expose? Functions, classes, exported constants, default exports, etc. List them with their signatures (or class shapes) and one-line descriptions.

### Step 3: Identify internals

Significant private functions, state, algorithms, control flow, side effects. This is the "how it works" section for readers who already understand the public surface and want to dig deeper.

### Step 4: Compute the source link

The link from the per-file page to the source file is short — both live near each other in the tree. Use `bin/lib/wiki_path.py:relative_link()`. The caller may supply a pre-computed value.

For a per-file page at `wiki/src/auth/login.md` linking to `src/auth/login.py`:
- Page dir: `wiki/src/auth/`
- Up 3 to project root, then `src/auth/login.py` → `../../../src/auth/login.py`.

### Step 5: Produce the page

Match the structure of `templates/page-perfile.md`:

```markdown
# <filename>

<Purpose: 1–3 sentences on what this file is responsible for.>

## Public surface

- `<function/class/export>` — <signature + one-line description>
- ...

## Internals

<Key logic, algorithms, state. Cross-link to related wikis (the leaf wiki for this folder, or sibling per-file pages, or topic pages) where useful.>

## Source

[`<filename>`](<computed relative link>)
```

The H1 is the filename including extension stripped (e.g. `login` for `login.py`). Use code-style backticks for the H1 if the filename matters as code (always, in practice).

### Step 6: Write the file

Use `Write` to create the page at `target_wiki_relpath`. The directory should already exist (the leaf wiki lives there); if not, create it.

## Output format requirements

- **Language**: match `wiki_language`.
- **Length**: 30–150 lines is the sweet spot. A per-file page longer than 250 lines suggests the file itself should be refactored — note this in the page's last paragraph if applicable.
- **Public surface section**: every exported symbol gets a bullet. Skip private symbols (those without `export` / underscore-prefixed in Python convention) unless they're load-bearing.
- **Internals section**: focus on what's not obvious from reading the public surface. If everything is obvious, the internals section can be a single line: "Implementation is straightforward; see source."

## Quality criteria

✓ **Concrete**: every claim cites a function name, class, or line range.
✓ **Honest about complexity**: if a function does many things, list them; don't pretend it's simple.
✓ **Cross-linked**: when this file uses something from another folder, link to that folder's wiki.

✗ Do not paraphrase docstrings verbatim — link to the source if the docstring is the documentation.
✗ Do not duplicate the leaf wiki's content. The per-file page is *deeper*, not *broader*.
✗ Do not invent design rationale you can't observe in the code.

## Failure modes

- File unreadable (binary, encoding errors) → produce a page that says so and stop ("`<file>` is binary; not analyzed by code-wiki"); the leaf page still references it.
- File is empty or trivial (e.g. just an `__init__.py` with one re-export) → produce a 5–10 line page; do not pad. The threshold logic in the leaf shouldn't have spawned a per-file page for this anyway, but be defensive.
