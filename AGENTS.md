# Agent toolkit development

- Claude packages live in `claude/`; Codex packages in `codex/`. Keep each plugin self-contained for installation.
- Claude catalog: `.claude-plugin/marketplace.json`; Codex catalog: `.agents/plugins/marketplace.json`.
- Codex MVP-Builder: `codex/skills/mvp-builder/README.md` and `VALIDATION.md`. Runtime is standard-library Python, `bin/pipeline.py` + `bin/codex_runner.py`.
- Run regression tests with `python3 -m unittest discover -s codex/skills/mvp-builder/tests -v`.
- The program owns state, approval transitions, ledger and artifact writes. Skills invoke the program; they never substitute parent-session AI output or manually edit state.
- Keep fixture tests and actual model runs distinct. A pending gate is not a completed run. Preserve approved contracts, CLI failures, timeouts and invalid-response holds.
- Preserve source attribution and `prompts/full/LICENSE`. Do not change Claude runtime behavior as a side effect of Codex work.
- New Codex port branch starts at upstream `e8204973658f396052f8ec7d43cabc4a509063e7` (Claude MVP-Builder 0.4.2). Publication is separate from local implementation.
