"""Local conversation snapshots, with metadata for resuming native sessions.

Keep transcript files as lists for compatibility with existing archives. The
private index supplies the session, repository and draft missing in old files.

A conversation can pass between agents. Each message records the agent it was
exchanged with, an agent-switch entry marks where another agent took over, and
the index keeps each native agent's own session in the conversation.
"""
from datetime import datetime
import json
from pathlib import Path
import time

from conversation_names import archive_filename, conversation_name
from core import AGENTS, private_write, read_json

USER_ROLES = {'You', 'Você', 'Tú'}
# A transcript entry, not a message: another agent continues the conversation from here.
SWITCH_ROLE = 'agent-switch'


def conversation_agents(messages, current=None):
    """The agents that took part, in order, ending with the one that answers next."""
    agents = [m.get('agent') for m in messages if m.get('role') != SWITCH_ROLE]
    return [a for a in dict.fromkeys(agents + [current]) if a in AGENTS]


def conversation_sessions(record):
    """Each native agent's session in a saved conversation, also for older archives."""
    sessions = record.get('sessions') if record else None
    sessions = {a: t for a, t in sessions.items() if a in AGENTS and isinstance(t, str) and t} \
        if isinstance(sessions, dict) else {}
    if record and record.get('agent') in AGENTS and record.get('thread_id'):
        sessions.setdefault(record['agent'], record['thread_id'])
    return sessions


def unseen_messages(messages, agent, resumed):
    """What an agent's session has not seen of this conversation.

    A resumed session missed only what came after its own last message; a new
    session has seen nothing."""
    messages = [m for m in messages if m.get('role') != SWITCH_ROLE]
    if resumed:
        last = max((i for i, m in enumerate(messages) if m.get('agent') == agent), default=-1)
        messages = messages[last + 1:]
    return messages


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
        request = next((m['text'] for m in messages if m['role'] in USER_ROLES), '')
        try:
            modified = path.stat().st_mtime
            created = datetime.strptime(identifier[:15], '%Y%m%d-%H%M%S').timestamp()
        except (OSError, ValueError):
            modified = created = 0
        return {**metadata, 'id': identifier, 'agent': agent, 'messages': messages,
                'agents': conversation_agents(messages, agent),
                'name': metadata.get('name') or conversation_name(request),
                'created_at': metadata.get('created_at', created),
                'updated_at': metadata.get('updated_at', modified),
                'legacy': not bool(metadata)}

    def entries(self):
        records = (self.get(path.name) for path in self.directory.glob('*.json'))
        return sorted((r for r in records if r), key=lambda r: r['updated_at'], reverse=True)


def transcript_context(messages, limit=32000, *, resumed=False):
    """Earlier messages for a session that has not seen them, newest first within the limit.

    A new session receives the conversation so far, from an older archive or
    from another agent. A resumed session receives only what was said with
    other agents since its own last turn. Either way the text comes before the
    request, so the session's earlier turns stay a cacheable prefix."""
    selected = []
    remaining = limit
    for message in reversed(messages):
        role, text = message.get('role', ''), message.get('text', '')
        if not text or remaining <= 0 or role == SWITCH_ROLE:
            continue
        entry = {'role': role, 'text': text[-remaining:]}
        if role not in USER_ROLES and message.get('agent') in AGENTS:
            entry['agent'] = AGENTS[message['agent']]
        if message.get('images'):
            entry['images_attached'] = len(message['images'])
        selected.append(entry)
        remaining -= len(json.dumps(entry, ensure_ascii=False))
    if not selected:
        return ''
    heading = ('Messages of this conversation that your session has not seen: since your last turn, '
               'the user continued it with another agent' if resumed else
               'Earlier messages of this conversation, from a saved transcript or from another agent '
               'the user was talking to')
    return (heading + ' (background only; do not repeat actions already taken). '
            'The current request follows.\n' +
            json.dumps(list(reversed(selected)), ensure_ascii=False) + '\n\n')
