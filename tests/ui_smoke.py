"""Run manually in an Omarchy session. Isolated state; no agent or real sync."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from app import Application, SettingsWindow, Gtk, Gdk, GLib, LayerShell
from core import private_write
from claude_client import ClaudeClient

CLAUDE_MODELS = [
    {"model": "", "displayName": "Default", "supportedReasoningEfforts": [{"reasoningEffort": "high"}]},
    {"model": "opus", "displayName": "Opus with a very long display name", "supportedReasoningEfforts": [
        {"reasoningEffort": e} for e in ("low", "medium", "high", "xhigh", "max")]},
    {"model": "haiku", "displayName": "Haiku", "supportedReasoningEfforts": []},
]


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
    with patch.dict(os.environ, env), patch("app.agent_executable", side_effect=lambda agent: sys.executable if agent in {"codex", "claude"} else None), patch("app.CodexClient") as client_constructor, patch(
        "app.discover_models", return_value=CLAUDE_MODELS
    ) as discover:
        application = Gtk.Application(application_id="org.omarchy.AgentSettings.Test")
        application.register(None)
        window = SettingsWindow(application)
        window.present()
        assert window.vte is None, "Native conversations must not initialize VTE"
        assert json.loads(window.attention_file.read_text())["opened"]
        client_constructor.assert_not_called()
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
        assert window.send_button.get_sensitive(), "First request can start Codex on demand"
        window.ready = True
        window.update_models([{"model": "sample-model", "displayName": "Sample model",
                               "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "high"}]}])
        window.model_select.set_selected(1)
        window.effort_select.set_selected(2)
        assert window.selection() == ("sample-model", "high")
        def settle():
            until = time.monotonic() + .15
            wait(lambda: time.monotonic() >= until)
        def geometry():
            result = []
            for widget in (window.popup_card, window.controls, window.agent_select,
                           window.model_select, window.effort_select, window.input_area, window.stop_button):
                ok, bounds = widget.compute_bounds(window)
                assert ok
                result.append(tuple(round(v) for v in (bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height())))
            return result
        settle()
        baseline = geometry()
        # Long names, different catalogs and unsupported efforts must not move
        # the controls, composer, panel edge or footer action.
        window.agent_select.set_selected(window.agent_ids.index("claude"))
        wait(lambda: "claude" not in window.catalog_pending)
        assert window.content.get_visible_child_name() == "empty", "No unstarted terminal above the composer"
        for model in ("opus", "haiku", ""):
            window.model_select.set_selected(window.model_values.index(model))
            for effort in range(len(window.effort_values)):
                window.effort_select.set_selected(effort)
                settle()
                assert geometry() == baseline, (model, effort, baseline, geometry())
            if model == "haiku":
                assert not window.effort_select.get_sensitive()
        window.model_select.set_selected(window.model_values.index("opus"))
        window.effort_select.set_selected(window.effort_values.index("max"))
        window.agent_select.set_selected(window.agent_ids.index("gemini"))
        settle()
        assert geometry() == baseline
        window.agent_select.set_selected(window.agent_ids.index("claude"))
        assert window.selection() == ("opus", "max"), "Agent switches must preserve unsent selections"
        window.model_select.set_selected(window.model_values.index(None))
        assert window.panels
        window.popup_key(None, Gdk.KEY_Escape, 0, 0)
        assert window.get_visible() and not window.panels
        assert window.selection() == ("opus", "max"), "Canceling a custom model preserves the previous selection"
        window.busy = True
        window.status.set_text("Very long running command " * 40)
        window.update_buttons()
        settle()
        assert geometry() == baseline, "Long status text and Stop must not resize the panel"
        window.busy = False
        window.update_buttons()
        assert window.stop_button.get_visible() and not window.stop_button.get_sensitive()
        window.agent_select.set_selected(window.agent_ids.index("codex"))
        assert window.selection() == ("sample-model", "high")
        discover.assert_called_once()
        window.model_select.get_first_child().set_active(True)
        settle()
        window.popup_key(None, Gdk.KEY_Escape, 0, 0)
        assert window.get_visible(), "Escape closes the dropdown before the panel"
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
        # The first submission starts the backend, preserving the selected controls.
        window.client = None
        window.ready = False
        backend = client_constructor.return_value
        backend.models.return_value = [{"model": "sample-model", "displayName": "Sample model",
                                       "supportedReasoningEfforts": [{"reasoningEffort": "high"}]}]
        backend.start_thread.return_value = {"thread": {"id": "test-thread"}}
        backend.turn.return_value = {"turn": {"id": "test-turn"}}
        with patch("app.shutil.which", return_value="/usr/bin/codex"):
            assert window.submit("Test lazy startup")
        wait(lambda: window.turn_id == "test-turn")
        backend.start.assert_called_once()
        assert backend.turn.call_args.args[2:] == ("sample-model", "high")
        window.event({"method": "turn/completed",
                      "params": {"threadId": "test-thread", "turn": {"status": "completed"}}})
        assert not window.busy
        # A failed connection must close its backend and allow a fresh attempt.
        window.client = None
        window.ready = False
        backend.start.side_effect = RuntimeError("Test connection failure")
        with patch("app.shutil.which", return_value="/usr/bin/codex"):
            assert window.submit("Test failure cleanup")
        wait(lambda: not window.busy)
        assert window.client is None
        assert not window.thread_loaded
        backend.close.assert_called_once()
        # Exercise the native Claude protocol through the actual GTK questions.
        clients = []
        def fake_claude(event, **kwargs):
            client = ClaudeClient(event, **kwargs, command=[sys.executable, str(Path(__file__).with_name("fake_claude.py"))])
            clients.append(client)
            return client
        window.agent_select.set_selected(window.agent_ids.index("claude"))
        window.model_select.set_selected(window.model_values.index("opus"))
        with patch("app.ClaudeClient", side_effect=fake_claude):
            assert window.submit("Ask a structured question")
            wait(lambda: bool(window.question_windows))
            assert window.busy and window.attention_waiting
            assert json.loads(window.attention_file.read_text())["waiting"]
            assert not window.spinner.get_spinning()
            session_id = window.thread_id
            assert session_id != "test-thread"
            # A companion terminal is available during a request; settings remain
            # inspectable, while changes cannot affect the running conversation.
            with patch("app.terminal") as terminal:
                window.open_terminal()
                terminal.assert_called_once_with([os.environ.get("SHELL", "/bin/bash")])
            window.setup()
            assert all(not w.get_sensitive() for w in widgets(window.setup_panel) if isinstance(w, Gtk.Entry))
            window.setup_panel.on_close()
            with patch.object(application, "quit") as quit_app:
                window.dismiss()
                assert window.attention_waiting
                quit_app.assert_not_called()
                window.present()
            question = window.question_windows["question"]
            reply = next(w for w in widgets(question) if isinstance(w, Gtk.Button) and w.get_label() == tr("Reply"))
            reply.emit("clicked")
            assert window.question_windows, "Empty answers must not dismiss the question"
            choices = {w.get_label(): w for w in widgets(question) if isinstance(w, Gtk.CheckButton)}
            entries = [w for w in widgets(question) if isinstance(w, Gtk.Entry)]
            choices["Green"].set_active(True)
            entries[0].set_text("Custom")
            assert not choices["Green"].get_active()
            choices["Blue"].set_active(True)
            assert not entries[0].get_text()
            choices["One"].set_active(True)
            choices["Two"].set_active(True)
            reply.emit("clicked")
            wait(lambda: not window.busy)
            assert not window.question_windows and not window.attention_waiting
            assert not json.loads(window.attention_file.read_text())["waiting"]
            response = json.loads(window.messages[-1]["text"])
            assert response["updatedInput"]["answers"] == {"Which color?": "Blue", "Which extras?": "One, Two"}
            window.agent_select.set_selected(window.agent_ids.index("codex"))
            assert window.thread_id == "test-thread"
            window.agent_select.set_selected(window.agent_ids.index("claude"))
            assert window.thread_id == session_id
            assert window.submit("Test cancellation after resuming")
            wait(lambda: bool(window.question_windows))
            assert clients[-1].session_id == session_id
            window.stop()
            wait(lambda: not window.busy)
            assert not window.question_windows and not window.attention_waiting
            assert window.submit("Test disconnect cleanup")
            wait(lambda: bool(window.question_windows) or not window.busy)
            assert window.question_windows, window.messages[-2:]
            clients[-1].process.terminate()
            wait(lambda: window.client is None)
            assert not window.busy and not window.attention_waiting
        window.close_client()
        if window.ensure_vte():
            window.agent_select.set_selected(window.agent_ids.index("claude"))
            with patch("app.external_command", return_value=[sys.executable, "-c", "import time; print('terminal-ok',flush=True); time.sleep(.4)"]), patch("app.shutil.which", return_value=sys.executable):
                window.launch_external("test")
                wait(lambda: window.terminal_pid is not None)
                assert window.stop_button.get_visible()
                assert not window.sync_button.get_sensitive()
                wait(lambda: window.terminal_pid is None)
                assert window.send_button.get_sensitive()
        window.client = None
        with patch.object(window, "quit_if_idle") as cleanup:
            window.popup_key(None, Gdk.KEY_Escape, 0, 0)
            assert not window.get_visible()
            cleanup.assert_called_once()
            window.present()
            wait(lambda: window.get_visible())
            class Gesture:
                def set_state(self, state): self.state = state
            window.popup_click(Gesture(), 1, 0, 0)
            assert not window.get_visible()
        with patch.object(application, "quit") as quit_app:
            window.busy = True
            window.quit_if_idle()
            quit_app.assert_not_called()
            window.busy = False
            window.quit_if_idle()
            quit_app.assert_not_called()
            assert window.idle_timer is not None
            window.present()
            wait(lambda: window.idle_timer is None)
            window.dismiss()
            assert not json.loads(window.attention_file.read_text())["opened"]
            GLib.source_remove(window.idle_timer)
            window.expire_idle()
            quit_app.assert_called_once()
        GLib.source_remove(window.theme_timer)
        GLib.source_remove(window.attention_timer)
        window.destroy()
        print("UI smoke passed: fixed layout, native Claude questions, answers, resume, cancel, disconnect, attention, terminal, settings, Codex protocol, dismissal")
