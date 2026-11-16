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


def track(repo, number, behavior):
    """A queued task committed in the working tree, as bootstrap or another clone leaves it on the base branch."""
    repo.write(f'docs/tasks/F{number:03d}.json', {
        'id': f'F{number:03d}', 'type': 'feat', 'behavior': behavior, 'acceptance': ['works'], 'dependsOn': [],
        'state': 'not_started', 'verification': ['ok'], 'refs': [], 'keep': [], 'review': False, 'notes': [],
        'blockedReason': None, 'evidence': None})
    repo.commit(behavior)


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
            before = (root / 'docs/tasks/F001.json').read_bytes()
            (root / 'AGENTS.md').write_text('# User rule\n\n' + (root / 'AGENTS.md').read_text())
            (root / 'docs/PROJECT.md').write_text('# Example\n\n| D-1 | Keep Python |\n')
            for _ in range(2):
                self.assertEqual(bootstrap('install', root)[0], 0)
                self.assertEqual((root / 'docs/tasks/F001.json').read_bytes(), before)
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
        path = repo.root / 'docs/tasks/F001.json'
        task = json.loads(path.read_text())
        task['state'] = 'passing'
        payload = {key: task.get(key) for key in ('behavior', 'acceptance', 'verification')}
        task['evidence'] = {'version': 2, 'status': 'passed', 'taskHash': hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16], 'proof': {'1': 'legacy prose'}}
        repo.write('docs/tasks/F001.json', task)
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
                repo.edit_task('F001', lambda task: task.update(baseCommit='nonexistent-commit'))
                repo.write('src/a.py', 'changed')
                self.assertNotEqual(repo.run('verify', 'F001')[0], 0)

    def test_fixed_temporary_files_are_never_overwritten(self):
        for install in (False, True):
            with self.subTest(install=install):
                repo = Repo(self, [{'id': 'ok', 'argv': OK}])
                repo.write('user.txt', 'keep me')
                name = 'scripts/harness.py.tmp' if install else 'docs/tasks/F001.json.tmp'
                (repo.root / 'docs/tasks').mkdir(exist_ok=True)
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
        before = (repo.root / 'docs/tasks/F001.json').read_bytes()
        branch = repo.branch()
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo.root, capture_output=True, text=True).stdout.strip()
        merged = subprocess.run(['gh', 'pr', 'merge', '1', '--match-head-commit', head], cwd=repo.root,
                                env=repo.env, capture_output=True, text=True)
        self.assertEqual(merged.returncode, 0, merged.stderr)
        code, out = repo.run('done', 'F001')
        self.assertNotEqual(code, 0, out)
        self.assertEqual(repo.branch(), branch)
        self.assertEqual((repo.root / 'docs/tasks/F001.json').read_bytes(), before)

    def test_start_preserves_tasks_added_on_remote_base(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}])
        track(repo, 1, 'first')
        repo.git('push', 'origin', 'main')
        base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo.root, capture_output=True, text=True).stdout.strip()
        track(repo, 2, 'new remote task')
        repo.git('push', 'origin', 'main')
        repo.git('reset', '--hard', base)
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 0, out)
        self.assertEqual({key: task['behavior'] for key, task in repo.tasks().items()}, {'F001': 'first', 'F002': 'new remote task'})

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
        track(repo, 1, 'first')
        repo.git('push', 'origin', 'main')
        common = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo.root, capture_output=True, text=True).stdout.strip()
        track(repo, 2, 'local task')
        repo.git('switch', '-c', 'remote-update', common)
        track(repo, 2, 'remote task')
        repo.git('push', 'origin', 'HEAD:main'); repo.git('switch', 'main')
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 0, out)
        self.assertIn('this task is now F003', out)
        self.assertEqual({key: task['behavior'] for key, task in repo.tasks().items()},
                         {'F001': 'first', 'F002': 'remote task', 'F003': 'local task'})

    def test_queued_tasks_stay_out_of_the_working_tree_and_move_when_the_base_takes_their_number(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}])
        self.assertIn('added F001', repo.run('add', 'mine')[1])
        status = subprocess.run(['git', 'status', '--porcelain'], cwd=repo.root, capture_output=True, text=True).stdout
        self.assertEqual(status, '', 'a queued task is not a file that `git add -A` or a cleanup can take')
        track(repo, 1, 'theirs, pulled from the base branch')
        code, out = repo.run('list')
        self.assertEqual(code, 0, out)
        self.assertIn('this task is now F002', out)
        self.assertEqual({key: task['behavior'] for key, task in repo.tasks().items()},
                         {'F001': 'theirs, pulled from the base branch', 'F002': 'mine'})

    def test_the_single_queue_file_becomes_one_file_per_task_through_a_pull_request(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}])
        task = lambda number, state: {'id': f'F{number:03d}', 'behavior': f'task {number}', 'acceptance': [], 'dependsOn': [],
                                      'state': state, 'verification': ['ok'], 'evidence': None}
        repo.write('docs/tasks.json', {'schemaVersion': 2, 'nextId': 3, 'tasks': [task(1, 'not_started'), task(2, 'not_started')],
                                       'lastWrapup': {'at': 'earlier', 'clean': True, 'problems': [], 'note': 'old'}})
        repo.commit('earlier harness state'); repo.git('push', 'origin', 'main')
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        repo.write('work.txt', 'done\n')
        self.assertEqual(repo.run('verify', 'F001')[0], 0)
        repo.commit('work')
        code, out = repo.run('done', 'F001')
        self.assertEqual(code, 0, out)
        self.assertIsNone(repo.origin_file('docs/tasks.json'))
        self.assertEqual(json.loads(repo.origin_file('docs/tasks/F001.json'))['state'], 'passing')
        self.assertEqual(json.loads(repo.origin_file('docs/tasks/F002.json'))['state'], 'not_started')

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
        script = "import json; from pathlib import Path; p=Path('docs/tasks/F001.json'); d=json.loads(p.read_text()); d['state']='not_started'; p.write_text(json.dumps(d))"
        repo = Repo(self, [{'id': 'ok', 'argv': OK}, {'id': 'mutate', 'argv': [PY, '-c', script]}])
        repo.run('add', 'dependency', '--accept', 'works', '--check', 'ok')
        repo.run('start', 'F001'); repo.run('verify', 'F001'); repo.commit('dependency')
        self.assertEqual(repo.run('done', 'F001', '--proof', '1=ok')[0], 0)
        repo.run('add', 'dependent', '--accept', 'works', '--check', 'mutate', '--after', 'F001')
        self.assertEqual(repo.run('start', 'F002')[0], 0)
        self.assertNotEqual(repo.run('verify', 'F002')[0], 0)


def second(repo, name, clone=False):
    """Another working tree of the same repository, or another clone of its origin."""
    other = Repo.__new__(Repo)
    other.root, other.env = repo.root.parent / (repo.root.name + name), repo.env
    if clone:
        subprocess.run(['git', 'clone', '-q', str(repo.origin), str(other.root)], check=True)
        subprocess.run(['git', 'config', 'user.name', 't'], cwd=other.root, check=True)
        subprocess.run(['git', 'config', 'user.email', 't@example.com'], cwd=other.root, check=True)
    else:
        repo.git('worktree', 'add', '-q', '--detach', str(other.root), 'main')
    return other


class ReviewFindings(unittest.TestCase):
    """One test for each defect an independent review of the per-task files and parallel work reproduced."""

    def cleanup(self, other):
        self.addCleanup(shutil.rmtree, other.root, ignore_errors=True)
        return other

    def risky(self, use_git=True, mode='local'):
        count = [PY, '-c', "open('docs/runs/count.txt', 'a').write('x')"]
        repo = Repo(self, [{'id': 'bill', 'argv': count, 'required': True, 'paths': ['src/billing/**/*.py']},
                           {'id': 'ok', 'argv': OK, 'required': True}], use_git=use_git)
        config = json.loads((repo.root / 'docs/config.json').read_text())
        config.update(review={'paths': ['src/billing/*']}, delivery={'mode': mode})
        repo.write('docs/config.json', config)
        repo.write('src/billing/total.py', 'v1\n')
        if use_git:
            repo.commit('base')
        return repo

    def test_a_moved_file_and_a_non_ascii_name_still_count_as_changed(self):
        repo = self.risky()
        repo.run('add', 'Move the totals code')
        repo.run('start', 'F001')
        (repo.root / 'src/pricing').mkdir()
        (repo.root / 'src/billing/total.py').rename(repo.root / 'src/pricing/total.py')
        repo.commit('move totals')
        code, out = repo.run('verify', 'F001')
        self.assertIn('bill: passed', out)
        self.assertIn('independent review (src/billing/total.py', out)
        repo.run('review', 'F001', '--pass', '--summary', 'only moved')
        self.assertEqual(repo.run('done', 'F001')[0], 0)
        repo.commit('record')
        repo.run('add', 'Add a payment module')
        repo.run('start', 'F002')
        repo.write('src/billing/zahlung_\u00fc.py', 'v1\n')
        code, out = repo.run('verify', 'F002')
        self.assertIn('bill: passed', out, 'a glob written with **/ also matches a file directly in the folder')
        self.assertIn('independent review (src/billing/zahlung_\u00fc.py', out)

    def test_a_harness_below_the_top_of_the_git_repository_reads_its_own_paths(self):
        repo = self.risky(use_git=False)
        top = repo.root / 'top'
        shutil.copytree(repo.root, top / 'app', ignore=shutil.ignore_patterns('top'))
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=top, check=True)
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-q', '--allow-empty', '-m', 'init'], cwd=top, check=True)
        subprocess.run(['git', 'add', '-A'], cwd=top, check=True)
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-q', '-m', 'app'], cwd=top, check=True)
        app = Repo.__new__(Repo)
        app.root, app.env = top / 'app', repo.env
        app.run('add', 'Change totals')
        app.run('start', 'F001')
        app.write('src/billing/total.py', 'v2\n')
        code, out = app.run('verify', 'F001')
        self.assertIn('bill: passed', out)
        self.assertIn('independent review (src/billing/total.py', out)

    def test_local_delivery_keeps_the_starting_commit_and_no_git_fails_closed(self):
        repo = self.risky()
        repo.run('add', 'Change billing rounding')
        repo.run('start', 'F001')
        repo.write('src/billing/round.py', 'v1\n')
        repo.commit('wip billing')
        repo.run('block', 'F001', '--reason', 'need an answer from the user')
        repo.run('start', 'F001')
        code, out = repo.run('verify', 'F001')
        self.assertIn('independent review (src/billing/round.py', out)
        self.assertEqual(repo.run('done', 'F001')[0], 1)
        repo.run('reopen', 'F001', '--reason', 'one more tweak')
        repo.write('README.md', 'tweak\n')
        self.assertIn('independent review (src/billing/round.py', repo.run('verify', 'F001')[1])
        bare = self.risky(use_git=False)
        bare.run('add', 'Change the readme')
        bare.run('start', 'F001')
        code, out = bare.run('verify', 'F001')
        self.assertIn('review paths are set and the changed files cannot be read', out)

    def test_a_review_survives_an_unrelated_edit_when_the_task_has_acceptance_lines(self):
        repo = self.risky()
        repo.run('add', 'Round totals', '--accept', 'half a cent rounds up')
        repo.run('start', 'F001')
        repo.write('src/billing/total.py', 'v2\n')
        repo.run('verify', 'F001')
        repo.run('verify', 'F001', '--proof', '1=bill: test_half_cent_rounds_up passed')
        self.assertEqual(repo.run('review', 'F001', '--pass', '--summary', 'rounding is right')[0], 0)
        repo.write('README.md', 'a typo fixed after the review\n')
        code, out = repo.run('verify', 'F001')
        self.assertIn('next: commit, then `done F001`', out)
        repo.commit('work')
        self.assertEqual(repo.run('done', 'F001')[0], 0)

    def test_tasks_on_other_branches_are_known_and_two_renumbered_tasks_keep_their_order(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}], delivery={'mode': 'pr', 'autoMerge': True})
        other = self.cleanup(second(repo, '-second'))
        repo.run('add', 'First thing')
        repo.run('add', 'Second thing, needs the first', '--after', 'F001')
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        code, out = other.run('status')
        self.assertNotIn('problem:', out)
        self.assertNotRegex(out, r'(?m) on *(;|$)', 'no task is listed as waiting on nothing')
        self.assertEqual(other.run('add', 'Third thing', '--after', 'F001')[0], 0)
        repo.write('first.txt', 'work\n')
        repo.run('verify', 'F001')
        repo.commit('first')
        self.assertEqual(repo.run('done', 'F001')[0], 0)
        code, out = other.run('start', 'F002')
        self.assertEqual(code, 0, 'a dependency merged from another worktree counts without a pull here: ' + out)
        clone = RemoteRepo(self, [{'id': 'ok', 'argv': OK}])
        clone.run('add', 'A1 schema migration')
        clone.run('add', 'A2 uses the new schema', '--after', 'F001')
        track(clone, 1, 'theirs one')
        track(clone, 2, 'theirs two')
        clone.run('list')
        mine = {task['behavior']: task for task in clone.tasks().values()}
        self.assertEqual(mine['A2 uses the new schema']['dependsOn'], [mine['A1 schema migration']['id']])

    def test_delivery_carries_edits_to_tracked_records_and_leaves_other_files_alone(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        track(repo, 1, 'first')
        track(repo, 2, 'second')
        repo.git('push', 'origin', 'main')
        track(repo, 3, 'third')
        repo.git('push', 'origin', 'main')
        repo.run('start', 'F003')
        repo.write('third.txt', 'half\n')
        repo.commit('wip third')
        repo.run('block', 'F003', '--reason', 'waiting for the user')
        repo.run('start', 'F001')
        repo.write('feature.txt', 'work\n')
        repo.commit('work, with the edited record of the blocked task swept in')
        repo.run('note', 'F002', 'the user wants this in blue')
        repo.write('docs/tasks/how to.md', 'notes that are not a task record\n')
        self.assertEqual(repo.run('verify', 'F001')[0], 0)
        repo.git('add', 'docs/tasks/how to.md')
        repo.git('commit', '-q', '-m', 'notes')
        code, out = repo.run('done', 'F001', '--proof', '1=ok: works')
        self.assertEqual(code, 0, out)
        self.assertIn('F001 merged into main', out)
        self.assertIn('the user wants this in blue', repo.origin_file('docs/tasks/F002.json'))
        self.assertIsNotNone(repo.origin_file('docs/tasks/how to.md'))
        self.assertEqual(json.loads(repo.origin_file('docs/tasks/F003.json'))['state'], 'not_started',
                         'the record of a task in progress travels with its own branch')
        self.assertNotIn('waiting for merge', repo.run('status')[1], 'a file that is no record does not hide the merge')
        code, out = repo.run('start', 'F003')
        self.assertEqual(code, 0, out)

    def test_a_blocked_task_resumes_on_its_older_branch_and_still_merges(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        repo.run('add', 'First thing')
        repo.run('add', 'Second thing')
        repo.run('start', 'F001')
        repo.write('first.txt', 'half\n')
        repo.commit('wip first')
        repo.run('block', 'F001', '--reason', 'need an answer')
        repo.commit('record the block')
        self.assertEqual(repo.run('start', 'F002')[0], 0)
        repo.write('second.txt', 'work\n')
        repo.run('verify', 'F002')
        repo.commit('second')
        self.assertEqual(repo.run('done', 'F002')[0], 0)
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 0, out)
        self.assertEqual(repo.branch(), 'feat/f001-first-thing')
        repo.write('first.txt', 'whole\n')
        repo.run('verify', 'F001')
        repo.commit('first')
        self.assertEqual(repo.run('done', 'F001')[0], 0)

    def test_only_one_branch_replaces_the_single_queue_file(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}], delivery={'mode': 'pr', 'autoMerge': False})
        record = lambda number: {'id': f'F{number:03d}', 'behavior': f'task {number}', 'acceptance': [], 'dependsOn': [],
                                 'state': 'not_started', 'verification': ['ok'], 'evidence': None}
        repo.write('docs/tasks.json', {'schemaVersion': 2, 'nextId': 3, 'tasks': [record(1), record(2)]})
        repo.commit('earlier harness state')
        repo.git('push', 'origin', 'main')
        repo.git('branch', 'feat/f002-task-2-earlier-attempt')
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        repo.write('work.txt', 'done\n')
        repo.run('verify', 'F001')
        repo.commit('work')
        repo.run('done', 'F001')
        code, out = repo.run('start', 'F002')
        self.assertEqual(code, 1, out)
        self.assertIn('still has docs/tasks.json', out)

    def test_a_task_does_not_start_from_a_base_branch_that_has_an_earlier_runner(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}])
        record = lambda number: {'id': f'F{number:03d}', 'behavior': f'task {number}', 'acceptance': [], 'dependsOn': [],
                                 'state': 'not_started', 'verification': ['ok'], 'evidence': None}
        repo.write('docs/tasks.json', {'schemaVersion': 2, 'nextId': 3, 'tasks': [record(1), record(2)]})
        repo.commit('earlier harness state')
        repo.git('push', 'origin', 'main')
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        with open(repo.root / 'scripts/harness.py', 'a') as runner:
            runner.write('# the upgraded runner\n')
        repo.commit('upgrade the harness')
        repo.run('block', 'F001', '--reason', 'waiting for the owner to review the upgrade')
        code, out = repo.run('start', 'F002')
        self.assertEqual(code, 1, out)
        self.assertIn('another version of the runner', out)
        self.assertEqual(repo.branch(), 'feat/f001-task-1')
        self.assertEqual(repo.run('start', 'F001')[0], 0, 'the task that carries the upgrade can go on')

    def test_a_linked_worktree_finishes_detached_and_the_lock_is_waited_for(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        other = self.cleanup(second(repo, '-second'))
        other.run('add', 'Second thing')
        self.assertEqual(other.run('start', 'F001')[0], 0)
        other.write('second.txt', 'work\n')
        other.run('verify', 'F001')
        subprocess.run(['git', 'add', '-A'], cwd=other.root, check=True)
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-q', '-m', 'second'],
                       cwd=other.root, check=True)
        code, out = other.run('done', 'F001')
        self.assertEqual(code, 0, out)
        self.assertIn('this one is now at origin/main', out)
        holder = "import fcntl, sys, time; f = open(sys.argv[1], 'a+'); fcntl.flock(f, fcntl.LOCK_EX); time.sleep(float(sys.argv[2]))"
        lock = repo.root / '.git/harness.lock'
        busy = subprocess.Popen([PY, '-c', holder, str(lock), '1.5'])
        import time
        time.sleep(0.5)
        self.assertEqual(repo.run('add', 'Waited for the lock')[0], 0)
        busy.wait()
        busy = subprocess.Popen([PY, '-c', holder, str(lock), '3'])
        time.sleep(0.5)
        repo.env = dict(repo.env, HARNESS_LOCK_SECONDS='0.2')
        code, out = repo.run('add', 'Gave up on the lock')
        busy.kill()
        busy.wait()
        self.assertEqual(code, 1, out)
        self.assertIn('another harness command', out)

    def test_a_delivery_commit_that_failed_once_works_on_the_next_try(self):
        flaky = [PY, '-c', "import pathlib, sys; sys.exit(pathlib.Path('docs/runs/lint-broken').exists())"]
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}, {'id': 'lint', 'argv': flaky, 'precommit': True}])
        repo.run('add', 'First thing')
        repo.run('add', 'Second thing')
        repo.run('start', 'F001')
        repo.run('block', 'F001', '--reason', 'waiting for the user')
        repo.run('start', 'F002')
        repo.write('two.txt', 'work\n')
        repo.run('verify', 'F002')
        repo.commit('second, with the record of F001 swept in')
        (repo.root / 'docs/runs/lint-broken').write_text('x')
        code, out = repo.run('done', 'F002')
        self.assertEqual(code, 1, out)
        self.assertIn('pre-commit: lint failed', out)
        (repo.root / 'docs/runs/lint-broken').unlink()
        code, out = repo.run('done', 'F002')
        self.assertEqual(code, 0, out)
        self.assertIsNone(repo.origin_file('docs/tasks/F001.json'), 'the record of a task that is not delivered stays off the base branch')
        self.assertTrue((repo.root / 'docs/tasks/F001.json').exists())

    def test_two_clones_that_used_one_number_deliver_under_two(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}], delivery={'mode': 'pr', 'autoMerge': False})
        clone = self.cleanup(second(repo, '-clone', clone=True))
        for tree, name in ((repo, 'Export to CSV'), (clone, 'Import from CSV')):
            self.assertIn('added F001', tree.run('add', name)[1])
            self.assertEqual(tree.run('start', 'F001')[0], 0)
            tree.write(name.split()[0] + '.txt', 'work\n')
            tree.run('verify', 'F001')
            subprocess.run(['git', 'add', '-A'], cwd=tree.root, check=True)
            subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-q', '-m', name], cwd=tree.root, check=True)
        repo.run('done', 'F001')
        subprocess.run(['git', 'push', '-q', 'origin', 'feat/f001-export-to-csv:main'], cwd=repo.root, check=True,
                       env=dict(os.environ, HARNESS_BASE_PUSH='1'))
        code, out = clone.run('done', 'F001')
        self.assertIn('this task is now F002', out)
        merged = self.cleanup(second(repo, '-merge', clone=True))
        result = subprocess.run(['git', 'merge', '-q', '--no-edit', 'origin/feat/f001-import-from-csv'], cwd=merged.root,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({path.stem for path in (merged.root / 'docs/tasks').glob('*.json')}, {'F001', 'F002'})

    def test_two_clones_that_queued_under_the_same_numbers_lose_no_task(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        clone = self.cleanup(second(repo, '-clone', clone=True))
        repo.run('add', 'A1 schema migration')
        repo.run('add', 'A2 uses the new schema', '--after', 'F001')
        clone.run('add', 'B1 export')
        clone.run('start', 'F001')
        clone.write('export.txt', 'work\n')
        clone.run('verify', 'F001')
        subprocess.run(['git', 'add', '-A'], cwd=clone.root, check=True)
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-q', '-m', 'export'],
                       cwd=clone.root, check=True)
        self.assertEqual(clone.run('done', 'F001')[0], 0)
        repo.git('fetch', '-q', 'origin')
        code, out = repo.run('start', 'F002')
        self.assertEqual(code, 1, 'the other clone\'s F001 is not the task this one waits for: ' + out)
        mine = {task['behavior']: task for task in repo.tasks().values()}
        self.assertEqual(set(mine), {'A1 schema migration', 'A2 uses the new schema'}, 'a refused start loses no task')
        code, out = repo.run('start', mine['A1 schema migration']['id'])
        self.assertEqual(code, 0, out)
        self.assertIn('this task is now F003', out)
        self.assertEqual(repo.branch(), 'feat/f003-a1-schema-migration')
        mine = {task['behavior']: task for task in repo.tasks().values()}
        self.assertEqual(mine['A2 uses the new schema']['dependsOn'], ['F003'])

    def test_a_reopened_or_redefined_task_no_longer_satisfies_what_waits_for_it(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        repo.run('add', 'First thing')
        repo.run('add', 'Second thing, needs the first', '--after', 'F001')
        repo.run('start', 'F001')
        repo.write('first.txt', 'work\n')
        repo.run('verify', 'F001')
        repo.commit('first')
        self.assertEqual(repo.run('done', 'F001')[0], 0)
        self.assertIn('ready: F002', repo.run('status')[1])
        repo.run('edit', 'F001', '--accept', 'works for every locale')
        self.assertNotIn('ready: F002', repo.run('status')[1])
        self.assertEqual(repo.run('start', 'F002')[0], 1)
        repo.run('reopen', 'F001', '--reason', 'the export is wrong')
        repo.run('block', 'F001', '--reason', 'waiting for the user')
        self.assertNotIn('ready: F002', repo.run('status')[1])
        code, out = repo.run('start', 'F002')
        self.assertEqual(code, 1, out)
        self.assertIn('F002 waits on F001', out)

    def test_a_task_from_before_the_upgrade_keeps_its_number_when_reworded(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        track(repo, 1, 'first')
        track(repo, 2, 'second')
        repo.git('push', 'origin', 'main')
        repo.run('edit', 'F001', '--behavior', 'First thing, with the export button')
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        repo.write('first.txt', 'work\n')
        repo.run('verify', 'F001')
        repo.commit('first')
        code, out = repo.run('done', 'F001', '--proof', '1=ok: works')
        self.assertEqual(code, 0, out)
        self.assertIn('F001 merged into main', out)
        self.assertNotIn('waiting for merge', repo.run('status')[1])

    def test_proof_is_asked_again_when_the_acceptance_line_changes(self):
        repo = Repo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        repo.run('add', 'Export totals', '--accept', 'the CSV has a header row')
        repo.run('start', 'F001')
        repo.write('export.txt', 'work\n')
        repo.run('verify', 'F001')
        repo.run('verify', 'F001', '--proof', '1=ok: test_csv_has_header passed')
        repo.run('edit', 'F001', '--accept', 'amounts are rounded to cents')
        code, out = repo.run('verify', 'F001')
        self.assertNotIn('next: commit, then `done F001`', out)
        repo.commit('work')
        code, out = repo.run('done', 'F001')
        self.assertEqual(code, 1, out)
        self.assertIn('--proof for 1', out)

    def test_a_blocked_task_resumes_while_another_blocked_task_keeps_its_state(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        track(repo, 1, 'first')
        track(repo, 2, 'second')
        repo.git('push', 'origin', 'main')
        for number in (1, 2):
            repo.run('start', f'F00{number}')
            repo.write(f'file{number}.txt', 'half\n')
            repo.git('add', f'file{number}.txt')
            repo.git('commit', '-q', '-m', f'wip {number}')
            repo.run('block', f'F00{number}', '--reason', f'question {number}')
        code, out = repo.run('start', 'F001')
        self.assertEqual(code, 0, out)
        self.assertEqual(repo.branch(), 'feat/f001-first')
        self.assertEqual(repo.tasks()['F002']['blockedReason'], 'question 2')
        repo.write('file1.txt', 'whole\n')
        repo.run('verify', 'F001')
        repo.git('add', 'file1.txt')
        repo.git('commit', '-q', '-m', 'first')
        self.assertEqual(repo.run('done', 'F001', '--proof', '1=ok: works')[0], 0)
        self.assertEqual(json.loads(repo.origin_file('docs/tasks/F002.json'))['state'], 'not_started')
        self.assertEqual(repo.tasks()['F002']['blockedReason'], 'question 2')

    def test_a_working_tree_that_did_not_pull_does_not_offer_a_merged_task(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        track(repo, 1, 'first')
        track(repo, 2, 'second')
        repo.git('push', 'origin', 'main')
        other = self.cleanup(second(repo, '-second'))
        repo.run('start', 'F002')
        self.assertNotRegex(other.run('status')[1], r'(?m) on *(;|$)', 'a task in progress elsewhere waits on nothing here')
        repo.write('second.txt', 'work\n')
        repo.run('verify', 'F002')
        repo.commit('second')
        self.assertEqual(repo.run('done', 'F002', '--proof', '1=ok: works')[0], 0)
        code, out = other.run('status')
        self.assertIn('ready: F001 first', out)
        self.assertNotIn('F002', out.split('ready:')[1].splitlines()[0])

    def test_a_refused_start_keeps_the_task_it_renumbered(self):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK, 'required': True}])
        track(repo, 1, 'first')
        repo.git('push', 'origin', 'main')
        clone = self.cleanup(second(repo, '-clone', clone=True))
        clone.run('note', 'F001', 'a note from the other clone')
        clone.run('add', 'B1 export')
        clone.run('start', 'F002')
        clone.write('export.txt', 'work\n')
        clone.run('verify', 'F002')
        subprocess.run(['git', 'add', '-A'], cwd=clone.root, check=True)
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-q', '-m', 'export'],
                       cwd=clone.root, check=True)
        self.assertEqual(clone.run('done', 'F002')[0], 0)
        repo.run('add', 'A1 import')
        repo.run('note', 'F001', 'a note from this clone')
        code, out = repo.run('start', 'F002')
        self.assertEqual(code, 1, out)
        self.assertIn('concurrent task queue edits to F001', out)
        self.assertIn('this task is now F003', out)
        self.assertIn('A1 import', {task['behavior'] for task in repo.tasks().values()})

