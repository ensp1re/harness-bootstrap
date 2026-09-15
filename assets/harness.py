#!/usr/bin/env python3
"""Project harness: one task queue, recorded verification, and a short resume view.

Installed by harness-bootstrap. Standard library only, Python 3.8+.
Start every session with `python3 scripts/harness.py status`; `-h` lists commands.
Agents do not need to read this file: `status`, `show ID` and `COMMAND -h` print what the loop needs.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TASKS = 'docs/tasks.json'
CONFIG = 'docs/config.json'
RUNS = 'docs/runs'
LOCK = 'docs/.harness.lock'
STATES = ('not_started', 'active', 'blocked', 'verified', 'passing', 'dropped')
BOOKKEEPING = (TASKS, LOCK, RUNS + '/', 'docs/install.json')  # never fingerprinted, never blocks `done`
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.next', 'dist', 'build', 'target', 'coverage'}
TAIL_LINES = 30
TASK_ID = re.compile(r'F\d{3,}')
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'  # git's empty tree, the base for repos without commits
DEBUG_LEFTOVER = re.compile(r'console\.log\(|\bdebugger\b|breakpoint\(\)|pdb\.set_trace\(|binding\.pry|\bdbg!\(|\b(TODO|FIXME|XXX)\b')


def is_path_rule(rule):
    """A must-not-change entry that names files (no spaces; contains / * or .) instead of a behavior."""
    return bool(re.fullmatch(r'\S+', rule)) and any(mark in rule for mark in '/*.')


def changed_since(root, base):
    """Paths changed since commit `base` (committed, staged, unstaged, or untracked); None without git."""
    tracked = git(root, 'diff', '--name-only', base or EMPTY_TREE)
    untracked = git(root, 'ls-files', '--others', '--exclude-standard')
    if tracked is None or untracked is None:
        return None
    return sorted({name for name in (tracked + untracked).splitlines() if name and not name.startswith(BOOKKEEPING)})


def added_lines(root):
    """(path, line number, text) for lines added since the last commit, untracked files included; None without git."""
    if git(root, 'rev-parse', '--is-inside-work-tree') is None:
        return None
    found, path, line_number = [], None, 0
    diff = git(root, 'diff', 'HEAD', '--unified=0', '--no-color', '--no-ext-diff')
    for line in (diff or '').splitlines():
        if line.startswith('+++ '):
            path = line[6:] if line.startswith('+++ b/') else None
        elif line.startswith('@@'):
            match = re.search(r'\+(\d+)', line)
            line_number = int(match.group(1)) if match else 0
        elif line.startswith('+') and path:
            found.append((path, line_number, line[1:]))
            line_number += 1
    listing = git(root, 'ls-files', '--others', '--exclude-standard') if diff is not None \
        else git(root, 'ls-files', '--cached', '--others', '--exclude-standard')
    for name in (listing or '').splitlines():
        try:
            if (root / name).stat().st_size > 200_000:
                continue
            text = (root / name).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        found.extend((name, index, content) for index, content in enumerate(text.splitlines(), 1))
    return found


def debug_leftovers(root):
    lines = added_lines(root)
    if lines is None:
        return None
    runner = Path(__file__).resolve()
    return [f'{name}:{line_number}: {shorten(text.strip(), 70)}' for name, line_number, text in lines
            if not name.startswith(BOOKKEEPING) and not name.endswith(('.md', '.txt'))
            and (root / name).resolve() != runner and DEBUG_LEFTOVER.search(text)]


def uncommitted(root):
    status = git(root, 'status', '--porcelain', '--untracked-files=all')
    if status is None:
        return None
    return [line[3:] for line in status.splitlines() if not line[3:].strip('"').startswith(BOOKKEEPING)]


class Refused(Exception):
    """The command cannot proceed. code 1: refused or failed; code 2: invalid input or state."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise Refused(f'missing {path}; install the harness first', 2)
    except (ValueError, UnicodeDecodeError) as error:
        raise Refused(f'{path} is not valid JSON: {error}', 2)


def write_json(path, data):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]


def task_hash(task):
    return digest({key: task.get(key) for key in ('behavior', 'acceptance', 'verification')})


def number(task):
    task_id = str(task.get('id', ''))
    return int(task_id[1:]) if TASK_ID.fullmatch(task_id) else 10 ** 9


def git(root, *args):
    try:
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class Lock:
    """Single writer for docs/tasks.json. A lock left by a dead process is taken over."""

    def __init__(self, root):
        self.path = root / LOCK

    def __enter__(self):
        for _ in range(2):
            try:
                handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    owner = int(self.path.read_text().strip() or 0)
                except (OSError, ValueError):
                    owner = 0
                if pid_alive(owner):
                    raise Refused(f'another harness command (pid {owner}) is writing; retry when it ends')
                self.path.unlink(missing_ok=True)
                continue
            os.write(handle, str(os.getpid()).encode())
            os.close(handle)
            return self
        raise Refused(f'could not take {LOCK}')

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


class State:
    def __init__(self, root):
        self.root = root
        self.data = read_json(root / TASKS)
        if not isinstance(self.data, dict) or self.data.get('schemaVersion') not in (1, 2):
            raise Refused(f'{TASKS}: missing or unsupported schemaVersion (this runner reads 1 and 2)', 2)
        tasks = self.data.get('tasks')
        if not isinstance(tasks, list) or not all(isinstance(task, dict) for task in tasks):
            raise Refused(f'{TASKS}: "tasks" must be a list of objects', 2)
        self.tasks = tasks
        path = root / CONFIG
        self.config = read_json(path) if path.exists() else {'schemaVersion': 2, 'checks': []}
        if not isinstance(self.config, dict):
            raise Refused(f'{CONFIG}: expected an object', 2)
        self._files_hash = None

    def task(self, task_id):
        for task in self.tasks:
            if task.get('id') == task_id:
                return task
        raise Refused(f'no task {task_id}', 2)

    def checks(self):
        return {check.get('id'): check for check in self.config.get('checks') or [] if isinstance(check, dict)}

    def with_state(self, *states):
        return sorted((task for task in self.tasks if task.get('state') in states), key=number)

    def satisfied(self, dependency):
        if (self.root / 'docs/archive' / f'{dependency}.json').exists():
            return True
        return any(task.get('id') == dependency and task.get('state') == 'passing' and not stale_reason(self, task)
                   for task in self.tasks)

    def ready(self):
        return [task for task in self.with_state('not_started')
                if all(self.satisfied(dep) for dep in task.get('dependsOn') or [])]

    def file_digests(self):
        configured = self.config.get('fingerprintPaths')
        listed = None if configured else git(self.root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard')
        if listed is not None:
            names = [name for name in listed.split('\0') if name]
        else:
            names = walk(self.root, configured or ['.'])
        digests = {}
        for name in sorted(set(names)):
            path = self.root / name
            if name.startswith(BOOKKEEPING) or SKIP_DIRS.intersection(Path(name).parts):
                continue
            if path.is_file():
                try:
                    digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    digests[name] = 'unreadable'
        return digests

    def files_hash(self):
        if self._files_hash is None:
            self._files_hash = digest(self.file_digests())
        return self._files_hash

    def save(self):
        self.data['schemaVersion'] = 2
        write_json(self.root / TASKS, self.data)


def walk(root, entries):
    names = []
    for entry in entries:
        base = root / entry
        if base.is_file():
            names.append(Path(entry).as_posix())
        for directory, subdirs, files in os.walk(base):
            subdirs[:] = [name for name in subdirs if name not in SKIP_DIRS]
            names.extend((Path(directory) / name).relative_to(root).as_posix() for name in files)
    return names


def stale_reason(state, task):
    """Why recorded evidence no longer supports the task's state, or None."""
    evidence = task.get('evidence') or {}
    if task.get('state') == 'passing':
        if evidence.get('version') == 2 and evidence.get('taskHash') != task_hash(task):
            return 'definition changed after done'
        return None
    if task.get('state') != 'verified':
        return None
    if evidence.get('version') != 2:
        return 'evidence predates this harness version'
    if evidence.get('taskHash') != task_hash(task):
        return 'definition changed after verify'
    if evidence.get('filesHash') != state.files_hash():
        return 'files changed after verify'
    return None


def find_cycle(tasks):
    graph = {task.get('id'): list(task.get('dependsOn') or []) for task in tasks}
    visiting, finished = [], set()

    def visit(node):
        if node in finished or node not in graph:
            return None
        if node in visiting:
            return visiting[visiting.index(node):] + [node]
        visiting.append(node)
        for dependency in graph[node]:
            cycle = visit(dependency)
            if cycle:
                return cycle
        visiting.pop()
        finished.add(node)
        return None

    for node in graph:
        cycle = visit(node)
        if cycle:
            return cycle
    return None


def problems(state):
    found = []
    checks = state.checks()
    for check in state.config.get('checks') or []:
        argv = check.get('argv') if isinstance(check, dict) else None
        if not isinstance(check, dict) or not check.get('id') or not isinstance(argv, list) or not argv \
                or not all(isinstance(part, str) for part in argv):
            found.append(f'{CONFIG}: each check needs an "id" and a non-empty "argv" list of strings')
    for entry in state.config.get('fingerprintPaths') or []:
        target = (state.root / entry).resolve()
        if target != state.root and state.root not in target.parents:
            found.append(f'{CONFIG}: fingerprint path {entry!r} is outside the repository')
        elif not target.exists():
            found.append(f'{CONFIG}: fingerprint path {entry!r} does not exist')
    seen = set()
    for task in state.tasks:
        task_id = task.get('id')
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            found.append(f'task id {task_id!r} must look like F001')
            continue
        if task_id in seen:
            found.append(f'{task_id}: duplicate id')
        seen.add(task_id)
        if task.get('state') not in STATES:
            found.append(f'{task_id}: unknown state {task.get("state")!r}')
        if not task.get('behavior'):
            found.append(f'{task_id}: behavior is empty')
        for check_id in task.get('verification') or []:
            if check_id not in checks:
                found.append(f'{task_id}: check {check_id!r} is not defined in {CONFIG}')
        if task.get('state') == 'blocked' and not task.get('blockedReason'):
            found.append(f'{task_id}: blocked without a reason')
    for task in state.tasks:
        for dependency in task.get('dependsOn') or []:
            if dependency not in seen and not state.satisfied(dependency):
                found.append(f'{task.get("id")}: depends on unknown task {dependency}')
    in_progress = state.with_state('active', 'verified')
    if len(in_progress) > 1:
        found.append('more than one task in progress (active or verified): ' + ', '.join(t['id'] for t in in_progress))
    numbers = [number(task) for task in state.tasks if TASK_ID.fullmatch(str(task.get('id', '')))]
    if numbers and not (isinstance(state.data.get('nextId'), int) and state.data['nextId'] > max(numbers)):
        found.append(f'{TASKS}: nextId must be an integer greater than every task number')
    cycle = find_cycle(state.tasks)
    if cycle:
        found.append('dependency cycle: ' + ' -> '.join(cycle))
    return found


def run_order(state, task):
    order = list(task.get('verification') or [])
    order += [check['id'] for check in state.config.get('checks') or []
              if isinstance(check, dict) and check.get('required') and check.get('id') not in order]
    return order


def tail(path):
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').rstrip().splitlines()
    except OSError:
        return '(log unreadable)'
    return '\n'.join(lines[-TAIL_LINES:])


def run_check(root, check, log_path):
    started = time.monotonic()

    def result(outcome, code):
        return {'id': check['id'], 'outcome': outcome, 'exit': code,
                'seconds': round(time.monotonic() - started, 1), 'log': log_path.relative_to(root).as_posix()}

    with open(log_path, 'wb') as log:
        log.write(('$ ' + ' '.join(check['argv']) + '\n').encode())
        log.flush()
        try:
            process = subprocess.Popen(check['argv'], cwd=root / check.get('cwd', '.'), stdout=log,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as error:
            log.write(f'cannot start: {error}\n'.encode())
            return result('missing-command', 127)
        try:
            code = process.wait(timeout=check.get('timeoutSeconds', 900))
        except subprocess.TimeoutExpired:
            stop(process)
            return result('timeout', 124)
        except BaseException:
            stop(process)
            raise
    return result('passed' if code == 0 else 'failed', code)


def stop(process):
    try:
        if hasattr(os, 'killpg'):
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except OSError:
        pass
    process.wait()


def evidence_line(task):
    evidence = task.get('evidence') or {}
    status, when = evidence.get('status'), evidence.get('at', '?')
    if not status:
        return 'no verify yet'
    if status == 'running':
        return f'verify running since {when}' if pid_alive(evidence.get('pid')) else f'verify interrupted at {when}'
    failed = [check for check in evidence.get('checks') or [] if check.get('outcome', 'passed') != 'passed']
    if status == 'failed' and failed:
        return f'verify failed at {when}: ' + '; '.join(
            f'{check.get("id")} {check.get("outcome")} (log {check.get("log")})' for check in failed)
    return f'verify {status} at {when}'


def shorten(text, width=90):
    text = ' '.join(str(text).split())
    return text if len(text) <= width else text[:width - 3] + '...'


def next_step(state, found):
    if found:
        return 'fix the problems above (`validate` lists them)'
    active = state.with_state('active')
    if active:
        task = active[0]
        evidence = task.get('evidence') or {}
        if evidence.get('status') == 'running' and not pid_alive(evidence.get('pid')):
            return f'`verify {task["id"]}` again; the last run was interrupted'
        if evidence.get('status') == 'failed':
            return f'fix the failing check, then `verify {task["id"]}`'
        return f'implement {task["id"]}, then `verify {task["id"]}`'
    verified = state.with_state('verified')
    if verified:
        task = verified[0]
        reason = stale_reason(state, task)
        if reason:
            return f'`verify {task["id"]}` again ({reason})'
        if task.get('review') and not review_passed(state, task):
            return (f'get an independent review: a reviewer with fresh context reads `show {task["id"]}` and `git diff`, '
                    f'then records `review {task["id"]} --pass|--fail --summary "..."`')
        return f'commit, then `done {task["id"]} --proof ...`'
    ready = state.ready()
    if ready:
        task = ready[0]
        if not task.get('acceptance') or not task.get('verification'):
            return f'give {task["id"]} acceptance criteria and checks (`edit`), then `start {task["id"]}`'
        return f'`start {task["id"]}`'
    if state.with_state('blocked'):
        return 'every remaining task is blocked or waiting; resolve a blocker or add work'
    if state.with_state('not_started'):
        return 'remaining tasks wait on dependencies that are not passing; see `list`'
    return 'the queue is empty: add the next task or stop'


def cmd_status(root, args):
    state = State(root)
    found = problems(state)
    if git(root, 'rev-parse', '--is-inside-work-tree') is None:
        print('git: not a repository')
    else:
        branch = (git(root, 'branch', '--show-current') or '').strip() or 'detached'
        head = (git(root, 'rev-parse', '--short', 'HEAD') or '').strip() or 'no commits'
        changed = (git(root, 'status', '--porcelain') or '').splitlines()
        print(f'git: {branch} @ {head}, ' + (f'{len(changed)} uncommitted paths' if changed else 'clean'))
    last = state.data.get('lastWrapup')
    if isinstance(last, dict):
        print(f'last wrapup: {"clean" if last.get("clean") else "not clean"} at {last.get("at")}'
              + ''.join(f'; {problem}' for problem in (last.get('problems') or [])[:3])
              + (f'; note: {last["note"]}' if last.get('note') else ''))
    checks = state.checks()
    for task in state.with_state('active', 'verified'):
        print(f'{task["state"]}: {task["id"]} {task.get("behavior")}')
        for index, item in enumerate(task.get('acceptance') or [], 1):
            print(f'  accept {index}: {item}')
        for check_id in run_order(state, task):
            argv = checks.get(check_id, {}).get('argv')
            print(f'  check {check_id}: ' + (' '.join(argv) if argv else f'MISSING from {CONFIG}'))
        if task.get('keep'):
            print('  must not change: ' + '; '.join(task['keep']))
        if task.get('refs'):
            print('  refs: ' + ', '.join(task['refs']))
        reason = stale_reason(state, task)
        print('  last: ' + evidence_line(task) + (f' [stale: {reason}]' if reason else ''))
        if task.get('review'):
            review = (task.get('evidence') or {}).get('review')
            print('  review: ' + (f'{review.get("result")} by {review.get("by")} at {review.get("at")}: {review.get("summary")}'
                                 if review else 'required, not done yet'))
        if (task.get('failedVerifies') or 0) >= 2:
            print(f'  failed verifies in a row: {task["failedVerifies"]}')
        for note in (task.get('notes') or [])[-3:]:
            print(f'  note: {note}')
    ready = state.ready()
    if ready:
        print('ready: ' + '; '.join(f'{task["id"]} {shorten(task.get("behavior"), 60)}' for task in ready[:3])
              + (f' (+{len(ready) - 3} more)' if len(ready) > 3 else ''))
    waiting = [task for task in state.with_state('not_started') if task not in ready]
    if waiting:
        print('waiting: ' + '; '.join(
            f'{task["id"]} on ' + ', '.join(dep for dep in task.get('dependsOn') or [] if not state.satisfied(dep))
            for task in waiting[:3]) + (f' (+{len(waiting) - 3} more)' if len(waiting) > 3 else ''))
    for task in state.with_state('blocked'):
        print(f'blocked: {task["id"]} {task.get("blockedReason")}')
    dropped = {task['id'] for task in state.with_state('dropped')}
    for task in state.with_state('not_started', 'blocked'):
        gone = [dep for dep in task.get('dependsOn') or [] if dep in dropped]
        if gone:
            print(f'attention: {task["id"]} depends on dropped {", ".join(gone)}; `edit {task["id"]} --after ...`')
    for task in state.with_state('passing'):
        reason = stale_reason(state, task)
        if reason:
            print(f'attention: {task["id"]} passing but {reason}; `reopen {task["id"]}` or restore the definition')
    for legacy in ('docs/handoff.json', 'docs/SESSION_HANDOFF.md', 'docs/PLAN.md'):
        if (root / legacy).exists():
            print(f'attention: legacy {legacy}; move what is still true into task notes or docs/PROJECT.md, then delete it')
    for problem in found:
        print(f'problem: {problem}')
    counts = {name: len(state.with_state(name)) for name in STATES}
    print('tasks: ' + ', '.join(f'{count} {name.replace("_", " ")}' for name, count in counts.items() if count) if state.tasks else 'tasks: none')
    print('next: ' + next_step(state, found))
    return 0


def cmd_list(root, args):
    state = State(root)
    hidden = {}
    for task in sorted(state.tasks, key=number):
        if task.get('state') in ('passing', 'dropped') and not args.all:
            hidden[task['state']] = hidden.get(task['state'], 0) + 1
            continue
        waits = [dep for dep in task.get('dependsOn') or [] if not state.satisfied(dep)]
        extra = f' [waits on {", ".join(waits)}]' if waits and task.get('state') == 'not_started' else ''
        if task.get('state') == 'blocked':
            extra = f' [{task.get("blockedReason")}]'
        refs = f' ({", ".join(task["refs"])})' if task.get('refs') else ''
        print(f'{task.get("id")} {task.get("state", "?"):<11} {shorten(task.get("behavior"), 80)}{refs}{extra}')
    if hidden:
        print('(' + ', '.join(f'{count} {name}' for name, count in hidden.items()) + ' hidden; `list --all` shows them)')
    if not state.tasks:
        print('no tasks')
    return 0


def cmd_show(root, args):
    state = State(root)
    task = state.task(args.id)
    checks = state.checks()
    print(f'{task["id"]} [{task.get("state")}] {task.get("behavior")}')
    for key, label in (('dependsOn', 'depends on'), ('refs', 'refs')):
        if task.get(key):
            print(f'{label}: ' + ', '.join(task[key]))
    if task.get('keep'):
        print('must not change: ' + '; '.join(task['keep']))
    for key in ('spec', 'plan', 'blockedReason', 'baseCommit'):
        if task.get(key):
            print(f'{key}: {task[key]}')
    if task.get('review'):
        review = (task.get('evidence') or {}).get('review')
        print('review: ' + (f'{review.get("result")} by {review.get("by")} at {review.get("at")}: {review.get("summary")}'
                            if review else 'required, not done yet'))
    for index, item in enumerate(task.get('acceptance') or [], 1):
        print(f'accept {index}: {item}')
    for check_id in run_order(state, task):
        argv = checks.get(check_id, {}).get('argv')
        own = '' if check_id in (task.get('verification') or []) else ' (required for every task)'
        print(f'check {check_id}: ' + (' '.join(argv) if argv else 'MISSING') + own)
    evidence = task.get('evidence') or {}
    print('last: ' + evidence_line(task))
    for check in evidence.get('checks') or []:
        print(f'  {check.get("id")}: {check.get("outcome")} exit {check.get("exit")} {check.get("seconds")}s {check.get("log")}')
    if evidence.get('changedDuringRun'):
        print('  checks changed files: ' + ', '.join(evidence['changedDuringRun']))
    if evidence.get('commit'):
        print(f'  done at commit {evidence["commit"]}')
    reason = stale_reason(state, task)
    if reason:
        print(f'stale: {reason}')
    for note in task.get('notes') or []:
        print(f'note: {note}')
    return 0


def clear_or(values):
    return [] if values == ['none'] else values


def check_references(state, task_id, checks=None, deps=None):
    known = state.checks()
    unknown = [check for check in checks or [] if check not in known]
    if unknown:
        raise Refused(f'unknown check {", ".join(unknown)}; defined in {CONFIG}: {", ".join(known) or "none yet"}', 2)
    ids = {task.get('id') for task in state.tasks}
    missing = [dep for dep in deps or [] if dep == task_id or (dep not in ids and not state.satisfied(dep))]
    if missing:
        raise Refused(f'invalid dependency {", ".join(missing)}', 2)


def cmd_add(root, args):
    with Lock(root):
        state = State(root)
        check_references(state, None, args.check, args.after)
        next_id = state.data.get('nextId') if isinstance(state.data.get('nextId'), int) else 1
        next_id = max([next_id] + [number(task) + 1 for task in state.tasks if number(task) < 10 ** 9])
        task = {'id': f'F{next_id:03d}', 'behavior': args.behavior, 'acceptance': args.accept,
                'dependsOn': args.after, 'state': 'not_started', 'verification': args.check,
                'refs': args.ref, 'keep': args.keep, 'review': args.review, 'notes': [],
                'blockedReason': None, 'evidence': None}
        state.tasks.append(task)
        state.data['nextId'] = next_id + 1
        state.save()
    print(f'added {task["id"]}: {args.behavior}')
    if not args.accept or not args.check:
        print(f'before starting: `edit {task["id"]} --accept ... --check ...`')
    return 0


def cmd_edit(root, args):
    with Lock(root):
        state = State(root)
        task = state.task(args.id)
        before = task_hash(task)
        if args.behavior is not None:
            task['behavior'] = args.behavior
        if args.accept:
            task['acceptance'] = args.accept
        if args.check:
            check_references(state, task['id'], checks=clear_or(args.check))
            task['verification'] = clear_or(args.check)
        if args.after:
            check_references(state, task['id'], deps=clear_or(args.after))
            task['dependsOn'] = clear_or(args.after)
        if args.ref:
            task['refs'] = clear_or(args.ref)
        if args.keep:
            task['keep'] = clear_or(args.keep)
        if args.review is not None:
            task['review'] = args.review == 'on'
        cycle = find_cycle(state.tasks)
        if cycle:
            raise Refused('dependency cycle: ' + ' -> '.join(cycle), 2)
        state.save()
    print(f'updated {task["id"]}')
    if task_hash(task) != before and task.get('state') == 'verified':
        print(f'its verification no longer matches the definition: `verify {task["id"]}` again')
    if task_hash(task) != before and task.get('state') == 'passing':
        print(f'it is passing under the old definition: `reopen {task["id"]} --reason ...` if code must change')
    return 0


def transition(root, task_id, change):
    with Lock(root):
        state = State(root)
        task = state.task(task_id)
        message = change(state, task)
        state.save()
    print(message)
    return 0


def cmd_start(root, args):
    def change(state, task):
        if task.get('state') not in ('not_started', 'blocked'):
            hint = f' (use `reopen {task["id"]}`)' if task.get('state') in ('verified', 'passing') else ''
            raise Refused(f'{task["id"]} is {task.get("state")}{hint}')
        busy = state.with_state('active', 'verified')
        if busy:
            raise Refused(f'{busy[0]["id"]} is {busy[0]["state"]}; finish it (`verify`, commit, `done`) or `block` it first')
        waiting = [dep for dep in task.get('dependsOn') or [] if not state.satisfied(dep)]
        if waiting:
            raise Refused(f'{task["id"]} waits on {", ".join(waiting)}, which must be passing first')
        if not task.get('acceptance') or not task.get('verification'):
            raise Refused(f'{task["id"]} needs acceptance criteria and at least one check: `edit {task["id"]} --accept ... --check ...`')
        task['state'], task['blockedReason'] = 'active', None
        task['baseCommit'] = head_commit(state.root)
        return f'started {task["id"]}: {task.get("behavior")}\nnext: implement it, then `verify {task["id"]}`'
    return transition(root, args.id, change)


def head_commit(root):
    """The commit work starts from; must-not-change paths are compared against it."""
    return (git(root, 'rev-parse', 'HEAD') or '').strip() or None


def cmd_block(root, args):
    def change(state, task):
        if task.get('state') not in ('not_started', 'active'):
            raise Refused(f'{task["id"]} is {task.get("state")}; only not_started or active tasks can be blocked')
        task['state'], task['blockedReason'] = 'blocked', args.reason
        task.setdefault('notes', []).append(f'{now()[:10]} blocked: {args.reason}')
        return f'blocked {task["id"]}: {args.reason}'
    return transition(root, args.id, change)


def cmd_reopen(root, args):
    def change(state, task):
        if task.get('state') not in ('verified', 'passing'):
            raise Refused(f'{task["id"]} is {task.get("state")}; reopen applies to verified or passing tasks')
        busy = [other for other in state.with_state('active', 'verified') if other is not task]
        if busy:
            raise Refused(f'{busy[0]["id"]} is {busy[0]["state"]}; finish or block it first')
        task['state'], task['baseCommit'] = 'active', head_commit(state.root)
        task.setdefault('notes', []).append(f'{now()[:10]} reopened: {args.reason}')
        return f'reopened {task["id"]}\nnext: change what the reason requires, then `verify {task["id"]}`'
    return transition(root, args.id, change)


def cmd_note(root, args):
    def change(state, task):
        task.setdefault('notes', []).append(f'{now()[:10]} {args.text}')
        return f'noted on {task["id"]}'
    return transition(root, args.id, change)


def cmd_verify(root, args):
    with Lock(root):
        state = State(root)
        task = state.task(args.id)
        others = [other['id'] for other in state.with_state('active', 'verified') if other is not task]
        if task.get('state') not in ('active', 'verified') or others:
            raise Refused(f'{task["id"]} is {task.get("state")}; verify runs on the task in progress'
                          + (f' ({", ".join(others)} is in progress)' if others else ' (`start` it first)'))
        if not task.get('acceptance') or not task.get('verification'):
            raise Refused(f'{task["id"]} needs acceptance criteria and its own checks: `edit {task["id"]} --accept ... --check ...`')
        checks = state.checks()
        order = run_order(state, task)
        missing = [check_id for check_id in order if check_id not in checks]
        if missing:
            raise Refused(f'checks not defined in {CONFIG}: {", ".join(missing)}', 2)
        previous = task.get('evidence') or {}
        if previous.get('status') == 'running' and pid_alive(previous.get('pid')):
            raise Refused(f'verify of {task["id"]} is already running (pid {previous["pid"]})')
        started, definition = now(), task_hash(task)
        task['evidence'] = {'version': 2, 'status': 'running', 'at': started, 'pid': os.getpid()}
        state.save()
    runs = root / RUNS
    runs.mkdir(parents=True, exist_ok=True)
    stamp = started.replace('-', '').replace(':', '')
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # lets run_check stop the check's process group
    before = state.file_digests()
    results = [run_check(root, checks[check_id], runs / f'{task["id"]}-{stamp}-{check_id}.log') for check_id in order]
    path_rules = [rule for rule in task.get('keep') or [] if is_path_rule(rule)]
    if path_rules:
        touched = changed_since(root, task.get('baseCommit'))
        if touched is None:
            print('must-not-change paths were not checked: this is not a git repository')
        else:
            hits = [f'{name} (matches {rule})' for name in touched for rule in path_rules if fnmatch.fnmatch(name, rule)]
            keep_log = runs / f'{task["id"]}-{stamp}-keep.log'
            keep_log.write_text(''.join(f'changed a must-not-change path: {hit}\n' for hit in hits)
                                or 'no must-not-change path changed\n', encoding='utf-8')
            results.append({'id': 'keep', 'outcome': 'failed' if hits else 'passed', 'exit': 1 if hits else 0,
                            'seconds': 0.0, 'log': keep_log.relative_to(root).as_posix()})
    after = state.file_digests()
    changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    passed = all(result['outcome'] == 'passed' for result in results)
    with Lock(root):
        state = State(root)
        task = state.task(args.id)
        if (task.get('evidence') or {}).get('at') != started or task.get('state') not in ('active', 'verified'):
            raise Refused(f'{task["id"]} changed while its checks ran (now {task.get("state")}); '
                          f'this result was not recorded, logs are in {RUNS}/')
        task['evidence'] = {'version': 2, 'status': 'passed' if passed else 'failed', 'at': started,
                            'checks': results, 'taskHash': definition, 'filesHash': digest(after)}
        if changed:
            task['evidence']['changedDuringRun'] = changed[:20]
        task['state'] = 'verified' if passed else 'active'
        task['failedVerifies'] = 0 if passed else int(task.get('failedVerifies') or 0) + 1
        state.save()
    seconds = sum(result['seconds'] for result in results)
    if passed:
        print(f'verify {task["id"]}: passed ({len(results)} checks, {seconds:.1f}s)')
    else:
        print(f'verify {task["id"]}: FAILED')
    for result in results:
        print(f'  {result["id"]}: {result["outcome"]} exit {result["exit"]} {result["seconds"]}s {result["log"]}')
    if changed:
        print('checks changed files: ' + ', '.join(changed[:5]) + ' (ignore generated files in .gitignore or commit them)')
    for result in [result for result in results if result['outcome'] != 'passed'][:2]:
        print(f'--- last {TAIL_LINES} lines of {result["log"]} ---\n{tail(root / result["log"])}')
    if not passed and task['failedVerifies'] >= 3:
        print(f'{task["failedVerifies"]} failed verifies in a row: if you have no new idea, '
              f'`note {task["id"]} "what you tried"` and `block {task["id"]} --reason "..."`')
    print(f'next: commit, then `done {task["id"]}`' if passed else f'next: fix the cause, then `verify {task["id"]}`')
    return 0 if passed else 1


def parse_proof(items, task):
    proof = {}
    for item in items:
        index, separator, text = item.partition('=')
        if not separator or not index.strip().isdigit() or not text.strip():
            raise Refused(f'--proof takes "N=<test or check that proves criterion N>", got {item!r}', 2)
        proof[index.strip()] = text.strip()
    missing = [str(n) for n in range(1, len(task.get('acceptance') or []) + 1) if str(n) not in proof]
    if missing:
        raise Refused(f'name what proves each acceptance criterion: add --proof for {", ".join(missing)} '
                      f'(`show {task["id"]}` lists them)')
    return proof


def cmd_done(root, args):
    with Lock(root):
        state = State(root)
        task = state.task(args.id)
        if task.get('state') != 'verified':
            raise Refused(f'{task["id"]} is {task.get("state")}; `verify {task["id"]}` must pass first')
        proof = parse_proof(args.proof, task)
        reason = stale_reason(state, task)
        if reason:
            raise Refused(f'{task["id"]} evidence is stale ({reason}); run `verify {task["id"]}` again')
        if task.get('review') and not review_passed(state, task):
            raise Refused(f'{task["id"]} needs an independent review of the current files: a reviewer with fresh context '
                          f'reads `show {task["id"]}` and `git diff`, then records `review {task["id"]} --pass|--fail --summary "..."`')
        commit = None
        pending = uncommitted(root)
        if pending is not None:
            if pending:
                raise Refused('commit the verified change first; uncommitted: ' + ', '.join(pending[:5])
                              + (' ...' if len(pending) > 5 else ''))
            commit = (git(root, 'rev-parse', '--short', 'HEAD') or '').strip() or None
        task['state'] = 'passing'
        task['evidence'].update({'commit': commit, 'doneAt': now(), 'proof': proof})
        state.save()
        ready = state.ready()
    print(f'{task["id"]} passing' + (f' at {commit}' if commit else ''))
    print('next: ' + (f'`start {ready[0]["id"]}`' if ready else '`status`') + '; commit docs/tasks.json with your next change')
    return 0


def cmd_validate(root, args):
    found = problems(State(root))
    for problem in found:
        print(problem)
    print('ok' if not found else f'{len(found)} problem(s)')
    return 1 if found else 0


def cmd_drop(root, args):
    def change(state, task):
        if task.get('state') in ('passing', 'dropped'):
            raise Refused(f'{task["id"]} is {task.get("state")}; drop applies to unfinished tasks')
        task['state'], task['blockedReason'] = 'dropped', None
        task.setdefault('notes', []).append(f'{now()[:10]} dropped: {args.reason}')
        waiting = [other['id'] for other in state.tasks if task['id'] in (other.get('dependsOn') or [])
                   and other.get('state') not in ('passing', 'dropped')]
        return f'dropped {task["id"]}' + (f'\nstill depending on it: {", ".join(waiting)} (`edit ID --after ...`)' if waiting else '')
    return transition(root, args.id, change)


def review_passed(state, task):
    review = (task.get('evidence') or {}).get('review') or {}
    return review.get('result') == 'pass' and review.get('filesHash') == state.files_hash()


def cmd_review(root, args):
    if args.result is None:
        raise Refused('give --pass or --fail', 2)

    def change(state, task):
        if task.get('state') != 'verified':
            raise Refused(f'{task["id"]} is {task.get("state")}; review a task after `verify {task["id"]}` passes')
        reason = stale_reason(state, task)
        if reason:
            raise Refused(f'{task["id"]} evidence is stale ({reason}); `verify {task["id"]}` again before the review')
        task['evidence']['review'] = {'result': args.result, 'by': args.by, 'summary': args.summary,
                                      'at': now(), 'filesHash': state.files_hash()}
        task.setdefault('notes', []).append(f'{now()[:10]} review {args.result} by {args.by}: {args.summary}')
        if args.result == 'fail':
            task['state'] = 'active'
            return f'review failed for {task["id"]}; it is active again\nnext: fix the findings, then `verify {task["id"]}`'
        return f'review passed for {task["id"]}\nnext: commit, then `done {task["id"]} --proof ...`'
    return transition(root, args.id, change)


def cmd_wrapup(root, args):
    state = State(root)
    in_progress = state.with_state('active', 'verified')
    if in_progress and not args.note:
        raise Refused(f'{in_progress[0]["id"]} is {in_progress[0]["state"]}: add --note "what is done, what is next" '
                      'so the next session can continue', 2)
    checks = state.checks()
    selected = [check['id'] for check in state.config.get('checks') or []
                if isinstance(check, dict) and check.get('id') and (check.get('required') or check.get('wrapup'))]
    runs = root / RUNS
    runs.mkdir(parents=True, exist_ok=True)
    stamp = now().replace('-', '').replace(':', '')
    results = [run_check(root, checks[check_id], runs / f'wrapup-{stamp}-{check_id}.log') for check_id in selected]
    found = [f'{result["id"]} {result["outcome"]} (log {result["log"]})' for result in results if result['outcome'] != 'passed']
    leftovers = debug_leftovers(root)
    found += [f'debug leftover {hit}' for hit in (leftovers or [])[:10]]
    pending = uncommitted(root) or []
    if pending and not args.note:
        found.append(f'{len(pending)} uncommitted paths and no --note explaining them')
    with Lock(root):
        state = State(root)
        for task in state.with_state('active', 'verified'):
            task.setdefault('notes', []).append(f'{now()[:10]} {args.note}')
        state.data['lastWrapup'] = {'at': now(), 'clean': not found, 'problems': found[:10], 'note': args.note}
        state.save()
    for result in results:
        print(f'  {result["id"]}: {result["outcome"]} exit {result["exit"]} {result["seconds"]}s {result["log"]}')
    if leftovers is None:
        print('debug leftovers were not checked: this is not a git repository')
    if pending:
        print('uncommitted: ' + ', '.join(pending[:5]) + (' ...' if len(pending) > 5 else ''))
    for problem in found:
        print(f'problem: {problem}')
    print('wrapup: clean' if not found else f'wrapup: not clean ({len(found)} problems); fix them or leave them for the next session')
    return 0 if not found else 1


def parser():
    top = argparse.ArgumentParser(prog='harness.py', description=__doc__.splitlines()[0])
    top.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent,
                     help='repository root (default: the parent of this script\'s folder)')
    sub = top.add_subparsers(dest='command', metavar='COMMAND')
    sub.required = True

    def command(name, handler, help_text, *arguments):
        item = sub.add_parser(name, help=help_text, description=help_text)
        for flags, options in arguments:
            item.add_argument(*flags, **options)
        item.set_defaults(handler=handler)

    task_id = (['id'], {'help': 'task id, e.g. F001'})
    many = {'action': 'append', 'default': []}
    keep_help = 'what must not change while the task is built: a path glob such as public/* or a behavior (repeat)'
    command('status', cmd_status, 'where things stand and the next step; start every session here')
    command('list', cmd_list, 'one line per open task', (['--all'], {'action': 'store_true', 'help': 'include passing and dropped tasks'}))
    command('show', cmd_show, 'full detail, evidence and notes for one task', task_id)
    command('add', cmd_add, 'queue a task',
            (['behavior'], {'help': 'observable outcome, one sentence'}),
            (['--accept'], dict(many, help='acceptance criterion (repeat)')),
            (['--check'], dict(many, help='check id from docs/config.json (repeat)')),
            (['--after'], dict(many, help='task id this depends on (repeat)')),
            (['--ref'], dict(many, help='related id in docs, e.g. R-2 or A-1 (repeat)')),
            (['--keep'], dict(many, help=keep_help)),
            (['--review'], {'action': 'store_true', 'help': 'require an independent review before done'}))
    command('edit', cmd_edit, 'change a task; each list option replaces the list ("none" clears it)', task_id,
            (['--behavior'], {}), (['--accept'], dict(many)), (['--check'], dict(many)),
            (['--after'], dict(many)), (['--ref'], dict(many)), (['--keep'], dict(many, help=keep_help)),
            (['--review'], {'choices': ['on', 'off'], 'help': 'require an independent review before done'}))
    command('review', cmd_review, 'record an independent review of a verified task', task_id,
            (['--pass'], {'dest': 'result', 'action': 'store_const', 'const': 'pass'}),
            (['--fail'], {'dest': 'result', 'action': 'store_const', 'const': 'fail'}),
            (['--summary'], {'required': True, 'help': 'findings, with evidence'}),
            (['--by'], {'default': 'reviewer', 'help': 'who reviewed, e.g. subagent or a name'}))
    command('wrapup', cmd_wrapup, 'end-of-session check: required checks, debug leftovers, uncommitted work',
            (['--note'], {'help': 'what is done and what is next; required while a task is in progress'}))
    command('start', cmd_start, 'make a ready task active (one task in progress at a time)', task_id)
    command('verify', cmd_verify, 'run the task checks plus required checks and record the result', task_id)
    command('done', cmd_done, 'mark a freshly verified, committed task passing', task_id,
            (['--proof'], dict(many, help='N=test or check that proves acceptance criterion N (one per criterion)')))
    command('block', cmd_block, 'stop a task that cannot proceed', task_id, (['--reason'], {'required': True}))
    command('drop', cmd_drop, 'remove an unfinished task from the plan, keeping its record', task_id,
            (['--reason'], {'required': True}))
    command('reopen', cmd_reopen, 'return a verified or passing task to active', task_id, (['--reason'], {'required': True}))
    command('note', cmd_note, 'append a short dated note: decision, finding, or next step', task_id, (['text'], {}))
    command('validate', cmd_validate, 'check docs/tasks.json and docs/config.json for structural problems')
    return top


def main(argv=None):
    args = parser().parse_args(argv)
    root = args.root.resolve()
    try:
        return args.handler(root, args)
    except Refused as error:
        print(f'error: {error}', file=sys.stderr)
        return error.code


if __name__ == '__main__':
    sys.exit(main())
