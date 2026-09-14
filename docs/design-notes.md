# Design notes (maintainers)

Why harness-bootstrap 2.0 works the way it does. Agents running the skill never need this file. Version 1.x rationale (Symphony, Spec Kit, OpenSpec, Beads, OpenHands) is in git history under `references/research.md`.

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
| One tested runner (`assets/harness.py`) copied into projects | P1, P2, P10, P11, P15 | Deterministic behavior belongs in code, not in prose an agent re-implements; bundled scripts run without entering context (Agent Skills spec) | Needs Python 3.8+ where agents work; one implementation to maintain | `evals/test_harness.py` |
| Local definition of done: `verify` (own + required checks) → commit → `done --proof` | P1, P6, P7 | Course lecture 07 loop; Anthropic long-running harness (2025-11-26); OpenAI harness engineering (2026-02-11). No source makes PR + CI the definition of done | `--proof` names the test but cannot prove coverage; CI stays outside the gate | full-loop test; scenario d |
| One home per kind of state; `status` computes the resume view from tasks.json, notes and git | P3, P13 | Sources keep machine task state + one narrative + git, and compute git facts on read (OpenAI exec plans 2025-10; Anthropic 2025-11, 2026-03) | History lives only in short notes and commits | scenario d |
| Two hashes: task definition and repository files, bookkeeping files excluded; passing tasks flagged only on definition change | P4 | Keeps evidence meaningful without re-verify churn | Any file edit between verify and done needs a new verify; large repos hash many files | stale-evidence test |
| Runner commands `add`, `edit`, `drop`, `note`, `block`, `reopen`; one task active or verified at a time | P5, P7 | Anthropic's agents may only flip a pass flag; lecture 07 WIP = 1 | More commands to learn; `-h` lists them | loop and dependency tests |
| Tiered discovery with budgets, stop rules, one batch of at most 3 questions; ID'd rows in PROJECT.md, facts in RESEARCH.md | P8 | Effort scaling (Anthropic multi-agent research, 2025-06-13); clarification limits (Spec Kit); assumption testing (Bland 2020, Torres 2023); value of information (Howard 1966); saturation (Francis et al. 2010) | Budgets and thresholds are unmeasured estimates | scenarios a, b, e |
| Progressive disclosure: SKILL.md always, discovery.md only for undefined products, harness.md only for checks, reruns or migration | P9 | Agent Skills guidance; AGENTS.md studies show more always-loaded text raises cost without a correctness gain (arXiv 2602.11988, 2607.27250) | Agents must follow the pointers | byte measurements in the report |
| Installer with hashes and markers (`scripts/bootstrap.py install`) | P12 | Makes reruns deterministic instead of improvised | Only the runner and the AGENTS.md block are managed; docs are the agent's and the user's | installer tests; scenario f |
| Check recipes per stack; a browser test for each visible criterion in web projects | P14 | Anthropic: agents marked features done untested until told to test like a user; METR (2026-03-10): passing tests are not mergeable code | Playwright needs a network install; not bundled | scenarios a, c |

## Considered and not adopted

- **Generate a native runner per project (1.x):** token cost and drift (P2).
- **A Node twin of the runner:** a second implementation to keep identical. Python 3 is present on nearly every development machine and agent sandbox. Ported runners remain possible, but the tests are Python.
- **A separate evaluator agent per task:** Anthropic's full harness cost about 22× a solo run and helped mainly near the model's limit. Keep it as a project choice, not a default.
- **Running a task's checks at `start` to prove they fail first:** slow for build or browser suites. `--proof` at `done` is the cheaper guard; revisit if evaluations show false completions.
- **A GitHub `deliver` command and `archive`:** outward actions stay under the user's authorization. `status` stays short without archiving.

## Decisions to revisit

1. The Python requirement reverses the 1.x rule "never require Python for Node projects".
2. `passing` no longer means "merged with green CI". Repositories that need that should gate merges in CI.
3. `docs/harness-sequence.png` still shows the 1.x flow.
