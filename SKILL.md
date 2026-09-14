---
name: harness-bootstrap
description: Turn a project idea, a written spec, or an existing repository into a working harness for coding agents - domain research scaled to the uncertainty, a project definition with testable requirements, a small task queue with real checks, and a bundled runner that tracks tasks, verification evidence, and session handoff. Use when someone wants to start a project with coding agents ("I have an idea for a website", "set up this repo so agents can build it", "bootstrap the harness"), rerun or upgrade an existing harness, or migrate a harness-bootstrap 1.x project. Not for ordinary feature work in a repository that already has the harness; its AGENTS.md covers that.
---
# Harness Bootstrap

The result: a fresh agent session in the repository runs one command, learns what to do next, finishes one task end to end with proof, and leaves state the next session can trust. Bootstrap ends with the project defined, the harness installed, and tasks queued. Build product features only if the user asked for that as well.

A bootstrapped repository gets: `AGENTS.md` (project notes plus the harness block), `docs/PROJECT.md`, `docs/RESEARCH.md` when research ran, `docs/tasks.json` and `docs/config.json`, and the runner `scripts/harness.py`. Details: [references/harness.md](references/harness.md).

`<skill>` below means the directory that contains this file.

## 1. Inspect

Run `python3 <skill>/scripts/bootstrap.py inspect <repo>`. Read the instruction files it lists (AGENTS.md, CLAUDE.md, CONTRIBUTING) and the README. Existing project rules win over this skill's defaults.

Pick the mode:
- **Idea**: no code and no spec. Full discovery.
- **Spec**: the request or docs already define users, behavior, interface, and checkable results. Discovery tier 0.
- **Existing code**: the code is the truth about current behavior. Discover only the requested next work and what the code cannot tell.
- **Rerun**: the harness or 1.x files are present. Follow "Rerunning bootstrap" or "Migrating" in references/harness.md, then continue at step 4 for anything new.

If `python3` is missing, stop and report it as a blocker with the install command for the platform. Do not generate a runner in another language unless the user asks for one.

## 2. Discover

In Idea mode, and for Existing code when the requested work is not defined yet, read [references/discovery.md](references/discovery.md) and follow it. Skip it for Spec and Rerun unless the request changes what the product should do. It sets the research depth from uncertainty and stakes, the budget, when to stop, and when to ask the user. Ask at most 3 questions, once, each with a recommended default. The stack is your decision, recorded with its reason, not a question.

## 3. Define

Write `docs/PROJECT.md` from [the template](assets/templates/PROJECT.md.tmpl), and `docs/RESEARCH.md` from [its template](assets/templates/RESEARCH.md.tmpl) when research ran. Delete empty sections. PROJECT.md holds decisions, not history, copied research text, or a restatement of the request: add a D- row only for a choice someone could reasonably make differently.

Each requirement is one observable behavior with Given/When/Then acceptance, concrete values, and the check that will prove it. Write `docs/ARCHITECTURE.md` only for two or more deployable parts, or boundaries the code will not show.

## 4. Plan the queue

- One task is one observable behavior that a single session can finish, with 1–5 acceptance lines copied from its R- rows and `--ref` to those IDs. Split anything bigger.
- New project: F001 is a walking skeleton. Scaffold the chosen stack, and add one passing example of every check the project will use (for a web app: unit, build, and a browser smoke test). Later tasks then start from green checks.
- Existing code: if the current checks fail, F001 makes them pass before any feature.
- Order by dependency. Put code that can test the riskiest assumption early.
- Queue 3–8 tasks for the first release. Later ideas stay in the PROJECT.md scope, not in the queue. Behavior that already exists and works needs no task.

## 5. Install and configure

1. Run `python3 <skill>/scripts/bootstrap.py install <repo>`. Add `--claude` when the user works in Claude Code. On a repository that already has a harness or legacy files, run with `--dry-run` first. Report conflicts; never overwrite them.
2. Put the checks in `docs/config.json` (see "Checks" in references/harness.md). Take commands from package scripts, Makefile, and CI. Required checks are the fast regression suite. Also give each task its own check that runs only the tests for its acceptance (for example `node --test test/tags.test.js`); the task itself creates that test. Web interfaces get browser tests, unless project rules forbid the tooling: then use HTTP-level tests and record the gap as an A- row.
3. Above the harness block in `AGENTS.md`, write the project part in at most 40 lines: purpose in one line, setup, dev, and run commands, and project rules the code does not show. Leave existing instructions as they are. Link to PROJECT.md instead of copying it. No generic advice.
4. Queue the tasks: `python3 scripts/harness.py add "<behavior>" --accept "..." --check <id> --after F00n --ref R-n`. Never write `docs/tasks.json` by hand.

## 6. Validate and report

Run `python3 scripts/harness.py validate` and `status`. For existing code, run the required checks' commands once and record whether the baseline passes; queue fixes instead of making them during bootstrap. Prove a new check by running its command directly, not with `start` or `verify`: a task left active or verified blocks the first task of the next session. Do not commit or push unless the user asked; list the files to commit.

Report briefly:
- the mode and discovery tier, and the findings that changed scope;
- questions asked, and the defaults in use;
- files created, updated, or in conflict;
- checks and the baseline result;
- the queue and its first task;
- anything unverified or blocked.

Stop here unless the user also asked you to build. If they did, follow the task loop in the AGENTS.md harness block.

## Rules that prevent known failures

- Never invent facts, check results, or links. Unknowns become A- or Q- rows.
- One home for each kind of state: tasks and evidence in `docs/tasks.json` through the runner, product decisions in PROJECT.md, check commands in `docs/config.json`. Do not create plan, handoff, status, or changelog documents.
- Never overwrite user content. Edit existing docs surgically.
- Research subagents only for tier 3, on separate topics. One agent writes the docs and runs the harness.

Changing this skill: see [evals/README.md](evals/README.md).
