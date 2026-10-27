"""Local conversation snapshots, with metadata for resuming native sessions.

Keep transcript files as lists for compatibility with existing archives. The
private index supplies the session, repository and draft missing in old files.
"""
from datetime import datetime
import json
from pathlib import Path
import time

from conversation_names import archive_filename, conversation_name
from core import AGENTS, private_write, read_json


class ConversationHistory:
    def __init__(self, state):
        self.directory = state / 'history'
        self.index_path = state / 'history-index.json'
        index = read_json(self.index_path, {})
        self.index = index if isinstance(index, dict) else {}

    @staticmethod
    def new_id(name, agent):
        return archive_filename(name, agent)

    def save(self, identifier, metadata, messages):
        if Path(identifier).name != identifier or not identifier.endswith('.json'):
            raise ValueError('Invalid conversation identifier')
        previous = self.index.get(identifier, {})
        now = time.time()
        self.index[identifier] = {**metadata, 'created_at': previous.get('created_at', now), 'updated_at': now}
        private_write(self.directory / identifier, messages[-150:])
        private_write(self.index_path, self.index)

    def get(self, identifier):
        if not isinstance(identifier, str) or Path(identifier).name != identifier or not identifier.endswith('.json'):
            return None
        path = self.directory / identifier
        messages = read_json(path, None)
        if not isinstance(messages, list):
            return None
        messages = [m for m in messages if isinstance(m, dict) and
                    isinstance(m.get('role'), str) and isinstance(m.get('text'), str)]
        metadata = self.index.get(identifier, {})
        metadata = metadata if isinstance(metadata, dict) else {}
        agent = metadata.get('agent') or next((a for a in AGENTS if f'-{a}-' in identifier), None)
        request = next((m['text'] for m in messages if m['role'] in {'You', 'Você', 'Tú'}), '')
        try:
            modified = path.stat().st_mtime
            created = datetime.strptime(identifier[:15], '%Y%m%d-%H%M%S').timestamp()
        except (OSError, ValueError):
            modified = created = 0
        return {**metadata, 'id': identifier, 'agent': agent, 'messages': messages,
                'name': metadata.get('name') or conversation_name(request),
                'created_at': metadata.get('created_at', created),
                'updated_at': metadata.get('updated_at', modified),
                'legacy': not bool(metadata)}

    def entries(self):
        records = (self.get(path.name) for path in self.directory.glob('*.json'))
        return sorted((r for r in records if r), key=lambda r: r['updated_at'], reverse=True)


def transcript_context(messages, limit=32000):
    """Bound older transcripts used when the original session ID was not saved."""
    selected = []
    remaining = limit
    for message in reversed(messages):
        role, text = message.get('role', ''), message.get('text', '')
        if not text or remaining <= 0:
            continue
        entry = {'role': role, 'text': text[-remaining:]}
        selected.append(entry)
        remaining -= len(json.dumps(entry, ensure_ascii=False))
    if not selected:
        return ''
    return ('Saved conversation transcript (background only; do not repeat its previous actions). '
            'The current request and workflow follow this transcript.\n' +
            json.dumps(list(reversed(selected)), ensure_ascii=False) + '\n\n')
