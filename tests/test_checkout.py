import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
import checkout

IDENTITY = {'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 't@example.com',
            'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 't@example.com',
            'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}


def git(*args):
    subprocess.run(['git', *args], check=True, capture_output=True)


class CheckoutTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.env = patch.dict(os.environ, IDENTITY)
        self.env.start()
        self.origin = root / 'origin.git'
        git('init', '-q', '--bare', '-b', 'main', str(self.origin))
        seed = root / 'seed'
        git('clone', '-q', str(self.origin), str(seed))
        (seed / 'README.md').write_text('config\n')
        git('-C', str(seed), 'add', '.')
        git('-C', str(seed), 'commit', '-q', '-m', 'seed')
        git('-C', str(seed), 'push', '-q', 'origin', 'HEAD:main')
        self.seed = seed
        self.workspace = root / 'workspace'
        self.url = str(self.origin)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_clone_fast_forward_and_publish_only_the_machine_file(self):
        path, sha, problem = checkout.update(self.workspace, self.url, 'main')
        self.assertIsNone(problem)
        self.assertEqual(path, self.workspace / 'repository')
        (self.seed / 'features.toml').write_text('version = 1\n')
        git('-C', str(self.seed), 'add', '.')
        git('-C', str(self.seed), 'commit', '-q', '-m', 'catalog')
        git('-C', str(self.seed), 'push', '-q', 'origin', 'HEAD:main')
        _, newer, problem = checkout.update(self.workspace, self.url, 'main')
        self.assertIsNone(problem)
        self.assertNotEqual(newer, sha)
        self.assertTrue((path / 'features.toml').exists())
        machine = path / 'machines/desk.toml'
        machine.parent.mkdir()
        machine.write_text('name = "desk"\n')
        (path / 'unrelated.txt').write_text('agent work in progress\n')
        self.assertIsNone(checkout.publish(path, 'main', [machine], 'Update settings for desk'))
        files = subprocess.run(['git', '--git-dir', str(self.origin), 'show', '--name-only', '--format=', 'main'],
                               capture_output=True, text=True).stdout.split()
        self.assertEqual(files, ['machines/desk.toml'])
        self.assertTrue((path / 'unrelated.txt').exists())

    def test_never_pushes_other_local_commits(self):
        path, _, _ = checkout.update(self.workspace, self.url, 'main')
        (path / 'local.txt').write_text('unpublished\n')
        git('-C', str(path), 'add', '.')
        git('-C', str(path), 'commit', '-q', '-m', 'local only')
        machine = path / 'machines/desk.toml'
        machine.parent.mkdir()
        machine.write_text('name = "desk"\n')
        problem = checkout.publish(path, 'main', [machine], 'Update settings for desk')
        self.assertIn('not on origin/main', problem)
        log = subprocess.run(['git', '--git-dir', str(self.origin), 'log', '--format=%s', 'main'],
                             capture_output=True, text=True).stdout.split('\n')
        self.assertNotIn('local only', log)

    def test_another_remote_gets_its_own_working_copy(self):
        (self.workspace / 'repository').mkdir(parents=True)
        git('init', '-q', str(self.workspace / 'repository'))
        git('-C', str(self.workspace / 'repository'), 'remote', 'add', 'origin', 'https://example.com/other/repo')
        self.assertNotEqual(checkout.location(self.workspace, self.url), self.workspace / 'repository')

    def push_from_another_machine(self, name, text, message='another machine'):
        (self.seed / name).parent.mkdir(parents=True, exist_ok=True)
        (self.seed / name).write_text(text)
        git('-C', str(self.seed), 'add', '.')
        git('-C', str(self.seed), 'commit', '-q', '-m', message)
        git('-C', str(self.seed), 'push', '-q', 'origin', 'HEAD:main')

    def test_fetch_without_fast_forward_leaves_the_working_copy_and_exports_the_repository(self):
        path, sha, _ = checkout.update(self.workspace, self.url, 'main')
        self.push_from_another_machine('features.toml', 'version = 1\n')
        # While the agent works, Sync only fetches.
        _, still, problem = checkout.update(self.workspace, self.url, 'main', fast_forward=False)
        self.assertIsNone(problem)
        self.assertEqual(still, sha)
        self.assertFalse((path / 'features.toml').exists())
        remote, ahead, behind = checkout.compare(path, 'main')
        self.assertNotEqual(remote, sha)
        self.assertEqual((ahead, behind), (0, 1))
        copy = Path(self.temp.name) / 'state/published'
        self.assertIsNone(checkout.export(path, remote, copy))
        self.assertEqual((copy / 'features.toml').read_text(), 'version = 1\n')
        self.assertFalse((copy / '.git').exists())
        self.assertIsInstance(checkout.last_change(path, remote), int)
        # The same commit is not exported twice; a newer one replaces the copy.
        (copy / 'marker').write_text('kept\n')
        self.assertIsNone(checkout.export(path, remote, copy))
        self.assertTrue((copy / 'marker').exists())
        self.push_from_another_machine('features.toml', 'version = 1\n# newer\n')
        checkout.update(self.workspace, self.url, 'main', fast_forward=False)
        newer, _, _ = checkout.compare(path, 'main')
        self.assertIsNone(checkout.export(path, newer, copy))
        self.assertFalse((copy / 'marker').exists())
        self.assertIn('# newer', (copy / 'features.toml').read_text())
        # When the agent is done, the working copy catches up without fetching again.
        self.assertIsNone(checkout.catch_up(path, 'main'))
        self.assertEqual(checkout.head(path), newer)

    def test_local_changes_that_block_a_fast_forward_are_named(self):
        path, _, _ = checkout.update(self.workspace, self.url, 'main')
        machine = path / 'machines/desk.toml'
        machine.parent.mkdir()
        machine.write_text('name = "desk"\n')
        git('-C', str(path), 'add', '.')
        git('-C', str(path), 'commit', '-q', '-m', 'desk')
        git('-C', str(path), 'push', '-q', 'origin', 'HEAD:main')
        git('-C', str(self.seed), 'pull', '-q', 'origin', 'main')
        machine.write_text('name = "desk"\n[features]\nunpublished = "on"\n')
        # Removing a customization elsewhere also edits this machine's choices.
        self.push_from_another_machine('machines/desk.toml', 'name = "desk"\n[features]\n')
        self.push_from_another_machine('features.toml', 'version = 1\n')
        problem = checkout.update(self.workspace, self.url, 'main')[2]
        self.assertTrue(problem)
        self.assertEqual(checkout.changed(path), ['machines/desk.toml'])
        self.assertEqual(checkout.compare(path, 'main')[1:], (0, 2))
        self.assertIn('unpublished', machine.read_text(), 'local changes are never discarded')

    def test_unpublished_local_commits_are_counted(self):
        path, _, _ = checkout.update(self.workspace, self.url, 'main')
        (path / 'local.txt').write_text('unpublished\n')
        git('-C', str(path), 'add', '.')
        git('-C', str(path), 'commit', '-q', '-m', 'local only')
        self.push_from_another_machine('features.toml', 'version = 1\n')
        self.assertTrue(checkout.update(self.workspace, self.url, 'main')[2])
        self.assertEqual(checkout.compare(path, 'main')[1:], (1, 1))


if __name__ == '__main__':
    unittest.main()
