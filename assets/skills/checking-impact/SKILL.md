---
name: checking-impact
description: Finds everything a change can break - callers, text references, stored values, docs - updates it, and proves the sweep is complete; before adding a new API or type, checks whether one already exists. Use when changing, renaming, moving, or deleting a function, type, field, API, route, config key, environment variable, file path, or other shared name, when changing what something returns or how it fails, and when adding a new API, type, or module.
---
# Checking impact

Types and tests catch only part of what a change breaks. Names also live in strings, config, stored data, docs, and other packages, where no compiler looks.

## 1. List what changes

- The visible change: names, parameters, return values, fields, file paths.
- The hidden change: defaults, order, timing, error type and message, output format, side effects. Callers depend on these too.

## 2. Find every use

- Start with the language's own tools when the project has them: the type checker, the compiler, "find references" in a language server.
- Then search the text, because those tools miss strings and other languages. Search every spelling of the name: `userId`, `user_id`, `user-id`, `UserId`, `USER_ID`, and the plural.
- Search everywhere a name can appear: code, tests and test mocks, config files, environment variables, routes and URLs, SQL, migrations and stored column names, JSON and other serialized keys, scripts, CI files, docs, and other packages in the repo.
- When a tool limits its results, raise the limit until you have seen all of them.
- Change a generated file by changing its source and running the generator, not by hand.
- Count the uses. Many callers, or uses in another package or service, mean the change needs more care and its own task if it grows.

## 3. Update or stay compatible

- Inside the repo: update every use in the same change.
- When something outside the repo can depend on it (a public API, CLI, file format, stored data, event, deployed setting), don't break it. Add the new form next to the old one, or write a migration step. Ask before removing the old form.
- Before deleting code that looks unused, check why it was added: `git log -S "<code>"`. Code that was removed and later added back often marks a bug that will return.

## 4. Prove the sweep is complete

- Search again for the old name in every spelling. The search must run without error and find no active use. With `rg`, exit code 1 means no match and exit code 2 means the search failed.
- A search with no results does not prove something is unused. Names built from strings, reflection, dynamic imports, other repositories, and deployed clients don't show up. Write down what you could not check.
- When a shared interface changed, run the full required checks, not only the ones for the changed files: `python3 scripts/harness.py check`.

## Before adding a new API, type, or module

- Search for something that already does the job: three to six searches with the domain nouns, verbs, and synonyms, not only the name you planned.
- Reuse or extend what you find when it serves the same purpose. Don't reuse something only because its name is close.
- Find the commit that added the most similar existing feature, and touch the same kinds of places: exports, registrations, routes, schema, config, docs, tests.

## Report

In your final message: what changed, how many uses you found and where, what you updated, what stays for compatibility, and what you could not check.
