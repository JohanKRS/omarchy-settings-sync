#!/usr/bin/env python3
"""GTK4 shell for Codex conversations and interactive Omarchy agent CLIs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import threading
import time

from ctypes import CDLL
CDLL("libgtk4-layer-shell.so")
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango
from gi.repository import Gtk4LayerShell as LayerShell
try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte
except (ValueError, ImportError):
    Vte = None

from i18n import tr
from theme import Theme
from context import begin_task, finish_task

from core import (
    AGENTS, ROOT, CodexClient, cached_models, codex_defaults, default_agent, external_command,
    make_prompt, paths, private_write, read_json, repository_url, terminal,
)

EFFORT_LABELS = {
    "": tr('Default'), "none": tr('None'), "minimal": tr('Minimal'), "low": tr('Low'),
    "medium": tr('Medium'), "high": tr('High'), "xhigh": tr('Very high'), "max": tr('Maximum'), "ultra": "Ultra",
}
MODEL_AGENTS = {"codex", "claude", "opencode", "gemini", "copilot", "cursor-agent", "pi", "omp"}


def ui(callback, *args):
    def invoke():
        callback(*args)
        return False
    GLib.idle_add(invoke)


def label(text="", css=None):
    widget = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
    widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if css:
        widget.add_css_class(css)
    return widget


def box(vertical=True, spacing=8):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                   spacing=spacing)


def dropdown(values):
    widget = Gtk.DropDown.new_from_strings(values)
    factory = Gtk.SignalListItemFactory()
    def setup(_factory, item):
        item.set_child(Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=19))
    def bind(_factory, item):
        text = item.get_item().get_string()
        item.get_child().set_text(text)
        item.get_child().set_tooltip_text(text)
    factory.connect("setup", setup)
    factory.connect("bind", bind)
    widget.set_factory(factory)
    return widget


class Panel(Gtk.Box):
    """Keep setup and approvals inside the app, including under tiling WMs."""
    def __init__(self, owner, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.owner = owner
        self.on_close = self.destroy
        self.add_css_class("panel")
        for side in ("top", "bottom", "start", "end"):
            getattr(self, "set_margin_" + side)(12)
        header = box(False)
        heading = label(title, "title")
        heading.set_hexpand(True)
        header.append(heading)
        close = Gtk.Button(icon_name="window-close-symbolic")
        close.connect("clicked", lambda *_: self.on_close())
        header.append(close)
        self.append(header)
        self.scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.append(self.scroll)

    def set_content(self, content):
        self.scroll.set_child(content)

    def present(self):
        self.owner.main_content.set_sensitive(False)
        self.owner.overlay.add_overlay(self)
        self.owner.panels.append(self)
        self.grab_focus()

    def destroy(self):
        if self in self.owner.panels:
            self.owner.panels.remove(self)
            self.owner.overlay.remove_overlay(self)
        self.owner.main_content.set_sensitive(not self.owner.panels)


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Agent Settings · Omarchy")
        self.set_decorated(False)
        self.add_css_class("popup-host")
        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "omarchy-agent-settings")
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_exclusive_zone(self, -1)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.EXCLUSIVE)
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(self, edge, True)
        self.popup_bounds = (0, 0, 560, 640)
        self.set_icon_name("preferences-system-symbolic")
        self.locations = paths()
        self.settings_file = self.locations["config"] / "settings.json"
        self.settings = read_json(self.settings_file, {})
        self.client = None
        self.ready = False
        self.busy = False
        self.thread_id = self.settings.get("thread_id")
        self.thread_loaded = False
        self.turn_id = None
        self.models = cached_models()
        self.cards = {}
        self.message_entries = {}
        self.tool_items = {}
        self.panels = []
        self.setup_panel = None
        self.messages = []
        self.question_windows = {}
        self.terminal_pid = None
        self.pending_sync = False
        self.pending_create = False
        self.last_prompt = ""
        self.active_task = None
        self.session_file = self.locations["state"] / "conversation.json"
        self._build()
        self.theme = Theme(self)
        self.theme_timer = GLib.timeout_add_seconds(2, self.theme.refresh)
        self.connect("close-request", self.close_window)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.popup_key)
        self.add_controller(keys)
        clicks = Gtk.GestureClick()
        clicks.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        clicks.connect("pressed", self.popup_click)
        self.add_controller(clicks)
        self.place_popup()
        for message in read_json(self.session_file, [])[-100:]:
            self.add_message(message["role"], message["text"], save=False)
        self.refresh_sync_label()
        self.agent_changed()
        if not self.settings.get("repository"):
            GLib.idle_add(self.setup)

    def _build(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
            .title { font-size: 23px; font-weight: 700; }
            .muted { opacity: .68; }
            .message { padding: 14px; border-radius: 12px; background: alpha(@theme_fg_color, .055); }
            .user-message { background: alpha(@accent_bg_color, .14); }
            .card-role { font-size: 11px; font-weight: bold; opacity: .6; }
            .toolbar { padding: 12px; border-radius: 12px; background: alpha(@theme_fg_color, .04); }
            .composer { padding: 10px; border-radius: 10px; background: alpha(@theme_fg_color, .04); }
            textview, textview text { background: transparent; }
            .status { font-size: 12px; }
            .panel { background: @theme_bg_color; padding: 16px; border-radius: 12px; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.popup_card = box(spacing=0)
        self.popup_card.add_css_class("popup-card")
        header = box(False, 10)
        header.add_css_class("popup-header")
        icon = Gtk.Image.new_from_icon_name("preferences-system-symbolic")
        icon.set_pixel_size(26)
        header.append(icon)
        title = label("Agent Settings", "title")
        title.set_hexpand(True)
        header.append(title)
        settings_button = Gtk.Button(icon_name="emblem-system-symbolic", tooltip_text=tr('Settings'))
        settings_button.connect("clicked", lambda *_: self.setup())
        self.new_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=tr('New chat'))
        self.new_button.connect("clicked", lambda *_: self.new_chat())
        header.append(self.new_button)
        header.append(settings_button)
        close = Gtk.Button(icon_name="window-close-symbolic")
        close.connect("clicked", lambda *_: self.dismiss())
        header.append(close)
        self.popup_card.append(header)
        outer = box(spacing=10)
        for side in ("top", "bottom", "start", "end"):
            getattr(outer, "set_margin_" + side)(14)
        self.main_content = outer
        self.overlay = Gtk.Overlay(child=outer)
        self.overlay.set_vexpand(True)
        self.popup_card.append(self.overlay)
        self.popup_canvas = Gtk.Fixed()
        self.popup_canvas.put(self.popup_card, 0, 0)
        self.set_child(self.popup_canvas)
        hero = box(False, 12)
        headings = box(spacing=3)
        headings.set_hexpand(True)
        self.repo_label = label("", "muted")
        self.repo_label.set_wrap(False)
        self.repo_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        headings.append(self.repo_label)
        hero.append(headings)
        self.sync_button = Gtk.Button(label=tr('Sync'), valign=Gtk.Align.CENTER)
        self.sync_button.add_css_class("suggested-action")
        self.sync_button.connect("clicked", lambda *_: self.sync())
        hero.append(self.sync_button)
        outer.append(hero)
        controls = box(False, 10)
        controls.add_css_class("toolbar")
        self.agent_ids = list(AGENTS)
        self.agent_select = dropdown([AGENTS[a] + ("" if shutil.which(a) else tr(' · unavailable')) for a in self.agent_ids])
        current = self.settings.get("agent", default_agent())
        self.agent_select.set_selected(self.agent_ids.index(current) if current in self.agent_ids else 0)
        self.agent_select.connect("notify::selected", lambda *_: self.agent_changed())
        controls.append(self.control(tr('Agent'), self.agent_select))
        self.model_select = dropdown([tr('Default')])
        self.model_select.connect("notify::selected", lambda *_: self.model_changed())
        self.external_model = Gtk.Entry(placeholder_text=tr('Default'))
        self.model_stack = Gtk.Stack()
        self.model_stack.add_named(self.model_select, "codex")
        self.model_stack.add_named(self.external_model, "external")
        self.model_stack.set_hexpand(True)
        controls.append(self.control(tr('Model'), self.model_stack, expand=True))
        self.effort_select = dropdown([tr('Default')])
        controls.append(self.control(tr('Effort'), self.effort_select))
        outer.append(controls)
        self.content = Gtk.Stack()
        self.content.set_vexpand(True)
        self.scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.transcript = box(spacing=10)
        self.scroll.set_child(self.transcript)
        self.content.add_named(self.scroll, "chat")
        self.vte = None
        if Vte:
            self.vte = Vte.Terminal()
            self.vte.set_scrollback_lines(10000)
            self.vte.set_font(Pango.FontDescription.from_string("monospace 11"))
            self.vte.set_hexpand(True)
            self.vte.set_vexpand(True)
            self.vte.connect("child-exited", self.child_exited)
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self.terminal_key)
            self.vte.add_controller(keys)
            self.content.add_named(self.vte, "terminal")
        outer.append(self.content)
        self.input_area = box(spacing=8)
        self.input_area.add_css_class("composer")
        self.input = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.input.set_top_margin(8)
        self.input.set_left_margin(8)
        input_scroll = Gtk.ScrolledWindow(min_content_height=54, max_content_height=150)
        input_overlay = Gtk.Overlay(child=self.input)
        self.placeholder = label(tr("Change your system…"), "muted")
        self.placeholder.set_halign(Gtk.Align.START)
        self.placeholder.set_valign(Gtk.Align.START)
        self.placeholder.set_margin_start(8)
        self.placeholder.set_margin_top(8)
        self.placeholder.set_can_target(False)
        input_overlay.add_overlay(self.placeholder)
        self.input.get_buffer().connect("changed", lambda b: self.placeholder.set_visible(b.get_char_count() == 0))
        input_scroll.set_child(input_overlay)
        self.input_area.append(input_scroll)
        self.input.set_tooltip_text(tr("Change your system…"))
        row = box(False, 8)
        self.publish = Gtk.CheckButton(label=tr('Push changes'))
        self.publish.set_active(self.settings.get("publish", True))
        self.publish.set_hexpand(True)
        row.append(self.publish)
        self.stop_button = Gtk.Button(label=tr('Stop'), sensitive=False)
        self.stop_button.connect("clicked", lambda *_: self.stop())
        self.send_button = Gtk.Button(label=tr('Send'))
        self.send_button.add_css_class("suggested-action")
        self.send_button.connect("clicked", lambda *_: self.send())
        row.append(self.send_button)
        self.input_area.append(row)
        outer.append(self.input_area)
        bottom = box(False, 8)
        self.spinner = Gtk.Spinner()
        bottom.append(self.spinner)
        self.status = label(tr('Ready'), "status")
        self.status.set_hexpand(True)
        bottom.append(self.status)
        bottom.append(self.stop_button)
        self.terminal_button = Gtk.Button(icon_name="utilities-terminal-symbolic", tooltip_text=tr('Open in terminal'))
        self.terminal_button.add_css_class("flat")
        self.terminal_button.connect("clicked", lambda *_: self.open_terminal())
        bottom.append(self.terminal_button)
        outer.append(bottom)

    def control(self, title, widget, expand=False):
        container = box(spacing=4)
        container.set_hexpand(expand)
        container.append(label(title, "muted"))
        container.append(widget)
        return container

    def place_popup(self, monitor_name="", anchor_x=None, edge="top", bar_size=26):
        monitors = Gdk.Display.get_default().get_monitors()
        monitor = next((monitors.get_item(i) for i in range(monitors.get_n_items())
                        if monitors.get_item(i).get_connector() == monitor_name), None)
        if monitor is None:
            monitor = monitors.get_item(0)
        LayerShell.set_monitor(self, monitor)
        geometry = monitor.get_geometry()
        width = min(560, max(320, geometry.width - 10))
        height = min(660, max(300, geometry.height - bar_size - 10))
        margin = 5
        x = geometry.width - width - margin if anchor_x is None else max(margin, min(anchor_x - width / 2, geometry.width - width - margin))
        y = bar_size + margin
        if edge == "bottom":
            y = geometry.height - height - bar_size - margin
        elif edge in ("left", "right"):
            x = bar_size + margin if edge == "left" else geometry.width - width - bar_size - margin
            y = margin
        self.popup_bounds = (x, y, width, height)
        self.popup_card.set_size_request(width, height)
        self.popup_canvas.move(self.popup_card, x, y)

    def popup_key(self, _controller, key, _code, _state):
        if key == Gdk.KEY_Escape:
            self.dismiss()
            return True
        return False

    def popup_click(self, gesture, _count, x, y):
        left, top, width, height = self.popup_bounds
        if not (left <= x <= left + width and top <= y <= top + height):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dismiss()

    def dismiss(self):
        self.save_settings()
        self.set_visible(False)

    def agent(self):
        return self.agent_ids[self.agent_select.get_selected()]

    def selection(self):
        if self.agent() == "codex":
            index = self.model_select.get_selected()
            model = self.model_values[index] if index < len(self.model_values) else ""
        else:
            model = self.external_model.get_text().strip() if self.agent() in MODEL_AGENTS else ""
        index = self.effort_select.get_selected()
        effort = self.effort_values[index] if index < len(self.effort_values) else ""
        return model, effort

    def save_settings(self):
        model, effort = self.selection()
        self.settings.update(agent=self.agent(), publish=self.publish.get_active(), thread_id=self.thread_id)
        self.settings.setdefault("selections", {})[self.agent()] = {"model": model, "effort": effort}
        private_write(self.settings_file, self.settings)

    def agent_changed(self):
        if not hasattr(self, "content"):
            return
        agent = self.agent()
        self.model_stack.set_visible_child_name("codex" if agent == "codex" else "external")
        self.external_model.set_sensitive(agent in MODEL_AGENTS)
        if agent == "codex":
            self.content.set_visible_child_name("chat")
            self.update_models(self.models)
            if not self.client:
                self.connect_codex()
        else:
            self.content.set_visible_child_name("terminal" if self.vte else "chat")
            saved = self.settings.get("selections", {}).get(agent, {})
            self.external_model.set_text(saved.get("model", ""))
            efforts = ["", "low", "medium", "high", "xhigh", "max"] if agent == "claude" else [""]
            self.set_efforts(efforts, saved.get("effort", ""))
            self.status.set_text(tr('Ready · ') + AGENTS[agent])
        self.input_area.set_visible(not self.terminal_pid)
        self.update_buttons()

    def update_models(self, models):
        self.models = models
        self.model_values = [""] + [m["model"] for m in models]
        self.model_select.set_model(Gtk.StringList.new([tr('Default')] + [m["displayName"] for m in models]))
        saved = self.settings.get("selections", {}).get("codex", {})
        selected = saved.get("model", codex_defaults().get("model", ""))
        self.model_select.set_selected(self.model_values.index(selected) if selected in self.model_values else 0)
        self.model_changed()

    def model_changed(self):
        if not hasattr(self, "effort_select") or not hasattr(self, "model_values"):
            return
        index = self.model_select.get_selected()
        model = self.models[index - 1] if 0 < index <= len(self.models) else {}
        values = [""] + [e.get("reasoningEffort", e.get("effort")) for e in model.get("supportedReasoningEfforts", [])]
        saved = self.settings.get("selections", {}).get("codex", {})
        desired = saved.get("effort", codex_defaults().get("model_reasoning_effort", ""))
        self.set_efforts(values, desired)

    def set_efforts(self, values, desired):
        self.effort_values = list(dict.fromkeys(v for v in values if v is not None))
        self.effort_select.set_model(Gtk.StringList.new([EFFORT_LABELS.get(v, v) for v in self.effort_values]))
        self.effort_select.set_selected(self.effort_values.index(desired) if desired in self.effort_values else 0)

    def worker(self, operation, done=None):
        def work():
            try:
                result = operation()
                if done:
                    ui(done, result)
            except Exception as error:
                ui(self.failure, str(error))
        threading.Thread(target=work, daemon=True).start()

    def connect_codex(self):
        if not shutil.which("codex"):
            self.status.set_text(tr('Install Codex or choose another agent.'))
            return
        self.status.set_text(tr('Connecting…'))
        self.client = CodexClient(lambda message: ui(self.event, message))
        def connect():
            self.client.start()
            return self.client.models()
        def connected(models):
            self.ready = True
            self.models = models
            if self.agent() == "codex":
                self.update_models(models)
                self.status.set_text(tr('Codex · ') + self.mode_label())
            self.update_buttons()
            if self.pending_sync:
                self.pending_sync = False
                self.sync()
            elif self.pending_create:
                self.pending_create = False
                self.submit(tr('Create my configuration repository'), create=True)
        self.worker(connect, connected)

    def mode_label(self):
        return {"auto": tr('auto review'), "ask": tr('ask for approval'), "read": tr('read only')}.get(
            self.settings.get("permissions", "auto"), tr('auto review'))

    def update_buttons(self):
        native = self.agent() == "codex"
        available = not self.busy and not self.terminal_pid and (self.ready or not native)
        self.send_button.set_sensitive(available)
        self.sync_button.set_sensitive(available)
        self.new_button.set_sensitive(not self.busy and not self.terminal_pid)
        self.agent_select.set_sensitive(not self.busy and not self.terminal_pid)
        self.model_stack.set_sensitive(not self.busy and not self.terminal_pid)
        self.effort_select.set_sensitive(not self.busy and not self.terminal_pid)
        self.stop_button.set_sensitive(self.busy or bool(self.terminal_pid))
        self.stop_button.set_visible(self.busy or bool(self.terminal_pid))
        self.spinner.set_spinning(self.busy)

    def add_message(self, role, text, identifier=None, save=True):
        card = box(spacing=6)
        card.add_css_class("message")
        if role == tr('You'):
            card.add_css_class("user-message")
        card.append(label(role, "card-role"))
        body = label(text)
        body.set_hexpand(True)
        card.append(body)
        self.transcript.append(card)
        if identifier:
            self.cards[identifier] = body
        entry = {"role": role, "text": text}
        self.messages.append(entry)
        if identifier:
            self.message_entries[identifier] = entry
        if save:
            self.save_conversation()
        self.scroll_down()
        return body

    def save_conversation(self):
        private_write(self.session_file, self.messages[-150:])

    def scroll_down(self):
        def adjust():
            adj = self.scroll.get_vadjustment()
            adj.set_value(max(0, adj.get_upper() - adj.get_page_size()))
            return False
        GLib.idle_add(adjust)

    def failure(self, message):
        self.finish_activity("failed")
        self.busy = False
        self.turn_id = None
        self.status.set_text(tr('Needs attention'))
        self.add_message(tr('Error'), message)
        self.update_buttons()

    def send(self, *_):
        buffer = self.input.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()
        if text:
            if self.submit(text):
                buffer.set_text("")

    def sync(self):
        if not self.settings.get("repository"):
            self.setup()
            return
        if self.agent() == "codex" and not self.ready:
            self.pending_sync = True
            return
        self.submit(tr('Sync'), sync=True)

    def submit(self, text, sync=False, create=False):
        if self.busy or self.terminal_pid:
            self.status.set_text(tr('Stop the current task first.'))
            return False
        if not self.settings.get("repository"):
            self.setup()
            return False
        self.save_settings()
        try:
            prompt = make_prompt(
                text, repository=self.settings["repository"], branch=self.settings.get("branch", ""),
                sync=sync, publish=self.publish.get_active() or create, create=create,
                thread_id=self.thread_id if self.agent() == "codex" else None,
                locations=self.locations,
            )
        except ValueError as error:
            self.failure(str(error))
            return False
        self.last_prompt = prompt
        self.active_task = begin_task(
            self.locations, self.settings["repository"], self.settings.get("branch", ""),
            "create" if create else "sync" if sync else "change", self.agent(), private_write,
        )
        if self.agent() != "codex":
            self.launch_external(prompt)
            return True
        if not self.ready:
            self.failure(tr('Waiting for Codex…'))
            return False
        self.add_message(tr('You'), text)
        self.busy = True
        self.status.set_text(tr('Working…'))
        self.update_buttons()
        model, effort = self.selection()
        def execute():
            if not self.thread_loaded:
                result = self.client.start_thread(model, self.settings.get("permissions", "auto"), self.thread_id)
                self.thread_id = result["thread"]["id"]
                self.thread_loaded = True
                ui(self.save_settings)
            return self.client.turn(self.thread_id, prompt, model, effort)
        self.worker(execute, lambda r: self.started(r["turn"]["id"]))
        return True

    def finish_activity(self, status):
        finish_task(self.active_task, status, private_write)
        self.active_task = None

    def started(self, turn_id):
        if self.busy:
            self.turn_id = turn_id

    def event(self, message):
        method = message.get("method", "")
        params = message.get("params", {})
        if "id" in message:
            self.request_from_agent(message)
            return
        if params.get("threadId") and self.thread_id and params["threadId"] != self.thread_id:
            return
        if method == "turn/started":
            self.turn_id = params["turn"]["id"]
        elif method == "item/agentMessage/delta":
            identifier = params["itemId"]
            if identifier not in self.cards:
                self.add_message(tr('Agent'), "", identifier)
            current = self.cards[identifier].get_text()
            self.cards[identifier].set_text(current + params.get("delta", ""))
            self.scroll_down()
        elif method == "item/started":
            item = params.get("item", {})
            if item.get("id"):
                self.tool_items[item["id"]] = item
            kind = item.get("type", "")
            if kind == "commandExecution":
                self.status.set_text(tr('Running: ') + item.get("command", "")[:110])
            elif kind == "mcpToolCall":
                self.status.set_text(tr('Tool: ') + str(item.get("tool", item.get("server", "")))[:110])
        elif method == "item/completed":
            item = params.get("item", {})
            identifier = item.get("id")
            if item.get("type") == "agentMessage":
                text = item.get("text", "")
                if identifier in self.cards:
                    self.cards[identifier].set_text(text)
                    # Store complete messages, not every streaming fragment.
                    self.message_entries[identifier]["text"] = text
                    self.save_conversation()
                else:
                    self.add_message(tr('Agent'), text, identifier)
        elif method == "turn/completed":
            self.busy = False
            self.turn_id = None
            turn = params.get("turn", {})
            if turn.get("error"):
                self.failure(str(turn["error"].get("message", turn["error"])))
            else:
                self.status.set_text(tr('Stopped') if turn.get("status") == "interrupted" else tr('Done'))
                self.finish_activity("interrupted" if turn.get("status") == "interrupted" else "response_completed")
            self.update_buttons()
            self.refresh_sync_label()
            self.save_settings()
        elif method == "client/disconnected":
            self.ready = False
            self.failure(tr('Disconnected. Reopen the window to reconnect.'))
        elif method == "error":
            self.add_message("Codex", str(params.get("message", params.get("error", params))))
        elif method == "item/autoApprovalReview/started":
            self.status.set_text(tr('Reviewing approval…'))

    def stop(self):
        if self.terminal_pid:
            # A real keypress in the PTY preserves the agent's interrupt semantics.
            self.vte.feed_child(b"\x03")
            self.status.set_text(tr('Interrupt sent. Use /exit to close the CLI.'))
        elif self.turn_id:
            self.worker(lambda: self.client.request("turn/interrupt", {"threadId": self.thread_id, "turnId": self.turn_id}))

    def request_from_agent(self, message):
        identifier, method, params = message["id"], message["method"], message.get("params", {})
        dialog = Panel(self, tr('Your input'))
        content = box(spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, "set_margin_" + side)(20)
        dialog.set_content(content)
        answered = [False]
        def answer(result=None, error=None):
            if answered[0]:
                return
            answered[0] = True
            self.client.respond(identifier, result, error)
            self.question_windows.pop(identifier, None)
            dialog.destroy()
        buttons = box(False, 8)
        content.append(label(params.get("reason") or params.get("message") or tr('Review this request.')))
        decline = {"decision": "decline"}
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            item = self.tool_items.get(params.get("itemId"), {})
            details = params.get("command") or item.get("changes") or params
            content.append(label(details if isinstance(details, str) else json.dumps(details, ensure_ascii=False, indent=2)))
            if params.get("cwd"):
                content.append(label(params["cwd"], "muted"))
            available = params.get("availableDecisions")
            approve = {"decision": "accept"} if available is None or "accept" in available else None
        elif method == "item/permissions/requestApproval":
            content.append(label(json.dumps(params.get("permissions", {}), ensure_ascii=False, indent=2)))
            approve = {"permissions": params.get("permissions", {}), "scope": "turn"}
            decline = {"permissions": {}, "scope": "turn"}
        elif method == "item/tool/requestUserInput":
            entries = {}
            for q in params.get("questions", []):
                content.append(label(q["question"]))
                entry = Gtk.Entry(visibility=not q.get("isSecret", False))
                entries[q["id"]] = entry
                for option in q.get("options") or []:
                    choice = Gtk.Button(label=option["label"])
                    choice.set_tooltip_text(option.get("description", ""))
                    choice.connect("clicked", lambda _, e=entry, value=option["label"]: e.set_text(value))
                    content.append(choice)
                content.append(entry)
            approve = lambda: {"answers": {key: {"answers": [value.get_text()]} for key, value in entries.items()}}
            decline = {"answers": {}}
        elif method == "mcpServer/elicitation/request":
            decline = {"action": "decline"}
            if params.get("mode") == "url":
                url = params.get("url", "")
                if url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
                    content.append(Gtk.LinkButton(uri=url, label=tr('Open in browser')))
                approve = {"action": "accept"}
            elif params.get("mode") in ("form", "openai/form", "openaiForm"):
                schema = params.get("requestedSchema", {})
                content.append(label(tr('Requested fields')))
                content.append(label(json.dumps(schema, ensure_ascii=False, indent=2)))
                entry = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
                entry.set_size_request(-1, 100)
                entry.get_buffer().set_text("{}")
                content.append(entry)
                validation = label("")
                content.append(validation)
                def form_answer():
                    b = entry.get_buffer()
                    try:
                        value = json.loads(b.get_text(b.get_start_iter(), b.get_end_iter(), False))
                        if not isinstance(value, dict):
                            raise ValueError(tr('Enter a JSON object.'))
                        missing = [key for key in schema.get("required", []) if key not in value]
                        if missing:
                            raise ValueError(tr('Required: ') + ", ".join(missing))
                        return {"action": "accept", "content": value}
                    except ValueError as error:
                        validation.set_text(str(error))
                        return None
                approve = form_answer
            else:
                content.append(label(tr('Verification required. Continue in the terminal.')))
                approve = None
        else:
            content.append(label(tr('Continue this request in the terminal.')))
            approve = None
            decline = None
        cancel = Gtk.Button(label=tr('Decline') if "Approval" in method else tr('Cancel'))
        cancel.connect("clicked", lambda *_: answer(decline, None if decline is not None else {"code": -32601, "message": "Unsupported request"}))
        buttons.append(cancel)
        if approve is not None:
            accept = Gtk.Button(label=tr('Reply') if callable(approve) else tr('Allow once'))
            accept.add_css_class("suggested-action")
            def accept_clicked(*_):
                value = approve() if callable(approve) else approve
                if value is not None:
                    answer(value)
            accept.connect("clicked", accept_clicked)
            buttons.append(accept)
        content.append(buttons)
        dialog.on_close = lambda: answer(decline, None if decline is not None else {"code": -32601, "message": "Unsupported request"})
        self.question_windows[identifier] = dialog
        dialog.present()

    def launch_external(self, prompt):
        agent = self.agent()
        if not shutil.which(agent):
            self.failure(tr("Install {agent} from the Omarchy agent menu.", agent=AGENTS[agent]))
            return
        model, effort = self.selection()
        command = external_command(agent, prompt, model, effort)
        if not self.vte:
            terminal(command)
            self.finish_activity("external_unverified")
            self.status.set_text(tr('Opened in terminal.'))
            return
        self.content.set_visible_child_name("terminal")
        self.vte.reset(True, True)
        self.locations["workspace"].mkdir(parents=True, exist_ok=True)
        self.busy = True
        self.update_buttons()
        environment = dict(os.environ)
        environment["TERM"] = "xterm-256color"
        if agent == "hermes":
            environment.pop("HERMES_SESSION_SOURCE", None)
        def spawned(term, pid, error, _data=None):
            self.busy = False
            if error:
                self.failure(str(error))
                return
            self.terminal_pid = pid
            self.status.set_text(AGENTS[agent] + tr(' · active'))
            self.input_area.set_visible(False)
            self.update_buttons()
            self.vte.grab_focus()
        self.vte.spawn_async(
            pty_flags=Vte.PtyFlags.DEFAULT, working_directory=str(self.locations["workspace"]),
            argv=command, envv=[f"{k}={v}" for k, v in environment.items()],
            spawn_flags=GLib.SpawnFlags.SEARCH_PATH, child_setup=None,
            timeout=-1, cancellable=None, callback=spawned,
        )

    def terminal_key(self, _controller, key, _code, state):
        shortcut = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        if state & shortcut == shortcut:
            if key in (Gdk.KEY_C, Gdk.KEY_c):
                self.vte.copy_clipboard_format(Vte.Format.TEXT)
                return True
            if key in (Gdk.KEY_V, Gdk.KEY_v):
                self.vte.paste_clipboard()
                return True
        return False

    def child_exited(self, _terminal, status):
        self.finish_activity("external_unverified")
        self.terminal_pid = None
        self.busy = False
        self.status.set_text(tr("Session ended · {status}", status=status))
        self.input_area.set_visible(True)
        self.update_buttons()
        self.refresh_sync_label()

    def open_terminal(self):
        if self.busy or self.terminal_pid:
            self.status.set_text(tr('Stop the current task first.'))
            return
        if self.agent() == "codex" and self.thread_id:
            mode = self.settings.get("permissions", "auto")
            flags = (["--approve-for-me"] if mode == "auto" else
                     ["--sandbox", "read-only" if mode == "read" else "workspace-write",
                      "--ask-for-approval", "never" if mode == "read" else "on-request"])
            terminal(["codex", *flags, "resume", self.thread_id])
        else:
            model, effort = self.selection()
            terminal(external_command(self.agent(), self.last_prompt or "Ajude-me a configurar este Omarchy.", model, effort))

    def new_chat(self):
        self.thread_id = None
        self.thread_loaded = False
        if self.messages:
            private_write(self.locations["state"] / "history" / (time.strftime("%Y%m%d-%H%M%S") + ".json"), self.messages)
        self.messages = []
        self.cards = {}
        self.message_entries = {}
        self.tool_items = {}
        while self.transcript.get_first_child():
            self.transcript.remove(self.transcript.get_first_child())
        self.save_conversation()
        self.save_settings()
        self.status.set_text(tr('Ready'))

    def refresh_sync_label(self):
        repository = self.settings.get("repository", "")
        self.repo_label.set_text(repository.removeprefix("https://github.com/").removesuffix(".git") or tr('Select repository'))
        self.repo_label.set_tooltip_text(repository)

    def setup(self):
        if self.busy or self.terminal_pid:
            self.status.set_text(tr('Finish the current task first.'))
            return False
        if self.setup_panel in self.panels:
            return False
        dialog = Panel(self, tr('Settings'))
        self.setup_panel = dialog
        content = box(spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, "set_margin_" + side)(24)
        dialog.set_content(content)
        repository = Gtk.Entry(placeholder_text=tr('owner/dotfiles'))
        repository.set_text(self.settings.get("repository", ""))
        content.append(self.control(tr('Repository'), repository))
        branch = Gtk.Entry(placeholder_text=tr('Default branch'))
        branch.set_text(self.settings.get("branch", ""))
        content.append(self.control(tr('Branch'), branch))
        agent = dropdown([AGENTS[a] for a in self.agent_ids])
        agent.set_selected(self.agent_select.get_selected())
        content.append(self.control(tr('Agent'), agent))
        mode = dropdown([tr('Auto review'), tr('Ask for approval'), tr('Read only')])
        modes = ["auto", "ask", "read"]
        current_mode = self.settings.get("permissions", "auto")
        mode.set_selected(modes.index(current_mode) if current_mode in modes else 0)
        content.append(self.control(tr('Codex permissions'), mode))
        error_label = label("")
        content.append(error_label)
        buttons = box(False, 10)
        def save(create=False):
            try:
                value = repository_url(repository.get_text())
                branch_value = branch.get_text().strip()
                if branch_value.startswith("-") or any(c.isspace() for c in branch_value):
                    raise ValueError(tr('Invalid branch.'))
            except ValueError as error:
                error_label.set_text(str(error))
                return
            changed = value != self.settings.get("repository") or branch_value != self.settings.get("branch", "")
            self.settings.update(repository=value, branch=branch_value, permissions=modes[mode.get_selected()])
            self.thread_loaded = False
            self.agent_select.set_selected(agent.get_selected())
            if changed:
                self.new_chat()
            self.save_settings()
            self.refresh_sync_label()
            dialog.destroy()
            if create:
                if self.agent() == "codex" and not self.ready:
                    self.pending_create = True
                    self.status.set_text(tr('Connecting…'))
                else:
                    self.submit(tr('Create my configuration repository'), create=True)
        existing = Gtk.Button(label=tr('Use repository'))
        existing.add_css_class("suggested-action")
        existing.connect("clicked", lambda *_: save())
        create = Gtk.Button(label=tr('Create with agent'))
        create.connect("clicked", lambda *_: save(True))
        buttons.append(existing)
        buttons.append(create)
        content.append(buttons)
        dialog.present()
        return False

    def close_window(self, *_):
        self.dismiss()
        return True


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.omarchy.AgentSettings",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = SettingsWindow(self)
        self.window.present()

    def do_command_line(self, command_line):
        arguments = command_line.get_arguments()
        if "--quit" in arguments:
            if self.window and (self.window.busy or self.window.terminal_pid):
                return 1
            if self.window and self.window.client:
                self.window.client.close()
            self.quit()
            return 0
        options = dict(arg[2:].split("=", 1) for arg in arguments if arg.startswith("--") and "=" in arg)
        if self.window and self.window.get_visible() and "--toggle" in arguments and "--sync" not in arguments:
            self.window.dismiss()
            return 0
        if not self.window:
            self.window = SettingsWindow(self)
        try:
            self.window.place_popup(
                options.get("monitor", ""), float(options["anchor-x"]) if "anchor-x" in options else None,
                options.get("edge", "top"), int(options.get("bar-size", 26)),
            )
        except ValueError:
            return 1
        self.window.present()
        if "--sync" in arguments:
            GLib.idle_add(self.window.sync)
        return 0


if __name__ == "__main__":
    raise SystemExit(Application().run(sys.argv))
