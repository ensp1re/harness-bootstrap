"""Installed-project probes; the generated runner and docs work without the skill."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from test_harness import Repo, RemoteRepo, OK, PY, SKILL, bootstrap


class GeneratedProbe(unittest.TestCase):
    def test_installed_workflow_registry_and_document_checks(self):
        with tempfile.TemporaryDirectory(prefix='generated-probe-') as directory:
            root = Path(directory)
            code, out = bootstrap('install', root)
            self.assertEqual(code, 0, out)
            config = json.loads((root / 'docs/config.json').read_text())
            self.assertFalse(config['delivery']['autoMerge'])
            self.assertEqual(config['delivery']['mode'], 'pr')
            config['delivery']['mode'] = 'local'
            config['checks'].append({'id': 'unit', 'argv': [PY, '-m', 'unittest', 'discover', '-s', 'tests'], 'required': True})
            (root / 'docs/config.json').write_text(json.dumps(config))
            (root / 'tests').mkdir()
            (root / 'tests/test_example.py').write_text('import unittest\nclass Example(unittest.TestCase):\n def test_add(self): self.assertEqual(2+2,4)\n')
            def run(*args):
                return subprocess.run([PY, str(root / 'scripts/harness.py'), *args], cwd=root,
                                      capture_output=True, text=True)
            self.assertEqual(run('check').returncode, 0)
            self.assertEqual(run('add', 'example', '--accept', 'addition works', '--check', 'unit', '--review').returncode, 0)
            self.assertEqual(run('start', 'F001').returncode, 0)
            self.assertEqual(run('verify', 'F001', '--proof', '1=unit: addition').returncode, 0)
            self.assertIn('proof 1: unit: addition', run('show', 'F001').stdout)
            self.assertEqual(run('review', 'F001', '--pass', '--summary', 'test proves addition').returncode, 0)
            self.assertEqual(run('done', 'F001').returncode, 0)
            before = (root / 'docs/tasks.json').read_bytes()
            (root / 'AGENTS.md').write_text('# User rule\n\n' + (root / 'AGENTS.md').read_text())
            (root / 'docs/PROJECT.md').write_text('# Example\n\n| D-1 | Keep Python |\n')
            for _ in range(2):
                self.assertEqual(bootstrap('install', root)[0], 0)
                self.assertEqual((root / 'docs/tasks.json').read_bytes(), before)
                self.assertEqual(json.loads((root / 'docs/config.json').read_text())['delivery']['mode'], 'local')
            self.assertEqual(run('check').returncode, 0)
            (root / 'docs/other.md').write_text('| D-1 | conflicting decision |\n[broken](missing.md)\n')
            result = run('check')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('duplicate decision', result.stdout)
            self.assertIn('broken link', result.stdout)

    def test_legacy_v2_completion_stays_historical(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK}])
        repo.run('add', 'old completion', '--accept', 'works', '--check', 'ok')
        path = repo.root / 'docs/tasks.json'
        data = json.loads(path.read_text()); task = data['tasks'][0]
        task['state'] = 'passing'
        payload = {key: task.get(key) for key in ('behavior', 'acceptance', 'verification')}
        task['evidence'] = {'version': 2, 'status': 'passed', 'taskHash': hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16], 'proof': {'1': 'legacy prose'}}
        repo.write('docs/tasks.json', data)
        before = path.read_bytes()
        self.assertNotIn('definition changed', repo.run('status')[1])
        bootstrap('install', repo.root)
        self.assertEqual(path.read_bytes(), before)
        repo.run('add', 'next', '--accept', 'works', '--check', 'ok', '--after', 'F001')
        self.assertEqual(repo.run('start', 'F002')[0], 0)
        self.assertEqual(repo.tasks()['F001'], task)

    def test_missing_pnpm_filtered_script_never_executes_fake_success(self):
        repo = Repo(self, [{'id': 'e2e', 'argv': ['pnpm', '--filter', '@fixture/web', 'e2e']}])
        repo.write('apps/web/package.json', {'name': '@fixture/web', 'scripts': {'test': 'echo ok'}})
        tools = repo.root / 'bin'; tools.mkdir()
        exe = tools / 'pnpm'; exe.write_text('#!/bin/sh\nexit 0\n'); exe.chmod(0o755)
        repo.env = dict(os.environ, PATH=str(tools)+os.pathsep+os.environ['PATH'])
        repo.run('add', 'browser behavior', '--accept', 'works', '--check', 'e2e')
        repo.run('start', 'F001')
        code, out = repo.run('verify', 'F001')
        self.assertNotEqual(code, 0, out)
        self.assertIn('missing package script', out)
        repo.write('apps/web/package.json', {'name': '@fixture/web', 'scripts': {'e2e': 'echo ok'}})
        self.assertEqual(repo.run('verify', 'F001')[0], 0)

    def test_installer_does_not_follow_symlinks_or_overwrite_non_utf8(self):
        for name in ('AGENTS.md', 'scripts/harness.py', '.gitignore'):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory(prefix='install-containment-') as directory:
                    home = Path(directory); root = home / 'project'; root.mkdir()
                    other = home / 'user'; other.write_text('user-owned')
                    dest = root / name; dest.parent.mkdir(parents=True, exist_ok=True); dest.symlink_to(other)
                    self.assertNotEqual(bootstrap('install', root)[0], 0)
                    self.assertEqual(other.read_text(), 'user-owned')
                    dest.unlink(); dest.write_bytes(b'\xff')
                    self.assertNotEqual(bootstrap('install', root)[0], 0)
                    self.assertEqual(dest.read_bytes(), b'\xff')

    def test_delivery_commit_runs_precommit_hooks(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}])
        repo.run('add', 'work', '--accept', 'works', '--check', 'ok')
        repo.run('start', 'F001'); repo.run('verify', 'F001'); repo.commit('work')
        hook = repo.root / '.git/hooks/pre-commit'; hook.write_text('#!/bin/sh\necho rejected >&2\nexit 1\n'); hook.chmod(0o755)
        code, out = repo.run('done', 'F001', '--proof', '1=ok')
        self.assertNotEqual(code, 0, out)
        self.assertIn('rejected', out)
        self.assertEqual(repo.pull_requests(), [])

    def test_package_manager_redirection_is_rejected(self):
        repo = Repo(self, [{'id': 'unit', 'argv': ['npm', 'run', 'test', '--prefix', 'other']}])
        repo.write('package.json', {'scripts': {'test': 'exit 1'}})
        repo.write('other/package.json', {'scripts': {'test': 'exit 0'}})
        repo.run('add', 'root behavior', '--accept', 'works', '--check', 'unit')
        repo.run('start', 'F001')
        self.assertNotEqual(repo.run('verify', 'F001')[0], 0)

    def test_keep_requires_readable_base(self):
        for use_git in (False, True):
            with self.subTest(use_git=use_git):
                repo = Repo(self, [{'id': 'ok', 'argv': OK}], use_git=use_git)
                repo.run('add', 'stable API', '--accept', 'works', '--check', 'ok', '--keep', 'src/*')
                repo.run('start', 'F001')
                data = json.loads((repo.root / 'docs/tasks.json').read_text())
                data['tasks'][0]['baseCommit'] = 'nonexistent-commit'
                repo.write('docs/tasks.json', data)
                repo.write('src/a.py', 'changed')
                self.assertNotEqual(repo.run('verify', 'F001')[0], 0)

    def test_fixed_temporary_files_are_never_overwritten(self):
        for install in (False, True):
            with self.subTest(install=install):
                repo = Repo(self, [{'id': 'ok', 'argv': OK}])
                repo.write('user.txt', 'keep me')
                name = 'scripts/harness.py.tmp' if install else 'docs/tasks.json.tmp'
                (repo.root / name).symlink_to(repo.root / 'user.txt')
                if install:
                    # Missing runner exercises actual installer write.
                    (repo.root / 'scripts/harness.py').unlink()
                    bootstrap('install', repo.root)
                else:
                    repo.run('add', 'new task')
                self.assertEqual((repo.root / 'user.txt').read_text(), 'keep me')
                self.assertTrue((repo.root / name).is_symlink())

    def test_owner_merge_does_not_overwrite_dirty_queue(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}], delivery={'mode': 'pr', 'autoMerge': False})
        repo.run('add', 'work', '--accept', 'works', '--check', 'ok')
        repo.run('start', 'F001'); repo.run('verify', 'F001'); repo.commit('work')
        self.assertNotEqual(repo.run('done', 'F001', '--proof', '1=ok')[0], 0)
        repo.run('note', 'F001', 'local note must survive')
        before = (repo.root / 'docs/tasks.json').read_bytes()
        branch = repo.branch()
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo.root, capture_output=True, text=True).stdout.strip()
        merged = subprocess.run(['gh', 'pr', 'merge', '1', '--match-head-commit', head], cwd=repo.root,
                                env=repo.env, capture_output=True, text=True)
        self.assertEqual(merged.returncode, 0, merged.stderr)
        code, out = repo.run('done', 'F001')
        self.assertNotEqual(code, 0, out)
        self.assertEqual(repo.branch(), branch)
        self.assertEqual((repo.root / 'docs/tasks.json').read_bytes(), before)

    def test_start_preserves_tasks_added_on_remote_base(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}])
        repo.run('add', 'first', '--accept', 'works', '--check', 'ok')
        repo.commit('queue first')
        repo.git('push', 'origin', 'main')
        base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo.root, capture_output=True, text=True).stdout.strip()
        repo.run('add', 'new remote task', '--accept', 'works', '--check', 'ok')
        repo.commit('remote queue'); repo.git('push', 'origin', 'main')
        repo.git('reset', '--hard', base)
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 0, out)
        self.assertEqual(set(repo.tasks()), {'F001', 'F002'})

    def test_executable_mode_changes_invalidate_evidence(self):
        repo = Repo(self, [{'id': 'cli', 'argv': ['./cli.sh']}])
        repo.write('cli.sh', '#!/bin/sh\nexit 0\n')
        (repo.root / 'cli.sh').chmod(0o755); repo.commit('cli')
        repo.run('add', 'cli', '--accept', 'works', '--check', 'cli'); repo.run('start', 'F001')
        self.assertEqual(repo.run('verify', 'F001')[0], 0); repo.commit('verified')
        (repo.root / 'cli.sh').chmod(0o644); repo.commit('mode change')
        self.assertNotEqual(repo.run('done', 'F001', '--proof', '1=cli')[0], 0)

    def test_unmet_dependencies_cannot_be_verified(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK}])
        for behavior in ('first', 'dependency'):
            repo.run('add', behavior, '--accept', 'works', '--check', 'ok')
        repo.run('start', 'F001'); repo.run('edit', 'F001', '--after', 'F002')
        code, out = repo.run('verify', 'F001')
        self.assertNotEqual(code, 0, out)

    def test_owner_merge_preserves_later_local_commits(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}], delivery={'mode': 'pr', 'autoMerge': False})
        repo.run('add', 'work', '--accept', 'works', '--check', 'ok')
        repo.run('start', 'F001'); repo.run('verify', 'F001'); repo.commit('work')
        repo.run('done', 'F001', '--proof', '1=ok')
        branch = repo.branch()
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo.root, capture_output=True, text=True).stdout.strip()
        subprocess.run(['gh', 'pr', 'merge', '1', '--match-head-commit', head], cwd=repo.root, env=repo.env, check=True)
        repo.write('later.txt', 'local work'); repo.commit('later')
        self.assertNotEqual(repo.run('done', 'F001')[0], 0)
        self.assertEqual(repo.branch(), branch)
        self.assertEqual((repo.root / 'later.txt').read_text(), 'local work')

    def test_start_preserves_committed_local_and_remote_tasks(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}])
        repo.run('add', 'first', '--accept', 'works', '--check', 'ok')
        repo.commit('common queue'); repo.git('push', 'origin', 'main')
        common = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo.root, capture_output=True, text=True).stdout.strip()
        repo.run('add', 'local task', '--accept', 'works', '--check', 'ok'); repo.commit('local queue')
        repo.git('switch', '-c', 'remote-update', common)
        data = json.loads((repo.root / 'docs/tasks.json').read_text()); data['nextId'] = 3
        repo.write('docs/tasks.json', data)
        repo.run('add', 'remote task', '--accept', 'works', '--check', 'ok'); repo.commit('remote queue')
        repo.git('push', 'origin', 'HEAD:main'); repo.git('switch', 'main')
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 0, out)
        self.assertEqual(set(repo.tasks()), {'F001', 'F002', 'F003'})

    def test_reopen_owner_merged_task_uses_new_base_branch(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}], delivery={'mode': 'pr', 'autoMerge': False})
        repo.run('add', 'work', '--accept', 'works', '--check', 'ok')
        repo.run('start', 'F001'); repo.run('verify', 'F001'); repo.commit('work')
        repo.run('done', 'F001', '--proof', '1=ok')
        branch = repo.branch()
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo.root, capture_output=True, text=True).stdout.strip()
        subprocess.run(['gh', 'pr', 'merge', '1', '--match-head-commit', head], cwd=repo.root, env=repo.env, check=True)
        repo.git('fetch', 'origin')
        code, out = repo.run('reopen', 'F001', '--reason', 'new requirement')
        self.assertEqual(code, 0, out)
        self.assertNotEqual(repo.branch(), branch)
        self.assertEqual(repo.tasks()['F001']['state'], 'active')

    def test_dependency_mutation_during_checks_fails(self):
        script = "import json; from pathlib import Path; p=Path('docs/tasks.json'); d=json.loads(p.read_text()); d['tasks'][0]['state']='not_started'; p.write_text(json.dumps(d))"
        repo = Repo(self, [{'id': 'ok', 'argv': OK}, {'id': 'mutate', 'argv': [PY, '-c', script]}])
        repo.run('add', 'dependency', '--accept', 'works', '--check', 'ok')
        repo.run('start', 'F001'); repo.run('verify', 'F001'); repo.commit('dependency')
        self.assertEqual(repo.run('done', 'F001', '--proof', '1=ok')[0], 0)
        repo.run('add', 'dependent', '--accept', 'works', '--check', 'mutate', '--after', 'F001')
        self.assertEqual(repo.run('start', 'F002')[0], 0)
        self.assertNotEqual(repo.run('verify', 'F002')[0], 0)
