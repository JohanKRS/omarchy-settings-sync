"""JSON-RPC peer for integration tests. Never launches an agent."""
import json
import sys


def send(value):
    print(json.dumps(value), flush=True)


for line in sys.stdin:
    request = json.loads(line)
    method, identifier = request.get("method"), request.get("id")
    if identifier == "approval-test" and not method:
        send({"method": "turn/completed", "params": {"turn": {"status": "completed"}, "approval": request.get("result")}})
        continue
    if identifier is None:
        continue
    params = request.get("params", {})
    result = {}
    if method == "model/list":
        cursor = params.get("cursor")
        result = {"data": [{"model": "second" if cursor else "first", "displayName": "Model"}],
                  "nextCursor": None if cursor else "page-2"}
    elif method in ("thread/start", "thread/resume"):
        result = {"thread": {"id": params.get("threadId", "thread-test")}, "received": params}
    elif method == "turn/start":
        result = {"turn": {"id": "turn-test"}, "received": params}
    elif method == "turn/steer":
        if params.get('expectedTurnId') != 'turn-test':
            send({'id': identifier, 'error': {'code': -32602, 'message': 'Turn mismatch'}})
            continue
        result = {'turnId': params['expectedTurnId'], 'received': params}
    elif method == "test/error":
        send({"id": identifier, "error": {"code": -1, "message": "expected error"}})
        continue
    elif method == "test/disconnect":
        sys.exit(0)
    send({"id": identifier, "result": result})
    if method == "turn/start":
        send({"method": "item/agentMessage/delta", "params": {"itemId": "message-test", "delta": "Hello"}})
        send({"id": "approval-test", "method": "item/commandExecution/requestApproval",
              "params": {"command": "printf hello", "availableDecisions": ["accept", "decline"]}})
