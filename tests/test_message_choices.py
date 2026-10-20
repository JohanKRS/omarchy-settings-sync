from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
from message_choices import choice_groups
from message_markup import parse_markdown


def groups(text):
    return list(choice_groups(parse_markdown(text)).values())


class ConversationChoiceTests(unittest.TestCase):
    def test_numbered_options_include_question_and_full_answer(self):
        group, = groups('Qual opção você prefere?\n\n1. **Manter** `~/Desktop` — preservar atalhos.\n2. Mover a pasta.')
        self.assertEqual(group.question, 'Qual opção você prefere?')
        self.assertEqual([c.text for c in group.choices], ['Manter ~/Desktop — preservar atalhos.', 'Mover a pasta.'])

    def test_question_after_options_and_supported_languages(self):
        for question in ('Which option do you prefer?', 'Qual você prefere?', '¿Cuál prefieres?'):
            with self.subTest(question=question):
                group, = groups('- Blue\n- Green\n\n' + question)
                self.assertEqual(group.question, question)
                self.assertEqual(len(group.choices), 2)
        self.assertTrue(groups('Choose an option:\n\n- A\n- B'))

    def test_lettered_options_with_or_without_separate_intro(self):
        for separator in ('\n', '\n\n'):
            group, = groups('Qual opção prefere?' + separator + 'A) **Azul**\nB) Verde')
            self.assertEqual([c.text for c in group.choices], ['Azul', 'Verde'])
        self.assertFalse(groups('Which option?\n\nA) Blue\nC) Green'))

    def test_normal_lists_quotes_code_and_checklists_are_not_questions(self):
        for text in ('Changes made:\n\n1. Blue\n2. Green',
                     'How does it work?\n\n1. First step\n2. Second step',
                     'Which option?\n\n- [ ] Blue\n- [x] Green',
                     '> Which option?\n>\n> - Blue\n> - Green',
                     '```\nWhich option?\n\n- Blue\n- Green\n```',
                     'Which option?\n\n- Blue\n  - Nested\n- Green',
                     'Which option?\n\n- Only one',
                     'Which option?\n\nUnrelated explanation.\n\n- Blue\n- Green'):
            with self.subTest(text=text):
                self.assertFalse(groups(text))

    def test_links_and_html_become_literal_answer_text(self):
        group, = groups('Which option?\n\n- [Blue](https://example.com) &amp; <b>green</b>\n- `$(touch /tmp/no)`')
        self.assertEqual(group.choices[0].text, 'Blue & green')
        self.assertEqual(group.choices[1].text, '$(touch /tmp/no)')


if __name__ == '__main__':
    unittest.main()
