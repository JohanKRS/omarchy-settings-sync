import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
from core import AGENTS
from outbox import Outbox


class OutboxTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'outbox.json'
        self.queue = Outbox(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, agent='codex', **kwargs):
        return self.queue.add(agent, 'https://example.com/team/config', 'main', None,
                              'Keep this\nmessage exactly', False, **kwargs)

    def test_every_supported_agent_has_an_independent_durable_fifo(self):
        for agent in AGENTS:
            first, second = self.add(agent), self.add(agent)
            self.assertEqual(self.queue.for_agent(agent), [first, second])
        restored = Outbox(self.path)
        self.assertEqual(restored.entries, self.queue.entries)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(restored.entries), 2 * len(AGENTS))

    def test_crash_during_delivery_requires_review_not_automatic_retry(self):
        entry = self.add()
        self.queue.mark(entry, 'sending')
        restored = Outbox(self.path)
        self.assertEqual(restored.entries[0]['state'], 'uncertain')
        self.assertEqual(restored.entries[0]['text'], entry['text'])

    def test_thread_binding_cannot_cross_agents_repositories_or_branches(self):
        entry = self.add()
        other = self.add('claude')
        mismatched = self.queue.add('codex', 'https://example.com/other/config', 'main', None, 'other', True)
        branch = self.queue.add('codex', entry['repository'], 'other', None, 'branch', True)
        self.queue.bind_thread('codex', entry['repository'], 'main', None, 'new-thread')
        self.assertTrue(self.queue.matches(entry, entry['repository'], 'main', 'new-thread'))
        for untouched in (other, mismatched, branch):
            self.assertIsNone(untouched['thread_id'])
        self.assertFalse(self.queue.matches(entry, entry['repository'], 'main', 'old-thread'))

    def test_redirect_gets_priority_without_discarding_queued_work(self):
        first, second = self.add(), self.add()
        direction = self.add(first=True)
        self.assertEqual(self.queue.for_agent('codex'), [direction, first, second])
        self.queue.remove(direction)
        self.assertEqual(Outbox(self.path).entries, [first, second])

    def test_invalid_state_does_not_crash_startup(self):
        self.path.write_text(json.dumps([{}, None, 'bad']))
        self.assertEqual(Outbox(self.path).entries, [])


if __name__ == '__main__':
    unittest.main()
