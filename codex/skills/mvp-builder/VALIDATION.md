# Validation — 2026-09-12

## Automated regression tests

`python3 -m unittest discover -s codex/skills/mvp-builder/tests -v`

**21 tests passed.** These include real subprocess calls to a deterministic CLI double; they do not count as model evaluations.

- Human spec/design approval waits; rejection stays within the appropriate phase.
- Automatic design completion and automatic holds for missing IDs/review exhaustion.
- Full-mode high-level design prompt availability.
- Delta review resolution, reentry, finding-ID deadlock, transactional rejection of invalid/partial responses.
- Incompatible Claude/foreign state is rejected without overwrite.
- Existing-run overwrite rejection; stale SPEC after CLI failure cannot pass; old DESIGN from another idea is regenerated.
- Nonzero CLI exit, missing/invalid response and timeout.
- Protected contract/control mutation and symlink output rejection before build export.
- Generated tests run outside the actual project and cannot modify its approved contracts through relative writes.
- Dependencies prepared in the build copy remain available to the completion gate, then are cleaned up.
- Multiline/shell-metacharacter idea preservation and CLI writer locking; status remains readable during a lock.

## Actual Codex integration

A disposable, standard-library Python addition module was run through the program using `--lite --fast --auto-approve` and the user's configured Codex model. The parent conversation did not write its SPEC, DESIGN, implementation, tests or review responses.

Result: **built**, process exit **0**.

| Check | Result |
|---|---|
| Actual Codex subprocess nodes | 5: spec, design, review, plan, build |
| Acceptance criteria | A1, 1 criterion |
| Design rounds | 1, ID coverage 100% |
| Review rounds | 1, open must 0 |
| Build rounds | 1 |
| Source / test files | 1 / 1 |
| Test runner | Python unittest discover |
| Test result | test_A1 passed, exit 0 |
| Missing acceptance IDs in tests | 0 |
| Approved SPEC / DESIGN | unchanged |

An earlier real run exposed an ID matcher bug: `test_A1` was not recognized due to underscore boundaries. That run stopped at build_incomplete rather than falsely passing. The corrected run reached built. The later build-workspace dependency-lifetime adjustment was covered by the regression suite; the real smoke result is evidence for the five-node pipeline, not an exhaustive model/option matrix.

Raw request/event/response/state files are retained in the lecture workspace under `docs/implementation/mvp-builder-codex-validation/real-run/`; they are not included in this distributable plugin. This test used automatic program gates, not user-reviewed artifact approvals. Human/rejection/deadlock paths are covered with fixtures, not claimed as separate live model runs.

## Packaging

- Codex plugin manifest validation passed.
- Four skill manifests validated.
- Local marketplace registration and plugin installation succeeded with an isolated temporary Codex home, leaving the user's normal plugin installation untouched.
- Actual Codex loader resolved `.agents/plugins/marketplace.json` source `./codex/skills/mvp-builder` correctly and installed the package with its scripts, schemas, policies and prompts.

## Limits

No claim of equal model outputs, latency, cost or reasoning quality across Claude/Codex. Full/lite, build/design and review failures are structurally tested; only the small lite/fast automatic build above was exercised against a real model. No external Slack/GitHub actions or deployments were performed. Existing Claude implementation files were not changed (README cross-link only).
