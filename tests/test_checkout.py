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


if __name__ == '__main__':
    unittest.main()
