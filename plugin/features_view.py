"""The Settings tab: one switch per catalog feature, staged until Apply."""
from __future__ import annotations

from dataclasses import dataclass, field
import platform
from pathlib import Path

from gi.repository import GLib, Gtk, Pango

from applier import Applier, Ledger, delegation, status
import checkout
from context import repository_state
from core import private_write
from features import (GROUPS, Probe, dependents, desired, has_catalog, install_id, list_machines, load_catalog,
                      load_machine, machine_name, machine_path, machine_text, off_mode, ordered, part_enabled,
                      remove_machine, rename_machine, valid_machine)
from i18n import tr

FILTERS = ("all", "on", "off", "new", "pending", "modified", "unavailable")
FILTER_LABELS = {"all": "All", "on": "On", "off": "Off", "new": "New", "pending": "Pending",
                 "modified": "Edited locally", "unavailable": "Not applicable"}
STATUS_LABELS = {"applied": "Applied", "pending": "Pending", "modified": "Edited locally", "off": "Off",
                 "new": "New", "unavailable": "Not applicable"}
GROUP_LABELS = {"desktop": "Desktop", "apps": "Apps", "system": "System"}
AREA_LABELS = {"hyprland": "Hyprland", "firefox": "Firefox", "shell": "Shell", "voxtype": "Voxtype", "mime": "MIME", "gtk": "GTK"}


@dataclass
class Snapshot:
    checkout: Path = None
    sha: str = ""
    problem: str = None
    features: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    machine_name: str = ""
    machine: dict = field(default_factory=dict)
    ledger: Ledger = None
    states: dict = field(default_factory=dict)
    labels: dict = field(default_factory=dict)
    failing: dict = field(default_factory=dict)
    machines: list = field(default_factory=list)
    binding_needed: bool = False

    @property
    def catalog(self):
        return has_catalog(self.checkout)


def state_dir(window):
    return repository_state(window.locations, window.settings["repository"])


def local_catalog(window):
    return state_dir(window) / "features.local.toml"


def results_path(window):
    return state_dir(window) / "agent-results.json"


def make_applier(window, path, ledger):
    return Applier(path, ledger, window.locations["state"] / "backups", script_dir=state_dir(window))


def collect(window, *, fetch=False):
    """Read everything the tab shows. Runs in a worker thread."""
    snapshot = Snapshot(machine_name=machine_name(window.settings))
    repository = window.settings.get("repository")
    if not repository:
        snapshot.problem = tr('Choose a configuration repository in Settings.')
        return snapshot
    path = checkout.location(window.locations["workspace"], repository)
    if fetch or not (path / ".git").exists():
        path, snapshot.sha, snapshot.problem = checkout.update(
            window.locations["workspace"], repository, window.settings.get("branch", ""))
    else:
        snapshot.sha = checkout.head(path)
    snapshot.checkout = path
    snapshot.features, snapshot.errors = load_catalog(path, local_catalog(window))
    snapshot.machine = load_machine(path, snapshot.machine_name)
    snapshot.machines = list_machines(path)
    if "machine" not in window.settings and snapshot.machines:
        # After a reinstall, ask which machine this is instead of guessing.
        known = {info["name"]: info for info in snapshot.machines}
        mine = known.get(snapshot.machine_name)
        snapshot.binding_needed = not mine or bool(mine["install"] and mine["install"] != install_id())
    snapshot.ledger = Ledger(state_dir(window) / "applied.json")
    applier = make_applier(window, path, snapshot.ledger)
    if results_path(window).exists():
        applier.merge_agent_results(results_path(window), snapshot.features)
    probe = Probe()
    for feature in snapshot.features:
        failing = probe.applicable(feature)
        if failing:
            snapshot.failing[feature.id] = failing
        choice = desired(feature, snapshot.machine)
        states = applier.inspect(feature) if choice == "on" and not failing else {}
        snapshot.states[feature.id] = states
        snapshot.labels[feature.id] = status(feature, choice, off_mode(feature, snapshot.machine),
                                             snapshot.ledger, states, failing)
    return snapshot


def changes_for_sync(snapshot):
    """Features a Sync should process on this machine: (feature, action, mode)."""
    result = []
    for feature in ordered(snapshot.features):
        if feature.id in snapshot.failing:
            continue
        choice = desired(feature, snapshot.machine)
        mode = off_mode(feature, snapshot.machine)
        if choice == "on":
            result.append((feature, "on", mode))
        elif choice == "off" and snapshot.ledger.applied(feature.id) and mode != "keep":
            result.append((feature, "off", mode))
    return result


def run_changes(window, snapshot, changes):
    """Apply (feature, action, mode) triples; returns outcomes. Runs in a worker thread."""
    applier = make_applier(window, snapshot.checkout, snapshot.ledger)
    outcomes = []
    offs = [change for change in changes if change[1] == "off"]
    ons = [change for change in changes if change[1] == "on"]
    for feature, _, mode in reversed(offs):
        outcomes.append(applier.disable(feature, mode))
    for feature, _, _ in ons:
        outcomes.append(applier.enable(feature, snapshot.machine))
    applier.finish(outcomes)
    snapshot.ledger.data["sha"] = snapshot.sha
    snapshot.ledger.save()
    return outcomes


def save_machine(window, snapshot, publish):
    """Write this machine's choices; publish them when publishing is enabled."""
    path = machine_path(snapshot.checkout, snapshot.machine_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    version = Probe().omarchy()
    path.write_text(machine_text(snapshot.machine_name, snapshot.machine, hostname=platform.node(),
                                 omarchy=version, updated=GLib.DateTime.new_now_utc().format_iso8601(),
                                 install=install_id()))
    if not publish:
        return None
    return checkout.publish(snapshot.checkout, window.settings.get("branch", ""), [path],
                            f"Update settings for {snapshot.machine_name}")


class FeaturesPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.window = window
        self.snapshot = None
        self.staged = {}
        self.expanded = set()
        self.loading = False
        for side in ("top", "bottom", "start", "end"):
            getattr(self, "set_margin_" + side)(14)
        tools = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(placeholder_text=tr('Search customizations'), hexpand=True)
        self.search.connect("search-changed", lambda *_: self.render())
        tools.append(self.search)
        self.filter = Gtk.DropDown.new_from_strings([tr(FILTER_LABELS[key]) for key in FILTERS])
        self.filter.connect("notify::selected", lambda *_: self.render())
        tools.append(self.filter)
        self.append(tools)
        machine_row = Gtk.Box(spacing=8)
        self.machine_label = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self.machine_label.add_css_class("muted")
        machine_row.append(self.machine_label)
        self.machines_button = Gtk.Button(label=tr('Manage machines'))
        self.machines_button.add_css_class("flat")
        self.machines_button.connect("clicked", lambda *_: self.show_machines())
        machine_row.append(self.machines_button)
        self.append(machine_row)
        self.banner = Gtk.Box(spacing=8, visible=False)
        self.banner.add_css_class("features-banner")
        self.banner_text = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.banner_text.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.banner.append(self.banner_text)
        self.banner_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self.banner_button.connect("clicked", lambda *_: self.banner_action())
        self.banner.append(self.banner_button)
        self.append(self.banner)
        self.listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.listing)
        self.append(scroll)
        self.bar = Gtk.Box(spacing=8, visible=False)
        self.bar.add_css_class("pending-bar")
        self.bar_text = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.bar_text.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.bar.append(self.bar_text)
        discard = Gtk.Button(label=tr('Discard'), valign=Gtk.Align.CENTER)
        discard.connect("clicked", lambda *_: self.discard())
        self.bar.append(discard)
        self.apply_button = Gtk.Button(label=tr('Apply'), valign=Gtk.Align.CENTER)
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", lambda *_: self.apply())
        self.bar.append(self.apply_button)
        self.append(self.bar)
        self.banner_mode = None
        self.controls = []

    def sync_sensitivity(self):
        for widget in self.controls:
            widget.set_sensitive(not self.window.busy)
        if self.bar.get_visible():
            self.apply_button.set_sensitive(not self.window.busy and not self.loading)

    # Data ------------------------------------------------------------------
    def refresh(self, fetch=False):
        if self.loading or not self.window.settings.get("repository"):
            if not self.window.settings.get("repository"):
                self.show_banner(tr('Choose a configuration repository in Settings.'), None)
            return
        self.loading = True
        self.machine_label.set_text(tr('Loading customizations…'))
        def done(snapshot):
            self.loading = False
            self.snapshot = snapshot
            self.render()
        def failed(message):
            self.loading = False
            self.show_banner(message, None)
        self.window.worker(lambda: collect(self.window, fetch=fetch), done, failed)

    def show_banner(self, text, mode, button=None):
        self.banner_mode = mode
        self.banner_text.set_text(text)
        self.banner_button.set_visible(bool(mode))
        if button:
            self.banner_button.set_label(button)
        self.banner.set_visible(bool(text))

    def banner_action(self):
        if self.banner_mode == "migrate":
            self.window.migrate_catalog()
        elif self.banner_mode == "fix":
            self.window.ask_agent_about_catalog(self.snapshot.errors)
        elif self.banner_mode == "machines":
            self.show_machines()

    # Rendering ---------------------------------------------------------------
    def effective(self, feature):
        staged = self.staged.get(feature.id, {})
        return staged.get("state") or desired(feature, self.snapshot.machine)

    def render(self):
        while self.listing.get_first_child():
            self.listing.remove(self.listing.get_first_child())
        self.controls = []
        snapshot = self.snapshot
        if not snapshot:
            return
        machine = snapshot.machine_name
        self.machine_label.set_text(tr('Machine not chosen yet') if snapshot.binding_needed
                                    else tr('On this machine: {name}', name=machine))
        self.machines_button.set_sensitive(bool(snapshot.checkout))
        if snapshot.binding_needed:
            self.show_banner(tr('This installation is not linked to a machine yet. Choose one to reuse its choices, or create a new one.'),
                             "machines", tr('Choose machine'))
        elif snapshot.problem and not snapshot.catalog:
            self.show_banner(tr('The repository could not be updated: {problem}', problem=snapshot.problem), None)
        elif not snapshot.catalog and not snapshot.features:
            self.show_banner(tr('This repository has no customizations catalog yet. The agent can create one from your current settings.'),
                             "migrate", tr('Create catalog'))
        elif snapshot.errors:
            self.show_banner(tr('The catalog has {count} problems.', count=len(snapshot.errors)), "fix", tr('Fix with the agent'))
        elif snapshot.problem:
            self.show_banner(tr('Showing the local copy. {problem}', problem=snapshot.problem), None)
        else:
            self.show_banner("", None)
        query = self.search.get_text().casefold().strip()
        wanted = FILTERS[self.filter.get_selected()] if self.filter.get_selected() < len(FILTERS) else "all"
        groups = {}
        for feature in snapshot.features:
            label = snapshot.labels.get(feature.id, "off")
            text = " ".join([feature.title, feature.summary, feature.id, *feature.areas]).casefold()
            if query and query not in text:
                continue
            on = self.effective(feature) == "on"
            if wanted == "on" and not on or wanted == "off" and on:
                continue
            if wanted not in ("all", "on", "off") and label != wanted:
                continue
            groups.setdefault(feature.group, []).append(feature)
        for group in GROUPS:
            if group not in groups:
                continue
            heading = Gtk.Label(label=tr(GROUP_LABELS[group]).upper(), xalign=0)
            heading.add_css_class("feature-group")
            self.listing.append(heading)
            for feature in groups[group]:
                self.listing.append(self.row(feature))
        if not groups and snapshot.features:
            empty = Gtk.Label(label=tr('No customizations match.'), xalign=0)
            empty.add_css_class("muted")
            self.listing.append(empty)
        self.update_bar()

    def row(self, feature):
        snapshot = self.snapshot
        label = snapshot.labels.get(feature.id, "off")
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        frame.add_css_class("feature-row")
        if label == "unavailable":
            frame.add_css_class("unavailable")
        head = Gtk.Box(spacing=10)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Label(label=feature.title, xalign=0, wrap=True)
        title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title.add_css_class("feature-title")
        texts.append(title)
        details = [AREA_LABELS.get(area, area.capitalize()) for area in feature.areas]
        if feature.needs_agent:
            details.append(tr('uses the agent'))
        if feature.needs_admin:
            details.append(tr('asks for password'))
        if feature.local:
            details.append(tr('this machine only'))
        if label == "unavailable":
            details = [tr('Not applicable here: {condition}', condition=snapshot.failing[feature.id])]
        if details:
            subtitle = Gtk.Label(label=" · ".join(details), xalign=0, wrap=True)
            subtitle.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            subtitle.add_css_class("muted")
            texts.append(subtitle)
        head.append(texts)
        staged = feature.id in self.staged
        badge = Gtk.Label(label=tr('Changed') if staged else tr(STATUS_LABELS[label]), valign=Gtk.Align.CENTER)
        badge.add_css_class("feature-status")
        badge.add_css_class("status-" + ("staged" if staged else label))
        head.append(badge)
        switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=self.effective(feature) == "on")
        switch.set_sensitive(label != "unavailable" and not self.window.busy)
        if label != "unavailable":
            self.controls.append(switch)
        switch.update_property([Gtk.AccessibleProperty.LABEL], [feature.title])
        switch.connect("notify::active", lambda widget, _: self.toggled(feature, widget.get_active()))
        head.append(switch)
        frame.append(head)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self.toggle_details(feature))
        texts.add_controller(click)
        revealer = Gtk.Revealer(reveal_child=feature.id in self.expanded)
        revealer.set_child(self.details(feature))
        frame.append(revealer)
        return frame

    def details(self, feature):
        snapshot = self.snapshot
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.add_css_class("feature-details")
        if feature.summary:
            summary = Gtk.Label(label=feature.summary, xalign=0, wrap=True)
            summary.add_css_class("muted")
            content.append(summary)
        states = snapshot.states.get(feature.id, {})
        staged_parts = self.staged.get(feature.id, {}).get("parts", {})
        for part in feature.parts:
            line = Gtk.Box(spacing=8)
            name = Gtk.Label(label=part.title, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
            name.set_tooltip_text(part.data.get("dest") or part.title)
            line.append(name)
            who = tr('agent') if part.agent else tr('asks for password') if part.admin else tr('plugin')
            state = states.get(part.key)
            if state in ("modified", "missing", "outdated"):
                who = tr(STATUS_LABELS["modified" if state == "modified" else "pending"]) + " · " + who
            hint = Gtk.Label(label=who)
            hint.add_css_class("muted")
            line.append(hint)
            if part.optional:
                key = f"{feature.id}.{part.data['id']}"
                active = staged_parts.get(key, "on" if part_enabled(feature, part, snapshot.machine) else "off") == "on"
                toggle = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
                toggle.set_sensitive(not self.window.busy)
                self.controls.append(toggle)
                toggle.connect("notify::active", lambda widget, _, k=key: self.part_toggled(feature, k, widget.get_active()))
                line.append(toggle)
            content.append(line)
        off = Gtk.Label(label=tr('When turned off on this machine:'), xalign=0)
        off.add_css_class("feature-group")
        content.append(off)
        current = self.staged.get(feature.id, {}).get("mode", off_mode(feature, snapshot.machine))
        group = None
        for mode, text in (("default", tr('Remove and return to the Omarchy default')),
                           ("keep", tr('Stop syncing and keep it as it is')),
                           ("previous", tr('Restore how it was before (backup)'))):
            option = Gtk.CheckButton(label=text, active=current == mode)
            if group:
                option.set_group(group)
            group = group or option
            option.set_sensitive(not self.window.busy)
            self.controls.append(option)
            option.connect("toggled", lambda widget, m=mode: widget.get_active() and self.mode_changed(feature, m))
            content.append(option)
        talk = Gtk.Button(label=tr('Talk about this customization'), halign=Gtk.Align.START)
        talk.connect("clicked", lambda *_: self.window.discuss_feature(feature))
        content.append(talk)
        return content

    # Staging ---------------------------------------------------------------
    def toggle_details(self, feature):
        self.expanded.symmetric_difference_update({feature.id})
        self.render()

    def stage(self, feature, **values):
        entry = self.staged.setdefault(feature.id, {})
        entry.update(values)
        base = desired(feature, self.snapshot.machine)
        if entry.get("state") == base:
            entry.pop("state")
        if entry.get("mode") == off_mode(feature, self.snapshot.machine):
            entry.pop("mode")
        if not entry.get("parts"):
            entry.pop("parts", None)
        if not entry:
            self.staged.pop(feature.id)

    def toggled(self, feature, active):
        if (self.effective(feature) == "on") == active:
            return
        by_id = {f.id: f for f in self.snapshot.features}
        self.stage(feature, state="on" if active else "off")
        if active:
            for required in ordered(self.snapshot.features, feature.requires):
                if required.id != feature.id and self.effective(required) != "on":
                    self.stage(required, state="on")
        else:
            for dependent in dependents(self.snapshot.features, feature.id):
                if self.effective(dependent) == "on":
                    self.stage(by_id[dependent.id], state="off")
            if self.snapshot.ledger.applied(feature.id):
                self.expanded.add(feature.id)
        GLib.idle_add(self.render)

    def part_toggled(self, feature, key, active):
        parts = dict(self.staged.get(feature.id, {}).get("parts", {}))
        saved = self.snapshot.machine.get("parts", {}).get(key, "on")
        value = "on" if active else "off"
        if value == saved:
            parts.pop(key, None)
        else:
            parts[key] = value
        self.stage(feature, parts=parts)
        self.update_bar()

    def mode_changed(self, feature, mode):
        self.stage(feature, mode=mode)
        self.update_bar()

    def discard(self):
        self.staged.clear()
        self.render()

    def update_bar(self):
        if not self.staged or not self.snapshot:
            self.bar.set_visible(False)
            return
        by_id = {f.id: f for f in self.snapshot.features}
        ons = [i for i, e in self.staged.items() if e.get("state") == "on"]
        offs = [i for i, e in self.staged.items() if e.get("state") == "off"]
        other = [i for i, e in self.staged.items() if "state" not in e]
        parts = []
        if ons:
            parts.append(tr('{count} to turn on', count=len(ons)))
        if offs:
            parts.append(tr('{count} to turn off', count=len(offs)))
        if other:
            parts.append(tr('{count} adjusted', count=len(other)))
        touched = [by_id[i] for i in self.staged if i in by_id]
        if any(f.needs_admin for f in touched):
            parts.append(tr('asks for password'))
        if any(f.needs_agent for f in touched):
            parts.append(tr('uses the agent'))
        self.bar_text.set_text(" · ".join(parts))
        self.apply_button.set_sensitive(not self.window.busy and not self.loading)
        self.bar.set_visible(True)

    def apply(self):
        if not self.staged or self.window.busy or not self.snapshot:
            return
        if self.snapshot.binding_needed:
            self.show_machines()
            return
        snapshot, staged = self.snapshot, dict(self.staged)
        machine = snapshot.machine
        for identifier, entry in staged.items():
            if "state" in entry:
                machine.setdefault("features", {})[identifier] = entry["state"]
            if "mode" in entry:
                if entry["mode"] == "default":
                    machine.setdefault("off", {}).pop(identifier, None)
                else:
                    machine.setdefault("off", {})[identifier] = entry["mode"]
            for key, value in entry.get("parts", {}).items():
                machine.setdefault("parts", {})[key] = value
        by_id = {feature.id: feature for feature in snapshot.features}
        changes = []
        for feature in ordered(snapshot.features, [i for i in staged if i in by_id]):
            choice = desired(feature, machine)
            mode = off_mode(feature, machine)
            if choice == "on":
                changes.append((feature, "on", mode))
            elif choice == "off" and snapshot.ledger.applied(feature.id):
                changes.append((feature, "off", mode))
        publish = self.window.publish.get_active()
        self.staged.clear()
        self.loading = True
        self.apply_button.set_sensitive(False)
        self.window.status.set_text(tr('Applying customizations…'))
        def work():
            problem = save_machine(self.window, snapshot, publish)
            return run_changes(self.window, snapshot, changes), problem
        def done(result):
            self.loading = False
            self.window.features_applied(snapshot, *result)
        def failed(message):
            self.loading = False
            self.window.failure(message)
            self.refresh()
        self.window.worker(work, done, failed)

    # Machines --------------------------------------------------------------
    def show_machines(self):
        if not self.snapshot or not self.snapshot.checkout:
            return
        panel = self.window.make_panel(tr('Machines'))
        self.machines_panel = panel
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.set_content(content)
        self.render_machines(content)
        panel.present()

    def render_machines(self, content, editing=None, confirming=None, message=""):
        while content.get_first_child():
            content.remove(content.get_first_child())
        snapshot = self.snapshot
        current = snapshot.machine_name
        bound = "machine" in self.window.settings and not snapshot.binding_needed
        intro = Gtk.Label(label=tr('Each installation uses the choices of one machine. After reinstalling, choose the same machine to get its choices back.'),
                          xalign=0, wrap=True)
        intro.add_css_class("muted")
        content.append(intro)
        if message:
            note = Gtk.Label(label=message, xalign=0, wrap=True)
            note.add_css_class("status-modified")
            content.append(note)
        names = [info["name"] for info in snapshot.machines]
        machines = list(snapshot.machines)
        if current not in names:
            machines.insert(0, {"name": current, "hostname": "", "omarchy": "", "updated": "", "install": "",
                                "on": 0, "off": 0, "unsaved": True})
        busy = self.window.busy or self.loading
        for info in machines:
            name = info["name"]
            mine = name == current and bound
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            row.add_css_class("feature-row")
            head = Gtk.Box(spacing=8)
            title = Gtk.Label(label=name, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
            title.add_css_class("feature-title")
            head.append(title)
            if mine:
                badge = Gtk.Label(label=tr('this installation'))
                badge.add_css_class("feature-status")
                badge.add_css_class("status-applied")
                head.append(badge)
            row.append(head)
            details = []
            if info.get("unsaved"):
                details.append(tr('not saved yet'))
            if info["hostname"]:
                details.append(info["hostname"])
            if info["omarchy"]:
                details.append("Omarchy " + info["omarchy"])
            if info["updated"]:
                details.append(tr('updated {date}', date=info["updated"][:10]))
            if not info.get("unsaved"):
                details.append(tr('{on} on · {off} off', on=info["on"], off=info["off"]))
            if info["install"] and info["install"] == install_id() and not mine:
                details.append(tr('same installation as this one'))
            line = Gtk.Label(label=" · ".join(details), xalign=0, wrap=True)
            line.add_css_class("muted")
            row.append(line)
            actions = Gtk.Box(spacing=6)
            if editing == name:
                entry = Gtk.Entry(text=name, hexpand=True)
                actions.append(entry)
                save = Gtk.Button(label=tr('Save'))
                save.add_css_class("suggested-action")
                save.connect("clicked", lambda *_, old=name, field=entry: self.machine_action(
                    content, "rename", old, field.get_text().strip()))
                entry.connect("activate", lambda field, old=name: self.machine_action(content, "rename", old, field.get_text().strip()))
                actions.append(save)
                cancel = Gtk.Button(label=tr('Cancel'))
                cancel.connect("clicked", lambda *_: self.render_machines(content))
                actions.append(cancel)
            elif confirming == name:
                question = Gtk.Label(label=tr('Remove {name} from the repository?', name=name), xalign=0, hexpand=True, wrap=True)
                actions.append(question)
                remove = Gtk.Button(label=tr('Remove'))
                remove.connect("clicked", lambda *_, n=name: self.machine_action(content, "remove", n))
                actions.append(remove)
                cancel = Gtk.Button(label=tr('Cancel'))
                cancel.connect("clicked", lambda *_: self.render_machines(content))
                actions.append(cancel)
            else:
                if not mine:
                    use = Gtk.Button(label=tr('Use on this installation'))
                    use.add_css_class("suggested-action")
                    use.connect("clicked", lambda *_, n=name: self.machine_action(content, "use", n))
                    actions.append(use)
                if not info.get("unsaved"):
                    rename = Gtk.Button(label=tr('Rename'))
                    rename.connect("clicked", lambda *_, n=name: self.render_machines(content, editing=n))
                    actions.append(rename)
                    if not mine:
                        remove = Gtk.Button(label=tr('Remove'))
                        remove.connect("clicked", lambda *_, n=name: self.render_machines(content, confirming=n))
                        actions.append(remove)
            for child in list(_children(actions)):
                if isinstance(child, (Gtk.Button, Gtk.Entry)):
                    child.set_sensitive(not busy)
            row.append(actions)
            content.append(row)
        create = Gtk.Box(spacing=6)
        entry = Gtk.Entry(placeholder_text=tr('New machine name'), hexpand=True)
        create.append(entry)
        add = Gtk.Button(label=tr('Create and use'))
        add.connect("clicked", lambda *_: self.machine_action(content, "create", entry.get_text().strip()))
        entry.connect("activate", lambda *_: self.machine_action(content, "create", entry.get_text().strip()))
        add.set_sensitive(not busy)
        create.append(add)
        content.append(create)

    def machine_action(self, content, action, name, new=None):
        snapshot = self.snapshot
        if action == "create":
            name, new = name.lower(), None
        target = (new or "").lower() if action == "rename" else name
        if action in ("rename", "create") and not valid_machine(target):
            self.render_machines(content, editing=name if action == "rename" else None,
                                 message=tr('Use lowercase letters, digits and hyphens.'))
            return
        if action == "create" and target in {info["name"] for info in snapshot.machines}:
            self.render_machines(content, message=tr('A machine with this name already exists.'))
            return
        publish = self.window.publish.get_active()
        branch = self.window.settings.get("branch", "")
        def work():
            paths = []
            if action == "rename":
                paths = rename_machine(snapshot.checkout, name, target)
            elif action == "remove":
                paths = remove_machine(snapshot.checkout, name)
            elif action == "create":
                path = machine_path(snapshot.checkout, target)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(machine_text(target, {}, hostname=platform.node(), omarchy=Probe().omarchy(),
                                             updated=GLib.DateTime.new_now_utc().format_iso8601(), install=install_id()))
                paths = [path]
            if not paths or not publish:
                return None
            verb = {"rename": f"Rename machine {name} to {target}", "remove": f"Remove machine {name}",
                    "create": f"Add machine {target}"}[action]
            return checkout.publish(snapshot.checkout, branch, paths, verb)
        def done(problem):
            self.loading = False
            settings = self.window.settings
            if action in ("use", "create") or (action == "rename" and name == snapshot.machine_name):
                settings["machine"] = target
            self.window.save_settings()
            if problem:
                self.window.status.set_text(tr('Not published: {problem}', problem=problem.splitlines()[0][:160]))
            if getattr(self, "machines_panel", None) in self.window.panels:
                self.machines_panel.destroy()
            self.refresh()
        def failed(message):
            self.loading = False
            self.render_machines(content, message=message)
        self.loading = True
        self.window.worker(work, done, failed)


def _children(widget):
    child = widget.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()
