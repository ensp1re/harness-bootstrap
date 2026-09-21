# Harness reference

Read this when choosing checks, rerunning bootstrap, migrating a 1.x project, or debugging the runner. The runner is `scripts/harness.py`, copied from `assets/harness.py` (Python 3.8+, standard library only). Commands print short text. Exit 0 means success, 1 means refused or checks failed, 2 means invalid input or unreadable state. `python3 scripts/harness.py -h` lists the commands.

## Files in a bootstrapped repository

| File | Written by | Purpose |
|---|---|---|
| `AGENTS.md` | project part: agent and user; block between the harness markers: `bootstrap.py install` | Loaded by the coding agent every session: commands, project rules, definition of done, task loop |
| `docs/PROJECT.md` | agent and user | Users, scope, domain, R-/D-/A-/Q- rows |
| `docs/RESEARCH.md` | agent, discovery tier 1+ | V- facts with sources, alternatives, what was not researched |
| `docs/ARCHITECTURE.md` | agent, only with 2+ deployable parts or boundaries the code does not make obvious | Components, data flow, ownership |
| `docs/tasks.json` | runner only | Queue, states, must-not-change lists, evidence, reviews, notes, last wrapup |
| `docs/config.json` | agent | Checks, optional `fingerprintPaths` |
| `docs/install.json` | `bootstrap.py install` | Hashes of installed content, for safe reruns |
| `docs/runs/` | runner, gitignored | One log per check run |

## Task states

| Change | Command | Refused when |
|---|---|---|
| not_started or blocked → active | `start ID` | another task is active or verified; a dependency is not passing; no acceptance or no own check |
| active → verified, or stays active | `verify ID` | the task is not in progress; a check id is undefined; a verify is already running. A changed must-not-change path counts as a failed check |
| verified → verified (review recorded) or active | `review ID --pass` or `--fail` | the task is not verified; its evidence is stale |
| verified → passing | `done ID --proof "N=..."` | evidence is stale; the task needs a review that did not pass on the current files; uncommitted changes outside bookkeeping files; a criterion has no proof; with pull-request delivery, you are not on the task's branch. The task waits until its pull request is merged |
| not_started or active → blocked | `block ID --reason` | — |
| verified or passing → active | `reopen ID --reason` | another task is in progress |
| unfinished → dropped | `drop ID --reason` | the task is passing |

`add`, `edit`, `note`, `show`, `list`, `status`, `validate` and `wrapup` never change a task's state. `edit` list options replace the list; `none` clears it. `add --review` and `edit ID --review on|off` set whether a task needs an independent review. `add --keep` and `edit --keep` set the must-not-change list.

## Checks

```json
{"schemaVersion": 2, "checks": [
  {"id": "lint", "argv": ["npm", "run", "lint"], "required": true, "precommit": true},
  {"id": "unit", "argv": ["npm", "test"], "required": true},
  {"id": "e2e", "argv": ["npx", "playwright", "test"], "timeoutSeconds": 600},
  {"id": "startup", "argv": ["node", "scripts/smoke.mjs"], "wrapup": true}
]}
```

- `argv` runs without a shell. Use `["sh", "-c", "..."]` only for pipes or `&&`.
- `required: true` checks run on every verify and at every wrapup; they catch regressions. Other checks run only for tasks that list them, so a task's own check can target exactly its acceptance.
- `wrapup: true` checks also run at session end, for example a startup smoke test.
- `precommit: true` checks run before every commit through the pre-commit hook. Use only fast checks that read files and do not change them (for example `prettier --check`, not `--write`).
- Optional: `cwd` (default `.`), `timeoutSeconds` (default 900). A timeout kills the check's whole process group.
- Take commands from the repository first (package scripts, Makefile, CI steps). A check whose tool is not installed yet fails with `missing-command`; the task that sets the tool up makes it pass.

| Stack | Typical checks |
|---|---|
| Web app on Node | `npm run lint`; `npx tsc --noEmit`; `npx vitest run`; `npm run build`; `npx playwright test` with `webServer` in the Playwright config, so the test starts and stops the app |
| Node service or library | `npm test` or `node --test`; an HTTP smoke test that listens on port 0 |
| Python | `ruff check .`; `mypy` when configured; `pytest -q` or `python -m unittest` |
| Go | `go vet ./...`; `go test ./...` (use `httptest` for HTTP) |
| Rust | `cargo clippy -- -D warnings`; `cargo test` |

For a web project, every user-visible acceptance criterion gets a browser test. Keep traces or screenshots on failure (Playwright `trace: 'retain-on-failure'`); their paths appear in the check log. Write check failure messages that say what to fix, not only what broke.

## Evidence, must-not-change, and review

`verify` stores each check's outcome, exit code, duration and log path, plus two hashes: the task definition (behavior, acceptance, checks) and the repository files (git-tracked and untracked non-ignored files, or `fingerprintPaths`). `docs/tasks.json`, `docs/install.json`, `docs/runs/` and the lock are excluded, so notes and queue edits never make evidence stale.

- A verified task is stale when its definition or any file changed after verify. `done` refuses it; run `verify` again.
- A passing task is flagged only when its definition changed. Later code changes are normal, and required checks catch regressions. Until the task is reopened and finished, or the definition restored, tasks that depend on it wait.
- For verified tasks, evidence written by harness 1.x counts as stale.
- Files changed by the checks themselves are listed after verify. Ignore generated output in `.gitignore`.
- **Must-not-change.** `start` and `reopen` record the current commit. Entries without spaces that contain `/`, `*` or `.` are file globs: `verify` adds a `keep` result that fails when a matching path changed since that commit. Other entries are shown by `status` and `show` for the agent and the reviewer. Without git the globs are not checked, and `verify` says so.
- **Review.** A review records pass or fail, the reviewer, a summary, and the files hash. `done` accepts only a passing review of the current files, so any change after the review needs a new verify and review. The runner cannot prove the reviewer was independent: use a subagent or a new session that did not write the code.

## Delivery: branch, pull request, merge

`docs/config.json` may set `"delivery": {"mode": "pr", "base": "main", "merge": "squash", "checksWaitSeconds": 90}`. Without it, the runner uses pull requests whenever the repository has an `origin` remote, into the default branch origin reports (else `main`). `"mode": "local"` keeps finished work local.

With pull requests:
- **`start`:** fetches origin. It refuses while the tree has uncommitted work, another task's pull request is not merged, or `origin/<base>` has no `docs/tasks.json` yet (merge the harness first). Otherwise it creates `<type>/<id>-<words>` from `origin/<base>`, where the type comes from `add --type` (feat, fix, refactor, perf, docs, test, build, ci, chore). It also installs the git hooks (see "Git hooks").
- **`verify` and `done`:** refuse on any branch except the task's own.
- **`done`:**
  1. records the task as passing in a commit on the branch, and pushes;
  2. opens the pull request, or finds the open one;
  3. waits for the checks, at most `checksWaitSeconds` per call, so it ends before the 2-minute command limit many agent tools have;
  4. merges with `--match-head-commit`, so only the verified commit can land;
  5. reads the pull request back from GitHub and counts it merged only when GitHub says so;
  6. switches to the base branch, pulls, and deletes the task branch.
- **Failed checks:** the task is active again, with the failing check names and links in a note. Fix, commit, `verify`, `done`.
- **Waiting for merge:** the task stays passing, no other task can start, and `done ID` (without `--proof`) continues. This happens when:
  - checks are still running: run `done ID` again;
  - GitHub needs an approval: tell the user;
  - the base branch uses a merge queue: run `done ID` again later;
  - the branch conflicts with the base branch: `git merge origin/<base>`, then `reopen`, `verify`, `done`.
- **Changes after `done`:** `done ID` refuses to continue when files on the task branch changed since the verified commit. `reopen` and verify again.
- **Closed without merging:** `done ID` stops and says so. Ask the user; `reopen` to change the work, and `drop` it after reopening if it is not wanted.
- **Errors from `gh`** (not logged in, network): `done` stops without merging and prints the error. It never reads an error as "no checks".
- **No checks:** when GitHub reports none, `done` merges. If a workflow in `.github/workflows` runs on `pull_request`, it first waits up to 60 seconds for the checks to appear.
- **Another clone:** until the merge, the queue that shows the task lives on the task branch. In a clone that is on the base branch, `status` lists those task branches and says to switch to one.
- **First push:** when origin has no base branch yet, `start` refuses and prints the one allowed direct push, `HARNESS_BASE_PUSH=1 git push -u origin <base>`, for the harness commit. Bootstrap makes that push, or creates the GitHub repository with `gh repo create --push`. Every task, the walking skeleton included, then goes through a pull request.
- **GitHub CLI:** `gh` must be installed and logged in. Without it, `done` pushes the branch and stops with the fix.

Limits:
- The hooks protect every clone when husky runs them, and otherwise only clones where `start` or `hook install` ran. `--no-verify` skips them. Turn on branch protection for the base branch in the GitHub settings to enforce the rule on the server.
- Merge state is read from `docs/tasks.json` on `origin/<base>`, so that file must be committed.
- Checks from systems outside GitHub Actions that report late can be missed by the no-checks rule; require them in branch protection.

## Git hooks

`start` and `reopen` install two hooks, and `hook install` does the same by hand:
- **pre-commit** runs the checks marked `"precommit": true` and stops the commit when one fails, printing the log tail.
- **pre-push** stops pushes to the base branch when delivery uses pull requests. `HARNESS_BASE_PUSH=1` allows the one direct push of the harness commit.

Where they go:
- **husky runs the hooks** (`core.hooksPath` is `.husky/_` or `.husky`): the runner adds `python3 scripts/harness.py hook pre-commit` to the end of `.husky/pre-commit` and `... hook pre-push` to the top of `.husky/pre-push`, keeping what is there. These files are committed, so every clone that runs `npm install` gets the hooks.
- **no hook manager:** small scripts in this clone's `.git/hooks/`. A hook there that the harness did not write is kept, and `start` prints the line to add to it.
- **another hook manager** in `core.hooksPath`: `start` prints the two lines to add to it.

The runner's own commit of `docs/tasks.json` during `done` skips the hooks, because `verify` already ran the checks.

## Session end: `wrapup`

`wrapup --note "done / next"` runs the required and `wrapup: true` checks, lists debug leftovers in lines added since the last commit (`console.log(`, `debugger`, `breakpoint()`, `pdb.set_trace(`, `binding.pry`, `dbg!(`, `TODO`, `FIXME`, `XXX`; Markdown and text files are skipped), and lists uncommitted work. It exits 1 when a check fails, a leftover is found, or uncommitted work has no note. The note is required while a task is in progress, and it is saved on that task. The result is stored as the last wrapup, and the next `status` shows it.

## When the project grows

- `status` stays short however long the queue gets: the task in progress, three ready tasks, blocked tasks, and the last three notes. `list` hides passing and dropped tasks unless you pass `--all`. Agents never need to open `docs/tasks.json`.
- Keep `docs/PROJECT.md` about the current state: replace rows that changed, and delete closed questions and wrong assumptions after updating what depended on them; git keeps the history. When it passes about 300 lines, move a whole area (for example one product domain) into `docs/<area>.md` and leave a one-line link in PROJECT.md.
- Open `docs/RESEARCH.md` only for scope or domain questions.
- Old logs in `docs/runs/` can be deleted at any time; evidence keeps only paths.
- Within a long session, save the state with `note` when the context is more than half full. After a compaction or restart, `status` restores the task, its last result and the notes.

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
