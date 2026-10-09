#!/usr/bin/env python3
"""Project harness: one task queue, recorded verification, pull-request delivery, and a short resume view.

Installed by harness-bootstrap. Standard library only, Python 3.8+.
Start every session with `python3 scripts/harness.py status`; `-h` lists commands.
Agents do not need to read this file: `status`, `show ID` and `COMMAND -h` print what the loop needs.
"""
import argparse
import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

TASKS = 'docs/tasks.json'
CONFIG = 'docs/config.json'
RUNS = 'docs/runs'
LOCK = 'docs/.harness.lock'
STATES = ('not_started', 'active', 'blocked', 'verified', 'passing', 'dropped')
TYPES = ('feat', 'fix', 'refactor', 'perf', 'docs', 'test', 'build', 'ci', 'chore')
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.next', 'dist', 'build', 'target', 'coverage'}
TAIL_LINES = 30
TASK_ID = re.compile(r'F\d{3,}')
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'  # git's empty tree, the base for repos without commits
DEBUG_LEFTOVER = re.compile(r'console\.log\(|\bdebugger\b|breakpoint\(\)|pdb\.set_trace\(|binding\.pry|\bdbg!\(|\b(TODO|FIXME|XXX)\b')
HOOKS = ('pre-commit', 'pre-push')
HOOK_SCRIPT = '''#!/bin/sh
# harness-bootstrap hook: git runs this file; the check itself is `harness.py hook {name}`
[ -f scripts/harness.py ] || exit 0
exec python3 scripts/harness.py hook {name}
'''


def is_path_rule(rule):
    """A must-not-change entry that names files (no spaces; contains / * or .) instead of a behavior."""
    return bool(re.fullmatch(r'\S+', rule)) and any(mark in rule for mark in '/*.')


def changed_since(root, base):
    """Paths changed since commit `base` (committed, staged, unstaged, or untracked); None without git."""
    tracked = git(root, 'diff', '--name-only', base or EMPTY_TREE)
    untracked = git(root, 'ls-files', '--others', '--exclude-standard')
    if tracked is None or untracked is None:
        return None
    return sorted({name for name in (tracked + untracked).splitlines() if name and not bookkeeping(name)})


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
            if not bookkeeping(name) and not name.endswith(('.md', '.txt'))
            and (root / name).resolve() != runner and DEBUG_LEFTOVER.search(text)
            and not (re.search(r'console\.log\(', text) and
                     (set(Path(name).parts) & {'scripts', 'tests', 'test', '__tests__', 'bin'}
                      or re.search(r'\.(test|spec)\.[^.]+$', name))
                     and not re.search(r'\bdebugger\b|breakpoint\(\)|pdb\.set_trace\(', text))]


def uncommitted(root):
    status = git(root, 'status', '--porcelain', '--untracked-files=all')
    if status is None:
        return None
    return [line[3:] for line in status.splitlines() if not bookkeeping(line[3:].strip('"'))]


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
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]


def task_hash(task, version=3):
    keys = ('behavior', 'acceptance', 'verification')
    if version >= 3:
        keys += ('keep', 'dependsOn', 'refs', 'review', 'spec', 'plan', 'baseCommit')
    return digest({key: task.get(key) for key in keys})


def bookkeeping(name):
    return name in (TASKS, LOCK, 'docs/install.json') or name.startswith(RUNS + '/')



def number(task):
    task_id = str(task.get('id', ''))
    return int(task_id[1:]) if TASK_ID.fullmatch(task_id) else 10 ** 9


def git(root, *args):
    try:
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def git_or_refuse(root, *args):
    try:
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(f'git {" ".join(args)} failed: {error}')
    if result.returncode != 0:
        raise Refused(f'git {" ".join(args)} failed: {(result.stderr or result.stdout).strip()[-400:]}')
    return result.stdout


def gh(root, *args):
    try:
        return subprocess.run(['gh', *args], cwd=root, capture_output=True, text=True, timeout=300,
                              env=dict(os.environ, GH_PROMPT_DISABLED='1'))
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(['gh', *args], 127, '', str(error))


def current_branch(root):
    return (git(root, 'branch', '--show-current') or '').strip()


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


def contained(root, value, label):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise Refused(f'{CONFIG}: {label} must be a relative repository path', 2)
    target = (root / value).resolve()
    if target != root and root not in target.parents:
        raise Refused(f'{CONFIG}: {label} is outside the repository', 2)
    return target


def validate_config(root, config):
    if config.get('schemaVersion') != 2 or not isinstance(config.get('checks'), list):
        raise Refused(f'{CONFIG}: schemaVersion 2 and a checks list are required', 2)
    seen = set()
    for check in config['checks']:
        if not isinstance(check, dict):
            raise Refused(f'{CONFIG}: each check must be an object', 2)
        ident, argv = check.get('id'), check.get('argv')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', ident) or ident == 'keep':
            raise Refused(f'{CONFIG}: invalid check id {ident!r} (keep is reserved)', 2)
        if ident in seen:
            raise Refused(f'{CONFIG}: duplicate check {ident}', 2)
        seen.add(ident)
        if not isinstance(argv, list) or not argv or not all(isinstance(part, str) and part.strip() and '\0' not in part for part in argv):
            raise Refused(f'{CONFIG}: {ident} needs a non-empty argv list of non-empty strings', 2)
        cwd = contained(root, check.get('cwd', '.'), f'{ident} cwd')
        if not cwd.is_dir():
            raise Refused(f'{CONFIG}: {ident} cwd does not exist', 2)
        for key in ('required', 'precommit', 'wrapup'):
            if key in check and not isinstance(check[key], bool):
                raise Refused(f'{CONFIG}: {ident} {key} must be boolean', 2)
        timeout = check.get('timeoutSeconds', 900)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise Refused(f'{CONFIG}: {ident} timeoutSeconds must be positive and finite', 2)
        if 'package' in check:
            contained(root, check['package'], f'{ident} package')
        if 'script' in check and (not isinstance(check['script'], str) or not check['script'].strip()):
            raise Refused(f'{CONFIG}: {ident} script must be non-empty', 2)
    paths = config.get('fingerprintPaths', [])
    if not isinstance(paths, list):
        raise Refused(f'{CONFIG}: fingerprintPaths must be a list', 2)
    for entry in paths:
        contained(root, entry, 'fingerprint path')
    settings = config.get('delivery', {})
    if not isinstance(settings, dict) or settings.get('mode', 'pr') not in ('pr', 'local'):
        raise Refused(f'{CONFIG}: delivery mode must be pr or local', 2)
    if 'autoMerge' in settings and not isinstance(settings['autoMerge'], bool):
        raise Refused(f'{CONFIG}: autoMerge must be boolean', 2)
    wait = settings.get('checksWaitSeconds', 90)
    if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not math.isfinite(wait) or wait < 0:
        raise Refused(f'{CONFIG}: checksWaitSeconds must be non-negative and finite', 2)
    if settings.get('merge', 'squash') not in ('squash', 'merge', 'rebase'):
        raise Refused(f'{CONFIG}: unknown merge method', 2)


def package_command(root, check):
    """Resolve simple npm/pnpm/yarn/bun scripts; refuse ambiguous workspace invocations.

    Use cwd plus `manager run script` instead of recursive/optional script commands.
    """
    argv = check['argv']
    manager = Path(argv[0]).name
    package, script = check.get('package'), check.get('script')
    if manager not in ('npm', 'pnpm', 'yarn', 'bun'):
        if package is not None or script is not None:
            raise Refused('package/script metadata requires a package-manager script command', 2)
        return None
    args = argv[1:]
    directory = root / check.get('cwd', '.')
    if args[:1] == ['--filter']:
        if manager != 'pnpm' or len(args) < 3:
            raise Refused('use cwd with a single package script', 2)
        selector, args = args[1], args[2:]
        candidates = []
        for name in walk(root, ['.']):
            if Path(name).name == 'package.json':
                path = root / name
                try:
                    data = json.loads(path.read_text())
                except (ValueError, OSError):
                    continue
                if isinstance(data, dict) and (data.get('name') == selector or
                        path.parent.resolve() == (directory / selector).resolve()):
                    candidates.append(path.parent)
        if len(candidates) != 1:
            raise Refused(f'package filter {selector!r} must resolve to exactly one local package', 2)
        directory = candidates[0]
    if not args or args[0].startswith('-'):
        raise Refused('use cwd and an explicit package command; optional or recursive checks can silently skip work', 2)
    manager_args = args[:args.index('--')] if '--' in args else args
    if any(arg.startswith('-') for arg in manager_args):
        raise Refused('optional or recursive script checks can silently skip work; use one cwd per check', 2)
    if args[0] in ('run', 'run-script'):
        if len(args) < 2 or args[1].startswith('-'):
            raise Refused('package script name is missing', 2)
        actual = args[1]
    elif args[0] in ('test', 'start', 'build', 'lint', 'e2e', 'typecheck') or manager in ('pnpm', 'yarn') and args[0] not in ('exec', 'dlx', 'install'):
        actual = args[0]
    else:
        if package is not None or script is not None:
            raise Refused('package metadata must describe the executed script', 2)
        return None
    resolved = contained(root, directory.relative_to(root).as_posix(), 'package')
    if package is not None and contained(root, package, 'package') != resolved or script is not None and script != actual:
        raise Refused('package/script metadata does not match argv', 2)
    manifest = read_json(resolved / 'package.json')
    scripts = manifest.get('scripts') if isinstance(manifest, dict) else None
    command = scripts.get(actual) if isinstance(scripts, dict) else None
    if not isinstance(command, str) or not command.strip():
        raise Refused(f'missing package script {actual!r} in {resolved.relative_to(root)}/package.json', 2)
    return resolved, actual


class State:
    def __init__(self, root, require_tasks=True):
        self.root = root
        self.data = read_json(root / TASKS) if require_tasks or (root / TASKS).exists() else {
            'schemaVersion': 2, 'nextId': 1, 'tasks': []}
        if not isinstance(self.data, dict) or self.data.get('schemaVersion') not in (1, 2):
            raise Refused(f'{TASKS}: missing or unsupported schemaVersion (this runner reads 1 and 2)', 2)
        tasks = self.data.get('tasks')
        if not isinstance(tasks, list) or not all(isinstance(task, dict) for task in tasks):
            raise Refused(f'{TASKS}: "tasks" must be a list of objects', 2)
        self.tasks = tasks
        path = root / CONFIG
        self.config = read_json(path)
        if not isinstance(self.config, dict):
            raise Refused(f'{CONFIG}: expected an object', 2)
        validate_config(self.root, self.config)
        self._files_hash = None
        self._base_states = {}

    def task(self, task_id):
        for task in self.tasks:
            if task.get('id') == task_id:
                return task
        raise Refused(f'no task {task_id}', 2)

    def checks(self):
        return {check['id']: check for check in self.config['checks']}

    def with_state(self, *states):
        return sorted((task for task in self.tasks if task.get('state') in states), key=number)

    def satisfied(self, dependency):
        if (self.root / 'docs/archive' / f'{dependency}.json').exists():
            return True
        return any(task.get('id') == dependency and task.get('state') == 'passing' and not stale_reason(self, task)
                   and not unmerged(self, task) for task in self.tasks)

    def ready(self):
        return [task for task in self.with_state('not_started')
                if all(self.satisfied(dep) for dep in task.get('dependsOn') or [])]

    def base_states(self, base):
        """Task states on origin's base branch as of the last fetch; None when origin has no tasks file there."""
        if base not in self._base_states:
            text = git(self.root, 'show', f'refs/remotes/origin/{base}:{TASKS}')
            try:
                self._base_states[base] = {task.get('id'): task.get('state') for task in json.loads(text)['tasks']} \
                    if text else None
            except (ValueError, KeyError, TypeError, AttributeError):
                self._base_states[base] = None
        return self._base_states[base]

    def forget_base(self):
        self._base_states = {}

    def file_digests(self):
        listed = git(self.root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard')
        names = [name for name in listed.split('\0') if name] if listed is not None else walk(self.root, ['.'])
        # Config, guidance and source always matter. fingerprintPaths only adds ignored inputs.
        names += walk(self.root, self.config.get('fingerprintPaths') or [])
        names += [CONFIG, 'scripts/harness.py', 'AGENTS.md']
        names += walk(self.root, ['docs'])
        digests = {}
        for name in sorted(set(names)):
            path = self.root / name
            if bookkeeping(name):
                continue
            if path.is_symlink():
                digests[name] = 'symlink:' + os.readlink(path)
            elif path.is_file():
                try:
                    digests[name] = digest([hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode & 0o111])
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
        if evidence.get('version') in (2, 3) and evidence.get('taskHash') != task_hash(task, evidence['version']):
            return 'definition changed after done'
        return None
    if task.get('state') != 'verified':
        return None
    if evidence.get('version') != 3:
        return 'evidence predates this harness version'
    if evidence.get('taskHash') != task_hash(task):
        return 'definition changed after verify'
    if evidence.get('configHash') != digest(state.config):
        return 'config changed after verify'
    if evidence.get('filesHash') != state.files_hash():
        return 'files changed after verify'
    return None


def require_dependencies(state, task):
    waiting = [dep for dep in task.get('dependsOn') or [] if not state.satisfied(dep)]
    if waiting:
        raise Refused(f'{task["id"]} waits on {", ".join(waiting)}, which must be passing first')


def verification_reason(state, task):
    require_dependencies(state, task)
    evidence = task.get('evidence') or {}
    if evidence.get('status') != 'passed':
        return 'verification has not passed'
    return stale_reason(state, dict(task, state='verified'))


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
            package_command(root, check)
        except Refused as error:
            log.write(f'{error}\n'.encode())
            return result('invalid-command', 2)
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


def delivery(state):
    """How finished work reaches the base branch: 'pr' (branch, pull request, merge) needs an origin remote."""
    config = state.config.get('delivery')
    config = config if isinstance(config, dict) else {}
    root = state.root
    remote_head = (git(root, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD') or '').strip()
    base = config.get('base') or config.get('defaultBranch') or (remote_head.split('/', 1)[1] if '/' in remote_head else 'main')
    wanted = config.get('mode') or ('local' if config.get('requirePR') is False else 'pr')
    has_origin = git(root, 'remote', 'get-url', 'origin') is not None
    return {'mode': wanted, 'wanted': wanted, 'hasOrigin': has_origin, 'base': base,
            'autoMerge': config.get('autoMerge') is True,
            'merge': config.get('merge') if config.get('merge') in ('squash', 'merge', 'rebase') else 'squash',
            # one `done` call waits this long, below the 2-minute command limit common in agent tools
            'wait': float(config.get('checksWaitSeconds', 90)),
            'poll': float(os.environ.get('HARNESS_POLL_SECONDS', '10')),
            'register': float(os.environ.get('HARNESS_CHECKS_REGISTER_SECONDS', '60'))}


def unmerged(state, task):
    """A passing task whose delivery has not reached origin's base branch yet (as of the last fetch)."""
    info = task.get('delivery') or {}
    if task.get('state') != 'passing' or info.get('mode') != 'pr':
        return False
    base = info.get('base') or 'main'
    merged = state.base_states(base)
    return merged is None or merged.get(task.get('id')) != 'passing'


def branch_name(task):
    slug = re.sub(r'[^a-z0-9]+', '-', str(task.get('behavior') or '').lower()).strip('-') or 'task'
    return f'{task.get("type") or "feat"}/{str(task.get("id")).lower()}-{slug}'


def branches_elsewhere(state):
    """Task branches, local or fetched from origin, whose task this queue does not know or shows as not started."""
    here, known = current_branch(state.root), {task.get('id'): task.get('state') for task in state.tasks}
    refs = git(state.root, 'for-each-ref', '--format=%(refname:lstrip=2)', 'refs/heads', 'refs/remotes/origin') or ''
    found = set()
    for ref in refs.split():
        name = ref[len('origin/'):] if ref.startswith('origin/') else ref
        match = re.fullmatch(rf'(?:{"|".join(TYPES)})/(f\d{{3,}})-.+', name)
        if match and name != here and known.get(match.group(1).upper(), 'not_started') == 'not_started':
            found.add(name)
    return sorted(found)


def ensure_hooks(root):
    """Make git run `hook pre-commit` and `hook pre-push`: in .husky/ when husky runs the hooks (those files are
    committed, so every clone that installs dependencies gets them), else in this clone's .git/hooks. Returns notes."""
    custom = (git(root, 'config', '--get', 'core.hooksPath') or '').strip()
    husky = custom.startswith('.husky')
    if custom and not husky:
        return [f'note: git hooks come from {custom}; add `python3 scripts/harness.py hook pre-commit` and '
                f'`... hook pre-push` to that setup']
    location = '.husky' if husky else (git(root, 'rev-parse', '--git-path', 'hooks') or '').strip()
    if not location:
        return []
    directory = Path(location) if Path(location).is_absolute() else root / location
    notes = []
    for name in HOOKS:
        hook, line = directory / name, f'python3 scripts/harness.py hook {name}'
        text = hook.read_text(encoding='utf-8', errors='replace') if hook.exists() else ''
        if line in text:
            continue
        if husky and text:
            lines = text.rstrip('\n').split('\n')
            # the push check goes first so it reads the pushed refs; after a shebang line, if there is one
            at = (1 if lines[0].startswith('#!') else 0) if name == 'pre-push' else len(lines)
            text = '\n'.join(lines[:at] + [line] + lines[at:]) + '\n'
        elif husky:
            text = f'#!/bin/sh\n{line}\n'
        elif text and 'harness-bootstrap' not in text:
            notes.append(f'note: kept the existing {name} hook in {location}; add `{line}` to it')
            continue
        else:
            text = HOOK_SCRIPT.format(name=name)
        directory.mkdir(parents=True, exist_ok=True)
        hook.write_text(text, encoding='utf-8')
        hook.chmod(0o755)
    return notes


def reconcile_queue(state, target, current_task):
    def read_at(ref):
        text = git(state.root, 'show', f'{ref}:{TASKS}')
        if text is None:
            raise Refused(f'cannot read task queue at {ref}; reconcile before switching')
        try:
            value = json.loads(text)
            if not isinstance(value, dict) or not isinstance(value.get('tasks'), list):
                raise ValueError('invalid task queue')
            return value
        except ValueError as error:
            raise Refused(f'invalid task queue at {ref}: {error}')

    ancestor = (git(state.root, 'merge-base', 'HEAD', target) or '').strip()
    if not ancestor:
        raise Refused('cannot reconcile task queues without a common ancestor')
    base, remote = read_at(ancestor), read_at(target)
    local = state.data
    def choose(old, ours, theirs, label):
        if ours == old:
            return theirs
        if theirs == old or ours == theirs:
            return ours
        raise Refused(f'concurrent task queue edits to {label}; reconcile {TASKS} with {target} before starting')

    base_tasks, local_tasks, remote_tasks = ({item['id']: item for item in data['tasks']}
                                             for data in (base, local, remote))
    merged = []
    for ident in dict.fromkeys([*remote_tasks, *local_tasks]):
        value = choose(base_tasks.get(ident), local_tasks.get(ident), remote_tasks.get(ident), ident)
        if value is not None:
            merged.append(value)
    selected = next((item for item in merged if item['id'] == current_task['id']), None)
    if selected != current_task:
        raise Refused(f'{current_task["id"]} changed on {target}; reconcile before starting')
    # Keep the caller's task object; subsequent transitions must edit the reconciled queue.
    merged = [current_task if item['id'] == current_task['id'] else item for item in merged]
    data = {}
    for key in (set(base) | set(local) | set(remote)) - {'tasks', 'nextId'}:
        data[key] = choose(base.get(key), local.get(key), remote.get(key), key)
    data['tasks'] = merged
    data['nextId'] = max([local.get('nextId', 1), remote.get('nextId', 1)] + [number(t) + 1 for t in merged])
    state.data, state.tasks = data, merged
    require_dependencies(state, current_task)


def prepare_branch(state, task, settings, fresh):
    """Put the working tree on the task's branch, cut from origin's base."""
    root, base = state.root, settings['base']
    dirty = uncommitted(root)
    if dirty:
        raise Refused(f'uncommitted changes: {", ".join(dirty[:5])}; commit them on their own task branch, stash, '
                      f'or discard them before switching to {task["id"]}')
    git_or_refuse(root, 'fetch', '--quiet', 'origin')
    state.forget_base()
    waiting = [other['id'] for other in state.tasks if other is not task and unmerged(state, other)]
    if waiting:
        raise Refused(f'{waiting[0]} is not merged into {base} yet: `done {waiting[0]}` checks its pull request and merge status')
    notes = []
    remote = (git(root, 'rev-parse', '--verify', '--quiet', f'refs/remotes/origin/{base}') or '').strip()
    if not remote:
        raise Refused(f'origin has no {base} branch yet: commit the harness on {base} and push it once with '
                      f'`HARNESS_BASE_PUSH=1 git push -u origin {base}`, the only direct push; then `start` again')
    if git(root, 'cat-file', '-e', f'refs/remotes/origin/{base}:{TASKS}') is None:
        raise Refused(f'origin/{base} has no {TASKS}: merge the harness into {base} through its own pull request first')
    name = task.get('branch')
    local = bool(name) and git(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{name}') is not None
    remote_branch = bool(name) and git(root, 'rev-parse', '--verify', '--quiet', f'refs/remotes/origin/{name}') is not None
    if not fresh and name and name != base and (local or remote_branch):
        command = ['switch', name] if local else ['switch', '-c', name, '--track', f'origin/{name}']
        target = name if local else f'origin/{name}'
    else:
        stem = name = branch_name(task)
        counter = 2
        while git(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{name}') is not None or \
                git(root, 'rev-parse', '--verify', '--quiet', f'refs/remotes/origin/{name}') is not None:
            name, counter = f'{stem}-{counter}', counter + 1
        command = ['switch', '-c', name, f'origin/{base}']
        target = f'origin/{base}'
    unpushed = (git(root, 'rev-list', '--count', f'origin/{base}..{base}') or '0').strip()
    if unpushed not in ('', '0'):
        notes.append(f'note: local {base} has {unpushed} commits that are not on origin; they are not part of this branch')
    if current_branch(root) != name:
        reconcile_queue(state, target, task)
        git(root, 'checkout', '--', TASKS)  # the queue is held in memory and written back after the switch
        try:
            git_or_refuse(root, *command)
        except Refused:
            state.save()
            raise
    task['branch'] = name
    task.pop('initial', None)  # written by earlier runners
    # the fork point, so a reused branch is not blamed for what changed on the base branch since
    task['baseCommit'] = (git(root, 'merge-base', 'HEAD', f'refs/remotes/origin/{base}') or remote).strip()
    return notes + [f'branch: {name}']


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
    waiting = [task for task in state.with_state('passing') if unmerged(state, task)]
    if waiting:
        return f'`done {waiting[0]["id"]}` to check its pull request and merge status'
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
    here, elsewhere = None, []
    if git(root, 'rev-parse', '--is-inside-work-tree') is None:
        print('git: not a repository')
    else:
        here = current_branch(root) or 'detached'
        head = (git(root, 'rev-parse', '--short', 'HEAD') or '').strip() or 'no commits'
        changed = (git(root, 'status', '--porcelain') or '').splitlines()
        print(f'git: {here} @ {head}, ' + (f'{len(changed)} uncommitted paths' if changed else 'clean'))
        settings = delivery(state)
        if settings['mode'] == 'pr':
            print(f'delivery: pull requests into {settings["base"]}; `done` checks delivery; merge needs authorization')
            elsewhere = branches_elsewhere(state)  # a clone on the base branch cannot see a queue that lives on a task branch
            if elsewhere:
                print('task branches this queue does not show: ' + ', '.join(elsewhere[:3])
                      + '; the task was started there, so its queue is newer')
        if settings['mode'] == 'pr' and not settings['hasOrigin']:
            print('delivery blocked: origin is missing; configure it before PR delivery')
    last = state.data.get('lastWrapup')
    if isinstance(last, dict):
        print(f'last wrapup: {"clean" if last.get("clean") else "not clean"} at {last.get("at")}'
              + ''.join(f'; {problem}' for problem in (last.get('problems') or [])[:3])
              + (f'; note: {last["note"]}' if last.get('note') else ''))
    checks = state.checks()
    for task in state.with_state('active', 'verified'):
        print(f'{task["state"]}: {task["id"]} {task.get("behavior")}')
        if task.get('branch'):
            print(f'  branch: {task["branch"]}' + (f' (you are on {here}: `git switch {task["branch"]}`)'
                                                     if here and here != task['branch'] else ''))
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
    for task in state.with_state('passing'):
        if unmerged(state, task):
            print(f'waiting for merge: {task["id"]} on {task["delivery"].get("branch")}; '
                  f'`done {task["id"]}` checks the pull request and merge status')
    ready = state.ready()
    if ready:
        print('ready: ' + '; '.join(f'{task["id"]} {task.get("behavior")}' for task in ready[:3])
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
    if elsewhere and not state.with_state('active', 'verified'):
        print(f'next: `git switch {elsewhere[0]}`, then `status` there')
    else:
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
    print(f'{task["id"]} [{task.get("state")}] {task.get("type") or "feat"}: {task.get("behavior")}')
    for key, label in (('dependsOn', 'depends on'), ('refs', 'refs')):
        if task.get(key):
            print(f'{label}: ' + ', '.join(task[key]))
    if task.get('keep'):
        print('must not change: ' + '; '.join(task['keep']))
    for key in ('branch', 'spec', 'plan', 'blockedReason', 'baseCommit'):
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
    for index, proof in (evidence.get('proof') or {}).items():
        print(f'proof {index}: {proof}')
    if evidence.get('changedDuringRun'):
        print('  checks changed files: ' + ', '.join(evidence['changedDuringRun']))
    if evidence.get('commit'):
        print(f'  done at commit {evidence["commit"]}')
    if unmerged(state, task):
        print(f'delivery: waiting for merge of {task["delivery"].get("branch")}')
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
        task = {'id': f'F{next_id:03d}', 'type': args.type, 'behavior': args.behavior, 'acceptance': args.accept,
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
        if args.type is not None:
            task['type'] = args.type
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


def head_commit(root):
    """The commit work starts from; must-not-change paths are compared against it."""
    return (git(root, 'rev-parse', 'HEAD') or '').strip() or None


def begin_work(state, task, fresh):
    """Switch to the task's branch (pull-request delivery) or record the starting commit, then check the git hooks."""
    settings = delivery(state)
    if settings['mode'] == 'pr':
        if not settings['hasOrigin']:
            raise Refused('pull-request delivery needs an origin remote; set delivery.mode to local only with user authorization')
        notes = prepare_branch(state, task, settings, fresh)
    else:
        notes, task['baseCommit'] = [], head_commit(state.root)
    if git(state.root, 'rev-parse', '--is-inside-work-tree') is not None:
        notes += ensure_hooks(state.root)
    return notes


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
        notes = begin_work(state, task, fresh=False)
        task['state'], task['blockedReason'] = 'active', None
        return '\n'.join([f'started {task["id"]}: {task.get("behavior")}', *notes,
                          f'next: implement it, then `verify {task["id"]}`'])
    return transition(root, args.id, change)


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
        notes = begin_work(state, task, fresh=task.get('state') == 'passing' and not unmerged(state, task))
        task['state'] = 'active'
        task.pop('delivery', None)
        task.setdefault('notes', []).append(f'{now()[:10]} reopened: {args.reason}')
        return '\n'.join([f'reopened {task["id"]}', *notes,
                          f'next: change what the reason requires, then `verify {task["id"]}`'])
    return transition(root, args.id, change)


def cmd_note(root, args):
    def change(state, task):
        task.setdefault('notes', []).append(f'{now()[:10]} {args.text}')
        return f'noted on {task["id"]}'
    return transition(root, args.id, change)


def require_task_branch(state, task, settings):
    """In pull-request delivery, work on the task's own branch, never on the base branch."""
    if settings['mode'] != 'pr':
        return
    if not settings['hasOrigin']:
        raise Refused('pull-request delivery needs an origin remote; local delivery requires explicit configuration')
    here, expected = current_branch(state.root), task.get('branch')
    if expected and here != expected:
        raise Refused(f'{task["id"]} is built on {expected}, but you are on {here or "a detached HEAD"}: `git switch {expected}`')
    if not expected and here == settings['base']:
        raise Refused(f'{task["id"]} has no task branch and you are on {settings["base"]}: '
                      f'`git switch -c {branch_name(task)}`, then run the command again')
    task['branch'] = expected or here


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
        require_task_branch(state, task, delivery(state))
        require_dependencies(state, task)
        checks = state.checks()
        order = run_order(state, task)
        missing = [check_id for check_id in order if check_id not in checks]
        if missing:
            raise Refused(f'checks not defined in {CONFIG}: {", ".join(missing)}', 2)
        previous = task.get('evidence') or {}
        if previous.get('status') == 'running' and pid_alive(previous.get('pid')):
            raise Refused(f'verify of {task["id"]} is already running (pid {previous["pid"]})')
        started, definition = now(), task_hash(task)
        configuration = digest(state.config)
        proof = parse_proof(args.proof, task, order) if args.proof else {}
        task['evidence'] = {'version': 3, 'status': 'running', 'at': started, 'pid': os.getpid()}
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
            results.append({'id': 'keep', 'outcome': 'failed', 'exit': 1, 'seconds': 0.0,
                            'log': f'{RUNS}/{task["id"]}-{stamp}-keep.log'})
            (root / results[-1]['log']).write_text('cannot check must-not-change paths: git or the starting commit is unavailable\n')
        else:
            hits = [f'{name} (matches {rule})' for name in touched for rule in path_rules if fnmatch.fnmatch(name, rule)]
            keep_log = runs / f'{task["id"]}-{stamp}-keep.log'
            keep_log.write_text(''.join(f'changed a must-not-change path: {hit}\n' for hit in hits)
                                or 'no must-not-change path changed\n', encoding='utf-8')
            results.append({'id': 'keep', 'outcome': 'failed' if hits else 'passed', 'exit': 1 if hits else 0,
                            'seconds': 0.0, 'log': keep_log.relative_to(root).as_posix()})
    after = state.file_digests()
    changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    passed = not changed and all(result['outcome'] == 'passed' for result in results)
    with Lock(root):
        state = State(root)
        task = state.task(args.id)
        if (task.get('evidence') or {}).get('at') != started or task.get('state') not in ('active', 'verified'):
            raise Refused(f'{task["id"]} changed while its checks ran (now {task.get("state")}); '
                          f'this result was not recorded, logs are in {RUNS}/')
        try:
            require_dependencies(state, task)
        except Refused as error:
            passed = False
            print(f'verification rejected: {error}')
        if task_hash(task) != definition or digest(state.config) != configuration or state.file_digests() != after:
            passed = False
            print('verification rejected: task, config or files changed during checks')
        task['evidence'] = {'version': 3, 'status': 'passed' if passed else 'failed', 'at': started,
                            'checks': results, 'taskHash': definition, 'filesHash': digest(after),
                            'configHash': configuration, 'proof': proof}
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
        print('verification rejected: inputs changed during checks: ' + ', '.join(changed[:5]))
    for result in [result for result in results if result['outcome'] != 'passed'][:2]:
        print(f'--- last {TAIL_LINES} lines of {result["log"]} ---\n{tail(root / result["log"])}')
    if not passed and task['failedVerifies'] >= 3:
        print(f'{task["failedVerifies"]} failed verifies in a row: if you have no new idea, '
              f'`note {task["id"]} "what you tried"` and `block {task["id"]} --reason "..."`')
    print(f'next: commit, then `done {task["id"]}`' if passed else f'next: fix the cause, then `verify {task["id"]}`')
    return 0 if passed else 1


def parse_proof(items, task, checks=None):
    proof = {}
    if checks is None:
        checks = [check['id'] for check in (task.get('evidence') or {}).get('checks', [])
                  if check.get('outcome') == 'passed' and check.get('exit') == 0 and check['id'] != 'keep']
    for item in items:
        index, separator, text = item.partition('=')
        if not separator or not index.strip().isdigit() or not text.strip():
            raise Refused(f'--proof takes "N=<test or check that proves criterion N>", got {item!r}', 2)
        index = str(int(index))
        if not 1 <= int(index) <= len(task.get('acceptance') or []):
            raise Refused(f'unknown acceptance criterion {index}', 2)
        if index in proof:
            raise Refused(f'duplicate proof for criterion {index}', 2)
        if text.strip().split(':', 1)[0] not in checks:
            raise Refused(f'proof must name an executed passing check: {text.strip()!r}', 2)
        proof[index] = text.strip()
    missing = [str(n) for n in range(1, len(task.get('acceptance') or []) + 1) if str(n) not in proof]
    if missing:
        raise Refused(f'name what proves each acceptance criterion: add --proof for {", ".join(missing)} '
                      f'(`show {task["id"]}` lists them)')
    return proof


def cmd_done(root, args):
    resumed = merged = False
    with Lock(root):
        state = State(root)
        task = state.task(args.id)
        settings = delivery(state)
        info = task.get('delivery') or {}
        if task.get('state') == 'passing' and info.get('mode') == 'pr':
            pr = pull_request(root, info.get('branch'))
            merged, resumed = bool(pr and pr.get('state') == 'MERGED'), True
            if not merged:
                require_task_branch(state, task, settings)
                reason = verification_reason(state, task)
                if settings['mode'] != 'pr' or reason:
                    raise Refused(f'{task["id"]} needs fresh verification before delivery: '
                                  f'{reason or "delivery mode changed"}; reopen, verify and review again')
                parse_proof([f'{key}={value}' for key, value in task['evidence'].get('proof', {}).items()], task)
                if task.get('review') and not review_passed(state, task):
                    raise Refused('pending delivery needs a fresh independent review')
                if uncommitted(root):
                    raise Refused('commit the verified change before resuming delivery')
        else:
            if task.get('state') != 'verified':
                raise Refused(f'{task["id"]} is {task.get("state")}; `verify {task["id"]}` must pass first')
            proof = parse_proof(args.proof or [f'{key}={value}' for key, value in
                                (task.get('evidence') or {}).get('proof', {}).items()], task)
            reason = verification_reason(state, task)
            if reason:
                raise Refused(f'{task["id"]} evidence is stale ({reason}); run `verify {task["id"]}` again')
            if task.get('review') and (not review_passed(state, task) or proof != task['evidence'].get('proof')):
                raise Refused(f'{task["id"]} needs an independent review of the current files: a reviewer with fresh context '
                              f'reads `show {task["id"]}` and `git diff`, then records `review {task["id"]} --pass|--fail --summary "..."`')
            commit = None
            pending = uncommitted(root)
            if pending is not None:
                if pending:
                    raise Refused('commit the verified change first; uncommitted: ' + ', '.join(pending[:5])
                                  + (' ...' if len(pending) > 5 else ''))
                commit = (git(root, 'rev-parse', '--short', 'HEAD') or '').strip() or None
            if settings['mode'] == 'pr':
                require_task_branch(state, task, settings)
                if task['branch'] == settings['base']:
                    raise Refused(f'{task["id"]} is on {settings["base"]}, which changes only through pull requests: '
                                  f'`git switch -c {branch_name(task)}`, then `done {task["id"]}` again')
                task['delivery'] = {'mode': 'pr', 'branch': task['branch'], 'base': settings['base']}
            task['state'] = 'passing'
            task['evidence'].update({'commit': commit, 'doneAt': now(), 'proof': proof})
            state.save()
            if settings['mode'] != 'pr':
                ready = state.ready()
                print(f'{task["id"]} passing' + (f' at {commit}' if commit else ''))
                print('next: ' + (f'`start {ready[0]["id"]}`' if ready else '`status`')
                      + '; commit docs/tasks.json with your next change')
                return 0
    if merged:
        base = info.get('base') or settings['base']
        if current_branch(root) != info.get('branch') or info.get('branch') == base:
            print(f'{args.id} is already merged into {base}')
            return 0
        return finish_merge(root, args.id, info['branch'], base, pr['url'], pr.get('headRefOid'))
    return deliver(root, args.id, settings, resumed)


def pr_title(task):
    return f'{task.get("type") or "feat"}: {task.get("behavior")} ({task["id"]})'


def pr_body(task):
    evidence = task.get('evidence') or {}
    proof = evidence.get('proof') or {}
    lines = [f'Task {task["id"]}: {task.get("behavior")}', '', 'Acceptance and what proves it:']
    lines += [f'{index}. {item}: {proof.get(str(index), "not named")}'
              for index, item in enumerate(task.get('acceptance') or [], 1)]
    checks = ', '.join(f'{check.get("id")} {check.get("outcome")}' for check in evidence.get('checks') or [])
    lines += ['', f'Local verify at {evidence.get("at")}: {checks or "no checks recorded"}']
    review = evidence.get('review')
    if review:
        lines.append(f'Review: {review.get("result")} by {review.get("by")}: {review.get("summary")}')
    if task.get('keep'):
        lines.append('Must not change: ' + '; '.join(task['keep']))
    if task.get('refs'):
        lines.append('Refs: ' + ', '.join(task['refs']))
    return '\n'.join(lines) + '\n'


def pull_request(root, branch):
    shown = gh(root, 'pr', 'view', branch, '--json', 'number,url,state,headRefOid')
    if shown.returncode != 0:
        return None
    try:
        return json.loads(shown.stdout)
    except ValueError:
        return None


def wait_for_checks(root, number_, settings):
    """('pass' | 'fail' | 'pending', checks) or ('error', gh output) once nothing is pending or this call's wait is over."""
    started = time.monotonic()
    workflows = root / '.github/workflows'
    expect_checks = workflows.is_dir() and any('pull_request' in path.read_text(encoding='utf-8', errors='replace')
                                               for path in workflows.glob('*.y*ml'))
    while True:
        result = gh(root, 'pr', 'checks', str(number_), '--json', 'name,bucket,link')
        elapsed = time.monotonic() - started
        try:
            checks = json.loads(result.stdout)
        except ValueError:
            if 'no checks reported' not in result.stderr:  # not logged in, network, rate limit: never read as "no checks"
                return 'error', (result.stderr or result.stdout).strip()[-400:]
            checks = []
        if not checks:
            if expect_checks and elapsed < min(settings['register'], settings['wait']):
                time.sleep(settings['poll'])
                continue
            return 'pending', [{'name': 'CI checks have not been reported'}]
        if not isinstance(checks, list) or not all(isinstance(check, dict) for check in checks):
            return 'error', 'invalid checks response'
        if result.returncode not in (0, 1, 8):
            return 'error', (result.stderr or result.stdout).strip()[-400:]
        failed = [check for check in checks if check.get('bucket') not in ('pass', 'pending')]
        pending = [check for check in checks if check.get('bucket') == 'pending']
        if failed:
            return 'fail', failed
        if not pending:
            return 'pass', checks
        if elapsed >= settings['wait']:
            return 'pending', pending
        time.sleep(settings['poll'])


def deliver(root, task_id, settings, resumed):
    """Push the task branch, open its pull request, wait for the checks, and merge the verified commit."""
    task = State(root).task(task_id)
    info = task['delivery']
    branch, base = info['branch'], info.get('base') or settings['base']
    try:
        if current_branch(root) == branch and git(root, 'status', '--porcelain', '--', TASKS):
            git_or_refuse(root, 'add', TASKS)
            git_or_refuse(root, 'commit', '--quiet', '-m', f'chore: mark {task_id} passing', '--', TASKS)
        current = State(root)
        reason = verification_reason(current, current.task(task_id))
        if reason:
            raise Refused(f'fresh verification needed: {reason}')
        git_or_refuse(root, 'push', '--quiet', '-u', 'origin', f'{branch}:{branch}')
    except Refused as error:
        print(f'{task_id} is passing locally but not delivered: {error}')
        print(f'next: fix the push problem, then `done {task_id}` again')
        return 1
    head = (git(root, 'rev-parse', f'refs/heads/{branch}') or '').strip()
    if not shutil.which('gh'):
        print(f'{task_id} is pushed to {branch}, but the GitHub CLI (gh) is not installed: '
              f'install it, run `gh auth login`, then `done {task_id}` again')
        return 1
    pr = pull_request(root, branch)
    if resumed and pr is not None and pr.get('state') == 'CLOSED':
        print(f'{pr["url"]} was closed without merging. Ask the user why, then `reopen {task_id} --reason "..."` '
              f'to change the work (and `drop` it after reopening if it is not wanted)')
        return 1
    if pr is None or pr.get('state') == 'CLOSED':
        body = root / RUNS / f'{task_id}-pull-request.md'
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_text(pr_body(task), encoding='utf-8')
        created = gh(root, 'pr', 'create', '--base', base, '--head', branch, '--title', pr_title(task),
                     '--body-file', str(body))
        if created.returncode != 0:
            print(f'could not open a pull request: {(created.stderr or created.stdout).strip()[-400:]}')
            print(f'next: fix that (for example `gh auth login`), then `done {task_id}` again')
            return 1
        pr = pull_request(root, branch)
        if pr is None:
            print(f'opened a pull request for {branch}, but could not read it back; run `done {task_id}` again')
            return 1
    print(f'pull request: {pr["url"]}')
    if pr.get('state') != 'MERGED':
        outcome, checks = wait_for_checks(root, pr['number'], settings)
        if outcome == 'error':
            print(f'could not read the checks: {checks}')
            print(f'next: fix that (for example `gh auth login`), then `done {task_id}` again')
            return 1
        if outcome == 'fail':
            names = ', '.join(f'{check.get("name")} ({check.get("link")})' for check in checks)
            with Lock(root):
                state = State(root)
                failed = state.task(task_id)
                failed['state'] = 'active'
                failed.setdefault('notes', []).append(f'{now()[:10]} checks failed on {pr["url"]}: {names}')
                state.save()
            print(f'checks failed: {names}')
            print(f'{task_id} is active again. next: read the failure (the link, or `gh run view RUN_ID --log-failed`), fix it, commit, '
                  f'`verify {task_id}`, then `done {task_id} --proof ...`')
            return 1
        if outcome == 'pending':
            print('checks are still running: ' + ', '.join(check.get('name', '?') for check in checks))
            print(f'next: `done {task_id}` again to check delivery')
            return 1
        print('checks: ' + (', '.join(f'{check.get("name")} {check.get("bucket")}' for check in checks) or 'none reported'))
        current = State(root)
        reason = verification_reason(current, current.task(task_id))
        if reason:
            raise Refused(f'fresh verification needed before merge: {reason}')
        if pr.get('headRefOid') != head:
            raise Refused('pull request head differs from the verified branch')
        if not settings['autoMerge']:
            print('checks passed; waiting for the owner to merge (autoMerge is not authorized)')
            return 1
        attempt = gh(root, 'pr', 'merge', str(pr['number']), f'--{settings["merge"]}', '--delete-branch',
                     '--match-head-commit', head)
        # the exit code is not the answer: a merge queue exits 0 without merging, and gh can fail after merging
        pr = pull_request(root, str(pr['number'])) or pr
        if pr.get('state') != 'MERGED':
            detail = (attempt.stderr or attempt.stdout).strip()[-400:] or 'GitHub accepted the merge request'
            print(f'{task_id} is not merged yet: {detail}')
            print(f'next: a required approval needs the user; a conflict needs `git merge origin/{base}`, `reopen {task_id}`, '
                  f'verify and `done`; a merge queue or new checks need `done {task_id}` again later')
            return 1
    return finish_merge(root, task_id, branch, base, pr['url'], pr.get('headRefOid'))


def finish_merge(root, task_id, branch, base, url, merged_head):
    """Clean up only the exact branch head GitHub confirmed merged, preserving later user work."""
    local_head = (git(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}') or '').strip()
    if local_head and (not merged_head or local_head != merged_head):
        raise Refused('PR is merged, but the local branch has later or unconfirmed commits; preserve and reconcile it manually')
    if uncommitted(root):
        raise Refused('PR is merged, but local files have edits; preserve and reconcile before switching to base')
    if git(root, 'status', '--porcelain', '--', TASKS):
        raise Refused('PR is merged, but local task state has edits; preserve and reconcile them before switching to base')
    if current_branch(root) != base and git(root, 'switch', base) is None:
        git(root, 'switch', '-c', base, f'origin/{base}')
    pulled = git(root, 'pull', '--ff-only', '--quiet', 'origin', base)
    if current_branch(root) != branch:
        if pulled is not None and current_branch(root) == base:
            git(root, 'branch', '-D', branch)
        git(root, 'branch', '-D', '-r', f'origin/{branch}')
    print(f'{task_id} merged into {base}' + (f': {url}' if url else ''))
    if current_branch(root) != base:
        print(f'note: could not switch to {base}; run `git switch {base}` and `git pull --ff-only origin {base}`')
    elif pulled is None:
        print(f'note: could not fast-forward local {base}; run `git pull --ff-only origin {base}`')
    ready = State(root).ready()
    print('next: ' + (f'`start {ready[0]["id"]}`' if ready else '`status`'))
    return 0


def cmd_check(root, args):
    state = State(root, require_tasks=False)
    checks = state.checks()
    selected = args.ids or [check['id'] for check in checks.values() if check.get('required')]
    if not selected:
        raise Refused('no required checks configured; declare them in docs/config.json', 2)
    unknown = set(selected) - set(checks)
    if unknown:
        raise Refused('unknown checks: ' + ', '.join(sorted(unknown)), 2)
    before, configuration = state.file_digests(), digest(state.config)
    runs = root / RUNS
    runs.mkdir(parents=True, exist_ok=True)
    stamp = time.time_ns()
    results = [run_check(root, checks[ident], runs / f'check-{stamp}-{ident}.log') for ident in dict.fromkeys(selected)]
    for result in results:
        print(f'{result["id"]}: {result["outcome"]} (log {result["log"]})')
        if result['outcome'] != 'passed':
            print(tail(root / result['log']))
    after = State(root, require_tasks=False)
    changed = before != after.file_digests() or configuration != digest(after.config)
    if changed:
        print('check failed: inputs changed during checks')
    return int(changed or any(result['outcome'] != 'passed' for result in results))


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
    return (review.get('result') == 'pass' and review.get('filesHash') == state.files_hash()
            and review.get('taskHash') == task_hash(task) and review.get('configHash') == digest(state.config)
            and review.get('proofHash') == digest((task.get('evidence') or {}).get('proof')))


def cmd_review(root, args):
    if args.result is None:
        raise Refused('give --pass or --fail', 2)

    def change(state, task):
        if task.get('state') != 'verified':
            raise Refused(f'{task["id"]} is {task.get("state")}; review a task after `verify {task["id"]}` passes')
        reason = stale_reason(state, task)
        if reason:
            raise Refused(f'{task["id"]} evidence is stale ({reason}); `verify {task["id"]}` again before the review')
        proof = parse_proof(args.proof or [f'{key}={value}' for key, value in
                            task['evidence'].get('proof', {}).items()], task)
        task['evidence']['proof'] = proof
        task['evidence']['review'] = {'result': args.result, 'by': args.by, 'summary': args.summary,
                                      'at': now(), 'filesHash': state.files_hash(), 'taskHash': task_hash(task),
                                      'configHash': digest(state.config), 'proofHash': digest(proof)}
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
    settings = delivery(state)
    if settings['mode'] == 'pr' and pending and current_branch(root) == settings['base']:
        found.append(f'uncommitted changes on {settings["base"]}, which changes only through pull requests; move them to a task')
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


def cmd_hook(root, args):
    """Git runs `pre-commit` and `pre-push` through the hooks that `start` installs; `install` sets them up by hand."""
    if args.name == 'install':
        if git(root, 'rev-parse', '--is-inside-work-tree') is None:
            raise Refused('not a git repository')
        for note in ensure_hooks(root):
            print(note)
        print('hooks: pre-commit runs the checks marked "precommit"; pre-push blocks pushes to the base branch')
        return 0
    if not (root / TASKS).exists():
        return 0
    state = State(root)
    if args.name == 'pre-push':
        settings = delivery(state)
        if settings['mode'] != 'pr' or os.environ.get('HARNESS_BASE_PUSH') == '1':
            return 0
        for line in sys.stdin:  # one line per ref: <local ref> <local sha> <remote ref> <remote sha>
            fields = line.split()
            if len(fields) == 4 and fields[2] == f'refs/heads/{settings["base"]}':
                print(f'Blocked by the harness: {settings["base"]} changes only through pull requests. '
                      'Finish the task with: python3 scripts/harness.py done ID', file=sys.stderr)
                return 1
        return 0
    runs = root / RUNS
    runs.mkdir(parents=True, exist_ok=True)
    stamp = now().replace('-', '').replace(':', '')
    results = [run_check(root, check, runs / f'precommit-{stamp}-{check["id"]}.log')
               for check in state.config.get('checks') or []
               if isinstance(check, dict) and check.get('precommit') and check.get('id') and check.get('argv')]
    failed = [result for result in results if result['outcome'] != 'passed']
    for result in failed:
        print(f'pre-commit: {result["id"]} {result["outcome"]} (exit {result["exit"]}), log {result["log"]}\n'
              + tail(root / result['log']), file=sys.stderr)
    if failed:
        print('fix it and commit again; never skip this hook with --no-verify', file=sys.stderr)
    return 1 if failed else 0


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
    type_help = 'kind of change; names the branch and the pull request title'
    command('check', cmd_check, 'run declared required checks (same command locally and in CI)',
            (['ids'], {'nargs': '*', 'help': 'optional specific check IDs'}))
    command('status', cmd_status, 'where things stand and the next step; start every session here')
    command('list', cmd_list, 'one line per open task', (['--all'], {'action': 'store_true', 'help': 'include passing and dropped tasks'}))
    command('show', cmd_show, 'full detail, evidence and notes for one task', task_id)
    command('add', cmd_add, 'queue a task',
            (['behavior'], {'help': 'observable outcome, one sentence'}),
            (['--type'], {'choices': TYPES, 'default': 'feat', 'help': type_help}),
            (['--accept'], dict(many, help='acceptance criterion (repeat)')),
            (['--check'], dict(many, help='check id from docs/config.json (repeat)')),
            (['--after'], dict(many, help='task id this depends on (repeat)')),
            (['--ref'], dict(many, help='related id in docs, e.g. R-2 or A-1 (repeat)')),
            (['--keep'], dict(many, help=keep_help)),
            (['--review'], {'action': 'store_true', 'help': 'require an independent review before done'}))
    command('edit', cmd_edit, 'change a task; each list option replaces the list ("none" clears it)', task_id,
            (['--behavior'], {}), (['--type'], {'choices': TYPES, 'help': type_help}),
            (['--accept'], dict(many)), (['--check'], dict(many)),
            (['--after'], dict(many)), (['--ref'], dict(many)), (['--keep'], dict(many, help=keep_help)),
            (['--review'], {'choices': ['on', 'off'], 'help': 'require an independent review before done'}))
    command('review', cmd_review, 'record an independent review of a verified task', task_id,
            (['--pass'], {'dest': 'result', 'action': 'store_const', 'const': 'pass'}),
            (['--fail'], {'dest': 'result', 'action': 'store_const', 'const': 'fail'}),
            (['--summary'], {'required': True, 'help': 'findings, with evidence'}),
            (['--proof'], dict(many, help='N=check-id: evidence; defaults to verified proof')),
            (['--by'], {'default': 'reviewer', 'help': 'who reviewed, e.g. subagent or a name'}))
    command('wrapup', cmd_wrapup, 'end-of-session check: required checks, debug leftovers, uncommitted work',
            (['--note'], {'help': 'what is done and what is next; required while a task is in progress'}))
    command('start', cmd_start, 'make a ready task active on its own branch (one task in progress at a time)', task_id)
    command('verify', cmd_verify, 'run the task checks plus required checks and record the result', task_id,
            (['--proof'], dict(many, help='N=check-id: evidence (repeat for each criterion)')))
    command('done', cmd_done, 'finish a verified, committed task: push, pull request, checks, merge', task_id,
            (['--proof'], dict(many, help='N=check-id: evidence for acceptance criterion N (one per criterion)')))
    command('block', cmd_block, 'stop a task that cannot proceed', task_id, (['--reason'], {'required': True}))
    command('drop', cmd_drop, 'remove an unfinished task from the plan, keeping its record', task_id,
            (['--reason'], {'required': True}))
    command('reopen', cmd_reopen, 'return a verified or passing task to active', task_id, (['--reason'], {'required': True}))
    command('note', cmd_note, 'append a short dated note: decision, finding, or next step', task_id, (['text'], {}))
    command('validate', cmd_validate, 'check docs/tasks.json and docs/config.json for structural problems')
    command('hook', cmd_hook, 'git hooks: pre-commit runs the checks marked "precommit", pre-push blocks pushes to the '
            'base branch; `hook install` sets them up (`start` does it too)', (['name'], {'choices': ('install',) + HOOKS}))
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
