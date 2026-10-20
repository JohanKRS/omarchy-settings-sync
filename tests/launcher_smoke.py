#!/usr/bin/env python3
"""Check the shell's warm D-Bus route; requires PyGObject and a session bus."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def serve(application_id, output):
    from gi.repository import Gio, GLib
    application = Gio.Application(application_id=application_id)
    action = Gio.SimpleAction.new('panel', GLib.VariantType.new('as'))
    def receive(_action, arguments):
        with output.open('a') as target:
            target.write(json.dumps(arguments.unpack()) + '\n')
    action.connect('activate', receive)
    application.add_action(action)
    application.register(None)
    output.write_text('ready\n')
    GLib.MainLoop().run()


def wait_for(output, count):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        lines = output.read_text().splitlines() if output.exists() else []
        if len(lines) >= count:
            return lines
        time.sleep(.01)
    raise AssertionError('Launcher did not deliver its arguments')


def main():
    with tempfile.TemporaryDirectory(prefix='omarchy-launcher-test-') as temporary:
        directory = Path(temporary)
        output = directory / 'requests'
        application_id = f'org.omarchy.AgentSettings.LauncherTest.P{os.getpid()}'
        process = subprocess.Popen([sys.executable, __file__, '--serve', application_id, str(output)])
        try:
            wait_for(output, 1)
            # A warm launch must not fall back to Python, including with no arguments.
            python = directory / 'python3'
            python.write_text('#!/bin/sh\necho "Unexpected Python fallback" >&2\nexit 99\n')
            python.chmod(0o755)
            env = {**os.environ, 'AGENT_SETTINGS_APP_ID': application_id,
                   'PATH': str(directory) + os.pathsep + os.environ['PATH']}
            cases = [[], ['--hide'], ['--toggle', '--monitor=HDMI-A-1', '--anchor-x=42'],
                     ["--literal=quote'backslash\\", 'line\nreturn\rtab\t',
                      '$(not-a-command); `also-not-a-command`', 'Unicode: configuração', '']]
            for count, arguments in enumerate(cases, 2):
                subprocess.run(['bash', str(ROOT / 'plugin/launch.sh'), *arguments],
                               env=env, check=True, timeout=5)
                assert json.loads(wait_for(output, count)[-1]) == arguments
        finally:
            process.terminate()
            process.wait(timeout=5)
    print('Launcher D-Bus smoke passed (empty, hide, positioning and literal arguments)')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--serve':
        serve(sys.argv[2], Path(sys.argv[3]))
    else:
        main()
