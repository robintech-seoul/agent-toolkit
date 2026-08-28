---
description: Answer a question using the wiki, with optional source drill-down. Cites sources. May propose a new topic page when the answer synthesizes multiple modules.
argument-hint: <question>
allowed-tools: Bash(python3 *), Read, Skill
---

The user has asked a question:

`$ARGUMENTS`

## Step 1: Preconditions

1. **Wiki initialized?** Verify `wiki/config.yaml` exists. If not:
   > "wiki/config.yaml not found. Run `/code-wiki:init` and `/code-wiki:build` first."

2. **Wiki has content?** Verify at least one file matching `wiki/<source-root>/index.md` exists. If `wiki/` is empty:
   > "Wiki has no generated pages. Run `/code-wiki:build` first."

## Step 2: Load style guidance

Read `wiki/CLAUDE.md`. It is the user's curated style guide for the wiki and influences how the answer should be phrased (especially `wiki_language`).

Read `wiki/config.yaml` to get `wiki_language`.

## Step 3: Traverse the wiki tree

Start from each source root's `index.md` (e.g. `wiki/src/index.md`, or for monorepos, every top-level configured source root). Read these high-level pages first to orient yourself, then descend into the children whose summaries appear most relevant to the user's question.

**Wiki-first**: rely on the wiki content alone whenever it answers the question. Many questions can be answered by reading 2–4 wiki pages.

**Source drill-down (only when needed)**: if the wiki content is insufficient (e.g. you need a function's exact signature, a constant's value, or precise control flow not captured in prose), open the **specific** source files cited by the relevant wiki pages. **Never enumerate the source tree directly** — every source read must be reachable from a wiki page you've already opened. If you find yourself wanting to grep for a name across the codebase, you've gone off-script: stop and answer based on what the wiki tells you, with explicit acknowledgement of any uncertainty.

The instruction is verifiable: a reviewer can inspect which files you opened and confirm each source read had a wiki link to it.

## Step 4: Synthesize the answer

Produce an answer that:

- Is in the language matching `wiki_language`.
- Cites every claim with a markdown link to the wiki page or source file used. Use the path as it appears on disk (project-root-relative is fine; readers can navigate from anywhere).
- Acknowledges uncertainty explicitly where the wiki is silent. Do not guess.
- Stays scoped to the question. A 1-line answer is fine; do not pad.

## Step 5: Topic candidate detection

After producing the answer, check whether it qualifies as a candidate for a topic page. The criteria (all four must hold):

1. The answer cites **≥3 distinct leaf wiki pages**.
2. The cited pages span **≥2 different sub-trees** (i.e. they are NOT all under the same direct parent — the topic is genuinely cross-cutting).
3. The question is **substantive** — the answer would be more than a single sentence.
4. **No existing topic page already covers this scope.** Check this by reading every file in `wiki/topics/` (if any): for each, read the title (`# <topic>`) and the first ~200 characters. If any visibly overlaps the user's question's scope, do NOT prompt for topic creation.

If all four hold, prompt the user:

> "This answer synthesizes [N] wiki pages across [M] modules. File as `wiki/topics/<suggested-name>.md` so future queries can reuse it? (yes / no)"

Suggest a kebab-case name derived from the question's core noun phrase ("How does authentication work?" → `authentication`).

If the user declines, just deliver the answer and stop. No topic page is created. No state update.

## Step 6: Lazy topic creation (if user accepts)

Invoke the topic skill with the synthesized answer + citations:

```
Skill(skill="code-wiki:generate-topic-page", args="""
  {
    "topic_name":     "<kebab-case name>",
    "description":    "<derived from the user's question, 1 line>",
    "seed_question":  "<original question>",
    "seed_answer":    "<your synthesized answer, citations included>",
    "relevant_wikis": [<wiki paths cited in your answer>],
    "wiki_language":  "<from config>",
    "language_hints": [<from config>]
  }
""")
```

The skill writes `wiki/topics/<name>.md` and produces a JSON summary of source/wiki references it discovered while writing the page.

## Step 7: Update state.json (only if topic was created)

Build a state-update report:

```json
{
  "operation": "query-topic",
  "pages": [
    {
      "wiki_path": "wiki/topics/<name>.md",
      "kind": "topic",
      "source_files": <list returned by topic skill>,
      "child_wikis": [],
      "referenced_wikis": <list returned by topic skill>
    }
  ]
}
```

```bash
echo '<json>' | python3 "${CLAUDE_PLUGIN_ROOT}/bin/state-update.py" --project-root "$(pwd)"
```

This registers the topic in state so future `/code-wiki:sync` runs can detect when its sources change.

## Step 8: Report

Deliver:

1. **The answer**, with all citations.
2. **A short footer** indicating which wiki pages were consulted (so the reader can navigate further).
3. **If a topic was created**, a one-line confirmation: "Filed at `wiki/topics/<name>.md`."

## What this command does NOT do

- Run `git` operations or modify state unless a topic page was created.
- Read source files that aren't referenced by an opened wiki page.
- Re-generate existing wiki pages.
- Edit `wiki/CLAUDE.md` or `wiki/config.yaml`.
