"""Settings catalog: each feature is a user-visible setting with typed parts.

The configuration repository lists features in features.toml; each machine
stores its own on/off choices under machines/. This module reads and checks
both. It never writes to a destination; see applier.py for that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tomllib

CATALOG = "features.toml"
MACHINES = "machines"
LOCAL_KINDS = {"file", "line", "block", "json", "ini", "mime", "user-service"}
ADMIN_KINDS = {"system-file", "package"}
KINDS = LOCAL_KINDS | ADMIN_KINDS | {"agent"}
DEFAULTS = {"on", "off", "ask"}
OFF_MODES = ("default", "previous", "keep")
GROUPS = ("desktop", "apps", "system")  # Fallback grouping when a feature names no app.
RELOADS = {"hyprland"}
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
PACKAGE = re.compile(r"[a-z0-9@._+-]+")
SYSTEM_ROOTS = ("/etc/", "/usr/lib/", "/usr/local/", "/opt/")
OMARCHY_PATH = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy"))
REQUIRED = {
    "file": ("source", "dest"), "line": ("dest", "text"), "block": ("dest",),
    "json": ("dest", "values"), "ini": ("dest", "section", "values"), "mime": ("types",),
    "user-service": ("unit",), "system-file": ("source", "dest"), "package": (),
    "agent": ("title", "instructions"),
}


def xdg(home=None, environ=None):
    env = os.environ if environ is None else environ
    home = Path(home or Path.home())
    return {
        "HOME": home,
        "XDG_CONFIG_HOME": Path(env.get("XDG_CONFIG_HOME") or home / ".config"),
        "XDG_DATA_HOME": Path(env.get("XDG_DATA_HOME") or home / ".local/share"),
        "XDG_STATE_HOME": Path(env.get("XDG_STATE_HOME") or home / ".local/state"),
    }


def expand(value, home=None, environ=None):
    """Expand ~ and the XDG variables used in SYNC.md, and nothing else."""
    places = xdg(home, environ)
    def variable(match):
        name = match.group(1) or match.group(3)
        if name not in places:
            raise ValueError(f"Unsupported variable: {name}")
        return str(places[name])
    text = re.sub(r"\$\{([A-Z_]+)(:-[^}]*)?\}|\$([A-Z_]+)", variable, str(value))
    if text == "~" or text.startswith("~/"):
        text = str(places["HOME"]) + text[1:]
    return Path(os.path.normpath(text))


def inside(path, root):
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


@dataclass
class Part:
    kind: str
    data: dict
    index: int
    base: object = None  # Directory that `source` is relative to.

    @property
    def key(self):
        if self.data.get("id"):
            return str(self.data["id"])
        target = self.data.get("dest") or self.data.get("unit") or ",".join(
            self.data.get("install", []) + self.data.get("remove", [])) or self.data.get("title", "")
        section = self.data.get("section")
        return f"{self.kind}:{target}" + (f"[{section}]" if section else "")

    @property
    def optional(self):
        return bool(self.data.get("optional"))

    @property
    def title(self):
        return str(self.data.get("title") or self.data.get("dest") or self.data.get("unit") or self.kind)

    @property
    def admin(self):
        return self.kind in ADMIN_KINDS

    @property
    def agent(self):
        return self.kind == "agent"


@dataclass
class Feature:
    id: str
    title: str
    summary: str = ""
    group: str = "apps"
    areas: list = field(default_factory=list)
    default: str = "on"
    when: list = field(default_factory=list)
    requires: list = field(default_factory=list)
    reload: list = field(default_factory=list)
    parts: list = field(default_factory=list)
    local: bool = False
    app: str = ""
    icon: str = ""
    program: str = ""  # "install" or "remove" for entries of the programs list

    @property
    def needs_agent(self):
        return any(part.agent for part in self.parts)

    @property
    def needs_admin(self):
        return any(part.admin for part in self.parts)


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def check_part(feature_id, index, data, repository, errors):
    where = f"{feature_id} part {index + 1}"
    kind = data.get("kind")
    if kind not in KINDS:
        errors.append(f"{where}: unknown kind {kind!r}")
        return None
    for name in REQUIRED[kind]:
        if name not in data:
            errors.append(f"{where}: missing {name}")
            return None
    if kind == "block" and ("source" in data) == ("text" in data):
        errors.append(f"{where}: a block needs exactly one of source or text")
        return None
    if data.get("optional") and not IDENTIFIER.fullmatch(str(data.get("id", ""))):
        errors.append(f"{where}: an optional part needs an id")
        return None
    if "source" in data:
        source = str(data["source"])
        path = Path(repository) / source
        if (Path(source).is_absolute() or ".." in Path(source).parts or path.is_symlink()
                or not path.is_file() or not inside(path.resolve(), Path(repository).resolve())):
            errors.append(f"{where}: source {source!r} must be a file inside the repository")
            return None
    if "dest" in data:
        try:
            dest = expand(data["dest"])
        except ValueError as error:
            errors.append(f"{where}: {error}")
            return None
        if kind == "system-file":
            if (not str(data["dest"]).startswith(SYSTEM_ROOTS) or dest != Path(data["dest"])
                    or inside(dest, OMARCHY_PATH)):
                errors.append(f"{where}: system files go under /etc, /usr/lib, /usr/local or /opt")
                return None
        elif not inside(dest, Path.home()) or dest == Path.home():
            errors.append(f"{where}: {data['dest']!r} must stay inside the home directory")
            return None
    for name in ("values", "types"):
        if name in data and (not isinstance(data[name], dict) or not data[name]):
            errors.append(f"{where}: {name} must be a non-empty table")
            return None
    if kind == "mime" and not all(str(app).endswith(".desktop") for app in data["types"].values()):
        errors.append(f"{where}: MIME defaults must name .desktop files")
        return None
    if kind == "ini" and data.get("format", "ini") not in ("ini", "toml"):
        errors.append(f"{where}: format must be ini or toml")
        return None
    if kind == "package":
        names = data.get("install", []) + data.get("remove", [])
        if not names or not _strings(names) or not all(PACKAGE.fullmatch(name) for name in names):
            errors.append(f"{where}: install/remove must list package names")
            return None
    if kind == "user-service" and not re.fullmatch(r"[A-Za-z0-9@._-]+\.(service|timer|socket|path)", str(data["unit"])):
        errors.append(f"{where}: invalid unit name")
        return None
    if "mode" in data and not re.fullmatch(r"0?[0-7]{3}", str(data["mode"])):
        errors.append(f"{where}: mode must be octal, such as 0644")
        return None
    return Part(kind, dict(data), index, Path(repository))


def parse(text, repository, *, local=False, errors=None):
    errors = [] if errors is None else errors
    try:
        document = tomllib.loads(text)
    except ValueError as error:
        errors.append(f"{CATALOG}: {error}")
        return []
    if document.get("version", 1) != 1:
        errors.append(f"{CATALOG}: unsupported version {document.get('version')!r}")
        return []
    features = []
    for entry in document.get("feature", []):
        identifier = str(entry.get("id", ""))
        if not IDENTIFIER.fullmatch(identifier):
            errors.append(f"Invalid feature id {identifier!r}")
            continue
        if not entry.get("title"):
            errors.append(f"{identifier}: missing title")
            continue
        if entry.get("default", "on") not in DEFAULTS:
            errors.append(f"{identifier}: default must be on, off or ask")
            continue
        lists = {name: entry.get(name, []) for name in ("areas", "when", "requires", "reload")}
        if not all(_strings(value) for value in lists.values()):
            errors.append(f"{identifier}: areas, when, requires and reload must be lists of text")
            continue
        if set(lists["reload"]) - RELOADS:
            errors.append(f"{identifier}: reload supports only {sorted(RELOADS)}")
            continue
        count = len(errors)
        parts = [check_part(identifier, index, data, repository, errors)
                 for index, data in enumerate(entry.get("part", []))]
        if len(errors) > count:
            continue
        if not parts:
            errors.append(f"{identifier}: a feature needs at least one part")
            continue
        keys = [part.key for part in parts]
        if len(set(keys)) != len(keys):
            errors.append(f"{identifier}: two parts have the same target; give them ids")
            continue
        group = entry.get("group") if entry.get("group") in GROUPS else "apps"
        # System-wide settings without an app stay together under System.
        app = str(entry.get("app") or (lists["areas"][0] if lists["areas"] and group != "system" else ""))
        if app and not IDENTIFIER.fullmatch(app):
            errors.append(f"{identifier}: app must be a short lowercase name, such as firefox")
            continue
        features.append(Feature(
            id=identifier, title=str(entry["title"]), summary=str(entry.get("summary", "")),
            group=group, default=entry.get("default", "on"), parts=parts, local=local, app=app,
            icon=str(entry.get("icon", "")), **lists))
    for entry in document.get("program", []):
        program = parse_program(entry, errors, local)
        if program:
            features.append(program)
    return features


def parse_program(entry, errors, local=False):
    """A program to install or remove on each machine, without a full feature entry."""
    package = str(entry.get("package", ""))
    action = entry.get("action", "install")
    packages = entry.get("packages", [package])
    identifier = str(entry.get("id") or f"program-{package}")
    if not PACKAGE.fullmatch(package) or not _strings(packages) or not all(PACKAGE.fullmatch(p) for p in packages):
        errors.append(f"Invalid program package {package!r}")
        return None
    if not IDENTIFIER.fullmatch(identifier):
        errors.append(f"{package}: invalid id {identifier!r}")
        return None
    if action not in ("install", "remove"):
        errors.append(f"{package}: action must be install or remove")
        return None
    if entry.get("default", "ask") not in DEFAULTS or not _strings(entry.get("when", [])):
        errors.append(f"{package}: invalid default or when")
        return None
    if action == "install" and (entry.get("aur") or entry.get("instructions")):
        # AUR helpers and direct downloads need the user's prompts and checks; the agent installs these.
        data = {"kind": "agent", "id": "package", "title": entry.get("title") or package,
                "instructions": str(entry.get("instructions")
                                    or f"Install the AUR package {package} with `omarchy pkg aur add {package}`.")}
    else:
        data = {"kind": "package", "id": "packages", ("install" if action == "install" else "remove"): list(packages)}
    return Feature(id=identifier, title=str(entry.get("title") or package),
                   summary=str(entry.get("summary", "")), group="programs", default=entry.get("default", "ask"),
                   when=list(entry.get("when", [])), parts=[Part(data["kind"], data, 0)], local=local,
                   icon=str(entry.get("icon") or package), program=action)


def load_catalog(repository, local_catalog=None):
    """Return (features, errors). A missing catalog is not an error."""
    errors, features = [], []
    path = Path(repository) / CATALOG if repository else None
    if path and path.is_file():
        features = parse(path.read_text(), repository, errors=errors)
    if local_catalog and Path(local_catalog).is_file():
        # Settings saved with publishing off stay on this machine only.
        features += parse(Path(local_catalog).read_text(), Path(local_catalog).parent, local=True, errors=errors)
    seen = set()
    for feature in list(features):
        if feature.id in seen:
            errors.append(f"Duplicate feature id {feature.id!r}")
            features.remove(feature)
        seen.add(feature.id)
    ids = {feature.id for feature in features}
    for feature in features:
        for required in feature.requires:
            if required not in ids:
                errors.append(f"{feature.id}: requires unknown feature {required!r}")
    return features, errors


def has_catalog(repository):
    return bool(repository) and (Path(repository) / CATALOG).is_file()


def _writes(feature):
    """What each part of a feature claims at its destination, as comparable keys."""
    for part in feature.parts:
        data, dest = part.data, str(part.data.get("dest", ""))
        if part.kind in ("file", "system-file"):
            yield (dest,), dest
        elif part.kind == "line":
            yield (dest, "line", data["text"]), f"{dest}: {data['text']}"
        elif part.kind == "block":
            yield (dest, "block", data.get("source") or data.get("text")), f"{dest}: {part.title}"
        elif part.kind == "json":
            for key in data["values"]:
                yield (dest, key), f"{dest}: {key}"
        elif part.kind == "ini":
            for key in data["values"]:
                yield (dest, data["section"], key), f"{dest} [{data['section']}] {key}"
        elif part.kind == "mime":
            for kind in data["types"]:
                yield ("mime", kind), f"MIME {kind}"
        elif part.kind == "user-service":
            yield ("unit", data["unit"]), data["unit"]


def overlaps(features):
    """Features that write the same file, line or key: one setting split across two switches."""
    owners, problems = {}, []
    for feature in features:
        for key, label in _writes(feature):
            other = owners.setdefault(key, feature.id)
            if other != feature.id:
                problems.append(f"{feature.id} and {other} both change {label}; keep a single feature "
                                f"(add the new parts to {other}) instead of two switches")
    return sorted(set(problems))


def saved_list(features, limit=150):
    """One line per saved customization, so a request can extend it instead of adding a twin."""
    lines = []
    for feature in features[:limit]:
        if feature.program:
            names = [name for part in feature.parts for name in part.data.get("install", []) + part.data.get("remove", [])]
            where = f"programa: {'instalar' if feature.program == 'install' else 'remover'} {' '.join(names) or feature.title}"
        else:
            targets = sorted({str(part.data.get("dest") or part.data.get("unit") or "") for part in feature.parts} - {""})
            where = ", ".join([feature.app or feature.group] + targets[:4] + (["…"] if len(targets) > 4 else []))
        optional = [str(part.data["id"]) for part in feature.parts if part.optional]
        lines.append(f"- {feature.id}: {feature.title} ({where})" + (" · local" if feature.local else "")
                     + (f" · opções: {', '.join(optional)}" if optional else ""))
    if len(features) > limit:
        lines.append(f"- … e mais {len(features) - limit} em {CATALOG}")
    return "\n".join(lines)


# Removing a customization ---------------------------------------------------
ENTRY = re.compile(r"\s*\[\[\s*(feature|program)\s*\]\]\s*(?:#.*)?$")
SUBTABLE = re.compile(r"\s*\[\[?\s*(feature|program)\s*\.")
TABLE = re.compile(r"\s*\[")
TEXT_LIMIT = 512 * 1024


@dataclass
class Removal:
    """What the plugin removed from the repository, and what it left for the agent."""
    paths: list = field(default_factory=list)  # Changed or deleted, to publish
    deleted: list = field(default_factory=list)  # Relative paths of deleted source files
    mentions: list = field(default_factory=list)  # "file:line: text" in the documentation
    leftovers: list = field(default_factory=list)  # Other files left in a removed component's folder


def _attached(lines, index):
    """Start of the comment lines written right above a table header."""
    while index > 0 and lines[index - 1].lstrip().startswith("#"):
        index -= 1
    return index


def _spans(lines):
    """[kind, start, end] of every [[feature]] and [[program]] entry, comments above it included."""
    headers = []
    for index, line in enumerate(lines):
        if not TABLE.match(line) or SUBTABLE.match(line):
            continue
        match = ENTRY.match(line)
        headers.append((index, match.group(1) if match else None))
    spans = []
    for position, (index, kind) in enumerate(headers):
        if kind:
            following = headers[position + 1][0] if position + 1 < len(headers) else None
            spans.append([kind, _attached(lines, index), len(lines) if following is None else _attached(lines, following)])
    return spans


def _entry_id(kind, entry):
    if kind == "program":
        return str(entry.get("id") or f"program-{entry.get('package', '')}")
    return str(entry.get("id", ""))


def _references(entries):
    """Repository files that catalog entries read: sources and instruction files."""
    found = set()
    for entry in entries:
        for item in [entry] + [part for part in entry.get("part", []) if isinstance(part, dict)]:
            for value in (item.get("source"), str(item.get("instructions", "")).split("#", 1)[0].strip()):
                # Instructions are a README path or plain text; only a path names a file.
                if value and len(str(value)) < 256 and not re.search(r"\s", str(value)) and not Path(str(value)).is_absolute():
                    found.add(os.path.normpath(str(value)))
    return found


def _without_requirement(line, identifier):
    match = re.fullmatch(r"(\s*requires\s*=\s*\[)([^\]]*)(\].*)", line.rstrip("\n"))
    if not match:
        return line
    items = [item.strip() for item in match.group(2).split(",") if item.strip()]
    kept = [item for item in items if item.strip("\"'") != identifier]
    if kept == items:
        return line
    return match.group(1) + ", ".join(kept) + match.group(3) + ("\n" if line.endswith("\n") else "")


def _drop_entry(text, kind, identifier):
    """The catalog text without one entry and without it in other entries' requires.

    Returns None unless the result parses to exactly the expected catalog, so a
    layout this cannot follow is left to the agent instead of being damaged.
    """
    try:
        document = tomllib.loads(text)
    except ValueError:
        return None
    entries = document.get(kind, [])
    matches = [index for index, entry in enumerate(entries) if _entry_id(kind, entry) == identifier]
    lines = text.splitlines(keepends=True)
    spans = [span for span in _spans(lines) if span[0] == kind]
    if len(matches) != 1 or len(spans) != len(entries):
        return None
    _, start, end = spans[matches[0]]
    if start > 0 and not lines[start - 1].strip() and (end >= len(lines) or not lines[end].strip()):
        start -= 1  # Do not leave two blank lines where the entry was.
    lines = lines[:start] + lines[end:]
    if kind == "feature":
        for _, first, last in _spans(lines):
            for index in range(first, last):
                lines[index] = _without_requirement(lines[index], identifier)
    expected = dict(document)
    expected[kind] = [entry for index, entry in enumerate(entries) if index != matches[0]]
    expected["feature"] = [dict(entry, requires=[item for item in entry["requires"] if item != identifier])
                           if identifier in entry.get("requires", []) else entry for entry in expected.get("feature", [])]
    result = "".join(lines)
    try:
        parsed = tomllib.loads(result)
    except ValueError:
        return None
    normal = lambda value: {key: item for key, item in value.items() if item != [] or key not in ("feature", "program")}
    return result if normal(parsed) == normal(expected) else None


def _choice_of(table, key, identifier):
    """Whether a key of a machine file's table belongs to one feature."""
    return key.startswith(identifier + ".") if table == "parts" else key == identifier


def _drop_choices(text, identifier):
    """A machine file without its choices for one feature; None when nothing changes or it cannot."""
    table, kept, dropped = None, [], False
    for line in text.splitlines(keepends=True):
        header = re.fullmatch(r"\s*\[([A-Za-z0-9_-]+)\]\s*(#.*)?", line.rstrip("\n"))
        if header:
            table = header.group(1)
        key = re.match(r'\s*("(?:[^"\\]|\\.)*"|[A-Za-z0-9_-]+)\s*=', line)
        if key and table in ("features", "off", "parts"):
            name = json.loads(key.group(1)) if key.group(1).startswith('"') else key.group(1)
            if _choice_of(table, name, identifier):
                dropped = True
                continue
        kept.append(line)
    if not dropped:
        return None
    result = "".join(kept)
    try:
        before, after = tomllib.loads(text), tomllib.loads(result)
    except ValueError:
        return None
    for table in ("features", "off", "parts"):
        values = before.get(table)
        if isinstance(values, dict):
            before[table] = {key: value for key, value in values.items() if not _choice_of(table, key, identifier)}
    return result if before == after else None


def _tracked(repository):
    try:
        output = subprocess.run(["git", "-C", str(repository), "ls-files", "-z"], capture_output=True,
                                timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [name for name in output.decode(errors="replace").split("\0") if name]


def _text(path):
    try:
        if path.stat().st_size > TEXT_LIMIT:
            return None
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def remove_feature(repository, feature, local_catalog=None):
    """Delete a customization from the catalog, machine files and its own source files.

    Returns a Removal, or None when the catalog's layout needs the agent. Text
    that only people read (README, SYNC.md) is reported in `mentions`, not edited.
    """
    local = feature.local and local_catalog
    catalog = Path(local_catalog) if local else Path(repository) / CATALOG
    base = catalog.parent
    kind = "program" if feature.program else "feature"
    try:
        text = catalog.read_text()
        document = tomllib.loads(text)
    except (OSError, ValueError):
        return None
    result = _drop_entry(text, kind, feature.id)
    if result is None:
        return None
    entries = document.get(kind, [])
    removed = [entry for entry in entries if _entry_id(kind, entry) == feature.id]
    remaining = [entry for entry in document.get("feature", []) + document.get("program", []) if entry not in removed]
    removal = Removal(paths=[catalog])
    catalog.write_text(result)
    tracked = [] if local else _tracked(base)
    if not local:
        for path in sorted((base / MACHINES).glob("*.toml")):
            changed = _drop_choices(_text(path) or "", feature.id)
            if changed is not None:
                path.write_text(changed)
                removal.paths.append(path)
    # Source files only this customization read go too, unless another file still names them.
    still_used = _references(remaining)
    others = [name for name in tracked if name != CATALOG and not name.endswith(".md")
              and not name.startswith(MACHINES + "/")]
    for reference in sorted(_references(removed) - still_used):
        path = base / reference
        try:
            if (".." in Path(reference).parts or path.is_symlink() or not path.is_file()
                    or not inside(path.resolve(), base.resolve())):
                continue
        except OSError:
            continue
        if reference.endswith(".md"):
            removal.leftovers.append(reference)  # Documentation is for the agent to judge.
            continue
        if any(reference in (_text(base / name) or "") for name in others if name != reference):
            continue
        # Only files the repository tracks, or this machine's own local/ sources.
        if not (reference.startswith("local/") if local else reference in tracked):
            continue
        path.unlink()
        removal.paths.append(path)
        removal.deleted.append(reference)
    # What the plugin cannot judge: documentation and helpers beside the deleted sources.
    folders = {os.path.dirname(name) for name in removal.deleted} - {""}
    for folder in sorted(folders):
        if any(reference.startswith(folder + "/") for reference in still_used):
            continue
        removal.leftovers += [name for name in tracked if name.startswith(folder + "/") and (base / name).is_file()
                              and name not in removal.leftovers]
    words = ([feature.title] if len(feature.title) >= 6 else []) + removal.deleted
    named = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(feature.id)}(?![A-Za-z0-9_-])")
    for name in [name for name in tracked if name.endswith(".md")]:
        for number, line in enumerate((_text(base / name) or "").splitlines(), 1):
            if named.search(line) or any(word.casefold() in line.casefold() for word in words):
                removal.mentions.append(f"{name}:{number}: {line.strip()[:160]}")
    return removal


class Probe:
    """Evaluate `when` conditions once per refresh."""
    def __init__(self, run=subprocess.run):
        self.run = run
        self.cache = {}

    def package(self, name):
        if name not in self.cache:
            try:
                self.cache[name] = self.run(["pacman", "-Q", name], capture_output=True, timeout=10).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                self.cache[name] = False
        return self.cache[name]

    def omarchy(self):
        if "omarchy-version" not in self.cache:
            try:
                result = self.run(["pacman", "-Q", "omarchy"], capture_output=True, text=True, timeout=10)
                self.cache["omarchy-version"] = result.stdout.split()[1] if result.returncode == 0 else ""
            except (OSError, subprocess.TimeoutExpired, IndexError):
                self.cache["omarchy-version"] = ""
        return self.cache["omarchy-version"]

    def check(self, condition):
        negate = condition.startswith("!")
        condition = condition.lstrip("!")
        kind, _, value = condition.partition(":")
        if kind == "package":
            result = self.package(value)
        elif kind == "command":
            result = shutil.which(value) is not None
        elif kind == "path":
            try:
                result = expand(value).exists()
            except ValueError:
                result = False
        elif condition.startswith("omarchy>="):
            result = version_key(self.omarchy()) >= version_key(condition.split(">=", 1)[1])
        else:
            result = False
        return result != negate

    def applicable(self, feature):
        """Return the first failing condition, or None."""
        return next((condition for condition in feature.when if not self.check(condition)), None)


def version_key(value):
    return [int(number) for number in re.findall(r"\d+", value.split("-")[0])]


def machine_name(settings=None):
    name = (settings or {}).get("machine") or platform.node() or "machine"
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:64] or "machine"


def machine_path(repository, name):
    return Path(repository) / MACHINES / f"{name}.toml"


def install_id(path="/etc/machine-id"):
    """A stable, non-reversible id for this installation; it changes after a reinstall."""
    try:
        raw = Path(path).read_text().strip()
    except OSError:
        return ""
    return hashlib.sha256(f"omarchy-settings-sync:{raw}".encode()).hexdigest()[:16] if raw else ""


def machine_info(repository, name):
    try:
        data = tomllib.loads(machine_path(repository, name).read_text())
    except (OSError, ValueError):
        data = {}
    features = data.get("features", {}) if isinstance(data.get("features"), dict) else {}
    info = {key: str(data.get(key, "")) for key in ("hostname", "omarchy", "updated", "install")}
    return dict(info, name=name, on=sum(v == "on" for v in features.values()),
                off=sum(v == "off" for v in features.values()))


def list_machines(repository):
    folder = Path(repository) / MACHINES if repository else None
    if not folder or not folder.is_dir():
        return []
    return [machine_info(repository, path.stem) for path in sorted(folder.glob("*.toml"))
            if IDENTIFIER.fullmatch(path.stem)]


def valid_machine(name):
    return bool(IDENTIFIER.fullmatch(name or ""))


def rename_machine(repository, old, new):
    """Rename a machine file, keeping its choices. Returns the paths to publish."""
    if not valid_machine(new):
        raise ValueError("Use lowercase letters, digits and hyphens.")
    source, target = machine_path(repository, old), machine_path(repository, new)
    if target.exists():
        raise ValueError(f"A machine named {new} already exists.")
    info, record = machine_info(repository, old), load_machine(repository, old)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(machine_text(new, record, hostname=info["hostname"], omarchy=info["omarchy"],
                                   updated=info["updated"], install=info["install"]))
    source.unlink(missing_ok=True)
    return [source, target]


def remove_machine(repository, name):
    path = machine_path(repository, name)
    path.unlink(missing_ok=True)
    return [path]


def load_machine(repository, name):
    """A machine without a file is new: nothing is applied until the user picks."""
    record = {"features": {}, "off": {}, "parts": {}, "defaults": "ask"}
    try:
        data = tomllib.loads(machine_path(repository, name).read_text())
    except (OSError, ValueError):
        return record
    for table in ("features", "off", "parts"):
        values = data.get(table, {})
        if isinstance(values, dict):
            record[table] = {str(k): str(v) for k, v in values.items() if isinstance(v, str)}
    record["defaults"] = "ask" if data.get("defaults") == "ask" else "catalog"
    return record


def _toml_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def machine_text(name, record, *, hostname="", omarchy="", updated="", install=""):
    lines = ["# Choices for one machine. Edited by Omarchy Settings Sync.",
             f"name = {_toml_string(name)}"]
    for key, value in (("hostname", hostname), ("omarchy", omarchy), ("updated", updated), ("install", install)):
        if value:
            lines.append(f"{key} = {_toml_string(value)}")
    if record.get("defaults") == "ask":
        # Undecided features stay off here until chosen, as on a clean install.
        lines.append('defaults = "ask"')
    for table in ("features", "off", "parts"):
        values = record.get(table, {})
        if values:
            lines += ["", f"[{table}]"] + [f"{_toml_string(k)} = {_toml_string(v)}" for k, v in sorted(values.items())]
    return "\n".join(lines) + "\n"


def desired(feature, machine):
    """'on', 'off' or 'new' for this machine."""
    choice = machine.get("features", {}).get(feature.id)
    if choice in ("on", "off"):
        return choice
    if machine.get("defaults") == "ask" and feature.default == "on":
        return "new"
    return {"on": "on", "off": "off", "ask": "new"}[feature.default]


def off_mode(feature, machine):
    mode = machine.get("off", {}).get(feature.id, "default")
    return mode if mode in OFF_MODES else "default"


def part_enabled(feature, part, machine):
    if not part.optional:
        return True
    return machine.get("parts", {}).get(f"{feature.id}.{part.data['id']}", "on") == "on"


def ordered(features, ids=None):
    """Dependencies first, so enabling never runs ahead of what it needs."""
    by_id = {feature.id: feature for feature in features}
    result, seen = [], set()
    def visit(identifier, trail=()):
        if identifier in seen or identifier not in by_id or identifier in trail:
            return
        for required in by_id[identifier].requires:
            visit(required, trail + (identifier,))
        seen.add(identifier)
        result.append(by_id[identifier])
    for identifier in (ids if ids is not None else by_id):
        visit(identifier)
    return result


def dependents(features, identifier):
    return [feature for feature in features if identifier in feature.requires]


def main(arguments):
    if len(arguments) != 2 or arguments[0] != "validate":
        print("Usage: features.py validate <configuration repository>", file=sys.stderr)
        return 2
    features, errors = load_catalog(arguments[1])
    if not has_catalog(arguments[1]):
        errors.append(f"{CATALOG} not found")
    errors += overlaps(features)
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f"{len(features)} features, {sum(len(f.parts) for f in features)} parts: OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
