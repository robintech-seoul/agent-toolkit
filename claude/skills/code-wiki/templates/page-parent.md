# <folder name>

## Overview

<1–3 paragraph synthesis of the parent's overall role, combining children + loose files into a coherent narrative. This is the "Overall role synthesis" — the highest-level statement of what this folder is.>

## Sub-modules

<Narrative synthesis of the children's wikis. For each child, give a meaningful paragraph (not a one-liner) describing what it contains, its responsibility, and how it relates to its siblings. The bullet list below is for navigation; the prose above it is for understanding.>

- [<child>](./child/index.md) — <one-line index>
- ...

## Loose files

<Only present if the parent folder has files directly in it (not in any sub-folder).>

<Brief narrative synthesis of what these loose files do collectively — the "Loose files synthesis".>

- [`<file>`](relative/path) — <one-line description>

## Architecture

<How sub-modules and loose files interact: data flow, dependency direction, layering. Include a mermaid diagram if and only if the LLM judges that a diagram materially clarifies the structure (i.e. when there are multiple components with non-trivial relationships). Skip diagrams when prose suffices.>

## Related Topics

<Links to topic pages relevant to this module, if any.>

---

<!--
Generation strategy:
A parent wiki has three distinct synthesis outputs combined into one page:
  1. Loose files synthesis — what the parent's own (non-subdirectory) source files do.
  2. Children synthesis — a narrative summary of what the children's wikis collectively contain.
  3. Overall role synthesis — how (1) and (2) together define the parent's role in the system.
Parent generation uses three coordinated prompts internally; this template is the unified output format.
-->
