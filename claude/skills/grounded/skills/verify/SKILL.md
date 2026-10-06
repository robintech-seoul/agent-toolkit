---
name: verify
description: Fact-check a finished grounded opinion document in a loop of up to three rounds. Each round hands only the document to the read-only `grounded:verifier` subagent (Sonnet, no conversation context), which extracts the factual claims the opinion rests on and confirms, refutes or marks each one unverifiable with cited evidence; then Fable re-judges every refutation against the cited evidence and revises the document, and a fresh verifier checks the revision. Stops when nothing is refuted, when the document stops changing, or after three rounds. Use after `/grounded:ask` when the discussion is done, or when asked to "verify the opinion", "fact-check this", "근거 확인해줘", "팩트체크".
argument-hint: "[<opinion.md path>]"
model: fable
---

# Grounded opinion — verify

Check the facts a finished opinion rests on, in a context that has never seen
the discussion, fold the result back into the document, and check again until
a fresh verifier finds nothing to refute. This runs on the finished document;
it is not part of writing it.

This session is the orchestrator. There is no separate agent driving the
loop: you spawn the verifier, you judge its refutations, you revise, you
decide whether to go around again.

## 0. The model

This skill sets `model: fable` because step 5 — deciding whether a refutation
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

Then make a scratch directory **outside the repository** for this run:
`mktemp -d -t grounded-verify`. Round reports live there until the loop ends
(step 7). If a `verdicts.md` from an earlier run already sits next to
`opinion.md`, move it into the scratch directory now. Nothing a verifier can
reach may hold an earlier verdict: the next round's verifier searches the
repository, and a `verdicts.md` quoting the claims would hand it the previous
round's findings and your rejections.

## 2. The loop

At most **three rounds**. A round is steps 3 → 4 → 5 → 6. After each round,
stop when any of these holds, otherwise go around again:

| Stop when | Meaning |
|---|---|
| the verifier refuted nothing | the document's facts hold |
| the document did not change in this round | every refutation was rejected or handed to the user; another verifier would see the same text |
| three rounds are done | report what is still open |

Then finish with steps 7 and 8. A round that changed the document is always
followed by another round if one is left: the revision can bring in new
facts, and the only way to check them is a verifier that has not seen the
discussion.

Every round starts a **new** verifier. Never continue a previous one.

## 3. Spawn the verifier with a fixed prompt

Use the Agent tool with `subagent_type: grounded:verifier`. The prompt is this
text with only the path filled in — **nothing else**, and the same text in
every round:

```
Fact-check the document at <absolute path to opinion.md>. Extract the factual
claims it rests on and verify each one against primary evidence, following
your instructions.
```

Do not add the question, the conversation, the round number, earlier
verdicts, your own view of which claims matter, what you already checked, or
anything that tells the verifier what to trust or skip. The verifier's value
comes from receiving the document alone.

If the document is long (roughly over 150 lines of body), split it: spawn one
verifier per range in a single message so they run in parallel, each with the
same prompt plus one sentence: `Extract claims only from lines <a>–<b>; read
the whole document for context.` Split at section boundaries.

Wait for the report(s). Do not verify claims yourself in the meantime; that
is the verifier's job and doing it here re-introduces your context.

## 4. Record the verdicts

Write the reports to `<scratch>/verdicts.md` — not next to `opinion.md` yet.
Create it in round 1 and append a section per round:

```markdown
---
verified: <YYYY-MM-DD HH:MM>        # updated at the end
rounds: <n>                          # updated at the end
opinion_log_at: "<last line of opinion.md's ## Log when verification started>"
---

# Round 1

## Verdicts

<the verifier report(s), verbatim; for a split run, one subsection per range>

## Author's re-judgement

<filled in step 5>

# Round 2

…
```

Copy the reports as they came. Do not reorder, trim or reword them.

## 5. Re-judge every refutation yourself

The verifier can be wrong too. For each **REFUTED** claim, and each
**UNVERIFIABLE** claim that carries the position (see the opinion's "Where it
could be wrong"):

1. **Check whether it came up before.** If a refutation in an earlier round
   made the same point about the same claim and you rejected it, do **not**
   re-judge it. Two independent verifiers have now disagreed with you; that is
   a signal, not noise. Mark it **escalated** and hand it to the user in the
   report. Rejecting it twice would turn the loop into insisting.
2. Otherwise open the verifier's citation yourself — the file and line, the
   command, the URL. Do not decide from the note alone.
3. Decide:
   - **accepted** — the evidence contradicts the claim. Fix the document
     (step 6).
   - **rejected** — the evidence does not show what the verifier says, or the
     claim was misread. Write why, citing what you opened.
   - **needs the user** — the fact is outside what you can observe (a
     production system, a decision someone made, a number only they know).
4. For UNVERIFIABLE claims that matter: try to reach evidence the verifier
   could not. If you can, cite it and, if the document should say where the
   fact comes from, add the source in the text; if you cannot, note it for
   step 7.

Record each decision under the round's `## Author's re-judgement`:

```markdown
- C3 — accepted: <what changed in opinion.md>
- C7 — rejected: <why, with the citation you opened>
- C9 — needs the user: <what only they can confirm>
- C2 — escalated: same as round 1 C5, which I rejected; two verifiers disagree
```

Never accept a refutation without opening its evidence, and never dismiss
one without opening it either.

## 6. Revise the document — body only

Edit `opinion.md` in place, but during the loop touch **only the body**:

- Correct the sentences whose claims were accepted as refuted. If a corrected
  fact changes the reasoning or the position, rewrite those sections — do not
  leave a position standing on a fact you just removed.
- Do **not** yet add `(unverified: …)` markers, change `status`, or write to
  `## Log`. The next round's verifier reads this file; those marks would tell
  it what the previous verifier found and what to skip. They go in at the
  end (step 7).

Note whether the body changed in this round; step 2 needs it.

## 7. Finalize the document

After the loop ends:

- Mark claims that remained UNVERIFIABLE in the last round, where they
  appear, briefly: `(unverified: <why>)`.
- Set frontmatter `status: verified` and add to `## Log`:
  `- <date> verified in <n> round(s) — last round: <n> confirmed, <n> refuted (<n> accepted), <n> unverifiable; <n> escalated; see verdicts.md`
- Update `verified:` and `rounds:` in the scratch `verdicts.md`'s frontmatter,
  then move it to `.grounded/<doc>/verdicts.md`, replacing any earlier one
  (its summary is already in `## Log`). Remove the scratch directory.

## 8. Report

Tell the user, in this order:

1. Whether the position survived, changed, or fell — one sentence, first.
2. How many rounds ran and why the loop stopped (nothing refuted / document
   unchanged / three rounds), with each round's counts on one line.
3. Each accepted refutation, by round: the claim, what is actually the case,
   what changed in the document.
4. Each escalated item: both sides — the verifiers' evidence and why you
   rejected it the first time — so the user can settle it.
5. Each rejected refutation in one line, so they can overrule you.
6. Anything else that needs their answer.
7. The paths of `opinion.md` and `verdicts.md`.
