"""Keep the installed plugin on the latest GitHub release.

Omarchy installs plugins as git checkouts and `omarchy plugin update`
follows the default branch. This module checks the latest published
release instead and fast-forwards the checkout to its tag, so commits that
were never released are not installed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request

from core import ROOT, private_write, read_json

API = "https://api.github.com/repos/JohanKRS/omarchy-settings-sync/releases/latest"
INTERVAL = 24 * 3600
TAG = re.compile(r"v?(\d+(?:\.\d+)*)")


def version_key(value):
    match = TAG.fullmatch(str(value or "").strip())
    return tuple(int(n) for n in match.group(1).split(".")) if match else ()


def installed_version(root=ROOT):
    """The version on disk, which is newer than the running code after an update."""
    return str(read_json(Path(root) / "manifest.json", {}).get("version", ""))


def latest_release(opener=urllib.request.urlopen):
    request = urllib.request.Request(API, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "omarchy-settings-sync"})
    with opener(request, timeout=10) as response:
        data = json.loads(response.read().decode())
    tag = str(data.get("tag_name", ""))
    if not version_key(tag) or data.get("draft") or data.get("prerelease"):
        raise ValueError("no published release")
    return {"tag": tag, "version": tag.lstrip("v"), "url": str(data.get("html_url", "")),
            "notes": str(data.get("body") or "")[:4000]}


def git(root, *args, run=subprocess.run, timeout=60):
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        result = run(["git", "-C", str(root), *args], capture_output=True, text=True,
                     timeout=timeout, env=environment)
        return result.returncode, (result.stdout or "").strip() or (result.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)


def checkout_state(root=ROOT, run=subprocess.run):
    """Whether the installed copy can be updated automatically, and why not."""
    if not (Path(root) / ".git").exists():
        return "not-git"
    code, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD", run=run, timeout=10)
    code_default, default = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", run=run, timeout=10)
    default = default.split("/", 1)[1] if code_default == 0 and "/" in default else "main"
    if code or branch != default:
        return "branch"
    code, changes = git(root, "status", "--porcelain", "--untracked-files=no", run=run, timeout=10)
    if code or changes:
        return "modified"
    return "ready"


def update_to(tag, root=ROOT, run=subprocess.run):
    """Fast-forward the installed checkout to a release tag. Returns a problem or None."""
    state = checkout_state(root, run)
    if state != "ready":
        return state
    code, output = git(root, "fetch", "--quiet", "origin", f"refs/tags/{tag}:refs/tags/{tag}", run=run, timeout=120)
    if code:
        return output or "git fetch failed"
    code, output = git(root, "merge", "--ff-only", "--quiet", tag, run=run)
    return (output or "the installed copy cannot fast-forward") if code else None


class Updater:
    """Daily check; installs only when the panel is idle and the copy is a clean default-branch checkout."""
    def __init__(self, state_path, *, root=ROOT, run=subprocess.run, fetch=latest_release, clock=time.time):
        self.path = Path(state_path)
        self.root = Path(root)
        self.run = run
        self.fetch = fetch
        self.clock = clock
        self.state = read_json(self.path, {})
        if not isinstance(self.state, dict):
            self.state = {}

    def save(self):
        private_write(self.path, self.state)

    def due(self):
        return self.clock() - float(self.state.get("checked", 0)) >= INTERVAL

    def available(self):
        latest = self.state.get("latest") or {}
        return latest if version_key(latest.get("tag")) > version_key(installed_version(self.root)) else None

    def check(self, *, install=False):
        """Ask GitHub for the latest release; install it when allowed. Runs in a worker thread."""
        self.state["checked"] = self.clock()
        try:
            self.state["latest"] = self.fetch()
            self.state.pop("error", None)
        except (OSError, ValueError) as error:
            self.state["error"] = str(error)[:300]
            self.save()
            return self.state
        release = self.available()
        if release and install:
            problem = update_to(release["tag"], self.root, self.run)
            if problem:
                self.state["blocked"] = problem
            else:
                self.state.pop("blocked", None)
                self.state["installed"] = release["tag"]
        self.save()
        return self.state
