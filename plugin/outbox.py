"""Durable follow-ups. Only native clients expose a reliable turn boundary."""
from __future__ import annotations

import uuid

from core import private_write, read_json


class Outbox:
    def __init__(self, path):
        self.path = path
        self.entries = read_json(path, [])
        if not isinstance(self.entries, list):
            self.entries = []
        self.entries = [entry for entry in self.entries if isinstance(entry, dict)
                        and all(key in entry for key in
                                ("id", "agent", "repository", "branch", "thread_id", "text", "publish"))]
        # A crash after writing to the transport can leave delivery unknown.
        for entry in self.entries:
            if entry.get("state") == "sending":
                entry["state"] = "uncertain"

    def save(self):
        private_write(self.path, self.entries)

    def for_agent(self, agent):
        return [entry for entry in self.entries if entry["agent"] == agent]

    def add(self, agent, repository, branch, thread_id, text, publish, *, first=False):
        entry = dict(id=str(uuid.uuid4()), agent=agent, repository=repository,
                     branch=branch, thread_id=thread_id, text=text, publish=publish, state="pending")
        self.entries.insert(0 if first else len(self.entries), entry)
        self.save()
        return entry

    def remove(self, entry):
        self.entries.remove(entry)
        self.save()

    def mark(self, entry, state):
        entry["state"] = state
        self.save()

    def bind_thread(self, agent, repository, branch, previous, current):
        for entry in self.for_agent(agent):
            if self.matches(entry, repository, branch, previous):
                entry["thread_id"] = current
        self.save()

    @staticmethod
    def matches(entry, repository, branch, thread_id):
        return (entry["repository"], entry["branch"], entry["thread_id"]) == (repository, branch, thread_id)
