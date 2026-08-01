---
name: build
description: Build an interactive, recursively drillable architecture map of a codebase as a single self-contained HTML file. Boxes are modules, arrows are real calls labeled with the interface name, clicking a box opens its interior one layer down, and every arrow expands to a card with full signatures and source locations. Use when asked for an architecture diagram, a system map, a structure or onboarding doc for a codebase, "how does this system fit together", or any clickable/visual overview of modules and the interfaces between them.
---

# Architecture explorer

Produce **one HTML file** that a reader can explore top-down: the whole system
on screen, then click into any box to see what it is made of, recursively.
Arrows carry the name of the interface that crosses the boundary; the full
signatures live in cards under the diagram.

The output is a documentation artifact, not a sketch. Everything in it must be
read out of the source. **Never draw a relationship you have not confirmed in
code** — an invented arrow is worse than a missing one, because the reader has
no way to tell them apart.

## Before you start

Settle two things with the user if they are not already clear:

- **Scope** — the whole repo, or one service/directory. This sets what L0 is.
- **Output path** — default `docs/architecture/index.html`.

## 1. Read the code, then build the model

Do the reading first and the HTML last. Rushing to render produces a diagram
that looks finished and is wrong.

- **L0** = deployment/execution units and external dependencies — processes,
  services, datastores, third-party APIs — and how they talk to each other.
  For a monolith that is one process plus its DB; do not inflate it.
- **Each deeper layer** = the interior of one box from the layer above, drawn in
  the same visual language (boxes, arrows, labels).
- **Recurse until there is nothing left to decompose.** Stop a branch when the
  next level would be individual functions rather than components.
- **5–9 boxes per layer.** More than that and the layer is unreadable — group
  the excess and push it one level down. Fewer than 3 usually means the layer
  should not exist; merge it upward.
- Name boxes after what they are in the repo (a package, a directory, a class),
  not after an abstraction you invented for the diagram.

## 2. Interfaces are the point

The value of the map is in the edges, not the boxes.

- **Arrow label** = the name of the thing that crosses the boundary: a function,
  an HTTP endpoint, an event, a query, a CLI invocation — whatever it actually
  is. Not a description ("saves data"), a name (`SqlStorage.put_objective`).
- **Below the diagram, one card per arrow** in that layer, holding:
  - the full signature or request shape (parameters, payload, return),
  - what it is for, in one or two sentences,
  - the transport/protocol, when there is one (HTTP + auth header, stdio, SQL),
  - the source location as `file:line` or `file.py::function`.
- Include the constraints a reader cannot infer from the signature: auth
  requirements, sync vs async, retry/idempotency semantics, error contracts.

## 3. Render it

**A single HTML file with no external resources.** No CDN scripts, no web
fonts, no remote images — it must work opened from `file://` with no network.
Inline SVG plus vanilla JS. No build step.

Interaction contract:

- Click a box that has an interior → descend into that layer.
- Breadcrumb, a back control, and `Esc` to go up.
- URL hash per layer (`#worker`) so a specific view can be linked.
- Click an arrow → jump to its card. Click a box → filter the cards to the ones
  touching that box.

Keep **all** structure data in one declarative object at the top of the file,
separate from the render code, so that updating the map means editing data:

```js
const MODEL = {
  <viewId>: {
    title, hint, vb: [x, y, w, h], parent: <viewId|null>,
    nodes:  [{ id, x, y, w, h, kind, title, lines: [], badge?, drill?: <viewId> }],
    edges:  [{ from, to, label, iface, via?, path?, dashed?, offset? }],
    ifaces: [{ id, title, from, to, transport, note,
               items: [{ sig, desc, ref }] }]
  }
}
```

Place boxes by hand — hand-set coordinates beat an auto-layout for a diagram
that is read many times and edited rarely. Edge label positions are worth
auto-placing (search for empty space near the midpoint), since they move
whenever a label changes. When an edge has no clean corridor between boxes,
route it explicitly through the gutters (`path: [{x,y}, …]`) instead of letting
it cut through a box.

## 4. Verify before you call it done

- **Model integrity** — every `edge.from`/`edge.to` names an existing node,
  every `drill` points at a view that exists, every `edge.iface` has a matching
  `ifaces` entry, and every `iface` is referenced by some edge. Check this by
  script, not by eye.
- **Open it** from `file://` and walk every layer: drill into each box that has
  `drill`, come back up, and confirm the hash round-trips.
- **Read the diagram as a picture** — labels overlapping each other, labels
  overlapping boxes, edges passing through unrelated boxes. These are the
  defects a model-integrity check cannot see.
- **Spot-check the facts** — pick a few cards and confirm the `file:line` still
  says what the card claims.

Write a short `README.md` next to the file: how to open it, the layer tree, and
where to edit (the `MODEL` object). Whoever updates this in six months needs it.

## Common failure modes

- **Plausible arrows.** Drawing what a system like this usually does instead of
  what this one does. If you cannot cite the call site, the arrow is not real.
- **A flat L0 with 20 boxes.** Every module hoisted to the top level. L0 is
  deployment units only.
- **Labels that describe instead of name.** "sends the task" tells the reader
  nothing they can grep for.
- **Structure data tangled into render code.** The map is then write-once, and
  it rots at the first refactor.
- **Layers invented for symmetry.** A box with one child does not need its own
  view; let it be a leaf.
