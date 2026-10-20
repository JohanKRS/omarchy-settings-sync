import json
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from claude_client import ClaudeClient


class ClaudeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.events = queue.Queue()
        self.client = ClaudeClient(self.events.put, command=[sys.executable, str(Path(__file__).with_name("fake_claude.py"))],
                                   workspace=self.temp.name, log=Path(self.temp.name) / "log")
        self.client.start()

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def until(self, method):
        while True:
            value = self.events.get(timeout=3)
            if value.get("method") == method:
                return value

    def ask(self):
        session = self.client.start_thread()["thread"]["id"]
        self.client.turn(session, "protocol fixture")
        return self.until("item/tool/requestUserInput")

    def test_models_structured_answers_and_streaming(self):
        self.assertEqual(self.client.models()[0]["model"], "opus")
        question = self.ask()
        self.assertTrue(question["params"]["questions"][1]["multiSelect"])
        self.client.respond(question["id"], {"answers": {"0": {"answers": ["Blue"]}, "1": {"answers": ["One", "Two"]}}})
        self.assertEqual(self.until("item/agentMessage/delta")["params"]["delta"], "Received")
        result = json.loads(self.until("item/completed")["params"]["item"]["text"])
        self.assertEqual(result["behavior"], "allow")
        self.assertEqual(result["updatedInput"]["answers"], {"Which color?": "Blue", "Which extras?": "One, Two"})
        self.assertEqual(self.until("turn/completed")["params"]["turn"]["status"], "completed")

    def test_decline_does_not_authorize_the_tool(self):
        question = self.ask()
        self.client.respond(question["id"], {"answers": {}})
        result = json.loads(self.until("item/completed")["params"]["item"]["text"])
        self.assertEqual(result["behavior"], "deny")

    def test_tool_approval_preserves_the_requested_input(self):
        request = {"command": "printf test", "description": "Protocol fixture"}
        self.client.handle_request({"request_id": "tool", "request": {
            "subtype": "can_use_tool", "tool_name": "Bash", "input": request}})
        approval = self.until("item/commandExecution/requestApproval")
        self.assertEqual(approval["params"]["availableDecisions"], ["accept", "decline"])
        self.client.respond("tool", {"decision": "accept"})
        result = json.loads(self.until("item/completed")["params"]["item"]["text"])
        self.assertEqual(result, {"behavior": "allow", "updatedInput": request})

    def test_interrupt_cancels_question_and_finishes_turn(self):
        self.ask()
        self.client.request("turn/interrupt", {})
        self.assertEqual(self.until("question/cancelled")["params"]["id"], "question")
        self.assertEqual(self.until("turn/completed")["params"]["turn"]["status"], "interrupted")
        self.assertFalse(self.client.requests)

    def test_stale_interrupt_cannot_stop_a_successor_turn(self):
        self.ask()
        with patch.object(self.client, 'send') as send:
            self.assertEqual(self.client.request('turn/interrupt', {'turnId': 'old-turn'}), {})
            send.assert_not_called()
        self.assertFalse(self.client.interrupted)

    def test_startup_preserves_profile_and_binds_resume_as_a_value(self):
        client = ClaudeClient(lambda _: None, model="custom", effort="high", session_id="--not-a-flag")
        self.assertIn("--resume=--not-a-flag", client.command)
        self.assertIn("user,project,local", client.command)
        self.assertIn("stdio", client.command)
        self.assertNotIn("--dangerously-skip-permissions", client.command)
        self.assertNotIn("--strict-mcp-config", client.command)

    def test_permission_modes_reach_new_and_resumed_sessions(self):
        for mode in ('auto', 'default', 'acceptEdits', 'plan'):
            for session_id in (None, 'existing-session'):
                with self.subTest(mode=mode, session_id=session_id):
                    client = ClaudeClient(lambda _: None, permission_mode=mode, session_id=session_id)
                    index = client.command.index('--permission-mode')
                    self.assertEqual(client.command[index + 1], mode)
                    self.assertEqual(client.permission_mode, mode)
                    self.assertIn('stdio', client.command)
                    self.assertNotIn('--dangerously-skip-permissions', client.command)

    def test_invalid_permission_modes_do_not_start_a_process(self):
        with patch('claude_client.subprocess.Popen') as process:
            for mode in ('unknown', 'bypassPermissions', None):
                with self.assertRaises(ValueError):
                    ClaudeClient(lambda _: None, permission_mode=mode)
            process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
