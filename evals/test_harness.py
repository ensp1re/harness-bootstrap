"""Black-box tests for assets/harness.py (the runner copied into projects) and scripts/bootstrap.py."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
RUNNER = SKILL / 'assets/harness.py'
PY = sys.executable
OK = [PY, '-c', 'pass']
FEATURE = [PY, '-c', "import pathlib, sys; sys.exit(0 if pathlib.Path('feature.txt').exists() else 1)"]


class Repo:
    """A disposable repository with the runner installed at scripts/harness.py."""

    def __init__(self, test, checks, tasks=None, use_git=True):
        directory = tempfile.TemporaryDirectory(prefix='harness-test-')
        test.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / 'scripts').mkdir()
        shutil.copy(RUNNER, self.root / 'scripts/harness.py')
        self.write('docs/config.json', {'schemaVersion': 2, 'checks': checks})
        self.write('docs/tasks.json', tasks or {'schemaVersion': 2, 'nextId': 1, 'tasks': []})
        self.write('.gitignore', 'docs/runs/\ndocs/.harness.lock\n')
        if use_git:
            self.git('init', '-q', '-b', 'main')
            self.commit('initial')

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data))

    def git(self, *args):
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args],
                       cwd=self.root, check=True, capture_output=True)

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-q', '--allow-empty', '-m', message)

    def run(self, *args):
        result = subprocess.run([PY, str(self.root / 'scripts/harness.py'), *args], cwd=self.root,
                                capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout + result.stderr

    def tasks(self):
        return {task['id']: task for task in json.loads((self.root / 'docs/tasks.json').read_text())['tasks']}


class RunnerTest(unittest.TestCase):
    def test_full_task_loop_requires_passing_checks_commit_and_proof(self):
        repo = Repo(self, [{'id': 'feature', 'argv': FEATURE}, {'id': 'suite', 'argv': OK, 'required': True}])
        self.assertEqual(repo.run('add', 'Feature file exists', '--accept', 'feature.txt is present',
                                  '--check', 'feature', '--ref', 'R-1')[0], 0)
        self.assertIn('Feature file exists (R-1)', repo.run('list')[1])
        self.assertIn('`start F001`', repo.run('status')[1])
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('docs/runs/F001-', out)
        self.assertEqual(repo.tasks()['F001']['state'], 'active')
        self.assertIn('feature failed', repo.run('status')[1])
        (repo.root / 'feature.txt').write_text('done\n')
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 0, out)
        self.assertEqual([c['id'] for c in repo.tasks()['F001']['evidence']['checks']], ['feature', 'suite'])
        code, out = repo.run('done', 'F001', '--proof', '1=feature check')
        self.assertEqual(code, 1, out)
        self.assertIn('feature.txt', out)
        repo.commit('feature')
        code, out = repo.run('done', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('--proof', out)
        code, out = repo.run('done', 'F001', '--proof', '1=feature check')
        self.assertEqual(code, 0, out)
        task = repo.tasks()['F001']
        self.assertEqual(task['state'], 'passing')
        self.assertTrue(task['evidence']['commit'])
        self.assertEqual(task['evidence']['proof'], {'1': 'feature check'})

    def test_one_task_in_progress_and_dependencies_must_pass(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK}])
        repo.run('add', 'first', '--accept', 'x', '--check', 'ok')
        repo.run('add', 'second', '--accept', 'x', '--check', 'ok')
        repo.run('add', 'third', '--accept', 'x', '--check', 'ok', '--after', 'F001')
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        self.assertIn('waiting: F003 on F001', repo.run('status')[1])
        code, out = repo.run('start', 'F002')
        self.assertEqual(code, 1)
        self.assertIn('F001 is active', out)
        self.assertEqual(repo.run('block', 'F001', '--reason', 'need an answer')[0], 0)
        code, out = repo.run('start', 'F003')
        self.assertEqual(code, 1)
        self.assertIn('waits on F001', out)
        self.assertEqual(repo.run('start', 'F002')[0], 0)
        self.assertIn('blocked: F001 need an answer', repo.run('status')[1])
        self.assertEqual(repo.run('verify', 'F002')[0], 0)
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 1, 'a verified task must be finished before another starts')
        self.assertIn('F002 is verified', out)

    def test_changes_after_verify_make_evidence_stale_but_bookkeeping_does_not(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK}])
        repo.write('src.txt', 'v1')
        repo.commit('src')
        repo.run('add', 'thing', '--accept', 'works', '--check', 'ok')
        repo.run('start', 'F001')
        self.assertEqual(repo.run('verify', 'F001')[0], 0)
        repo.run('note', 'F001', 'queue edits must not invalidate evidence')
        repo.run('add', 'unrelated follow-up')
        self.assertIn('commit, then `done F001 --proof', repo.run('status')[1])
        repo.write('src.txt', 'v2')
        code, out = repo.run('done', 'F001', '--proof', '1=ok')
        self.assertEqual(code, 1)
        self.assertIn('files changed', out)
        repo.write('src.txt', 'v1')
        repo.run('edit', 'F001', '--accept', 'works', '--accept', 'is fast')
        self.assertIn('definition changed', repo.run('status')[1])
        self.assertEqual(repo.run('verify', 'F001')[0], 0)
        repo.commit('verified')
        self.assertEqual(repo.run('done', 'F001', '--proof', '1=ok', '--proof', '2=ok')[0], 0)
        repo.run('edit', 'F001', '--accept', 'works for everyone')
        self.assertIn('attention: F001 passing but definition changed', repo.run('status')[1])
        self.assertEqual(repo.run('reopen', 'F001', '--reason', 'scope change')[0], 0)
        self.assertEqual(repo.tasks()['F001']['state'], 'active')

    def test_interrupted_verify_is_reported_and_recoverable(self):
        repo = Repo(self, [{'id': 'slow', 'argv': [PY, '-c', 'import time; time.sleep(8)']}], use_git=False)
        repo.run('add', 'slow thing', '--accept', 'x', '--check', 'slow')
        repo.run('start', 'F001')
        process = subprocess.Popen([PY, str(repo.root / 'scripts/harness.py'), 'verify', 'F001'], cwd=repo.root,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + 20
        while (repo.tasks()['F001'].get('evidence') or {}).get('status') != 'running':
            self.assertLess(time.time(), deadline)
            time.sleep(0.1)
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        out = repo.run('status')[1]
        self.assertIn('interrupted', out)
        self.assertFalse((repo.root / 'docs/.harness.lock').exists())
        repo.write('docs/config.json', {'schemaVersion': 2, 'checks': [{'id': 'slow', 'argv': OK}]})
        self.assertEqual(repo.run('verify', 'F001')[0], 0)

    def test_lock_left_by_dead_process_is_taken_over(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK}], use_git=False)
        dead = subprocess.Popen([PY, '-c', 'pass'])
        dead.wait()
        repo.write('docs/.harness.lock', str(dead.pid))
        self.assertEqual(repo.run('add', 'after a crash')[0], 0)

    def test_missing_command_and_timeout_never_pass(self):
        repo = Repo(self, [{'id': 'missing', 'argv': ['no-such-command-for-harness-test']},
                           {'id': 'slow', 'argv': [PY, '-c', 'import time; time.sleep(5)'], 'timeoutSeconds': 1}],
                    use_git=False)
        repo.run('add', 'x', '--accept', 'y', '--check', 'missing', '--check', 'slow')
        repo.run('start', 'F001')
        self.assertEqual(repo.run('verify', 'F001')[0], 1)
        outcomes = {check['id']: check['outcome'] for check in repo.tasks()['F001']['evidence']['checks']}
        self.assertEqual(outcomes, {'missing': 'missing-command', 'slow': 'timeout'})
        self.assertEqual(repo.tasks()['F001']['state'], 'active')

    def test_invalid_state_is_reported_without_traceback(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK}], use_git=False)
        repo.write('docs/tasks.json', '{broken')
        code, out = repo.run('status')
        self.assertEqual(code, 2)
        self.assertIn('not valid JSON', out)
        self.assertNotIn('Traceback', out)
        repo.write('docs/tasks.json', {'schemaVersion': 2, 'nextId': 4, 'tasks': [
            {'id': 'F001', 'behavior': 'a', 'state': 'not_started', 'dependsOn': ['F002'], 'verification': ['nope']},
            {'id': 'F002', 'behavior': 'b', 'state': 'not_started', 'dependsOn': ['F001']},
            {'id': 'F003', 'behavior': 'c', 'state': 'not_started'},
            {'id': 'F003', 'behavior': 'd', 'state': 'not_started'}]})
        code, out = repo.run('validate')
        self.assertEqual(code, 1)
        for text in ('duplicate id', 'not defined', 'dependency cycle'):
            self.assertIn(text, out)

    def test_drop_incomplete_tasks_and_repeated_failures(self):
        repo = Repo(self, [{'id': 'fail', 'argv': [PY, '-c', 'raise SystemExit(3)']}], use_git=False)
        repo.run('add', 'vague idea')
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 1)
        self.assertIn('needs acceptance', out)
        repo.run('add', 'depends on the idea', '--accept', 'x', '--check', 'fail', '--after', 'F001')
        code, out = repo.run('drop', 'F001', '--reason', 'split into smaller tasks')
        self.assertEqual(code, 0, out)
        self.assertIn('F002', out)
        self.assertIn('depends on dropped F001', repo.run('status')[1])
        repo.run('edit', 'F002', '--after', 'none')
        self.assertEqual(repo.run('start', 'F002')[0], 0)
        for _ in range(3):
            code, out = repo.run('verify', 'F002')
        self.assertIn('3 failed verifies in a row', out)

    def test_previous_version_state_is_readable(self):
        legacy = {'schemaVersion': 1, 'nextId': 3, 'tasks': [
            {'id': 'F001', 'behavior': 'old done', 'acceptance': ['a'], 'dependsOn': [], 'state': 'passing',
             'verification': ['ok'], 'evidence': {'status': 'passed', 'fingerprintBefore': 'x'}, 'delivery': None,
             'spec': None, 'plan': None, 'blockedReason': None},
            {'id': 'F002', 'behavior': 'old verified', 'acceptance': ['b'], 'dependsOn': ['F001'],
             'state': 'verified', 'verification': ['ok'], 'evidence': {'status': 'passed', 'fingerprint': 'y'}}]}
        repo = Repo(self, [{'id': 'ok', 'argv': OK, 'required': True}], tasks=legacy, use_git=False)
        repo.write('docs/handoff.json', {'schemaVersion': 1})
        self.assertEqual(repo.run('validate')[0], 0)
        out = repo.run('status')[1]
        self.assertIn('evidence predates this harness version', out)
        self.assertIn('legacy docs/handoff.json', out)
        self.assertIn('`verify F002` again', out)
        self.assertEqual(repo.run('verify', 'F002')[0], 0)
        self.assertEqual(json.loads((repo.root / 'docs/tasks.json').read_text())['schemaVersion'], 2)

    def test_review_is_required_before_done_and_must_match_current_files(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK}])
        repo.run('add', 'reviewed thing', '--accept', 'works', '--check', 'ok', '--review')
        repo.run('start', 'F001')
        repo.write('app.txt', 'v1')
        self.assertEqual(repo.run('verify', 'F001')[0], 0)
        self.assertIn('independent review', repo.run('status')[1])
        repo.commit('work')
        code, out = repo.run('done', 'F001', '--proof', '1=ok')
        self.assertEqual(code, 1, out)
        self.assertIn('independent review', out)
        code, out = repo.run('review', 'F001', '--fail', '--summary', 'edge case missing', '--by', 'subagent')
        self.assertEqual(code, 0, out)
        self.assertEqual(repo.tasks()['F001']['state'], 'active')
        self.assertEqual(repo.run('verify', 'F001')[0], 0)
        self.assertEqual(repo.run('review', 'F001', '--pass', '--summary', 'covers the edge case')[0], 0)
        code, out = repo.run('done', 'F001', '--proof', '1=ok')
        self.assertEqual(code, 0, out)

    def test_changing_a_must_not_change_path_fails_verify(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK}])
        repo.write('public/api.txt', 'stable')
        repo.write('src/feature.txt', 'old')
        repo.commit('base')
        repo.run('add', 'change the feature only', '--accept', 'feature updated', '--check', 'ok',
                 '--keep', 'public/*', '--keep', 'the public response shape')
        repo.run('start', 'F001')
        self.assertIn('must not change: public/*; the public response shape', repo.run('status')[1])
        repo.write('src/feature.txt', 'new')
        repo.write('public/api.txt', 'changed')
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('public/api.txt', out)
        repo.write('public/api.txt', 'stable')
        self.assertEqual(repo.run('verify', 'F001')[0], 0)

    def test_wrapup_needs_a_note_runs_checks_and_flags_debug_leftovers(self):
        repo = Repo(self, [{'id': 'suite', 'argv': OK, 'required': True},
                           {'id': 'smoke', 'argv': [PY, '-c', 'raise SystemExit(1)'], 'wrapup': True}])
        repo.run('add', 'thing', '--accept', 'x', '--check', 'suite')
        repo.run('start', 'F001')
        code, out = repo.run('wrapup')
        self.assertEqual(code, 2, out)
        self.assertIn('--note', out)
        repo.write('src/app.js', 'console.log("debug here")\n')
        code, out = repo.run('wrapup', '--note', 'half done; next: finish the parser')
        self.assertEqual(code, 1, out)
        self.assertIn('smoke failed', out)
        self.assertIn('src/app.js:1', out)
        status = repo.run('status')[1]
        self.assertIn('last wrapup', status)
        self.assertIn('not clean', status)
        self.assertIn('half done; next: finish the parser', status)

    def test_list_hides_finished_tasks_unless_all(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK}], use_git=False)
        repo.run('add', 'first', '--accept', 'x', '--check', 'ok')
        repo.run('add', 'second', '--accept', 'x', '--check', 'ok')
        repo.run('drop', 'F002', '--reason', 'not needed')
        out = repo.run('list')[1]
        self.assertIn('F001', out)
        self.assertNotIn('F002', out)
        self.assertIn('1 dropped hidden', out)
        self.assertIn('F002', repo.run('list', '--all')[1])


def bootstrap(*args):
    result = subprocess.run([PY, str(SKILL / 'scripts/bootstrap.py'), *map(str, args)],
                            capture_output=True, text=True, timeout=120)
    return result.returncode, result.stdout + result.stderr


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='bootstrap-test-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def files(self):
        return {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}

    def test_install_keeps_existing_content_and_reruns_without_changes(self):
        (self.root / 'AGENTS.md').write_text('# Team rules\n\n- Keep the public API stable.\n')
        code, out = bootstrap('install', self.root, '--claude')
        self.assertEqual(code, 0, out)
        agents = (self.root / 'AGENTS.md').read_text()
        self.assertTrue(agents.startswith('# Team rules\n\n- Keep the public API stable.\n'))
        self.assertEqual(agents.count('<!-- harness:start'), 1)
        self.assertEqual((self.root / 'scripts/harness.py').read_text(), RUNNER.read_text())
        self.assertIn('docs/runs/', (self.root / '.gitignore').read_text())
        self.assertEqual((self.root / 'CLAUDE.md').read_text(), '@AGENTS.md\n')
        status = subprocess.run([PY, str(self.root / 'scripts/harness.py'), 'status'], capture_output=True, text=True)
        self.assertEqual(status.returncode, 0, status.stderr)

        tasks = self.root / 'docs/tasks.json'
        tasks.write_text(tasks.read_text().replace('"nextId": 1', '"nextId": 7'))
        before = self.files()
        code, out = bootstrap('install', self.root)
        self.assertEqual(code, 0, out)
        self.assertIn('unchanged: scripts/harness.py', out)
        self.assertEqual(self.files(), before)

        edited = agents.replace('before anything else in a session', 'first in every session')
        self.assertNotEqual(edited, agents)
        (self.root / 'AGENTS.md').write_text(edited)
        code, out = bootstrap('install', self.root)
        self.assertEqual(code, 1, out)
        self.assertIn('conflict: AGENTS.md#harness', out)
        self.assertIn('first in every session', (self.root / 'AGENTS.md').read_text())

    def test_runner_is_updated_only_when_unchanged_since_install(self):
        import hashlib
        old = '# runner from an older skill version\n'
        self.root.joinpath('scripts').mkdir()
        self.root.joinpath('docs').mkdir()
        (self.root / 'scripts/harness.py').write_text(old)
        (self.root / 'docs/install.json').write_text(json.dumps(
            {'schemaVersion': 2, 'skillVersion': '1.9.0', 'files': {'scripts/harness.py': hashlib.sha256(old.encode()).hexdigest()}}))
        code, out = bootstrap('install', self.root)
        self.assertEqual(code, 0, out)
        self.assertIn('updated: scripts/harness.py', out)
        (self.root / 'scripts/harness.py').write_text('# edited by hand\n')
        code, out = bootstrap('install', self.root)
        self.assertEqual(code, 1, out)
        self.assertEqual((self.root / 'scripts/harness.py').read_text(), '# edited by hand\n')

    def test_inspect_reports_commands_ci_and_legacy_files_and_dry_run_writes_nothing(self):
        (self.root / 'package.json').write_text('{"name": "site", "scripts": {"test": "node --test"}}')
        (self.root / '.github/workflows').mkdir(parents=True)
        (self.root / '.github/workflows/ci.yml').write_text('jobs:\n  test:\n    steps:\n      - run: npm test\n')
        (self.root / 'docs').mkdir()
        (self.root / 'docs/handoff.json').write_text('{}')
        code, out = bootstrap('inspect', self.root)
        self.assertEqual(code, 0, out)
        for text in ('script test: node --test', 'ci .github/workflows/ci.yml: npm test',
                     'legacy harness files: docs/handoff.json'):
            self.assertIn(text, out)
        before = self.files()
        code, out = bootstrap('install', self.root, '--dry-run')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.files(), before)


if __name__ == '__main__':
    unittest.main()
