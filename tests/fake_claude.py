"""Bidirectional Claude protocol fixture; never contacts a model."""
import json
import sys


def send(message):
    print(json.dumps(message), flush=True)


for line in sys.stdin:
    message = json.loads(line)
    if message["type"] == "control_request":
        request = message["request"]
        result = {}
        if request["subtype"] == "initialize":
            result = {"models": [{"value": "opus", "displayName": "Opus",
                                   "supportedEffortLevels": ["low", "high"]}]}
        send({"type": "control_response", "response": {"subtype": "success",
              "request_id": message["request_id"], "response": result}})
        if request["subtype"] == "interrupt":
            send({"type": "control_cancel_request", "request_id": "question"})
            send({"type": "result", "is_error": True, "result": "Interrupted"})
    elif message["type"] == "user":
        send({"type": "system", "subtype": "init", "session_id": message["session_id"]})
        send({"type": "control_request", "request_id": "question", "request": {
            "subtype": "can_use_tool", "tool_name": "AskUserQuestion", "input": {"questions": [
                {"question": "Which color?", "header": "Color", "options": [{"label": "Blue"}, {"label": "Green"}]},
                {"question": "Which extras?", "header": "Extras", "multiSelect": True,
                 "options": [{"label": "One"}, {"label": "Two"}]},
            ]}}})
    elif message["type"] == "control_response":
        response = message["response"]
        send({"type": "stream_event", "event": {"type": "message_start", "message": {"id": "reply"}}})
        send({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Received"}}})
        send({"type": "assistant", "message": {"id": "reply", "content": [{"type": "text", "text": json.dumps(response.get("response", {}))}]}})
        send({"type": "result", "subtype": "success", "is_error": False})
