"""Find customizations an Omarchy update affected.

Omarchy ships its defaults under /usr/share/omarchy and pacman keeps the
previous package in its cache, so the shipped files each customization
depends on can be compared between versions without guessing.
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path
import shutil
import subprocess

from applier import _ini_get, _ini_value, _lookup
from features import OMARCHY_PATH, expand, inside, xdg

CACHE = Path("/var/cache/pacman/pkg")
PREFIX = "usr/share/omarchy/"
ORDER = ("broken", "default-changed", "changed", "redundant")


def members(feature, home=None, environ=None, omarchy=OMARCHY_PATH):
    """Shipped files (relative to /usr/share/omarchy) that this feature depends on."""
    config = xdg(home, environ)["XDG_CONFIG_HOME"]
    result = set()
    for part in feature.parts:
        if part.kind == "package":
            result.add("install/omarchy-base.packages")
        dest = part.data.get("dest")
        if part.kind == "mime":
            dest = str(config / "mimeapps.list")
        if not dest:
            continue
        try:
            path = expand(dest, home, environ)
        except ValueError:
            continue
        if inside(path, config):
            result.add(f"config/{path.relative_to(config)}")
        if inside(path, config / "hypr"):
            # Omarchy's own defaults for the same Hyprland file, e.g. default/hypr/bindings.lua
            # and default/hypr/bindings/; unrelated Hyprland changes are left out.
            result |= {f"default/hypr/{path.name}", f"default/hypr/{path.stem}/"}
    return sorted(result)


def expand_members(names, listing):
    """Turn directory entries such as default/hypr/ into the files under them."""
    files = set()
    for name in names:
        if name.endswith("/"):
            files |= {item for item in listing if item.startswith(name) and not item.endswith("/")}
        else:
            files.add(name)
    return sorted(files)


class Package:
    """Read shipped files of an earlier Omarchy version from the pacman cache or a saved copy."""
    def __init__(self, version, *, cache=CACHE, snapshot=None, run=subprocess.run):
        self.run = run
        self.snapshot = Path(snapshot) if snapshot else None
        found = sorted(Path(cache).glob(f"omarchy-{version}-*.pkg.tar.zst")) if version else []
        self.archive = found[0] if found else None
        self._listing = None

    @property
    def available(self):
        return bool(self.archive) or bool(self.snapshot and self.snapshot.is_dir())

    def listing(self):
        if self._listing is None:
            self._listing = set()
            if self.archive:
                result = self.run(["tar", "--zstd", "-tf", str(self.archive)], capture_output=True, text=True, timeout=60)
                self._listing = {line[len(PREFIX):] for line in result.stdout.splitlines() if line.startswith(PREFIX)}
            elif self.snapshot and self.snapshot.is_dir():
                self._listing = {str(path.relative_to(self.snapshot)) for path in self.snapshot.rglob("*") if path.is_file()}
        return self._listing

    def read(self, member):
        if self.archive:
            if member not in self.listing():
                return None
            result = self.run(["tar", "--zstd", "-xOf", str(self.archive), PREFIX + member],
                              capture_output=True, timeout=60)
            return result.stdout if result.returncode == 0 else None
        if self.snapshot:
            path = self.snapshot / member
            return path.read_bytes() if path.is_file() else None
        return None


def current_listing(omarchy=OMARCHY_PATH):
    root = Path(omarchy)
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()} if root.is_dir() else set()


def _text(data):
    return data.decode(errors="replace") if data is not None else None


def _diff(member, old, new, limit=40):
    lines = list(difflib.unified_diff((old or "").splitlines(), (new or "").splitlines(),
                                      f"{member} (antes)", f"{member} (agora)", lineterm="", n=1))
    return "\n".join(lines[:limit] + (["…"] if len(lines) > limit else []))


def _key_values(part, text):
    """Return a getter for keys of a json/ini part in a shipped file's text."""
    if text is None:
        return lambda key: (False, None)
    if part.kind == "json":
        try:
            data = json.loads(text)
        except ValueError:
            return lambda key: (False, None)
        return lambda key: _lookup(data, key)
    lines = text.splitlines()
    section = "Default Applications" if part.kind == "mime" else part.data.get("section", "")
    fmt = part.data.get("format", "ini") if part.kind == "ini" else "ini"
    def get(key):
        index, raw = _ini_get(lines, section, key)
        return index is not None, _ini_value(raw, fmt)
    return get


def review(features, previous, *, home=None, environ=None, omarchy=OMARCHY_PATH, config_errors=""):
    """Return {feature id: {"kind", "files", "diff", "keys"}} for features the update touched."""
    current = current_listing(omarchy)
    old_listing = previous.listing()
    impacts = {}
    for feature in features:
        files = expand_members(members(feature, home, environ, omarchy), current | old_listing)
        changed = {}
        for member in files:
            old = _text(previous.read(member))
            path = Path(omarchy) / member
            new = path.read_text(errors="replace") if path.is_file() else None
            if old != new:
                changed[member] = (old, new)
        kinds, keys = set(), []
        for part in feature.parts:
            if part.kind not in ("json", "ini", "mime"):
                continue
            member = next((m for m in changed if m.startswith("config/") and _matches(part, m, home, environ)), None)
            if not member:
                continue
            old_get, new_get = (_key_values(part, text) for text in changed[member])
            values = part.data["types"] if part.kind == "mime" else part.data["values"]
            for key, mine in values.items():
                before, after = old_get(key), new_get(key)
                if before == after:
                    continue
                kind = "redundant" if after[0] and after[1] == mine else "default-changed"
                kinds.add(kind)
                keys.append({"key": key, "before": before[1] if before[0] else None,
                             "after": after[1] if after[0] else None, "mine": mine, "kind": kind})
        if changed and not kinds:
            kinds.add("changed")
        if config_errors and ("hyprland" in feature.areas or feature.app == "hyprland"
                              or any(m.startswith("default/hypr/") for m in files)):
            kinds.add("broken")
        if kinds:
            kind = next(k for k in ORDER if k in kinds)
            impacts[feature.id] = {
                "kind": kind, "files": sorted(changed),
                "diff": "\n".join(_diff(m, *changed[m]) for m in sorted(changed))[:6000],
                "keys": keys, "errors": config_errors[:1000] if kind == "broken" else "",
            }
    return impacts


def _matches(part, member, home, environ):
    config = xdg(home, environ)["XDG_CONFIG_HOME"]
    dest = config / "mimeapps.list" if part.kind == "mime" else expand(part.data["dest"], home, environ)
    return inside(dest, config) and f"config/{dest.relative_to(config)}" == member


def save_snapshot(features, target, *, home=None, environ=None, omarchy=OMARCHY_PATH):
    """Keep this version's relevant defaults, for when pacman's cache is cleaned before the next update."""
    target = Path(target)
    shutil.rmtree(target, ignore_errors=True)
    listing = current_listing(omarchy)
    wanted = set()
    for feature in features:
        wanted |= set(expand_members(members(feature, home, environ, omarchy), listing))
    for member in wanted:
        source = Path(omarchy) / member
        if source.is_file():
            (target / member).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target / member)


def agent_request(feature, impact, old, new):
    """Ask the agent to adapt one customization to the new Omarchy defaults."""
    keys = "\n".join(f"- {k['key']}: padrão {k['before']!r} → {k['after']!r}; personalização {k['mine']!r}"
                     for k in impact.get("keys", []))
    return (
        f"AJUSTAR APÓS ATUALIZAÇÃO DO OMARCHY. O Omarchy foi de {old} para {new} e isso afetou "
        f"'{feature.title}' ({feature.id}). Explique em poucas linhas o que mudou e se a personalização "
        "ainda é necessária, conflita ou ficou redundante. Proponha a menor adaptação, pergunte com a "
        "ferramenta de perguntas quando houver escolha, aplique e valide nesta máquina, e atualize o "
        "catálogo e o repositório se a adaptação for portátil.\n"
        + (f"Chaves afetadas:\n{keys}\n" if keys else "")
        + (f"Erros de configuração:\n{impact['errors']}\n" if impact.get("errors") else "")
        + f"Diferenças nos padrões do Omarchy:\n{impact.get('diff') or '(sem diferença de arquivo)'}"
    )
