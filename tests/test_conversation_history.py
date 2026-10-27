import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
from conversation_history import ConversationHistory, transcript_context
from core import private_write
from outbox import Outbox


class ConversationHistoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)
        self.history = ConversationHistory(self.state)
        self.messages = [{'role': 'You', 'text': 'Fix my keyboard'}, {'role': 'Agent', 'text': 'Done'}]

    def tearDown(self):
        self.temp.cleanup()

    def test_resumable_snapshot_preserves_transcript_format_and_metadata(self):
        key = self.history.new_id('Settings Sync · Keyboard', 'codex')
        metadata = {'name': 'Settings Sync · Keyboard', 'agent': 'codex', 'thread_id': 'native-thread',
                    'repository': 'https://example.com/config', 'branch': 'work',
                    'draft': {'text': 'Next request', 'images': ['/private/image.png'], 'publish': False}}
        self.history.save(key, metadata, self.messages)
        record = ConversationHistory(self.state).get(key)
        for field, value in metadata.items():
            self.assertEqual(record[field], value)
        self.assertEqual(record['messages'], self.messages)
        self.assertEqual(json.loads((self.history.directory / key).read_text()), self.messages)
        self.assertEqual(self.history.index_path.stat().st_mode & 0o777, 0o600)
        self.history.save(key, metadata, self.messages + [{'role': 'You', 'text': 'Follow-up'}])
        self.assertEqual(len(self.history.entries()), 1, 'Resuming must update the same history entry')
        self.assertEqual(self.history.get(key)['created_at'], record['created_at'])

    def test_legacy_archives_are_read_without_inventing_session_ids(self):
        for filename, agent in [('20261022-093523.json', None),
                                ('20261027-095754-claude-keyboard-12345678.json', 'claude')]:
            private_write(self.history.directory / filename, self.messages)
            record = self.history.get(filename)
            self.assertEqual(record['agent'], agent)
            self.assertTrue(record['legacy'])
            self.assertNotIn('thread_id', record)
            self.assertIn('Fix my keyboard', record['name'])
        self.assertEqual(len(self.history.entries()), 2)

    def test_invalid_archives_and_traversal_are_ignored(self):
        private_write(self.history.directory / 'invalid.json', {'unexpected': True})
        self.assertEqual(self.history.entries(), [])
        self.assertIsNone(self.history.get('../conversation.json'))
        self.assertIsNone(self.history.get(None))

    def test_legacy_context_is_bounded_and_only_contains_transcript_text(self):
        messages = [{'role': 'You', 'text': 'older secret phrase', 'images': ['/private/path']},
                    {'role': 'Agent', 'text': 'x' * 50000}]
        context = transcript_context(messages, limit=1000)
        self.assertNotIn('/private/path', context)
        self.assertNotIn('older secret phrase', context)
        self.assertLess(len(context), 1300)
        self.assertIn('do not repeat', context)
        self.assertEqual(transcript_context([]), '')

    def test_queued_drafts_bind_only_to_their_own_local_conversation(self):
        queue = Outbox(self.state / 'outbox.json')
        first = queue.add('codex', 'repo', '', None, 'First', False, conversation_id='one')
        second = queue.add('codex', 'repo', '', None, 'Second', False, conversation_id='two')
        queue.bind_thread('codex', 'repo', '', None, 'thread-one', 'one')
        self.assertEqual(first['thread_id'], 'thread-one')
        self.assertIsNone(second['thread_id'])
        self.assertEqual(Outbox(queue.path).entries, [first, second])


if __name__ == '__main__':
    unittest.main()
