import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from core import AGENTS, CodexClient, RpcError, external_command, make_prompt, permission_options, private_write, repository_url
from i18n import language
from context import snapshot, repository_state, begin_task, finish_task


class ConfigurationTest(unittest.TestCase):
    def test_urls_and_no_embedded_credentials_or_commands(self):
        self.assertEqual(repository_url("team/dotfiles"), "https://github.com/team/dotfiles")
        self.assertEqual(repository_url("git@example.com:team/dotfiles.git"), "git@example.com:team/dotfiles.git")
        for value in ["--upload-pack=x", "ext::sh code", "https://token@github.com/a/b",
                      "https://github.com/a/../b", "git@host:../repo", "git@host:repo",
                      "https://github.com/a/b?token=secret", "a/b\n--upload-pack=x"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                repository_url(value)

    def test_sync_prompt_is_independent_and_local_only_is_explicit(self):
        prompt = make_prompt("Sync", repository="sample/dotfiles", sync=True, publish=False)
        self.assertIn("https://github.com/sample/dotfiles", prompt)
        self.assertIn("DESLIGADO", prompt)
        self.assertIn("HEAD", prompt)
        self.assertIn("last-sync.json", prompt)
        self.assertNotIn("JohanKRS", prompt)
        create = make_prompt("", repository="sample/new", create=True)
        self.assertIn("PRIVADO", create)

    def test_all_adapters_keep_prompt_as_one_literal_argument(self):
        prompt = "Text 'quoted' $(touch /tmp/should-not-exist)\nSecond line"
        for agent in AGENTS:
            with self.subTest(agent=agent):
                cmd = external_command(agent, prompt)
                self.assertIn(prompt if agent != "hermes" else "--query=" + prompt, cmd)
                self.assertFalse(any(x in cmd for x in ("--yolo", "--dangerously-skip-permissions", "--allow-all")))
        cmd = external_command("claude", prompt, "opus", "high")
        self.assertEqual(cmd[cmd.index("--model") + 1], "opus")
        self.assertEqual(cmd[cmd.index("--effort") + 1], "high")
        with self.assertRaises(ValueError):
            external_command("unknown", prompt)

    def test_private_state_and_read_only_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "state" / "settings.json"
            private_write(target, {"repository": "one/two"})
            private_write(target, {"repository": "three/four"})
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(target.read_text())["repository"], "three/four")
        self.assertEqual(permission_options("read")["approvalPolicy"], "never")
        self.assertEqual(permission_options("ask")["approvalsReviewer"], "user")
        self.assertEqual(permission_options("auto")["approvalsReviewer"], "auto_review")

    def test_app_locale_and_english_fallback(self):
        for env, expected in [
            ({"LANG": "en_US.UTF-8"}, "en"),
            ({"LANG": "pt_BR.UTF-8"}, "pt"),
            ({"LANG": "es_ES.UTF-8"}, "es"),
            ({"LANG": "pt_BR", "LC_ALL": "C.UTF-8"}, "en"),
            ({"LANGUAGE": "es:en", "LANG": "en_US"}, "es"),
            ({"LANG": "ja_JP"}, "en"),
        ]:
            self.assertEqual(language(env), expected)


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.events = queue.Queue()
        self.client = CodexClient(
            self.events.put, command=[sys.executable, str(Path(__file__).with_name("fake_server.py"))],
            workspace=self.temp.name, log=Path(self.temp.name) / "log",
        )
        self.client.start()

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_models_resume_controls_and_approval_roundtrip(self):
        self.assertEqual([m["model"] for m in self.client.models()], ["first", "second"])
        start = self.client.start_thread("selected-model", "ask", "previous-thread")
        self.assertEqual(start["thread"]["id"], "previous-thread")
        self.assertEqual(start["received"]["approvalPolicy"], "on-request")
        self.assertEqual(start["received"]["model"], "selected-model")
        turn = self.client.turn("previous-thread", "literal prompt", "selected-model", "high")
        self.assertEqual(turn["received"]["effort"], "high")
        self.assertEqual(turn["received"]["input"][0]["text"], "literal prompt")
        self.assertEqual(self.events.get(timeout=3)["method"], "item/agentMessage/delta")
        approval = self.events.get(timeout=3)
        self.client.respond(approval["id"], {"decision": "decline"})
        completed = self.events.get(timeout=3)
        self.assertEqual(completed["params"]["approval"], {"decision": "decline"})

    def test_errors_and_disconnect_release_pending_request(self):
        with self.assertRaisesRegex(RpcError, "expected error"):
            self.client.request("test/error", {})
        with self.assertRaises(RpcError):
            self.client.request("test/disconnect", {}, timeout=3)


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.locations = {"state": Path(self.temp.name) / "state",
                          "workspace": Path(self.temp.name) / "workspace"}
        self.repo = "https://github.com/example/dotfiles"
        self.record_path = repository_state(self.locations, self.repo) / "last-sync.json"
        self.record = {"repository": self.repo, "branch": "main", "sha": "a" * 40,
                       "status": "complete", "pending": [], "date": "2026-01-01"}

    def tearDown(self):
        self.temp.cleanup()

    def test_first_use_does_not_assume_new_machine_or_empty_repository(self):
        state = snapshot(self.locations, self.repo, "main")
        self.assertEqual(state["scenario"], "first_plugin_use_existing_system")
        self.assertEqual(state["remote_state"], "unknown_until_checked")
        self.assertIsNone(state["last_applied_sha"])

    def test_complete_sync_uses_short_remote_only_prompt(self):
        private_write(self.record_path, self.record)
        prompt = make_prompt("Sync", repository=self.repo, branch="main", sync=True, locations=self.locations)
        self.assertIn("VERIFICAÇÃO RÁPIDA", prompt)
        self.assertIn("No changes.", prompt)
        self.assertIn("Não examine arquivos locais", prompt)
        self.assertIn("a" * 40, prompt)
        self.assertNotIn("## Preparação", prompt)

    def test_partial_sync_cannot_claim_no_changes(self):
        private_write(self.record_path, dict(self.record, status="partial", pending=["keyboard"]))
        state = snapshot(self.locations, self.repo, "main", operation="sync")
        self.assertEqual(state["scenario"], "resume_and_verify")
        self.assertIsNone(state["last_applied_sha"])
        prompt = make_prompt("Sync", repository=self.repo, branch="main", sync=True, locations=self.locations)
        self.assertNotIn("SINCRONIZAR — VERIFICAÇÃO RÁPIDA", prompt)

    def test_records_are_bound_to_repository_and_branch(self):
        private_write(self.record_path, self.record)
        state = snapshot(self.locations, self.repo, "other", operation="sync")
        self.assertIsNone(state["last_applied_sha"])
        state = snapshot(self.locations, "https://github.com/other/dotfiles", "main", operation="sync")
        self.assertIsNone(state["last_applied_sha"])
        ssh = repository_state(self.locations, "git@github.com:example/dotfiles.git")
        self.assertEqual(ssh, self.record_path.parent)

    def test_history_is_not_proof_of_success_and_retry_keeps_context(self):
        task = begin_task(self.locations, self.repo, "main", "sync", "claude", private_write)
        state = snapshot(self.locations, self.repo, "main", operation="sync")
        self.assertEqual(state["scenario"], "resume_and_verify")
        finish_task(task, "response_completed", private_write)
        state = snapshot(self.locations, self.repo, "main", operation="sync")
        self.assertEqual(state["previous_tasks"], 1)
        self.assertIsNone(state["last_applied_sha"])


if __name__ == "__main__":
    unittest.main()
