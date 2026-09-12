---
name: start
description: Start the MVP-Builder program from an idea when the user asks to create an MVP or run this pipeline.
---

Run the program at `../../bin/pipeline.py`, resolved relative to this SKILL.md's directory. Set `--project` to the user's target project, not the plugin directory. Use the shell tool with quoted path arguments.

Command shape: `python3 <resolved-plugin>/bin/pipeline.py --project <project> start`.

Save the user's idea verbatim to a temporary UTF-8 file and pass `--idea-file <file>`. This preserves shell metacharacters and multiline input. Remove the temporary file afterward. Pass requested `--lite`/`--full`, `--fast`/`--profile`, `--mode design`, `--model`, `--effort`, or `--auto-approve` options. Default to full/standard/build/human; do not add automatic approval unless the user requests it. The program must execute every node through codex exec; do not produce its artifacts in the parent conversation.

A run may take several minutes. Keep the actual shell process running, report progress from `.mvp/state.json` or `status`, and wait for its exit using the shell tool's process handle. Never simulate completion, edit `.mvp/state.json`/ledger, or manually run an AI node in place of the program. If interrupted, report the recorded state; there is no general crash-resume command. Do not delete an existing run to make start succeed.

Report the actual phase, per-round gate results, generated artifact paths, and any pending human gate. Explain errors from stderr and `.mvp/calls/`; do not turn failures into successful approvals. See `../../README.md` for supported options and limitations. User instructions govern scope, but only the pipeline's explicit `--auto-approve` mode changes its human approval policy.
