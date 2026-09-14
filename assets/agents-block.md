<!-- harness:start (installed by harness-bootstrap; keep project notes outside these markers) -->
## Harness

Run `python3 scripts/harness.py status` before anything else in a session. It prints the task in progress, its acceptance criteria and checks, the last verify result with its log path, recent notes, and the next step, so you do not need to read `docs/tasks.json`, old run logs, or the runner's source. `python3 scripts/harness.py <command> -h` explains any command. Change `docs/tasks.json` only through the runner.

- `docs/PROJECT.md`: users, scope, domain terms and rules, requirements (R-), decisions (D-), assumptions (A-), open questions (Q-). Read the rows a task's refs name, not the whole file.
- `docs/RESEARCH.md`, if present: cited facts (V-) behind the decisions. Open it for scope or domain questions only.
- `docs/config.json`: the checks `verify` runs. `docs/runs/`: check logs, not committed.

Task loop, one task at a time:
1. `start ID` for the task `status` suggests.
2. For each acceptance criterion, write or extend a test and see it fail. Make the smallest change that passes. Run the relevant check directly while you work.
3. `verify ID` runs the task's checks and the required checks and records the result. If it fails, read the printed log tail, fix the cause, verify again. After 3 failed verifies with no new idea, `note` what you tried and `block ID --reason "..."`.
4. Commit, then `done ID --proof "1=<test that proves criterion 1>" ...`. `done` refuses stale evidence and uncommitted changes.
5. Take the next ready task unless the user limited the work.

Stay in scope. Work you notice along the way becomes `add "<behavior>" --accept "..." --check ID`; do not fold it into the current change.

When scope or an assumption changes: update its rows in `docs/PROJECT.md`, find what depends on them with `grep -n "<ID>" docs/PROJECT.md` and `list` (each task shows its refs), then `edit` affected tasks (their evidence goes stale), `reopen` passing work that must change, `drop ID --reason "..."` work that is no longer wanted, and `add` new work.

Before you stop: `note ID "<what is done, what is next>"` on the task in progress. Push or open pull requests only when the user asked for it.
<!-- harness:end -->
