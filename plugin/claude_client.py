"""Claude Code's bidirectional stream protocol, adapted to the panel events."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import uuid
from attachments import claude_content

from catalog import normalize_claude_models
from core import CodexClient, RpcError, paths

PERMISSION_MODES = ('auto', 'default', 'acceptEdits', 'plan')


class ClaudeClient(CodexClient):
    def __init__(self, event, *, executable="claude", model="", effort="", session_id=None,
                 permission_mode="auto", command=None, workspace=None, log=None):
        if permission_mode not in PERMISSION_MODES:
            raise ValueError('Unsupported Claude permission mode: ' + str(permission_mode))
        self.session_id = session_id or str(uuid.uuid4())
        self.model, self.effort = model, effort
        self.permission_mode = permission_mode
        args = [executable, "--print", "--input-format", "stream-json",
                "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                "--permission-prompt-tool", "stdio", "--permission-mode", permission_mode,
                "--setting-sources", "user,project,local",
                ("--resume=" if session_id else "--session-id=") + self.session_id]
        if model:
            args.append("--model=" + model)
        if effort:
            args.append("--effort=" + effort)
        super().__init__(event, command=command or args, workspace=workspace,
                         log=log or paths()["state"] / "claude.log")
        self.requests = {}
        self.catalog = []
        self.turn_id = None
        self.message_id = None
        self.interrupted = False
        self.had_text = False

    def start(self):
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        Path(self.log).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.stderr_file = os.fdopen(os.open(self.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a")
        self.process = subprocess.Popen(
            self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr_file,
            text=True, bufsize=1, cwd=self.workspace, start_new_session=True,
            env={key: value for key, value in os.environ.items() if key != "CLAUDECODE"},
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        result = self.request("initialize", {"hooks": None}, timeout=45)
        self.catalog = normalize_claude_models(result.get("models", []))

    def request(self, method, params=None, timeout=45):
        if method == "turn/interrupt":
            if not self.turn_id or (params and params.get('turnId') and params['turnId'] != self.turn_id):
                return {}  # The completed turn must not interrupt its successor.
            method, params = "interrupt", {}
            self.interrupted = True
        with self.lock:
            self.counter += 1
            identifier = "panel-" + str(self.counter)
            waiting = queue.Queue(maxsize=1)
            self.pending[identifier] = waiting
        try:
            self.send({"type": "control_request", "request_id": identifier,
                       "request": {"subtype": method, **(params or {})}})
            result = waiting.get(timeout=timeout)
        except queue.Empty as error:
            raise RpcError("Claude Code did not respond to " + method) from error
        finally:
            with self.lock:
                self.pending.pop(identifier, None)
        if result.get("subtype") == "error":
            raise RpcError(result.get("error", "Claude Code disconnected"))
        return result.get("response", {})

    def models(self):
        return self.catalog

    def start_thread(self, model=None, mode="auto", thread_id=None):
        return {"thread": {"id": self.session_id}}

    def set_thread_name(self, thread_id, name):
        if thread_id != self.session_id:
            raise RpcError('Cannot rename a different Claude session')
        return self.request('rename_session', {'title': name, 'source': 'host'}, timeout=5)

    def turn(self, thread_id, text, model=None, effort=None, *, images=()):
        content = claude_content(text, images)
        self.turn_id = str(uuid.uuid4())
        self.interrupted = self.had_text = False
        self.emit("turn/started", {"turn": {"id": self.turn_id}})
        self.send({"type": "user", "session_id": self.session_id,
                   "message": {"role": "user", "content": content}, "parent_tool_use_id": None})
        return {"turn": {"id": self.turn_id}}

    def emit(self, method, params):
        self.event({"method": method, "params": params})

    def respond(self, identifier, result=None, error=None):
        request = self.requests.pop(identifier, None)
        if request is None:
            return  # The CLI already canceled this question.
        result = result or {}
        if error:
            response = {"subtype": "error", "request_id": identifier,
                        "error": str(error.get("message", error))}
        else:
            data = {"behavior": "deny", "message": "The user declined this request."}
            if request.get("tool_name") == "AskUserQuestion" and result.get("answers"):
                original = request.get("input", {})
                answers = {q["question"]: ", ".join(result["answers"].get(str(i), {}).get("answers", []))
                           for i, q in enumerate(original.get("questions", []))}
                data = {"behavior": "allow", "updatedInput": {**original, "answers": answers}}
            elif result.get("decision") == "accept":
                data = {"behavior": "allow", "updatedInput": request.get("input", {})}
            response = {"subtype": "success", "request_id": identifier, "response": data}
        self.send({"type": "control_response", "response": response})

    def handle_request(self, message):
        identifier, request = message["request_id"], message.get("request", {})
        self.requests[identifier] = request
        if request.get("subtype") != "can_use_tool":
            self.respond(identifier, error={"message": "Unsupported control request: " + str(request.get("subtype"))})
            self.emit("error", {"message": "Claude requested an unsupported interaction. Continue in the terminal."})
            return
        tool, data = request.get("tool_name", ""), request.get("input", {})
        if tool == "AskUserQuestion":
            method = "item/tool/requestUserInput"
            params = {"questions": [{**q, "id": str(i)} for i, q in enumerate(data.get("questions", []))]}
        else:
            method = "item/commandExecution/requestApproval"
            params = {"reason": request.get("description") or request.get("decision_reason") or tool,
                      "command": json.dumps(data, ensure_ascii=False, indent=2),
                      "availableDecisions": ["accept", "decline"]}
        self.event({"id": identifier, "method": method, "params": params})

    def handle_message(self, message):
        kind = message.get("type")
        if kind == "control_response":
            response = message.get("response", {})
            with self.lock:
                waiting = self.pending.get(response.get("request_id"))
            if waiting and waiting.empty():
                waiting.put(response)
        elif kind == "control_request":
            self.handle_request(message)
        elif kind == "control_cancel_request":
            self.requests.pop(message.get("request_id"), None)
            self.emit("question/cancelled", {"id": message.get("request_id")})
        elif kind == "system" and message.get("subtype") == "init":
            self.session_id = message.get("session_id", self.session_id)
            self.emit("session/started", {"id": self.session_id})
        elif kind == "stream_event":
            event = message.get("event", {})
            if event.get("type") == "message_start":
                self.message_id = event.get("message", {}).get("id") or str(uuid.uuid4())
            delta = event.get("delta", {})
            if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                self.had_text = True
                self.emit("item/agentMessage/delta", {"itemId": self.message_id, "delta": delta.get("text", "")})
        elif kind == "assistant":
            body = message.get("message", {})
            identifier = body.get("id") or self.message_id or str(uuid.uuid4())
            text = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text")
            if text:
                self.had_text = True
                self.emit("item/completed", {"item": {"id": identifier, "type": "agentMessage", "text": text}})
            for block in body.get("content", []):
                if block.get("type") == "tool_use":
                    self.emit("item/started", {"item": {"id": block.get("id"), "type": "mcpToolCall", "tool": block.get("name", "")}})
        elif kind == "result":
            if not self.turn_id:
                return
            if not self.had_text and message.get("result") and not message.get("is_error"):
                self.emit("item/completed", {"item": {"id": str(uuid.uuid4()), "type": "agentMessage", "text": message["result"]}})
            turn = {"id": self.turn_id, "status": "interrupted" if self.interrupted else "completed"}
            if message.get("is_error") and not self.interrupted:
                turn["error"] = {"message": "\n".join(message.get("errors", [])) or message.get("result") or message.get("subtype", "Claude Code error")}
            self.requests.clear()
            self.turn_id = None
            self.emit("turn/completed", {"turn": turn})
        elif kind == "error":
            self.emit("error", {"message": message.get("error", "Claude Code error")})

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    self.handle_message(json.loads(line))
                except ValueError:
                    continue
        finally:
            with self.lock:
                for waiting in self.pending.values():
                    if waiting.empty():
                        waiting.put({"subtype": "error", "error": "Claude Code disconnected"})
            if not self.closed:
                self.emit("client/disconnected", {})
