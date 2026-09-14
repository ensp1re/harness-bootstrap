# Harness reference

Read this when choosing checks, rerunning bootstrap, migrating a 1.x project, or debugging the runner. The runner is `scripts/harness.py`, copied from `assets/harness.py` (Python 3.8+, standard library only). Commands print short text. Exit 0 means success, 1 means refused or checks failed, 2 means invalid input or unreadable state. `python3 scripts/harness.py -h` lists the commands.

## Files in a bootstrapped repository

| File | Written by | Purpose |
|---|---|---|
| `AGENTS.md` | project part: agent and user; block between the harness markers: `bootstrap.py install` | Loaded by the coding agent every session: commands, project rules, task loop |
| `docs/PROJECT.md` | agent and user | Users, scope, domain, R-/D-/A-/Q- rows |
| `docs/RESEARCH.md` | agent, discovery tier 1+ | V- facts with sources, alternatives, what was not researched |
| `docs/ARCHITECTURE.md` | agent, only with 2+ deployable parts or boundaries the code does not make obvious | Components, data flow, ownership |
| `docs/tasks.json` | runner only | Queue, states, evidence, notes |
| `docs/config.json` | agent | Checks, optional `fingerprintPaths` |
| `docs/install.json` | `bootstrap.py install` | Hashes of installed content, for safe reruns |
| `docs/runs/` | runner, gitignored | One log per check run |

## Task states

| Change | Command | Refused when |
|---|---|---|
| not_started or blocked → active | `start ID` | another task is active or verified; a dependency is not passing; no acceptance or no own check |
| active → verified, or stays active | `verify ID` | the task is not in progress; a check id is undefined; a verify is already running |
| verified → passing | `done ID --proof "N=..."` | evidence is stale; uncommitted changes outside bookkeeping files; a criterion has no proof |
| not_started or active → blocked | `block ID --reason` | — |
| verified or passing → active | `reopen ID --reason` | another task is in progress |
| unfinished → dropped | `drop ID --reason` | the task is passing |

`add`, `edit`, `note`, `show`, `list`, `status` and `validate` never change state. `edit` list options replace the list; `none` clears it.

## Checks

```json
{"schemaVersion": 2, "checks": [
  {"id": "unit", "argv": ["npm", "test"], "required": true},
  {"id": "e2e", "argv": ["npx", "playwright", "test"], "timeoutSeconds": 600}
]}
```

- `argv` runs without a shell. Use `["sh", "-c", "..."]` only for pipes or `&&`.
- `required: true` checks run on every verify and catch regressions. Other checks run only for tasks that list them, so a task's own check can target exactly its acceptance.
- Optional: `cwd` (default `.`), `timeoutSeconds` (default 900). A timeout kills the check's whole process group.
- Take commands from the repository first (package scripts, Makefile, CI steps). A check whose tool is not installed yet fails with `missing-command`; the task that sets the tool up makes it pass.

| Stack | Typical checks |
|---|---|
| Web app on Node | `npm run lint`; `npx tsc --noEmit`; `npx vitest run`; `npm run build`; `npx playwright test` with `webServer` in the Playwright config, so the test starts and stops the app |
| Node service or library | `npm test` or `node --test`; an HTTP smoke test that listens on port 0 |
| Python | `ruff check .`; `mypy` when configured; `pytest -q` or `python -m unittest` |
| Go | `go vet ./...`; `go test ./...` (use `httptest` for HTTP) |
| Rust | `cargo clippy -- -D warnings`; `cargo test` |

For a web project, every user-visible acceptance criterion gets a browser test. Keep traces or screenshots on failure (Playwright `trace: 'retain-on-failure'`); their paths appear in the check log.

## Evidence and freshness

`verify` stores each check's outcome, exit code, duration and log path, plus two hashes: the task definition (behavior, acceptance, checks) and the repository files (git-tracked and untracked non-ignored files, or `fingerprintPaths`). `docs/tasks.json`, `docs/install.json`, `docs/runs/` and the lock are excluded, so notes and queue edits never make evidence stale.

- A verified task is stale when its definition or any file changed after verify. `done` refuses it; run `verify` again.
- A passing task is flagged only when its definition changed. Later code changes are normal, and required checks catch regressions. Until the task is reopened and finished, or the definition restored, tasks that depend on it wait.
- For verified tasks, evidence written by harness 1.x counts as stale.
- Files changed by the checks themselves are listed after verify. Ignore generated output in `.gitignore`.

## Recovery

- **Interrupted verify:** `status` says "verify interrupted"; run `verify` again.
- **Lock:** held only while `docs/tasks.json` is written. A lock left by a dead process is taken over.
- **Changes during a running verify:** if the task was blocked, dropped or re-verified meanwhile, the running verify discards its result.
- **Invalid JSON or schema:** commands exit 2 without writing. Fix the file, then `validate`.

## Rerunning bootstrap

Run `python3 <skill>/scripts/bootstrap.py install ROOT` again, with `--dry-run` first on a repository you did not bootstrap. It updates `scripts/harness.py` and the AGENTS.md block only when they are unchanged since the last install, and reports `conflict` otherwise. It never changes `docs/tasks.json`, `docs/config.json`, or any other doc.

## Migrating from harness-bootstrap 1.x

1. Run `install --dry-run`, then `install`. An old runner (`scripts/harness-runner.mjs`, `cmd/harness`) is reported, not deleted. A 1.x runner at `scripts/harness.py` shows as a conflict: move it aside and rerun.
2. `docs/tasks.json` version 1 is read as is, and the first write stores version 2. Verified tasks need `verify` again; passing tasks stay passing. Archived tasks in `docs/archive/ID.json` still satisfy dependencies.
3. Move decisions and next steps that are still true from `docs/handoff.json`, `docs/SESSION_HANDOFF.md` and `docs/PLAN.md` into D- rows or task notes, then delete those files. `status` reminds you while they exist.
4. RELIABILITY, SECURITY, TECH_DEBT and CHANGE documents are no longer generated. Keep the ones with real project rules and link them from AGENTS.md; open debt items become tasks.
5. Delete the old runner's instructions from AGENTS.md, keep your own project notes, and commit.
