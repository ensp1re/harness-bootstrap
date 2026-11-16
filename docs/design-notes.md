# Design notes (maintainers)

Historical rationale for harness-bootstrap 2.0. The current behavior is defined in [the runner reference](../references/harness.md); delivery and evidence rules below describe past decisions. Agents running the skill never need this file. Version 1.x rationale (Symphony, Spec Kit, OpenSpec, Beads, OpenHands) is in git history under `references/research.md`.

## Problems found in 1.x

Five reviews ran on 2026-09-14: external sources, domain research, token cost, workflow, and failure modes. **Observed** means reproduced on disposable copies of the 1.x fixtures.

| ID | Problem | Status |
|---|---|---|
| P1 | Tasks reached `verified`/`passing` without real evidence: a no-op check verified a product task, and hand-written delivery JSON produced `passing` | observed |
| P2 | Every bootstrap generated a 26–40 KB runner; the Node, Python and Go runners disagreed on JSON keys, dependency rules and freshness | observed |
| P3 | Resume sources contradicted each other (tasks.json, handoff.json, SESSION_HANDOFF.md, PLAN.md) | observed |
| P4 | Freshness was global: adding a task or a plan note made all evidence stale | observed |
| P5 | No commands to add, edit, drop, or note tasks; agents hand-edited JSON | observed |
| P6 | `passing` required GitHub PR + CI and no runner implemented `deliver`, so local projects could not finish | observed |
| P7 | No implement loop, definition of done, scope rule, or stop rule after bootstrap | observed |
| P8 | No domain research; the user was asked for stack and acceptance criteria; the spec template had no users, alternatives, glossary, or assumptions | observed |
| P9 | 44.6 KB of skill files read per bootstrap; 68% of contract.md described runner internals | observed (bytes) |
| P10 | A killed verify locked the Node harness permanently; checks kept running | observed |
| P11 | Probes did not test the contract: a runner with no logic passed the scenario probe | observed |
| P12 | Rerun reconciliation existed only as prose | observed |
| P13 | Seven generic documents had no consumer (RELIABILITY, SECURITY, TECH_DEBT, CHANGE, PLAN, SESSION_HANDOFF, templates README) | observed |
| P14 | No lint, build, or browser-test guidance for web projects | observed |
| P15 | Commands run during a verify corrupted state (blocked became verified) | observed |

## Adopted

| Approach | Fixes | Why it fits | Cost | How it is checked |
|---|---|---|---|---|
| One tested runner (`assets/harness.py`) copied into projects | P1, P2, P10, P11, P15 | Deterministic behavior belongs in code, not in prose an agent re-implements; bundled scripts run without entering context (Agent Skills spec) | Needs Python 3.8+ where agents work; one implementation to maintain | `tests/test_harness.py` |
| Local definition of done: `verify` (own + required checks) → commit → `done --proof` | P1, P6, P7 | Course lecture 07 loop; Anthropic long-running harness (2025-11-26); OpenAI harness engineering (2026-02-11). No source makes PR + CI the definition of done | `--proof` names the test but cannot prove coverage; CI stays outside the gate | full-loop test; scenario d |
| One home per kind of state; `status` computes the resume view from tasks.json, notes and git | P3, P13 | Sources keep machine task state + one narrative + git, and compute git facts on read (OpenAI exec plans 2025-10; Anthropic 2025-11, 2026-03) | History lives only in short notes and commits | scenario d |
| Two hashes: task definition and repository files, bookkeeping files excluded; passing tasks flagged only on definition change | P4 | Keeps evidence meaningful without re-verify churn | Any file edit between verify and done needs a new verify; large repos hash many files | stale-evidence test |
| Runner commands `add`, `edit`, `drop`, `note`, `block`, `reopen`; one task active or verified at a time | P5, P7 | Anthropic's agents may only flip a pass flag; lecture 07 WIP = 1 | More commands to learn; `-h` lists them | loop and dependency tests |
| Tiered discovery with budgets, stop rules, one batch of at most 3 questions; ID'd rows in PROJECT.md, facts in RESEARCH.md | P8 | Effort scaling (Anthropic multi-agent research, 2025-06-13); clarification limits (Spec Kit); assumption testing (Bland 2020, Torres 2023); value of information (Howard 1966); saturation (Francis et al. 2010) | Budgets and thresholds are unmeasured estimates | scenarios a, b, e |
| Progressive disclosure: SKILL.md always, discovery.md only for undefined products, harness.md only for checks, reruns or migration | P9 | Agent Skills guidance; AGENTS.md studies show more always-loaded text raises cost without a correctness gain (arXiv 2602.11988, 2607.27250) | Agents must follow the pointers | byte measurements in the report |
| Installer with hashes and markers (`scripts/bootstrap.py install`) | P12 | Makes reruns deterministic instead of improvised | Only the runner and the AGENTS.md block are managed; docs are the agent's and the user's | installer tests; scenario f |
| Check recipes per stack; a browser test for each visible criterion in web projects | P14 | Anthropic: agents marked features done untested until told to test like a user; METR (2026-03-10): passing tests are not mergeable code | Playwright needs a network install; not bundled | scenarios a, c |

## Added after reading the course end to end (2026-09-15)

| Course point | Change | Cost | How it is checked |
|---|---|---|---|
| L09, L11, L13, L14: the agent that writes code must not judge it | `add --review` marks a task; `review ID --pass/--fail` records a fresh-context review; `done` requires a passing review of the current files | one reviewer run per marked task; the runner cannot prove the reviewer was independent | review test |
| L12: every session ends clean | `wrapup --note` runs required and `wrapup: true` checks, flags debug leftovers in added lines and uncommitted work without a note, and stores the result for the next `status` | a check run per session end; leftover patterns can match legitimate lines | wrapup test |
| L07 task template, L11 sprint contract: what must not change | `--keep` entries; path globs fail `verify` when they changed since `start` | path checks need git | must-not-change test |
| L14: "not enough information → back to research" | task loop step 3: one round of at most 5 searches, or `block` with the question | depends on the agent following the rule | not tested |
| L06: initialization is its own phase and actually runs | SKILL.md step 6 builds the walking skeleton through the loop and commits the baseline | needs network and commit permission; otherwise F001 stays ready | not tested with agents |
| L01, L09: an explicit definition of done | a "Definition of done" paragraph in the AGENTS.md block, enforced by `verify`, `review` and `done` | about 80 more words loaded each session | bundle check |
| L04, L05: context that keeps growing | `list` hides finished tasks; notes before a compaction; PROJECT.md split rule in references/harness.md | none | list test |

## Considered and not adopted

- **Generate a native runner per project (1.x):** token cost and drift (P2).
- **A Node twin of the runner:** a second implementation to keep identical. Python 3 is present on nearly every development machine and agent sandbox. Ported runners remain possible, but the tests are Python.
- **A separate evaluator for every task:** Anthropic's full harness cost about 22× a solo run and helped mainly near the model's limit. Review is opt-in per task (`--review`) instead.
- **Running a task's checks at `start` to prove they fail first:** slow for build or browser suites. `--proof` at `done` is the cheaper guard; revisit if evaluations show false completions.
- **`archive`:** `status` stays short without archiving.

## Decisions

- **Python 3.8+ where agents work** (confirmed by the user on 2026-09-15). It reverses the 1.x rule against requiring Python in Node projects; one tested runner is worth the dependency.

- **Every change after the first delivery goes through a pull request** (the user's decision on 2026-09-17, after 2.0 made pushes and PRs opt-in).
  - `start` cuts a branch per task from `origin/<base>`.
  - `done` commits the passing state on that branch, pushes, opens the pull request, waits for `gh pr checks`, and merges with `--match-head-commit`.
  - One `done` call waits at most 90 seconds, because agent tools often stop commands after 2 minutes; the agent runs `done` again.
  - A merge counts only when GitHub reports the pull request as merged: a merge queue exits 0 without merging, and `gh` can exit 1 after merging.
  - A pre-push hook blocks direct pushes to the base branch.
  - A task counts as in progress until its pull request is merged, read from `docs/tasks.json` on `origin/<base>`.
  - The harness commit is the only direct push to the base branch.
  - Cost: needs `gh`; the hook is per clone. Checked by delivery tests against a bare local remote and a fake `gh`.

- **Bootstrap creates the GitHub repository** (the user's decision on 2026-09-21).
  - The repository is private, under the account `gh` uses, and named after the folder.
  - The harness commit is pushed directly; the walking skeleton then goes through a pull request like every task.
  - This replaces the first-delivery path, where F001 was built on the base branch and pushed directly.
- **Commit hooks** (the user's decision on 2026-09-21).
  - A pre-commit hook runs the checks marked `precommit`.
  - New Node projects get husky, so the hooks are committed and reach every clone that runs `npm install`.
  - The push guard moved from a generated shell script into `harness.py hook pre-push`, so one line works in `.git/hooks` and in husky files.
  - Cost: a Python start plus the fast checks on every commit.

## Task-loop changes (2026-11-16)

The evidence came from one project that ran 460 tasks on an earlier runner, and from old-versus-new runs ([evaluation](evaluation.md)).

| Problem seen | Change | Cost | How it is checked |
|---|---|---|---|
| Review was a flag set while planning, by topic. More than half of the tasks got one, small ones included | `review.paths` in the config: the runner requires a review when a task changes a listed file. `--review` stays for a user request | the paths must be kept current | review-path test |
| Any file edit cancelled a passed review, so every fix started a new full review | A review covers the changed files on review paths and stays valid until one of them changes. The runner sends the agent back to the same reviewer, and to the user after three failed reviews | an edit outside those files is not reviewed again | review-scope test |
| Every required check ran in each `verify`, at `wrapup` and in CI, also for a docs-only change | A check may declare `paths`: it is skipped when no changed file matches and not run again while those files are unchanged. `wrapup` runs only `wrapup` checks | `paths` must list every input; integration checks leave it off | paths test, `scripts/measure.py` |
| A typo needed acceptance lines, its own check and proof | Acceptance lines and an own check are optional. `verify` refuses when no check covers the change | a behavior task can be queued without acceptance lines | small-task test |
| `verify` told the agent to run `done` while a review was still missing | The next-step line names the review and the reason | none | review-path test |
| A stopped `wrapup` or `check` left its check running | The SIGTERM handler covers every command | none | SIGTERM test |
| Agents asked for permission to commit in every task | `delivery.autoPublish` records the standing answer; `status` prints it | information only, nothing is enforced | status test |
| Agents opened PROJECT.md to read one row | `show` prints the referenced rows | none | show test |
| Tests and comments piled up | The workflow says: no tests or comments by default, with named exceptions | a text rule, not enforced | agent runs |
| Agents wrote proof before the checks had run, and added a test only to have a check to name | `verify` hints to give proof afterwards; `verify --proof` on a verified task records it without a rerun; outside review paths a line may carry `manual:` proof | manual proof is the agent's word, said plainly | proof test, agent runs |
| No timing data from real use | One line per command in `docs/runs/events.jsonl` | a small ignored file | small-task test |

Left as it was: the runner does not check that a named check exercises the acceptance line; the unused `spec` and `plan` fields stay, because removing them would change stored hashes.

## Scale changes (2026-11-16)

Measured first: the runner itself is fast on a large repository (30,000 files add about 4 seconds to `verify`; 2,000 finished tasks leave `status` under 0.3 seconds). The limits were elsewhere.

| Problem seen | Change | Cost | How it is checked |
|---|---|---|---|
| Every task rewrote one `docs/tasks.json`, so two branches always conflicted in it | One file per task in `docs/tasks/`. The old file is read once and replaced at the first write | the upgrade must merge through one pull request before a second task starts | migration tests |
| One unmerged pull request blocked every other task | A task waits only for the tasks it depends on. Several worktrees or clones work at once | two tasks that edit the same code still conflict in git | parallel-worktree tests |
| Two branches gave the same id to different tasks | New ids skip the ids on the base branch, in the archive and in branch names. A clash found later renumbers the task that is not merged yet. A random `uid` on each task tells two tasks with one id apart | an id can change before delivery; the runner prints the new one | two-clone test |
| A queued task was an untracked file: `git add -A` swept it into another branch, and a reset deleted it | Tasks that were never started wait in the shared git folder, outside the working tree, once the harness is on the base branch. Delivery commits only the delivered task's record and edits to records git already tracks | such a task reaches other clones only when someone starts it | queue tests |
| A second command during a long one was refused, and a finished `verify` lost its result | One lock for all worktrees; commands wait for it up to 30 seconds | a command can wait | lock test |
| Dependencies were known only from local files | A dependency also counts when its record on origin's base branch is passing; a task on another branch is known, not reported as missing | one fetch at `start` | dependency test |

An independent review of these changes reproduced 18 defects. 16 are fixed. Two are left: a started task's record is an untracked file until the task's first commit, so `git clean` removes it (the same on the earlier runner); and a local benchmark script that is not part of the bundle still reads the old single file.

The same reviewer then checked the fixes. Three were incomplete, and the fixes had brought in 13 new defects, the worst being a refused `start` that deleted a queued task it had just renumbered. 11 of the 13 are fixed. Two are left as they are: with local delivery a task that is blocked and resumed counts the commits made in between as its own, which makes checks and review cover more, never less; and a value of `HARNESS_LOCK_SECONDS` that is not a number ends in a Python error, like the other timing settings. A third pass confirmed these fixes except one: the record of a blocked task still reached the base branch when the agent had committed it with `git add -A`. That is fixed, and a renumbered task now prints its new number even when the command is refused afterwards. Two small findings of that pass are left: two tasks made in two clones by a runner from before tasks carried a `uid` count as one task under the same number; and during an upgrade `status` still offers `start` while the upgraded runner sits on an unmerged branch, where `start` refuses and says to merge the upgrade first. Every fix from the three rounds has a test in `tests/test_generated.py` (`ReviewFindings`), and each of those tests fails when its fix is taken out.

Not done: stacked tasks (starting a task on top of an unmerged one), and sharing never-started tasks between clones before one of them is started.

## Decisions to revisit

1. `docs/harness-sequence.png` still shows the 1.x flow.
