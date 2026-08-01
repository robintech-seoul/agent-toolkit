# arch-explorer

Turn a codebase into an interactive architecture map — a single HTML file you
open from `file://`, no build step, no network.

Boxes are modules. Arrows are calls that actually exist in the source, labeled
with the name of the interface that crosses the boundary. Click a box to descend
into what it is made of; keep clicking until there is nothing left to decompose.
Under the diagram, every arrow expands into a card with full signatures, the
transport, and `file:line` source locations.

## Install

```
/plugin marketplace add robintech-seoul/agent-toolkit
/plugin install arch-explorer@robintech
```

## Use

```
/arch-explorer:build
```

Then say what to map — the whole repo, or one service. The skill also triggers
on its own when you ask for an architecture diagram, a system map, or a
structural overview of a codebase.

Output defaults to `docs/architecture/index.html` plus a short `README.md`
covering the layer tree and how to update it. All structure data lives in one
`MODEL` object at the top of the HTML, so later edits are data edits.
