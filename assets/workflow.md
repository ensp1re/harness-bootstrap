# Development workflow

Run `python3 scripts/harness.py status`, then `show ID`. No installed skill is needed.
Use `COMMAND -h` for options. Checks, review paths and delivery settings live only in `docs/config.json`;
local checks and CI both run `python3 scripts/harness.py check` after installing dependencies.

Done means: the checks pass on the current files, each acceptance line names a passing check,
a required review passed, and the change is committed and delivered.

## Task loop

1. `show ID` prints the task: acceptance, the text of its referenced rows, dependencies and must-not-change list.
2. For new work, `add "behavior" --type fix`. Docs, comments, copy and small fixes need nothing more.
   A behavior change gets 1–5 acceptance lines (`--accept`). Name a check (`--check`) only when the required checks do not prove it.
   Define unclear scope before coding; split independent behaviors into separate tasks.
3. `start ID` creates the task branch in PR mode; explicit local mode keeps the current branch.
   Reproduce a bug before fixing it. Make the smallest change that meets the acceptance lines.
4. `verify ID` runs the task's checks and the required checks that cover the changed files.
   Write proof only after they pass, one per acceptance line: `done ID --proof "1=CHECK: what it showed"`.
   Proof names a check that ran; outside review paths it may be `manual:` with the command you ran and its output.
5. `verify` says when a review is required: the change touches a review path, or the task was added with `--review`.
   Record the proof first with `verify ID --proof ...`; nothing runs again.
   A reviewer that did not write the code reads `show ID` and the diff of those files, then records
   `review ID --pass|--fail --summary "findings"`. It fails the task only for wrong behavior, a security or data problem,
   or proof that does not hold, each with a file and line. Style and wording are notes, not failures.
   After a failed review, send the fix to the same reviewer. After three failed reviews, stop and ask the user.
6. Commit and run `done ID`, with the proof when the task has acceptance lines. `status` says whether commit and push need approval, and who merges.
   PR delivery pushes and opens a PR. Missing CI is pending; skipped, cancelled or failed CI fails.
   Repeat `done ID` to resume pending delivery or confirm an owner merge.
7. Before stopping, `wrapup --note "result; next step"`. Fix failures or report what remains.

Fix failed checks; do not bypass hooks. Input changes during verification fail the run.
A later file edit needs `verify` again; a review stays valid until a file it covered changes.
`passing` with a pending PR does not mean merged; a task that does not depend on it can start, here or in another worktree.
Local delivery is an explicit user choice.
After three failures without a new approach, record attempts and `block ID --reason "..."`.
Use `edit`, `reopen`, and `drop` to reconcile scope while keeping task history and authorization.
Do not begin unrelated queued work unless the user requested it.

## What you add

- **Facts.** Open a file before stating a fact about it. Ask the user only when two readings of the task lead to
  different work; otherwise choose, say which, and continue. Research primary sources when the answer changes the work:
  one short round, at most 5 searches. A bigger question blocks the task.
- **Tests.** Add none on your own. Add or change a test only when the task asks for it, when it reproduces a reported bug
  (see it fail before the fix), or when the change is on a review path. A test must fail when the behavior breaks:
  none that repeat the implementation, constants, copy or layout.
- **Comments.** None by default. Keep a comment only for a reason the code cannot show, such as an outside quirk or a
  safety rule. Do not describe what the code does, narrate the change, or copy the style of nearby comments.
- **Scope.** No abstraction, option, file or document the task does not need.

## Where information belongs

| Topic | Owner |
|---|---|
| Project scope, requirements, decisions (D-), assumptions, questions | `docs/PROJECT.md`, when present |
| Research sources | `docs/RESEARCH.md`, when needed |
| Workflow | this file |
| Checks, review paths and delivery authorization | `docs/config.json` |
| Tasks, proof, reviews, notes | `docs/tasks/`, one file per task, through runner commands |
| Logs of failed checks, command timings | ignored `docs/runs/` |

Keep one canonical decision register in PROJECT.md; link to it from other docs. Keep it about the current state.
A task adds a row only for a product rule the code cannot show. The docs check fails a file over 40,000 bytes:
move one area into `docs/<area>.md` and leave a link.
Use unique IDs and working local links. Clearly separate current behavior from planned work.

## Checks and reconciliation

- Commands use argv arrays, without a shell. Prefer `cwd` and `npm/pnpm/yarn/bun run SCRIPT`
  for one package. Missing scripts must fail; avoid optional or recursive script commands.
- A check with `paths` runs only when a changed file matches, and is not run again while those files are unchanged.
  `paths` must list every file the check reads. Leave it off integration and environment-dependent checks: they always run.
- Parallel browser tests must start their own server on dynamic ports and close it afterward.
- `--keep` globs are enforced against the task's starting commit. Behavioral constraints need tests or review.
- `check ID` runs one declared check; `check` runs the whole required set. CI on a pull request may add `--since origin/BASE`.
- `wrapup` runs only checks marked `wrapup`; it does not repeat `verify`.
- Reinstall with a dry run first. Merge reported conflicts by hand; preserve user edits,
  removed instructions, completed records and delivery authorization. Never reset state to ease an upgrade.
