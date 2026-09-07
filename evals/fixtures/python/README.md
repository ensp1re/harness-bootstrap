# CSV header CLI harness fixture

This disposable fixture contains a generated, Python-native working harness for a planned
CSV-header checking CLI. The product is intentionally not implemented. The local check validates
the harness state and is labeled as plumbing evidence; it does not establish product readiness.

Use the runner as:

```text
python3 scripts/harness.py --root . context
python3 scripts/harness.py --root . tasks
python3 scripts/harness.py --root . validate
```

The durable state lives under `docs/`. Evaluation runs and logs are disposable evidence
records under `docs/runs/`; those transient outputs are omitted from this public snapshot.
The empty archive directory is recoverable under `docs/archive/` when the runner creates it.
