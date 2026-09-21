<!-- harness:start (installed by harness-bootstrap; keep project notes outside these markers) -->
## Harness

Run `python3 scripts/harness.py status` before anything else in a session, and again whenever your context was compacted or restarted. It prints the task in progress with its branch, acceptance, checks and must-not-change list, the last verify and review results with log paths, recent notes, pull requests waiting for merge, how the last session ended, and the next step, so you do not need to read `docs/tasks.json`, old run logs, or the runner's source. `python3 scripts/harness.py <command> -h` explains any command.

- `docs/PROJECT.md`: users, scope, domain terms and rules, requirements (R-), decisions (D-), assumptions (A-), open questions (Q-). Read the rows a task's refs name, not the whole file.
- `docs/RESEARCH.md`, if present: cited facts (V-) behind the decisions. Open it for scope or domain questions only.
- `docs/config.json`: the checks `verify` and `wrapup` run, and how work is delivered. `docs/runs/`: check logs, not committed.

**Every change goes through a pull request.** After bootstrap, the base branch changes only by merging a task's pull request. Never commit to it or push it directly; the runner blocks that push. Each new feature, fix or other change, even one line, is a task (`add "<behavior>" --type fix ...`) built on its own branch.

**Definition of done.** A task is done only when every acceptance line is proven by a test or check that passed in `verify` together with the required checks, nothing on its must-not-change list changed, an independent review passed if the task asks for one, and `done ID --proof` merged its pull request after the checks passed. The runner refuses `done` until these hold.

Task loop, one task at a time:
1. `start ID` for the task `status` suggests. It switches you to the task's own branch, cut from the latest base branch.
2. For each acceptance line, write or extend a test and see it fail. Make the smallest change that passes. Run the relevant check directly while you work.
3. Missing information? If a search can answer it, use at most 5 searches on primary sources, add the facts as V- rows (URL, date) and the choice as a D- row, `edit` the acceptance if it changed, and continue. If only the user can answer, `block ID --reason "question: ..."` and take another ready task.
4. `verify ID`. On failure, read the printed log tail, fix the cause, verify again. After 3 failed verifies with no new idea, `note` what you tried and `block` the task.
5. Task marked for review: someone with fresh context (a subagent or a new session that did not write the code) reads `show ID` and `git diff`, then records `review ID --pass` or `--fail` with `--summary "findings"`. A failed review returns the task to step 2.
6. Commit on the task branch, then `done ID --proof "1=<test for line 1>" ...`. It pushes the branch, opens the pull request, waits up to 90 seconds for the checks, merges, and returns you to the base branch. If checks fail, the task is active again: fix, commit, verify, `done`. If checks are still running, run `done ID` again. If the merge needs a person's approval or the pull request was closed, tell the user; do not start other work around it.
7. Take the next ready task unless the user limited the work.

Stay in scope: other work you notice becomes `add "<behavior>" --accept "..." --check ID`; do not fold it into the current change.

New feature requests and fixes:
- Small and clear (one behavior whose Given/When/Then you can write without guessing): add an R- row to `docs/PROJECT.md`, then `add` the task with `--type`, `--accept`, `--check`, `--ref R-n`, and `--keep` for what must not change.
- Large or unclear, or touching money, personal data or security: define it before building. Use the harness-bootstrap skill if it is installed; otherwise ask the user at most 3 questions with a recommended default each, record the answers as D-, A- or Q- rows, and split the feature into tasks.
- If a task is in progress, new work waits in the queue. If the user wants it first, `block` the current task with `--reason "paused for F0NN"`.

When scope or an assumption changes: update its rows in `docs/PROJECT.md` (replace outdated rows; git keeps the history), find what depends on them with `grep -n "<ID>" docs/PROJECT.md` and `list`, then `edit` affected tasks (their evidence goes stale), `reopen` passing work that must change, `drop ID --reason "..."` work that is no longer wanted, and `add` new work. Doc changes also reach the base branch through a pull request: make them on the branch of the task they belong to, or queue a `--type docs` task for them.

Keep context small: use `status` and `show` instead of state files, read log tails, and open only the rows a task needs. When your context is more than half full, `note ID "<done / next>"` so a compaction or restart loses nothing. Before you stop, run `wrapup --note "<done / next>"`: it runs the required checks, looks for debug leftovers and uncommitted work, and records how the session ended. Fix what it reports, or leave the report for the next session.
<!-- harness:end -->
