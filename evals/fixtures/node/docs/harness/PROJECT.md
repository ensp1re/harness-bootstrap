# JSON formatter CLI

## Outcome

Provide a local Node CLI that reads one JSON value from stdin and writes normalized JSON to stdout.

## Constraints

- Preserve the existing package scripts and repository instructions.
- Use two-space indentation and a trailing newline.
- Keep the implementation local and dependency-free.

## Acceptance

- Valid JSON is formatted deterministically.
- Invalid JSON exits non-zero with a useful diagnostic.
- The existing test script remains runnable.

Local rule: keep formatter changes reviewable.
