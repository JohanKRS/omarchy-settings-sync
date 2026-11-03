"""The working copy shared by the plugin and the agent.

The plugin only clones, fast-forwards and publishes its own machine file.
Anything that needs a merge decision is left to the agent.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

from context import identity


def git(path, *args, run=subprocess.run, timeout=120):
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="true")
    try:
        result = run(["git", "-C", str(path), *args], capture_output=True, text=True,
                     timeout=timeout, env=environment)
        return result.returncode, (result.stdout or "").strip() + ("\n" + result.stderr.strip() if result.stderr else "")
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)


def location(workspace, repository, run=subprocess.run):
    """Reuse workspace/repository when it tracks this remote, as the agent does."""
    shared = Path(workspace) / "repository"
    if not (shared / ".git").exists():
        return shared
    code, remote = git(shared, "remote", "get-url", "origin", run=run, timeout=10)
    if code == 0 and identity(remote.splitlines()[0]) == identity(repository):
        return shared
    key = hashlib.sha256(identity(repository).encode()).hexdigest()[:12]
    return Path(workspace) / "repositories" / key


def default_branch(path, run=subprocess.run):
    code, output = git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", run=run, timeout=10)
    return output.splitlines()[0].split("/", 1)[1] if code == 0 and "/" in output else "main"


def update(workspace, repository, branch="", run=subprocess.run):
    """Clone or fast-forward. Returns (path, sha, problem); problem is text or None."""
    path = location(workspace, repository, run)
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        args = ["clone", *(["--branch", branch] if branch else []), repository, str(path)]
        code, output = git(path.parent, *args, run=run, timeout=300)
        if code:
            return path, "", output or "git clone failed"
    else:
        code, output = git(path, "fetch", "origin", run=run)
        if code:
            return path, head(path, run), output or "git fetch failed"
        target = branch or default_branch(path, run)
        _, current = git(path, "rev-parse", "--abbrev-ref", "HEAD", run=run, timeout=10)
        if current != target:
            return path, head(path, run), f"the working copy is on {current}, not {target}"
        code, output = git(path, "merge", "--ff-only", f"origin/{target}", run=run)
        if code:
            return path, head(path, run), output or "the working copy cannot fast-forward"
    return path, head(path, run), None


def head(path, run=subprocess.run):
    code, output = git(path, "rev-parse", "HEAD", run=run, timeout=10)
    return output.splitlines()[0] if code == 0 and output else ""


def publish(path, branch, files, message, run=subprocess.run):
    """Commit only `files` and push them alone. Returns a problem description or None.

    Other local commits are never pushed: if the working copy is ahead of the
    remote, or the push is rejected, the files stay changed but uncommitted.
    """
    target = branch or default_branch(path, run)
    relative = [str(Path(f).relative_to(path)) for f in files]
    git(path, "fetch", "origin", run=run)
    code, ahead = git(path, "rev-list", "--count", f"origin/{target}..HEAD", run=run, timeout=10)
    if code or ahead.splitlines()[:1] != ["0"]:
        return f"the working copy has commits that are not on origin/{target}"
    code, output = git(path, "merge", "--ff-only", f"origin/{target}", run=run)
    if code:
        return output or "the working copy cannot fast-forward"
    code, output = git(path, "add", "--", *relative, run=run, timeout=30)
    if code:
        return output
    code, _ = git(path, "diff", "--cached", "--quiet", "--", *relative, run=run, timeout=30)
    if code == 0:
        return None
    code, output = git(path, "commit", "-m", message, "--", *relative, run=run, timeout=60)
    if code:
        git(path, "reset", "-q", "--", *relative, run=run, timeout=30)
        return output
    code, output = git(path, "push", "origin", f"HEAD:{target}", run=run)
    if code:
        git(path, "reset", "-q", "--soft", "HEAD~1", run=run, timeout=30)
        git(path, "reset", "-q", "--", *relative, run=run, timeout=30)
        return output or "git push failed"
    return None
