from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
from conversation_names import archive_filename, conversation_name


class ConversationNameTest(unittest.TestCase):
    def test_request_names_are_short_single_line_and_keep_unicode(self):
        self.assertEqual(conversation_name('  ## Ajustar a fonte\n do terminal\t'),
                         'Settings Sync · Ajustar a fonte do terminal')
        self.assertEqual(conversation_name('Atalho\x00 para áudio'), 'Settings Sync · Atalho para áudio')
        for text in ('Aplicar configuração ' * 20, 'x' * 200):
            title = conversation_name(text)
            self.assertLessEqual(len(title), len('Settings Sync · ') + 72)
            self.assertTrue(title.endswith('…'))

    def test_actions_have_readable_names_without_workflow_instructions(self):
        with patch('conversation_names.tr', side_effect=lambda s: s):
            for flags, expected in (({'sync': True}, 'Sync settings'),
                                    ({'create': True}, 'Create configuration repository'),
                                    ({'review_existing': True}, 'Review existing customizations')):
                self.assertEqual(conversation_name('Internal text', **flags), 'Settings Sync · ' + expected)
            self.assertEqual(conversation_name(' \n\x00 '), 'Settings Sync · Configuration')

    def test_archive_names_are_searchable_safe_and_unique(self):
        title = 'Settings Sync · Ajustar ~/áudio/../perfil'
        first = archive_filename(title, 'codex')
        second = archive_filename(title, 'codex')
        self.assertNotEqual(first, second)
        self.assertIn('-codex-Ajustar-áudio-perfil-', first)
        self.assertEqual(Path(first).name, first)
        self.assertTrue(first.endswith('.json'))
        unsafe = archive_filename('../', '../../claude')
        self.assertEqual(Path(unsafe).name, unsafe)
        self.assertIn('-claude-conversation-', unsafe)
        self.assertLess(len(archive_filename('𝒜' * 200, 'claude').encode('utf-8')), 255)
