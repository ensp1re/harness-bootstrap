# Evaluating harness-bootstrap

## 1. Deterministic checks (every change)

```sh
python3 assets/harness.py check
# Runs check_bundle.py, unittest tests (including generated probes), and evaluate.py mutations.
```

- `check_bundle.py` checks four things: required files exist, the SKILL.md frontmatter is valid, every runner command the docs mention exists, and local links resolve.
- `test_harness.py` runs the runner and the installer as black boxes in temporary repositories:
  - runner cases: the full task loop, the one-task limit, dependencies, stale evidence, interrupted verify, a lock left by a dead process, a missing command, timeouts, invalid state files, `drop`, repeated failures, 1.x state, required reviews, must-not-change paths, `wrapup`, and `list` hiding finished tasks;
  - delivery cases, against a bare local `origin` and a fake `gh`: merge through a pull request, failed checks, a pull request waiting for merge (with changes after `done` and a clone on the base branch), `gh` errors, a merge queue, a closed pull request, a merge that `gh` reports as failed after merging, `start` before the harness is merged, an empty remote (one direct push of the harness, then pull requests), a blocked direct push and its override, and `verify` outside the task branch;
  - hook cases: the pre-commit hook blocks a commit while a `precommit` check fails, and husky projects get the hook lines in their `.husky/` files;
  - installer cases: existing content is kept, reruns are safe, conflicts are reported, dry runs write nothing, and `inspect` output.

`python3 scripts/measure.py [--runner PATH] [--flag-review]` counts what four scripted tasks cost under a runner: commands, refusals, check runs and reviews. Run it on the previous runner and on the changed one; a change that adds a gate must show what the gate costs.

Deterministic probes in `tests/test_generated.py` install a standalone fixture, execute its registry, verify proof/review, preserve legacy evidence and test repeated reconciliation. `scripts/evaluate.py` injects six false-success bugs into disposable copies and requires assertion failures from the matching probes. Fixtures use `TMPDIR` when supplied.

## 2. Agent scenarios (substantial changes)

Build each fixture fresh in a scratch directory, never inside this repository. Give the agent only the skill path and the prompt, never the checks below. Run the old and new skill versions with the same model on the same fixture.

| ID | Starting repository | Prompt (short) | Passes when |
|---|---|---|---|
| a | empty directory | "website for my bouldering gym: new problems each week, members log sends" | all of: tier 1+ recorded; 3+ alternatives with dated sources; assumptions with tests; at most 3 questions, each with a default; R- rows with Given/When/Then and a check; F001 is a walking skeleton; `validate` passes; no feature code |
| b | empty git repository | csvdiff CLI with the exit codes, BOM, and duplicate-key rules spelled out | all of: tier 0; no RESEARCH.md; each stated rule is in the acceptance; checks use stdlib tools only; no questions |
| c | small Node site with tests, CI, AGENTS.md, and a stale README | "set up the harness; next up: dietary tags and a cap per category" | all of: AGENTS.md rules kept; real commands in config; stale README command reported; tasks for both features; baseline check result reported; existing CI setup preserved; check command uses the shared registry |
| d | c after bootstrap: one task active, last verify failed, a note | "pick up where the last session left off" | all of: the agent names the task and the failing check from `status` before opening other files; it finishes with `done --proof`; at most one task in progress |
| e | c after bootstrap, with an assumption that names are public | "names must not be shown publicly any more" | all of: the assumption row is marked invalid and a decision row added; affected tasks are edited, reopened, or dropped; new tasks queued; PROJECT.md and the queue agree |
| f | c after bootstrap, with user edits, one passing task, and a new Python script with tests | "run the bootstrap again and include the Python tests" | all of: user edits byte-identical; task IDs and evidence kept; new check added; `validate` passes |

Task-loop scenarios, on a bootstrapped fixture with a review path and a slow required check. Each agent gets one task and may not start other agents:

| ID | Task | Passes when |
|---|---|---|
| g | fix a typo in the README | finished; the slow check did not run; no review asked |
| h | fix a reported bug outside the review paths | hidden test passes; one regression test; no review asked |
| i | add a small helper outside the review paths | hidden test passes; no test file added; proof given after the checks ran |
| j | fix a reported bug on a review path | hidden test passes; the runner asks for a review and the agent stops there |

For every run, record:
- total tokens and duration, as reported by the agent runner;
- files created and questions asked;
- the steps taken before the first useful action;
- pass or fail for each check, with the file or output that shows it.

One run per scenario is a single observation. Report it as such and do not average it into a claim.

## 3. Context cost without a model

For each path (start a project, resume, implement a task, investigate a failure, change scope), list the files and command outputs an agent must read, and measure them in bytes. Token counts are estimated as bytes/4 and labeled as estimates.

Results: [historical results](evaluation-history.md).

## 2026-10-09 audit

The original 26 tests passed before changes. Added audit scenarios first reproduced 32 failing assertions across 16 scenarios, covering false verification, stale delivery, unsafe configuration and reconciliation. Further review reproduced package redirection, unchecked path constraints, lost task history, temporary-file overwrites, executable-mode changes and unsafe post-merge cleanup. Regression cases cover each fix, including two edge cases found while reviewing the fixes.

Validation commands:

- `python3 assets/harness.py check`: bundle validation, the full unittest suite, and six deliberate false-success mutations. CI uses the same registry on Python 3.8 and 3.14.
- `python3 -m unittest discover -s tests -p 'test_generated.py'`: installed-project probes, including standalone proof/review, legacy evidence, package scripts and reconciliation.
- Skill frontmatter validation with `quick_validate.py`: valid (PyYAML installed only in the disposable validation environment).

A separate read-only review found no remaining blocking findings after fixes. A fresh spec-mode CSV CLI fixture ran installation, checks, verification, wrapup and repeated dry-run/real reconciliation without the installed skill. It preserved user notes, project decisions, task evidence and explicit local-delivery settings byte-for-byte. Its attempted completion correctly stopped at an uncommitted-change check; no product CLI or remote was published.

Limits: deterministic delivery tests use a bare local remote and a fake GitHub CLI. Real branch protection, approval rules, merge queues, Windows and live browser execution are not covered. No claim of improved token use or broad product quality comes from this single forward fixture. Historical evaluation results remain in [evaluation-history.md](evaluation-history.md).

## 2026-11-16 task-loop changes

Old is commit `507b285`; new is the working tree described in [design notes](design-notes.md). Checks at that point: `python3 assets/harness.py check` passed (bundle, 66 tests, six mutations). Each new runner test fails on the old runner.

Scripted tasks, `scripts/measure.py`, old → new. The old run used `--flag-review`:

| Scripted task | Commands | Refused | Reviews | Slow check runs |
|---|---|---|---|---|
| docs typo | 8 → 5 | 2 → 0 | 0 → 0 | 2 → 0 |
| code fix, then a README edit after verify | 10 → 7 | 3 → 1 | 0 → 0 | 3 → 1 |
| risky change: one failed review, a fix, then a README edit | 17 → 10 | 6 → 1 | 3 → 2 | 4 → 2 |
| code change outside the review paths | 8 → 5 | 2 → 0 | 0 → 0 | 2 → 1 |

Agent runs: scenarios g–j, three runs each per version, the same model (Sonnet), a four-file Python fixture whose required unit check sleeps 20 seconds to stand in for a real suite. Medians of three, old → new:

| Scenario | Seconds | Slow check runs | Test lines added | Review asked | Hidden test |
|---|---|---|---|---|---|
| g typo | 63 → 24 | 2 → 0 | 0 → 0 | 0/3 → 0/3 | 3/3 → 3/3 |
| h bug fix | 72 → 52 | 2 → 1 | 3 → 3 | 0/3 → 0/3 | 3/3 → 3/3 |
| i helper | 87 → 50 | 2 → 1 | 13 → 0 | 0/3 → 0/3 | 3/3 → 3/3 |
| j bug on a review path | 70 → 49 | 2 → 1 | 4 → 4 | 0/3 → 3/3 | 3/3 → 3/3 |

- j is not a time comparison: the old runs delivered the change with no review, and the new runs stop where the review is pending.
- In the old runs, 11 of 12 first `verify` calls carried proof written before the checks ran, and the permission system of the agent tool refused four such commands; one run did not finish. In the new runs: 0 of 12, and none refused.
- Comment lines added were the same in both versions (one line in i and j), and each was a docstring in the fixture's style or a reason the code does not show. These runs give no evidence about comment volume.
- Output tokens per run changed little (medians 1,664–3,129 old, 1,524–2,601 new). The time saved comes from check runs that no longer happen.

Limits: one small fixture, one model, three runs per cell, no remote and no live reviewer. Review cost was not measured here. The numbers say nothing about large repositories or long sessions.

## 2026-11-16 scale changes and their review

What changed is in [design notes](design-notes.md), "Scale changes". Checks: `python3 assets/harness.py check` passed (bundle, 92 tests, six mutations). The scripted counts of `scripts/measure.py` are the same as in the table above.

Runner time on generated repositories, local delivery, one run each:

| Files | Finished tasks | `status` | `add` | `verify` (one instant check) | `done` |
|---|---|---|---|---|---|
| 1,000 | 0 | 0.15 s | 0.11 s | 0.35 s | 0.15 s |
| 10,000 | 0 | 0.15 s | 0.13 s | 1.46 s | 0.45 s |
| 30,000 | 0 | 0.17 s | 0.12 s | 5.02 s | 1.20 s |
| 1,000 | 2,000 | 0.17 s | 0.54 s | 0.68 s | 0.33 s |

The `add` in the last row is the one-time move of 2,000 records from the old single file to one file per task.

Parallel work, pull-request delivery, against a bare local `origin` and a fake `gh`: two worktrees finish two tasks at the same time; two clones that both used F001 deliver as F001 and F002 and their branches merge without a conflict; a task queued while another is in progress never appears in that task's branch.

Independent review: a reviewer with no part in the changes got the diff and the docs, and reported only defects it reproduced in scratch repositories. It found 18 (2 high, 7 medium, 9 low). The two high ones were false success: a moved file, a non-ASCII file name, or a harness below the top of the git repository hid changed files from check selection and from the review rule; and in local delivery `block` then `start` forgot what the task had already committed. 16 are fixed; the two left are listed in the design notes. The same reviewer then checked the fixes: 13 held, 3 were incomplete, and the fixes had added 13 new defects (1 high: a refused `start` deleted a queued task it had just renumbered). 11 of those are fixed and 2 are left, also listed in the design notes. A third pass confirmed the fixes, found one incomplete and three small defects; two are fixed and two are left, listed in the same place. Each fix has a test, and each test was run against a copy of the runner with that fix taken out, where it fails.

Limits: the times come from generated files on one machine. Parallel work was not run with real GitHub, so merge conflicts in product code, branch protection and merge queues are not covered. Local delivery has no support for parallel branches. No agent runs were repeated after these changes.
