# Harness document templates

These are project-agnostic starting points for a small, executable working contract. A generator selects the documents that fit the project, resolves their variables, and writes them to destinations supplied by the caller.

The templates are optional documents, not a framework. Adapt the headings and remove sections that do not apply. Do not copy an empty template into a project merely to satisfy the manifest. Preserve existing project documentation when the generated document would duplicate it.

## Generator contract

1. Read `manifest.json` from this directory.
2. Select the required router and any optional documents that the project needs.
3. Supply every variable used by the selected templates, including every destination path variable. Do not infer paths from these files.
4. For every optional link in every template, resolve to an existing canonical document or a selected output. Otherwise omit the reference or its conditional section. Do not generate unused documents merely to satisfy links. Substitute variables before writing. Fail if a `{{...}}` token remains or if a selected destination is missing.
5. Create a destination only when it does not already exist, or merge deliberately with a project-specific strategy. Never overwrite existing project guidance silently.
6. Keep the router short. It should point to the generated documents and commands, while the documents hold the detailed contract.

## Template map

| ID | Source | Default use | Required |
| --- | --- | --- | --- |
| `agents-router` | `AGENTS.md.tmpl` | Root working contract and lifecycle router | Yes |
| `project-spec` | `PROJECT.md.tmpl` | Product or project requirements and acceptance criteria | Optional |
| `architecture` | `ARCHITECTURE.md.tmpl` | Boundaries, ownership, interfaces, and invariants | Optional |
| `plan` | `PLAN.md.tmpl` | Multi-session execution plan and checkpoints | Optional |
| `change` | `CHANGE.md.tmpl` | One change slice, decision record, and evidence | Optional |
| `handoff` | `SESSION_HANDOFF.md.tmpl` | Restartable current-session state | Optional |
| `reliability` | `RELIABILITY.md.tmpl` | Failure, restart, verification, and evidence contract | Optional |
| `security` | `SECURITY.md.tmpl` | Trust boundaries, secrets, authorization, and destructive actions | Optional |
| `debt` | `TECH_DEBT.md.tmpl` | Deferred work with evidence and an executable next action | Optional |

The manifest uses destination variables rather than fixed `docs/` or root paths. This lets a project keep its existing documentation layout and avoids coupling the harness to a package manager, source tree, runtime, or editor directory.

## Lifecycle represented by the documents

The router and plan describe `not_started → active → verified → passing` and `blocked` when progress cannot continue. A failed check returns the task to `active`; a stale `verified` task must be reactivated and verified again. `passing` requires recorded local evidence and successful CI; prose that claims completion is not evidence.

When the user has authorized delivery, the intended delivery path is local work on an isolated branch or worktree, local verification, a commit and push, a draft GitHub pull request, CI observation and fixes, then recording the PR URL and verified commit before marking the slice `passing`.
