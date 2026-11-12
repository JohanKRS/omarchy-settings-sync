"""Bring Superwhisper dictations into the panel when Superwhisper cannot.

Superwhisper types a dictation into Hyprland's active window. The panel is a
layer-shell overlay, so the active window is still the app behind it: the
fcitx5 commit into the panel is declined as the wrong target, and since a
panel holds the keyboard, Superwhisper does not send its paste keystroke
either. It leaves the text on the clipboard and records the dictation, with
`delivery` "clipboard" and a warning starting with "panel_has_keyboard", in
its runtime `last.json`. While the panel is shown, this watches that file and
hands such a dictation to the panel, which types it at its cursor.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PANEL_REASON = "panel_has_keyboard"
LAST_FILE = "last.json"
# No space goes before these, nor after the opening ones.
CLOSING = set(",.;:!?)]}%…»”’")
OPENING = set("([{«“‘¿¡/@#-")


def last_files(environment=None):
    """Where a release or development Superwhisper daemon records its last dictation."""
    env = os.environ if environment is None else environment
    folders = []
    if env.get("SUPERWHISPER_RUNTIME"):
        folders.append(Path(env["SUPERWHISPER_RUNTIME"]))
    if env.get("XDG_RUNTIME_DIR"):
        folders += [Path(env["XDG_RUNTIME_DIR"]) / name for name in ("superwhisper", "superwhisper-dev")]
    return [folder / LAST_FILE for folder in folders]


def read_last(path):
    try:
        entry = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return entry if isinstance(entry, dict) else None


def identity(entry):
    """Tells one dictation from the next, also when the daemon rewrites the same one."""
    if not isinstance(entry, dict):
        return None
    return entry.get("createdAt"), entry.get("session_id"), entry.get("text")


def stranded_text(entry):
    """The text of a dictation left on the clipboard only because a panel had the keyboard.

    Any other delivery (typed, pasted, or clipboard by the user's choice) is not ours."""
    if not isinstance(entry, dict) or entry.get("delivery") != "clipboard":
        return None
    if not str(entry.get("warning") or "").startswith(PANEL_REASON):
        return None
    text = entry.get("text")
    return text.strip() if isinstance(text, str) and text.strip() else None


def spaced(text, before="", after=""):
    """Separate a dictation from the words on either side of the cursor with one space."""
    if before and not before.isspace() and before not in OPENING and text[:1] not in CLOSING:
        text = " " + text
    if after and not after.isspace() and after not in CLOSING and text[-1:] not in OPENING:
        text += " "
    return text


class DictationInbox:
    """Watch Superwhisper's last dictation while the panel is shown.

    `deliver(text)` is called on the main loop for each new dictation that
    Superwhisper could not insert into the panel."""

    def __init__(self, deliver, files=None):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.deliver = deliver
        self.files = last_files() if files is None else [Path(path) for path in files]
        self.monitors = []
        self.seen = set()
        self.pending = None

    def watch(self, active):
        if not active:
            self.stop()
            return
        if self.monitors:
            return
        # A dictation finished before the panel was shown went where Superwhisper put it.
        self.seen = {identity(read_last(path)) for path in self.files}
        for path in self.files:
            if not path.parent.is_dir():
                continue
            try:
                monitor = self.Gio.File.new_for_path(str(path.parent)).monitor_directory(
                    self.Gio.FileMonitorFlags.WATCH_MOVES, None)
            except self.GLib.Error:
                continue
            monitor.connect("changed", self.changed)
            self.monitors.append(monitor)

    def stop(self):
        for monitor in self.monitors:
            monitor.cancel()
        self.monitors = []
        if self.pending is not None:
            self.GLib.source_remove(self.pending)
            self.pending = None

    def changed(self, _monitor, file, other, _event):
        names = {file.get_basename() if file else None, other.get_basename() if other else None}
        if LAST_FILE in names and self.pending is None:
            # Let a write finish (or a rename land) before reading it.
            self.pending = self.GLib.timeout_add(60, self.check)

    def check(self):
        self.pending = None
        for path in self.files:
            entry = read_last(path)
            key = identity(entry)
            if key in self.seen:
                continue
            text = stranded_text(entry)
            if text:
                self.seen.add(key)
                self.deliver(text)
        return False
