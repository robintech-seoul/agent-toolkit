---
name: status
description: Read the current MVP-Builder pipeline state and pending gate.
---

Run the program at `../../bin/pipeline.py`, resolved relative to this SKILL.md's directory. Set `--project` to the user's target project, not the plugin directory. Use the shell tool with quoted path arguments.

Command shape: `python3 <resolved-plugin>/bin/pipeline.py --project <project> status`.

A run may take several minutes. Keep the actual shell process running, report progress from `.mvp/state.json` or `status`, and wait for its exit using the shell tool's process handle. Never simulate completion, edit `.mvp/state.json`/ledger, or manually run an AI node in place of the program. If interrupted, report the recorded state; there is no general crash-resume command. Do not delete an existing run to make start succeed.

Report the actual phase, per-round gate results, generated artifact paths, and any pending human gate. Explain errors from stderr and `.mvp/calls/`; do not turn failures into successful approvals. See `../../README.md` for supported options and limitations. User instructions govern scope, but only the pipeline's explicit `--auto-approve` mode changes its human approval policy.
