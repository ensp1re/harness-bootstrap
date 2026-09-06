#!/usr/bin/env python3
"""Small, stack-native harness runner for the disposable Python fixture."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

try:
    import fcntl
except ImportError:  # pragma: no cover - the fixture runs on POSIX
    fcntl = None


SCHEMA = 1
ID_RE = re.compile(r"^F\d{3,}$")
STATES = {"not_started", "active", "blocked", "verified", "passing"}
RUN_STATUSES = {"running", "passed", "failed", "interrupted"}


class Problem(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.message = message
        self.code = code


class StateProblem(Problem):
    def __init__(self, message: str):
        super().__init__(message, 1)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_text(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def root_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise Problem(f"root is not a directory: {value}")
    return path


def safe_path(root: Path, relative: str, *, allow_missing: bool = True) -> Path:
    """Resolve a repository-relative path while rejecting traversal and escaping symlinks."""
    if not isinstance(relative, str) or not relative:
        raise Problem("path must be a non-empty relative string")
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or any(part in {"..", "~"} for part in candidate.parts):
        raise Problem(f"path escapes root: {relative}")
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            resolved = current.resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise Problem(f"symlink escapes root: {relative}") from exc
    result = (root / Path(*candidate.parts)).resolve(strict=False)
    try:
        result.relative_to(root)
    except ValueError as exc:
        raise Problem(f"path escapes root: {relative}") from exc
    if not allow_missing and not result.exists():
        raise Problem(f"missing path: {relative}")
    return result


def rel_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def load_json(path: Path, label: str) -> dict:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise Problem(f"missing {label}: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise Problem(f"malformed {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Problem(f"{label} must be a JSON object")
    return value


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        with temp.open("x", encoding="utf-8") as handle:
            handle.write(json_text(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


@contextmanager
def state_lock(root: Path):
    lock_path = safe_path(root, "docs/harness/.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def paths(root: Path) -> dict[str, Path]:
    return {
        "config": safe_path(root, "docs/harness/config.json"),
        "tasks": safe_path(root, "docs/harness/tasks.json"),
        "handoff": safe_path(root, "docs/harness/handoff.json"),
        "handoff_md": safe_path(root, "docs/harness/SESSION_HANDOFF.md"),
        "archive": safe_path(root, "docs/harness/archive/tasks.json"),
        "runs": safe_path(root, "docs/harness/runs"),
    }


def validate_config(config: dict, root: Path) -> list[str]:
    errors: list[str] = []
    if config.get("schemaVersion") != SCHEMA:
        errors.append("config schemaVersion must be 1")
    checks = config.get("checks")
    if not isinstance(checks, list):
        errors.append("config checks must be a list")
        checks = []
    seen: set[str] = set()
    for index, check in enumerate(checks):
        prefix = f"checks[{index}]"
        if not isinstance(check, dict):
            errors.append(f"{prefix} must be an object")
            continue
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id:
            errors.append(f"{prefix}.id must be non-empty")
        elif check_id in seen:
            errors.append(f"duplicate check id: {check_id}")
        else:
            seen.add(check_id)
        argv = check.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
            errors.append(f"{prefix}.argv must be a non-empty string list")
        cwd = check.get("cwd", ".")
        try:
            safe_path(root, cwd, allow_missing=False)
        except Problem as exc:
            errors.append(f"{prefix}.cwd invalid: {exc.message}")
        timeout = check.get("timeoutSeconds")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            errors.append(f"{prefix}.timeoutSeconds must be positive")
        if not isinstance(check.get("required", True), bool):
            errors.append(f"{prefix}.required must be boolean")
    fingerprint_paths = config.get("fingerprintPaths")
    if not isinstance(fingerprint_paths, list) or not all(isinstance(item, str) for item in fingerprint_paths):
        errors.append("config fingerprintPaths must be a string list")
    else:
        for item in fingerprint_paths:
            try:
                safe_path(root, item)
            except Problem as exc:
                errors.append(f"fingerprint path invalid ({item}): {exc.message}")
    if not isinstance(config.get("delivery", {}), dict):
        errors.append("config delivery must be an object")
    return errors


def archive_tasks(archive: dict) -> list[dict]:
    value = archive.get("tasks", [])
    return value if isinstance(value, list) else []


def validate_task_shape(task: object, index: int, root: Path, check_ids: set[str]) -> list[str]:
    errors: list[str] = []
    prefix = f"tasks[{index}]"
    if not isinstance(task, dict):
        return [f"{prefix} must be an object"]
    task_id = task.get("id")
    if not isinstance(task_id, str) or not ID_RE.fullmatch(task_id):
        errors.append(f"{prefix}.id must match F followed by at least three digits")
    behavior = task.get("behavior")
    if not isinstance(behavior, str) or not behavior.strip():
        errors.append(f"{prefix}.behavior must be non-empty")
    acceptance = task.get("acceptance")
    if not isinstance(acceptance, list) or not acceptance or not all(isinstance(item, str) and item.strip() for item in acceptance):
        errors.append(f"{prefix}.acceptance must be a non-empty string list")
    deps = task.get("dependsOn", [])
    if not isinstance(deps, list) or not all(isinstance(item, str) for item in deps):
        errors.append(f"{prefix}.dependsOn must be a string list")
    elif len(deps) != len(set(deps)):
        errors.append(f"{prefix}.dependsOn contains duplicates")
    state = task.get("state")
    if state not in STATES:
        errors.append(f"{prefix}.state is invalid: {state}")
    for field in ("spec", "plan"):
        value = task.get(field)
        if value is not None:
            try:
                safe_path(root, value, allow_missing=False)
            except Problem as exc:
                errors.append(f"{prefix}.{field} invalid: {exc.message}")
    verification = task.get("verification", [])
    if not isinstance(verification, list) or not all(isinstance(item, str) for item in verification):
        errors.append(f"{prefix}.verification must be a string list")
    else:
        for check_id in verification:
            if check_id not in check_ids:
                errors.append(f"{prefix} references unknown check: {check_id}")
    if state == "blocked" and (not isinstance(task.get("blockedReason"), str) or not task["blockedReason"].strip()):
        errors.append(f"{prefix}.blockedReason is required for blocked tasks")
    if state in {"verified", "passing"} and not isinstance(task.get("evidence"), dict):
        errors.append(f"{prefix}.evidence is required for {state} tasks")
    if task.get("evidence") is not None and not isinstance(task.get("evidence"), dict):
        errors.append(f"{prefix}.evidence must be an object or null")
    if task.get("delivery") is not None and not isinstance(task.get("delivery"), dict):
        errors.append(f"{prefix}.delivery must be an object or null")
    return errors


def validate_tasks(tasks: dict, archive: dict, root: Path, config: dict) -> list[str]:
    errors: list[str] = []
    if tasks.get("schemaVersion") != SCHEMA:
        errors.append("tasks schemaVersion must be 1")
    if archive.get("schemaVersion") != SCHEMA:
        errors.append("archive schemaVersion must be 1")
    live = tasks.get("tasks")
    archived = archive_tasks(archive)
    if not isinstance(live, list):
        errors.append("tasks.tasks must be a list")
        live = []
    check_ids = {item.get("id") for item in config.get("checks", []) if isinstance(item, dict)}
    ids: dict[str, str] = {}
    for index, task in enumerate(live):
        errors.extend(validate_task_shape(task, index, root, check_ids))
        if isinstance(task, dict):
            task_id = task.get("id")
            if isinstance(task_id, str):
                if task_id in ids:
                    errors.append(f"duplicate task id: {task_id}")
                ids[task_id] = "live"
    for index, task in enumerate(archived):
        errors.extend(validate_task_shape(task, index, root, check_ids))
        if isinstance(task, dict):
            task_id = task.get("id")
            if isinstance(task_id, str):
                if task_id in ids:
                    errors.append(f"duplicate task id across live/archive: {task_id}")
                ids[task_id] = "archive"
    if not isinstance(tasks.get("nextId"), int) or isinstance(tasks.get("nextId"), bool) or tasks.get("nextId", 0) <= 0:
        errors.append("tasks.nextId must be a positive integer")
    else:
        numeric_ids = [int(item[1:]) for item in ids if ID_RE.fullmatch(item)]
        if numeric_ids and tasks["nextId"] <= max(numeric_ids):
            errors.append("tasks.nextId must be greater than every task number")
    live_by_id = {task.get("id"): task for task in live if isinstance(task, dict)}
    archived_by_id = {task.get("id"): task for task in archived if isinstance(task, dict)}
    for task in live:
        if not isinstance(task, dict):
            continue
        task_id = task.get("id")
        for dep in task.get("dependsOn", []) if isinstance(task.get("dependsOn"), list) else []:
            if dep not in ids:
                errors.append(f"{task_id} depends on missing task: {dep}")
        if task_id in (task.get("dependsOn") or []):
            errors.append(f"{task_id} depends on itself")
    graph = {task_id: [dep for dep in task.get("dependsOn", []) if dep in ids]
             for task_id, task in live_by_id.items()}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            errors.append(f"dependency cycle includes {task_id}")
            return
        if task_id in visited:
            return
        visiting.add(task_id)
        for dep in graph.get(task_id, []):
            if dep in graph:
                visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id)
    active = [task for task in live if isinstance(task, dict) and task.get("state") == "active"]
    if len(active) > 1:
        errors.append("at most one live task may be active")
    return errors


def load_state(root: Path) -> tuple[dict, dict, dict, dict[str, Path]]:
    locations = paths(root)
    config = load_json(locations["config"], "config")
    tasks = load_json(locations["tasks"], "tasks")
    archive = load_json(locations["archive"], "archive")
    handoff = load_json(locations["handoff"], "handoff") if locations["handoff"].exists() else {
        "schemaVersion": SCHEMA,
        "decisions": [],
        "rejectedApproaches": [],
        "blockers": [],
        "nextAction": None,
    }
    return config, tasks, archive, {**locations, "handoff_data": handoff}  # type: ignore[return-value]


def recover_running(root: Path, locations: dict[str, Path]) -> list[str]:
    recovered: list[str] = []
    run_dir = locations["runs"]
    if not run_dir.exists():
        return recovered
    for run_path in sorted(run_dir.glob("*.json")):
        try:
            record = load_json(run_path, "run record")
        except Problem:
            continue
        if record.get("status") == "running":
            record["status"] = "interrupted"
            record["endedAt"] = utc_now()
            record["recovered"] = True
            atomic_write_json(run_path, record)
            recovered.append(str(record.get("attemptId", run_path.stem)))
    return recovered


def canonical_file_bytes(root: Path, relative: str, path: Path) -> bytes:
    if relative == "docs/harness/tasks.json" and path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            for task in value.get("tasks", []) if isinstance(value, dict) else []:
                if isinstance(task, dict):
                    for field in ("state", "evidence", "blockedReason", "delivery"):
                        task.pop(field, None)
            return json_text(value).encode()
        except (OSError, ValueError):
            pass
    return path.read_bytes()


def fingerprint(root: Path, config: dict) -> str:
    entries: list[dict[str, str]] = []
    for configured in config.get("fingerprintPaths", []):
        path = safe_path(root, configured)
        if not path.exists():
            entries.append({"path": configured, "sha256": "<missing>"})
            continue
        if path.is_file():
            entries.append({"path": configured, "sha256": hashlib.sha256(canonical_file_bytes(root, configured, path)).hexdigest()})
            continue
        for child in sorted(path.rglob("*")):
            if not child.is_file() or any(part in {"runs", "archive", "__pycache__"} for part in child.relative_to(path).parts):
                continue
            child_rel = f"{configured.rstrip('/')}/{child.relative_to(path).as_posix()}"
            entries.append({"path": child_rel, "sha256": hashlib.sha256(child.read_bytes()).hexdigest()})
    return hashlib.sha256(json_text(entries).encode()).hexdigest()


def evidence_fresh(task: dict, current: str) -> bool:
    evidence = task.get("evidence")
    return isinstance(evidence, dict) and evidence.get("fingerprint") == current and evidence.get("status") == "passed"


def git_facts(root: Path) -> dict:
    if not (root / ".git").exists():
        return {"available": False, "branch": None, "revision": None, "dirty": None}

    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(["git", "-C", str(root), *args], check=False, capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    branch = git("symbolic-ref", "--short", "HEAD")
    revision = git("rev-parse", "HEAD")
    dirty_output = git("status", "--porcelain")
    available = branch is not None or revision is not None or dirty_output is not None
    return {"available": available, "branch": branch, "revision": revision, "dirty": bool(dirty_output) if dirty_output is not None else None}


def ready_tasks(tasks: dict, archive: dict) -> list[str]:
    all_tasks = {task.get("id"): task for task in tasks.get("tasks", []) if isinstance(task, dict)}
    all_tasks.update({task.get("id"): task for task in archive_tasks(archive) if isinstance(task, dict)})
    ready: list[str] = []
    for task in tasks.get("tasks", []):
        if not isinstance(task, dict) or task.get("state") != "not_started":
            continue
        if all(all_tasks.get(dep, {}).get("state") == "passing" for dep in task.get("dependsOn", [])):
            ready.append(task["id"])
    return sorted(ready, key=lambda value: int(value[1:]) if ID_RE.fullmatch(value) else value)


def render_handoff(data: dict) -> str:
    def bullets(items: object) -> str:
        if not isinstance(items, list) or not items:
            return "- None recorded"
        return "\n".join(f"- {item}" for item in items)

    verification = data.get("verification", [])
    if not isinstance(verification, list) or not verification:
        verification_text = "- None recorded"
    else:
        verification_text = "\n".join(
            f"- {item.get('id', 'check')}: {item.get('status', 'unknown')}" if isinstance(item, dict) else f"- {item}"
            for item in verification
        )
    return (
        "# Session handoff\n\n"
        "Keep this file current-only and restartable.\n\n"
        "## Run identity\n\n"
        f"- Updated at: {data.get('updatedAt')}\n"
        f"- Active slice: {data.get('activeTask') or 'None'}\n"
        f"- Branch or worktree: {data.get('branch') or 'Unavailable'}\n"
        f"- Base commit: {data.get('revision') or 'Unavailable'}\n"
        "- Tracking: `docs/harness/tasks.json`\n\n"
        "## Completed\n\n"
        f"{bullets(data.get('completed'))}\n\n"
        "## Exact next action\n\n"
        f"{data.get('nextAction') or 'Inspect the ready queue and choose the next authorized slice.'}\n\n"
        "## Verification evidence\n\n"
        f"{verification_text}\n\n"
        "## Blockers and decisions\n\n"
        "Blockers:\n"
        f"{bullets(data.get('blockers'))}\n\n"
        "Decisions:\n"
        f"{bullets(data.get('decisions'))}\n\n"
        "Rejected approaches:\n"
        f"{bullets(data.get('rejectedApproaches'))}\n"
    )


def parse_transition_args(rest: list[str]) -> tuple[str, str | None]:
    if not rest:
        raise Problem("transition requires a reason or delivery evidence when applicable")
    reason: str | None = None
    index = 0
    while index < len(rest):
        if rest[index] == "--reason" and index + 1 < len(rest):
            reason = rest[index + 1]
            index += 2
        elif rest[index] == "--delivery-json" and index + 1 < len(rest):
            reason = rest[index + 1]
            index += 2
        else:
            raise Problem(f"unknown transition option: {rest[index]}")
    return reason or "", reason


def get_task(tasks: dict, task_id: str) -> dict:
    for task in tasks.get("tasks", []):
        if isinstance(task, dict) and task.get("id") == task_id:
            return task
    raise StateProblem(f"unknown live task: {task_id}")


def deps_ready(task: dict, tasks: dict, archive: dict) -> bool:
    all_tasks = {item.get("id"): item for item in tasks.get("tasks", []) if isinstance(item, dict)}
    all_tasks.update({item.get("id"): item for item in archive_tasks(archive) if isinstance(item, dict)})
    return all(all_tasks.get(dep, {}).get("state") == "passing" for dep in task.get("dependsOn", []))


def command_validate(root: Path) -> tuple[dict, int]:
    with state_lock(root):
        config, tasks, archive, locations = load_state(root)
        recovered = recover_running(root, locations)
        errors = validate_config(config, root) + validate_tasks(tasks, archive, root, config)
        current = None
        try:
            current = fingerprint(root, config)
        except Problem as exc:
            errors.append(exc.message)
        freshness: dict[str, bool] = {}
        for task in tasks.get("tasks", []) if isinstance(tasks.get("tasks"), list) else []:
            if isinstance(task, dict) and task.get("state") in {"verified", "passing"} and current is not None:
                freshness[task.get("id", "unknown")] = evidence_fresh(task, current)
                if not freshness[task.get("id", "unknown")]:
                    errors.append(f"stale evidence: {task.get('id')}")
        payload = {"ok": not errors, "schemaVersion": SCHEMA, "errors": errors, "freshness": freshness, "recovered": recovered}
        return payload, 0 if not errors else 1


def command_context(root: Path) -> tuple[dict, int]:
    with state_lock(root):
        config, tasks, archive, locations = load_state(root)
        recovered = recover_running(root, locations)
        errors = validate_config(config, root) + validate_tasks(tasks, archive, root, config)
        current = fingerprint(root, config)
        active = [task for task in tasks.get("tasks", []) if isinstance(task, dict) and task.get("state") == "active"]
        stale = [task.get("id") for task in tasks.get("tasks", []) if isinstance(task, dict) and task.get("state") in {"verified", "passing"} and not evidence_fresh(task, current)]
        blockers = [
            {"task": task.get("id"), "reason": task.get("blockedReason")}
            for task in tasks.get("tasks", [])
            if isinstance(task, dict) and task.get("state") == "blocked"
        ]
        blockers.extend({"task": task_id, "reason": "stale evidence"} for task_id in stale)
        handoff = locations["handoff_data"]
        if active:
            next_action = f"Run verify {active[0].get('id')} and inspect every recorded check outcome."
        elif ready_tasks(tasks, archive):
            next_action = f"Activate {ready_tasks(tasks, archive)[0]} after reading its plan and acceptance criteria."
        else:
            next_action = handoff.get("nextAction") or "No ready task; update the plan or record a blocker."
        payload = {
            "ok": not errors,
            "schemaVersion": SCHEMA,
            "git": git_facts(root),
            "active": [task.get("id") for task in active],
            "ready": ready_tasks(tasks, archive),
            "blockers": blockers,
            "freshness": {task_id: task_id not in stale for task_id in stale},
            "nextAction": next_action,
            "recovered": recovered,
            "errors": errors,
        }
        return payload, 0 if not errors else 1


def command_tasks(root: Path) -> tuple[dict, int]:
    config, tasks, archive, _ = load_state(root)
    errors = validate_config(config, root) + validate_tasks(tasks, archive, root, config)
    if errors:
        raise StateProblem("invalid state: " + "; ".join(errors))
    rows = [task for task in tasks.get("tasks", []) if isinstance(task, dict)]
    return {"ok": True, "tasks": rows, "ready": ready_tasks(tasks, archive), "active": [task["id"] for task in rows if task.get("state") == "active"]}, 0


def command_transition(root: Path, task_id: str, state: str, rest: list[str]) -> tuple[dict, int]:
    if state not in STATES:
        raise Problem(f"unsupported target state: {state}")
    delivery_raw = None
    reason = None
    index = 0
    while index < len(rest):
        if rest[index] in {"--reason", "--delivery-json"} and index + 1 < len(rest):
            if rest[index] == "--reason":
                reason = rest[index + 1]
            else:
                delivery_raw = rest[index + 1]
            index += 2
        else:
            raise Problem(f"unknown transition option: {rest[index]}")
    with state_lock(root):
        config, tasks, archive, _ = load_state(root)
        errors = validate_config(config, root) + validate_tasks(tasks, archive, root, config)
        if errors:
            raise StateProblem("invalid state: " + "; ".join(errors))
        task = get_task(tasks, task_id)
        source = task.get("state")
        legal = False
        if source == "not_started" and state == "active":
            legal = True
        elif source == "blocked" and state == "active":
            legal = True
        elif source == "active" and state == "blocked":
            if not reason or not reason.strip():
                raise StateProblem("blocking an active task requires --reason")
            legal = True
        elif source == "verified" and state == "active":
            legal = True
        elif source == "verified" and state == "passing":
            if not delivery_raw:
                raise StateProblem("passing requires --delivery-json with delivery evidence")
            try:
                delivery = json.loads(delivery_raw)
            except json.JSONDecodeError as exc:
                raise Problem(f"invalid delivery JSON: {exc}") from exc
            if not isinstance(delivery, dict) or not delivery:
                raise StateProblem("delivery evidence must be a non-empty object")
            task["delivery"] = delivery
            legal = True
        elif source == state:
            raise StateProblem(f"task {task_id} is already {state}")
        elif source == "active" and state == "verified":
            raise StateProblem("active tasks enter verified only through verify")
        if not legal:
            raise StateProblem(f"illegal transition: {source} -> {state}")
        if state == "active":
            if not deps_ready(task, tasks, archive):
                raise StateProblem(f"dependencies are incomplete for {task_id}")
            if any(item.get("state") == "active" and item.get("id") != task_id for item in tasks.get("tasks", []) if isinstance(item, dict)):
                raise StateProblem("only one task may be active")
        if state == "blocked":
            task["blockedReason"] = reason
        else:
            task["blockedReason"] = None
        task["state"] = state
        atomic_write_json(paths(root)["tasks"], tasks)
        return {"ok": True, "task": task, "from": source, "to": state}, 0


def run_one_check(root: Path, check: dict, attempt_id: str, locations: dict[str, Path]) -> dict:
    argv = check["argv"]
    cwd_rel = check.get("cwd", ".")
    cwd = safe_path(root, cwd_rel, allow_missing=False)
    log_path = safe_path(root, f"docs/harness/runs/{attempt_id}-{check['id']}.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    executable = argv[0]
    if shutil.which(executable) is None and not (Path(executable).is_absolute() and os.access(executable, os.X_OK)):
        log_path.write_text(f"missing executable: {executable}\n", encoding="utf-8")
        return {
            "id": check["id"], "argv": argv, "cwd": cwd_rel, "status": "missing_command",
            "exitCode": None, "timedOut": False, "durationMs": 0, "logPath": rel_path(root, log_path),
        }
    started = time.monotonic()
    timed_out = False
    output = ""
    exit_code: int | None = None
    try:
        process = subprocess.Popen(
            argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, start_new_session=True,
        )
        try:
            output, _ = process.communicate(timeout=float(check["timeoutSeconds"]))
            exit_code = process.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            partial, _ = process.communicate()
            output = (exc.output or "") + (partial or "")
            exit_code = process.returncode
    except (OSError, ValueError) as exc:
        output = f"could not start check: {exc}\n"
        exit_code = None
    status = "timeout" if timed_out else ("passed" if exit_code == 0 else "failed")
    log_path.write_text(
        f"argv: {json.dumps(argv)}\ncwd: {cwd_rel}\nstatus: {status}\nexitCode: {exit_code}\n\n{output}",
        encoding="utf-8",
    )
    return {
        "id": check["id"], "argv": argv, "cwd": cwd_rel, "status": status,
        "exitCode": exit_code, "timedOut": timed_out,
        "durationMs": int((time.monotonic() - started) * 1000),
        "logPath": rel_path(root, log_path),
    }


def run_checks(root: Path, config: dict, task: dict, locations: dict[str, Path]) -> tuple[dict, list[dict]]:
    attempt_id = uuid.uuid4().hex
    attempt_path = safe_path(root, f"docs/harness/runs/{attempt_id}.json")
    check_map = {check.get("id"): check for check in config.get("checks", []) if isinstance(check, dict)}
    check_ids = task.get("verification", [])
    attempt = {
        "schemaVersion": SCHEMA, "attemptId": attempt_id, "taskId": task.get("id"),
        "startedAt": utc_now(), "status": "running", "checks": [],
    }
    atomic_write_json(attempt_path, attempt)
    results: list[dict] = []
    try:
        for check_id in check_ids:
            result = run_one_check(root, check_map[check_id], attempt_id, locations)
            results.append(result)
            attempt["checks"] = results
            atomic_write_json(attempt_path, attempt)
    except KeyboardInterrupt:
        attempt["status"] = "interrupted"
        attempt["endedAt"] = utc_now()
        atomic_write_json(attempt_path, attempt)
        raise StateProblem(f"verification interrupted; recover attempt {attempt_id}")
    return {**attempt, "attemptPath": rel_path(root, attempt_path)}, results


def acceptance_results(task: dict, results: list[dict]) -> tuple[bool, list[str]]:
    by_id = {item.get("id"): item for item in results}
    mapping = task.get("evidence", {}).get("acceptanceMap", {}) if isinstance(task.get("evidence"), dict) else {}
    errors: list[str] = []
    for criterion in task.get("acceptance", []):
        reference = mapping.get(criterion) if isinstance(mapping, dict) else None
        if not isinstance(reference, str):
            errors.append(f"no evidence mapping for acceptance criterion: {criterion}")
            continue
        if reference.startswith("check:"):
            check_id = reference[6:]
            result = by_id.get(check_id)
            if not result or result.get("status") != "passed":
                errors.append(f"acceptance check did not pass: {check_id}")
        elif reference.startswith("manual:"):
            errors.append(f"manual evidence is not established by verify: {reference}")
        else:
            errors.append(f"unsupported evidence reference: {reference}")
    return not errors, errors


def command_verify(root: Path, task_id: str) -> tuple[dict, int]:
    locations = paths(root)
    with state_lock(root):
        config, tasks, archive, locations = load_state(root)
        recovered = recover_running(root, locations)
        errors = validate_config(config, root) + validate_tasks(tasks, archive, root, config)
        if errors:
            raise StateProblem("invalid state: " + "; ".join(errors))
        task = get_task(tasks, task_id)
        if task.get("state") != "active":
            raise StateProblem(f"verify requires an active task: {task_id}")
        if not task.get("verification"):
            raise StateProblem("verification list is empty; product readiness cannot be established")
        pre = fingerprint(root, config)
    attempt, results = run_checks(root, config, task, locations)
    post = fingerprint(root, config)
    checks_passed = all(item.get("status") == "passed" for item in results)
    acceptance_passed, acceptance_errors = acceptance_results(task, results)
    passed = checks_passed and acceptance_passed and pre == post
    run_status = "passed" if passed else "failed"
    attempt.update({"status": run_status, "endedAt": utc_now(), "preFingerprint": pre, "postFingerprint": post,
                    "checks": results, "fresh": pre == post, "recoveredBeforeRun": recovered})
    attempt_path = safe_path(root, f"docs/harness/runs/{attempt['attemptId']}.json")
    with state_lock(root):
        config2, tasks2, archive2, locations2 = load_state(root)
        errors2 = validate_config(config2, root) + validate_tasks(tasks2, archive2, root, config2)
        if errors2:
            raise StateProblem("state changed during verification: " + "; ".join(errors2))
        final_task = get_task(tasks2, task_id)
        evidence = final_task.get("evidence") if isinstance(final_task.get("evidence"), dict) else {}
        evidence.update({"attemptId": attempt["attemptId"], "status": run_status, "fingerprint": post,
                         "preFingerprint": pre, "postFingerprint": post, "fresh": pre == post,
                         "checks": results, "recordedAt": attempt["endedAt"]})
        final_task["evidence"] = evidence
        if passed:
            final_task["state"] = "verified"
            final_task["blockedReason"] = None
        atomic_write_json(locations2["tasks"], tasks2)
        atomic_write_json(attempt_path, attempt)
    failure_reasons = list(acceptance_errors)
    if not checks_passed:
        failure_reasons.extend(f"{item.get('id')}: {item.get('status')}" for item in results if item.get("status") != "passed")
    if pre != post:
        failure_reasons.append("fingerprint changed during verification")
    payload = {"ok": passed, "task": final_task, "attempt": attempt, "errors": failure_reasons}
    return payload, 0 if passed else 1


def command_handoff(root: Path) -> tuple[dict, int]:
    with state_lock(root):
        config, tasks, archive, locations = load_state(root)
        recovered = recover_running(root, locations)
        errors = validate_config(config, root) + validate_tasks(tasks, archive, root, config)
        if errors:
            raise StateProblem("invalid state: " + "; ".join(errors))
        current = fingerprint(root, config)
        active = next((task for task in tasks.get("tasks", []) if isinstance(task, dict) and task.get("state") == "active"), None)
        previous = locations["handoff_data"]
        blockers = list(previous.get("blockers", [])) if isinstance(previous.get("blockers"), list) else []
        for task in tasks.get("tasks", []):
            if isinstance(task, dict) and task.get("state") == "blocked":
                item = f"{task.get('id')}: {task.get('blockedReason')}"
                if item not in blockers:
                    blockers.append(item)
        completed = list(previous.get("completed", [])) if isinstance(previous.get("completed"), list) else []
        for task in tasks.get("tasks", []):
            if isinstance(task, dict) and task.get("state") in {"verified", "passing"} and task.get("id") not in completed:
                completed.append(task.get("id"))
        verification = []
        if active and isinstance(active.get("evidence"), dict):
            verification = active["evidence"].get("checks", [])
        elif completed:
            latest = next((task for task in tasks.get("tasks", []) if isinstance(task, dict) and task.get("id") == completed[-1]), None)
            if latest and isinstance(latest.get("evidence"), dict):
                verification = latest["evidence"].get("checks", [])
        next_action = (
            f"Run verify {active.get('id')} and inspect every recorded check outcome." if active else
            f"Activate {ready_tasks(tasks, archive)[0]} after reading its plan and acceptance criteria." if ready_tasks(tasks, archive) else
            previous.get("nextAction") or "No ready task; update the plan or record a blocker."
        )
        data = dict(previous)
        data.update({
            "schemaVersion": SCHEMA, "updatedAt": utc_now(), "activeTask": active.get("id") if active else None,
            "branch": git_facts(root).get("branch"), "revision": git_facts(root).get("revision"),
            "workingTree": git_facts(root).get("dirty"), "completed": completed,
            "blockers": blockers, "verification": verification, "nextAction": next_action,
            "freshness": current, "recovered": recovered,
        })
        atomic_write_json(locations["handoff"], data)
        locations["handoff_md"].write_text(render_handoff(data), encoding="utf-8")
        return {"ok": True, "handoff": data, "path": rel_path(root, locations["handoff"])}, 0


def command_archive(root: Path, dry_run: bool) -> tuple[dict, int]:
    with state_lock(root):
        config, tasks, archive, locations = load_state(root)
        errors = validate_config(config, root) + validate_tasks(tasks, archive, root, config)
        if errors:
            raise StateProblem("invalid state: " + "; ".join(errors))
        candidates = [task for task in tasks.get("tasks", []) if isinstance(task, dict) and task.get("state") == "passing"]
        if dry_run:
            return {"ok": True, "dryRun": True, "candidates": [task.get("id") for task in candidates]}, 0
        for task in candidates:
            task["archivedAt"] = utc_now()
        archive.setdefault("tasks", []).extend(candidates)
        tasks["tasks"] = [task for task in tasks.get("tasks", []) if task not in candidates]
        atomic_write_json(locations["tasks"], tasks)
        atomic_write_json(locations["archive"], archive)
        return {"ok": True, "archived": [task.get("id") for task in candidates]}, 0


def parse_cli(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("command")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def dispatch(args: argparse.Namespace) -> tuple[dict, int]:
    root = root_path(args.root)
    command = args.command
    rest = list(args.args)
    if command == "context":
        return command_context(root)
    if command == "tasks":
        return command_tasks(root)
    if command == "validate":
        return command_validate(root)
    if command == "handoff":
        return command_handoff(root)
    if command == "verify":
        if len(rest) != 1:
            raise Problem("verify requires exactly one task id")
        return command_verify(root, rest[0])
    if command == "transition":
        if len(rest) < 2:
            raise Problem("transition requires task id and target state")
        return command_transition(root, rest[0], rest[1], rest[2:])
    if command == "archive":
        if any(item not in {"--dry-run"} for item in rest):
            raise Problem("archive accepts only --dry-run")
        return command_archive(root, "--dry-run" in rest)
    raise Problem(f"unknown command: {command}")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_cli(argv if argv is not None else sys.argv[1:])
        payload, code = dispatch(args)
    except Problem as exc:
        payload, code = {"ok": False, "error": exc.message}, exc.code
        print(exc.message, file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        payload, code = {"ok": False, "error": f"runner error: {exc}"}, 2
        print(f"runner error: {exc}", file=sys.stderr)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
