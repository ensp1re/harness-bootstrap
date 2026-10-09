---
name: harness-bootstrap
description: Turn a project idea, a written spec, or an existing repository into a working harness for coding agents - domain research scaled to the uncertainty, a project definition with testable requirements, a small task queue with real checks, an initialized walking skeleton, and a bundled runner that tracks tasks, verification evidence, reviews, session handoff, and delivery through pull requests with verified checks and explicit merge authorization. Use when someone wants to start a project with coding agents ("I have an idea for a website", "set up this repo so agents can build it", "bootstrap the harness"), define a large or unclear new feature for a repository that already has the harness, rerun or upgrade an existing harness, or migrate a harness-bootstrap 1.x project. Not for implementing tasks that are already queued; the repository's AGENTS.md covers that.
---
# Harness Bootstrap

The result: a fresh agent session in the repository runs one command, learns what to do next, finishes one task end to end with proof, delivers it through a pull request, with merge authorization kept separate, and leaves state the next session can trust. Bootstrap ends with the project defined, the harness installed and delivered, a new project initialized, and the next tasks queued. Build product features only if the user asked for that as well.

A bootstrapped repository gets: `AGENTS.md` (project notes plus the harness block), `docs/PROJECT.md`, `docs/RESEARCH.md` when research ran, `docs/tasks.json`, `docs/config.json` and `docs/workflow.md`, and the runner `scripts/harness.py`. Details: [references/harness.md](references/harness.md).

`<skill>` below means the directory that contains this file.

## 1. Inspect

Run `python3 <skill>/scripts/bootstrap.py inspect <repo>`. Read the instruction files it lists (AGENTS.md, CLAUDE.md, CONTRIBUTING) and the README. Existing project rules win over this skill's defaults.

Pick the mode:
- **Idea**: no code and no spec. Full discovery.
- **Spec**: the request or docs already define users, behavior, interface, and checkable results. Discovery tier 0.
- **Existing code**: the code is the truth about current behavior. Discover only the requested next work and what the code cannot tell.
- **Feature**: the harness is installed and the user asks for a large or unclear new feature. Run steps 2–4 for that feature only, then step 7.
- **Rerun**: the harness or 1.x files are present. Follow "Rerunning bootstrap" or "Migrating" in references/harness.md, then continue at step 4 for anything new.

If `python3` is missing, stop and report it as a blocker with the install command for the platform. Do not generate a runner in another language unless the user asks for one.

## 2. Discover

In Idea and Feature modes, and for Existing code when the requested work is not defined yet, read [references/discovery.md](references/discovery.md) and follow it. Skip it for Spec and Rerun unless the request changes what the product should do. It sets the research depth from uncertainty and stakes, the budget, when to stop, and when to ask the user. Ask at most 3 questions, once, each with a recommended default. The stack is your decision, recorded with its reason, not a question.

## 3. Define

Write `docs/PROJECT.md` from [the template](assets/templates/PROJECT.md.tmpl), and `docs/RESEARCH.md` from [its template](assets/templates/RESEARCH.md.tmpl) when research ran. Delete empty sections. PROJECT.md is the canonical decision register. Keep IDs unique; other docs link to its decisions. Distinguish implemented behavior from planned requirements. Delete the RESEARCH link when no research file exists. Do not copy research text or restate the request: add a D- row only for a choice someone could reasonably make differently.

Each requirement is one observable behavior with Given/When/Then acceptance, concrete values, and the check that will prove it. Those acceptance lines become the task's definition of done. Write `docs/ARCHITECTURE.md` only for two or more deployable parts, or boundaries the code will not show.

## 4. Plan the queue

- One task is one observable behavior that a single session can finish, with 1–5 acceptance lines copied from its R- rows and `--ref` to those IDs. Split anything bigger. Give it `--type` (feat, fix, refactor, docs, test, chore, ...); it names the task's branch and pull request.
- Give a task `--keep` entries for what must not change while it is built: file globs such as `public/*` (the runner fails `verify` when they change) or behaviors such as "the public response shape" (shown to the agent and the reviewer).
- Mark a task `--review` when checks cannot fully judge the result (visual design, wording, security, money, data deletion) or a wrong result is costly. A reviewer with fresh context must pass it before `done`.
- New project: F001 is the walking skeleton. It scaffolds the chosen stack, adds one passing example of every check the project will use (for a web app: unit, build, and a browser smoke test), and a CI workflow that runs the required checks on pull requests. In a Node project it also installs husky so every clone gets the git hooks: `npm install --save-dev husky`, `npx husky init && rm .husky/pre-commit`, then `python3 scripts/harness.py hook install`. Step 6 builds F001.
- Existing code: if the current checks fail, F001 makes them pass before any feature.
- Order by dependency. Put code that can test the riskiest assumption early.
- Queue 3–8 tasks for the first release. Later ideas stay in the PROJECT.md scope, not in the queue. Behavior that already exists and works needs no task.

## 5. Install and configure

1. Run `python3 <skill>/scripts/bootstrap.py install <repo>`. Add `--claude` when the user works in Claude Code. On a repository that already has a harness or legacy files, run with `--dry-run` first. Report conflicts; never overwrite them.
2. Put the checks in `docs/config.json` (see "Checks" in references/harness.md). Take commands from package scripts, Makefile, and CI. Required checks are the fast regression suite. Also give each task its own check that runs only the tests for its acceptance (for example `node --test test/tags.test.js`); the task itself creates that test. Web interfaces get browser tests, unless project rules forbid the tooling: then use HTTP-level tests and record the gap as an A- row. Use dynamic ports for parallel browser fixtures. Mark a startup smoke check `"wrapup": true` so every session end proves the app still starts. Mark the fast checks that only read files (format check, lint, typecheck) `"precommit": true`; the pre-commit hook runs them before every commit. CI installs the same dependencies and runs `python3 scripts/harness.py check`; local verification reads that same registry. Cache dependencies only, not integration-test outcomes. Use `cwd` and an explicit package script; missing scripts must fail.
3. Delivery: `install` writes `"delivery": {"mode": "pr", ...}`. Every finished task ships through a pull request; `done` waits for the owner to merge unless `delivery.autoMerge: true` was explicitly authorized, and pushes to the base branch are blocked (see "Delivery" in references/harness.md). Check `gh auth status --active`; a missing or logged-out `gh` is a delivery blocker to report. Recommend branch protection for the base branch in the GitHub settings; changing it is the user's decision. Use `"mode": "local"` only when the user wants no pull requests.
4. Above the harness block in `AGENTS.md`, write the project part in at most 40 lines: purpose in one line, setup, dev, and run commands, and project rules the code does not show. Leave existing instructions as they are. Link to PROJECT.md instead of copying it. No generic advice.
5. Queue the tasks: `python3 scripts/harness.py add "<behavior>" --type feat --accept "..." --check <id> --after F00n --ref R-n`, adding `--keep` and `--review` where step 4 says. Never write `docs/tasks.json` by hand.

## 6. Deliver the harness and initialize

Commit and publish only within the user’s authorization. Creating a repository and merging are separate actions; a request to open a PR does not authorize merge. Keep `autoMerge: false` unless the user authorizes automatic merge. Missing `origin`, `gh`, login or CI is a blocker, never permission to switch to local delivery. Use `"mode": "local"` only when the user chooses local delivery.

- **New project, or no GitHub remote yet, with repository creation and push authorized:**
  ```sh
  git init -b main                                      # only when there is no repository yet
  git add AGENTS.md docs scripts/harness.py .gitignore   # plus CLAUDE.md when created
  git commit -m "chore: add agent harness"
  HARNESS_BASE_PUSH=1 gh repo create <folder name> --private --source . --remote origin --push
  ```
  The repository is private, under the account `gh` uses, and named after the folder, unless the user chose another owner, name or visibility. If the name is taken, stop and ask which repository to use. When origin exists but is empty, push the same commit with `HARNESS_BASE_PUSH=1 git push -u origin main`. This push is the only direct push to the base branch.
- **Existing repository with an origin base branch:** deliver the harness through a pull request:
  ```sh
  git switch -c chore/agent-harness
  git add AGENTS.md docs scripts/harness.py .gitignore   # plus CLAUDE.md when created
  git commit -m "chore: add agent harness"
  git push -u origin chore/agent-harness
  gh pr create --base <base> --title "chore: add agent harness" --body "<what bootstrap set up>"
  gh pr checks --watch
  # Wait for the owner to merge, or merge only when explicitly authorized.
  ```
  Run `python3 scripts/harness.py check` and record the baseline. Queue fixes for unrelated failures. Confirm GitHub reports MERGED before continuing work that depends on the harness reaching the base branch.

A new project's F001 then runs through the installed `docs/workflow.md` task loop like every later task: `start F001` creates its branch, and `done F001 --proof ...` opens its pull request and waits for checks and an authorized merge.

If tools cannot be installed (no network, missing runtime), do not start F001: leave it ready and report why. Prove a new check by running its command directly. If blocked, preserve the actual task state and report the blocker. Do not reset evidence or weaken authorization just to finish bootstrap.

## 7. Validate and report

Run `python3 scripts/harness.py validate`, then `python3 scripts/harness.py wrapup --note "<what bootstrap set up; the next task>"` so the next session sees how bootstrap ended.

Report briefly:
- the mode and discovery tier, and the findings that changed scope;
- questions asked, and the defaults in use;
- files created, updated, or in conflict;
- checks, the initialization or baseline result, and the wrapup result;
- delivery: the GitHub repository (created or existing, and its visibility), pull requests into which base branch, the harness pull request or first push, `gh` status, the git hooks, and whether branch protection is on;
- the queue and its next task;
- anything unverified or blocked.

Stop here unless the user also asked you to build. If they did, follow the installed `docs/workflow.md` task loop.

## Rules that prevent known failures

- Never invent facts, check results, or links. Unknowns become A- or Q- rows.
- One home for each kind of state: tasks, evidence and notes in `docs/tasks.json` through the runner, product decisions in PROJECT.md, check and delivery settings in `docs/config.json`. Do not create plan, handoff, status, or changelog documents.
- Never overwrite user content. Edit existing docs surgically.
- After the harness commit, the base branch changes only through merged pull requests.
- Research subagents only for tier 3, on separate topics. One agent writes the docs and runs the harness.

Changing this skill: see [docs/evaluation.md](docs/evaluation.md).
