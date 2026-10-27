import base64
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
from attachments import MAX_IMAGE_BYTES, image_bytes, save_image
from core import CodexClient
from claude_client import ClaudeClient
from outbox import Outbox

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aT1sAAAAASUVORK5CYII=')


class AttachmentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = save_image(self.root / 'attachments', PNG)

    def tearDown(self):
        self.temp.cleanup()

    def test_private_png_storage_and_limits(self):
        self.assertEqual(image_bytes(self.path), PNG)
        self.assertEqual(Path(self.path).stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(self.path).parent.stat().st_mode & 0o777, 0o700)
        for data in (b'not an image', b'\x89PNG\r\n\x1a\n' + b'x' * MAX_IMAGE_BYTES):
            with self.assertRaises(ValueError):
                save_image(self.root / 'attachments', data)
        self.assertEqual(len(list((self.root / 'attachments').iterdir())), 1)

    def test_codex_turn_and_steer_deliver_image_blocks(self):
        client = CodexClient(lambda _: None)
        client.request = Mock()
        for text in ('Explain this screenshot', ''):
            client.turn('thread', text, images=[self.path])
            start = client.request.call_args.args
            self.assertEqual(start[0], 'turn/start')
            content = start[1]['input']
            self.assertEqual(content[-1], {'type': 'localImage', 'path': self.path})
            self.assertEqual(len(content), 2 if text else 1)
            client.steer('thread', 'turn', text, images=[self.path])
            self.assertEqual(client.request.call_args.args[1], {
                'threadId': 'thread', 'expectedTurnId': 'turn', 'input': content})

    def test_claude_delivers_png_bytes_and_preserves_plain_text(self):
        client = ClaudeClient(lambda _: None)
        client.send = Mock()
        client.turn('thread', 'Explain', images=[self.path])
        message = client.send.call_args.args[0]
        self.assertEqual(message['type'], 'user')
        content = message['message']['content']
        self.assertEqual(content[0], {'type': 'text', 'text': 'Explain'})
        self.assertEqual(content[1]['source']['media_type'], 'image/png')
        self.assertEqual(base64.b64decode(content[1]['source']['data']), PNG)
        client.turn('thread', 'Plain text')
        self.assertEqual(client.send.call_args.args[0]['message']['content'], 'Plain text')

    def test_missing_images_fail_before_sending(self):
        Path(self.path).unlink()
        for client in (CodexClient(lambda _: None), ClaudeClient(lambda _: None)):
            client.request = client.send = Mock()
            with self.assertRaises(OSError):
                client.turn('thread', 'Keep this request', images=[self.path])
            client.send.assert_not_called()

    def test_queue_keeps_images_across_restart_and_uncertain_delivery(self):
        queue = Outbox(self.root / 'outbox.json')
        images = [self.path]
        entry = queue.add('codex', 'example/config', '', None, '', False, images=images)
        images.clear()
        queue.mark(entry, 'sending')
        restored = Outbox(queue.path).entries[0]
        self.assertEqual(restored['state'], 'uncertain')
        self.assertEqual(restored['images'], [self.path])
        self.assertEqual(image_bytes(restored['images'][0]), PNG)


if __name__ == '__main__':
    unittest.main()
