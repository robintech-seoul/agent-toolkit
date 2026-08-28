# code-wiki fixtures

Three synthetic fixtures used to develop and regression-test the plugin's
skills and commands. Each represents a different shape of source tree:

| Fixture | Shape | Used for |
|---|---|---|
| `minimal/` | Single source root (`src/`), Python, ~6 files, 2 levels deep | Smoke tests; first-build verification |
| `monorepo/` | Three source roots (`apps/web/src`, `apps/api/src`, `packages/lib`), TypeScript | Multi-root path math; cross-cutting topic flow (auth spans `apps/api/src/routes/auth.ts` + `packages/lib/auth.ts`) |
| `mixed/` | One source root, Python + non-code files (README, YAML config, ignored `static/`) | Inclusion of context files; verification that READMEs are read but not paged |

## Initializing

The fixture source files live as plain text under each fixture directory.
They are not git repos by default in this plugin's checkout. Run:

```bash
./fixtures/init-fixtures.sh
```

…to initialize each fixture as a 2-commit git repo (idempotent — skips any
fixture whose `.git/` already exists). The created `.git/` directories are
gitignored in the parent plugin so they don't pollute the marketplace repo.

## Using a fixture

Once initialized, point `code-wiki` at it the same way a real project would:

```bash
cd fixtures/minimal
# inside a Claude Code session in this dir:
/code-wiki:init        # source-roots: src
/code-wiki:build
```

## Re-creating from scratch

```bash
rm -rf fixtures/<name>/.git fixtures/<name>/wiki fixtures/<name>/.code-wiki
./fixtures/init-fixtures.sh
```
