# Harness reference

Read this when choosing checks, rerunning bootstrap, migrating a 1.x project, or debugging the runner. The runner is `scripts/harness.py`, copied from `assets/harness.py` (Python 3.8+, standard library only). Commands print short text. Exit 0 means success, 1 means refused or checks failed, 2 means invalid input or unreadable state. `python3 scripts/harness.py -h` lists the commands.

## Files in a bootstrapped repository

| File | Written by | Purpose |
|---|---|---|
| `AGENTS.md` | project part: agent and user; block between the harness markers: `bootstrap.py install` | Loaded by the coding agent every session: short entry point, project rules, link to workflow |
| `docs/workflow.md` | installer, then user | Task loop, proof, review, delivery authorization and topic map |
| `docs/PROJECT.md` | agent and user | Users, scope, domain, R-/D-/A-/Q- rows |
| `docs/RESEARCH.md` | agent, discovery tier 1+ | V- facts with sources, alternatives, what was not researched |
| `docs/ARCHITECTURE.md` | agent, only with 2+ deployable parts or boundaries the code does not make obvious | Components, data flow, ownership |
| `docs/tasks/F001.json` | runner only | One file per task from `start` on: state, must-not-change list, evidence, reviews, notes. Two branches never edit the same file |
| `docs/config.json` | agent | Checks, review paths, delivery settings, optional `fingerprintPaths` |
| `docs/install.json` | `bootstrap.py install` | Hashes of installed content, for safe reruns |
| `scripts/check-docs.py` | installer | Local Markdown links and canonical decision IDs; included in new check registries |
| `.agents/skills/*/SKILL.md` | installer, then user | Coding rules agents read before writing, changing, debugging, testing or reviewing code; Codex loads them directly |
| `.claude/skills/*` | installer with `--claude` | Links to `.agents/skills/*`, because Claude Code reads only `.claude/skills` |
| `docs/runs/` | runner, gitignored | Logs of checks that did not pass; `events.jsonl`, one line per command with its duration |

## Task states

| Change | Command | Refused when |
|---|---|---|
| not_started or blocked → active | `start ID` | another task is active or verified; a dependency is not passing |
| active → verified, or stays active | `verify ID` | the task is not in progress; a check id is undefined; no check covers the change; a verify is already running. A changed must-not-change path or an input changed during checks fails verification |
| verified → verified (review recorded) or active | `review ID --pass` or `--fail` | the task is not verified; its evidence is stale |
| verified → passing | `done ID --proof "N=..."` | evidence is stale; the task needs a review and none passed on the files it covers; uncommitted changes outside bookkeeping files; a criterion has no proof naming an executed passing check; with pull-request delivery, you are not on the task's branch. The task waits until its pull request is merged |
| not_started or active → blocked | `block ID --reason` | — |
| verified or passing → active | `reopen ID --reason` | another task is in progress |
| unfinished → dropped | `drop ID --reason` | the task is passing |

`add`, `edit`, `note`, `show`, `list`, `status`, `validate` and `wrapup` never change a task's state. `edit` list options replace the list; `none` clears it. Review paths in `docs/config.json` decide when a task needs an independent review; `add --review` and `edit ID --review on|off` require one for a task that touches none. `add --keep` and `edit --keep` set the must-not-change list.

## Checks

```json
{"schemaVersion": 2, "checks": [
  {"id": "lint", "argv": ["npm", "run", "lint"], "required": true, "precommit": true},
  {"id": "unit", "argv": ["npm", "run", "test"], "required": true,
   "paths": ["src/*", "test/*", "package.json", "package-lock.json"]},
  {"id": "e2e", "argv": ["npx", "playwright", "test"], "timeoutSeconds": 600},
  {"id": "startup", "argv": ["node", "scripts/smoke.mjs"], "wrapup": true}
],
 "review": {"paths": ["src/billing/*", "migrations/*"]}}
```

- `python3 scripts/harness.py check` runs required checks locally and in CI; `check ID` runs selected checks without editing task state. No required checks is an error for `check`. `check --since REF` is for pull requests: it skips the required checks whose `paths` match no file changed since REF, and runs all of them when REF cannot be read. Keep one full `check` on every push to the base branch.
- `"taskLines": 400` (optional, top level): `verify` says so when a task changed more lines than that, and suggests a split. It refuses nothing.
- The installed docs check fails a Markdown file over 40,000 bytes and says to move one area into its own file.
- Check IDs must be unique safe names (`keep` is reserved). Flags must be booleans, timeouts positive, and cwd/package paths contained in the repository. Package script checks resolve the real manifest and fail when the script is absent. Prefer `cwd` plus `pnpm run e2e` over filters or optional/recursive commands.
- `argv` runs without a shell. Use `["sh", "-c", "..."]` only for pipes or `&&`.
- `required: true` checks run on every verify and in CI; they catch regressions. Other checks run only for tasks that list them with `--check`.
- `paths` (file globs; `*` also matches `/`): a required check with `paths` runs in `verify` only when a file the task changed matches, and is not run again while the matching files and the config are as they were when it passed. List every file the check reads, manifests and lockfiles included. A check without `paths` always runs; keep it that way for integration and environment-dependent checks. `check` runs every required check; `check --since REF` skips the ones whose `paths` the change does not touch.
- `wrapup: true` checks run at session end, for example a startup smoke test. `wrapup` runs no other check.
- `precommit: true` checks run before every commit through the pre-commit hook. Use only fast checks that read files and do not change them (for example `prettier --check`, not `--write`).
- Optional: `cwd` (default `.`), `timeoutSeconds` (default 900). A timeout kills the check's whole process group. Do not cache integration or environment-dependent test outcomes.
- Take commands from the repository first (package scripts, Makefile, CI steps). A check whose tool is not installed yet fails with `missing-command`; the task that sets the tool up makes it pass.

| Stack | Typical checks |
|---|---|
| Web app on Node | `npm run lint`; `npx tsc --noEmit`; `npx vitest run`; `npm run build`; `npx playwright test` with `webServer` in the Playwright config, so each test starts and stops its own app on a dynamic port |
| Node service or library | `npm test` or `node --test`; an HTTP smoke test that listens on port 0 |
| Python | `ruff check .`; `mypy` when configured; `pytest -q` or `python -m unittest` |
| Go | `go vet ./...`; `go test ./...` (use `httptest` for HTTP) |
| Rust | `cargo clippy -- -D warnings`; `cargo test` |

A web project gets one browser smoke test in the walking skeleton; add browser tests only for flows where a break is costly. Keep traces or screenshots on failure (Playwright `trace: 'retain-on-failure'`); their paths appear in the check log. Write check failure messages that say what to fix, not only what broke.

## Evidence, must-not-change, and review

`verify` stores each check's outcome, exit code, duration and, when it did not pass, its log path, plus versioned hashes of task constraints (behavior, acceptance, checks, keep, dependencies, refs, review, spec, plan and starting commit), config, and repository files. Git-tracked and untracked non-ignored inputs always count; `fingerprintPaths` adds ignored inputs. Config and docs cannot be excluded. `docs/tasks/`, `docs/install.json`, `docs/runs/` and the lock are excluded, so unrelated notes and queue edits do not make evidence stale. Edits to the current task constraints do.

- A verified task is stale when its definition or any file changed after verify. `done` refuses it; run `verify` again.
- A passing task is flagged only when its definition changed. Later code changes are normal, and required checks catch regressions. Until the task is reopened and finished, or the definition restored, tasks that depend on it wait.
- For verified tasks and pending delivery, evidence older than version 3 counts as stale. Completed v1/v2 evidence is preserved; v2 definitions use the original v2 hash fields.
- Input changes during checks fail verification. Ignore disposable generated output in `.gitignore`; verify again after intentional changes.
- **Must-not-change.** `start` and `reopen` record the current commit. Entries without spaces that contain `/`, `*` or `.` are file globs: `verify` adds a `keep` result that fails when a matching path changed since that commit. Other entries are shown by `status` and `show` for the agent and the reviewer. Missing git or an unreadable starting commit fails verification when path constraints exist.
- **Review.** A task needs one when it changed a file on `review.paths`, or was added with `--review`. A review records pass or fail, the reviewer, a summary, and hashes of the files it covers, config, task constraints and acceptance proof. It covers the changed files on review paths, or, for a `--review` task that changed none, every changed file. Edits to other files need a new `verify` but keep the review. Supply proof after the checks passed, with `verify --proof "1=check-id: evidence"` (on a verified task this records the proof and runs nothing) or `review --proof`; reviewers judge whether the named passing checks prove acceptance. Outside review paths a line may carry `manual:` proof, the command the agent ran and its output. After a failed review the same reviewer checks the fix; after three failed reviews the runner says to ask the user. The runner cannot prove the reviewer was independent: use a subagent or a new session that did not write the code.

## Delivery: branch, pull request, merge

`docs/config.json` may set `"delivery": {"mode": "pr", "base": "main", "merge": "squash", "checksWaitSeconds": 90}`. Without it, the runner requires pull-request delivery and an `origin` remote, into the default branch origin reports (else `main`). `"mode": "local"` keeps finished work local. In local mode the runner does not coordinate branches: two branches that each add a task give it the same id, so work on one branch. There a task that is blocked and started again counts every commit made since it first started as its own change, so its checks and review can cover more than it changed. `"autoPublish": true` records that agents may commit, push and open pull requests without asking each time; `status` prints it. Merging still needs `autoMerge`.

With pull requests:
- **`start`:** fetches origin. It refuses while the tree has uncommitted work, another task is active or verified in this working tree, a dependency is not merged, or `origin/<base>` has no `docs/config.json` yet (merge the harness first). A pending pull request of another task does not block it. It reconciles the local and fetched task queues against their common ancestor, preserving independent changes and refusing conflicts. Otherwise it creates `<type>/<id>-<words>` from `origin/<base>`, where the type comes from `add --type` (feat, fix, refactor, perf, docs, test, build, ci, chore). It also installs the git hooks (see "Git hooks").
- **`verify` and `done`:** refuse on any branch except the task's own.
- **`done`:**
  1. records the task as passing in a commit on the branch, and pushes;
  2. opens the pull request, or finds the open one. Its title is the first task commit's subject (capped at 72 characters); its body is the commit bodies, optional commit list when there are several, and a short test plan with the checks that passed;
  3. waits for the checks, at most `checksWaitSeconds` per call, so it ends before the 2-minute command limit many agent tools have;
  4. waits for the owner to merge; only explicitly authorized `autoMerge: true` requests merge with `--match-head-commit`;
  5. reads the pull request back from GitHub and counts it merged only when GitHub says so;
  6. switches to the base branch, pulls, and deletes only the exact branch head GitHub confirmed merged. Local queue edits or later commits block cleanup until reconciled.
- **Failed checks:** the task is active again, with the failing check names and links in a note. Fix, commit, `verify`, `done`.
- **Waiting for merge:** the task stays passing, tasks that depend on it wait, and `done ID` (without `--proof`) continues. This happens when:
  - checks are still running: run `done ID` again;
  - GitHub needs an approval: tell the user;
  - the base branch uses a merge queue: run `done ID` again later;
  - the branch conflicts with the base branch: `git merge origin/<base>`, then `reopen`, `verify`, `done`.
- **Changes after `done`:** resuming rechecks current files, config, task constraints, review and evidence version, including uncommitted edits. `reopen` and verify again.
- **Closed without merging:** `done ID` stops and says so. Ask the user; `reopen` to change the work, and `drop` it after reopening if it is not wanted.
- **Errors from `gh`** (not logged in, network): `done` stops without merging and prints the error. It never reads an error as "no checks".
- **No checks:** delivery stays pending. Every reported check must pass; skipped, cancelled, unknown and failed results fail delivery.
- **Another clone or worktree:** until the merge, a task's record lives on its branch. `status` lists task branches this working tree does not show: those checked out in another worktree as in progress there, the others with the command to switch to one. `start` refuses a task that already has a branch elsewhere.
- **Parallel work:** each worktree works on one task. Tasks wait in the repository's shared git folder until `start`, so every worktree sees the same queue and `git add -A` cannot take a queued task into another task's branch. Ids come from the tasks here, on origin's base branch and in branch names; a queued task whose number another clone used first is renumbered at `start`, with a note.
- **First push:** when origin has no base branch yet, `start` refuses and prints the one allowed direct push, `HARNESS_BASE_PUSH=1 git push -u origin <base>`, for the harness commit. Bootstrap makes that push, or creates the GitHub repository with `gh repo create --push`. Every task, the walking skeleton included, then goes through a pull request.
- **GitHub CLI:** `gh` must be installed and logged in. Without it, `done` pushes the branch and stops with the fix.

Limits:
- The hooks protect every clone when husky runs them, and otherwise only clones where `start` or `hook install` ran. `--no-verify` skips them. Turn on branch protection for the base branch in the GitHub settings to enforce the rule on the server.
- Merge state is read from `docs/tasks/` on `origin/<base>`.
- Tasks queued after the harness reached the base branch are local to this clone until they start. Tasks queued at bootstrap are committed with the harness.
- Late external check suites may appear after other checks pass. Require every mandatory suite in branch protection; the runner cannot infer which unreported external suites should exist.

## Git hooks

`start` and `reopen` install two hooks, and `hook install` does the same by hand:
- **pre-commit** runs the checks marked `"precommit": true` and stops the commit when one fails, printing the log tail.
- **pre-push** stops pushes to the base branch when delivery uses pull requests. `HARNESS_BASE_PUSH=1` allows the one direct push of the harness commit.

Where they go:
- **husky runs the hooks** (`core.hooksPath` is `.husky/_` or `.husky`): the runner adds `python3 scripts/harness.py hook pre-commit` to the end of `.husky/pre-commit` and `... hook pre-push` to the top of `.husky/pre-push`, keeping what is there. These files are committed, so every clone that runs `npm install` gets the hooks.
- **no hook manager:** small scripts in this clone's `.git/hooks/`. A hook there that the harness did not write is kept, and `start` prints the line to add to it.
- **another hook manager** in `core.hooksPath`: `start` prints the two lines to add to it.

The runner's delivery commit runs hooks too. Corrupt harness state fails hooks instead of silently disabling them.

## Session end: `wrapup`

`wrapup --note "done / next"` runs the `wrapup: true` checks, lists debug leftovers in lines added since the last commit (`console.log(`, `debugger`, `breakpoint()`, `pdb.set_trace(`, `binding.pry`, `dbg!(`, `TODO`, `FIXME`, `XXX`; Markdown and text files are skipped; ordinary console output under scripts/tests/bin and test modules is allowed), and lists uncommitted work. It exits 1 when a check fails, a leftover is found, or uncommitted work has no note. The note is required while a task is in progress, and it is saved on that task. The result is stored in this working tree (`docs/runs/wrapup.json`, ignored), and the next `status` here shows it; the note itself is also saved on the task in progress, which travels with its branch.

## When the project grows

- `status` stays short however long the queue gets: the task in progress, three ready tasks, blocked tasks, and the last three notes. `list` hides passing and dropped tasks unless you pass `--all`. Agents never need to open the files in `docs/tasks/`. A finished task's file is written once and not touched again, so the queue adds no churn as it grows.
- Keep `docs/PROJECT.md` about the current state: replace rows that changed, and delete closed questions and wrong assumptions after updating what depended on them; git keeps the history. When it passes about 300 lines, move a whole area (for example one product domain) into `docs/<area>.md` and leave a one-line link in PROJECT.md.
- Open `docs/RESEARCH.md` only for scope or domain questions.
- `docs/runs/` holds only logs of checks that did not pass and `events.jsonl`; both can be deleted at any time.
- Within a long session, save the state with `note` when the context is more than half full. After a compaction or restart, `status` restores the task, its last result and the notes.

## Recovery

- **Interrupted verify:** `status` says "verify interrupted"; run `verify` again.
- **Lock:** one command writes at a time across the worktrees of one repository. A command that finds the lock taken waits up to 30 seconds (`HARNESS_LOCK_SECONDS`), then refuses. The system frees the lock when the command that holds it ends.
- **Changes during a running verify:** if the task was blocked, dropped or re-verified meanwhile, the running verify discards its result. Task-constraint, config and file mutations fail the run.
- **Invalid JSON or schema:** commands exit 2 without writing. Fix the file, then `validate`.

## Rerunning bootstrap

Run `python3 <skill>/scripts/bootstrap.py install ROOT` again, with `--dry-run` first on a repository you did not bootstrap. It updates `scripts/harness.py`, `docs/workflow.md` and the AGENTS.md block only when they are unchanged since the last install, and reports `conflict` otherwise. Existing registries are kept: add the docs check through normal configuration review if upgrading. It never changes existing task files, `docs/config.json`, or other user docs. Removed managed instructions stay removed across repeated installs. Malformed markers, unreadable files and symlink destinations are conflicts. Existing delivery settings and explicit authorization remain unchanged; do not infer `autoMerge` from old defaults.

## Migrating from harness-bootstrap 1.x

1. Run `install --dry-run`, then `install`, and merge the upgraded runner into the base branch before starting a task: `start` refuses while the base branch has the earlier runner. An old runner (`scripts/harness-runner.mjs`, `cmd/harness`) is reported, not deleted. A 1.x runner at `scripts/harness.py` shows as a conflict: move it aside and rerun.
2. A `docs/tasks.json` of version 1 or 2 is read as is. The first write turns it into one file per task under `docs/tasks/` and removes it; with pull requests that change reaches the base branch through the first task's pull request, so merge open task branches first, and merge that first pull request before starting a second task: `start` refuses until then. A task that another clone queued and never committed stays in that clone's old `docs/tasks.json`: after pulling the upgrade, queue it again with `add` and delete the old file. Verified tasks need `verify` again; passing tasks stay passing. Archived tasks in `docs/archive/ID.json` still satisfy dependencies.
3. Move decisions and next steps that are still true from `docs/handoff.json`, `docs/SESSION_HANDOFF.md` and `docs/PLAN.md` into D- rows or task notes, then delete those files. `status` reminds you while they exist.
4. RELIABILITY, SECURITY, TECH_DEBT and CHANGE documents are no longer generated. Keep the ones with real project rules and link them from AGENTS.md; open debt items become tasks.
5. Delete the old runner's instructions from AGENTS.md, keep your own project notes, and commit.
