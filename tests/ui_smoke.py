"""Run manually in an Omarchy session. Isolated state; no agent or real sync."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from app import Application, SettingsWindow, Gtk, Gdk, GLib, LayerShell
from core import AGENTS, private_write
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
        # Exercise handlers explicitly without consuming real desktop input
        # or letting concurrent mouse/keyboard activity dismiss the fixture.
        LayerShell.set_keyboard_mode(window, LayerShell.KeyboardMode.NONE)
        window.set_can_target(False)
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
        # The optional review lives in Settings, never runs merely on opening,
        # and uses the repository entered in the form.
        with patch.object(window, 'submit', return_value=True) as submit_review:
            window.setup()
            extras = next(w for w in widgets(window.setup_panel) if isinstance(w, Gtk.Expander))
            assert not extras.get_expanded()
            submit_review.assert_not_called()
            review = extras.get_child()
            assert review.get_label() == tr('Review existing customizations') and review.get_sensitive()
            entries = [w for w in widgets(window.setup_panel) if isinstance(w, Gtk.Entry)]
            entries[0].set_text('invalid')
            extras.set_expanded(True)
            wait(lambda: review.get_mapped() and review.get_height() > 0)
            review.emit('clicked')
            submit_review.assert_not_called()
            assert window.setup_panel in window.panels
            entries[0].set_text('sample/dotfiles')
            review.emit('clicked')
            submit_review.assert_called_once_with(tr('Review my existing customizations'), review_existing=True)
            assert not window.panels
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
                           window.model_select, window.effort_select, window.input_area,
                           window.terminal_button):
                ok, bounds = widget.compute_bounds(window)
                assert ok
                result.append(tuple(round(v) for v in (bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height())))
            _, send = window.send_button.compute_bounds(window)
            _, terminal = window.terminal_button.compute_bounds(window)
            assert abs(send.get_x() + send.get_width() - terminal.get_x() - terminal.get_width()) < 1
            return result
        settle()
        baseline = geometry()
        assert not window.queue_area.get_visible(), 'An empty queue should not add controls'
        assert not window.spinner.get_visible(), 'Idle must not leave a static activity ring'
        assert window.popup_bounds[3] <= 740
        assert window.stop_button.get_next_sibling() == window.send_button
        assert window.terminal_button.get_next_sibling() is None, 'Terminal belongs at the footer right edge'
        assert not window.stop_button.get_visible()
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
        assert window.get_visible() and not window.panels, ('custom model dismissal', window.get_visible(), len(window.panels))
        assert window.selection() == ("opus", "max"), "Canceling a custom model preserves the previous selection"
        window.busy = True
        window.status.set_text("Very long running command " * 40)
        window.update_buttons()
        settle()
        assert geometry() == baseline, ("Long status text and Stop must not resize the panel", baseline, geometry())
        assert window.stop_button.get_visible() and window.stop_button.get_sensitive()
        window.busy = False
        window.update_buttons()
        assert not window.stop_button.get_visible() and not window.stop_button.get_sensitive()
        window.agent_select.set_selected(window.agent_ids.index("codex"))
        assert window.selection() == ("sample-model", "high")
        discover.assert_called_once()
        window.model_select.get_first_child().set_active(True)
        wait(lambda: any(isinstance(w, Gtk.Popover) and w.get_visible() for w in widgets(window.model_select)))
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
        # Streaming/final updates must follow the new layout, not yesterday's
        # adjustment range. The whole final line needs room above the composer.
        streamed_text = ('Earlier line of a long response.\n' * 40)
        window.event({'method': 'item/agentMessage/delta', 'params': {
            'itemId': 'scroll-bottom', 'delta': streamed_text}})
        settle()
        final_text = streamed_text + ('The final response can wrap onto additional lines. ' * 6) + '\nÚltima linha: gypq.'
        window.event({'method': 'item/completed', 'params': {'item': {
            'type': 'agentMessage', 'id': 'scroll-bottom', 'text': final_text}}})
        settle()
        adjustment = window.scroll.get_vadjustment()
        assert abs(adjustment.get_upper() - adjustment.get_page_size() - adjustment.get_value()) < 1, 'Final streamed line was left below the viewport'
        ok, last_line = window.cards['scroll-bottom'].compute_bounds(window.scroll)
        assert ok and last_line.get_y() + last_line.get_height() <= window.scroll.get_height() - 8, ('Last line needs bottom breathing room', last_line.get_y(), last_line.get_height(), window.scroll.get_height(), adjustment.get_value(), adjustment.get_upper(), adjustment.get_page_size())
        # Reading older messages must not be interrupted by a streaming update.
        adjustment.set_value(0)
        assert window.latest_button.get_visible()
        window.event({'method': 'item/agentMessage/delta', 'params': {'itemId': 'scroll-bottom', 'delta': '\nMore text'}})
        settle()
        assert adjustment.get_value() == 0 and not window.scroll.follow_tail
        window.latest_button.emit('clicked')
        assert window.scroll.follow_tail and not window.latest_button.get_visible()
        window.scroll.pull(-100)
        assert -28 <= window.transcript.offset < 0
        wait(lambda: window.scroll.tick is None)
        assert window.transcript.offset == 0
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
        settle()
        first_indicator = window.spinner.indicator
        assert first_indicator is not None and first_indicator.get_spinning()
        window.set_visible(False)
        settle()
        assert window.spinner.indicator is None
        window.present()
        settle()
        assert window.spinner.indicator is not first_indicator and window.spinner.indicator.get_spinning()
        # Queued work waits for a completion; steering keeps the same turn.
        window.input.get_buffer().set_text('Run after the current response')
        assert window.composer_key(None, Gdk.KEY_Return, 0, 0)
        assert len(window.outbox.for_agent('codex')) == 1
        assert backend.turn.call_count == 1
        pending = window.outbox.for_agent('codex')[0]
        window.input.get_buffer().set_text('Do not overwrite this draft')
        assert window.queue_area.get_visible() and not window.panels
        assert window.queue_area.get_next_sibling() == window.input_area
        window.edit_queued(pending)
        assert pending in window.outbox.entries
        assert window.input.get_buffer().get_char_count() > 0
        window.input.get_buffer().set_text('')
        window.edit_queued(pending)
        assert pending not in window.outbox.entries and window.queue_paused
        assert window.input.get_buffer().get_text(*window.input.get_buffer().get_bounds(), False) == pending['text']
        assert not window.panels
        window.send(queued=True)
        window.queue_toggle.emit('clicked')
        assert not window.queue_paused and not window.panels
        window.input.get_buffer().set_text('Focus on the keyboard first')
        window.composer_key(None, Gdk.KEY_Return, 0, Gdk.ModifierType.CONTROL_MASK)
        wait(lambda: not window.delivery_pending)
        backend.steer.assert_called_once_with('test-thread', 'test-turn', 'Focus on the keyboard first')
        assert window.busy and backend.turn.call_count == 1
        assert len(window.outbox.for_agent('codex')) == 1
        window.event({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
        wait(lambda: not window.delivery_pending)
        assert window.busy and backend.turn.call_count == 2
        assert not window.outbox.for_agent('codex')
        assert 'Run after the current response' in backend.turn.call_args.args[1]
        direction = window.queue_message('Promote this queued message')
        next(w for w in widgets(window.queue_list) if isinstance(w, Gtk.Button) and
             w.get_tooltip_text() == tr('Direct now')).emit('clicked')
        wait(lambda: not window.delivery_pending)
        assert not window.outbox.for_agent('codex') and direction not in window.outbox.entries
        assert window.busy and backend.turn.call_count == 2, 'Promoting a queue item must steer without duplicating it'
        window.event({"method": "turn/completed",
                      "params": {"threadId": "test-thread", "turn": {"status": "completed"}}})
        assert not window.busy
        # The idle row sends directly; long queues stay bounded and previews
        # remain one line even for multiline Markdown or very long messages.
        assert not window.spinner.get_visible()
        queued = [window.queue_message(f'Follow-up {n}\n' + 'Long preview ' * 70) for n in range(6)]
        settle()
        assert 0 < window.queue_scroll.get_height() <= 96
        for preview in (w for w in widgets(window.queue_list) if isinstance(w, Gtk.Label)):
            assert '\n' not in preview.get_text() and not preview.get_wrap()
        before = backend.turn.call_count
        next(w for w in widgets(window.queue_list) if isinstance(w, Gtk.Button) and
             w.get_tooltip_text() == tr('Send now')).emit('clicked')
        wait(lambda: not window.delivery_pending)
        assert backend.turn.call_count == before + 1 and queued[0] not in window.outbox.entries
        assert window.spinner.get_visible()
        window.queue_paused = True
        window.event({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
        for entry in queued[1:]:
            window.remove_queued(entry)
        assert not window.queue_area.get_visible()
        # Markdown remains source-backed while the UI uses native tables,
        # selectable inline markup and links. Raw HTML is never executed.
        markdown = ('## Choices\n\n**Bold** and *italic*, ~~old~~, `x < y`, '
                    '[Docs](https://example.com?a=1&b=2) and <b>HTML</b><br>Next.\n\n'
                    '| Option | Result |\n| --- | --- |\n'
                    '| `~/Desktop` | **Visible** directory |\n'
                    '| Hidden | A longer description that wraps within the cell. |\n\n'
                    '- [x] Done\n- [ ] Pending\n\n> A quote\n\n'
                    '```html\n<script>alert(1)</script>\n```')
        body = window.add_message(tr('Agent'), markdown, 'markdown-fixture')
        settle()
        assert body.get_text() == markdown
        cells = [w for w in widgets(body) if isinstance(w, Gtk.Label) and w.has_css_class('markdown-cell')]
        assert len(cells) == 6 and cells[2].get_text() == '~/Desktop'
        assert '<b>Visible</b>' in cells[3].get_label()
        links = [w for w in widgets(body) if isinstance(w, Gtk.Label) and '<a href=' in w.get_label()]
        assert links and 'https://example.com?a=1&amp;b=2' in links[0].get_label()
        assert any(w.get_text() == '<script>alert(1)</script>' for w in widgets(body) if isinstance(w, Gtk.Label))
        _, table_bounds = cells[0].get_parent().compute_bounds(window.popup_card)
        assert table_bounds.get_x() + table_bounds.get_width() < window.popup_card.get_width()
        # Streaming must append to raw Markdown rather than already rendered text.
        window.add_message(tr('Agent'), '**Hel', 'markdown-stream')
        window.event({'method': 'item/agentMessage/delta', 'params': {'itemId': 'markdown-stream', 'delta': 'lo**'}})
        assert window.cards['markdown-stream'].get_text() == '**Hello**'
        assert window.cards['markdown-stream'].get_first_child().get_label() == '<b>Hello</b>'
        # Only completed, current agent choices are actionable. A click directs
        # the existing turn, bypasses the queue and leaves the composer alone.
        assert window.submit('Offer inline options')
        wait(lambda: not window.delivery_pending)
        choice_text = 'Qual opção você prefere?\n\n1. **Azul** — manter a configuração.\n2. Verde'
        window.event({'method': 'item/agentMessage/delta', 'params': {'itemId': 'inline', 'delta': choice_text}})
        body = window.cards['inline']
        assert not body.choice_buttons, 'Streaming options must not submit incomplete answers'
        window.event({'method': 'item/completed', 'params': {'item': {
            'id': 'inline', 'type': 'agentMessage', 'text': choice_text}}})
        assert len(body.choice_buttons) == 2 and body.choice_buttons[0].get_sensitive()
        window.input.get_buffer().set_text('Preserve this draft')
        queued = window.queue_message('A later task')
        window.queue_paused = True
        before = backend.steer.call_count
        body.choice_buttons[0].emit('clicked')
        body.choice_buttons[1].emit('clicked')
        wait(lambda: not window.delivery_pending)
        assert backend.steer.call_count == before + 1
        backend.steer.assert_called_with('test-thread', 'test-turn',
                                         'Qual opção você prefere?\nAzul — manter a configuração.')
        assert window.busy and window.outbox.for_agent('codex') == [queued]
        assert window.input.get_buffer().get_text(*window.input.get_buffer().get_bounds(), False) == 'Preserve this draft'
        assert not any(b.get_sensitive() for b in body.choice_buttons)
        assert window.message_entries['inline']['choices_answered']
        assert any(m.get('choices_answered') for m in json.loads(window.session_file.read_text()))
        window.remove_queued(queued)
        window.event({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
        window.input.get_buffer().set_text('')
        # Idle answers start a new turn in the existing thread; old messages,
        # user-authored lists and structured permission requests cannot redirect.
        old = window.add_message(tr('Agent'), choice_text, 'old-choice')
        idle = window.add_message(tr('Agent'), 'Which color?\n\n- Blue\n- Green', 'idle-choice')
        assert not old.choice_buttons[0].get_sensitive()
        before = backend.turn.call_count
        old.choice_buttons[0].emit('clicked')
        assert backend.turn.call_count == before
        window.request_from_agent({'id': 'block-choice', 'method': 'item/commandExecution/requestApproval',
                                   'params': {'command': 'test', 'availableDecisions': ['decline']}})
        assert not idle.choice_buttons[0].get_sensitive()
        window.panels[-1].on_close()
        idle.choice_buttons[1].emit('clicked')
        wait(lambda: not window.delivery_pending)
        assert backend.turn.call_count == before + 1 and 'Which color?\nGreen' in backend.turn.call_args.args[1]
        assert not window.outbox.for_agent('codex')
        window.event({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
        assert not window.add_message(tr('You'), choice_text).choice_buttons
        # Native questions do not depend on selection words in the prose. Use
        # the reported diagnostic wording, then exercise Codex's resolution event.
        native_question = {'id': 'native-question', 'method': 'item/tool/requestUserInput', 'params': {
            'threadId': 'test-thread', 'turnId': 'test-turn', 'itemId': 'diagnostic',
            'questions': [{'id': 'appearance', 'header': 'Appearance',
                           'question': 'What does the stuck icon look like in the ChatGPT tab?',
                           'options': [{'label': text, 'description': ''} for text in (
                               'Firefox’s usual page-loading spinner',
                               'A special ChatGPT animation or changing logo', 'I’m not sure')]}]}}
        window.event(native_question)
        panel = window.question_windows['native-question']
        options = [w for w in widgets(panel) if isinstance(w, Gtk.CheckButton)]
        assert len(options) == 3 and all(w.get_sensitive() for w in options)
        assert window.attention_waiting
        options[0].set_active(True)
        before = backend.respond.call_count
        next(w for w in widgets(panel) if isinstance(w, Gtk.Button) and w.get_label() == tr('Reply')).emit('clicked')
        backend.respond.assert_called_with('native-question', {
            'answers': {'appearance': {'answers': ['Firefox’s usual page-loading spinner']}}}, None)
        assert backend.respond.call_count == before + 1
        resolved = {'method': 'serverRequest/resolved', 'params': {
            'threadId': 'test-thread', 'requestId': 'native-question'}}
        window.event(resolved)
        assert not window.question_windows and not window.attention_waiting
        # Cancellation before an answer also closes the panel; repeated events
        # cannot send an answer on the user's behalf or clear another thread.
        window.event(native_question)
        window.event({'method': 'serverRequest/resolved', 'params': {
            'threadId': 'another-thread', 'requestId': 'native-question'}})
        assert window.question_windows
        window.event(resolved)
        window.event(resolved)
        assert not window.question_windows and not window.attention_waiting
        assert backend.respond.call_count == before + 1
        # A rejected/unknown steering delivery must not mark the active turn idle.
        assert window.submit('Keep working after a failed steer')
        wait(lambda: not window.delivery_pending)
        backend.steer.side_effect = RuntimeError('Simulated steering timeout')
        uncertain = window.add_message(tr('Agent'), 'Which option?\n\n- First\n- Second')
        uncertain.choice_buttons[0].emit('clicked')
        wait(lambda: not window.delivery_pending)
        assert window.busy and window.queue_paused
        kept = window.outbox.for_agent('codex')[0]
        assert kept['state'] == 'uncertain'
        assert kept['text'] == 'Which option?\nFirst' and not uncertain.choice_buttons[0].get_sensitive()
        window.remove_queued(kept)
        backend.steer.side_effect = None
        window.queue_message('Keep this after stopping')
        window.stop()
        window.event({'method': 'turn/completed', 'params': {'turn': {'status': 'interrupted'}}})
        assert not window.busy and window.queue_paused
        assert len(window.outbox.for_agent('codex')) == 1
        window.remove_queued(window.outbox.for_agent('codex')[0])
        # A completion can reach GTK before the worker receives turn/start's ACK.
        # Do not start another request until that first ACK is handled.
        release_start = threading.Event()
        def slow_ack(*_):
            release_start.wait(5)
            return {'turn': {'id': 'fast-turn'}}
        backend.turn.side_effect = slow_ack
        window.queue_paused = False
        calls_before = backend.turn.call_count
        assert window.submit('Response before acknowledgement')
        wait(lambda: backend.turn.call_count == calls_before + 1)
        window.queue_message('After the fast response')
        window.event({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
        assert not window.busy and window.delivery_pending
        assert backend.turn.call_count == calls_before + 1
        release_start.set()
        wait(lambda: backend.turn.call_count == calls_before + 2 and not window.delivery_pending)
        assert window.busy and not window.outbox.for_agent('codex')
        backend.turn.side_effect = None
        window.event({'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}})
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
        # Permission choices belong to the selected agent, persist to disk and
        # must reach both a new Claude process and the terminal resume path.
        window.settings['permissions'] = 'read'
        window.setup()
        labels = [w.get_text() for w in widgets(window.setup_panel) if isinstance(w, Gtk.Label)]
        assert tr('Claude permissions') in labels and tr('Codex permissions') not in labels
        permission_select = next(w for w in widgets(window.setup_panel) if isinstance(w, Gtk.DropDown))
        permission_select.set_selected(1)
        next(w for w in widgets(window.setup_panel) if isinstance(w, Gtk.Button) and
             w.get_label() == tr('Use repository')).emit('clicked')
        saved = json.loads(window.settings_file.read_text())
        assert saved['claude_permissions'] == 'default' and saved['permissions'] == 'read'
        with patch("app.ClaudeClient", side_effect=fake_claude):
            assert window.submit("Ask a structured question")
            wait(lambda: bool(window.question_windows))
            assert clients[-1].permission_mode == 'default'
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
            review = next(w for w in widgets(window.setup_panel) if isinstance(w, Gtk.Expander)).get_child()
            assert not review.get_sensitive()
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
            assert window.submit('Show inline alternatives')
            wait(lambda: window.reply_body and window.reply_body.choice_buttons and not window.delivery_pending)
            inline_body = window.reply_body
            old_turn, old_pid = window.turn_id, window.client.process.pid
            queued = window.queue_message('After choosing a color')
            window.queue_paused = True
            inline_body.choice_buttons[0].emit('clicked')
            inline_body.choice_buttons[1].emit('clicked')
            wait(lambda: not window.busy and not window.delivery_pending)
            assert window.client.process.pid == old_pid and window.thread_id == session_id
            assert window.messages[-1]['text'] == 'Received inline answer'
            assert window.outbox.for_agent('claude') == [queued]
            assert not inline_body.choice_buttons[0].get_sensitive()
            window.remove_queued(queued)
            previous_client = window.client
            window.setup()
            permission_select = next(w for w in widgets(window.setup_panel) if isinstance(w, Gtk.DropDown))
            permission_select.set_selected(3)
            next(w for w in widgets(window.setup_panel) if isinstance(w, Gtk.Button) and
                 w.get_label() == tr('Use repository')).emit('clicked')
            assert window.submit('Task to redirect')
            wait(lambda: bool(window.question_windows) and not window.delivery_pending)
            assert window.client is not previous_client and window.client.permission_mode == 'plan'
            assert window.thread_id == session_id
            assert window.settings['permissions'] == 'read'
            old_turn, old_pid = window.turn_id, window.client.process.pid
            window.queue_message('Later follow-up')
            assert window.steer('New direction in the same conversation')
            wait(lambda: window.turn_id and window.turn_id != old_turn and
                 bool(window.question_windows) and not window.delivery_pending)
            assert window.client.process.pid == old_pid and window.thread_id == session_id
            assert [entry['text'] for entry in window.outbox.for_agent('claude')] == ['Later follow-up']
            window.stop()
            wait(lambda: not window.busy)
            assert window.queue_paused and len(window.outbox.for_agent('claude')) == 1
            window.remove_queued(window.outbox.for_agent('claude')[0])
            with patch('app.terminal') as terminal:
                window.resume_in_terminal()
                terminal.assert_called_once_with([window.executables['claude'], '--permission-mode', 'plan',
                                                  '--resume=' + session_id])
            window.present()
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
        # Every external adapter can keep and copy follow-ups while its PTY runs.
        # Copying must never inject Enter, text, or permission answers into a PTY.
        terminal_placeholder = Gtk.Box()
        window.content.add_named(terminal_placeholder, 'terminal')
        for agent in AGENTS.keys() - {'codex', 'claude'}:
            window.executables[agent] = sys.executable
            window.agent_select.set_selected(window.agent_ids.index(agent))
            secret = "PRIVATE-REQUEST-" + agent + "\n' $(never-run) ç --option"
            window.vte = Mock()
            with patch('app.Vte', Mock()):
                assert window.launch_external(secret)
            launch = window.vte.spawn_async.call_args.kwargs
            assert not any(secret in arg or 'PRIVATE-REQUEST-' in arg for arg in launch['argv'] + launch['envv'])
            assert '--prompt' not in launch['argv'] and '--message' not in launch['argv']
            launch['callback'](window.vte, 12345, None)
            assert window.external_prompt_area.get_visible()
            with patch.object(window, 'copy_to_terminal') as copy:
                window.copy_request_button.emit('clicked')
                copy.assert_called_once_with(secret)
            window.vte.feed_child.assert_not_called()
            window.terminal_pid = None
            launch['callback'](window.vte, -1, RuntimeError('Fixture VTE failure'))
            assert not window.busy and window.external_prompt == secret
            with patch.object(window, 'ensure_vte', return_value=False), patch('app.terminal') as terminal:
                assert window.launch_external(secret)
                assert not any('PRIVATE-REQUEST-' in arg for arg in terminal.call_args.args[0])
                assert window.external_prompt == secret
            with patch.object(window, 'ensure_vte', return_value=False), patch('app.terminal', side_effect=OSError('Launch failed')):
                assert not window.launch_external(secret)
                assert not window.busy
            window.terminal_pid = 12345
            window.vte = Mock()
            window.update_buttons()
            assert window.input_area.get_sensitive() and window.send_button.get_sensitive()
            window.input.get_buffer().set_text('External follow-up\nwith another line')
            window.send(immediate=True)
            assert len(window.outbox.for_agent(agent)) == 1
            window.vte.feed_child.assert_not_called()
            window.vte.paste_text.assert_not_called()
            assert window.popup_key(None, Gdk.KEY_Escape, 0, 0) is False
            window.terminal_pid = None
            window.remove_queued(window.outbox.for_agent(agent)[0])
            window.vte = None
        window.content.remove(terminal_placeholder)
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
print("UI smoke passed: layout, questions, resume, cancellation, native queues and steering, acknowledgement races, all external queues, terminal, settings, dismissal")
