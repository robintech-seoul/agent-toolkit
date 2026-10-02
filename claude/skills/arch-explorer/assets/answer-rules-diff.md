## This is a change map

The map in the browser is a change map: it shows what one branch changed
against a base, with boxes, arrows and interfaces marked `added`, `modified`
or `removed`, and a change card per block. Each question starts with a
`[change range]` block naming head, base, the merge-base and the after side,
and saying where to read the code before and after the change.

If this session built the map, the analysis you did then is your primary
source for the change. Otherwise the `[change range]` block says
`[build context] none`; then the change notes in `[map context]` and git take
its place, and you say the build's analysis is not available.

## Where each answer comes from

1. **What the branch changed** — anything marked in the map, a change card,
   "what changed", "why", "what did it do before": answer from the build's
   analysis first. When it does not cover the question, read only the hunks
   and files the question needs: `git diff <merge-base> <after> -- <path>`,
   and `git show <merge-base>:<path>` for the code before. Cite after-side
   lines for added or modified code (`src/a.py:42`), and merge-base-side lines
   for removed code, marked as removed (`src/a.py:42 (removed)`).
2. **Code the branch did not change** — lines the diff does not touch, even
   inside a file it changed: what an untouched module or function does, who
   calls it, how the changed code fits into the rest. **Go through the wiki,
   by the rules above, even when you remember that code from the build.** The
   build read untouched code only as far as explaining the change needed —
   often a hunk, a few lines, a subagent's summary or a box title — and what
   you remember of it may have been summarised since. So:
   - Every claim about unchanged code cites a wiki page you read in this
     conversation, or a source line you opened in this conversation because
     the wiki was silent (only a file a wiki page you read links to).
   - Never cite a line of unchanged code from memory of the build. A wiki
     page rarely gives line numbers; when the answer needs one, open the file
     the page links to now and cite what you read — or cite the wiki page
     alone.
   - The build's analysis may add only how the change relates to that code
     ("`list` is untouched; it now reads files `save` writes atomically"),
     marked as coming from the change.
   - If there is no wiki or it is silent and links nothing that answers it,
     say so rather than answer from the build's memory.
   The wiki describes the code at the merge-base or earlier, so it is the
   right source for "how it was" and for everything around the change.
3. **Both** — explain the existing behaviour from the wiki and the change
   from the build's analysis, and keep it clear which sentence rests on which.

The rule against reading widely holds for the change too: the analysis is
already done, so open only what the question asks for. Do not reread the
whole diff to answer one question about one block.

When the wiki and the change disagree, the change wins for code at head; say
that the wiki predates it.

Only `git show`, `git diff` and `git log` are available, read-only. Never try
to check out, stash or change anything.
