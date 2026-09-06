# Harness research rationale

Accessed 2026-09-06. This note supports a standalone, portable repository harness. It is a design input for the skill, not a Qyre product specification.

## Decision

Use a small repository-local harness with five separable concerns:

1. versioned change artifacts for intent, scope, and handoff;
2. an explicit task state machine with dependencies and ownership;
3. an append-only run log plus a compact current-state snapshot;
4. a deterministic verifier that records observed check outcomes;
5. optional isolated workers and fresh-context review for tasks that benefit from them.

The default path should remain one bounded task in one workspace. A tracker daemon, database-backed scheduler, multi-agent swarm, or model-based evaluator is an extension selected by task shape and operational need.

## Alternatives and useful mechanisms

| Project | Concrete mechanism | Borrow | Cost or limitation |
|---|---|---|---|
| [OpenAI Symphony](https://github.com/openai/symphony/blob/main/SPEC.md) ([announcement, Apr. 27, 2026](https://openai.com/index/open-source-codex-orchestration-symphony/)) | Normalized issues feed a bounded orchestrator; each issue has a deterministic workspace, attempts, retries/backoff, stall handling, session metadata, and a repository-owned `WORKFLOW.md`. | Model `Task`, `Workspace`, `RunAttempt`, and `LiveSession`; keep orchestration state authoritative; reconcile eligibility before dispatch. | The reference Elixir implementation is explicitly an evaluation prototype for trusted environments. Some blocked state is memory-only, and exact in-memory scheduler state is not restored. A local skill should extract the state model without requiring Linear, Elixir, or a daemon. |
| [GitHub Spec Kit](https://github.com/github/spec-kit) ([agentic SDD](https://github.com/github/spec-kit/blob/main/docs/reference/agentic-sdd.md), [workflow architecture](https://github.com/github/spec-kit/blob/main/workflows/ARCHITECTURE.md), [docs updated Aug. 21, 2026](https://github.github.com/spec-kit/)) | Spec → plan → tasks → implement → converge; YAML workflows support gates, loops, fan-out/fan-in, and `RunState` persisted after each step. | Persist run ID, current step, step results, inputs, and an append-only log; support explicit human gates and read-only cross-artifact analysis. | The full CLI generates many integration files and maintains shell, PowerShell, and Python script variants. Its checklists and artifacts still need an external verifier; they are not proof by themselves. |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) ([concepts](https://github.com/Fission-AI/OpenSpec/blob/main/docs/overview.md), [CLI](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md)) | A change folder contains proposal, delta specs, design, and tasks. Artifact schemas declare dependencies; `status --json`, `instructions --json`, `validate`, and transactional `archive` expose machine-readable progress. | Use one change directory per bounded feature, delta artifacts for brownfield behavior, dependency-ordered status, JSON output, and archive only after validation. | It is a Node CLI and its task checkboxes remain agent-editable. The current v1.12.0 release (2026-09-03) improves validation and archive behavior, but the tool is still a broad workflow system rather than a minimal bootstrap. |
| [Beads](https://github.com/gastownhall/beads) ([coordination](https://github.com/gastownhall/beads/blob/main/docs/multi-agent/coordination.md), [sync model](https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md)) | Dolt-backed dependency graph; `ready` finds unblocked work, `update --claim` atomically claims it, assignees/comments/labels record ownership, and merge slots serialize conflict-prone work. | Borrow stable IDs, `blocked_by`, atomic claims, ownership, append-only notes, and deterministic ready-work calculation. | It requires a system-wide `bd` binary and Dolt storage for its full model. JSONL is an export rather than the canonical sync channel. Its v1.2.2 release (2026-08-15) was a recovery release after accidental untested releases caused schema skew, so any adoption requires pinned versions, backup, and migration discipline. |
| [OpenHands Software Agent SDK](https://github.com/OpenHands/software-agent-sdk) ([persistence guide](https://docs.openhands.dev/sdk/guides/convo-persistence), [SDK paper, Nov. 5, 2025](https://arxiv.org/abs/2511.03690), [task-tracker gaps](https://github.com/OpenHands/software-agent-sdk/issues/2040)) | Stable conversation IDs; mutable base state is snapshotted while messages, tool calls, and observations append to event files; state auto-saves and resumes. Local and remote workspaces share an abstraction. | Use `snapshot + append-only events`, stable run IDs, and an execution/workspace boundary. Keep the state format provider-neutral. | The SDK includes Python/TypeScript/REST APIs, tools, remote workspaces, and sandbox/runtime concerns. Its own task tracker has lacked dependency, stable-ID, and ownership features, so it complements rather than replaces a task graph. |

## Evidence conflicts and resulting policy

The sources do not support one universal workflow.

- **Gates versus fluid artifacts:** Spec Kit describes flow-back, flow-forward, and living-spec persistence models; OpenSpec says artifacts can be revised at any point rather than treated as rigid phases. The harness should declare the repository’s artifact policy, then enforce only the chosen invariants. It should not force every task through a heavyweight ceremony.
- **Files versus a database:** Symphony deliberately supports restart recovery without a persistent scheduler database; Spec Kit persists JSON run state; OpenHands separates a snapshot from an event log; Beads uses Dolt as canonical storage. The portable baseline should use files or SQLite locally, with an adapter boundary for a tracker or durable database when needed.
- **Closure versus proof:** Beads can close a task and OpenSpec can archive a change, but neither action independently proves that the implementation works. The skill distinguishes locally `verified` from delivered `passing`; archival is retention, not proof. See contract.md for normative states.
- **Parallelism versus coordination:** Symphony and Beads provide bounded dispatch, claims, and merge controls. OpenHands supports resumable subagents. These mechanisms reduce manual coordination only when work is independent and isolated. They do not establish a universal speed or quality advantage, so single-agent execution is the default and multi-agent mode must be budgeted and evaluated.

The performance numbers reported by first-party projects are context-specific internal reports, not a common benchmark. This note makes no universal claim about throughput, quality, token cost, or model superiority. Compare modes with the same task set, total token/compute budget, verifier, and intervention policy before enabling parallel workers or extra evaluator passes.

The dated source points used here are: Symphony’s OpenAI announcement (2026-04-27), Spec Kit’s documentation update (2026-08-21), OpenSpec v1.12.0 (2026-09-03), Beads v1.2.2 (2026-08-15), and the OpenHands SDK paper (2025-11-05). Repository pages are fast-moving; pin any implementation dependency and re-check release notes before copying commands or schemas.

## Adopted baseline for the skill

These are conceptual primitives; contract.md defines normative names and states, and existing project paths take precedence:

- `GOALS.md` for outcome, scope, non-goals, and constraints;
- `PLANS.md` or a per-change plan for decisions, progress, discoveries, and planned verification;
- a bounded task record with stable ID, dependencies, owner, workspace, attempt, commit, next action, and status;
- `events.jsonl` plus `state.json` per run;
- idempotent initialization and baseline smoke scripts;
- a verifier that records command, exit status, commit/worktree, artifact paths or hashes, verifier version, and timestamp;
- an optional read-only evaluator that cannot mutate authoritative pass state;
- isolated worktrees and atomic claims only when multi-agent mode is explicitly enabled.

The verifier must reject completion based solely on an agent summary, unchecked task prose, a `COMPLETE` marker, or a model-generated review. Hooks guide the agent; CI supplies an additional execution boundary. Repository-local records are not tamper-proof against a writer with access to the repository. Stronger assurance requires separately protected verification infrastructure.

## Qyre extraction facts

These are local repository facts, separated from the external research above. The repository’s `AGENTS.md` describes Qyre as a local-first, role-aware database UI for Postgres, MySQL, SQLite, and MongoDB, with writes gated by connected-user grants and a hard `--read-only` override. Its working contract requires compact startup context (`pwd`, `pnpm context`, the active feature, linked spec, and relevant architecture documents), feature-scoped changes, and verification before a feature can be marked passing. It also names repository documents for plans, reliability, security, and session handoff, and standard checks including `pnpm verify:pr`.

Therefore the bootstrap should stay repository-local and adapter-neutral, preserve explicit handoff/verification records, and avoid requiring an external issue tracker or agent service. Qyre can later add a tracker adapter, cross-engine conformance evidence, or isolated worker mode without changing the portable artifact and verifier contracts.

## Findings that changed the design

- [LangChain Deep Agents v0.7, July 29 2026](https://www.langchain.com/blog/deep-agents-v0-7): removed generic base prompting and made todo middleware optional after evaluations. Keep durable project tracking, but avoid imposing extra planning tools and rituals on every task. Vendor evaluation, not proof for every project.
- [GSD verification](https://github.com/open-gsd/gsd-core/blob/main/docs/how-to/verify-and-ship.md): fingerprints covered implementation and requirement inputs, invalidating stale verdicts. Borrow this behavior without mandatory fresh workers for every step.
- [Factory compression evaluation, December 16 2025](https://factory.com/news/evaluating-compression): evaluates recall, artifact tracking, decisions and continuation; artifact retention remained weak. Use executable handoff probes and mechanically captured facts, not summary length as the quality metric. Results use an LLM judge on vendor-collected sessions.
- [Cursor dynamic context](https://cursor.com/blog/dynamic-context-discovery): preserve large tool outputs in files and retrieve relevant portions. Compact startup output should reference retained evidence rather than discard it.
- [Evaluating AGENTS.md](https://arxiv.org/abs/2602.11988) finds added repository context can increase cost without significant completion gains, whereas [Vercel's Next.js evaluation](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals) favors a compressed docs index. Different task scopes support a narrow router with useful missing knowledge, not automatic documentation expansion.
- [Google's agent-scaling research](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/) finds benefits depend on task decomposition. Keep selective independent research/review and one owner for shared state.
- [Anthropic infrastructure noise](https://www.anthropic.com/engineering/infrastructure-noise): environment resources affect outcomes. Record toolchain and failure categories and match environments when comparing harness variants.
- [Ralph loop source](https://github.com/snarktank/ralph/blob/main/ralph.sh): a completion string terminates the loop. Bounded repetition does not replace verification. Do not copy permission-bypass defaults.

No source above establishes this combination as universally best. The shipped evaluation record distinguishes observed checks from planned comparative experiments.
