import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from catalog import agent_executable, discover_models, normalize_claude_models, parse_opencode_models


class CatalogTest(unittest.TestCase):
    def test_claude_metadata_preserves_per_model_capabilities(self):
        rows = normalize_claude_models([
            {"value": "default", "displayName": "Default", "supportedEffortLevels": ["low", "high"]},
            {"value": "opus", "displayName": "Opus", "supportedEffortLevels": ["low", "high", "max"]},
            {"value": "haiku-older", "displayName": "Older Haiku"},
        ])
        self.assertEqual(rows[0]["model"], "")
        self.assertEqual(rows[1]["supportedReasoningEfforts"][-1], {"reasoningEffort": "max"})
        self.assertEqual(rows[2]["supportedReasoningEfforts"], [])

    def test_discovery_never_sends_a_prompt_and_is_bounded(self):
        response = {"response": {"request_id": "models", "subtype": "success", "response": {
            "models": [{"value": "opus", "displayName": "Opus"}]}}}
        with patch("catalog.subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")) as run:
            self.assertEqual(discover_models("claude", "/bin/claude")[0]["model"], "opus")
            args, kwargs = run.call_args
            self.assertEqual(json.loads(kwargs["input"])["type"], "control_request")
            self.assertIn("--strict-mcp-config", args[0])
            self.assertIn('{"disableAllHooks":true}', args[0])
            self.assertEqual(kwargs["timeout"], 20)
        with patch("catalog.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 20)):
            with self.assertRaises(subprocess.TimeoutExpired):
                discover_models("claude", "/bin/claude")

    def test_install_launchers_are_not_treated_as_installed_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory) / "opencode"
            launcher.write_text('#!/bin/bash\nmise use -g --quiet "opencode"\nexec mise x "opencode" -- opencode "$@"\n')
            with patch("catalog.shutil.which", return_value=str(launcher)), patch(
                "catalog.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "not installed")
            ) as run:
                self.assertIsNone(agent_executable("opencode"))
                self.assertEqual(run.call_args.args[0], ["mise", "which", "opencode"])

    def test_opencode_variants_are_model_specific(self):
        output = 'provider/first\n' + json.dumps({"variants": {"low": {}, "high": {}, "hidden": {"disabled": True}}}, indent=2)
        output += '\nprovider/second\n{}\n'
        rows = parse_opencode_models(output)
        self.assertEqual([x["model"] for x in rows], ["provider/first", "provider/second"])
        self.assertEqual(rows[0]["supportedReasoningEfforts"], [{"reasoningEffort": "low"}, {"reasoningEffort": "high"}])
        self.assertEqual(rows[1]["supportedReasoningEfforts"], [])

    def test_cursor_list_ignores_headings_and_does_not_invent_efforts(self):
        output = 'Available models\n\x1b[32mexample-fast - Example Fast\x1b[0m\nexample-long - Example Long\n'
        with patch("catalog.subprocess.run", return_value=subprocess.CompletedProcess([], 0, output, "")):
            rows = discover_models("cursor-agent", "/bin/cursor-agent")
        self.assertEqual([m["model"] for m in rows], ["example-fast", "example-long"])
        self.assertTrue(all(not m["supportedReasoningEfforts"] for m in rows))


if __name__ == "__main__":
    unittest.main()
