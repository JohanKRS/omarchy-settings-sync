"""Read CLI model metadata without sending prompts or installing agents."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


MODEL_AGENTS = {"codex", "claude", "opencode", "gemini", "copilot", "cursor-agent", "pi", "omp"}
DISCOVERY_AGENTS = {"claude", "opencode", "cursor-agent"}


def agent_executable(agent):
    executable = shutil.which(agent)
    if not executable:
        return None
    # Omarchy ships launchers for agents that have never been installed. Do not
    # run them to probe capabilities: `mise use` would install/change settings.
    try:
        with open(executable, "rb") as stream:
            launcher = stream.read(4096).decode("utf-8", errors="replace")
        if "mise use " in launcher and "exec mise x " in launcher:
            result = subprocess.run(["mise", "which", agent], capture_output=True,
                                    text=True, timeout=3)
            resolved = result.stdout.strip()
            return resolved if result.returncode == 0 and os.path.isfile(resolved) and resolved != executable else None
    except (OSError, subprocess.TimeoutExpired):
        return None
    return executable


def normalize_claude_models(rows):
    models = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("value"), str):
            continue
        models.append({
            "model": "" if row["value"] == "default" else row["value"],
            "displayName": row.get("displayName") or row["value"],
            "description": row.get("description", ""),
            "supportedReasoningEfforts": [
                {"reasoningEffort": effort} for effort in row.get("supportedEffortLevels", [])
                if isinstance(effort, str)
            ],
        })
    return models


def parse_opencode_models(output):
    """`models --verbose` emits a model ID followed by its JSON metadata."""
    decoder = json.JSONDecoder()
    models = []
    while output.strip():
        output = output.lstrip()
        name, _, output = output.partition("\n")
        if not re.fullmatch(r"[\w.-]+/[^\s]+", name):
            continue
        metadata = {}
        if output.lstrip().startswith("{"):
            output = output.lstrip()
            metadata, end = decoder.raw_decode(output)
            output = output[end:]
        models.append({"model": name, "displayName": name,
                       "supportedReasoningEfforts": [
                           {"reasoningEffort": key} for key, value in metadata.get("variants", {}).items()
                           if not isinstance(value, dict) or not value.get("disabled")
                       ]})
    return models


def discover_models(agent, executable):
    """Bounded metadata-only calls; no user messages, hooks, or MCP startup."""
    if agent not in DISCOVERY_AGENTS:
        return []
    with tempfile.TemporaryDirectory(prefix="agent-settings-models-") as directory:
        if agent == "claude":
            command = [executable, "--print", "--input-format", "stream-json",
                       "--output-format", "stream-json", "--verbose",
                       "--no-session-persistence", "--strict-mcp-config",
                       "--mcp-config", '{"mcpServers":{}}',
                       "--settings", '{"disableAllHooks":true}', "--setting-sources", "user"]
            request = {"type": "control_request", "request_id": "models",
                       "request": {"subtype": "initialize", "hooks": None}}
            result = subprocess.run(command, input=json.dumps(request) + "\n",
                                    capture_output=True, text=True, timeout=20, cwd=directory)
            for line in result.stdout.splitlines():
                try:
                    response = json.loads(line)
                except ValueError:
                    continue
                response = response.get("response", {})
                if response.get("request_id") == "models" and response.get("subtype") == "success":
                    models = normalize_claude_models(response.get("response", {}).get("models", []))
                    if models:
                        return models
        elif agent == "opencode":
            result = subprocess.run([executable, "models", "--verbose"], capture_output=True,
                                    text=True, timeout=20, cwd=directory)
            if result.returncode == 0:
                models = parse_opencode_models(result.stdout)
                if models:
                    return models
        elif agent == "cursor-agent":
            result = subprocess.run([executable, "--list-models"], capture_output=True,
                                    text=True, timeout=20, cwd=directory,
                                    env={**os.environ, "NO_COLOR": "1"})
            # Cursor emits `id - Display name`; do not mistake headings/errors
            # for model IDs, nor infer effort flags that the CLI doesn't expose.
            clean = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
            models = []
            for line in clean.splitlines() if result.returncode == 0 else []:
                match = re.fullmatch(r"\s*([\w.:-]+)\s+[-–]\s+(.+?)\s*", line)
                if match:
                    models.append({"model": match[1], "displayName": match[2],
                                   "supportedReasoningEfforts": []})
            if models:
                return models
    raise RuntimeError("Model list unavailable")
