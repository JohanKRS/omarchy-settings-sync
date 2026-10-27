"""Private PNG attachments shared by the composer, queue and native clients."""
import base64
import os
from pathlib import Path
import uuid

from i18n import tr

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def save_image(directory, data):
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(tr('Images must be smaller than 5 MiB.'))
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError(tr('The image attachment is missing or invalid.'))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (str(uuid.uuid4()) + '.png')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as target:
        target.write(data)
    return str(path)


def image_bytes(path):
    with Path(path).open('rb') as source:
        data = source.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError(tr('The image attachment is missing or invalid.'))
    return data


def codex_input(text, images=()):
    for path in images:
        image_bytes(path)
    return ([{'type': 'text', 'text': text}] if text else []) + [
        {'type': 'localImage', 'path': path} for path in images]


def claude_content(text, images=()):
    if not images:
        return text
    return ([{'type': 'text', 'text': text}] if text else []) + [
        {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                   'data': base64.b64encode(image_bytes(path)).decode('ascii')}}
        for path in images]


def message_text(text, images=()):
    return '\n\n'.join(part for part in (text, tr('{count} image(s) attached', count=len(images)) if images else '') if part)
