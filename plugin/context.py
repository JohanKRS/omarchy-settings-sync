"""Local task history informs prompts; it never applies configuration itself."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import uuid
from urllib.parse import urlparse


def identity(repository):
    value = repository.strip().rstrip("/").removesuffix(".git")
    if value.startswith("git@") and ":" in value:
        host, path = value[4:].split(":", 1)
    else:
        parsed = urlparse(value)
        host, path = parsed.hostname or "", parsed.path.strip("/")
    return host.lower() + "/" + (path.lower() if host.lower() == "github.com" else path)


def repository_state(locations, repository):
    key = hashlib.sha256(identity(repository).encode()).hexdigest()[:20]
    return Path(locations["state"]) / "repositories" / key


def load(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def snapshot(locations, repository, branch="", *, thread_id=None, operation="change"):
    directory = repository_state(locations, repository)
    record = load(directory / "last-sync.json", {})
    if not record:
        record = load(Path(locations["state"]) / "last-sync.json", {})
    if not isinstance(record, dict):
        record = {}
    if identity(record.get("repository", "")) != identity(repository):
        record = {}
    if branch and record.get("branch") != branch:
        record = {}
    activities = load(directory / "activity.json", [])
    activities = [a for a in activities if isinstance(a, dict) and (not branch or a.get("branch") == branch)] if isinstance(activities, list) else []
    last = activities[-1] if activities else None
    sha = record.get("sha", record.get("commit", record.get("commit_sha", "")))
    complete = (record.get("status") == "complete" and isinstance(sha, str)
                and re.fullmatch(r"[a-fA-F0-9]{40}", sha) and not record.get("pending"))
    if complete and operation == "sync":
        scenario = "check_remote_head_first"
    elif record or (last and last.get("status") in ("running", "interrupted", "failed", "external_unverified")):
        scenario = "resume_and_verify"
    elif activities or thread_id:
        scenario = "existing_workspace"
    else:
        scenario = "first_plugin_use_existing_system"
    return {
        "scenario": scenario,
        "machine": platform.node(),
        "conversation_resumed": bool(thread_id),
        "previous_tasks": len(activities),
        "last_task": last,
        "last_sync": {k: record[k] for k in ("repository", "branch", "status", "pending", "date") if k in record},
        "last_applied_sha": sha if complete else None,
        "sync_record_path": str(directory / "last-sync.json"),
        "remote_state": "unknown_until_checked",
    }


def begin_task(locations, repository, branch, operation, agent, write):
    location = repository_state(locations, repository) / "activity.json"
    records = load(location, [])
    if not isinstance(records, list):
        records = []
    identifier = str(uuid.uuid4())
    records.append({"id": identifier, "branch": branch, "operation": operation, "agent": agent,
                    "started_at": datetime.now(timezone.utc).isoformat(), "status": "running"})
    write(location, records[-50:])
    return location, identifier


def finish_task(task, status, write):
    if not task:
        return
    location, identifier = task
    records = load(location, [])
    for record in records:
        if record.get("id") == identifier:
            record.update(status=status, ended_at=datetime.now(timezone.utc).isoformat())
    write(location, records)
