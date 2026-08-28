# Wiki Style Guide

This file is loaded by Claude Code whenever it operates inside `wiki/`. It defines the conventions for generating and maintaining the wiki. The plugin never edits this file — only the user does.

## Page length norms

- **Leaf pages**: typically 50–300 lines. A 20-line page is too sparse; a 3000+ line page is too coarse and probably needs per-file pages.
- **Parent pages**: typically 50–200 lines. The synthesis should be tight; if it bloats, the structure of the underlying children may need rethinking.
- **Per-file pages**: 30–150 lines, focused on the file's public surface and key internals.
- **Topic pages**: 80–300 lines, with a substantive Flow section that traces actual execution.

## Tone and voice

- **Factual, not opinionated.** Describe what the code does, not whether it is good code.
- **Concrete, not vague.** Prefer specific function/type names over phrases like "various utilities" or "helper functions".
- **Cite sources.** Every claim about behavior should be traceable to a wiki page or source file via a markdown link.
- **No filler.** If a section has nothing to say, omit it. Empty "Notes" sections are noise.

## Linking rules

- **Prefer wiki-to-wiki links** when the target information lives in another wiki page. This is what gives the wiki its compounding value — readers navigate by topic, not by file system.
- **Use wiki-to-source links** for specifics: a function's exact signature, a constant's value, an algorithm not fully captured in prose.
- **Use standard markdown relative paths.** From `wiki/<source-root-path>/<sub>/index.md`, a link to `<source-root>/<path>/<file>` is computed by counting `../` to `wiki/`'s parent and walking down to the source file. The plugin's `bin/lib/wiki_path.py` does this consistently — generated content should match its output.

## Structure preservation

- The plugin regenerates wiki pages freely. **Do not hand-edit auto-generated pages** — your changes will be overwritten.
- The two files in `wiki/` that the plugin never touches after `init` are this file (`CLAUDE.md`) and `config.yaml`. Customize style and configuration here.

## Topic page criteria

A topic page should be created (via `/code-wiki:topic <name>` or accepted from a `/code-wiki:query` answer) when:
- The concern spans **≥3 leaf wiki pages from ≥2 sub-trees** of the source tree.
- The concern has a clear **Flow** — entry points, control flow, side effects — that a reader needs to follow end-to-end.
- The information is **reusable** across multiple future questions.

Avoid topic pages for narrow, single-folder concerns (covered by the corresponding leaf wiki) or for one-off observations.

## Open questions, not guesses

When generation surfaces ambiguity (a function's behavior depends on an unread config; control flow has a branch you can't fully resolve from the code), record it in the page's "Notes" or "Open Questions" section rather than guessing. Future regeneration runs can refine these as understanding improves.
