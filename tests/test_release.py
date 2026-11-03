import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
from features import load_catalog
from release import Package, agent_request, members, review, save_snapshot

CATALOG = '''
[[feature]]
id = "idle"
title = "Idle timers"
app = "shell"
[[feature.part]]
kind = "json"
dest = "~/.config/omarchy/shell.json"
values = { "idle.screensaver" = 300, "idle.lock" = 600 }

[[feature]]
id = "lock-shortcut"
title = "Super+L locks"
areas = ["hyprland"]
[[feature.part]]
kind = "block"
dest = "~/.config/hypr/bindings.lua"
text = "bind('SUPER', 'L', lock)"

[[feature]]
id = "terminal-font"
title = "Terminal font"
app = "alacritty"
[[feature.part]]
kind = "line"
dest = "~/.config/alacritty/alacritty.toml"
text = "size = 12"

[[program]]
package = "libreoffice-fresh"
action = "remove"
'''


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.home, self.repo = root / 'home', root / 'repo'
        self.old, self.new = root / 'old', root / 'new'
        self.repo.mkdir()
        (self.repo / 'features.toml').write_text(CATALOG)
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CONFIG_HOME': ''})
        self.env.start()
        for base, idle, bindings, packages in (
                (self.old, {'screensaver': 150, 'lock': 300}, "bind('SUPER', 'Q', close)\n", 'libreoffice-fresh\nnautilus\n'),
                (self.new, {'screensaver': 300, 'lock': 900}, "bind('SUPER', 'Q', close)\nbind('SUPER', 'L', layout)\n", 'nautilus\n')):
            (base / 'config/omarchy').mkdir(parents=True)
            (base / 'config/omarchy/shell.json').write_text(json.dumps({'idle': idle}))
            (base / 'default/hypr').mkdir(parents=True)
            (base / 'default/hypr/bindings.lua').write_text(bindings)
            (base / 'install').mkdir()
            (base / 'install/omarchy-base.packages').write_text(packages)
        (self.new / 'config/alacritty').mkdir(parents=True)
        (self.new / 'config/alacritty/alacritty.toml').write_text('size = 11\n')
        (self.old / 'config/alacritty').mkdir(parents=True)
        (self.old / 'config/alacritty/alacritty.toml').write_text('size = 11\n')
        self.features, errors = load_catalog(self.repo)
        self.assertEqual(errors, [])
        self.by_id = {f.id: f for f in self.features}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_members_follow_destinations_areas_and_packages(self):
        self.assertEqual(members(self.by_id['idle'], self.home), ['config/omarchy/shell.json'])
        self.assertEqual(members(self.by_id['lock-shortcut'], self.home),
                         ['config/hypr/bindings.lua', 'default/hypr/bindings.lua', 'default/hypr/bindings/'])
        self.assertEqual(members(self.by_id['program-libreoffice-fresh'], self.home), ['install/omarchy-base.packages'])

    def test_review_classifies_what_the_update_changed(self):
        previous = Package('4.0.6-1', cache=self.temp.name, snapshot=self.old)
        self.assertTrue(previous.available)
        impacts = review(self.features, previous, home=self.home, omarchy=self.new)
        self.assertEqual(set(impacts), {'idle', 'lock-shortcut', 'program-libreoffice-fresh'})
        idle = impacts['idle']
        self.assertEqual(idle['kind'], 'default-changed')
        kinds = {k['key']: k['kind'] for k in idle['keys']}
        self.assertEqual(kinds, {'idle.screensaver': 'redundant', 'idle.lock': 'default-changed'})
        self.assertIn("bind('SUPER', 'L', layout)", impacts['lock-shortcut']['diff'])
        self.assertEqual(impacts['lock-shortcut']['kind'], 'changed')
        self.assertIn('-libreoffice-fresh', impacts['program-libreoffice-fresh']['diff'])
        broken = review(self.features, previous, home=self.home, omarchy=self.new, config_errors='bindings.lua:2 bad')
        self.assertEqual(broken['lock-shortcut']['kind'], 'broken')
        text = agent_request(self.by_id['idle'], idle, '4.0.6-1', '4.1.0-1')
        self.assertIn('AJUSTAR APÓS ATUALIZAÇÃO DO OMARCHY', text)
        self.assertIn('idle.lock', text)

    def test_snapshot_keeps_only_relevant_defaults(self):
        target = Path(self.temp.name) / 'snapshot'
        save_snapshot(self.features, target, home=self.home, omarchy=self.new)
        saved = sorted(str(p.relative_to(target)) for p in target.rglob('*') if p.is_file())
        self.assertEqual(saved, ['config/alacritty/alacritty.toml', 'config/omarchy/shell.json',
                                 'default/hypr/bindings.lua', 'install/omarchy-base.packages'])
        self.assertEqual(review(self.features, Package('x', cache=self.temp.name, snapshot=target),
                                home=self.home, omarchy=self.new), {})

    def test_missing_previous_version_is_reported_as_unavailable(self):
        self.assertFalse(Package('9.9.9', cache=self.temp.name).available)


if __name__ == '__main__':
    unittest.main()
