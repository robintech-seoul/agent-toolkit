---
name: verify
description: Fact-check a finished grounded opinion document. Hands only the document to the read-only `grounded:verifier` subagent (Sonnet, no conversation context), which extracts the factual claims the opinion rests on and confirms, refutes or marks each one unverifiable with cited evidence; then re-judges every refutation against the cited evidence on Fable and revises the document. Use after `/grounded:ask` when the discussion is done, or when asked to "verify the opinion", "fact-check this", "근거 확인해줘", "팩트체크".
argument-hint: "[<opinion.md path>]"
model: fable
---

# Grounded opinion — verify

Check the facts a finished opinion rests on, in a context that has never seen
the discussion, and fold the result back into the document. This runs once,
on the finished document; it is not part of writing it.

## 0. The model

This skill sets `model: fable` because step 4 — deciding whether a refutation
is right — is the author's judgement and belongs to the strongest model. The
switch is not visible from inside the turn; do not try to confirm it.

## 1. Find the document

```
/grounded:verify [<opinion.md path>]
```

In order: the path given; the `.grounded/` document this conversation has
been editing; the most recently modified `.grounded/*/opinion.md` under the
repository root. If none exists, say so and point at `/grounded:ask`. If the
choice is ambiguous, ask.

Read it. If its `## Log` shows edits after the last verification (or it has
never been verified), proceed. If it is already `status: verified` and
unchanged since, say so and ask whether to re-run.

## 2. Spawn the verifier with a fixed prompt

Use the Agent tool with `subagent_type: grounded:verifier`. The prompt is this
text with only the path filled in — **nothing else**:

```
Fact-check the document at <absolute path to opinion.md>. Extract the factual
claims it rests on and verify each one against primary evidence, following
your instructions.
```

Do not add the question, the conversation, your own view of which claims
matter, what you already checked, or anything that tells the verifier what to
trust or skip. The verifier's value comes from receiving the document alone.

If the document is long (roughly over 150 lines of body), split it: spawn one
verifier per range in a single message so they run in parallel, each with the
same prompt plus one sentence: `Extract claims only from lines <a>–<b>; read
the whole document for context.` Split at section boundaries.

Wait for the report(s). Do not verify claims yourself in the meantime; that
is the verifier's job and doing it here re-introduces your context.

## 3. Record the verdicts

Write `verdicts.md` next to `opinion.md`:

```markdown
---
verified: <YYYY-MM-DD HH:MM>
opinion_log_at: "<last line of opinion.md's ## Log at the time>"
---

# Verdicts

<the verifier report(s), verbatim; for a split run, one section per range>

# Author's re-judgement

<filled in step 4>
```

Copy the reports as they came. Do not reorder, trim or reword them.

## 4. Re-judge every refutation yourself

The verifier can be wrong too. For each **REFUTED** claim, and each
**UNVERIFIABLE** claim that carries the position (see the opinion's "Where it
could be wrong"):

1. Open the verifier's citation yourself — the file and line, the command,
   the URL. Do not decide from the note alone.
2. Decide:
   - **accepted** — the evidence contradicts the claim. Fix the document
     (step 5).
   - **rejected** — the evidence does not show what the verifier says, or the
     claim was misread. Write why, citing what you opened.
   - **needs the user** — the fact is outside what you can observe (a
     production system, a decision someone made, a number only they know).
3. For UNVERIFIABLE claims that matter: try to reach evidence the verifier
   could not. If you can, cite it; if you cannot, the claim stays flagged in
   the document.

Record each decision under `# Author's re-judgement` in `verdicts.md`:

```markdown
- C3 — accepted: <what changed in opinion.md>
- C7 — rejected: <why, with the citation you opened>
- C9 — needs the user: <what only they can confirm>
```

Never accept a refutation without opening its evidence, and never dismiss
one without opening it either.

## 5. Revise the document

Edit `opinion.md` in place:

- Correct the sentences whose claims were accepted as refuted. If a corrected
  fact changes the reasoning or the position, rewrite those sections — do not
  leave a position standing on a fact you just removed.
- Mark claims that remain UNVERIFIABLE where they appear, briefly:
  `(unverified: <why>)`.
- Set frontmatter `status: verified` and add to `## Log`:
  `- <date> verified — <n> confirmed, <n> refuted (<n> accepted), <n> unverifiable; see verdicts.md`

## 6. Report

Tell the user, in this order:

1. Whether the position survived, changed, or fell — one sentence, first.
2. The counts.
3. Each accepted refutation: the claim, what is actually the case, what
   changed in the document.
4. Each rejected refutation in one line, so they can overrule you.
5. Anything that needs their answer.
6. The paths of `opinion.md` and `verdicts.md`.
