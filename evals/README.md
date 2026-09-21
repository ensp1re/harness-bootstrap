# Evaluating harness-bootstrap

## 1. Deterministic checks (every change)

```sh
python3 scripts/check_bundle.py
python3 -m unittest discover -s evals -p 'test_*.py'
```

- `check_bundle.py` checks four things: required files exist, the SKILL.md frontmatter is valid, every runner command the docs mention exists, and local links resolve.
- `test_harness.py` runs the runner and the installer as black boxes in temporary repositories:
  - runner cases: the full task loop, the one-task limit, dependencies, stale evidence, interrupted verify, a lock left by a dead process, a missing command, timeouts, invalid state files, `drop`, repeated failures, 1.x state, required reviews, must-not-change paths, `wrapup`, and `list` hiding finished tasks;
  - delivery cases, against a bare local `origin` and a fake `gh`: merge through a pull request, failed checks, a pull request waiting for merge (with changes after `done` and a clone on the base branch), `gh` errors, a merge queue, a closed pull request, a merge that `gh` reports as failed after merging, `start` before the harness is merged, the first push to an empty remote, a blocked direct push, and `verify` outside the task branch;
  - installer cases: existing content is kept, reruns are safe, conflicts are reported, dry runs write nothing, and `inspect` output.

## 2. Agent scenarios (substantial changes)

Build each fixture fresh in a scratch directory, never inside this repository. Give the agent only the skill path and the prompt, never the checks below. Run the old and new skill versions with the same model on the same fixture.

| ID | Starting repository | Prompt (short) | Passes when |
|---|---|---|---|
| a | empty directory | "website for my bouldering gym: new problems each week, members log sends" | all of: tier 1+ recorded; 3+ alternatives with dated sources; assumptions with tests; at most 3 questions, each with a default; R- rows with Given/When/Then and a check; F001 is a walking skeleton; `validate` passes; no feature code |
| b | empty git repository | csvdiff CLI with the exit codes, BOM, and duplicate-key rules spelled out | all of: tier 0; no RESEARCH.md; each stated rule is in the acceptance; checks use stdlib tools only; no questions |
| c | small Node site with tests, CI, AGENTS.md, and a stale README | "set up the harness; next up: dietary tags and a cap per category" | all of: AGENTS.md rules kept; real commands in config; stale README command reported; tasks for both features; baseline check result reported; CI file unchanged |
| d | c after bootstrap: one task active, last verify failed, a note | "pick up where the last session left off" | all of: the agent names the task and the failing check from `status` before opening other files; it finishes with `done --proof`; at most one task in progress |
| e | c after bootstrap, with an assumption that names are public | "names must not be shown publicly any more" | all of: the assumption row is marked invalid and a decision row added; affected tasks are edited, reopened, or dropped; new tasks queued; PROJECT.md and the queue agree |
| f | c after bootstrap, with user edits, one passing task, and a new Python script with tests | "run the bootstrap again and include the Python tests" | all of: user edits byte-identical; task IDs and evidence kept; new check added; `validate` passes |

For every run, record:
- total tokens and duration, as reported by the agent runner;
- files created and questions asked;
- the steps taken before the first useful action;
- pass or fail for each check, with the file or output that shows it.

One run per scenario is a single observation. Report it as such and do not average it into a claim.

## 3. Context cost without a model

For each path (start a project, resume, implement a task, investigate a failure, change scope), list the files and command outputs an agent must read, and measure them in bytes. Token counts are estimated as bytes/4 and labeled as estimates.

Results: [results/REPORT.md](results/REPORT.md).
