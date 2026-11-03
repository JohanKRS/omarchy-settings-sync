"""Apply and revert catalog parts that need no judgment.

Each part is recorded in a per-machine ledger with what the plugin wrote and
what was there before, so turning a feature off removes exactly that. Parts
of kind `agent`, conflicts and failures are returned for the agent to handle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tomllib

from core import private_write, read_json
from features import OMARCHY_PATH, expand, inside, part_enabled, xdg

COMMENTS = {".lua": ("--", ""), ".js": ("//", ""), ".mjs": ("//", ""), ".css": ("/*", " */"),
            ".qml": ("//", ""), ".jsonc": ("//", "")}
STATES = ("applied", "missing", "modified", "outdated")


def digest(value):
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


class Conflict(Exception):
    """The destination changed outside the plugin; the agent reconciles it."""


class Ledger:
    """What the plugin applied on this machine, per feature and part."""
    def __init__(self, path):
        self.path = Path(path)
        data = read_json(self.path, {})
        valid = isinstance(data, dict) and isinstance(data.get("features"), dict)
        self.data = data if valid else {"version": 1, "features": {}}

    def parts(self, feature_id):
        return self.data["features"].get(feature_id, {}).get("parts", {})

    def part(self, feature_id, key):
        return self.parts(feature_id).get(key)

    def set_part(self, feature_id, key, record):
        entry = self.data["features"].setdefault(feature_id, {"parts": {}})
        entry["parts"][key] = dict(record, date=now())

    def drop_part(self, feature_id, key):
        entry = self.data["features"].get(feature_id)
        if entry:
            entry["parts"].pop(key, None)
            if not entry["parts"]:
                self.data["features"].pop(feature_id)

    def applied(self, feature_id):
        return bool(self.parts(feature_id))

    def save(self):
        private_write(self.path, self.data)


@dataclass
class Outcome:
    feature: object
    action: str
    mode: str = "default"
    done: list = field(default_factory=list)
    delegated: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.delegated and not self.errors


def _style(dest, part):
    if part.data.get("comment"):
        return str(part.data["comment"]), ""
    return COMMENTS.get(Path(dest).suffix, ("#", ""))


def _read(path):
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return None


def _write(path, data, mode=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.settings-sync")
    if isinstance(data, bytes):
        temporary.write_bytes(data)
    else:
        temporary.write_text(data)
    if mode is not None:
        os.chmod(temporary, mode)
    elif path.exists():
        shutil.copymode(path, temporary)
    os.replace(temporary, path)


def _lookup(data, dotted):
    current = data
    for key in dotted.split("."):
        if not isinstance(current, dict) or key not in current:
            return False, None
        current = current[key]
    return True, current


def _assign(data, dotted, value):
    keys = dotted.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
        if not isinstance(data, dict):
            raise Conflict(f"{dotted} is not inside a JSON object")
    data[keys[-1]] = value


def _remove(data, dotted):
    keys = dotted.split(".")
    for key in keys[:-1]:
        data = data.get(key) if isinstance(data, dict) else None
    if isinstance(data, dict):
        data.pop(keys[-1], None)


def _literal(value, fmt):
    if isinstance(value, bool):
        return "true" if value else "false"
    if fmt == "toml":
        return json.dumps(value, ensure_ascii=False) if isinstance(value, str) else json.dumps(value)
    return str(value)


def _section(lines, section):
    """Return the [start, end) line range of an INI/TOML section; start is None if absent."""
    if not section:
        end = next((i for i, line in enumerate(lines) if re.match(r"\s*\[", line)), len(lines))
        return 0, end
    start = next((i for i, line in enumerate(lines) if line.strip() == f"[{section}]"), None)
    if start is None:
        return None, len(lines)
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"\s*\[", lines[i])), len(lines))
    return start + 1, end


def _ini_get(lines, section, key):
    start, end = _section(lines, section)
    if start is None:
        return None, None
    for index in range(start, end):
        match = re.match(rf"\s*{re.escape(key)}\s*=\s*(.*?)\s*$", lines[index])
        if match:
            return index, match.group(1)
    return None, None


def _ini_same(raw, value, fmt):
    if raw is None:
        return False
    if fmt == "toml":
        try:
            return tomllib.loads(f"x = {raw}")["x"] == value
        except ValueError:
            return False
    return raw == _literal(value, fmt)


def _ini_value(raw, fmt):
    if raw is None or fmt != "toml":
        return raw
    try:
        return tomllib.loads(f"x = {raw}")["x"]
    except ValueError:
        return raw


class Applier:
    def __init__(self, repository, ledger, backups, *, run=subprocess.run, home=None, environ=None,
                 omarchy=OMARCHY_PATH, script_dir=None, root="/"):
        self.repository = Path(repository)
        self.ledger = ledger
        self.backups = Path(backups)
        self.run = run
        self.home = Path(home or Path.home())
        self.environ = environ
        self.omarchy = Path(omarchy)
        self.root = Path(root)
        self.script_dir = Path(script_dir or self.backups.parent)
        self.admin = []
        self.changed = []
        self.stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Shared helpers --------------------------------------------------------
    def dest(self, part):
        path = expand(part.data["dest"], self.home, self.environ)
        if path.is_symlink():
            target = path.resolve()
            if not inside(target, self.home):
                raise Conflict(f"{path} is a link outside the home directory")
            path = target
        return path

    def write(self, path, data, mode=None):
        _write(path, data, mode)
        self.changed.append(Path(path))

    def unlink(self, path):
        Path(path).unlink(missing_ok=True)
        self.changed.append(Path(path))

    def system_dest(self, part):
        return self.root / Path(part.data["dest"]).relative_to("/")

    def source_path(self, part):
        return Path(part.base or self.repository) / part.data["source"]

    def source_bytes(self, part):
        return self.source_path(part).read_bytes()

    def omarchy_default(self, dest):
        config = xdg(self.home, self.environ)["XDG_CONFIG_HOME"]
        if inside(dest, config):
            candidate = self.omarchy / "config" / dest.relative_to(config)
            if candidate.is_file():
                return candidate
        return None

    def backup(self, feature, path):
        if not Path(path).is_file():
            return None
        target = self.backups / f"{self.stamp}-features" / feature.id / Path(path).name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(path, target)
        return str(target)

    def command(self, *args, timeout=60):
        try:
            result = self.run(list(args), capture_output=True, text=True, timeout=timeout)
            return result.returncode, (result.stdout or "") + (result.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as error:
            return 1, str(error)

    @staticmethod
    def settled(record, current, want):
        """Applied as-is, or a local variant the agent already reconciled."""
        return current == want or (record is not None and current == record.get("digest")
                                   and want == record.get("source"))

    def guard(self, record, current, want):
        """Decide whether writing `want` over `current` is safe."""
        if current is None:
            return
        if record is None:
            raise Conflict("exists with different content and was not applied by the plugin")
        if current != record.get("digest"):
            raise Conflict("changed locally since it was applied")
        if record.get("digest") != record.get("source"):
            raise Conflict("the repository changed a version that was adapted locally")

    # Whole files -----------------------------------------------------------
    def inspect_file(self, feature, part, record):
        dest = expand(part.data["dest"], self.home, self.environ)
        if not dest.exists():
            return "missing"
        current, want = digest(dest.read_bytes()), digest(self.source_bytes(part))
        if self.settled(record, current, want):
            return "applied"
        if record and current == record.get("digest"):
            return "outdated"
        return "modified"

    def apply_file(self, feature, part, record):
        dest, data = self.dest(part), self.source_bytes(part)
        want = digest(data)
        current = digest(dest.read_bytes()) if dest.exists() else None
        record = dict(record or {})
        if self.settled(record or None, current, want):
            record.setdefault("created", False)
            return dict(record, digest=current, source=want)
        self.guard(record or None, current, want)
        mode = int(str(part.data["mode"]), 8) if "mode" in part.data else (
            self.source_path(part).stat().st_mode & 0o777)
        self.write(dest, data, mode)
        return dict(record, digest=want, source=want, created=record.get("created", current is None))

    def revert_file(self, feature, part, record, mode):
        dest = self.dest(part)
        if not dest.exists():
            return
        current = digest(dest.read_bytes())
        if record and current != record.get("digest"):
            raise Conflict("changed locally since it was applied")
        default = self.omarchy_default(dest) if mode == "default" else None
        if default:
            self.write(dest, default.read_bytes())
        elif mode == "previous" and record and record.get("backup") and Path(record["backup"]).is_file():
            self.write(dest, Path(record["backup"]).read_bytes())
        elif mode == "previous" and record and not record.get("created"):
            return
        else:
            self.unlink(dest)

    # One line --------------------------------------------------------------
    def inspect_line(self, feature, part, record):
        text = _read(expand(part.data["dest"], self.home, self.environ)) or ""
        return "applied" if part.data["text"] in text.splitlines() else "missing"

    def apply_line(self, feature, part, record):
        dest = self.dest(part)
        text = _read(dest)
        record = dict(record or {}, created=(record or {}).get("created", text is None))
        if text is not None and part.data["text"] in text.splitlines():
            return record
        text = text or ""
        self.write(dest, text + ("" if not text or text.endswith("\n") else "\n") + part.data["text"] + "\n")
        return record

    def revert_line(self, feature, part, record, mode):
        dest = self.dest(part)
        text = _read(dest)
        if text is None:
            return
        lines = [line for line in text.splitlines() if line != part.data["text"]]
        if record and record.get("created") and not "".join(lines).strip():
            self.unlink(dest)
        else:
            self.write(dest, "\n".join(lines) + ("\n" if lines else ""))

    # Marked blocks ---------------------------------------------------------
    def block_content(self, part):
        text = self.source_bytes(part).decode() if "source" in part.data else str(part.data["text"])
        return text.rstrip("\n")

    def markers(self, feature, part, dest):
        prefix, suffix = _style(dest, part)
        name = f"{feature.id}/{part.data.get('id') or part.index + 1}"
        return (f"{prefix} >>> settings-sync {name} >>>{suffix}", f"{prefix} <<< settings-sync {name} <<<{suffix}")

    def find_block(self, feature, part, dest, text):
        start, end = self.markers(feature, part, dest)
        lines = text.splitlines()
        try:
            first = lines.index(start)
            last = lines.index(end, first + 1)
        except ValueError:
            return None
        return first, last, "\n".join(lines[first + 1:last])

    def inspect_block(self, feature, part, record):
        dest = expand(part.data["dest"], self.home, self.environ)
        text, want = _read(dest), self.block_content(part)
        if text is None:
            return "missing"
        found = self.find_block(feature, part, dest, text)
        if not found:
            return "applied" if want and want in text else "missing"
        current = digest(found[2])
        if self.settled(record, current, digest(want)):
            return "applied"
        return "outdated" if record and current == record.get("digest") else "modified"

    def apply_block(self, feature, part, record):
        dest = self.dest(part)
        text, want = _read(dest), self.block_content(part)
        start, end = self.markers(feature, part, dest)
        record = dict(record or {}, created=(record or {}).get("created", text is None))
        text = text or ""
        found = self.find_block(feature, part, dest, text)
        lines = text.splitlines()
        if found:
            current = digest(found[2])
            if self.settled(record if "digest" in record else None, current, digest(want)):
                return dict(record, digest=current, source=digest(want))
            self.guard(record if "digest" in record else None, current, digest(want))
            lines[found[0]:found[1] + 1] = [start, *want.splitlines(), end]
        elif want and want in text:
            # Adopt a block the agent appended before the catalog existed.
            index = text.index(want)
            text = text[:index] + start + "\n" + want + "\n" + end + text[index + len(want):]
            self.write(dest, text)
            return dict(record, digest=digest(want), source=digest(want))
        else:
            if lines and lines[-1].strip():
                lines.append("")
            lines += [start, *want.splitlines(), end]
        self.write(dest, "\n".join(lines) + "\n")
        return dict(record, digest=digest(want), source=digest(want))

    def revert_block(self, feature, part, record, mode):
        dest = self.dest(part)
        text = _read(dest)
        if text is None:
            return
        found = self.find_block(feature, part, dest, text)
        lines = text.splitlines()
        if found:
            if record and digest(found[2]) != record.get("digest"):
                raise Conflict("changed locally since it was applied")
            first, last = found[0], found[1] + 1
            if first > 0 and not lines[first - 1].strip():
                first -= 1
            del lines[first:last]
        else:
            want = self.block_content(part)
            if not want or want not in text:
                return
            lines = text.replace(want, "", 1).splitlines()
        if record and record.get("created") and not "".join(lines).strip():
            self.unlink(dest)
        else:
            self.write(dest, "\n".join(lines) + ("\n" if lines else ""))

    # Keys in JSON, INI and TOML files ---------------------------------------
    def key_format(self, part):
        if part.kind == "json":
            return "json"
        return part.data.get("format", "ini") if part.kind == "ini" else "ini"

    def key_values(self, part):
        return part.data["types"] if part.kind == "mime" else part.data["values"]

    def key_dest(self, part):
        if part.kind == "mime":
            return xdg(self.home, self.environ)["XDG_CONFIG_HOME"] / "mimeapps.list"
        return expand(part.data["dest"], self.home, self.environ)

    def key_section(self, part):
        return "Default Applications" if part.kind == "mime" else part.data.get("section", "")

    def read_keys(self, part, path):
        """Return a getter for current values, or raise Conflict for unreadable JSON."""
        text = _read(path)
        fmt = self.key_format(part)
        if fmt == "json":
            try:
                data = json.loads(text) if text else {}
            except ValueError as error:
                raise Conflict(f"{path} is not plain JSON: {error}") from error
            if not isinstance(data, dict):
                raise Conflict(f"{path} is not a JSON object")
            return data, lambda key: _lookup(data, key)
        lines = (text or "").splitlines()
        section = self.key_section(part)
        def get(key):
            index, raw = _ini_get(lines, section, key)
            return index is not None, _ini_value(raw, fmt)
        return lines, get

    def default_keys(self, part, dest):
        default = self.omarchy_default(dest)
        if not default:
            return lambda key: (False, None)
        return self.read_keys(part, default)[1]

    def write_keys(self, part, path, data, changes):
        """changes: {key: (exists, value)}; exists False deletes the key."""
        fmt = self.key_format(part)
        if fmt == "json":
            for key, (exists, value) in changes.items():
                if exists:
                    _assign(data, key, value)
                else:
                    _remove(data, key)
            self.write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            return
        lines, section = data, self.key_section(part)
        separator = " = " if fmt == "toml" else "="
        for key, (exists, value) in changes.items():
            index, _ = _ini_get(lines, section, key)
            if not exists:
                if index is not None:
                    del lines[index]
                continue
            line = f"{key}{separator}{_literal(value, fmt)}"
            if index is not None:
                lines[index] = line
                continue
            start, end = _section(lines, section)
            if start is None:
                if lines and lines[-1].strip():
                    lines.append("")
                lines += [f"[{section}]", line]
            else:
                while end > start and not lines[end - 1].strip():
                    end -= 1
                lines.insert(end, line)
        self.write(path, "\n".join(lines) + "\n")

    def same(self, part, current, value):
        exists, actual = current
        return exists and actual == value

    def inspect_keys(self, feature, part, record):
        dest = self.key_dest(part)
        try:
            _, get = self.read_keys(part, dest)
        except Conflict:
            return "modified"
        record = record or {}
        states = set()
        for key, value in self.key_values(part).items():
            current = get(key)
            mine = record.get("values", {}).get(key)
            if self.same(part, current, value) or (current[0] and current[1] == mine
                                                   and record.get("source", {}).get(key) == value):
                states.add("applied")
            elif not current[0]:
                states.add("missing")
            elif key in record.get("values", {}) and current[1] == mine:
                states.add("outdated")
            else:
                states.add("modified" if key in record.get("values", {}) else "missing")
        for state in ("modified", "outdated", "missing"):
            if state in states:
                return state
        return "applied"

    def apply_keys(self, feature, part, record):
        dest = self.dest(part) if part.kind != "mime" else self.key_dest(part)
        existed = dest.exists()
        data, get = self.read_keys(part, dest)
        record = dict(record or {})
        values, source = dict(record.get("values", {})), dict(record.get("source", {}))
        previous = dict(record.get("previous", {}))
        changes = {}
        for key, want in self.key_values(part).items():
            exists, current = get(key)
            if key not in previous:
                previous[key] = {"exists": exists, "value": current}
            if exists and (current == want or (current == values.get(key) and source.get(key) == want)):
                values[key], source[key] = current, want
                continue
            if exists and key in values and current != values[key]:
                raise Conflict(f"{key} changed locally since it was applied")
            if exists and key in values and values[key] != source.get(key):
                raise Conflict(f"{key} was adapted locally and the repository changed it")
            changes[key] = (True, want)
            values[key], source[key] = want, want
        if changes:
            self.write_keys(part, dest, data, changes)
        return dict(record, values=values, source=source, previous=previous,
                    created=record.get("created", not existed))

    def revert_keys(self, feature, part, record, mode):
        dest = self.dest(part) if part.kind != "mime" else self.key_dest(part)
        if not dest.exists():
            return
        data, get = self.read_keys(part, dest)
        record = record or {}
        defaults = self.default_keys(part, dest)
        changes = {}
        for key in self.key_values(part):
            exists, current = get(key)
            if key in record.get("values", {}) and exists and current != record["values"][key]:
                raise Conflict(f"{key} changed locally since it was applied")
            before = record.get("previous", {}).get(key, {"exists": False, "value": None})
            target = defaults(key) if mode == "default" else (False, None)
            if not target[0]:
                target = (bool(before.get("exists")), before.get("value"))
                if mode == "default" and before.get("value") == record.get("values", {}).get(key):
                    target = (False, None)  # Adopted values have no other known default.
            if (exists, current) != target:
                changes[key] = target
        if changes:
            self.write_keys(part, dest, data, changes)

    # User services ---------------------------------------------------------
    def enabled(self, unit):
        code, output = self.command("systemctl", "--user", "is-enabled", unit, timeout=15)
        return code == 0 and output.strip().splitlines()[:1] == ["enabled"]

    def inspect_user_service(self, feature, part, record):
        return "applied" if self.enabled(part.data["unit"]) or not part.data.get("enable", True) else "missing"

    def apply_user_service(self, feature, part, record):
        unit = part.data["unit"]
        record = dict(record or {})
        record.setdefault("was_enabled", self.enabled(unit))
        self.command("systemctl", "--user", "daemon-reload")
        if part.data.get("enable", True) and not self.enabled(unit):
            args = ["systemctl", "--user", "enable"] + (["--now"] if part.data.get("start", True) else []) + [unit]
            code, output = self.command(*args)
            if code:
                raise RuntimeError(output.strip() or f"systemctl failed for {unit}")
        return record

    def revert_user_service(self, feature, part, record, mode):
        if record and record.get("was_enabled"):
            return
        self.command("systemctl", "--user", "disable", "--now", part.data["unit"])

    # Administrator parts, run together under one pkexec prompt --------------
    def inspect_system_file(self, feature, part, record):
        dest = self.system_dest(part)
        try:
            current = digest(dest.read_bytes()) if dest.exists() else None
        except OSError:
            return "missing"
        if current is None:
            return "missing"
        want = digest(self.source_bytes(part))
        if self.settled(record, current, want):
            return "applied"
        return "outdated" if record and current == record.get("digest") else "modified"

    def apply_system_file(self, feature, part, record):
        dest, want = self.system_dest(part), digest(self.source_bytes(part))
        current = digest(dest.read_bytes()) if dest.exists() else None
        record = dict(record or {})
        if self.settled(record or None, current, want):
            record.setdefault("created", False)
            return dict(record, digest=current, source=want)
        self.guard(record or None, current, want)
        mode = str(part.data.get("mode", "0644")).rjust(4, "0")
        backup = record.get("backup") or (self.backup(feature, dest) if current else None)
        self.admin.append((feature, part, ["install", "-D", "-m", mode, str(self.source_path(part)), str(dest)]))
        return dict(record, digest=want, source=want, created=record.get("created", current is None), backup=backup)

    def revert_system_file(self, feature, part, record, mode):
        dest = self.system_dest(part)
        if not dest.exists():
            return
        if record and digest(dest.read_bytes()) != record.get("digest"):
            raise Conflict("changed locally since it was applied")
        if record and record.get("backup") and not record.get("created") and Path(record["backup"]).is_file():
            self.admin.append((feature, part, ["install", "-m", "0644", record["backup"], str(dest)]))
        elif not record or record.get("created"):
            self.admin.append((feature, part, ["rm", "-f", str(dest)]))
        else:
            raise Conflict("no backup of the previous system file")

    def installed(self, names):
        return {name: self.command("pacman", "-Q", name, timeout=15)[0] == 0 for name in names}

    def base_packages(self):
        try:
            text = (self.omarchy / "install/omarchy-base.packages").read_text()
        except OSError:
            return set()
        return {line.split("#", 1)[0].strip() for line in text.splitlines()} - {""}

    def inspect_package(self, feature, part, record):
        install, remove = part.data.get("install", []), part.data.get("remove", [])
        present = self.installed(install + remove)
        ok = all(present[name] for name in install) and not any(present[name] for name in remove)
        return "applied" if ok else "missing"

    def apply_package(self, feature, part, record):
        install, remove = part.data.get("install", []), part.data.get("remove", [])
        present = self.installed(install + remove)
        record = dict(record or {})
        before = dict(record.get("present_before", {}))
        for name, value in present.items():
            before.setdefault(name, value)
        missing = [name for name in install if not present[name]]
        extra = [name for name in remove if present[name]]
        if missing:
            self.admin.append((feature, part, ["pacman", "-S", "--needed", "--noconfirm", *missing]))
        if extra:
            # Never remove dependencies recursively; a failure goes to the agent.
            self.admin.append((feature, part, ["pacman", "-R", "--noconfirm", *extra]))
        return dict(record, present_before=before,
                    installed=sorted(set(record.get("installed", [])) | set(missing)),
                    removed=sorted(set(record.get("removed", [])) | set(extra)))

    def revert_package(self, feature, part, record, mode):
        record = record or {}
        before = record.get("present_before", {})
        base = self.base_packages() if mode == "default" else set()
        restore = [name for name in record.get("removed", []) if before.get(name) or name in base]
        drop = [name for name in record.get("installed", []) if not before.get(name) and name not in base]
        present = self.installed(restore + drop)
        restore = [name for name in restore if not present[name]]
        drop = [name for name in drop if present[name]]
        if restore:
            self.admin.append((feature, part, ["pacman", "-S", "--needed", "--noconfirm", *restore]))
        if drop:
            self.admin.append((feature, part, ["pacman", "-R", "--noconfirm", *drop]))

    def flush_admin(self):
        """Run every queued administrator step in one pkexec call; return failed steps."""
        steps, self.admin = self.admin, []
        if not steps:
            return []
        self.script_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        script = self.script_dir / "settings-sync-admin.sh"
        lines = ["#!/bin/sh", "set -u",
                 'step() { n="$1"; shift; if "$@"; then echo "settings-sync-ok $n"; '
                 'else echo "settings-sync-fail $n $?"; fi; }']
        lines += [f"step {index} " + shlex.join(args) for index, (_, _, args) in enumerate(steps)]
        script.write_text("\n".join(lines) + "\n")
        os.chmod(script, 0o700)
        code, output = self.command("pkexec", "/bin/sh", str(script), timeout=1800)
        script.unlink(missing_ok=True)
        succeeded = {int(n) for n in re.findall(r"^settings-sync-ok (\d+)$", output, re.M)}
        reason = output.strip()[-400:] or "administrator authorization was not granted"
        return [(feature, part, " ".join(args), reason) for index, (feature, part, args) in enumerate(steps)
                if index not in succeeded]

    # Dispatch --------------------------------------------------------------
    def handler(self, part, verb):
        name = {"json": "keys", "ini": "keys", "mime": "keys"}.get(part.kind, part.kind.replace("-", "_"))
        return getattr(self, f"{verb}_{name}")

    def inspect(self, feature):
        """Return {part key: state} for parts the plugin manages, plus agent records."""
        result = {}
        for part in feature.parts:
            record = self.ledger.part(feature.id, part.key)
            if part.agent:
                current = self.instructions_digest(part)
                result[part.key] = ("applied" if record and record.get("status") == "applied"
                                    and record.get("instructions") == current else "missing")
                continue
            try:
                result[part.key] = self.handler(part, "inspect")(feature, part, record)
            except (OSError, ValueError, Conflict):
                result[part.key] = "modified"
        return result

    def instructions_digest(self, part):
        reference = str(part.data["instructions"]).split("#", 1)[0]
        path = Path(part.base or self.repository) / reference
        if reference and not Path(reference).is_absolute() and ".." not in Path(reference).parts and path.is_file():
            return digest(path.read_bytes() + str(part.data["instructions"]).encode())
        return digest(str(part.data["instructions"]))

    def enable(self, feature, machine):
        outcome = Outcome(feature, "on")
        for part in feature.parts:
            if not part_enabled(feature, part, machine):
                if self.ledger.part(feature.id, part.key):
                    self.disable_part(feature, part, "default", outcome)
                continue
            record = self.ledger.part(feature.id, part.key)
            if part.agent:
                if not (record and record.get("status") == "applied"
                        and record.get("instructions") == self.instructions_digest(part)):
                    self.ledger.set_part(feature.id, part.key, {"status": "delegated", "kind": "agent"})
                    outcome.delegated.append({"part": part, "action": "on", "reason": "needs the agent"})
                continue
            try:
                updated = self.handler(part, "apply")(feature, part, record)
                self.ledger.set_part(feature.id, part.key, dict(updated, kind=part.kind, status="applied"))
                outcome.done.append(part.title)
            except Conflict as error:
                outcome.delegated.append({"part": part, "action": "on", "reason": f"conflict: {error}"})
            except (OSError, RuntimeError, ValueError, UnicodeDecodeError) as error:
                outcome.delegated.append({"part": part, "action": "on", "reason": f"failed: {error}"})
        return outcome

    def disable_part(self, feature, part, mode, outcome):
        record = self.ledger.part(feature.id, part.key)
        if mode == "keep":
            self.ledger.drop_part(feature.id, part.key)
            return
        if part.agent:
            if record and record.get("status") in ("applied", "delegated"):
                outcome.delegated.append({"part": part, "action": "off", "reason": "needs the agent"})
            else:
                self.ledger.drop_part(feature.id, part.key)
            return
        try:
            self.handler(part, "revert")(feature, part, record, mode)
            if not part.admin:
                self.ledger.drop_part(feature.id, part.key)
            outcome.done.append(part.title)
        except Conflict as error:
            outcome.delegated.append({"part": part, "action": "off", "reason": f"conflict: {error}"})
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError) as error:
            outcome.delegated.append({"part": part, "action": "off", "reason": f"failed: {error}"})

    def disable(self, feature, mode="default"):
        outcome = Outcome(feature, "off", mode)
        for part in reversed(feature.parts):
            self.disable_part(feature, part, mode, outcome)
        return outcome

    def finish(self, outcomes):
        """Run administrator steps and reloads after every feature was processed."""
        failed = self.flush_admin()
        by_feature = {outcome.feature.id: outcome for outcome in outcomes}
        failed_keys = set()
        for feature, part, step, reason in failed:
            failed_keys.add((feature.id, part.key))
            outcome = by_feature.get(feature.id)
            if outcome:
                outcome.delegated.append({"part": part, "action": outcome.action, "reason": f"failed: {step}: {reason}"})
                record = self.ledger.part(feature.id, part.key)
                if record and outcome.action == "on":
                    self.ledger.set_part(feature.id, part.key, dict(record, status="failed", note=reason[:500]))
        for outcome in outcomes:
            for part in outcome.feature.parts:
                if not part.admin or (outcome.feature.id, part.key) in failed_keys:
                    continue
                if outcome.action == "off":
                    self.ledger.drop_part(outcome.feature.id, part.key)
        hypr = xdg(self.home, self.environ)["XDG_CONFIG_HOME"] / "hypr"
        touched_hypr = any(inside(path, hypr) for path in self.changed)
        if touched_hypr or any("hyprland" in o.feature.reload and o.done for o in outcomes):
            self.command("hyprctl", "reload", timeout=20)
            code, output = self.command("hyprctl", "configerrors", timeout=20)
            errors = output.strip()
            if code == 0 and errors and errors.lower() not in ("no errors", "ok"):
                touched = [o for o in outcomes if o.done] or outcomes
                for outcome in touched:
                    outcome.errors.append(f"Hyprland reported configuration errors: {errors[:400]}")
        self.ledger.data["updated"] = now()
        self.ledger.save()
        return outcomes

    def merge_agent_results(self, path, features):
        """Record what the agent reported for delegated parts, then remove the report."""
        report = read_json(path, {})
        if not isinstance(report, dict) or not isinstance(report.get("features"), dict):
            return False
        by_id = {feature.id: feature for feature in features}
        for feature_id, parts in report["features"].items():
            feature = by_id.get(feature_id)
            if not feature or not isinstance(parts, dict):
                continue
            for part in feature.parts:
                result = parts.get(part.key)
                if not isinstance(result, dict):
                    continue
                status = result.get("status")
                if status == "reverted":
                    self.ledger.drop_part(feature_id, part.key)
                elif status == "applied" and part.agent:
                    self.ledger.set_part(feature_id, part.key, {
                        "kind": "agent", "status": "applied", "note": str(result.get("note", ""))[:500],
                        "instructions": self.instructions_digest(part)})
                elif status == "applied":
                    self.adopt(feature, part)
                elif status == "failed":
                    record = dict(self.ledger.part(feature_id, part.key) or {"kind": part.kind})
                    self.ledger.set_part(feature_id, part.key, dict(record, status="failed",
                                                                    note=str(result.get("note", ""))[:500]))
        self.ledger.save()
        Path(path).unlink(missing_ok=True)
        return True

    def adopt(self, feature, part):
        """Accept the destination as reconciled by the agent, even if it differs from the source."""
        record = dict(self.ledger.part(feature.id, part.key) or {}, kind=part.kind, status="applied")
        try:
            if part.kind in ("file", "system-file"):
                dest = self.system_dest(part) if part.admin else expand(part.data["dest"], self.home, self.environ)
                record.update(digest=digest(dest.read_bytes()), source=digest(self.source_bytes(part)))
            elif part.kind == "block":
                dest = expand(part.data["dest"], self.home, self.environ)
                found = self.find_block(feature, part, dest, _read(dest) or "")
                want = digest(self.block_content(part))
                record.update(digest=digest(found[2]) if found else want, source=want)
            elif part.kind in ("json", "ini", "mime"):
                _, get = self.read_keys(part, self.key_dest(part))
                values = self.key_values(part)
                record.update(values={key: get(key)[1] for key in values}, source=dict(values))
        except (OSError, ValueError, Conflict, UnicodeDecodeError):
            pass
        self.ledger.set_part(feature.id, part.key, record)


def status(feature, choice, mode, ledger, states, failing=None):
    """One label per feature for the panel."""
    if failing:
        return "unavailable"
    if choice == "new":
        return "new"
    records = ledger.parts(feature.id)
    if choice == "off":
        return "off" if not records or mode == "keep" else "pending"
    if any(record.get("status") in ("delegated", "failed") for record in records.values()):
        return "pending"
    values = set(states.values())
    if "modified" in values:
        return "modified"
    if values & {"missing", "outdated"}:
        return "pending"
    return "applied"


def delegation(outcomes, results_path, *, machine, catalog_errors=()):
    """Describe the work left for the agent, in the same style as the other plugin requests."""
    lines = [
        "APLICAR CONFIGURAÇÕES DO CATÁLOGO. O plugin já aplicou ou reverteu as partes simples; "
        "faça somente o que está listado abaixo, nesta máquina.",
        f"Máquina: {machine}. Catálogo: features.toml na raiz do repositório de configurações.",
        "Ações: 'on' aplica a parte; 'off' remove a parte. Em 'off' com modo 'default', volte ao "
        "padrão do Omarchy (/usr/share/omarchy/config, default ou install/omarchy-base.packages) ou, "
        "sem padrão, ao padrão do próprio aplicativo; 'previous' restaura o estado anterior pelo backup. "
        "Em conflitos, compare o destino, o arquivo do repositório e o registro do plugin; preserve "
        "alterações locais e pergunte quando não houver uma escolha segura.",
        "",
    ]
    for outcome in outcomes:
        for item in outcome.delegated:
            part = item["part"]
            details = {key: value for key, value in part.data.items() if key != "kind"}
            lines.append(f"- {outcome.feature.id} ({outcome.feature.title}) · parte '{part.key}' · tipo {part.kind} "
                         f"· ação {item['action']}" + (f" · modo {outcome.mode}" if item["action"] == "off" else "")
                         + f" · motivo: {item['reason']}")
            lines.append(f"  dados: {json.dumps(details, ensure_ascii=False)}")
        for error in outcome.errors:
            lines.append(f"- {outcome.feature.id}: {error}")
    if catalog_errors:
        lines += ["", "Problemas no catálogo para corrigir no repositório:"] + [f"- {error}" for error in catalog_errors]
    lines += [
        "",
        f"Ao terminar, grave o resultado em {results_path} como JSON: "
        '{"features": {"<id>": {"<parte>": {"status": "applied|reverted|failed|skipped", "note": "..."}}}}. '
        "Use 'applied' só depois de validar. O plugin lê esse arquivo e atualiza os interruptores.",
    ]
    return "\n".join(lines)
