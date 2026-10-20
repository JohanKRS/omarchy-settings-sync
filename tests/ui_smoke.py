"""Run manually in an Omarchy session. Isolated state; no agent or real sync."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from app import Application, SettingsWindow, Gtk, Gdk, GLib, Vte, LayerShell
from core import private_write


def widgets(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from widgets(child)
        child = child.get_next_sibling()


def wait(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while GLib.MainContext.default().iteration(False):
            pass
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError("UI condition timed out")


with tempfile.TemporaryDirectory(prefix="agent-settings-ui-") as temp:
    env = {key: str(Path(temp) / name) for key, name in [
        ("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"), ("XDG_DATA_HOME", "data")]}
    with patch.dict(os.environ, env), patch.object(SettingsWindow, "connect_codex"):
        application = Gtk.Application(application_id="org.omarchy.AgentSettings.Test")
        application.register(None)
        window = SettingsWindow(application)
        window.present()
        wait(lambda: bool(window.panels))
        assert LayerShell.is_layer_window(window)
        assert not window.get_decorated()
        assert len(application.get_windows()) == 1, "Setup must stay in one tiling window"
        window.setup()
        assert len(window.panels) == 1
        entries = [w for w in widgets(window.setup_panel) if isinstance(w, Gtk.Entry)]
        entries[0].set_text("sample/dotfiles")
        from i18n import tr
        buttons = [w for w in widgets(window.setup_panel) if isinstance(w, Gtk.Button)]
        next(w for w in buttons if w.get_label() == tr("Use repository")).emit("clicked")
        assert window.settings["repository"] == "https://github.com/sample/dotfiles"
        assert not window.panels
        window.ready = True
        window.update_models([{"model": "sample-model", "displayName": "Sample model",
                               "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "high"}]}])
        window.model_select.set_selected(1)
        window.effort_select.set_selected(2)
        assert window.selection() == ("sample-model", "high")
        replies = []
        class Client:
            def respond(self, *args): replies.append(args)
        window.client = Client()
        window.request_from_agent({"id": "denied", "method": "item/commandExecution/requestApproval",
                                   "params": {"command": "printf test", "availableDecisions": ["decline"]}})
        assert not any(isinstance(w, Gtk.Button) and w.get_label() == tr("Allow once") for w in widgets(window.panels[-1]))
        window.panels[-1].on_close()
        assert replies[-1][1] == {"decision": "decline"}
        # Out-of-order streaming messages must persist against their own IDs.
        for ident in ("a", "b"):
            window.event({"method": "item/agentMessage/delta", "params": {"itemId": ident, "delta": ident}})
        for ident in ("a", "b"):
            window.event({"method": "item/completed", "params": {"item": {"type": "agentMessage", "id": ident, "text": ident + " done"}}})
        assert window.message_entries["a"]["text"] == "a done"
        assert window.message_entries["b"]["text"] == "b done"
        if Vte:
            window.agent_select.set_selected(window.agent_ids.index("claude"))
            with patch("app.external_command", return_value=[sys.executable, "-c", "import time; print('terminal-ok',flush=True); time.sleep(.4)"]), patch("app.shutil.which", return_value=sys.executable):
                window.launch_external("test")
                wait(lambda: window.terminal_pid is not None)
                assert window.stop_button.get_visible()
                assert not window.sync_button.get_sensitive()
                wait(lambda: window.terminal_pid is None)
                assert window.send_button.get_sensitive()
        window.client = None
        window.popup_key(None, Gdk.KEY_Escape, 0, 0)
        assert not window.get_visible()
        window.present()
        wait(lambda: window.get_visible())
        class Gesture:
            def set_state(self, state): self.state = state
        window.popup_click(Gesture(), 1, 0, 0)
        assert not window.get_visible()
        GLib.source_remove(window.theme_timer)
        window.destroy()
        print("UI smoke passed: layer popup, setup, controls, approvals, streaming, terminal, dismissal")
