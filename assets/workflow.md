# Development workflow

Run `python3 scripts/harness.py status`, then `show ID`. No installed skill is needed.
Use `COMMAND -h` for options. Check commands live only in `docs/config.json`;
local checks and CI both run `python3 scripts/harness.py check` after installing dependencies.
The registry must include required regression checks. Add task-specific checks for acceptance.

## Task loop

1. Read the task's acceptance, refs, dependencies and must-not-change list.
2. For clear new work, `add "behavior" --type fix --accept "..." --check CHECK`.
   Use existing requirement refs when relevant. Small fixes need no new spec or decision document.
   Define unclear scope before coding; split independent behaviors into separate tasks.
3. `start ID` creates the task branch in PR mode; explicit local mode keeps the current branch. Reproduce bugs, make the smallest fix, run its checks.
4. `verify ID --proof "1=CHECK: evidence" ...` runs the task and required checks.
   Proof must name executed passing checks. It explains why each acceptance criterion is met.
5. When review is required, a fresh reviewer reads `show ID`, the full task diff and proof.
   They judge whether checks cover acceptance and constraints, then record
   `review ID --pass|--fail --summary "findings"`. Checks alone cannot judge relevance.
6. With authorization to commit and publish, commit and run `done ID`.
   PR delivery pushes and opens a PR. Missing CI is pending; skipped, cancelled or failed CI fails.
   Merge requires the owner's action or explicit `delivery.autoMerge: true` authorization.
   Repeat `done ID` to resume pending delivery or confirm an owner merge.
7. Before stopping, `wrapup --note "result; next step"`. Fix failures or report what remains.

Fix failed checks; do not bypass hooks. Input changes during verification fail the run.
Later source, config or task-constraint edits require fresh verification and review.
`passing` with a pending PR does not mean merged. Local delivery is an explicit user choice.
After three failures without a new approach, record attempts and `block ID --reason "..."`.
Use `edit`, `reopen`, and `drop` to reconcile scope while keeping task history and authorization.
Do not begin unrelated queued work unless the user requested it.

## Where information belongs

| Topic | Owner |
|---|---|
| Project scope, requirements, decisions (D-), assumptions, questions | `docs/PROJECT.md`, when present |
| Research sources | `docs/RESEARCH.md`, when needed |
| Workflow | this file |
| Check commands and delivery authorization | `docs/config.json` |
| Tasks, proof, reviews, session notes | `docs/tasks.json`, through runner commands |
| Code and tools | project source and `scripts/` |
| Regression scenarios | `tests/` |
| Disposable check logs | ignored `docs/runs/` |

Keep one canonical decision register in PROJECT.md; link to it from other docs.
Use unique IDs and working local links. Clearly separate current behavior from planned work.
Read only the task's referenced rows and relevant code. Ask about material uncertainty;
research primary sources when needed. Keep small tasks small.

## Checks and reconciliation

- Commands use argv arrays, without a shell. Prefer `cwd` and `npm/pnpm/yarn/bun run SCRIPT`
  for one package. Missing scripts must fail; avoid optional or recursive script commands.
- Run integration and environment-dependent tests fresh. Cache dependencies, not their outcomes.
- Parallel browser tests must start their own server on dynamic ports and close it afterward.
- `--keep` globs are enforced against the task's starting commit. Behavioral constraints need tests or review.
- `check ID` runs one declared check; `check` runs the required set, including in CI.
- `verify` may omit proof while debugging. Supply proof before review or with `done --proof`.
- Completed legacy evidence remains historical. Pending legacy delivery must be reopened and verified again.
- Reinstall with a dry run first. Merge reported conflicts by hand; preserve user edits,
  removed instructions, completed records and delivery authorization. Never reset state to ease an upgrade.
