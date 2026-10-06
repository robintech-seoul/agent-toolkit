---
name: ask
description: Give a deep, reasoned opinion on a hard technical question using the strongest model, written as a document that `/grounded:verify` will fact-check later. Runs on Fable regardless of the session's model. Use for architecture decisions, debugging theories, "is this approach right", trade-off analyses, or any question where the answer rests on facts about code, APIs or documents that should be double-checked — and for follow-ups that continue such a discussion. Also triggers on "깊이 있게 의견 내줘", "근거 있는 의견", "이 접근이 맞나".
argument-hint: "<question or follow-up> [--doc=<path>]"
model: fable
---

# Grounded opinion — ask

Answer a hard question with a considered opinion, and make the opinion a
**document** so that a separate, context-free verifier can later check the
facts it rests on. The document is the deliverable; the chat reply only points
at it.

## 0. The model

This skill sets `model: fable`, so this turn runs on the strongest model no
matter what the session is on. You cannot confirm that from inside the turn —
the environment's model line still names the session model — so do not try;
just do the work. (The README says how a user can check.)

## 1. Find or start the document

```
/grounded:ask <question or follow-up> [--doc=<path>]
```

Everything that is not `--doc` is the question. Decide which document this is
about, in order:

1. `--doc=<path>` — use that file.
2. A document under `.grounded/` that this conversation has already been
   editing — continue it.
3. Otherwise this is a new question: create
   `.grounded/<YYYY-MM-DD>-<slug>/opinion.md` under the repository root
   (`git rev-parse --show-toplevel`, or the working directory outside git).
   `<slug>` is a short ASCII kebab-case summary of the topic, at most 40
   characters; translate if the question is not in English.

If a `.grounded/` document exists but it is not clear whether the user means
to continue it, ask.

## 2. Think, then write the document first

Work the problem the way a senior engineer would before committing to a
position: read the code the question is about, open the docs, run read-only
commands, look at history. Form the opinion from what you found, not from
what you expect to find.

Then **write the opinion into the file before saying anything in chat**. The
file is the original; the chat reply is derived from it. Writing the opinion
in chat and copying it afterward re-generates the text, and the copy drifts.

Document shape — keep the headings, drop sections that do not apply:

```markdown
---
question: <the question, verbatim>
created: <YYYY-MM-DD>
status: draft
---

# <Title>

## Position
The answer in a few sentences. State it plainly.

## Reasoning
Why. Each step of the argument, in order.

## What this rests on
The facts the position depends on, as plain statements — what the code does,
what the API returns, what the document says, what the numbers are. Give the
source when you looked at one: `path:line`, a URL, a command and its output.
Include the premises you take for granted; those are what verification most
often catches.

## Where it could be wrong
What would change the conclusion, and which facts above carry the most weight.

## Log
- <YYYY-MM-DD> created
```

Rules for the text:

- **Never claim a fact you did not see.** If you are reasoning from memory
  about how a library behaves, say so in the text ("as far as I recall …")
  rather than stating it as fact. The verifier will test it either way.
- **No confidence markers aimed at the verifier.** Do not tag sentences as
  "verified", "certain" or "already checked". The verifier must not be told
  what to skip.
- Judgements and recommendations are yours to make; write them as such. Only
  the facts under them are what gets checked.

## 3. Reply in chat

Give the position and the gist of the reasoning in a few paragraphs, then the
document path. Do not paste the whole document.

End with how to continue:

- more discussion → `/grounded:ask <follow-up>` (each call runs on Fable; a
  plain follow-up message runs on the session's model)
- the document is done → `/grounded:verify`

## 4. Follow-ups

A follow-up edits the same document: revise the position, reasoning and facts
in place so the document always reads as the current opinion, not as a
transcript. Add one line to `## Log` per follow-up saying what changed. If a
follow-up reverses the position, say so at the top of the chat reply.

## What this skill does not do

- It does **not** spawn the verifier. Verification runs once, on the finished
  document, from `/grounded:verify`. Verifying every draft wastes the
  verifier's work and interrupts the discussion.
- It does not edit the project. The opinion may recommend changes; making
  them is a separate decision for the user.
