# grounded

Deep opinions from the strongest model, fact-checked by a cheaper one that
never saw the discussion.

Asking a strong model for a considered opinion on a hard problem works well.
Asking the same model, in the same conversation, to "double-check that" does
not: it re-reads its own reasoning and approves it. What catches mistakes is
a fresh context that receives only the finished text and has to find the
evidence itself — and for that job a cheaper model is enough, because
checking "does `src/a.py:40` really do X" is far easier than deciding what to
build.

`grounded` splits the two:

| Step | Who | Sees |
|---|---|---|
| `/grounded:ask` | Fable, in your session | the conversation, the code, the web |
| `/grounded:verify` → `grounded:verifier` | Sonnet, in a separate subagent, read-only | the opinion document and nothing else |
| `/grounded:verify` re-judgement | Fable, in your session | the verifier's cited evidence |

## Install

```
/plugin marketplace add robintech-seoul/agent-toolkit
/plugin install grounded@robintech
```

Claude Code only. `ask` and `verify` need access to Fable; `verifier` uses
Sonnet.

## Use

```
/grounded:ask Should the sync job move from cron to a queue consumer?
```

`ask` switches to Fable for that turn no matter what model the session is on,
works the problem against the actual code and docs, and writes the opinion to
`.grounded/<date>-<slug>/opinion.md` — position, reasoning, the facts it
rests on with sources, where it could be wrong. The chat reply summarizes and
points at the file.

Keep discussing with more `ask` calls; each one edits the same document and
runs on Fable. (A plain follow-up message runs on the session's model.)

```
/grounded:ask what if the queue consumer crashes mid-batch?
```

When the document says what you want checked:

```
/grounded:verify
```

`verify` hands the document's path — only the path, in a fixed prompt — to
the `verifier` subagent. It extracts every checkable claim, including
premises the text takes for granted, and tests each against primary evidence:

| Verdict | Requires |
|---|---|
| CONFIRMED | a citation it opened — `path:line`, command output, URL and passage |
| REFUTED | a citation of the contradicting evidence |
| UNVERIFIABLE | what it tried; memory never counts as evidence |

The reports land verbatim in `verdicts.md` next to the opinion. Then Fable
re-judges every refutation by opening the cited evidence itself — accepting,
rejecting with a reason, or handing it to you — and revises `opinion.md` so it
never stands on a fact that was just removed.

If the document changed, a **fresh** verifier checks the revision, and so on
for up to three rounds. The loop stops when a verifier refutes nothing, when
the document stops changing, or after the third round. Your session is the
orchestrator; no extra agent drives it. A refutation that Fable rejected once
and a second, independent verifier raises again is not re-judged — it is
escalated to you with both sides, so the loop checks three times rather than
insists three times. No round's verifier learns what the previous one found:
markers and the log line are written only after the loop, round reports stay
in a temp directory outside the repository until then, an earlier run's
`verdicts.md` is moved aside first, and the verifier is told to read nothing
under `.grounded/` but the file it was given.

The chat reply leads with whether the position survived, then the rounds and
what each one changed.

## Files

```
.grounded/
└── 2026-10-06-cron-to-queue/
    ├── opinion.md     the opinion; frontmatter status: draft | verified; ## Log of edits
    └── verdicts.md    per round: verifier report verbatim + the author's re-judgement
```

Commit the folder to keep the record with the decision, or add `.grounded/`
to `.gitignore` if opinions are personal scratch. Point `ask` and `verify`
at a specific file with `--doc=<path>` / `<path>`.

## Design notes

- **The document is the original.** `ask` writes the file before replying in
  chat. Writing in chat and copying to a file afterward re-generates the
  text, and the copy drifts.
- **The verifier extracts the claims, not the author.** An author's list of
  "claims to check" omits whatever the author took for granted.
- **The prompt is fixed.** Only the path goes in, so the parent cannot slip
  in hints about what to trust or skip.
- **Refutations are re-judged, not applied.** The verifier is cheaper and
  can misread; the strongest model opens the citation and decides.
- **Verification starts on the finished document, and loops until a fresh
  verifier finds nothing.** Running it on every draft interrupts the
  discussion; running it once leaves the revision unchecked. Three rounds is
  the cap.
- **A refutation raised twice goes to you, not back to Fable.** Two
  independent verifiers disagreeing with the author is a signal; letting the
  author reject it again would be the self-approval the design exists to
  avoid.
- **Facts only.** Judgements, predictions and recommendations are not
  verdicts' business. The verifier reports whether the facts under them
  hold; whether the conclusion follows is yours and Fable's.

## Limits

- The verifier's Bash is restricted by instruction to inspecting commands,
  not by tooling. It runs under your session's permission mode.
- The model switch is not visible from inside the turn, so the skills do not
  check it. To confirm it on your setup, run once headless and look at
  `modelUsage`:
  `claude -p --model sonnet --output-format json "/grounded:ask …"` — it
  should list only the Fable model. If your organization's allowlist excludes
  Fable, the turn silently runs on the session model.
- Model names are pinned (`fable`, `sonnet`). When a stronger family ships,
  bump the plugin.
