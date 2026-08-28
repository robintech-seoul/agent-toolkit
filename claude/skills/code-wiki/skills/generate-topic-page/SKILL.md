---
name: generate-topic-page
description: Generates a topic page (Markdown) capturing a cross-cutting concern — auth, logging, payment flow, etc. Combines wiki summaries with concrete source-file analysis to produce a narrative Flow section that traces actual end-to-end execution. Invoked by `/code-wiki:topic` (explicit) and `/code-wiki:query` (lazy creation when an answer crosses multiple sub-trees).
---

# generate-topic-page

Use this skill to produce one topic page at `wiki/topics/<name>.md`. A topic page captures a cross-cutting concern: a behavior that lives in multiple folders and benefits from a single, coherent narrative trace.

## When to use

- Explicit `/code-wiki:topic <name>` invocation.
- Lazy creation triggered by `/code-wiki:query` when an answer cited ≥3 leaf wikis from ≥2 sub-trees.
- Sync regenerating a topic page whose recorded sources have changed (v2; v1 surfaces them as warnings only).

A topic page exists *because* the underlying concern has scattered source touchpoints. If the concern lives entirely in one folder, that folder's leaf wiki is the right home — do not create a topic page.

## Inputs (passed by the caller)

The caller provides one of these shapes:

### Shape A — explicit invocation (from `/code-wiki:topic`)

```
{
  "topic_name":   "auth",
  "description":  "Authentication and session-token validation",   // optional, 1 line
  "wiki_language": "en",
  "language_hints": [...]
}
```

In this shape, the skill must **discover** relevant wikis on its own by reading `wiki/<source-root>/**/index.md` and matching against the topic name.

### Shape B — lazy invocation (from `/code-wiki:query`)

```
{
  "topic_name":   "auth",
  "description":  "...",
  "seed_question": "How does authentication work in this codebase?",
  "seed_answer":   "<the prose answer the query produced, with citations>",
  "relevant_wikis": ["wiki/src/api/auth/index.md", "wiki/packages/lib/index.md", ...],
  "wiki_language": "...",
  "language_hints": [...]
}
```

In this shape, the seed answer + the cited wikis are pre-supplied. The skill's job is to upgrade them into a full topic page (especially adding the **Flow** section).

If neither shape's required fields are present, abort with a clear error.

## Process

### Step 1: Confirm the topic is worth a page

If invoked from query (Shape B), this was already verified — proceed.

If invoked explicitly (Shape A), search the wiki for relevant content:
- For each `wiki/<source-root>/**/index.md`, read the page and search for occurrences of the topic name (and obvious synonyms — for "auth", also look for "authenticate", "login", "session", "token", "credential").
- Collect the matching wiki pages as `relevant_wikis`.
- If `relevant_wikis` is empty, abort:
  > "No wiki pages reference '<topic>'. Generate the wiki first (/code-wiki:build) or pick a different topic name."
- If `relevant_wikis` has only one entry under a single sub-tree, warn:
  > "'<topic>' appears in only one location. Topic pages are most useful for cross-cutting concerns; consider using the existing leaf wiki at <path> instead."
  …but proceed if the user is explicit.

### Step 2: Read the relevant wikis

Read every `relevant_wikis` page in full. Collect:
- The source files each wiki cites (parse outbound `source` links).
- The wiki-to-wiki cross-links between them (parse outbound `wiki` links).

These give you the **Source Touchpoints** and **Key Components** sections respectively.

### Step 3: Read the source files (the Flow analysis)

This is what makes a topic page valuable beyond what the wiki alone offers. For each source file from Step 2:

1. Open the file and read its actual code.
2. Identify entry points (exported functions, request handlers, public API).
3. Trace control flow: what calls what, in what order, with what side effects.
4. Identify the data flow: what flows in, what's transformed, what flows out.

Compose a **narrative trace** that follows execution from entry to side effect. Example shape (for an auth topic):

> "A login request enters at `apps/api/src/routes/auth.ts` (the `POST /login` handler), which validates the request body and calls `signToken(claims)` from `packages/lib/auth.ts:14`. `signToken` serializes the claims with an expiration, hashes them via `naiveHash`, and returns the concatenated token. On the client, the token is stored and resent in the `Authorization: Bearer …` header for subsequent requests. Validation occurs at `validateToken(token)` (`packages/lib/auth.ts:30`), which decodes the base64 payload, recomputes the hash, and rejects if hashes mismatch or `exp` has passed."

This is what a human reader needs to navigate the topic — not a link list, but a *trace*.

If you encounter behavior you cannot fully resolve from the source you've read (e.g. control flow depends on an external service or runtime config you don't see), record it in the **Open Questions** section rather than guessing.

### Step 4: Identify Patterns & Conventions

While reading the source, note:
- Recurring code shapes (e.g. "every route handler returns `{ status, body }`").
- Shared assumptions (e.g. "all tokens are validated at the route level, never deeper").
- Notable design decisions (e.g. "validation logic lives in the lib, not the routes").
- Known gotchas (e.g. "the SECRET is hard-coded for the fixture; not safe for production").

These go in the **Patterns & Conventions** section.

### Step 5: Produce the page

Match the structure of `templates/page-topic.md`:

```markdown
# <topic_name>

<2–4 line overview: what the topic is and where it lives.>

## Key Components

- [<wiki page>](<relative path from wiki/topics/ to wiki page>) — <role in this topic>
- ...

## Source Touchpoints

- [`<file>`](<relative path from wiki/topics/ to source file>) — <where the topic's logic appears, ideally with line ranges>
- ...

## Flow

<Step 3's narrative trace, end-to-end.>

## Patterns & Conventions

<Step 4's observations.>

## Open Questions

<Anything you couldn't resolve from the source. Use bullet points; mark each as "Unknown:" or "Likely:".>
```

### Step 6: Compute relative paths

The page lives at `wiki/topics/<name>.md`. From there:
- A wiki link to `wiki/src/api/auth/index.md` is `../src/api/auth/index.md` (up 1 to `wiki/`, then descend).
- A source link to `src/api/auth/auth.ts` is `../../src/api/auth/auth.ts` (up 2 to project root, then descend).

Use `bin/lib/wiki_path.py:relative_link()` to compute these correctly. The caller may have pre-computed them — if so, use those values verbatim.

### Step 7: Write the file

Use `Write` to create `wiki/topics/<name>.md`. Create the `wiki/topics/` directory if it doesn't exist.

### Step 8: Return a structured summary to the caller

When you finish, output (as the skill's return value or a final assistant message):

```json
{
  "topic_name": "auth",
  "wiki_path":  "wiki/topics/auth.md",
  "source_files": ["src/api/auth/auth.ts", "packages/lib/auth.ts", ...],
  "referenced_wikis": ["wiki/src/api/auth/index.md", "wiki/packages/lib/index.md", ...]
}
```

The caller (query.md or topic.md) uses this to update state.json so sync can keep the topic page current when its sources change.

## Output format requirements

- **Language**: match `wiki_language`.
- **Length**: 80–300 lines. Topic pages are denser than leaf pages — they consolidate information that's spread across many sources.
- **Flow section is mandatory**: a topic page without a real Flow section is just a glorified link list and doesn't earn its keep. If you cannot produce a meaningful Flow (because the topic doesn't actually have a discernible execution flow), consider whether this should be a topic page at all.
- **Citations always**: every claim in Flow / Patterns / Open Questions cites a wiki page or source file.

## Quality criteria

✓ **Trace-able**: a reader can follow Flow line by line and find every step in real source.
✓ **Honest**: ambiguities are in Open Questions, not papered over.
✓ **Scoped**: focuses on the topic's actual cross-cutting nature; doesn't drift into unrelated concerns.
✓ **Hand-offs**: when the topic crosses a folder boundary (the whole point of a topic page), the prose explicitly names the boundary ("the HTTP layer in `apps/api` calls into the lib in `packages/lib`").

✗ Do not just bullet-list every wiki + every source file. The Flow section is the differentiator.
✗ Do not invent control flow you didn't observe in source.
✗ Do not duplicate content from leaf wikis verbatim — the topic page should add a *cross-cutting view*, not restate per-folder content.

## Failure modes — surface, don't paper over

- Source file unreadable (permissions, encoding) → record in Open Questions, continue.
- Source file references in a wiki point to nonexistent files → record in Open Questions, do not break.
- Topic genuinely has no flow (purely structural concern, e.g. "naming conventions") → produce a page without a Flow section; note this in the Overview as "this topic is structural rather than dynamic; see Patterns below."
- Caller-supplied `relevant_wikis` includes paths that don't exist → skip them, note in Open Questions.
