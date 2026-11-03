import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
from updater import INTERVAL, Updater, checkout_state, version_key

IDENTITY = {'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 't@example.com',
            'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 't@example.com',
            'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}


def git(*args):
    subprocess.run(['git', *args], check=True, capture_output=True)


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.env = patch.dict(os.environ, IDENTITY)
        self.env.start()
        self.origin, self.work, self.installed = root / 'origin.git', root / 'work', root / 'installed'
        git('init', '-q', '--bare', '-b', 'main', str(self.origin))
        git('clone', '-q', str(self.origin), str(self.work))
        self.commit('0.1.13', tag='v0.1.13')
        git('clone', '-q', str(self.origin), str(self.installed))
        git('-C', str(self.installed), 'remote', 'set-head', 'origin', 'main')
        self.commit('0.2.0', tag='v0.2.0')
        self.commit('0.2.1-dev')  # Unreleased work on main must not be installed.
        self.now = 1_000_000.0

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def commit(self, version, tag=None):
        (self.work / 'manifest.json').write_text(json.dumps({'version': version}))
        git('-C', str(self.work), 'add', '.')
        git('-C', str(self.work), 'commit', '-q', '-m', version)
        git('-C', str(self.work), 'push', '-q', 'origin', 'HEAD:main')
        if tag:
            git('-C', str(self.work), 'tag', '-a', tag, '-m', tag)
            git('-C', str(self.work), 'push', '-q', 'origin', tag)

    def updater(self, tag='v0.2.0'):
        release = {'tag': tag, 'version': tag.lstrip('v'), 'url': 'https://example.com', 'notes': ''}
        return Updater(Path(self.temp.name) / 'update.json', root=self.installed,
                       fetch=lambda: release, clock=lambda: self.now)

    def version(self):
        return json.loads((self.installed / 'manifest.json').read_text())['version']

    def test_versions_compare_numerically(self):
        self.assertGreater(version_key('v0.1.13'), version_key('0.1.9'))
        self.assertEqual(version_key('main'), ())

    def test_installs_exactly_the_latest_release_tag(self):
        updater = self.updater()
        self.assertTrue(updater.due())
        state = updater.check(install=True)
        self.assertEqual(state['installed'], 'v0.2.0')
        self.assertEqual(self.version(), '0.2.0')
        self.assertIsNone(updater.available())
        self.assertFalse(updater.due())
        self.now += INTERVAL
        self.assertTrue(updater.due())

    def test_only_reports_when_automatic_updates_are_off(self):
        state = self.updater().check(install=False)
        self.assertEqual(state['latest']['tag'], 'v0.2.0')
        self.assertEqual(self.version(), '0.1.13')
        self.assertEqual(self.updater().available()['tag'], 'v0.2.0')

    def test_never_touches_a_test_branch_or_local_edits(self):
        git('-C', str(self.installed), 'switch', '-q', '-c', 'feature/test')
        self.assertEqual(checkout_state(self.installed), 'branch')
        self.assertEqual(self.updater().check(install=True)['blocked'], 'branch')
        self.assertEqual(self.version(), '0.1.13')
        git('-C', str(self.installed), 'switch', '-q', 'main')
        (self.installed / 'manifest.json').write_text('{"version": "edited"}')
        self.assertEqual(self.updater().check(install=True)['blocked'], 'modified')

    def test_network_errors_are_recorded(self):
        updater = Updater(Path(self.temp.name) / 'update.json', root=self.installed,
                          fetch=lambda: (_ for _ in ()).throw(OSError('offline')), clock=lambda: self.now)
        self.assertEqual(updater.check(install=True)['error'], 'offline')


if __name__ == '__main__':
    unittest.main()
