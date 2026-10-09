# harness-bootstrap

A skill for coding agents (Codex, Claude Code) that turns a project idea, a written spec, or an existing repository into a harness agents can work in. The harness has four parts:

- a project definition backed by research;
- a small task queue with real checks;
- a runner that tracks tasks and verification evidence;
- handoff between sessions.

## Use it

Copy this folder as `harness-bootstrap` into your agent's skills directory (for example `~/.codex/skills/` or `~/.claude/skills/`), then ask:

```text
$harness-bootstrap
I want to build a website where neighbours can lend each other tools. Set it up so agents can build it.
```

## What happens

1. **Inspect.** `scripts/bootstrap.py inspect` lists the stack, commands, CI, instruction files, and any existing harness.
2. **Discover.** Research depth follows uncertainty and stakes: tiers 0–3, each with a search budget and stop rules. The agent asks at most 3 questions, each with a default.
3. **Define.** The agent writes `docs/PROJECT.md`: users and their jobs, scope, domain terms, and ID'd rows for requirements (Given/When/Then acceptance and a check), decisions, assumptions, and open questions. When research ran, `docs/RESEARCH.md` holds cited, dated facts.
4. **Plan.** 3–8 small tasks, starting with a walking skeleton that makes every check type pass once.
5. **Install.** `scripts/bootstrap.py install` copies the runner to `scripts/harness.py`, adds the harness block to `AGENTS.md`, and creates `docs/tasks.json` and `docs/config.json`. Reruns never overwrite edited content.
6. **Deliver and initialize.** A new project gets a private GitHub repository and one direct push of the harness commit. The walking skeleton (F001) then goes through the task loop and a pull request, like every later task.
7. **Report.** Findings, defaults in use, checks and their baseline, the wrapup result, and the next task.

In a bootstrapped repository, start with `python3 scripts/harness.py status`.
The short AGENTS.md entry links to `docs/workflow.md`, which works without the installed skill.
Tasks follow `start` → reproduce and fix → `verify --proof` → independent review when required → commit → `done`.
Proof names passing checks. Source, config or task-constraint changes invalidate verification and review.

`done` opens a PR and checks CI. Missing CI stays pending; only successful results pass.
The owner merges unless automatic merge was explicitly authorized. Missing remote or GitHub CLI
never silently switches to local delivery. Set local mode only when the user chooses it.
Local checks and CI use the same `docs/config.json` registry via `python3 scripts/harness.py check`.

Requirement: Python 3.8+ where agents and CI run the harness.

## Layout

| Path | When an agent reads it |
|---|---|
| `SKILL.md` | when the skill triggers |
| `references/discovery.md` | when the product is not fully defined |
| `references/harness.md` | when choosing checks, rerunning, migrating, or debugging |
| `assets/` | never in full: copied (runner, AGENTS block) or filled in (templates) |
| `scripts/bootstrap.py` | never: it is run |
| `tests/`, `docs/evaluation.md`, `docs/design-notes.md` | only when changing this skill |

Upgrading a project bootstrapped with 1.x: see "Migrating" in [references/harness.md](references/harness.md).

## Validate the bundle

```sh
python3 assets/harness.py check
```

Evaluation protocol and results: [evaluation guide](docs/evaluation.md), [historical results](docs/evaluation-history.md).
