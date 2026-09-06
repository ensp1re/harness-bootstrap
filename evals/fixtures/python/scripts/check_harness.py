#!/usr/bin/env python3
"""Independent harness-plumbing smoke check; it does not test the CSV product."""
import json
from pathlib import Path
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "docs/harness/config.json").read_text())
    tasks = json.loads((root / "docs/harness/tasks.json").read_text())
    if config.get("schemaVersion") != 1 or tasks.get("schemaVersion") != 1:
        return 1
    ids = [task.get("id") for task in tasks.get("tasks", [])]
    if len(ids) != len(set(ids)) or not all(isinstance(item, str) for item in ids):
        return 1
    print("harness plumbing ok; product acceptance not evaluated")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, json.JSONDecodeError):
        sys.exit(1)
