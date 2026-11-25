import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
from conversation_history import (ConversationHistory, SWITCH_ROLE, conversation_sessions, transcript_context,
                                  unseen_messages)
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

    def test_a_conversation_continued_by_another_agent(self):
        messages = [{'role': 'You', 'text': 'Make the bar taller', 'agent': 'codex'},
                    {'role': 'Agent', 'text': 'The bar is 32 px now.', 'agent': 'codex'},
                    {'role': SWITCH_ROLE, 'text': 'Claude Code', 'agent': 'claude'},
                    {'role': 'You', 'text': 'Also use a bigger font', 'agent': 'claude'},
                    {'role': 'Agent', 'text': 'The font is 14 px.', 'agent': 'claude'},
                    {'role': SWITCH_ROLE, 'text': 'Codex', 'agent': 'codex'}]
        # A new session reads everything; a resumed one only what it missed.
        self.assertEqual([m['text'] for m in unseen_messages(messages, 'gemini', False)],
                         ['Make the bar taller', 'The bar is 32 px now.', 'Also use a bigger font', 'The font is 14 px.'])
        self.assertEqual([m['text'] for m in unseen_messages(messages, 'codex', True)],
                         ['Also use a bigger font', 'The font is 14 px.'])
        self.assertEqual(unseen_messages(messages, 'claude', True), [])
        context = transcript_context(unseen_messages(messages, 'codex', True), resumed=True)
        self.assertIn('since your last turn', context)
        self.assertIn('"agent": "Claude Code"', context)
        self.assertNotIn(SWITCH_ROLE, context)
        self.assertNotIn('Make the bar taller', context)
        self.assertIn('Make the bar taller', transcript_context(unseen_messages(messages, 'claude', False)))
        key = self.history.new_id('Settings Sync · Bar', 'codex')
        self.history.save(key, {'name': 'Settings Sync · Bar', 'agent': 'codex', 'thread_id': 'codex-thread',
                                'sessions': {'codex': 'codex-thread', 'claude': 'claude-session'}}, messages)
        record = self.history.get(key)
        self.assertEqual(record['agents'], ['codex', 'claude'])
        self.assertEqual(conversation_sessions(record), {'codex': 'codex-thread', 'claude': 'claude-session'})

    def test_sessions_of_older_archives(self):
        self.assertEqual(conversation_sessions({'agent': 'claude', 'thread_id': 'old-session'}), {'claude': 'old-session'})
        self.assertEqual(conversation_sessions({'agent': 'codex', 'sessions': {'unknown': 'x', 'claude': ''}}), {})
        self.assertEqual(conversation_sessions(None), {})

    def test_queued_messages_follow_their_conversation_to_another_agent(self):
        queue = Outbox(self.state / 'outbox.json')
        mine = queue.add('codex', 'repo', '', 'codex-thread', 'Mine', True, conversation_id='one')
        other = queue.add('codex', 'repo', '', 'codex-thread', 'Other', True, conversation_id='two')
        queue.follow('one', 'codex', 'claude', None)
        self.assertEqual((mine['agent'], mine['thread_id']), ('claude', None))
        self.assertEqual((other['agent'], other['thread_id']), ('codex', 'codex-thread'))
        self.assertEqual(Outbox(queue.path).entries, [mine, other])

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
