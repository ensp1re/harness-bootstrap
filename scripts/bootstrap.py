#!/usr/bin/env python3
"""Inspect a repository, then install or update the harness in it.

  python3 scripts/bootstrap.py inspect ROOT
  python3 scripts/bootstrap.py install ROOT [--dry-run] [--claude]

install copies assets/harness.py to scripts/harness.py, creates docs/tasks.json and docs/config.json
when missing, adds the harness block to AGENTS.md and ignores run logs in .gitignore. It records hashes
of what it wrote in docs/install.json, so a rerun updates only content nobody changed since and reports
everything else instead of overwriting it.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SKILL_VERSION = '2.0.0'
SKILL = Path(__file__).resolve().parents[1]
START, END = '<!-- harness:start', '<!-- harness:end -->'
IGNORE_LINES = ('docs/runs/', 'docs/.harness.lock')
LEGACY = ('docs/handoff.json', 'docs/SESSION_HANDOFF.md', 'docs/PLAN.md', 'docs/archive',
          'scripts/harness-runner.mjs', 'cmd/harness')
SKIP = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build', '.next', 'target', 'coverage'}
TOOLS = (('python3', '--version'), ('node', '--version'), ('npm', '--version'), ('pnpm', '--version'),
         ('yarn', '--version'), ('bun', '--version'), ('deno', '--version'), ('uv', '--version'),
         ('go', 'version'), ('cargo', '--version'), ('java', '--version'), ('ruby', '--version'),
         ('php', '--version'), ('dotnet', '--version'), ('docker', '--version'), ('gh', '--version'))
MANIFESTS = ('requirements.txt', 'requirements-dev.txt', 'setup.py', 'tox.ini', 'noxfile.py', 'go.mod',
             'Cargo.toml', 'Gemfile', 'composer.json', 'pom.xml', 'build.gradle', 'build.gradle.kts',
             'Makefile', 'justfile', 'Taskfile.yml', 'Dockerfile', 'docker-compose.yml', 'compose.yaml',
             '.pre-commit-config.yaml', '.env.example', 'playwright.config.ts', 'playwright.config.js')


def run(root, *command):
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def text_or_none(path):
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def walk(root, limit=5000):
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = sorted(name for name in subdirs if name not in SKIP)
        for name in files:
            yield Path(directory, name).relative_to(root)
            limit -= 1
            if limit <= 0:
                return


def read_install(root):
    try:
        data = json.loads((root / 'docs/install.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'files': {}}
    files = data.get('files') if isinstance(data, dict) else None
    if isinstance(files, list):
        files = {item.get('path'): item.get('sha256') for item in files if isinstance(item, dict)}
    elif isinstance(files, dict):
        files = {key: value.get('sha256') if isinstance(value, dict) else value for key, value in files.items()}
    data = data if isinstance(data, dict) else {}
    data['files'] = files or {}
    return data


def inspect(root):
    print(f'root: {root}')
    if run(root, 'git', 'rev-parse', '--is-inside-work-tree') is None:
        print('git: not a repository')
    else:
        remotes = sorted({re.sub(r'^.*?(?:@|://)([^/:]+).*$', r'\1', line.split()[1])
                          for line in (run(root, 'git', 'remote', '-v') or '').splitlines() if len(line.split()) > 1})
        dirty = len((run(root, 'git', 'status', '--porcelain') or '').splitlines())
        print(f'git: branch {run(root, "git", "branch", "--show-current") or "?"}, '
              f'{run(root, "git", "rev-list", "--count", "HEAD") or 0} commits, {dirty} uncommitted paths, '
              f'remotes: {", ".join(remotes) or "none"}')
    tools = []
    for tool, flag in TOOLS:
        if shutil.which(tool):
            version = re.search(r'\d+(?:\.\d+)+', run(root, tool, flag) or '')
            tools.append(tool + (f' {version.group(0)}' if version else ''))
    print('tools: ' + (', '.join(tools) or 'none found'))

    names = (run(root, 'git', 'ls-files') or '').splitlines() or [path.as_posix() for path in walk(root)]
    kinds = Counter(Path(name).suffix or Path(name).name for name in names)
    print(f'files: {len(names)}; ' + ', '.join(f'{kind} {count}' for kind, count in kinds.most_common(8)))

    package = text_or_none(root / 'package.json')
    if package is not None:
        try:
            data = json.loads(package)
            lock = next((name for name in ('package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', 'bun.lock', 'bun.lockb')
                         if (root / name).exists()), 'no lockfile')
            print(f'package.json: {data.get("name", "?")}, {lock}'
                  + (f', packageManager {data["packageManager"]}' if data.get('packageManager') else ''))
            for name, command in (data.get('scripts') or {}).items():
                print(f'  script {name}: {command}')
            deps = sorted({**(data.get('dependencies') or {}), **(data.get('devDependencies') or {})})
            if deps:
                print('  deps: ' + ', '.join(deps[:40]) + (' ...' if len(deps) > 40 else ''))
        except ValueError:
            print('package.json: invalid JSON')
    pyproject = text_or_none(root / 'pyproject.toml')
    if pyproject is not None:
        print('pyproject.toml sections: ' + ', '.join(re.findall(r'^\[([^\]]+)\]', pyproject, re.M)[:25]))
    for name in MANIFESTS:
        text = text_or_none(root / name)
        if text is None:
            continue
        detail = ''
        if name == 'Makefile':
            detail = ' targets: ' + ', '.join(re.findall(r'^([A-Za-z0-9_.-]+):(?!=)', text, re.M)[:20])
        elif name == 'go.mod':
            detail = ' ' + '; '.join(line for line in text.splitlines() if line.startswith(('module ', 'go ')))
        print(f'{name}:{detail}')

    workflows = root / '.github/workflows'
    for path in sorted(workflows.glob('*.y*ml')) if workflows.is_dir() else []:
        steps = ['(multi-line script)' if value.strip() in ('|', '>') else value.strip()
                 for value in re.findall(r'^\s*(?:-\s*)?run:\s*(.+)$', text_or_none(path) or '', re.M)]
        print(f'ci {path.relative_to(root).as_posix()}: ' + ('; '.join(steps[:8]) or 'no run steps'))
    for name in ('.gitlab-ci.yml', '.circleci/config.yml', 'azure-pipelines.yml', 'Jenkinsfile'):
        if (root / name).exists():
            print(f'ci: {name}')

    for name in ('AGENTS.md', 'CLAUDE.md', '.cursorrules', '.github/copilot-instructions.md', 'CONTRIBUTING.md',
                 'README.md', 'README.rst', 'README'):
        text = text_or_none(root / name)
        if text is not None:
            print(f'doc {name}: {len(text.splitlines())} lines' + (', has harness block' if START in text else ''))
    if (root / '.cursor/rules').is_dir():
        print('doc .cursor/rules/: present')
    if (root / 'docs').is_dir():
        print('docs/: ' + ', '.join(sorted(path.name for path in (root / 'docs').iterdir())[:25]))
    tests = sorted({path.parent.as_posix() for path in walk(root)
                    if set(path.parent.parts) & {'test', 'tests', '__tests__', 'spec', 'e2e'}})
    if tests:
        print('test folders: ' + ', '.join(tests[:10]))

    tasks = text_or_none(root / 'docs/tasks.json')
    if tasks is not None:
        try:
            data = json.loads(tasks)
            states = Counter(task.get('state') for task in data.get('tasks', []))
            print(f'harness: docs/tasks.json schemaVersion {data.get("schemaVersion")}; '
                  + (', '.join(f'{count} {state}' for state, count in states.items()) or 'no tasks'))
        except (ValueError, AttributeError):
            print('harness: docs/tasks.json is not valid JSON')
    installed = read_install(root).get('skillVersion')
    if installed:
        print(f'harness: installed by harness-bootstrap {installed} (this skill is {SKILL_VERSION})')
    legacy = [name for name in LEGACY if (root / name).exists()]
    if legacy:
        print('legacy harness files: ' + ', '.join(legacy) + ' (see references/harness.md, "Migrating")')
    return 0


def extract_block(text):
    if text is None or START not in text or END not in text:
        return None
    start = text.index(START)
    return text[start:text.index(END, start) + len(END)]


def install(root, dry_run, claude):
    before = read_install(root)
    recorded, hashes, report = before['files'], {}, []

    def managed(key, current, new, write, respect_removal=False):
        """Write only when absent, identical, or unchanged since the last install recorded its hash."""
        if current == new:
            hashes[key] = sha(new)
            report.append(('unchanged', key))
        elif current is None and respect_removal and key in recorded:
            report.append(('left removed', key))
        elif current is None or sha(current) == recorded.get(key):
            hashes[key] = sha(new)
            report.append(('created' if current is None else 'updated', key))
            if not dry_run:
                write()
        else:
            if key in recorded:
                hashes[key] = recorded[key]
            report.append(('conflict', key))

    runner_path = root / 'scripts/harness.py'
    runner = (SKILL / 'assets/harness.py').read_text(encoding='utf-8')
    managed('scripts/harness.py', text_or_none(runner_path), runner, lambda: write_text(runner_path, runner))

    agents_path = root / 'AGENTS.md'
    agents = text_or_none(agents_path)
    block = (SKILL / 'assets/agents-block.md').read_text(encoding='utf-8').strip()
    current = extract_block(agents)

    def write_block():
        if agents is None:
            write_text(agents_path, f'# {root.name}\n\n{block}\n')
        elif current is None:
            write_text(agents_path, agents.rstrip() + f'\n\n{block}\n')
        else:
            write_text(agents_path, agents.replace(current, block))
    managed('AGENTS.md#harness', current, block, write_block, respect_removal=True)

    for relative, default in (('docs/tasks.json', {'schemaVersion': 2, 'nextId': 1, 'tasks': []}),
                              ('docs/config.json', {'schemaVersion': 2, 'checks': []})):
        if (root / relative).exists():
            report.append(('kept', relative))
        else:
            report.append(('created', relative))
            if not dry_run:
                write_text(root / relative, json.dumps(default, indent=2) + '\n')

    ignore_path = root / '.gitignore'
    ignore = text_or_none(ignore_path) or ''
    missing = [line for line in IGNORE_LINES if line not in ignore.splitlines()]
    if missing:
        report.append(('updated' if ignore else 'created', '.gitignore: ' + ', '.join(missing)))
        if not dry_run:
            write_text(ignore_path, ignore + ('\n' if ignore and not ignore.endswith('\n') else '') + '\n'.join(missing) + '\n')
    if claude and not (root / 'CLAUDE.md').exists():
        report.append(('created', 'CLAUDE.md'))
        if not dry_run:
            write_text(root / 'CLAUDE.md', '@AGENTS.md\n')

    if not dry_run and (hashes != recorded or before.get('skillVersion') != SKILL_VERSION):
        write_text(root / 'docs/install.json', json.dumps({
            'schemaVersion': 2, 'skillVersion': SKILL_VERSION, 'files': hashes,
            'updatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}, indent=2) + '\n')
    for status, name in report:
        print(f'{status}: {name}')
    for name in LEGACY:
        if (root / name).exists():
            print(f'legacy: {name} (previous harness version; see references/harness.md, "Migrating")')
    conflicts = [name for status, name in report if status == 'conflict']
    if conflicts:
        print('conflict means the file changed since it was installed; it was not touched. '
              f'Compare it with {SKILL}/assets and merge by hand.')
    if dry_run:
        print('dry run: nothing was written')
    return 1 if conflicts else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inspect', help='print repository facts').add_argument('root', type=Path)
    item = sub.add_parser('install', help='install or update harness files')
    item.add_argument('root', type=Path)
    item.add_argument('--dry-run', action='store_true', help='report what would change without writing')
    item.add_argument('--claude', action='store_true', help='also create CLAUDE.md importing AGENTS.md when missing')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f'error: {root} is not a directory', file=sys.stderr)
        return 2
    return inspect(root) if args.command == 'inspect' else install(root, args.dry_run, args.claude)


if __name__ == '__main__':
    sys.exit(main())
