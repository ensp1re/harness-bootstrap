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
        self.env = dict(os.environ, npm_config_cache=str(self.root.parent / 'harness-npm-cache'))
        (self.root / 'scripts').mkdir()
        shutil.copy(RUNNER, self.root / 'scripts/harness.py')
        self.write('docs/config.json', {'schemaVersion': 2, 'checks': checks, 'delivery': {'mode': 'local'}})
        if tasks:  # the single queue file of earlier versions
            self.write('docs/tasks.json', tasks)
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
                                capture_output=True, text=True, timeout=120, env=getattr(self, 'env', None))
        return result.returncode, result.stdout + result.stderr

    def branch(self):
        return subprocess.run(['git', 'branch', '--show-current'], cwd=self.root, capture_output=True,
                              text=True).stdout.strip()

    def task_files(self):
        shared = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=self.root, capture_output=True, text=True).stdout.strip()
        folders = [self.root / 'docs/tasks'] + ([self.root / shared / 'harness-queue'] if shared else [])
        return [path for folder in folders for path in sorted(folder.glob('*.json'))]

    def tasks(self):
        legacy = self.root / 'docs/tasks.json'
        found = json.loads(legacy.read_text())['tasks'] if legacy.exists() else \
            [json.loads(path.read_text()) for path in self.task_files()]
        return {task['id']: task for task in found}

    def edit_task(self, task_id, change):
        path = next(path for path in self.task_files() if path.stem == task_id)
        task = json.loads(path.read_text())
        change(task)
        path.write_text(json.dumps(task))


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
        code, out = repo.run('done', 'F001', '--proof', '1=feature: check')
        self.assertEqual(code, 1, out)
        self.assertIn('feature.txt', out)
        repo.commit('feature')
        code, out = repo.run('done', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('--proof', out)
        code, out = repo.run('done', 'F001', '--proof', '1=feature: check')
        self.assertEqual(code, 0, out)
        task = repo.tasks()['F001']
        self.assertEqual(task['state'], 'passing')
        self.assertTrue(task['evidence']['commit'])
        self.assertEqual(task['evidence']['proof'], {'1': 'feature: check'})

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
        self.assertEqual(repo.run('note', 'F001', 'the lock died with the process')[0], 0)
        repo.write('docs/config.json', {'schemaVersion': 2, 'checks': [{'id': 'slow', 'argv': OK}], 'delivery': {'mode': 'local'}})
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
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 1)
        self.assertIn('no check covers this change', out)
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
        self.assertFalse((repo.root / 'docs/tasks.json').exists(), 'the first write moves tasks to one file each')
        self.assertEqual({key: task['state'] for key, task in repo.tasks().items()}, {'F001': 'passing', 'F002': 'verified'})

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
        code, out = repo.run('review', 'F001', '--proof', '1=ok', '--fail', '--summary', 'edge case missing', '--by', 'subagent')
        self.assertEqual(code, 0, out)
        self.assertEqual(repo.tasks()['F001']['state'], 'active')
        self.assertEqual(repo.run('verify', 'F001')[0], 0)
        self.assertEqual(repo.run('review', 'F001', '--proof', '1=ok', '--pass', '--summary', 'covers the edge case')[0], 0)
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

    def test_small_task_needs_no_acceptance_proof_or_own_check(self):
        repo = Repo(self, [{'id': 'suite', 'argv': OK, 'required': True}])
        self.assertEqual(repo.run('add', 'Fix a typo in the README', '--type', 'docs')[0], 0)
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        repo.write('README.md', 'fixed\n')
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 0, out)
        self.assertIn('next: commit, then `done F001`', out)
        self.assertEqual(list((repo.root / 'docs/runs').glob('*.log')), [], 'a passed check keeps no log')
        repo.commit('typo')
        self.assertEqual(repo.run('done', 'F001')[0], 0)
        events = [json.loads(line) for line in (repo.root / 'docs/runs/events.jsonl').read_text().splitlines()]
        self.assertEqual([event['command'] for event in events], ['add', 'start', 'verify', 'hook', 'done'])

    def test_checks_with_paths_run_only_for_matching_changes_and_are_not_rerun(self):
        count = [PY, '-c', "open('docs/runs/count.txt', 'a').write('x')"]
        repo = Repo(self, [{'id': 'unit', 'argv': count, 'required': True, 'paths': ['src/*']},
                           {'id': 'docs', 'argv': OK, 'required': True}, {'id': 'smoke', 'argv': OK, 'wrapup': True}])
        runs = lambda: len((repo.root / 'docs/runs/count.txt').read_text()) if (repo.root / 'docs/runs/count.txt').exists() else 0
        repo.run('add', 'Reword the README', '--type', 'docs')
        repo.run('start', 'F001')
        repo.write('README.md', 'reworded\n')
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 0, out)
        self.assertIn('not run, no changed file matches their paths: unit', out)
        self.assertEqual(runs(), 0)
        repo.commit('docs')
        self.assertEqual(repo.run('done', 'F001')[0], 0)
        repo.commit('queue')
        repo.run('add', 'Change the code')
        repo.run('start', 'F002')
        repo.write('src/app.py', 'v1\n')
        self.assertEqual(repo.run('verify', 'F002')[0], 0)
        self.assertEqual(runs(), 1)
        repo.write('README.md', 'reworded again\n')
        code, out = repo.run('verify', 'F002')
        self.assertEqual(code, 0, out)
        self.assertIn('unit: passed exit 0 (reused', out)
        self.assertEqual(runs(), 1, 'a docs edit must not rerun a check whose files did not change')
        repo.write('src/app.py', 'v2\n')
        self.assertEqual(repo.run('verify', 'F002')[0], 0)
        self.assertEqual(runs(), 2)
        self.assertEqual(repo.run('wrapup', '--note', 'verified; next: commit')[0], 0)
        self.assertEqual(runs(), 2, 'wrapup runs only the checks marked wrapup')

    def test_review_is_required_by_changed_review_paths_not_by_the_task(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        config = json.loads((repo.root / 'docs/config.json').read_text())
        config['review'] = {'paths': ['src/billing/*']}
        repo.write('docs/config.json', config)
        repo.commit('review paths')
        repo.run('add', 'Change a label')
        repo.run('start', 'F001')
        repo.write('src/ui/label.py', 'v1\n')
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 0, out)
        self.assertIn('next: commit, then `done F001`', out)
        repo.commit('label')
        self.assertEqual(repo.run('done', 'F001')[0], 0)
        repo.commit('queue')
        repo.run('add', 'Round totals to cents')
        repo.run('start', 'F002')
        repo.write('src/billing/total.py', 'v1\n')
        code, out = repo.run('verify', 'F002')
        self.assertEqual(code, 0, out)
        self.assertIn('next: get an independent review (src/billing/total.py is on a review path)', out)
        repo.commit('totals')
        code, out = repo.run('done', 'F002')
        self.assertEqual(code, 1, out)
        self.assertIn('independent review', out)
        self.assertEqual(repo.run('review', 'F002', '--pass', '--summary', 'rounding is right')[0], 0)
        self.assertEqual(repo.run('done', 'F002')[0], 0)

    def test_review_stays_valid_until_a_reviewed_file_changes(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        config = json.loads((repo.root / 'docs/config.json').read_text())
        config['review'] = {'paths': ['src/billing/*']}
        repo.write('docs/config.json', config)
        repo.commit('review paths')
        repo.run('add', 'Round totals to cents')
        repo.run('start', 'F001')
        repo.write('src/billing/total.py', 'v1\n')
        repo.write('src/ui/label.py', 'v1\n')
        self.assertEqual(repo.run('verify', 'F001')[0], 0)
        self.assertEqual(repo.run('review', 'F001', '--pass', '--summary', 'rounding is right')[0], 0)
        repo.write('README.md', 'a typo fixed after the review\n')
        repo.write('src/ui/label.py', 'v2\n')
        repo.commit('work')
        code, out = repo.run('done', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('files changed', out)
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 0, out)
        self.assertIn('next: commit, then `done F001`', out)
        repo.write('src/billing/total.py', 'v2\n')
        repo.commit('billing changed after the review')
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 0, out)
        self.assertIn('independent review', out)
        self.assertIn('stale', repo.run('status')[1])
        self.assertEqual(repo.run('done', 'F001')[0], 1)

    def test_proof_is_given_after_the_checks_pass_and_may_be_manual_outside_review_paths(self):
        count = [PY, '-c', "open('docs/runs/count.txt', 'a').write('x')"]
        repo = Repo(self, [{'id': 'unit', 'argv': count, 'required': True}])
        config = json.loads((repo.root / 'docs/config.json').read_text())
        config['review'] = {'paths': ['src/billing/*']}
        repo.write('docs/config.json', config)
        repo.commit('review paths')
        repo.run('add', 'Add a helper', '--accept', 'short text is unchanged')
        repo.run('start', 'F001')
        repo.write('src/helper.py', 'v1\n')
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 0, out)
        self.assertIn('next: commit, then `done F001 --proof "1=CHECK: what it showed"`', out)
        code, out = repo.run('verify', 'F001', '--proof', "1=manual: ran helper('abc') and it printed abc")
        self.assertEqual(code, 0, out)
        self.assertIn('proof recorded', out)
        self.assertEqual(len((repo.root / 'docs/runs/count.txt').read_text()), 1, 'recording proof must not rerun checks')
        repo.commit('helper')
        self.assertEqual(repo.run('done', 'F001')[0], 0)
        repo.commit('queue')
        repo.run('add', 'Round totals', '--accept', 'half a cent rounds up')
        repo.run('start', 'F002')
        repo.write('src/billing/total.py', 'v1\n')
        self.assertEqual(repo.run('verify', 'F002')[0], 0)
        code, out = repo.run('verify', 'F002', '--proof', '1=manual: looked right')
        self.assertEqual(code, 2, out)
        self.assertIn('proof must name an executed passing check', out)
        self.assertEqual(repo.run('verify', 'F002', '--proof', '1=unit: test_half_cent_rounds_up')[0], 0)

    def test_check_since_skips_checks_whose_paths_did_not_change_and_verify_flags_a_large_task(self):
        count = [PY, '-c', "open('docs/runs/count.txt', 'a').write('x')"]
        repo = Repo(self, [{'id': 'unit', 'argv': count, 'required': True, 'paths': ['src/*']},
                           {'id': 'docs', 'argv': OK, 'required': True}])
        config = json.loads((repo.root / 'docs/config.json').read_text())
        config['taskLines'] = 5
        repo.write('docs/config.json', config)
        repo.write('README.md', 'one\n')
        repo.commit('docs only')
        code, out = repo.run('check', '--since', 'HEAD~1')
        self.assertEqual(code, 0, out)
        self.assertIn('not run, no changed file matches their paths: unit', out)
        self.assertFalse((repo.root / 'docs/runs/count.txt').exists())
        self.assertEqual(repo.run('check', '--since', 'no-such-ref')[0], 0)
        self.assertTrue((repo.root / 'docs/runs/count.txt').exists(), 'an unknown ref runs every required check')
        repo.run('add', 'A big change')
        repo.run('start', 'F001')
        repo.write('src/big.py', 'line\n' * 12)
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 0, out)
        self.assertIn('this task changed 12 lines, over the taskLines limit of 5', out)

    def test_show_finds_referenced_rows_in_any_doc_and_wrapup_leaves_no_shared_state(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        repo.write('docs/billing.md', '| ID | Requirement |\n|---|---|\n| R-7 | Totals round half up to cents. |\n')
        repo.commit('area doc')
        repo.run('add', 'Round totals', '--ref', 'R-7')
        self.assertIn('Totals round half up to cents.', repo.run('show', 'F001')[1])
        before = sorted(path.name for path in (repo.root / 'docs/tasks').iterdir())
        self.assertEqual(repo.run('wrapup', '--note', 'queued one task')[0], 0)
        self.assertIn('queued one task', repo.run('status')[1])
        self.assertEqual(sorted(path.name for path in (repo.root / 'docs/tasks').iterdir()), before)
        self.assertFalse((repo.root / 'docs/tasks.json').exists())

    def test_three_failed_reviews_send_the_agent_to_the_user(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        repo.run('add', 'Risky thing', '--review')
        repo.run('start', 'F001')
        repo.write('app.py', 'v1\n')
        for attempt in range(3):
            self.assertEqual(repo.run('verify', 'F001')[0], 0)
            code, out = repo.run('review', 'F001', '--fail', '--summary', f'finding {attempt}')
            self.assertEqual('stop and ask the user' in out, attempt == 2, out)

    def test_sigterm_stops_the_check_a_wrapup_is_running(self):
        slow = [PY, '-c', "import os, time; open('docs/runs/pid.txt', 'w').write(str(os.getpid())); time.sleep(30)"]
        repo = Repo(self, [{'id': 'slow', 'argv': slow, 'wrapup': True}], use_git=False)
        process = subprocess.Popen([PY, str(repo.root / 'scripts/harness.py'), 'wrapup', '--note', 'x'], cwd=repo.root,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        marker, deadline = repo.root / 'docs/runs/pid.txt', time.time() + 20
        while not (marker.exists() and marker.read_text()):
            self.assertLess(time.time(), deadline)
            time.sleep(0.1)
        check = int(marker.read_text())
        self.addCleanup(lambda: subprocess.run(['kill', '-9', str(check)], capture_output=True))
        process.terminate()
        process.wait(timeout=10)
        deadline = time.time() + 5
        while subprocess.run(['kill', '-0', str(check)], capture_output=True).returncode == 0:
            self.assertLess(time.time(), deadline, 'the check outlived the harness')
            time.sleep(0.1)

    def test_show_prints_referenced_project_rows_and_status_states_approval(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        repo.write('docs/PROJECT.md', '| ID | Requirement |\n|---|---|\n| R-1 | When a total has half a cent, it rounds up. |\n'
                                      '| R-12 | Another row. |\n')
        repo.run('add', 'Round totals', '--ref', 'R-1')
        out = repo.run('show', 'F001')[1]
        self.assertIn('When a total has half a cent, it rounds up.', out)
        self.assertNotIn('Another row', out)
        self.assertIn('ask before commit and push', repo.run('status')[1])
        config = json.loads((repo.root / 'docs/config.json').read_text())
        config['delivery']['autoPublish'] = True
        repo.write('docs/config.json', config)
        self.assertIn('commit and push need no approval', repo.run('status')[1])


FAKE_GH = r'''#!/usr/bin/env python3
"""A stand-in for the GitHub CLI: pull requests live in a JSON file, merges move refs in the bare origin."""
import json, os, subprocess, sys

STATE = os.environ['FAKE_GH_STATE']
state = json.load(open(STATE)) if os.path.exists(STATE) else {'prs': []}
args = sys.argv[1:]


def save():
    with open(STATE, 'w') as handle:
        json.dump(state, handle)


def origin_git(*command):
    origin = subprocess.run(['git', 'remote', 'get-url', 'origin'], capture_output=True, text=True).stdout.strip()
    return subprocess.run(['git', '--git-dir', origin, *command], capture_output=True, text=True)


def find(key):
    return next((pr for pr in reversed(state['prs']) if key in (str(pr['number']), pr['head'])), None)


if args[:2] == ['pr', 'view']:
    pr = find(args[2])
    if pr is None:
        sys.exit('no pull requests found for branch ' + args[2])
    head = origin_git('rev-parse', '--verify', '--quiet', 'refs/heads/' + pr['head']).stdout.strip()
    print(json.dumps({'number': pr['number'], 'url': pr['url'], 'state': pr['state'], 'headRefOid': head or pr.get('mergedHead')}))
elif args[:2] == ['pr', 'create']:
    options = dict(zip(args[2::2], args[3::2]))
    pr = {'number': len(state['prs']) + 1, 'head': options['--head'], 'base': options['--base'],
          'title': options['--title'], 'state': 'OPEN'}
    pr['url'] = 'https://github.test/pull/%d' % pr['number']
    state['prs'].append(pr)
    save()
    print(pr['url'])
elif args[:2] == ['pr', 'checks']:
    mode = os.environ.get('FAKE_GH_CHECKS', 'pass')
    if mode == 'none':
        sys.exit("no checks reported on the 'branch' branch")
    if mode == 'error':
        sys.exit('HTTP 401: Bad credentials (https://api.github.com/graphql)')
    print(json.dumps([{'name': 'ci', 'bucket': mode, 'link': 'https://ci.test/run/1'}]))
    sys.exit({'pass': 0, 'fail': 1, 'pending': 8}.get(mode, 0))
elif args[:2] == ['pr', 'merge']:
    pr = find(args[2])
    head = origin_git('rev-parse', 'refs/heads/' + pr['head']).stdout.strip()
    if head != args[args.index('--match-head-commit') + 1]:
        sys.exit('head commit does not match')
    if os.environ.get('FAKE_GH_MERGE') == 'queue':  # a merge queue accepts the request and merges later
        sys.exit(0)
    origin_git('update-ref', 'refs/heads/' + pr['base'], head)
    origin_git('update-ref', '-d', 'refs/heads/' + pr['head'])
    pr['state'] = 'MERGED'
    pr['mergedHead'] = head
    save()
    if os.environ.get('FAKE_GH_MERGE') == 'fail-after-merge':  # gh merged, then its local branch cleanup failed
        sys.exit('failed to delete local branch')
else:
    sys.exit('fake gh does not support: ' + ' '.join(args))
'''


class RemoteRepo(Repo):
    """A Repo with a bare local `origin` and the fake GitHub CLI first on PATH."""

    def __init__(self, test, checks, empty_remote=False, delivery=None):
        super().__init__(test, checks)
        delivery = delivery or {'mode': 'pr', 'autoMerge': True}
        delivery.setdefault('autoMerge', True)
        if delivery:
            config = json.loads((self.root / 'docs/config.json').read_text())
            config['delivery'] = delivery
            self.write('docs/config.json', config)
            self.commit('delivery settings')
        directory = tempfile.TemporaryDirectory(prefix='harness-remote-')
        test.addCleanup(directory.cleanup)
        home = Path(directory.name)
        self.origin = home / 'origin.git'
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(self.origin)], check=True)
        self.git('remote', 'add', 'origin', str(self.origin))
        if not empty_remote:
            self.git('push', '-q', 'origin', 'main')
        tools = home / 'bin'
        tools.mkdir()
        (tools / 'gh').write_text(FAKE_GH)
        (tools / 'gh').chmod(0o755)
        self.env = dict(os.environ, PATH=f'{tools}{os.pathsep}{os.environ["PATH"]}', FAKE_GH_STATE=str(home / 'gh.json'),
                        HARNESS_POLL_SECONDS='0.05', HARNESS_CHECKS_REGISTER_SECONDS='0',
                        GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.com',
                        GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.com')

    def origin_file(self, path):
        shown = subprocess.run(['git', '--git-dir', str(self.origin), 'show', f'main:{path}'],
                               capture_output=True, text=True)
        return shown.stdout if shown.returncode == 0 else None

    def pull_requests(self):
        path = Path(self.env['FAKE_GH_STATE'])
        return json.loads(path.read_text())['prs'] if path.exists() else []


class HookTest(unittest.TestCase):
    def commit(self, repo, message):
        subprocess.run(['git', 'add', '-A'], cwd=repo.root, check=True)
        return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-q', '-m', message],
                              cwd=repo.root, capture_output=True, text=True)

    def test_pre_commit_hook_blocks_a_commit_while_a_precommit_check_fails(self):
        clean = [PY, '-c', "import pathlib, sys; sys.exit(1 if pathlib.Path('bad.txt').exists() else 0)"]
        repo = Repo(self, [{'id': 'lint', 'argv': clean, 'precommit': True}, {'id': 'ok', 'argv': OK}])
        repo.run('add', 'Something', '--accept', 'x', '--check', 'ok')
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        repo.write('bad.txt', 'a lint error\n')
        blocked = self.commit(repo, 'with a lint error')
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn('pre-commit: lint failed', blocked.stderr)
        (repo.root / 'bad.txt').unlink()
        repo.write('good.txt', 'fine\n')
        committed = self.commit(repo, 'clean')
        self.assertEqual(committed.returncode, 0, committed.stderr)

    def test_husky_projects_get_the_hook_lines_in_their_husky_files(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK}])
        repo.write('.husky/pre-commit', 'npx lint-staged\n')
        repo.commit('husky')
        repo.git('config', 'core.hooksPath', '.husky/_')
        repo.run('add', 'Something', '--accept', 'x', '--check', 'ok')
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 0, out)
        self.assertEqual(repo.run('hook', 'install')[0], 0)
        self.assertEqual((repo.root / '.husky/pre-commit').read_text(),
                         'npx lint-staged\npython3 scripts/harness.py hook pre-commit\n')
        self.assertEqual((repo.root / '.husky/pre-push').read_text(), '#!/bin/sh\npython3 scripts/harness.py hook pre-push\n')
        self.assertFalse((repo.root / '.git/hooks/pre-push').exists())


class DeliveryTest(unittest.TestCase):
    def finish_work(self, repo, task='F001'):
        (repo.root / 'feature.txt').write_text('done\n')
        self.assertEqual(repo.run('verify', task)[0], 0)
        repo.commit('add the feature')

    def test_task_is_built_on_a_branch_and_merged_through_a_pull_request(self):
        repo = RemoteRepo(self, [{'id': 'feature', 'argv': FEATURE}])
        repo.run('add', 'Feature file exists', '--type', 'feat', '--accept', 'feature.txt is present', '--check', 'feature')
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 0, out)
        self.assertEqual(repo.branch(), 'feat/f001-feature-file-exists')
        self.assertIn('harness.py hook pre-push', (repo.root / '.git/hooks/pre-push').read_text())
        self.finish_work(repo)
        code, out = repo.run('done', 'F001', '--proof', '1=feature: check')
        self.assertEqual(code, 0, out)
        self.assertIn('https://github.test/pull/1', out)
        self.assertEqual(repo.branch(), 'main')
        self.assertEqual(repo.origin_file('feature.txt'), 'done\n')
        self.assertEqual(json.loads(repo.origin_file('docs/tasks/F001.json'))['state'], 'passing')
        self.assertEqual([pr['title'] for pr in repo.pull_requests()], ['feat: Feature file exists (F001)'])
        self.assertIn('the queue is empty', repo.run('status')[1])

    def test_failed_checks_return_the_task_to_active_without_merging(self):
        repo = RemoteRepo(self, [{'id': 'feature', 'argv': FEATURE}])
        repo.env['FAKE_GH_CHECKS'] = 'fail'
        repo.run('add', 'Feature file exists', '--accept', 'feature.txt is present', '--check', 'feature')
        repo.run('start', 'F001')
        self.finish_work(repo)
        code, out = repo.run('done', 'F001', '--proof', '1=feature: check')
        self.assertEqual(code, 1, out)
        self.assertIn('checks failed: ci', out)
        self.assertEqual(repo.tasks()['F001']['state'], 'active')
        self.assertIsNone(repo.origin_file('feature.txt'))

    def test_a_pending_pull_request_does_not_block_a_task_that_does_not_depend_on_it(self):
        repo = RemoteRepo(self, [{'id': 'feature', 'argv': FEATURE}, {'id': 'ok', 'argv': OK}],
                          delivery={'mode': 'pr', 'checksWaitSeconds': 0.05})
        repo.env['FAKE_GH_CHECKS'] = 'pending'
        repo.run('add', 'Feature file exists', '--accept', 'feature.txt is present', '--check', 'feature')
        repo.run('add', 'Second thing', '--accept', 'x', '--check', 'ok')
        repo.run('add', 'Third thing', '--accept', 'x', '--check', 'ok', '--after', 'F001')
        repo.run('start', 'F001')
        self.finish_work(repo)
        code, out = repo.run('done', 'F001', '--proof', '1=feature: check')
        self.assertEqual(code, 1, out)
        self.assertIn('still running', out)
        self.assertIn('waiting for merge: F001', repo.run('status')[1])
        added = subprocess.run(['git', 'diff', '--name-only', 'origin/main...HEAD', '--', 'docs/tasks'], cwd=repo.root,
                               capture_output=True, text=True).stdout.split()
        self.assertEqual(added, ['docs/tasks/F001.json'], 'a branch carries only the record of its own task')
        repo.write('feature.txt', 'changed after done\n')
        repo.commit('late change')
        code, out = repo.run('done', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('fresh verification', out)
        repo.git('reset', '-q', '--hard', 'HEAD~1')
        code, out = repo.run('start', 'F003')
        self.assertEqual(code, 1, out)
        self.assertIn('waits on F001', out)
        code, out = repo.run('start', 'F002')
        self.assertEqual(code, 0, out)
        self.assertEqual(repo.branch(), 'feat/f002-second-thing')
        self.assertNotIn('F001', repo.tasks(), 'the pending task stays on its own branch')
        subprocess.run(['git', 'switch', '-q', 'feat/f001-feature-file-exists'], cwd=repo.root, check=True)
        repo.env['FAKE_GH_CHECKS'] = 'pass'
        code, out = repo.run('done', 'F001')
        self.assertEqual(code, 0, out)
        self.assertEqual(repo.branch(), 'main')

    def test_a_clone_on_the_base_branch_is_sent_to_the_task_branch(self):
        repo = RemoteRepo(self, [{'id': 'feature', 'argv': FEATURE}], delivery={'mode': 'pr', 'checksWaitSeconds': 0.05})
        repo.env['FAKE_GH_CHECKS'] = 'pending'
        repo.run('add', 'Feature file exists', '--accept', 'feature.txt is present', '--check', 'feature')
        repo.run('start', 'F001')
        self.finish_work(repo)
        repo.run('done', 'F001', '--proof', '1=feature: check')
        subprocess.run(['git', 'switch', '-q', 'main'], cwd=repo.root, check=True)
        self.assertIn('next: `git switch feat/f001-feature-file-exists`', repo.run('status')[1])

    def test_two_worktrees_work_in_parallel_and_both_merge(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}], delivery={'mode': 'pr', 'autoMerge': False})
        other = Repo.__new__(Repo)
        other.root, other.env = repo.root.parent / (repo.root.name + '-second'), repo.env
        self.addCleanup(shutil.rmtree, other.root, ignore_errors=True)
        repo.git('worktree', 'add', '-q', '--detach', str(other.root), 'main')
        repo.run('add', 'First thing')
        self.assertIn('added F002', other.run('add', 'Second thing')[1], 'every worktree sees one queue')
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        code, out = other.run('start', 'F002')
        self.assertEqual(code, 0, out)
        self.assertIn('in progress in other worktrees: feat/f002-second-thing', repo.run('status')[1])
        for tree, name in ((repo, 'F001'), (other, 'F002')):
            tree.write(f'{name}.txt', 'work\n')
            self.assertEqual(tree.run('verify', name)[0], 0)
            subprocess.run(['git', 'add', '-A'], cwd=tree.root, check=True)
            subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-q', '-m', name],
                           cwd=tree.root, check=True)
            code, out = tree.run('done', name)
            self.assertIn('waiting for the owner to merge', out)
            tree.run('wrapup', '--note', 'pushed; waiting for the merge')
        merged = repo.root.parent / (repo.root.name + '-merge')
        self.addCleanup(shutil.rmtree, merged, ignore_errors=True)
        subprocess.run(['git', 'clone', '-q', str(repo.origin), str(merged)], check=True)
        for branch in ('feat/f001-first-thing', 'feat/f002-second-thing'):
            result = subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', 'merge', '-q', '--no-edit',
                                     f'origin/{branch}'], cwd=merged, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        states = {path.stem: json.loads(path.read_text())['state'] for path in (merged / 'docs/tasks').glob('*.json')}
        self.assertEqual(states, {'F001': 'passing', 'F002': 'passing'})

    def test_merge_counts_only_when_github_reports_it_merged(self):
        repo = RemoteRepo(self, [{'id': 'feature', 'argv': FEATURE}])
        repo.run('add', 'Feature file exists', '--accept', 'feature.txt is present', '--check', 'feature')
        repo.run('start', 'F001')
        self.finish_work(repo)
        repo.env['FAKE_GH_CHECKS'] = 'error'
        code, out = repo.run('done', 'F001', '--proof', '1=feature: check')
        self.assertEqual(code, 1, out)
        self.assertIn('could not read the checks: HTTP 401', out)
        repo.env.update(FAKE_GH_CHECKS='pass', FAKE_GH_MERGE='queue')
        code, out = repo.run('done', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('F001 is not merged yet', out)
        self.assertIsNone(repo.origin_file('feature.txt'))
        gh_state = Path(repo.env['FAKE_GH_STATE'])
        gh_state.write_text(gh_state.read_text().replace('"OPEN"', '"CLOSED"'))
        code, out = repo.run('done', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('closed without merging', out)
        self.assertEqual(repo.run('reopen', 'F001', '--reason', 'the user wants it after all')[0], 0)
        self.assertEqual(repo.run('verify', 'F001')[0], 0)
        repo.env['FAKE_GH_MERGE'] = 'fail-after-merge'
        code, out = repo.run('done', 'F001', '--proof', '1=feature: check')
        self.assertEqual(code, 0, out)
        self.assertIn('merged into main: https://github.test/pull/2', out)
        self.assertEqual(repo.origin_file('feature.txt'), 'done\n')
        self.assertEqual(repo.branch(), 'main')

    def test_an_empty_remote_gets_one_direct_push_of_the_harness_then_pull_requests(self):
        repo = RemoteRepo(self, [{'id': 'feature', 'argv': FEATURE}], empty_remote=True)
        repo.run('add', 'Walking skeleton', '--accept', 'feature.txt is present', '--check', 'feature')
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('`HARNESS_BASE_PUSH=1 git push -u origin main`', out)
        repo.commit('chore: add agent harness')
        subprocess.run(['git', 'push', '-q', '-u', 'origin', 'main'], cwd=repo.root, check=True)
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        self.assertEqual(repo.branch(), 'feat/f001-walking-skeleton')

    def test_direct_push_to_the_base_branch_is_blocked(self):
        repo = RemoteRepo(self, [{'id': 'feature', 'argv': FEATURE}])
        repo.run('add', 'Feature file exists', '--accept', 'feature.txt is present', '--check', 'feature')
        repo.run('start', 'F001')
        subprocess.run(['git', 'switch', '-q', 'main'], cwd=repo.root, check=True)
        repo.write('hotfix.txt', 'quick fix\n')
        repo.commit('hotfix straight to main')
        pushed = subprocess.run(['git', 'push', 'origin', 'main'], cwd=repo.root, capture_output=True, text=True)
        self.assertNotEqual(pushed.returncode, 0)
        self.assertIn('only through pull requests', pushed.stderr)
        self.assertIsNone(repo.origin_file('hotfix.txt'))
        subprocess.run(['git', 'push', '-q', 'origin', 'main'], cwd=repo.root, check=True,
                       env=dict(os.environ, HARNESS_BASE_PUSH='1'))  # the documented override for the one direct push
        self.assertEqual(repo.origin_file('hotfix.txt'), 'quick fix\n')

    def test_start_refuses_until_the_harness_is_merged_into_the_base_branch(self):
        repo = RemoteRepo(self, [{'id': 'feature', 'argv': FEATURE}])
        empty = subprocess.run(['git', 'commit-tree', '4b825dc642cb6eb9a060e54bf8d69288fbee4904', '-m', 'before the harness'],
                               cwd=repo.root, capture_output=True, text=True, env=repo.env, check=True).stdout.strip()
        subprocess.run(['git', 'push', '-q', '-f', 'origin', f'{empty}:refs/heads/main'], cwd=repo.root, check=True)
        repo.run('add', 'Feature file exists', '--accept', 'feature.txt is present', '--check', 'feature')
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('origin/main has no docs/config.json', out)
        self.assertEqual(repo.branch(), 'main')
        self.assertTrue((repo.root / 'scripts/harness.py').exists())

    def test_verify_refuses_outside_the_task_branch(self):
        repo = RemoteRepo(self, [{'id': 'feature', 'argv': FEATURE}])
        repo.run('add', 'Feature file exists', '--accept', 'feature.txt is present', '--check', 'feature')
        repo.run('start', 'F001')
        subprocess.run(['git', 'switch', '-q', 'main'], cwd=repo.root, check=True)
        code, out = repo.run('verify', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('git switch feat/f001-feature-file-exists', out)


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

        (self.root / 'docs/tasks').mkdir()
        (self.root / 'docs/tasks/F007.json').write_text('{"id": "F007", "behavior": "kept", "state": "not_started"}')
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

    def test_install_copies_coding_skills_and_links_them_for_claude(self):
        own = self.root / '.claude/skills/writing-code'
        own.mkdir(parents=True)
        (own / 'SKILL.md').write_text('own skill\n')
        code, out = bootstrap('install', self.root, '--claude')
        self.assertEqual(code, 1, out)
        self.assertIn('conflict: .claude/skills/writing-code', out)
        self.assertEqual((own / 'SKILL.md').read_text(), 'own skill\n')
        self.assertIn('.agents/skills/', (self.root / 'AGENTS.md').read_text())
        skills = sorted((SKILL / 'assets/skills').glob('*/SKILL.md'))
        self.assertGreater(len(skills), 1)
        for source in skills:
            name = source.parent.name
            self.assertEqual((self.root / '.agents/skills' / name / 'SKILL.md').read_text(), source.read_text())
            if name != 'writing-code':
                link = self.root / '.claude/skills' / name
                self.assertTrue(link.is_symlink(), name)
                self.assertEqual((link / 'SKILL.md').read_text(), source.read_text())

        shutil.rmtree(own)
        code, out = bootstrap('install', self.root, '--claude')
        self.assertEqual(code, 0, out)
        self.assertIn('created: .claude/skills/writing-code', out)
        self.assertIn('unchanged: .claude/skills/debugging', out)

        installed = self.root / '.agents/skills/debugging/SKILL.md'
        installed.write_text('edited by the team\n')
        code, out = bootstrap('install', self.root, '--claude')
        self.assertEqual(code, 1, out)
        self.assertIn('conflict: .agents/skills/debugging/SKILL.md', out)
        self.assertEqual(installed.read_text(), 'edited by the team\n')

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
