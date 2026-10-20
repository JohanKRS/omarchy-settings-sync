#!/usr/bin/env python3
"""GTK4 panel for native Codex/Claude conversations and Omarchy agent CLIs."""
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
Vte = None  # Load the terminal library only when an external agent needs it.

from i18n import tr
from theme import Theme
from context import begin_task, finish_task
from catalog import MODEL_AGENTS, DISCOVERY_AGENTS, agent_executable, discover_models
from claude_client import ClaudeClient
from outbox import Outbox
from chat_view import ChatView

NATIVE_AGENTS = {"codex", "claude"}

from core import (
    AGENTS, ROOT, CodexClient, cached_models, codex_defaults, default_agent, external_command,
    make_prompt, paths, private_write, read_json, repository_url, terminal,
)

EFFORT_LABELS = {
    "": tr('Default'), "none": tr('None'), "minimal": tr('Minimal'), "low": tr('Low'),
    "medium": tr('Medium'), "high": tr('High'), "xhigh": tr('Very high'), "max": tr('Maximum'), "ultra": "Ultra",
}


def ui(callback, *args):
    def invoke():
        callback(*args)
        return False
    GLib.idle_add(invoke)


def label(text="", css=None, selectable=False):
    widget = Gtk.Label(label=text, xalign=0, wrap=True, selectable=selectable)
    widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if css:
        widget.add_css_class(css)
    return widget


def box(vertical=True, spacing=8):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                   spacing=spacing)


def dropdown(values):
    widget = Gtk.DropDown.new_from_strings(values)
    widget.set_hexpand(True)
    widget.set_size_request(-1, 36)
    def make_factory(compact):
        factory = Gtk.SignalListItemFactory()
        def setup(_factory, item):
            item.set_child(Gtk.Label(
                xalign=0,
                ellipsize=Pango.EllipsizeMode.END if compact else Pango.EllipsizeMode.NONE,
                width_chars=1 if compact else -1,
                max_width_chars=1 if compact else -1,
                hexpand=True,
            ))
        def bind(_factory, item):
            text = item.get_item().get_string()
            item.get_child().set_text(text)
            item.get_child().set_tooltip_text(text)
        factory.connect("setup", setup)
        factory.connect("bind", bind)
        return factory
    # Keep the toolbar compact; size the open list for the complete option names.
    widget.set_factory(make_factory(True))
    widget.set_list_factory(make_factory(False))
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
        heading.set_selectable(False)
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
        self.owner.update_buttons()
        self.grab_focus()

    def destroy(self):
        if self in self.owner.panels:
            self.owner.panels.remove(self)
            self.owner.overlay.remove_overlay(self)
        self.owner.main_content.set_sensitive(not self.owner.panels)
        self.owner.update_buttons()


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Omarchy Settings Sync")
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
        self.client_epoch = 0
        self.closing_clients = []
        self.idle_timer = None
        self.ready = False
        self.busy = False
        self.thread_ids = self.settings.get("thread_ids", {})
        self.thread_ids.setdefault("codex", self.settings.get("thread_id"))
        self.thread_id = None
        self.thread_loaded = False
        self.turn_id = None
        self.outbox = Outbox(self.locations["state"] / "outbox.json")
        self.queue_paused = bool(self.outbox.entries)
        self.queue_panel = None
        self.delivery_pending = False
        self.redirect_entry = None
        self.stopping = False
        self.models = cached_models()
        self.executables = {agent: agent_executable(agent) for agent in AGENTS}
        self.catalog_file = self.locations["state"] / "model-catalog.json"
        self.catalogs = read_json(self.catalog_file, {})
        self.catalog_pending = set()
        self.catalog_attempted = set()
        self.catalog_errors = set()
        self.selected_agent = None
        self.changing_controls = False
        self.model_values = [""]
        self.effort_values = [""]
        self.cards = {}
        self.message_entries = {}
        self.tool_items = {}
        self.panels = []
        self.setup_panel = None
        self.messages = []
        self.question_windows = {}
        self.attention_file = self.locations["state"] / "attention.json"
        self.attention_waiting = False
        self.attention_opened = False
        self.attention_updated = 0
        self.monitor_name = ""
        self.terminal_pid = None
        self.last_prompt = ""
        self.active_task = None
        self.session_file = self.locations["state"] / "conversation.json"
        self._build()
        self.theme = Theme(self)
        self.theme_timer = GLib.timeout_add_seconds(2, self.refresh_theme)
        self.attention_timer = GLib.timeout_add_seconds(10, self.update_attention)
        self.update_attention(force=True)
        self.connect("notify::visible", lambda *_: self.update_attention(force=True))
        self.connect("close-request", self.close_window)
        self.connect("map", self.focus_content)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.popup_key)
        self.add_controller(keys)
        clicks = Gtk.GestureClick()
        clicks.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        clicks.connect("pressed", self.popup_click)
        self.add_controller(clicks)
        self.place_popup()
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
        title = label("Omarchy Settings Sync", "title")
        title.set_selectable(False)
        title.set_hexpand(True)
        header.append(title)
        settings_button = Gtk.Button(icon_name="emblem-system-symbolic", tooltip_text=tr('Settings'))
        settings_button.connect("clicked", lambda *_: self.setup())
        self.new_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=tr('New chat'))
        self.new_button.connect("clicked", lambda *_: self.new_chat())
        header.append(self.new_button)
        header.append(settings_button)
        sync_content = box(False, 6)
        sync_content.append(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        sync_content.append(Gtk.Label(label="Sync"))
        self.sync_button = Gtk.Button(child=sync_content, tooltip_text=tr('Sync'))
        self.sync_button.add_css_class("flat")
        self.sync_button.connect("clicked", lambda *_: self.sync())
        header.append(self.sync_button)
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
        controls = Gtk.Grid(column_spacing=10, column_homogeneous=True)
        self.controls = controls
        controls.add_css_class("toolbar")
        self.agent_ids = list(AGENTS)
        self.agent_select = dropdown([AGENTS[a] + ("" if self.executables[a] else tr(' · unavailable')) for a in self.agent_ids])
        current = self.settings.get("agent", default_agent())
        self.agent_select.set_selected(self.agent_ids.index(current) if current in self.agent_ids else 0)
        self.agent_select.connect("notify::selected", lambda *_: self.agent_changed())
        controls.attach(self.control(tr('Agent'), self.agent_select, expand=True), 0, 0, 1, 1)
        self.model_select = dropdown([tr('Default')])
        self.model_select.connect("notify::selected", lambda *_: self.model_changed())
        controls.attach(self.control(tr('Model'), self.model_select, expand=True), 1, 0, 1, 1)
        self.effort_select = dropdown([tr('Default')])
        self.effort_select.connect("notify::selected", lambda *_: self.remember_selection())
        controls.attach(self.control(tr('Effort'), self.effort_select, expand=True), 2, 0, 1, 1)
        outer.append(controls)
        self.model_info = box(False, 8)
        self.model_hint = label("", "muted")
        self.model_hint.set_wrap(False)
        self.model_hint.set_ellipsize(Pango.EllipsizeMode.END)
        self.model_hint.set_max_width_chars(1)
        self.model_hint.set_hexpand(True)
        self.model_info.append(self.model_hint)
        self.refresh_models_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=tr('Refresh models'))
        self.refresh_models_button.add_css_class("flat")
        self.refresh_models_button.connect("clicked", lambda *_: self.refresh_catalog(force=True))
        self.model_info.append(self.refresh_models_button)
        self.content = Gtk.Stack()
        self.content.set_vexpand(True)
        self.content.set_hhomogeneous(False)
        self.content.set_vhomogeneous(False)
        self.scroll = ChatView()
        self.transcript = self.scroll.messages
        self.content.add_named(self.scroll, "chat")
        empty = box(spacing=10)
        empty.set_valign(Gtk.Align.CENTER)
        empty.set_halign(Gtk.Align.FILL)
        self.empty_title = label("", "empty-title")
        self.empty_title.set_justify(Gtk.Justification.CENTER)
        self.empty_title.set_xalign(.5)
        self.empty_description = label("", "muted")
        self.empty_description.set_justify(Gtk.Justification.CENTER)
        self.empty_description.set_xalign(.5)
        self.empty_description.set_max_width_chars(30)
        empty.append(self.empty_title)
        empty.append(self.empty_description)
        self.content.add_named(empty, "empty")
        self.vte = None
        outer.append(self.content)
        self.input_area = box(spacing=8)
        self.input_area.add_css_class("composer")
        self.input = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.input.set_top_margin(8)
        self.input.set_left_margin(8)
        input_scroll = Gtk.ScrolledWindow(min_content_height=76, max_content_height=76,
                                         hscrollbar_policy=Gtk.PolicyType.NEVER)
        input_overlay = Gtk.Overlay(child=self.input)
        self.placeholder = label(tr("Change your system…"), "muted")
        self.placeholder.set_halign(Gtk.Align.START)
        self.placeholder.set_valign(Gtk.Align.START)
        self.placeholder.set_margin_start(8)
        self.placeholder.set_margin_top(8)
        self.placeholder.set_can_target(False)
        self.placeholder.set_wrap(False)
        self.placeholder.set_ellipsize(Pango.EllipsizeMode.END)
        input_overlay.add_overlay(self.placeholder)
        self.input.get_buffer().connect("changed", lambda b: self.placeholder.set_visible(b.get_char_count() == 0))
        input_scroll.set_child(input_overlay)
        self.input_area.append(input_scroll)
        self.input.set_tooltip_text(tr("Change your system…"))
        composer_keys = Gtk.EventControllerKey()
        composer_keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        composer_keys.connect("key-pressed", self.composer_key)
        self.input.add_controller(composer_keys)
        row = box(False, 8)
        self.publish = Gtk.CheckButton(label=tr('Push changes'))
        self.publish.set_active(self.settings.get("publish", True))
        self.publish.set_hexpand(True)
        row.append(self.publish)
        self.stop_button = Gtk.Button(label=tr('Stop'), sensitive=False)
        self.stop_button.connect("clicked", lambda *_: self.stop())
        self.queue_button = Gtk.Button(label=tr('{count} queued', count=0))
        self.queue_button.add_css_class('flat')
        self.queue_button.connect("clicked", lambda *_: self.show_queue())
        row.append(self.queue_button)
        self.send_button = Gtk.Button(label=tr('Send'))
        self.send_button.add_css_class("suggested-action")
        self.send_button.set_size_request(104, 36)
        self.send_button.connect("clicked", lambda *_: self.send())
        row.append(self.send_button)
        self.input_area.append(row)
        outer.append(self.input_area)
        bottom = box(False, 8)
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(16, 16)
        bottom.append(self.spinner)
        self.status = label(tr('Ready'), "status")
        self.status.set_wrap(False)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_max_width_chars(1)
        self.status.connect("notify::label", lambda *_: self.status.set_tooltip_text(self.status.get_text()))
        self.status.set_hexpand(True)
        bottom.append(self.status)
        self.stop_button.set_size_request(104, 36)
        self.stop_button.set_valign(Gtk.Align.CENTER)
        self.terminal_button = Gtk.Button(icon_name="utilities-terminal-symbolic", tooltip_text=tr('Open workspace terminal'))
        self.terminal_button.add_css_class("flat")
        self.terminal_button.set_size_request(36, 36)
        self.terminal_button.connect("clicked", lambda *_: self.open_terminal())
        bottom.append(self.terminal_button)
        bottom.append(self.stop_button)
        outer.append(bottom)

    def control(self, title, widget, expand=False):
        container = box(spacing=4)
        container.set_hexpand(expand)
        heading = label(title, "muted")
        heading.set_wrap(False)
        container.append(heading)
        container.append(widget)
        return container

    def place_popup(self, monitor_name="", anchor_x=None, edge="top", bar_size=26):
        monitors = Gdk.Display.get_default().get_monitors()
        monitor = next((monitors.get_item(i) for i in range(monitors.get_n_items())
                        if monitors.get_item(i).get_connector() == monitor_name), None)
        if monitor is None:
            monitor = monitors.get_item(0)
        LayerShell.set_monitor(self, monitor)
        self.monitor_name = monitor.get_connector() or ""
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
        self.update_attention(force=True)

    def focus_content(self, *_):
        if self.idle_timer is not None:
            GLib.source_remove(self.idle_timer)
            self.idle_timer = None
        self.theme.refresh()
        if not self.panels:
            target = self.vte if self.terminal_pid and self.vte else self.input
            target.grab_focus()

    def popup_key(self, _controller, key, _code, _state):
        if key == Gdk.KEY_Escape:
            if self.panels:
                self.panels[-1].on_close()
                return True
            # Escape closes a selector before it closes the whole panel.
            def close_popover(widget):
                child = widget.get_first_child()
                while child:
                    if isinstance(child, Gtk.Popover) and child.get_visible():
                        child.popdown()
                        return True
                    if close_popover(child):
                        return True
                    child = child.get_next_sibling()
                return False
            if close_popover(self.popup_card):
                return True
            if self.terminal_pid and self.vte and self.vte.has_focus():
                # Escape is also a native agent interrupt/edit key.
                return False
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
        self.quit_if_idle()

    def quit_if_idle(self):
        if self.get_visible() or self.busy or self.terminal_pid or self.question_windows or self.delivery_pending:
            return False
        self.close_client(background=True)
        if self.idle_timer is None:
            self.idle_timer = GLib.timeout_add_seconds(60, self.expire_idle)
        return False

    def expire_idle(self):
        self.idle_timer = None
        if not (self.get_visible() or self.busy or self.terminal_pid or self.question_windows or self.delivery_pending):
            self.get_application().quit()
        return False

    def refresh_theme(self):
        if self.get_visible():
            self.theme.refresh()
        return True

    def agent(self):
        return self.agent_ids[self.agent_select.get_selected()]

    def selection(self):
        index = self.model_select.get_selected()
        model = self.model_values[index] if index < len(self.model_values) else ""
        index = self.effort_select.get_selected()
        effort = self.effort_values[index] if index < len(self.effort_values) else ""
        return model or "", effort

    def remember_selection(self):
        if self.changing_controls or self.selected_agent is None:
            return
        index = self.model_select.get_selected()
        if index >= len(self.model_values) or self.model_values[index] is None:
            return
        model, effort = self.selection()
        self.settings.setdefault("selections", {})[self.selected_agent] = {"model": model, "effort": effort}

    def save_settings(self):
        self.remember_selection()
        self.thread_ids[self.agent()] = self.thread_id
        self.settings.update(agent=self.agent(), publish=self.publish.get_active(),
                             thread_id=self.thread_ids.get("codex"), thread_ids=self.thread_ids)
        private_write(self.settings_file, self.settings)

    def agent_changed(self):
        if not hasattr(self, "content"):
            return
        self.remember_selection()
        previous = self.selected_agent
        if previous != self.agent():
            if previous:
                self.thread_ids[previous] = self.thread_id
                self.save_conversation()
            self.close_client()
            self.thread_id = self.thread_ids.get(self.agent())
            self.session_file = self.locations["state"] / ("conversation.json" if self.agent() == "codex" else "conversation-" + self.agent() + ".json")
            self.messages, self.cards, self.message_entries, self.tool_items = [], {}, {}, {}
            while self.transcript.get_first_child():
                self.transcript.remove(self.transcript.get_first_child())
            for message in read_json(self.session_file, [])[-100:]:
                self.add_message(message["role"], message["text"], save=False)
        self.selected_agent = self.agent()
        if previous != self.agent():
            self.queue_paused = bool(self.outbox.for_agent(self.agent()))
        self.render_models()
        self.show_idle_content()
        self.status.set_text(tr('Ready · ') + AGENTS[self.agent()])
        self.update_buttons()
        self.refresh_catalog()

    def show_idle_content(self):
        if self.terminal_pid:
            self.content.set_visible_child_name("terminal")
        elif self.agent() in NATIVE_AGENTS and self.messages:
            self.content.set_visible_child_name("chat")
        else:
            self.empty_title.set_text(AGENTS[self.agent()])
            self.empty_description.set_text(
                tr('Write a request below to begin.') if self.executables[self.agent()]
                else tr('Install {agent} from the Omarchy agent menu.', agent=AGENTS[self.agent()]))
            self.content.set_visible_child_name("empty")

    def agent_models(self):
        if self.agent() == "codex":
            return self.models
        return self.catalogs.get(self.agent(), {}).get("models", [])

    def render_models(self):
        self.changing_controls = True
        rows = self.agent_models()
        default = next((m for m in rows if not m["model"]), {})
        self.visible_models = [default] + [m for m in rows if m["model"]]
        self.model_values = [""] + [m["model"] for m in self.visible_models[1:]]
        names = [tr('Default')] + [m["displayName"] for m in self.visible_models[1:]]
        saved = self.settings.get("selections", {}).get(self.agent(), {})
        defaults = codex_defaults() if self.agent() == "codex" else {}
        selected = saved.get("model", defaults.get("model", ""))
        if selected and selected not in self.model_values:
            self.model_values.append(selected)
            self.visible_models.append({"model": selected, "displayName": selected})
            names.append(selected)
        if self.agent() in MODEL_AGENTS:
            self.model_values.append(None)
            names.append(tr('Custom model…'))
        self.model_select.set_model(Gtk.StringList.new(names))
        self.model_select.set_selected(self.model_values.index(selected) if selected in self.model_values else 0)
        self.changing_controls = False
        self.model_changed()
        self.update_model_hint()

    def update_models(self, models):
        self.remember_selection()
        self.models = models
        if self.agent() == "codex":
            self.render_models()

    def model_changed(self):
        if self.changing_controls or not hasattr(self, "effort_select") or not hasattr(self, "visible_models"):
            return
        index = self.model_select.get_selected()
        if index >= len(self.model_values):
            return
        if self.model_values[index] is None:
            self.custom_model()
            return
        model = self.visible_models[index] if index < len(self.visible_models) else {}
        if not model and self.agent() == "codex":
            configured = codex_defaults().get("model", "")
            model = next((m for m in self.models if m["model"] == configured), {})
        values = [""] + [e.get("reasoningEffort", e.get("effort")) for e in model.get("supportedReasoningEfforts", [])]
        saved = self.settings.get("selections", {}).get(self.agent(), {})
        defaults = codex_defaults() if self.agent() == "codex" else {}
        desired = saved.get("effort", defaults.get("model_reasoning_effort", ""))
        self.changing_controls = True
        self.set_efforts(values, desired)
        self.changing_controls = False
        self.model_select.set_tooltip_text(model.get("description") or model.get("displayName") or tr('Default'))
        self.remember_selection()
        self.update_buttons()

    def custom_model(self):
        # Restore the previous choice until the user accepts the custom ID.
        saved = self.settings.get("selections", {}).get(self.agent(), {})
        previous = saved.get("model", "")
        self.changing_controls = True
        self.model_select.set_selected(self.model_values.index(previous) if previous in self.model_values else 0)
        self.changing_controls = False
        panel = Panel(self, tr('Custom model'))
        content = box(spacing=12)
        entry = Gtk.Entry(placeholder_text=tr('Model ID'), text=previous)
        content.append(self.control(tr('Model ID'), entry))
        save = Gtk.Button(label=tr('Use model'))
        save.add_css_class("suggested-action")
        def apply(*_):
            model = entry.get_text().strip()
            if not model:
                return
            self.settings.setdefault("selections", {})[self.agent()] = {"model": model, "effort": ""}
            panel.destroy()
            self.render_models()
            self.save_settings()
        save.connect("clicked", apply)
        entry.connect("activate", apply)
        content.append(save)
        panel.set_content(content)
        panel.present()
        entry.grab_focus()

    def set_efforts(self, values, desired):
        self.effort_values = list(dict.fromkeys(v for v in values if v is not None))
        self.effort_select.set_model(Gtk.StringList.new([EFFORT_LABELS.get(v, v) for v in self.effort_values]))
        self.effort_select.set_selected(self.effort_values.index(desired) if desired in self.effort_values else 0)

    def update_model_hint(self):
        agent = self.agent()
        if not self.executables[agent]:
            text = tr('Agent not installed')
        elif agent in self.catalog_pending:
            text = tr('Loading models…')
        elif agent in self.catalog_errors:
            text = tr('Could not refresh models. Retry or use a custom model.')
        elif self.agent_models():
            text = tr('Models from your installed agent')
        else:
            text = tr('Use the agent default or choose a model in its terminal.')
        self.model_hint.set_text(text)
        self.model_hint.set_tooltip_text(text)

    def refresh_catalog(self, force=False):
        agent = self.agent()
        if agent == "codex":
            if force:
                self.update_models(cached_models())
            return
        if agent not in DISCOVERY_AGENTS or not self.executables[agent] or agent in self.catalog_pending:
            return
        cached = self.catalogs.get(agent, {})
        if not force and (agent in self.catalog_attempted or time.time() - cached.get("updated", 0) < 21600):
            return
        self.catalog_pending.add(agent)
        self.catalog_attempted.add(agent)
        self.update_model_hint()
        self.update_buttons()
        def fetch():
            try:
                models = discover_models(agent, self.executables[agent])
                ui(self.catalog_loaded, agent, models)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                ui(self.catalog_loaded, agent, None)
        threading.Thread(target=fetch, daemon=True).start()

    def catalog_loaded(self, agent, models):
        self.catalog_pending.discard(agent)
        if models:
            self.catalogs[agent] = {"models": models, "updated": time.time()}
            self.catalog_errors.discard(agent)
            private_write(self.catalog_file, self.catalogs)
        else:
            self.catalog_errors.add(agent)
        if self.agent() == agent:
            self.remember_selection()
            self.render_models()
            self.update_buttons()

    def worker(self, operation, done=None, failed=None):
        def work():
            try:
                result = operation()
                if done:
                    ui(done, result)
            except Exception as error:
                ui(failed or self.failure, str(error))
        threading.Thread(target=work, daemon=True).start()

    def connected_models(self, models):
        if self.agent() == "codex":
            self.update_models(models)
        elif self.agent() == "claude":
            self.catalog_loaded("claude", models)

    def mode_label(self):
        return {"auto": tr('auto review'), "ask": tr('ask for approval'), "read": tr('read only')}.get(
            self.settings.get("permissions", "auto"), tr('auto review'))

    def update_buttons(self):
        available = not self.busy and not self.terminal_pid and not self.delivery_pending
        installed = bool(self.executables[self.agent()])
        running = self.busy or bool(self.terminal_pid)
        self.send_button.set_label(tr('Queue') if running or self.delivery_pending else tr('Send'))
        self.send_button.set_sensitive(installed)
        self.send_button.set_tooltip_text(tr('Enter: queue. Ctrl+Enter: send now. Shift+Enter: new line.')
                                         if running else tr('Enter: send. Shift+Enter: new line.'))
        self.sync_button.set_sensitive(available and installed and not self.panels)
        self.terminal_button.set_sensitive(True)
        self.new_button.set_sensitive(available and not self.panels and not self.outbox.for_agent(self.agent()))
        self.agent_select.set_sensitive(available)
        self.model_select.set_sensitive(available and bool(self.executables[self.agent()]) and self.agent() in MODEL_AGENTS)
        self.effort_select.set_sensitive(available and len(self.effort_values) > 1)
        self.effort_select.set_tooltip_text(tr('Effort') if len(self.effort_values) > 1 else tr('Effort is managed by this agent.'))
        self.refresh_models_button.set_sensitive(available and bool(self.executables[self.agent()]) and self.agent() in DISCOVERY_AGENTS | {"codex"} and self.agent() not in self.catalog_pending)
        self.input_area.set_sensitive(True)
        self.publish.set_sensitive(not running and not self.delivery_pending)
        self.stop_button.set_sensitive(running and not self.stopping)
        self.stop_button.set_visible(True)
        self.spinner.set_spinning(self.busy and not self.attention_waiting)
        self.update_queue()

    def composer_key(self, _controller, key, _code, state):
        if key not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        if state & Gdk.ModifierType.SHIFT_MASK:
            return False
        self.send(immediate=bool(state & Gdk.ModifierType.CONTROL_MASK))
        return True

    def queue_message(self, text, *, first=False):
        if not self.settings.get("repository"):
            self.setup()
            return None
        entry = self.outbox.add(self.agent(), self.settings["repository"], self.settings.get("branch", ""),
                                self.thread_id, text, self.publish.get_active(), first=first)
        self.save_settings()
        self.update_buttons()
        return entry

    def update_queue(self):
        entries = self.outbox.for_agent(self.agent())
        self.queue_button.set_label(tr('{count} queued', count=len(entries)))
        self.queue_button.set_visible(bool(entries))
        self.queue_button.set_tooltip_text(tr('Queue paused') if self.queue_paused else tr('Queued messages'))
        if self.queue_panel in self.panels:
            self.render_queue()

    def show_queue(self):
        if self.queue_panel in self.panels:
            return
        self.queue_panel = Panel(self, tr('Queued messages'))
        self.render_queue()
        self.queue_panel.present()

    def render_queue(self):
        content = box(spacing=12)
        entries = self.outbox.for_agent(self.agent())
        native = self.agent() in NATIVE_AGENTS and not self.terminal_pid
        content.append(label(tr('Messages are saved until sent. Stop or an error pauses the queue.') if native else
                             tr('Copy a message, paste it into the agent input, then use its send or queue keys. Remove it here after sending.')))
        if entries and native:
            resume = Gtk.Button(label=tr('Resume queue') if self.queue_paused or not self.busy else tr('Pause queue'))
            resume.set_sensitive(not self.delivery_pending and not self.stopping)
            def toggle(*_):
                self.queue_paused = not self.queue_paused if self.busy else False
                self.queue_panel.destroy()
                self.drain_queue()
                self.update_buttons()
            resume.connect('clicked', toggle)
            content.append(resume)
        if not entries:
            content.append(label(tr('No queued messages.')))
        for entry in entries:
            card = box(spacing=6)
            card.add_css_class('message')
            card.append(label(entry['text'], selectable=True))
            card.append(label(tr('Push changes') if entry['publish'] else tr('Local changes only'), 'muted'))
            if not self.queue_matches(entry):
                card.append(label(tr('From another conversation or repository. Edit to reuse.')))
            if entry.get('state') == 'uncertain':
                card.append(label(tr('Delivery unconfirmed. Check the conversation before editing and retrying.')))
            actions = box(False, 8)
            if native:
                now = Gtk.Button(label=tr('Direct now') if self.busy else tr('Send now'))
                now.add_css_class('suggested-action')
                now.set_tooltip_text(tr('Interrupt and continue in the same conversation.')
                                     if self.busy and self.agent() == 'claude' else tr('Ctrl+Enter'))
                now.set_sensitive(not self.delivery_pending and not self.stopping and self.queue_matches(entry)
                                  and entry.get('state') == 'pending' and entry is not self.redirect_entry
                                  and (not self.busy or bool(self.turn_id)))
                now.connect('clicked', lambda _, e=entry: self.send_queued_now(e))
                actions.append(now)
            for title, action in ((tr('Edit'), self.edit_queued), (tr('Remove'), self.remove_queued)):
                button = Gtk.Button(label=title, sensitive=entry.get('state') != 'sending' and entry is not self.redirect_entry)
                button.connect('clicked', lambda _, e=entry, fn=action: fn(e))
                actions.append(button)
            if not native:
                copy = Gtk.Button(label=tr('Copy to terminal'))
                copy.connect('clicked', lambda _, e=entry: self.copy_to_terminal(e['text']))
                actions.append(copy)
            card.append(actions)
            content.append(card)
        self.queue_panel.set_content(content)

    def edit_queued(self, entry):
        if entry.get('state') == 'sending' or entry is self.redirect_entry:
            return
        buffer = self.input.get_buffer()
        if buffer.get_char_count():
            self.status.set_text(tr('Keep or clear your draft before editing a queued message.'))
            self.queue_panel.destroy()
            return
        self.queue_paused = True
        self.publish.set_active(entry['publish'])
        buffer.set_text(entry['text'])
        self.outbox.remove(entry)
        self.queue_panel.destroy()
        self.update_buttons()
        self.input.grab_focus()

    def remove_queued(self, entry):
        if entry.get('state') == 'sending' or entry is self.redirect_entry:
            return
        self.outbox.remove(entry)
        self.update_buttons()

    def copy_to_terminal(self, text):
        self.get_clipboard().set(text)
        if self.queue_panel in self.panels:
            self.queue_panel.destroy()
        if self.terminal_pid and self.vte:
            self.vte.grab_focus()
        self.status.set_text(tr('Copied. Paste into the agent input with Ctrl+Shift+V.'))

    def send_queued_now(self, entry):
        if self.delivery_pending or self.stopping or entry.get('state') != 'pending' or not self.queue_matches(entry):
            return
        if self.queue_panel in self.panels:
            self.queue_panel.destroy()
        if self.busy:
            self.steer(entry['text'], queued_entry=entry)
        else:
            self.submit(entry['text'], queued_entry=entry, publish=entry['publish'])

    def queue_matches(self, entry):
        return self.outbox.matches(entry, self.settings.get('repository'), self.settings.get('branch', ''), self.thread_id)

    def drain_queue(self):
        if self.busy or self.delivery_pending or self.terminal_pid or self.stopping:
            return False
        if self.redirect_entry:
            entry, self.redirect_entry = self.redirect_entry, None
        elif not self.queue_paused and self.agent() in NATIVE_AGENTS:
            entries = self.outbox.for_agent(self.agent())
            entry = entries[0] if entries else None
        else:
            return False
        if entry:
            if entry.get('state') != 'pending' or not self.queue_matches(entry):
                self.queue_paused = True
                self.update_buttons()
                return False
            if not self.submit(entry['text'], queued_entry=entry, publish=entry['publish']):
                self.queue_paused = True
                self.update_buttons()
        return False

    def add_message(self, role, text, identifier=None, save=True):
        card = box(spacing=6)
        card.add_css_class("message")
        if role == tr('You'):
            card.add_css_class("user-message")
        card.append(label(role, "card-role"))
        body = label(text, selectable=True)
        body.set_max_width_chars(1)
        body.set_hexpand(True)
        card.append(body)
        self.transcript.append(card)
        if self.agent() in NATIVE_AGENTS or role == tr("Error"):
            self.content.set_visible_child_name("chat")
        if identifier:
            self.cards[identifier] = body
        entry = {"role": role, "text": text}
        self.messages.append(entry)
        if identifier:
            self.message_entries[identifier] = entry
        if save:
            self.save_conversation()
        self.scroll.to_end(force=role == tr('You'))
        return body

    def save_conversation(self):
        private_write(self.session_file, self.messages[-150:])

    def scroll_down(self):
        self.scroll.to_end()

    def failure(self, message):
        self.queue_paused = True
        self.redirect_entry = None
        self.stopping = False
        self.delivery_pending = False
        for entry in self.outbox.for_agent(self.agent()):
            if entry.get('state') == 'sending':
                self.outbox.mark(entry, 'uncertain')
        self.finish_activity("failed")
        self.busy = False
        self.turn_id = None
        self.status.set_text(tr('Needs attention'))
        self.add_message(tr('Error'), message)
        self.update_buttons()
        GLib.idle_add(self.quit_if_idle)

    def send(self, *_, queued=False, immediate=False):
        buffer = self.input.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()
        if text:
            running = self.busy or self.terminal_pid or self.delivery_pending
            if queued or (running and not immediate):
                accepted = self.queue_message(text) is not None
            elif self.terminal_pid:
                accepted = self.queue_message(text) is not None
                if accepted:
                    self.copy_to_terminal(text)
            elif self.busy:
                accepted = self.steer(text)
            elif self.delivery_pending:
                accepted = False
            else:
                accepted = self.submit(text)
            if accepted:
                buffer.set_text("")

    def steer(self, text, *, queued_entry=None):
        if self.delivery_pending or self.stopping or not self.turn_id or self.agent() not in NATIVE_AGENTS:
            return False
        entry = queued_entry or self.queue_message(text, first=True)
        if not entry:
            return False
        self.delivery_pending = True
        client, thread_id, turn_id, epoch = self.client, self.thread_id, self.turn_id, self.client_epoch
        is_claude = self.agent() == 'claude'
        if is_claude:
            # The bidirectional Claude protocol offers interrupt, not turn/steer.
            # Wait for BOTH interrupt acknowledgement and the terminal result.
            self.redirect_entry = entry
            self.status.set_text(tr('Interrupting to redirect…'))
        else:
            self.outbox.mark(entry, 'sending')
        self.update_buttons()
        def accepted(result):
            if epoch != self.client_epoch:
                return
            self.delivery_pending = False
            if not is_claude:
                if entry in self.outbox.entries:
                    self.outbox.remove(entry)
                self.add_message(tr('You'), text)
            self.update_buttons()
            self.drain_queue()
            self.quit_if_idle()
        def rejected(message):
            if epoch != self.client_epoch:
                return
            self.delivery_pending = False
            self.redirect_entry = None
            self.queue_paused = True
            if not is_claude:
                self.outbox.mark(entry, 'uncertain')
            self.status.set_text(tr('Message kept in queue. Check delivery before retrying.'))
            self.add_message(tr('Error'), message)
            self.update_buttons()
            self.quit_if_idle()
        self.worker(lambda: client.request('turn/interrupt', {'threadId': thread_id, 'turnId': turn_id})
                    if is_claude else client.steer(thread_id, turn_id, text), accepted, rejected)
        return True

    def sync(self):
        if not self.settings.get("repository"):
            self.setup()
            return
        self.submit(tr('Sync'), sync=True)

    def submit(self, text, sync=False, create=False, *, queued_entry=None, publish=None):
        if self.busy or self.terminal_pid or self.delivery_pending:
            self.status.set_text(tr('Stop the current task first.'))
            return False
        if not self.settings.get("repository"):
            self.setup()
            return False
        if self.agent() == "codex" and not shutil.which("codex"):
            self.failure(tr('Install Codex or choose another agent.'))
            return False
        self.save_settings()
        try:
            prompt = make_prompt(
                text, repository=self.settings["repository"], branch=self.settings.get("branch", ""),
                sync=sync, publish=(self.publish.get_active() if publish is None else publish) or create, create=create,
                thread_id=self.thread_id if self.agent() in NATIVE_AGENTS else None,
                locations=self.locations,
            )
        except ValueError as error:
            self.failure(str(error))
            return False
        self.last_prompt = prompt
        self.stopping = False
        self.active_task = begin_task(
            self.locations, self.settings["repository"], self.settings.get("branch", ""),
            "create" if create else "sync" if sync else "change", self.agent(), private_write,
        )
        if self.agent() not in NATIVE_AGENTS:
            self.launch_external(prompt)
            return True
        model, effort = self.selection()
        if self.agent() == "claude" and self.client and (self.client.model, self.client.effort) != (model, effort):
            self.close_client()
        self.add_message(tr('You'), text)
        self.busy = True
        self.delivery_pending = True
        if queued_entry:
            self.outbox.mark(queued_entry, 'sending')
        self.status.set_text(tr('Working…') if self.ready else tr('Connecting…'))
        self.update_buttons()
        model, effort = self.selection()
        if not self.client:
            epoch = self.client_epoch
            def receive(message):
                def deliver():
                    if epoch == self.client_epoch:
                        self.event(message)
                ui(deliver)
            if self.agent() == "claude":
                self.client = ClaudeClient(receive, executable=self.executables["claude"],
                                           model=model, effort=effort, session_id=self.thread_id)
            else:
                self.client = CodexClient(receive)
        client = self.client
        agent, repository, branch = self.agent(), self.settings['repository'], self.settings.get('branch', '')
        def execute():
            # A quick reopen may overlap shutdown of the previous CLI. Wait in
            # the worker, never in the UI, before resuming the same conversation.
            for closing in self.closing_clients:
                closing.join()
            self.closing_clients.clear()
            if not self.ready:
                try:
                    self.client.start()
                    models = self.client.models()
                except Exception:
                    self.close_client()
                    raise
                self.ready = True
                ui(self.connected_models, models)
            if not self.thread_loaded:
                result = self.client.start_thread(model, self.settings.get("permissions", "auto"), self.thread_id)
                previous_thread = self.thread_id
                self.thread_id = result["thread"]["id"]
                self.thread_loaded = True
                ui(self.outbox.bind_thread, agent, repository, branch, previous_thread, self.thread_id)
                ui(self.save_settings)
            return self.client.turn(self.thread_id, prompt, model, effort)
        self.worker(execute, lambda r: self.started(r["turn"]["id"], queued_entry) if client is self.client else None)
        return True

    def finish_activity(self, status):
        self.clear_questions()
        finish_task(self.active_task, status, private_write)
        self.active_task = None

    def started(self, turn_id, queued_entry=None):
        self.delivery_pending = False
        if self.busy:
            self.turn_id = turn_id
        if queued_entry and queued_entry in self.outbox.entries:
            self.outbox.remove(queued_entry)
        self.update_buttons()
        # A fast response may finish before the request acknowledgement arrives.
        if not self.busy:
            self.drain_queue()
            self.quit_if_idle()

    def event(self, message):
        method = message.get("method", "")
        params = message.get("params", {})
        if "id" in message:
            self.request_from_agent(message)
            return
        if params.get("threadId") and self.thread_id and params["threadId"] != self.thread_id:
            return
        if method == "session/started":
            self.thread_id = params["id"]
            self.save_settings()
        elif method == "question/cancelled":
            panel = self.question_windows.pop(params.get("id"), None)
            if panel:
                panel.destroy()
            self.update_attention(force=True)
            self.update_buttons()
        elif method == "turn/started":
            self.turn_id = params["turn"]["id"]
            self.update_buttons()
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
                    self.scroll_down()
                else:
                    self.add_message(tr('Agent'), text, identifier)
        elif method == "turn/completed":
            turn = params.get("turn", {})
            if turn.get('id') and self.turn_id and turn['id'] != self.turn_id:
                return
            self.busy = False
            self.turn_id = None
            if turn.get("error") or turn.get('status') == 'failed':
                self.failure(str((turn.get('error') or {}).get('message', tr('Task failed.'))))
            else:
                self.status.set_text(tr('Stopped') if turn.get("status") == "interrupted" else tr('Done'))
                self.finish_activity("interrupted" if turn.get("status") == "interrupted" else "response_completed")
                if turn.get('status') != 'completed' and not self.redirect_entry:
                    self.queue_paused = True
                self.stopping = False
            self.update_buttons()
            self.save_settings()
            self.drain_queue()
            GLib.idle_add(self.quit_if_idle)
        elif method == "client/disconnected":
            self.ready = False
            self.thread_loaded = False
            self.failure(tr('Agent disconnected. Send again to reconnect.'))
            self.close_client()
        elif method == "error":
            self.add_message(AGENTS[self.agent()], str(params.get("message", params.get("error", params))))
        elif method == "item/autoApprovalReview/started":
            self.status.set_text(tr('Reviewing approval…'))

    def stop(self):
        self.queue_paused = True
        self.redirect_entry = None
        if self.terminal_pid:
            # A real keypress in the PTY preserves the agent's interrupt semantics.
            self.vte.feed_child(b"\x03")
            self.status.set_text(tr('Interrupt sent. Use /exit to close the CLI.'))
        elif self.turn_id:
            self.stopping = True
            client, thread_id, turn_id = self.client, self.thread_id, self.turn_id
            def failed(message):
                self.stopping = False
                self.add_message(tr('Error'), message)
                self.update_buttons()
            self.worker(lambda: client.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}), failed=failed)
        self.update_buttons()

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
            self.update_attention(force=True)
            if not self.question_windows:
                self.status.set_text(tr('Working…') if self.busy else tr('Ready'))
            self.update_buttons()
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
            first_input = None
            for q in params.get("questions", []):
                content.append(label(q["question"]))
                entry = Gtk.Entry(visibility=not q.get("isSecret", False), placeholder_text=tr('Your answer…'))
                choices = []
                for option in q.get("options") or []:
                    choice = Gtk.CheckButton(label=option["label"])
                    if choices and not q.get("multiSelect", False):
                        choice.set_group(choices[0])
                    choice.set_tooltip_text(option.get("description", ""))
                    if not q.get("multiSelect", False):
                        choice.connect("toggled", lambda button, e=entry: e.set_text("") if button.get_active() else None)
                    choices.append(choice)
                    content.append(choice)
                    if option.get("description"):
                        content.append(label(option["description"], "muted"))
                def typed(field, options=choices):
                    if field.get_text().strip():
                        for option in options:
                            option.set_active(False)
                if not q.get("multiSelect", False):
                    entry.connect("changed", typed)
                entries[q["id"]] = (entry, choices)
                content.append(entry)
                if first_input is None:
                    first_input = choices[0] if choices else entry
            validation = label("", "muted")
            content.append(validation)
            def question_answer():
                answers = {}
                for key, (entry, choices) in entries.items():
                    values = [choice.get_label() for choice in choices if choice.get_active()]
                    if entry.get_text().strip():
                        values.append(entry.get_text().strip())
                    if not values:
                        validation.set_text(tr('Answer each question before sending.'))
                        return None
                    answers[key] = {"answers": values}
                return {"answers": answers}
            approve = question_answer
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
        self.status.set_text(tr('Waiting for your reply'))
        self.update_attention(force=True)
        self.update_buttons()
        if method == "item/tool/requestUserInput" and first_input:
            first_input.grab_focus()

    def launch_external(self, prompt):
        agent = self.agent()
        if not self.executables[agent]:
            self.failure(tr("Install {agent} from the Omarchy agent menu.", agent=AGENTS[agent]))
            return
        model, effort = self.selection()
        command = external_command(agent, prompt, model, effort)
        if command[0] == agent:
            command[0] = self.executables[agent]
        if not self.ensure_vte():
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
            self.update_buttons()
            self.vte.grab_focus()
        self.vte.spawn_async(
            pty_flags=Vte.PtyFlags.DEFAULT, working_directory=str(self.locations["workspace"]),
            argv=command, envv=[f"{k}={v}" for k, v in environment.items()],
            spawn_flags=GLib.SpawnFlags.SEARCH_PATH, child_setup=None,
            timeout=-1, cancellable=None, callback=spawned,
        )

    def ensure_vte(self):
        if self.vte:
            return True
        global Vte
        try:
            gi.require_version("Vte", "3.91")
            from gi.repository import Vte
        except (ValueError, ImportError):
            return False
        self.vte = Vte.Terminal()
        self.vte.set_scrollback_lines(10000)
        self.vte.set_hexpand(True)
        self.vte.set_vexpand(True)
        self.vte.connect("child-exited", self.child_exited)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.terminal_key)
        self.vte.add_controller(keys)
        terminal_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                            vscrollbar_policy=Gtk.PolicyType.EXTERNAL)
        terminal_scroll.set_child(self.vte)
        self.content.add_named(terminal_scroll, "terminal")
        self.theme.previous = None
        self.theme.refresh()
        return True

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
        self.queue_paused = True
        self.finish_activity("external_unverified")
        self.terminal_pid = None
        self.busy = False
        self.status.set_text(tr("Session ended · {status}", status=status))
        self.input_area.set_sensitive(True)
        self.update_buttons()
        GLib.idle_add(self.quit_if_idle)

    def open_terminal(self):
        # A companion shell never attaches a second writer to an active session.
        terminal([os.environ.get("SHELL", "/bin/bash")])

    def resume_in_terminal(self):
        if self.busy or self.terminal_pid or self.delivery_pending or self.outbox.for_agent(self.agent()) or not self.thread_id:
            return
        self.close_client()
        if self.agent() == "claude":
            terminal([self.executables["claude"], "--resume=" + self.thread_id])
        elif self.agent() == "codex":
            mode = self.settings.get("permissions", "auto")
            flags = (["--approve-for-me"] if mode == "auto" else
                     ["--sandbox", "read-only" if mode == "read" else "workspace-write",
                      "--ask-for-approval", "never" if mode == "read" else "on-request"])
            terminal(["codex", *flags, "resume", self.thread_id])
        self.dismiss()

    def close_client(self, background=False):
        self.client_epoch += 1
        client, self.client = self.client, None
        self.ready = self.thread_loaded = False
        if client:
            if background:
                closing = threading.Thread(target=client.close)
                self.closing_clients.append(closing)
                closing.start()
            else:
                client.close()

    def update_attention(self, force=False):
        waiting = bool(self.question_windows)
        opened = self.get_visible()
        if (force or waiting != self.attention_waiting or opened != self.attention_opened
                or ((waiting or opened) and time.time() - self.attention_updated >= 9)):
            self.attention_waiting = waiting
            self.attention_opened = opened
            self.attention_updated = time.time()
            private_write(self.attention_file, {"waiting": waiting, "opened": opened,
                                               "monitor": self.monitor_name, "updated": self.attention_updated})
        return True

    def clear_questions(self):
        for panel in list(self.question_windows.values()):
            panel.destroy()
        self.question_windows.clear()
        self.update_attention(force=True)

    def new_chat(self):
        if self.busy or self.terminal_pid or self.delivery_pending:
            return
        if self.outbox.for_agent(self.agent()):
            self.show_queue()
            return
        self.queue_paused = False
        self.close_client()
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
        self.show_idle_content()

    def setup(self):
        locked = bool(self.busy or self.terminal_pid or self.delivery_pending or self.outbox.entries)
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
        if self.model_info.get_parent():
            self.model_info.get_parent().remove(self.model_info)
        content.append(self.model_info)
        mode = dropdown([tr('Auto review'), tr('Ask for approval'), tr('Read only')])
        modes = ["auto", "ask", "read"]
        current_mode = self.settings.get("permissions", "auto")
        mode.set_selected(modes.index(current_mode) if current_mode in modes else 0)
        content.append(self.control(tr('Codex permissions'), mode))
        error_label = label("")
        error_label.set_visible(False)
        content.append(error_label)
        buttons = box(False, 10)
        buttons.set_homogeneous(True)
        def save(create=False):
            try:
                value = repository_url(repository.get_text())
                branch_value = branch.get_text().strip()
                if branch_value.startswith("-") or any(c.isspace() for c in branch_value):
                    raise ValueError(tr('Invalid branch.'))
            except ValueError as error:
                error_label.set_text(str(error))
                error_label.set_visible(True)
                return
            changed = value != self.settings.get("repository") or branch_value != self.settings.get("branch", "")
            self.settings.update(repository=value, branch=branch_value, permissions=modes[mode.get_selected()])
            self.thread_loaded = False
            if changed:
                self.new_chat()
            self.save_settings()
            dialog.destroy()
            if create:
                self.submit(tr('Create my configuration repository'), create=True)
        existing = Gtk.Button(label=tr('Use repository'))
        existing.set_hexpand(True)
        existing.add_css_class("suggested-action")
        existing.connect("clicked", lambda *_: save())
        create = Gtk.Button(label=tr('Create with agent'))
        create.connect("clicked", lambda *_: save(True))
        buttons.append(existing)
        buttons.append(create)
        content.append(buttons)
        resume = Gtk.Button(label=tr('Continue conversation in terminal'))
        resume.set_sensitive(not locked and bool(self.thread_id) and self.agent() in NATIVE_AGENTS)
        resume.connect("clicked", lambda *_: self.resume_in_terminal())
        content.append(resume)
        if locked:
            for widget in (repository, branch, mode, existing, create):
                widget.set_sensitive(False)
            error_label.set_text(tr('Finish the task and send or remove queued messages before changing settings.'))
            error_label.set_visible(True)
        dialog.present()
        return False

    def close_window(self, *_):
        self.dismiss()
        return True


class Application(Gtk.Application):
    def __init__(self, application_id="org.omarchy.AgentSettings"):
        super().__init__(application_id=application_id,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        action = Gio.SimpleAction.new("panel", GLib.VariantType.new("as"))
        action.connect("activate", lambda _action, arguments: self.handle_arguments(arguments.unpack()))
        self.add_action(action)

    def do_activate(self):
        if not self.window:
            self.window = SettingsWindow(self)
        self.window.present()

    def do_command_line(self, command_line):
        return self.handle_arguments(command_line.get_arguments())

    def handle_arguments(self, arguments):
        if "--hide" in arguments:
            if self.window:
                self.window.dismiss()
            return 0
        if "--quit" in arguments:
            if self.window and (self.window.busy or self.window.terminal_pid or self.window.question_windows or self.window.delivery_pending):
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
