#!/usr/bin/env python3
"""Capture the panel with synthetic data; requires an Omarchy session and grim."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
os.environ['AGENT_SETTINGS_LANGUAGE'] = 'en'
sys.path.insert(0, str(ROOT / 'plugin'))
from app import Gtk, GLib, SettingsWindow
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
        window.client = None
        GLib.source_remove(window.theme_timer)
        GLib.source_remove(window.attention_timer)
        window.destroy()
        print('Captured preview.png and docs/questions.png using synthetic configuration')
