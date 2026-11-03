#!/usr/bin/env python3
"""Capture the panel with synthetic data; requires an Omarchy session and grim."""
import os
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
os.environ['AGENT_SETTINGS_LANGUAGE'] = 'en'
sys.path.insert(0, str(ROOT / 'plugin'))
from app import Gtk, Gdk, GLib, SettingsWindow, LayerShell
from attachments import save_image
from core import private_write

MODELS = [{'model': '', 'displayName': 'Default', 'supportedReasoningEfforts': []}]


def widgets(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from widgets(child)
        child = child.get_next_sibling()


def settle():
    until = time.monotonic() + .3
    while time.monotonic() < until:
        while GLib.MainContext.default().iteration(False):
            pass
        time.sleep(.01)


CATALOG = """version = 1

[[feature]]
id = "lock-shortcut"
title = "Super+L locks the screen"
summary = "Super+Ctrl+L toggles the workspace layout instead."
app = "hyprland"
areas = ["hyprland"]
[[feature.part]]
kind = "block"
dest = "~/.config/hypr/bindings.lua"
text = "-- lock"

[[feature]]
id = "window-layout"
title = "Main apps take two thirds of the screen"
app = "hyprland"
areas = ["hyprland"]
[[feature.part]]
kind = "line"
dest = "~/.config/hypr/hyprland.lua"
text = 'require("hypr.window-layout")'

[[feature]]
id = "idle-timers"
title = "Screensaver after 5 minutes, lock after 10"
app = "shell"
[[feature.part]]
kind = "json"
dest = "~/.config/omarchy/shell.json"
values = { "idle.screensaver" = 300, "idle.lock" = 600 }

[[feature]]
id = "firefox-popups"
title = "Website popups float centered"
summary = "Passkey and extension popups float on the browser's workspace."
app = "firefox"
areas = ["firefox", "hyprland"]
[[feature.part]]
kind = "line"
dest = "~/.config/hypr/hyprland.lua"
text = 'require("hypr.firefox-popups")'
[[feature.part]]
kind = "agent"
id = "profile"
optional = true
title = "Module in the Firefox profile"
instructions = "Install the profile module."

[[feature]]
id = "firefox-toolbar"
title = "Compact bookmarks toolbar"
app = "firefox"
[[feature.part]]
kind = "agent"
title = "userChrome.css block"
instructions = "Merge the toolbar block."

[[feature]]
id = "dictation"
title = "Hold Menu to dictate"
app = "voxtype"
areas = ["voxtype", "hyprland"]
[[feature.part]]
kind = "line"
dest = "~/.config/hypr/bindings.lua"
text = "-- dictation"

[[feature]]
id = "no-sleep"
title = "The computer never suspends"
group = "system"
[[feature.part]]
kind = "line"
dest = "~/.config/example-no-sleep"
text = "AllowSuspend=no"

[[program]]
package = "papers"
title = "Papers"

[[program]]
package = "libreoffice-fresh"
title = "LibreOffice"
action = "remove"
icon = "libreoffice-main"
"""


def make_catalog(path):
    """A synthetic configuration repository for the Customizations screenshots."""
    path.mkdir(parents=True, exist_ok=True)
    (path / 'features.toml').write_text(CATALOG)
    (path / 'machines').mkdir(exist_ok=True)
    for name, host, version, updated in (('desktop', 'desktop', '4.0.6-1', '2026-11-03T18:30:00Z'),
                                         ('laptop', 'laptop', '4.0.6-1', '2026-10-30T09:12:00Z')):
        (path / f'machines/{name}.toml').write_text(
            f'name = "{name}"\nhostname = "{host}"\nomarchy = "{version}"\nupdated = "{updated}"\n\n'
            '[features]\n"lock-shortcut" = "on"\n"window-layout" = "on"\n"idle-timers" = "on"\n'
            '"firefox-popups" = "on"\n"firefox-toolbar" = "on"\n"no-sleep" = "off"\n"program-libreoffice-fresh" = "on"\n')
    subprocess.run(['git', 'init', '-q', str(path)], check=True)
    subprocess.run(['git', '-C', str(path), 'remote', 'add', 'origin', 'https://github.com/example/dotfiles'], check=True)


def capture_customizations(window, region):
    page = window.features_page
    page.fetched = time.monotonic()  # The example remote is fictional; never fetch it.
    window.show_page('features')
    deadline = time.monotonic() + 10
    while not (page.snapshot and page.snapshot.features) and time.monotonic() < deadline:
        settle()
    snapshot = page.snapshot
    # Show the states a real machine goes through; destinations here are fictional.
    snapshot.labels.update({'lock-shortcut': 'applied', 'window-layout': 'applied', 'idle-timers': 'applied',
                            'firefox-popups': 'applied', 'firefox-toolbar': 'pending', 'dictation': 'new',
                            'no-sleep': 'off', 'program-papers': 'new', 'program-libreoffice-fresh': 'applied'})
    page.render()
    settle()
    subprocess.run(['grim', '-g', region, str(ROOT / 'docs/customizations.png')], check=True)
    snapshot.release = {'from': '4.0.6-1', 'to': '4.1.0-1', 'dismissed': [], 'impacts': {'idle-timers': {
        'kind': 'default-changed', 'files': ['config/omarchy/shell.json'],
        'diff': '--- config/omarchy/shell.json (before)\n+++ config/omarchy/shell.json (now)\n@@ -2,4 +2,4 @@\n'
                '   "idle": {\n-    "screensaver": 150,\n-    "lock": 300\n+    "screensaver": 180,\n+    "lock": 360\n   },',
        'keys': [{'key': 'idle.screensaver', 'before': 150, 'after': 180, 'mine': 300, 'kind': 'default-changed'},
                 {'key': 'idle.lock', 'before': 300, 'after': 360, 'mine': 600, 'kind': 'default-changed'}],
        'errors': ''}}}
    page.expanded.add('idle-timers')
    page.filter.set_selected(page_filter('release'))
    settle()
    subprocess.run(['grim', '-g', region, str(ROOT / 'docs/release-review.png')], check=True)
    page.expanded.clear()
    page.filter.set_selected(0)
    snapshot.release = {}
    page.show_machines()
    settle()
    subprocess.run(['grim', '-g', region, str(ROOT / 'docs/machines.png')], check=True)
    page.hide_machines()
    page.render()
    settle()


def page_filter(name):
    from features_view import FILTERS
    return FILTERS.index(name)


def compose_showcase():
    """preview.png: the marketplace and README picture, two panels beside a short pitch."""
    import cairo
    from theme import palette
    colors = palette()
    def rgb(value, alpha=1):
        value = value.lstrip('#')
        return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (alpha,)
    width, height = 2400, 1400
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_source_rgba(*rgb(colors['background']))
    cr.paint()
    def panel(path, x, y, scale, alpha=1.0):
        image = cairo.ImageSurface.create_from_png(str(path))
        cr.save()
        cr.translate(x, y)
        cr.scale(scale, scale)
        cr.set_source_surface(image, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_BEST)
        cr.paint_with_alpha(alpha)
        cr.restore()
        return image.get_width() * scale, image.get_height() * scale
    panel(ROOT / 'docs/panel.png', 1110, 150, 0.92, 0.55)
    panel(ROOT / 'docs/customizations.png', 1430, 110, 1.0)
    family = 'JetBrainsMono Nerd Font'
    def text(words, x, y, size, color, weight=cairo.FONT_WEIGHT_NORMAL, spacing=0):
        cr.select_font_face(family, cairo.FONT_SLANT_NORMAL, weight)
        cr.set_font_size(size)
        cr.set_source_rgba(*color)
        cursor = x
        for letter in words:
            cr.move_to(cursor, y)
            cr.show_text(letter)
            cursor += cr.text_extents(letter).x_advance + spacing
    fg, accent = rgb(colors['foreground']), rgb(colors['accent'])
    muted = rgb(colors['foreground'], .62)
    text('OMARCHY PLUGIN', 140, 250, 28, accent, cairo.FONT_WEIGHT_BOLD, 6)
    text('Your setup,', 140, 360, 84, fg, cairo.FONT_WEIGHT_BOLD)
    text('on every machine.', 140, 460, 84, fg, cairo.FONT_WEIGHT_BOLD)
    text('Ask your agent for a change. Save it to your', 140, 560, 32, muted)
    text('repository. Switch it on, machine by machine.', 140, 606, 32, muted)
    points = ('One switch per customization, grouped by app',
              'Fresh install? Pick exactly what comes back',
              'Omarchy updated? See what changed in your setup',
              'Codex, Claude Code and 11 more agents')
    for index, point in enumerate(points):
        y = 730 + index * 86
        cr.set_source_rgba(*accent)
        cr.rectangle(140, y - 22, 18, 18)
        cr.fill()
        text(point, 186, y, 30, fg)
    text('github.com/JohanKRS/omarchy-settings-sync', 140, 1250, 24, muted)
    surface.write_to_png(str(ROOT / 'preview.png'))


with tempfile.TemporaryDirectory(prefix='omarchy-settings-preview-') as temp:
    env = {key: str(Path(temp) / name) for key, name in (
        ('XDG_CONFIG_HOME', 'config'), ('XDG_STATE_HOME', 'state'), ('XDG_DATA_HOME', 'data'))}
    with patch.dict(os.environ, env), patch('app.discover_models', return_value=MODELS), patch(
        'app.agent_executable', side_effect=lambda agent: sys.executable if agent in {'codex', 'claude'} else None
    ):
        private_write(Path(env['XDG_CONFIG_HOME']) / 'omarchy-agent-settings/settings.json',
                      {'agent': 'claude', 'repository': 'https://github.com/example/dotfiles', 'publish': True,
                       'machine': 'desktop'})
        make_catalog(Path(env['XDG_DATA_HOME']) / 'omarchy-agent-settings/workspace/repository')
        application = Gtk.Application(application_id='org.omarchy.AgentSettings.Preview')
        application.register(None)
        window = SettingsWindow(application)
        LayerShell.set_keyboard_mode(window, LayerShell.KeyboardMode.NONE)
        window.set_can_target(False)
        for controller in list(window.observe_controllers()):
            if isinstance(controller, (Gtk.GestureClick, Gtk.EventControllerKey)):
                window.remove_controller(controller)
        window.present()
        settle()
        x, y, width, height = map(int, window.popup_bounds)
        region = f'{x},{y} {width}x{height}'
        window.add_message('You', 'Set my terminal font to JetBrains Mono and save it for my other Omarchy machines.')
        window.add_message('Agent', 'I’ll update the terminal font on this machine, save the portable setting in your repository and document how to apply it with **Sync** on the others.')
        window.busy = True
        window.turn_id = 'preview-turn'
        window.status.set_text('Checking terminal settings…')
        window.update_buttons()
        settle()
        subprocess.run(['grim', '-g', region, str(ROOT / 'docs/panel.png')], check=True)
        window.busy = False
        window.turn_id = None
        window.new_chat()
        settle()
        window.setup()
        settle()
        review = next(w for w in widgets(window.setup_panel)
                      if isinstance(w, Gtk.Button) and w.get_label() == 'Review existing customizations')
        assert review.get_mapped(), 'Customization review must be visible in Settings'
        subprocess.run(['grim', '-g', region, str(ROOT / 'docs/settings.png')], check=True)
        window.setup_panel.on_close()
        window.client = Mock()
        window.busy = True
        window.request_from_agent({'id': 'preview', 'method': 'item/tool/requestUserInput', 'params': {
            'questions': [
                {'id': 'profile', 'question': 'Which configuration should this installation use?', 'options': [
                    {'label': 'Shared defaults', 'description': 'Apply the portable preferences from your repository.'},
                    {'label': 'Machine overrides', 'description': 'Keep the local hardware-specific settings.'}]},
                {'id': 'components', 'question': 'Which components should be synchronized?', 'multiSelect': True,
                 'options': [{'label': 'Keyboard shortcuts'}, {'label': 'Terminal preferences'}]},
            ]}})
        settle()
        subprocess.run(['grim', '-g', region, str(ROOT / 'docs/questions.png')], check=True)
        window.clear_questions()
        window.add_message('You', 'Compare the portable desktop folder options.')
        window.add_message('Agent', '''## Desktop folder options

Choose the location that fits this installation. See the [XDG documentation](https://www.freedesktop.org/wiki/Software/xdg-user-dirs/).

| Option | Result |
| --- | --- |
| **Desktop** | Shortcuts go into `~/Desktop`. |
| **Hidden folder** | Use `~/.local/share/desktop` to keep Home clean. |
| **Current setup** | Hide individual files with `.hidden`. |

**Bold**, *italic*, ~~removed~~ and `inline code` are supported. HTML can format <b>text</b> and insert<br>a line break.

- [x] Keep local preferences
- [ ] Save the reusable configuration

```sh
xdg-user-dir DESKTOP
```
''')
        window.turn_id = 'preview-turn'
        window.queue_message('Use the hidden folder and preserve existing shortcuts.')
        window.queue_message('Then document the portable setup.\nKeep the machine-specific paths local.')
        window.queue_message('Check the result on the next installation.')
        window.status.set_text('Working…')
        window.update_buttons()
        window.input.grab_focus()
        texture = Gdk.Texture.new_from_filename(str(ROOT / 'docs/settings.png'))
        window.draft_images = [save_image(window.locations['state'] / 'attachments',
                                         texture.save_to_png_bytes().get_data())]
        window.update_images()
        window.input.emit('insert-at-cursor',
                          'Use the screenshot to check the current settings.\n'
                          'Keep the shared configuration portable.\n'
                          'Preserve this machine’s display settings.\n'
                          'Document how to apply the changes elsewhere.\n'
                          'Keep the cursor visible as this request grows.')
        settle()
        window.scroll.get_vadjustment().set_value(110)
        settle()
        subprocess.run(['grim', '-g', region, str(ROOT / 'docs/conversation.png')], check=True)
        window.input.get_buffer().set_text('')
        window.draft_images = []
        window.update_images()
        window.add_message('Agent', '''Which desktop folder do you prefer?

1. **Desktop** — Keep shortcuts in `~/Desktop`.
2. **Hidden folder** — Store shortcuts under `~/.local/share/desktop`.
3. **Current setup** — Keep the existing location.
''')
        window.scroll.to_end(force=True)
        settle()
        subprocess.run(['grim', '-g', region, str(ROOT / 'docs/choices.png')], check=True)
        window.input.get_buffer().set_text('')
        window.draft_images = []
        window.update_images()
        # Verify the native spinner changes frames after hiding/reopening the
        # panel, the lifecycle that used to leave GTK's SVG paused.
        window.set_visible(False)
        settle()
        window.present()
        settle()
        ok, bounds = window.spinner.compute_bounds(window)
        assert ok
        spinner_region = f'{int(bounds.get_x())},{int(bounds.get_y())} {int(bounds.get_width())}x{int(bounds.get_height())}'
        frames = []
        for _ in range(3):
            settle()
            frames.append(hashlib.sha256(subprocess.check_output(['grim', '-g', spinner_region, '-'])).hexdigest())
        assert len(set(frames)) > 1, 'Activity indicator did not animate after reopening'
        window.busy = False
        window.turn_id = None
        window.update_buttons()
        for name, agent, topic in (
                ('Settings Sync · Terminal font', 'codex', 'Use JetBrains Mono in my terminal.'),
                ('Settings Sync · Shared keyboard shortcuts', 'claude', 'Sync my keyboard shortcuts.')):
            key = window.history.new_id(name, agent)
            window.history.save(key, {'name': name, 'agent': agent, 'thread_id': 'synthetic-session',
                                     'repository': 'https://github.com/example/dotfiles', 'branch': ''},
                                [{'role': 'You', 'text': topic}])
        window.show_history()
        settle()
        subprocess.run(['grim', '-g', region, str(ROOT / 'docs/history.png')], check=True)
        window.history_panel.destroy()
        capture_customizations(window, region)
        window.client = None
        GLib.source_remove(window.theme_timer)
        GLib.source_remove(window.attention_timer)
        window.destroy()
        compose_showcase()
        print('Captured preview.png, docs/panel.png, docs/settings.png, docs/questions.png, docs/conversation.png, '
              'docs/choices.png, docs/history.png, docs/customizations.png, docs/machines.png and '
              'docs/release-review.png; spinner animates after reopening')
