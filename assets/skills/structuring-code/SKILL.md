---
name: structuring-code
description: Decides where code belongs and how to split it into modules, files, and layers so the codebase stays easy to change. Use when adding a feature, module, file, or package, when deciding where code belongs, when designing the interface between two parts, or when code has become tangled, duplicated, or hard to test.
---
# Structuring code

The existing structure wins. In an existing codebase, follow its layout even if you would choose another; propose a change as its own task instead of starting a second style.

## Where code goes

- Group by feature or domain (`billing/`, `accounts/`), not by technical kind (`controllers/`, `services/`, `models/`), unless the project already does it the other way.
- Code that changes together lives together. Put new code next to the code it works with.
- Don't split one feature across many small files to look modular. Pieces that are always changed together and only make sense together belong in one place.
- No `utils`, `helpers`, `common`, or `misc` dumping grounds. A function belongs with the concept it works on. A truly generic one goes in a file named for what it holds (`dates`, `retry`).
- One concept per file. Split a file when it holds unrelated concepts, not when it reaches a line count.
- A new top-level folder or package needs a reason you can state in one line.

## Modules

A module is anything with an inside and an outside: a function, class, file, package, or service.

- Make modules deep: much useful behavior behind a small, simple interface. A caller should need to know little to use it.
- A shallow module costs more than it gives: a function or class that only renames, forwards, or wraps one call adds a name to learn and nothing else. Inline it.
- Deletion test: imagine deleting the module and putting its code into the callers. If complexity goes away, the module was not helping. If complexity spreads into many callers, it earns its place.
- Hide each decision that may change (storage format, outside service, algorithm) inside one module, so changing it touches one place.
- Keep the interface small: few functions, few parameters, simple types. Don't expose internals in case a caller might want them.

## Dependencies and boundaries

- Core logic (rules, calculations, decisions) does no input or output. It takes values and returns values. Database, network, files, clock, and randomness live at the edges and call the core. The core is then tested without fakes.
- Use another module only through its public interface. Don't reach into its private functions, fields, or files; add what you need to its interface, or move the code to where it belongs.
- No import cycles. If two modules need each other, a concept is split in the wrong place: move the shared part into one of them, or into a third module.
- Add an interface or a passed-in dependency (a seam: a point where one implementation can be swapped for another) only when a second implementation actually exists. A test fake counts only when the real thing is slow, costly, or not repeatable.
- Each outside system (API, SDK, database, queue) is used through one module that converts its data into your own types. The rest of the code never sees the outside shapes.
- Validate and convert outside data once, at the boundary. Inside, pass your own types.

## Data

- Give a domain value its own type (money, an ID, a status) only when mixing it up is likely or has already caused a bug, such as two kinds of ID passed to the same function, or amounts in different units. Don't wrap every string or number.
- Show states with one enum or tagged type instead of several booleans that can contradict each other.

## Duplication

- Two similar pieces of code are fine. Extract a shared one on the third copy, and only when all copies change for the same reason.
- Code that looks the same but changes for different reasons stays separate.
- A wrong shared abstraction is worse than duplication. When a shared function grows flags to serve different callers, split it back.

## Public interfaces (APIs, CLIs, file formats, events, stored data)

- Change by adding: new optional fields, new endpoints. Don't rename, remove, or change the meaning of existing ones without a migration step; `checking-impact` covers how.
- One error shape and one naming style across the whole interface.
- Callers will depend on everything they can observe, including order, timing, and error text. Keep the observable surface small.

## When you find tangled code

- Don't restructure in the middle of a feature or fix. Finish the task in the current shape, then propose the restructure as a separate task with the reason and the files it touches.
- A restructure must reduce what a reader has to keep in mind. Moving code into more files without that is not an improvement.
