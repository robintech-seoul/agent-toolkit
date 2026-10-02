---
name: diff
description: Explain what a branch changed, block by block, as an interactive architecture map in a single self-contained HTML file. Compares a head branch against a base (default — the current branch against main or master), assigns every changed file to the module box it lives in, explains each block's changes as features with file:line references, and draws the map with added, modified and removed boxes, arrows and interfaces marked. With --open, builds the map in a headless Claude session and opens it with a chat panel that answers questions about the change from that session's analysis and about the existing code from the code-wiki. Use when asked what a branch or PR changed structurally, to explain or review a branch's changes by module, for a visual change summary, to ask questions about a branch's changes next to its map, or "브랜치 변경 내용을 블럭별로 설명해줘".
argument-hint: "[head [base]] [--save-to[=<path>]] [--include-uncommitted] [--open]"
---

# Branch change map

Produce **one HTML file** that shows what a branch changed: the architecture
map of the code at the head of the branch, with every box, arrow and interface
the branch touched marked, and under it one card per block explaining which
features changed and where.

This skill builds on `/arch-explorer:build`. Read its `SKILL.md` — the sibling
`build/SKILL.md` in this plugin — and follow its sections 1–4 (reading the
code, interfaces, rendering, verifying) with the overrides below. Its rule
holds here too, and applies to changes as much as to structure: **never claim
a change you have not seen in the diff.**

`<plugin>` below is this plugin's root: two levels above this skill's base
directory. `<root>` is `git rev-parse --show-toplevel`.

## 0. Arguments

```
/arch-explorer:diff [head [base]] [--save-to[=<path>]] [--include-uncommitted] [--open]
```

| Given | head (the new work) | base (compared against) |
|---|---|---|
| `head base` | `head` | `base` |
| `head` | `head` | auto-detected (§1) |
| nothing | the current branch | auto-detected (§1) |

Three flags, and no others; anything else that is not a ref, ask about
rather than guess.

- `--save-to` changes where the file is written (§6).
- `--include-uncommitted` compares against the working tree instead of head's
  last commit: staged, unstaged and untracked (not ignored) files all count as
  part of the branch's work. It applies only when head is the current branch,
  since only the current branch has a working tree here.
- `--open` builds the map in a headless Claude session instead of this one,
  then opens it with a chat panel that forks that session (§8). Without it,
  this session builds the map and nothing is opened.

**If your prompt already gives you `RANGE` and `OUTPUT`, you are that
headless build:** skip §0, §1 and §8, follow §2–§7 for that range, and write
only `OUTPUT` — the program records the sidecar.

## 1. Resolve the range

The program resolves the range; it never checks out, resets, stashes or
touches the user's index. **Do not do any of that yourself either.**

```bash
python3 "<plugin>/bin/diff_session.py" resolve --root <root> [head [base]] \
  [--include-uncommitted] [--save-to[=<path>]]
```

Pass the user's refs and flags through as given (`--save-to` alone, or
`--save-to=<path>`; never `--save-to <path>`). It prints one of:

| Output | Do |
|---|---|
| `ask: true` | Ask the user `reason`, offering `choices` when there are any. Then resolve again with what they chose — an explicit `head base`, or `head head` with `--include-uncommitted` for "only the uncommitted changes". Do not proceed on a guess. |
| `empty: true` | Say that head has no changes against the base and stop. Write no file. |
| `error` | Report it and stop. |
| the range | Go on. |

The range has `head`, `head_sha`, `base`, `mb` (the merge-base), `after`,
`uncommitted`, `read_from`, `commits`, `files`, `notes`, `out` (where §6 puts
the map), `sidecar` and `range_file`. What it settles, for the sections
below:

- **Diffs run from the merge-base `mb`**, the same as `git diff base...head`. A
  two-dot diff against the base tip would also show everything that landed on
  the base after the branch forked, as if the branch had reverted it.
- **The after side is `<after>`**: head's commit, or with
  `--include-uncommitted` a tree snapshot of the work tree (ignored files
  left out). Every diff below uses `<after>`; the commit list reads
  `mb..head`.
- **`notes`** go in the report: which base ref was used when local and
  `origin/` disagree, uncommitted changes left out (and that the flag would
  include them) or how many files came from them, a file to be overwritten.

## 2. Collect the change

```
git log --reverse --format='%h %s' mb..head
git diff --name-status -M mb <after>
git diff --numstat -M mb <after>
```

**Where to read code.** The code before the change is `git show mb:<path>`.
The code after it is the working tree when `read_from` is `worktree`;
otherwise add a temporary worktree,
`git worktree add --detach <scratch-dir> <head>`, read there, and remove it
with `git worktree remove` when done. (A headless build is told where to read
instead; its worktree is made and removed by the program.)

## 3. Map the head — only as deep as the change

Build the map of the code at head following build's sections 1–2, with these
overrides:

- **Scope** is the whole repository — a change can reach anywhere. Do not ask.
- **Start from an existing map when there is one.** If
  `git show mb:docs/architecture/index.html` succeeds, take its `MODEL` as the
  starting point and bring it up to date with head, instead of mapping from
  nothing.
- **Depth follows the change.** Draw L0 and L1 in full. Below that, drill only
  into boxes that contain a changed file; an unchanged box stays a leaf with
  no `drill`. Mapping untouched subtrees makes the cost grow with the
  repository instead of with the change.
- **Keep what was removed.** A module, arrow or interface that existed at `mb`
  and is gone at head stays in the map, marked `removed`, where it used to be.
- **Assign every changed file to a block** — the deepest box whose code
  contains it. A file that belongs to no box (lockfiles, CI config, docs) goes
  in an explicit `other` block. No changed file is dropped.

## 4. Explain each block — subagents

The block is the unit of explanation. For a small change (about five files or
fewer, or a single block) do this yourself. Otherwise launch **one subagent
per block, all in a single message** so they run in parallel; with more than
six blocks, group sibling blocks until there are six at most.

Give each subagent: head, `mb`, `<after>`, where to read head's code (§2),
the block's box title and its list of changed files. Tell it to read
`git diff mb <after> -- <files>`, the surrounding code at head and the old
code with `git show mb:<path>`, and to **return only this JSON, writing no
files**:

```json
{
  "block": "<viewId>/<nodeId>",
  "summary": "one or two sentences: what this block's change does",
  "features": [
    { "title": "name of the behaviour that changed",
      "desc": "what it did before, what it does now, why it matters",
      "refs": ["path:line"] }
  ],
  "ifaces": [
    { "name": "SqlStorage.put_objective",
      "change": "added | modified | removed",
      "before": "old signature or null", "after": "new signature or null",
      "ref": "path:line" }
  ],
  "modules": [
    { "path": "src/foo/", "change": "added | removed", "what": "one line" }
  ]
}
```

Describe **features, not lines.** "Retries the upload three times on 5xx" is
an explanation; "added a for loop in upload.py" is a diff read aloud.

You are the only writer of `MODEL`. Merge the subagents' results into it
yourself, and spot-check a few of their `refs` before trusting them.

## 5. The change overlay

The file carries build's `MODEL` plus change marks. An element with no
`change` is unchanged, so an untouched part of the map is plain build output.

```js
const MODEL = {
  <viewId>: {
    ...,                                  // as in build
    nodes:  [{ ..., change?: 'added' | 'modified' | 'removed' }],
    edges:  [{ ..., change? }],
    ifaces: [{ ..., change?,
               items: [{ sig, before?, desc, ref }] }]   // before: old signature
  }
}
const CHANGES = {
  range:  { head, base, mergeBase, uncommitted: bool, commits: [{ sha, subject }] },
  blocks: [{ node: '<viewId>/<nodeId>' | 'other', summary,
             features: [{ title, desc, refs: [] }],
             files:    [{ path, status, added, removed }] }]
}
```

Do not store what can be derived. Whether a box *contains* changes is
computed by the renderer from its descendants, not written into the data.

The renderer is yours to write, as in build, and must add to build's
interaction contract:

- A header with head vs base, the merge-base short sha and the commit list
  (collapsed by default). When `uncommitted` is true, the header says the map
  includes uncommitted work, so nobody mistakes it for the pushed branch.
- A legend. Added, modified and removed each get a distinct colour; removed
  elements are drawn ghosted and dashed.
- A badge on every box with changes inside it, showing how many changed files
  it holds, so a reader can follow the change down from L0.
- Under the diagram, the change cards for the blocks in the current view,
  before the interface cards. Clicking a box filters both to that box.
- An interface card whose signature changed shows `before` and the new
  signature together.
- `refs` link to nothing outside the file; show them as `path:line` text.

## 6. Where to write it

Write the map to the range's `out`. `resolve` names it `<head>-vs-<base>.html`,
with `/` in branch names replaced by `-` (`feature/login` against `main` →
`feature-login-vs-main.html`). With `--include-uncommitted`, `<head>` becomes
`<head>-uncommitted` (`feature-login-uncommitted-vs-main.html`), so a snapshot
of work in progress never overwrites the map of the committed branch.

| `--save-to` | Written to |
|---|---|
| absent | `./<head>-vs-<base>.html` in the current directory |
| `--save-to` | `docs/architecture/changes/<head>-vs-<base>.html` |
| `--save-to=<path>` ending in `.html` | exactly `<path>` |
| `--save-to=<path>`, any other path | `<path>/<head>-vs-<base>.html` |

Paths are relative to the current directory. Create missing directories. If
the file already exists, overwrite it — it is the same comparison, re-run —
and say in the report that you did. Unlike build, write no `README.md` next to
it: this is a review of one branch, not a document to maintain.

After the checks in §7 pass, record the sidecar, so that
`/arch-explorer:open <out>` recognises the map as a change map later:

```bash
python3 "<plugin>/bin/diff_session.py" record --range-file <range_file>
```

It writes `<stem>.arch-explorer.json` next to the map with `session: null` —
this session is interactive, so the chat cannot fork it and will answer
without the build's analysis.

## 7. Verify before you call it done

Run build's section 4 checks, and add:

- **Coverage** — every path from `git diff --name-status mb <after>` appears in
  exactly one block's `files`. Check this by script.
- **Reachability** — every element with a `change`, and every block's node,
  can be reached from L0 through `drill` links.
- **Refs land on the change** — each feature has at least one ref inside a
  changed hunk: after-side line numbers from `git diff -U0 mb <after>` for added
  or modified code, `mb`-side for removed code. Check this by script.
- **Removed means removed** — every `removed` element existed at `mb` and does
  not exist at `<after>`.

Then remove any worktree you added, and report: the output path, the range
(head, base, merge-base, commit count), blocks and files changed, and the
range's `notes`. Mention that `/arch-explorer:open <out>` opens it with a
chat panel, and that `--open` next time gives that chat this build's
analysis.

## 8. `--open`: build headless, then open with a chat panel

The map is built by a headless `claude -p` session that the program starts,
so that the chat can later fork that session and answer from its analysis.
Ask every question **before** the build: it runs unattended and can take
several minutes.

1. **Range.** §1, including its questions.
2. **Engine.** `python3 "<plugin>/bin/engines.py" choose --engine claude`. If
   `engine` is null, Claude Code's CLI is not installed: say `--open` needs
   it, and ask whether to build the map here without the chat instead (then
   follow §2–§7). A saved default of codex does not matter here; say that the
   build and the chat use Claude this time.
3. **Wiki.** The chat answers questions about unchanged code from the
   code-wiki, judged against the merge-base:
   ```bash
   python3 "<plugin>/bin/status.py" check --root <root> --map <out> --against <mb>
   ```
   Read `wiki` and handle it as `/arch-explorer:open` §2 does (the sibling
   `open/SKILL.md`), with one difference: a missing or declined wiki does
   **not** turn the chat off — questions about the change still have the
   build's analysis. Say that answers about unchanged code will be thin.
   Remember any wiki dirs for step 5.
4. **Build**, in the background (Bash `run_in_background`):
   ```bash
   python3 "<plugin>/bin/diff_session.py" build --range-file <range_file>
   ```
   Tell the user it is running and where its progress log is (`build_log`
   from the range); read the log when they ask how it is going. When it
   ends it prints:
   - `error` → report it with the last lines of `log`, and stop. When it
     names files the build changed, ask the user to review them; the program
     does not revert anything. When a `session` is given, the user can
     inspect it with `claude --resume <session>`.
   - `reused: true` → the same range was built before; say so. Pass `--force`
     only when the user asks for a fresh build.
   - otherwise `report` is the build's §7 report.
5. **Open.**
   ```bash
   python3 "<plugin>/bin/chat_server.py" launch --root <root> --map <out> \
     --engine claude [--wiki <dir> …]
   ```
   As in `/arch-explorer:open` §4: on an error, show the last lines of its
   log and stop.
6. **Report**: the build's report (output path, range, blocks and files, the
   range's notes), the URL, that answers about the change come from the
   build session (`session`) and those about the rest of the code from the
   wiki, and how to stop the server:
   `python3 "<plugin>/bin/chat_server.py" stop --root <root> --map <out>`.
   `/arch-explorer:open <out>` reopens it later with the same build session.

## Common failure modes

- **A two-dot diff.** Comparing against the base tip shows the base's newer
  commits as reverted by the branch. Always diff from the merge-base.
- **Reading the diff aloud.** Cards that list changed lines instead of saying
  which behaviour changed.
- **Mapping the whole repository deeply.** Only changed paths get depth.
- **Dropping files that do not fit a box.** They go in `other`, visibly.
- **Resolving the range by hand.** `diff_session.py resolve` already does it,
  without touching the user's index; its snapshot excludes the map's own
  files.
- **Checking out the branch to read it.** Use `git show` or a separate
  worktree; the user's working tree is not yours to move.
- **Asking during an `--open` build.** Nobody is there to answer; settle
  everything in §8 steps 1–3 first.
