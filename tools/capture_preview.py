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
from app import Gtk, GLib, SettingsWindow, LayerShell
from core import private_write

MODELS = [{'model': '', 'displayName': 'Default', 'supportedReasoningEfforts': []}]


def settle():
    until = time.monotonic() + .3
    while time.monotonic() < until:
        while GLib.MainContext.default().iteration(False):
            pass
        time.sleep(.01)


with tempfile.TemporaryDirectory(prefix='omarchy-settings-preview-') as temp:
    env = {key: str(Path(temp) / name) for key, name in (
        ('XDG_CONFIG_HOME', 'config'), ('XDG_STATE_HOME', 'state'), ('XDG_DATA_HOME', 'data'))}
    with patch.dict(os.environ, env), patch('app.discover_models', return_value=MODELS), patch(
        'app.agent_executable', side_effect=lambda agent: sys.executable if agent in {'codex', 'claude'} else None
    ):
        private_write(Path(env['XDG_CONFIG_HOME']) / 'omarchy-agent-settings/settings.json',
                      {'agent': 'claude', 'repository': 'https://github.com/example/dotfiles', 'publish': True})
        application = Gtk.Application(application_id='org.omarchy.AgentSettings.Preview')
        application.register(None)
        window = SettingsWindow(application)
        LayerShell.set_keyboard_mode(window, LayerShell.KeyboardMode.NONE)
        window.set_can_target(False)
        window.present()
        settle()
        x, y, width, height = map(int, window.popup_bounds)
        region = f'{x},{y} {width}x{height}'
        subprocess.run(['grim', '-g', region, str(ROOT / 'preview.png')], check=True)
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
        settle()
        window.scroll.get_vadjustment().set_value(110)
        settle()
        subprocess.run(['grim', '-g', region, str(ROOT / 'docs/conversation.png')], check=True)
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
        window.update_buttons()
        window.client = None
        GLib.source_remove(window.theme_timer)
        GLib.source_remove(window.attention_timer)
        window.destroy()
        print('Captured preview.png, docs/questions.png and docs/conversation.png; spinner animates after reopening')
