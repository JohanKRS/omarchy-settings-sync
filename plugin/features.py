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
GROUPS = ("desktop", "apps", "system")
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
        features.append(Feature(
            id=identifier, title=str(entry["title"]), summary=str(entry.get("summary", "")),
            group=entry.get("group") if entry.get("group") in GROUPS else "apps",
            default=entry.get("default", "on"), parts=parts, local=local, **lists))
    return features


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
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f"{len(features)} features, {sum(len(f.parts) for f in features)} parts: OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
