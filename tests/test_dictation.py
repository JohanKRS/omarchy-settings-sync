import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
from dictation import DictationInbox, identity, last_files, spaced, stranded_text

try:
    import gi  # noqa: F401
    from gi.repository import GLib  # noqa: F401
    HAVE_GI = True
except (ImportError, ValueError):
    HAVE_GI = False


def entry(text='Teste, teste.', delivery='clipboard', warning='panel_has_keyboard', created=1794440855, session=3):
    return {'text': text, 'delivery': delivery, 'warning': warning, 'createdAt': created, 'session_id': session}


class StrandedTextTest(unittest.TestCase):
    def test_only_a_dictation_withheld_because_a_panel_had_the_keyboard_is_taken(self):
        self.assertEqual(stranded_text(entry()), 'Teste, teste.')
        self.assertEqual(stranded_text(entry(warning='panel_has_keyboard: Vocabulary needles are being prepared')),
                         'Teste, teste.')
        self.assertEqual(stranded_text(entry(text='  Ditado.\n')), 'Ditado.')

    def test_other_deliveries_stay_where_superwhisper_put_them(self):
        for other in (entry(delivery='pasted'), entry(delivery='paste_sent'), entry(delivery='fcitx5'),
                      entry(warning='auto_paste_off'), entry(warning=None), entry(warning='focus_changed'),
                      entry(text=''), entry(text='   '), entry(text=None), None, [], 'text'):
            self.assertIsNone(stranded_text(other), other)

    def test_identity_tells_dictations_apart(self):
        self.assertEqual(identity(entry()), identity(entry(delivery='pasted')))
        self.assertNotEqual(identity(entry()), identity(entry(created=1794440856)))
        self.assertNotEqual(identity(entry()), identity(entry(session=4)))
        self.assertIsNone(identity(None))


class SpacingTest(unittest.TestCase):
    def test_a_space_separates_the_dictation_from_neighboring_words(self):
        self.assertEqual(spaced('Teste.'), 'Teste.')
        self.assertEqual(spaced('Teste.', before='a'), ' Teste.')
        self.assertEqual(spaced('Teste.', before=' '), 'Teste.')
        self.assertEqual(spaced('Teste.', before='\n'), 'Teste.')
        self.assertEqual(spaced('teste', after='x'), 'teste ')
        self.assertEqual(spaced('teste', before='a', after='b'), ' teste ')

    def test_punctuation_and_brackets_need_no_space(self):
        self.assertEqual(spaced(', depois.', before='a'), ', depois.')
        self.assertEqual(spaced('teste', before='('), 'teste')
        self.assertEqual(spaced('teste', after='.'), 'teste')
        self.assertEqual(spaced('teste', after=')'), 'teste')


class LastFilesTest(unittest.TestCase):
    def test_release_development_and_explicit_runtime_folders(self):
        self.assertEqual(last_files({'XDG_RUNTIME_DIR': '/run/user/1000'}), [
            Path('/run/user/1000/superwhisper/last.json'), Path('/run/user/1000/superwhisper-dev/last.json')])
        self.assertEqual(last_files({'SUPERWHISPER_RUNTIME': '/tmp/sw', 'XDG_RUNTIME_DIR': '/run/user/1000'})[0],
                         Path('/tmp/sw/last.json'))
        self.assertEqual(last_files({}), [])


@unittest.skipUnless(HAVE_GI, 'PyGObject is not installed')
class InboxTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'last.json'
        self.delivered = []
        self.inbox = DictationInbox(self.delivered.append, files=[self.path])

    def tearDown(self):
        self.inbox.stop()
        self.temp.cleanup()

    def write(self, value):
        self.path.write_text(json.dumps(value))

    def test_a_dictation_from_before_the_panel_opened_is_left_alone(self):
        self.write(entry())
        self.inbox.watch(True)
        self.inbox.check()
        self.assertEqual(self.delivered, [])

    def test_each_new_withheld_dictation_is_delivered_once(self):
        self.write(entry(text='Antes.', delivery='pasted'))
        self.inbox.watch(True)
        self.write(entry(text='Primeiro.', created=1794440900))
        self.inbox.check()
        self.inbox.check()  # Superwhisper may rewrite the same dictation.
        self.write(entry(text='Segundo.', created=1794440910))
        self.inbox.check()
        self.write(entry(text='Colado.', delivery='pasted', created=1794440920))
        self.inbox.check()
        self.assertEqual(self.delivered, ['Primeiro.', 'Segundo.'])

    def test_missing_or_broken_files_are_ignored(self):
        self.inbox.watch(True)
        self.inbox.check()
        self.path.write_text('{not json')
        self.inbox.check()
        self.assertEqual(self.delivered, [])

    def test_hiding_the_panel_stops_watching(self):
        self.inbox.watch(True)
        self.assertEqual(len(self.inbox.monitors), 1)
        self.inbox.watch(False)
        self.assertEqual(self.inbox.monitors, [])


if __name__ == '__main__':
    unittest.main()
