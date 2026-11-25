---
name: writing-code
description: Gives the rules for writing or changing code so it stays small, clear, and consistent with the codebase, and lists the signs of careless generated code to remove. Use before writing or editing code in any language - features, fixes, refactors, scripts.
---
# Writing code

Project rules (AGENTS.md, `docs/workflow.md`, linters, formatters) win over this skill. When a change renames, moves, deletes, or changes the behavior of something other code uses, also follow `checking-impact`.

## Before you write

1. Read the code you will change and the code that calls it. Follow the real flow from input to output.
2. Search for what already exists: a helper, type, constant, pattern, or installed library that does the job. Reuse it. A second copy of something that lives a few files away is the most common mistake.
3. Find the closest existing feature like the one you are adding, and the commit that added it (`git log -- <its files>`). Follow its shape, and touch the same kinds of places it touched: exports, routes, schema, config, docs, tests.
4. Don't guess an API. Read the installed version's source, types, or docs, and run it when unsure. Calling a function or option that does not exist is the most common runtime bug in generated code.

## Scope

- Every changed line traces to the task. Don't reformat, rename, or improve code next to your change.
- Remove what your change made unused. Mention other dead code; don't delete it.
- No new dependency without asking.

## Simplicity

- Write the least code that solves today's problem. No options, flags, settings, hooks, or extension points nobody asked for.
- No abstraction with one user: no interface with one implementation, base class with one child, factory for one product, or wrapper that only passes calls through.
- Prefer the standard library and platform features over custom code.
- If the code grows much longer than you expected, stop and look for the simpler way before you continue.

## Names

- Name things by what they mean in the domain (the terms in `docs/PROJECT.md`), not by how they are built: `unpaidInvoices`, not `filteredData`.
- Avoid empty names: data, info, item, result, temp, value, handler, manager, helper, util. Fine only inside a few lines.
- One thing has one name everywhere. Follow the naming style the code already uses for the same kind of thing.

## Functions

- One job per function. Handle edge cases first and return early instead of nesting deeply.
- A boolean parameter that switches behavior usually means two functions.
- Don't split a short function into several pieces used once. Mixed jobs are the problem, not length.

## Values

- A literal used in several places gets one named constant, defined once. A value used once whose meaning is clear where it is used stays a literal.
- One source of truth for each fact. Don't store what you can compute cheaply, and don't keep two fields that must stay in sync.

## Errors

- Validate input where it enters the system: user input, files, network, environment. Inside, trust your own types and calls; don't re-check the same thing in every layer.
- Catch the specific error you expect, never everything. Catch only when you can do something useful: retry, add context, convert it to the error your caller expects, or clean up. Never catch and ignore.
- No silent fallbacks. Don't return an empty list, null, zero, or a default to hide a failure, and don't let null-safe operators or defaults (`?.`, `??`, `or default`) silently skip work that must happen. A wrong value that looks right is worse than a crash.
- An error message says what failed and with which value: `config file not found: /etc/app.json`, not `an error occurred`.
- Use the project's existing error style (exceptions, result values, error codes). Don't mix styles.

## Comments

- None by default. Comment only a reason the code cannot show: an outside bug or quirk, a non-obvious limit, a safety rule, a link to a spec.
- Never write: comments that repeat the code; step-by-step narration ("Step 1", "First", "Next"); comments that narrate the change ("added X", "now uses Y"); section banners or end-of-block markers; emoji; commented-out code; TODOs without a task; docstrings that only repeat the function signature.
- Docstrings only on public interfaces, or where the project requires them.

## Signs of careless code

Remove these from your own change before you finish:

- error handling around code that cannot fail, or a catch-all handler
- debug prints and logs
- unused parameters, imports, variables, branches
- a copy of a helper that already exists
- wrappers and classes that add nothing
- null checks for values that are never null
- "just in case" options nobody passes
- compatibility code for something that was never released
- type escapes and lint-ignore markers used to silence an error instead of fixing it
- tests or checks weakened or skipped to make them pass

Keep a pattern the project uses the same way on purpose, such as the defensive checks or logging a module does everywhere, or one the user asked for. When you cannot tell whether something is careless or deliberate, leave it and mention it.

## Before you say done

- Read the whole diff as a reviewer would. Remove anything the task did not need.
- Run the checks. Done means they pass on the current files.
