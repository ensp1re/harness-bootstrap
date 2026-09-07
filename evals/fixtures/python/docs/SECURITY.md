# Security

The runner invokes explicit argv arrays without a shell. Configured working directories and
fingerprint paths must stay inside the repository root. Run logs contain command output but no
environment dump; credentials must not be placed in commands or source files.

State writes use repository-local paths, atomic replacement, and a lock. Destructive delivery and
archive transitions require explicit state and delivery evidence.
