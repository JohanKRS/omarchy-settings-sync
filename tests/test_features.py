import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
from applier import Applier, Ledger, delegation, status
from features import (Probe, desired, expand, install_id, list_machines, load_catalog, load_machine,
                      machine_path, machine_text, ordered, part_enabled, remove_machine, rename_machine)

CATALOG = '''
version = 1

[[feature]]
id = "lock-shortcut"
title = "Super+L locks the screen"
group = "desktop"
areas = ["hyprland"]

[[feature.part]]
kind = "block"
dest = "~/.config/hypr/bindings.lua"
source = "desktop/lock.lua"

[[feature]]
id = "idle"
title = "Screensaver after 5 minutes"
group = "desktop"
default = "ask"

[[feature.part]]
kind = "json"
dest = "~/.config/omarchy/shell.json"
values = { "idle.screensaver" = 300, "idle.lock" = 600 }

[[feature]]
id = "popups"
title = "Floating popups"
requires = ["lock-shortcut"]
when = ["command:sh"]

[[feature.part]]
kind = "file"
source = "desktop/popups.lua"
dest = "~/.config/hypr/settings-sync/popups.lua"

[[feature.part]]
kind = "line"
dest = "~/.config/hypr/hyprland.lua"
text = 'require("hypr.settings-sync.popups")'

[[feature.part]]
kind = "agent"
id = "profile"
optional = true
title = "Firefox profile module"
instructions = "apps/firefox/README.md"

[[feature]]
id = "pdf"
title = "Papers opens PDFs"
group = "apps"
when = ["!command:definitely-not-installed-command"]

[[feature.part]]
kind = "mime"
types = { "application/pdf" = "org.gnome.Papers.desktop" }

[[feature.part]]
kind = "ini"
dest = "~/.config/gtk-3.0/settings.ini"
section = "Settings"
values = { gtk-print-backends = "cups,file" }

[[feature.part]]
kind = "ini"
format = "toml"
dest = "~/.config/voxtype/config.toml"
section = "osd"
values = { frame = "minimal", visible = true }

[[feature]]
id = "no-sleep"
title = "Never suspend"
group = "system"

[[feature.part]]
kind = "system-file"
source = "system/sleep.conf"
dest = "/etc/systemd/sleep.conf.d/90-no-sleep.conf"

[[feature.part]]
kind = "package"
remove = ["libreoffice-fresh"]
'''


class Runner:
    """A fake subprocess.run for systemctl, pacman, pkexec and hyprctl."""
    def __init__(self):
        self.calls = []
        self.packages = {'libreoffice-fresh'}
        self.deny = False

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        out, code = '', 0
        if args[:2] == ['pacman', '-Q']:
            code = 0 if args[2] in self.packages else 1
        elif args[0] == 'pkexec':
            if self.deny:
                code = 126
            else:
                lines = Path(args[2]).read_text().splitlines()
                steps = [line for line in lines if line.startswith('step ')]
                out = '\n'.join(f'settings-sync-ok {line.split()[1]}' for line in steps)
        return subprocess.CompletedProcess(args, code, out, '')


class FeatureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.home, self.repo, self.state = root / 'home', root / 'repo', root / 'state'
        (self.repo / 'desktop').mkdir(parents=True)
        (self.repo / 'system').mkdir()
        (self.repo / 'apps/firefox').mkdir(parents=True)
        (self.repo / 'desktop/lock.lua').write_text('bind("SUPER", "L", lock)\n')
        (self.repo / 'desktop/popups.lua').write_text('-- popups\n')
        (self.repo / 'system/sleep.conf').write_text('[Sleep]\nAllowSuspend=no\n')
        (self.repo / 'apps/firefox/README.md').write_text('Install the module.\n')
        (self.repo / 'features.toml').write_text(CATALOG)
        self.omarchy = root / 'omarchy'
        (self.omarchy / 'config/omarchy').mkdir(parents=True)
        (self.omarchy / 'config/omarchy/shell.json').write_text(json.dumps({'idle': {'screensaver': 150, 'lock': 300}}))
        (self.omarchy / 'install').mkdir()
        (self.omarchy / 'install/omarchy-base.packages').write_text('# base\nlibreoffice-fresh\n')
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CONFIG_HOME': '', 'XDG_DATA_HOME': ''})
        self.env.start()
        self.run = Runner()
        self.ledger = Ledger(self.state / 'applied.json')
        self.applier = Applier(self.repo, self.ledger, self.state / 'backups', run=self.run,
                               home=self.home, omarchy=self.omarchy, root=root / 'root')
        self.features, self.errors = load_catalog(self.repo)
        self.by_id = {feature.id: feature for feature in self.features}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def config(self, relative):
        return self.home / '.config' / relative

    def test_catalog_parses_kinds_conditions_and_dependencies(self):
        self.assertEqual(self.errors, [])
        self.assertEqual([f.id for f in self.features], ['lock-shortcut', 'idle', 'popups', 'pdf', 'no-sleep'])
        self.assertEqual([f.id for f in ordered(self.features, ['popups'])], ['lock-shortcut', 'popups'])
        self.assertTrue(self.by_id['popups'].needs_agent)
        self.assertTrue(self.by_id['no-sleep'].needs_admin)
        probe = Probe(run=self.run)
        self.assertIsNone(probe.applicable(self.by_id['pdf']))
        self.assertIsNone(probe.applicable(self.by_id['popups']))
        self.assertEqual(expand('${XDG_CONFIG_HOME:-$HOME/.config}/a'), self.home / '.config/a')

    def test_catalog_rejects_unsafe_or_incomplete_parts(self):
        bad = [
            ('file', 'source = "../outside"\ndest = "~/.x"'),
            ('file', 'source = "desktop/lock.lua"\ndest = "/etc/passwd"'),
            ('system-file', 'source = "desktop/lock.lua"\ndest = "/usr/share/omarchy/config/x"'),
            ('package', 'install = ["bad name; rm"]'),
            ('agent', 'title = "x"'),
            ('script', 'run = "rm -rf ~"'),
        ]
        for kind, body in bad:
            with self.subTest(kind=kind, body=body):
                (self.repo / 'features.toml').write_text(
                    f'[[feature]]\nid = "x"\ntitle = "X"\n[[feature.part]]\nkind = "{kind}"\n{body}\n')
                features, errors = load_catalog(self.repo)
                self.assertEqual(features, [])
                self.assertTrue(errors)

    def test_machine_choices_round_trip_and_defaults(self):
        record = {'features': {'idle': 'on', 'pdf': 'off'}, 'off': {'pdf': 'keep'}, 'parts': {'popups.profile': 'off'}}
        machine_path(self.repo, 'desk').parent.mkdir()
        machine_path(self.repo, 'desk').write_text(machine_text('desk', record, hostname='desk', omarchy='4.0.6-1'))
        loaded = load_machine(self.repo, 'desk')
        self.assertEqual(loaded, record)
        self.assertEqual(desired(self.by_id['idle'], loaded), 'on')
        self.assertEqual(desired(self.by_id['idle'], {}), 'new')
        self.assertEqual(desired(self.by_id['lock-shortcut'], {}), 'on')
        profile = self.by_id['popups'].parts[2]
        self.assertFalse(part_enabled(self.by_id['popups'], profile, loaded))

    def test_machines_can_be_listed_renamed_and_removed(self):
        (self.repo / 'machines').mkdir()
        record = {'features': {'idle': 'on', 'pdf': 'off'}, 'off': {}, 'parts': {}}
        machine_path(self.repo, 'omarchy').write_text(
            machine_text('omarchy', record, hostname='omarchy', omarchy='4.0.6-1', install='abc'))
        machine_path(self.repo, 'laptop').write_text(machine_text('laptop', {}, hostname='laptop'))
        machines = list_machines(self.repo)
        self.assertEqual([m['name'] for m in machines], ['laptop', 'omarchy'])
        self.assertEqual((machines[1]['on'], machines[1]['off'], machines[1]['install']), (1, 1, 'abc'))
        paths = rename_machine(self.repo, 'omarchy', 'desktop')
        self.assertEqual([p.name for p in paths], ['omarchy.toml', 'desktop.toml'])
        self.assertEqual(load_machine(self.repo, 'desktop'), record)
        self.assertIn('install = "abc"', machine_path(self.repo, 'desktop').read_text())
        with self.assertRaises(ValueError):
            rename_machine(self.repo, 'desktop', 'laptop')
        with self.assertRaises(ValueError):
            rename_machine(self.repo, 'desktop', 'Bad Name')
        remove_machine(self.repo, 'laptop')
        self.assertEqual([m['name'] for m in list_machines(self.repo)], ['desktop'])
        machine_id = self.repo / 'machine-id'
        machine_id.write_text('0123456789abcdef\n')
        self.assertEqual(len(install_id(machine_id)), 16)
        self.assertNotIn('0123456789abcdef', install_id(machine_id))
        self.assertEqual(install_id(self.repo / 'missing'), '')

    def test_block_line_and_file_apply_idempotently_and_revert_exactly(self):
        bindings = self.config('hypr/bindings.lua')
        bindings.parent.mkdir(parents=True)
        bindings.write_text('-- Omarchy defaults\nbind("SUPER", "Q", close)\n')
        for _ in range(2):
            outcomes = [self.applier.enable(self.by_id['lock-shortcut'], {})]
            self.applier.finish(outcomes)
        text = bindings.read_text()
        self.assertEqual(text.count('settings-sync lock-shortcut/1'), 2)
        self.assertEqual(text.count('bind("SUPER", "L", lock)'), 1)
        self.assertEqual(self.applier.inspect(self.by_id['lock-shortcut']), {'block:~/.config/hypr/bindings.lua': 'applied'})
        self.assertIn(['hyprctl', 'reload'], self.run.calls)
        self.applier.finish([self.applier.disable(self.by_id['lock-shortcut'])])
        self.assertEqual(bindings.read_text(), '-- Omarchy defaults\nbind("SUPER", "Q", close)\n')
        self.assertFalse(self.ledger.applied('lock-shortcut'))

    def test_existing_unmarked_block_is_adopted_not_duplicated(self):
        bindings = self.config('hypr/bindings.lua')
        bindings.parent.mkdir(parents=True)
        bindings.write_text('x\nbind("SUPER", "L", lock)\ny\n')
        self.applier.finish([self.applier.enable(self.by_id['lock-shortcut'], {})])
        text = bindings.read_text()
        self.assertEqual(text.count('bind("SUPER", "L", lock)'), 1)
        self.assertTrue(text.startswith('x\n-- >>> settings-sync'))
        self.assertTrue(text.endswith('y\n'))

    def test_local_edits_are_conflicts_for_the_agent(self):
        bindings = self.config('hypr/bindings.lua')
        self.applier.finish([self.applier.enable(self.by_id['lock-shortcut'], {})])
        bindings.write_text(bindings.read_text().replace('lock)', 'lock_now)'))
        self.assertEqual(self.applier.inspect(self.by_id['lock-shortcut'])['block:~/.config/hypr/bindings.lua'], 'modified')
        outcome = self.applier.disable(self.by_id['lock-shortcut'])
        self.assertIn('conflict', outcome.delegated[0]['reason'])
        self.assertIn('lock_now', bindings.read_text())
        text = delegation([outcome], self.state / 'agent-results.json', machine='desk')
        self.assertIn('lock-shortcut', text)
        self.assertIn('agent-results.json', text)

    def test_json_keys_return_to_the_omarchy_default(self):
        shell = self.config('omarchy/shell.json')
        shell.parent.mkdir(parents=True)
        shell.write_text(json.dumps({'bar': {'position': 'top'}, 'idle': {'screensaver': 120, 'lock': 240}}, indent=2))
        self.applier.finish([self.applier.enable(self.by_id['idle'], {})])
        self.assertEqual(json.loads(shell.read_text())['idle'], {'screensaver': 300, 'lock': 600})
        self.applier.finish([self.applier.disable(self.by_id['idle'], 'default')])
        data = json.loads(shell.read_text())
        self.assertEqual(data['idle'], {'screensaver': 150, 'lock': 300})
        self.assertEqual(data['bar'], {'position': 'top'})

    def test_json_keys_can_return_to_the_previous_value(self):
        shell = self.config('omarchy/shell.json')
        shell.parent.mkdir(parents=True)
        shell.write_text(json.dumps({'idle': {'screensaver': 120}}))
        self.applier.finish([self.applier.enable(self.by_id['idle'], {})])
        self.applier.finish([self.applier.disable(self.by_id['idle'], 'previous')])
        self.assertEqual(json.loads(shell.read_text())['idle'], {'screensaver': 120})

    def test_ini_toml_and_mime_keys_preserve_other_lines(self):
        gtk = self.config('gtk-3.0/settings.ini')
        gtk.parent.mkdir(parents=True)
        gtk.write_text('[Settings]\ngtk-theme-name=Adwaita\n')
        voxtype = self.config('voxtype/config.toml')
        voxtype.parent.mkdir(parents=True)
        voxtype.write_text('engine = "whisper"\n\n[osd]\nframe = "full"\n\n[audio]\ndevice = "default"\n')
        mime = self.config('mimeapps.list')
        mime.write_text('[Default Applications]\nimage/png=imv.desktop\napplication/pdf=org.gnome.Evince.desktop\n')
        self.applier.finish([self.applier.enable(self.by_id['pdf'], {})])
        self.assertIn('gtk-print-backends=cups,file', gtk.read_text())
        self.assertIn('gtk-theme-name=Adwaita', gtk.read_text())
        self.assertIn('[osd]\nframe = "minimal"\nvisible = true\n', voxtype.read_text())
        self.assertIn('device = "default"', voxtype.read_text())
        self.assertIn('application/pdf=org.gnome.Papers.desktop', mime.read_text())
        self.assertEqual(set(self.applier.inspect(self.by_id['pdf']).values()), {'applied'})
        self.applier.finish([self.applier.disable(self.by_id['pdf'], 'default')])
        self.assertIn('application/pdf=org.gnome.Evince.desktop', mime.read_text())
        self.assertIn('image/png=imv.desktop', mime.read_text())
        self.assertNotIn('gtk-print-backends', gtk.read_text())
        self.assertIn('frame = "full"', voxtype.read_text())
        self.assertNotIn('visible', voxtype.read_text())

    def test_agent_parts_are_delegated_and_recorded_from_the_report(self):
        outcome = self.applier.enable(self.by_id['popups'], {})
        self.applier.finish([outcome])
        self.assertEqual([item['part'].key for item in outcome.delegated], ['profile'])
        self.assertTrue(self.config('hypr/settings-sync/popups.lua').exists())
        self.assertIn('require("hypr.settings-sync.popups")', self.config('hypr/hyprland.lua').read_text())
        results = self.state / 'agent-results.json'
        results.write_text(json.dumps({'features': {'popups': {'profile': {'status': 'applied', 'note': 'ok'}}}}))
        self.assertTrue(self.applier.merge_agent_results(results, self.features))
        self.assertFalse(results.exists())
        self.assertEqual(set(self.applier.inspect(self.by_id['popups']).values()), {'applied'})
        self.assertEqual(status(self.by_id['popups'], 'on', 'default', self.ledger,
                                self.applier.inspect(self.by_id['popups'])), 'applied')
        again = self.applier.enable(self.by_id['popups'], {})
        self.assertEqual(again.delegated, [])
        off = self.applier.disable(self.by_id['popups'])
        self.applier.finish([off])
        self.assertEqual([item['part'].key for item in off.delegated], ['profile'])
        self.assertFalse(self.config('hypr/settings-sync/popups.lua').exists())
        self.assertFalse(self.config('hypr/hyprland.lua').exists())  # Created by the feature, now empty.

    def test_disabled_optional_part_is_skipped(self):
        machine = {'parts': {'popups.profile': 'off'}}
        outcome = self.applier.enable(self.by_id['popups'], machine)
        self.assertEqual(outcome.delegated, [])

    def test_administrator_steps_share_one_prompt_and_revert_to_base_packages(self):
        outcome = self.applier.enable(self.by_id['no-sleep'], {})
        self.applier.finish([outcome])
        prompts = [call for call in self.run.calls if call[0] == 'pkexec']
        self.assertEqual(len(prompts), 1)
        self.assertEqual(outcome.delegated, [])
        self.assertEqual(self.ledger.part('no-sleep', 'package:libreoffice-fresh')['removed'], ['libreoffice-fresh'])
        self.run.packages.discard('libreoffice-fresh')
        self.run.calls.clear()
        self.applier.finish([self.applier.disable(self.by_id['no-sleep'], 'default')])
        script_steps = [call for call in self.run.calls if call[0] == 'pkexec']
        self.assertEqual(len(script_steps), 1)

    def test_cancelled_administrator_prompt_is_reported(self):
        self.run.deny = True
        outcome = self.applier.enable(self.by_id['no-sleep'], {})
        self.applier.finish([outcome])
        self.assertEqual(len(outcome.delegated), 2)
        self.assertEqual(self.ledger.part('no-sleep', 'system-file:/etc/systemd/sleep.conf.d/90-no-sleep.conf')['status'], 'failed')

    def test_status_labels(self):
        feature = self.by_id['idle']
        self.assertEqual(status(feature, 'new', 'default', self.ledger, {}), 'new')
        self.assertEqual(status(feature, 'off', 'default', self.ledger, {}), 'off')
        self.assertEqual(status(feature, 'on', 'default', self.ledger, {'x': 'missing'}), 'pending')
        self.assertEqual(status(feature, 'on', 'default', self.ledger, {'x': 'modified'}), 'modified')
        self.assertEqual(status(feature, 'on', 'default', self.ledger, {}, failing='package:x'), 'unavailable')


if __name__ == '__main__':
    unittest.main()
