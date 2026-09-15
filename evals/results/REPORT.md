# Evaluation record: harness-bootstrap 2.0 (2026-09-15)

This record compares 1.x (commit 786b6a4) with 2.0 on disposable fixtures. The fixtures and run folders were in the session scratchpad and are not committed. The comparison has two parts: byte counts, which are exact, and agent runs, which are single observations.

## 1. Deterministic checks

| Check | Result |
|---|---|
| `python3 scripts/check_bundle.py` | ok |
| skill-creator `quick_validate.py` | valid. PyYAML is not installed, so a local stand-in parsed the flat `key: value` frontmatter; it fails on anything more complex. |
| `python3 -m unittest discover -s evals -p 'test_*.py'` | 16 tests OK on Python 3.14.7 and on macOS system Python 3.9.6 |
| Manual smoke test on a copy of the potluck site | install, add, start, then a failing verify printed the log path and log tail; `status` showed the failure |

## 2. What an agent reads and writes

All numbers are bytes. Token counts are estimates: bytes/4.

| Path | 1.x | 2.0 |
|---|---|---|
| Bootstrap: skill files read | 44,639 (plus 12,139 when research.md is read) | 14,443 when the request is a full spec; 20,041 for an idea; plus the 654-byte `inspect` output |
| Bootstrap: runner code the model writes | 31,590–39,689 per project | 0 (the installer copies the 35,775-byte runner; agents are told not to read it) |
| Instruction file loaded every session | 4,373 router template before project text | 2,255 harness block; the potluck AGENTS.md is 2,701 in total |
| Resume view | `context` 337–461 plus `tasks` 905–2,031, SESSION_HANDOFF.md and PLAN.md, which disagreed with each other | `status` 891: the active failing task with its acceptance, checks, last failure and log paths, notes, and waiting tasks |
| Queue with 30 extra tasks | `tasks` output 15,775 (Node) and 22,171 (Python) | `status` 284; `list` 2,848 |
| Failure investigation | Node verify 251 with no log path; Python 2,538 | 329 (one failing check) to 2,230 (two failing checks with npm output), log tail included |
| Finding what a scope change affects | PROJECT.md, PLAN.md and tasks.json edited by hand | PROJECT.md 2,810, grep 449–725, `list` |
| Skill description, loaded wherever the skill is listed | 300 characters | 666 characters (about 90 tokens more, estimate) |

## 3. Agent runs

- **Model:** Sonnet for every run. Earlier parallel Opus runs hit the account session limit.
- **Setup:** unattended. Questions went to `questions.md`, with defaults.
- **Token counts:** tokens and time come from the agent runner and include each agent's system prompt and tool overhead.
- **Sample size:** one run per cell.

| Scenario | 2.0 | 2.0 tokens / minutes / tool calls | 1.x | 1.x tokens / minutes / tool calls |
|---|---|---|---|---|
| a: vague website idea (empty folder) | pass | 163,077 / 12.1 / 49 | fail: no research (0 sources, no alternatives), wrote product code, committed 5 times unasked | 344,577 / 36.6 / 103 |
| b: fully specified CLI | pass, over-documented | 149,654 / 10.7 / 47 | not run | — |
| c: existing site, partial docs | pass, weak per-task checks | 147,051 / 9.2 / 52 | pass by its own contract; wrote a 38,764-byte runner, 13,766 bytes of runner tests and 6 docs | 267,514 / 22.3 / 64 |
| d: resume after an interrupted session | pass, read runner source | 103,793 / 5.1 / 37 | not run | — |
| d, reworded AGENTS.md block | pass; ran `status` as its second step, did not read the runner, still read `docs/tasks.json` once | 91,468 / 3.2 / 26 | — | — |
| e: scope change invalidates an assumption | pass, read runner source | 131,096 / 7.0 / 34 | not run | — |
| f: rerun bootstrap with user edits | pass, but added a task for existing code | 180,354 / 13.9 / 58 | not run | — |

### 2.0 run details

- **a:**
  - Discovery: tier 2 with its trigger recorded; used 7 of 15 searches and 4 of 25 pages, with the stop reason written down.
  - RESEARCH.md: 8 facts with URL, published and checked dates, and 4 alternatives with gaps.
  - The research changed the scope: Q-1 offers "adopt TopLogger/KAYA instead" as an option, and the COPPA fact produced Q-2, about under-13 members.
  - PROJECT.md: 9 requirements with Given/When/Then, 3 assumptions with thresholds, and 3 questions, each with options and a default.
  - Tasks: 5, dependency-ordered. F001 is a walking skeleton with lint, typecheck, unit, build and a browser smoke test.
  - `validate` passes and no feature code was written.
- **b:**
  - Tier 0, no RESEARCH.md.
  - Every stated rule (exit codes 0/1/2, quoted fields, BOM, duplicate keys, `--json`) is in the acceptance of 6 tasks; `validate` passes.
  - Weak points: 10 decision rows, mostly restating the request (PROJECT.md 8,593 bytes), and only one shared test check for all tasks.
  - It asked 3 CLI-design questions the spec left open (key syntax, schema mismatch, table layout), each with a default.
- **c:**
  - The three AGENTS.md rules and the CI file are unchanged. Baseline `npm test` passed 3/3.
  - The README's missing `npm run dev` was reported and left alone.
  - Two tasks for the requested features. Browser tooling was skipped because the project's no-dependency rule forbids it.
  - Weak points: every task uses the shared `npm test` check, and the agent added an H1 heading above the existing notes.
- **d:**
  - The agent found F001 and its failing checks and read the note. It fixed `lib/store.js` and `public/index.html`, then ran verify, commit, `done --proof` (2 criteria), and committed `docs/tasks.json`. The tree is clean and `validate` passes.
  - It did not start F002, reading "pick up where the last session left off" as a limit.
  - Waste: its log shows no `status` call; it read `docs/tasks.json` and the runner source instead.
- **e:**
  - A-1 is marked wrong and R-3 rewritten. R-4 (organizer view) and Q-2 (how to keep it private, with a default) were added.
  - F001 was edited and reopened with a note, F003 queued with its own check, and F002 left untouched.
  - The change was committed and `validate` passes. PROJECT.md and the queue agree.
  - Waste: it read `docs/tasks.json` and the runner source.
- **d, second run with the reworded block:** `status` was its second step, right after AGENTS.md. It did not read the runner source and finished the same way: verify, commit, `done --proof`, commit. It opened `docs/tasks.json` once, to see what waits on F001.
- **f:**
  - `install --dry-run`, then `install`, reported unchanged or kept, with no conflicts.
  - The user's AGENTS.md line and D-3 row are byte-identical, and F001 keeps its passing evidence, commit and proof.
  - The new Python tests became a required `export` check, and `validate` passes.
  - Waste: it read discovery.md, which a rerun does not need, and created R-4 and F003 for the export script that already existed. It then verified F003, which leaves a verified task blocking F002 until someone commits and runs `done`.

### 1.x run details

- **a:**
  - No domain research: the docs cite 0 sources and name no existing gym apps. Product choices went straight to questions.md as defaults.
  - Wrote a 43,398-byte runner, 29,562 bytes of tests and test helpers, and six docs (20,124 bytes).
  - It also implemented F001, a server skeleton in `src/server.mjs`, although 1.x forbids product code during bootstrap. F001 stays `verified`, because `passing` needs GitHub delivery.
  - It made 5 commits without being asked, including two fixes to its own runner's freshness logic.
- **c:**
  - Wrote a 38,764-byte runner, 13,766 bytes of runner tests (21 tests), the ARCHITECTURE, PLAN, PROJECT, RELIABILITY, SECURITY and SESSION_HANDOFF docs, handoff.json and install.json. It also changed package.json.
  - The three AGENTS.md rules and the CI file are unchanged. `validate` passes, and its own probes passed 6/6 and 8/8.
  - Bytes written into the repository: 76,613 for 1.x (2,527 into existing files, 74,086 in new files) against 11,366 for 2.0 (2,431 and 8,935). The 2.0 figure includes the script-written tasks.json and install.json and excludes the copied runner.

## 4. Changes made because of these runs

1. **d, e:** the AGENTS.md block now says to run `status` before anything else, and that `status`, `show` and `COMMAND -h` replace reading `docs/tasks.json`, old logs, or the runner. The runner header says the same.
2. **b, c:** SKILL.md asks for a per-task check that runs only that task's tests.
3. **b:** SKILL.md allows a decision row only for a choice someone could reasonably make differently.
4. **Byte measurement:** grep on `docs/tasks.json` finds a ref but not its task, so `list` now prints refs and the block points to `list`.
5. **d, second run:** the agent opened `docs/tasks.json` only to see what waits on F001, so `status` now prints waiting tasks and their unmet dependencies.
6. **f:** SKILL.md says behavior that already exists and works needs no task.
7. **f:** discovery is skipped in Spec and Rerun modes unless the request changes what the product should do.
8. **f:** bootstrap proves a new check by running its command directly, so it never leaves a task active or verified.

## 5. Not tested

- 1.x on scenarios b, d, e and f. Scenarios d–f need 1.x state that only a 1.x bootstrap creates, and the runs were limited to stay within the usage limit.
- Codex, the skill's first target. All runs used Claude Sonnet subagents.
- Browser checks actually running: there was no network for installing Playwright, and no walking skeleton was implemented.
- Windows and Python 3.8. Tests ran on 3.9.6 and 3.14.7 only.
- Research budgets, tier triggers and the 6-month recheck rule: unmeasured estimates, tried on one idea.
- Repeated trials. No claim here rests on more than one run.

## 6. Added after the agent runs (not re-run with agents)

These were added after reading the course end to end:
- the independent review step;
- `wrapup` at session end;
- must-not-change lists;
- the rule for research in the middle of a task;
- a real initialization phase;
- the explicit definition of done;
- `list` hiding finished tasks.

The unit tests in `evals/test_harness.py` cover the runner parts. No agent scenario was re-run after these changes, so their effect on tokens and completion is not measured.
