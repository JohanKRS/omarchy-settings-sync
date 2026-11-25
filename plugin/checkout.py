"""The working copy shared by the plugin and the agent.

The plugin only clones, fast-forwards, exports clean copies of the repository
for the list, and publishes its own machine file. Anything that needs a merge
decision is left to the agent.
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

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


def update(workspace, repository, branch="", run=subprocess.run, *, fetch=True, fast_forward=True):
    """Clone, fetch and fast-forward. Returns (path, sha, problem); problem is text or None.

    With `fast_forward` off the working copy stays as it is, for while the
    agent works in it: `compare` and `export` then tell what the repository has.
    """
    path = location(workspace, repository, run)
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        args = ["clone", *(["--branch", branch] if branch else []), repository, str(path)]
        code, output = git(path.parent, *args, run=run, timeout=300)
        if code:
            return path, "", output or "git clone failed"
        return path, head(path, run), None
    if fetch:
        code, output = git(path, "fetch", "origin", run=run)
        if code:
            return path, head(path, run), output or "git fetch failed"
    problem = catch_up(path, branch, run) if fast_forward else None
    return path, head(path, run), problem


def catch_up(path, branch="", run=subprocess.run):
    """Fast-forward the working copy to what was last fetched. Returns a problem or None."""
    target = branch or default_branch(path, run)
    remote = remote_head(path, branch, run)
    if not remote or remote == head(path, run):
        return None
    _, current = git(path, "rev-parse", "--abbrev-ref", "HEAD", run=run, timeout=10)
    if current != target:
        return f"the working copy is on {current}, not {target}"
    code, output = git(path, "merge", "--ff-only", f"origin/{target}", run=run)
    if code:
        return output or "the working copy cannot fast-forward"
    return None


def remote_head(path, branch="", run=subprocess.run):
    """The commit of the configured branch as last fetched, or ""."""
    target = branch or default_branch(path, run)
    code, output = git(path, "rev-parse", "--verify", "-q", f"origin/{target}^{{commit}}", run=run, timeout=10)
    return output.splitlines()[0] if code == 0 and output else ""


def compare(path, branch="", run=subprocess.run):
    """(remote sha, local commits not in it, its commits not here) for the configured branch."""
    remote = remote_head(path, branch, run)
    if not remote:
        return "", 0, 0
    code, output = git(path, "rev-list", "--left-right", "--count", f"HEAD...{remote}", run=run, timeout=10)
    try:
        ahead, behind = (int(value) for value in output.split()[:2]) if code == 0 else (0, 0)
    except ValueError:
        ahead, behind = 0, 0
    return remote, ahead, behind


def changed(path, run=subprocess.run):
    """Files with local changes, tracked or new, in the working copy."""
    names = []
    for args in (("diff", "--name-only", "HEAD"), ("ls-files", "--others", "--exclude-standard")):
        code, output = git(path, *args, run=run, timeout=30)
        if code == 0:
            names += [name for name in output.splitlines() if name and name not in names]
    return names


def last_change(path, ref, run=subprocess.run):
    """When `ref` was committed, as a Unix time, or None."""
    code, output = git(path, "log", "-1", "--format=%ct", ref, run=run, timeout=10)
    try:
        return int(output.splitlines()[0]) if code == 0 and output else None
    except ValueError:
        return None


def export(path, ref, destination, run=subprocess.run):
    """Write a clean copy of `ref` to `destination` without touching the working copy.

    The list of customizations reads this copy while the agent works in the
    working copy, or when the working copy cannot fast-forward. Returns a
    problem or None. An export of the same commit is reused.
    """
    destination = Path(destination)
    stamp = destination.with_name(destination.name + ".commit")
    try:
        if destination.is_dir() and stamp.read_text().strip() == ref:
            return None
    except OSError:
        pass
    try:
        result = run(["git", "-C", str(path), "archive", "--format=tar", ref], capture_output=True, timeout=120,
                     env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)
    if result.returncode:
        return (result.stderr or b"").decode(errors="replace").strip() or "git archive failed"
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".export-", dir=destination.parent))
    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
            # Only plain files and folders inside the copy: a catalog never needs links.
            members = [member for member in archive.getmembers()
                       if (member.isfile() or member.isdir()) and not Path(member.name).is_absolute()
                       and ".." not in Path(member.name).parts]
            options = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            archive.extractall(staging, members=members, **options)
        old = None
        if destination.exists():
            old = destination.with_name(f".{destination.name}.old")
            shutil.rmtree(old, ignore_errors=True)
            destination.rename(old)
        staging.rename(destination)
        if old:
            shutil.rmtree(old, ignore_errors=True)
        stamp.write_text(ref + "\n")
    except (OSError, tarfile.TarError) as error:
        shutil.rmtree(staging, ignore_errors=True)
        return str(error)
    return None


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
