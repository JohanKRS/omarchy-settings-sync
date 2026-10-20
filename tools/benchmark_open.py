#!/usr/bin/env python3
"""Measure cold/repeated panel opening in isolated state, without an agent call."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, default=ROOT)
parser.add_argument('--samples', type=int, default=5)
parser.add_argument('--cold-only', action='store_true')
parser.add_argument('--serve', type=Path)
parser.add_argument('--client', action='store_true')
parser.add_argument('--app-id', default='org.omarchy.AgentSettings.Benchmark')
parser.add_argument('actions', nargs='*')
args = parser.parse_args()
sys.path.insert(0, str(args.source / 'plugin'))

if args.client:
    from launcher import main
    raise SystemExit(main(['benchmark', *args.actions], application_id=args.app_id))

if args.serve:
    import app
    class Window(app.SettingsWindow):
        def focus_content(self, *unused):
            super().focus_content(*unused)
            def frame(*unused):
                with args.serve.open('a') as output:
                    output.write(str(time.perf_counter_ns()) + '\n')
                return False
            self.add_tick_callback(frame)
    app.SettingsWindow = Window
    # Older versions did not accept an application_id constructor argument.
    application = app.Application()
    application.set_application_id(args.app_id)
    raise SystemExit(application.run(['benchmark']))


def await_frame(path, previous):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        frames = path.read_text().splitlines() if path.exists() else []
        if len(frames) > previous:
            return int(frames[-1])
        time.sleep(.002)
    raise RuntimeError('No new frame within five seconds')


cold, warm = [], []
with tempfile.TemporaryDirectory(prefix='omarchy-settings-benchmark-') as temp:
    directory = Path(temp)
    env = {**os.environ, **{key: str(directory / name) for key, name in (
        ('XDG_CONFIG_HOME', 'config'), ('XDG_STATE_HOME', 'state'), ('XDG_DATA_HOME', 'data'))}}
    settings = directory / 'config/omarchy-agent-settings/settings.json'
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({'agent': 'codex', 'repository': 'https://github.com/example/dotfiles'}))
    for sample in range(args.samples):
        output = directory / f'frames-{sample}'
        app_id = f'org.omarchy.AgentSettings.Benchmark.P{os.getpid()}S{sample}'
        base = [sys.executable, str(Path(__file__).resolve()), '--source', str(args.source), '--app-id', app_id]
        before = time.perf_counter_ns()
        process = subprocess.Popen([*base, '--serve', str(output)], env=env, stdout=subprocess.DEVNULL)
        try:
            cold.append((await_frame(output, 0) - before) / 1_000_000)
            if not args.cold_only:
                launch = ['bash', str(args.source / 'plugin/launch.sh')]
                client_env = {**env, 'AGENT_SETTINGS_APP_ID': app_id}
                subprocess.run([*launch, '--hide'], env=client_env, check=True)
                before = time.perf_counter_ns()
                subprocess.run(launch, env=client_env, check=True)
                warm.append((await_frame(output, 1) - before) / 1_000_000)
        finally:
            process.terminate()
            process.wait(timeout=5)
print(json.dumps({'samples': args.samples, 'cold_ms': [round(n, 1) for n in cold],
                  'cold_median_ms': round(statistics.median(cold), 1),
                  'reopen_ms': [round(n, 1) for n in warm],
                  'reopen_median_ms': round(statistics.median(warm), 1) if warm else None}, indent=2))
