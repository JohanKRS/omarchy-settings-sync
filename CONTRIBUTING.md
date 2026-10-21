# Contributing

The project's primary purpose is synchronizing portable configuration across
multiple Omarchy installations through the user's own repository and local
agent. Changes should support that workflow and preserve machine-specific data.

## Development setup

Clone the repository into a normal working directory. Do not edit packaged files
under `/usr/share/omarchy`. Python protocol tests use only the standard library
and fake subprocesses; no account or agent call is required.

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q plugin tests tools
bash -n plugin/launch.sh
python3 tools/check_repository.py
```

On an Omarchy desktop with the README's GTK dependencies installed:

```sh
omarchy plugin validate .
bash tools/lint_qml.sh
python3 tests/ui_smoke.py
python3 tests/launcher_smoke.py
```

The UI smoke test uses temporary XDG state and protocol fixtures. It checks
layout stability, questions, terminal behavior and settings without running a
real configuration sync. GitHub Actions runs the portable checks on Python 3.11
and 3.14; graphical and shell integration checks require an Omarchy session.

## Runtime layout

- `manifest.json` declares the single `bar-widget` entry point.
- `plugin/BarWidget.qml` renders the icon and forwards the shell lifecycle.
- `plugin/app.py` provides the GTK panel and native conversation UI.
- `plugin/core.py` implements Codex RPC and external CLI launch arguments.
- `plugin/claude_client.py` adapts Claude's bidirectional stream protocol.
- `plugin/catalog.py` queries model metadata without starting a conversation.
- `plugin/context.py` tracks local sync activity and repository identity.
- `plugin/message_markup.py` parses Markdown and restricts inline markup/links;
  `plugin/message_view.py` builds the native message widgets. The pinned parser
  and its update instructions are in `plugin/_vendor/`.
- `plugin/WORKFLOW.md` contains the instructions sent to the agent for syncs.

See [compatibility notes](docs/COMPATIBILITY.md) before changing shell integration.
Use argument arrays for subprocess calls, preserve authentication boundaries and
keep test state separate from real user settings. Agent-specific features should
reflect the installed CLI's capabilities rather than a guessed model list.

## Documentation and screenshots

All project documentation is in English. UI translations belong in
`plugin/locales/`. Keep synchronization between installations as the main story
in the README, screenshots and release notes.

Generate screenshots with synthetic data in a running Omarchy session:

```sh
AGENT_SETTINGS_LANGUAGE=en python3 tools/capture_preview.py
```

This captures only the test panel into `preview.png`, `docs/settings.png`,
`docs/questions.png`, `docs/choices.png` and `docs/conversation.png`, and checks
activity animation after reopening.
Inspect all images before committing. Do not include
private repositories, usernames from filesystem paths, tokens or conversations.

## Changes and releases

Explain the behavior being changed and how you verified it. Add focused tests
for protocol, permission, state or lifecycle changes. Documentation-only changes
do not need new tests. Keep the manifest version and Codex client information in
sync, and update `CHANGELOG.md` for user-visible changes.

Follow [RELEASING.md](docs/RELEASING.md) for publication and marketplace submission.
Every published version gets an annotated `vX.Y.Z` tag and a GitHub Release with
the corresponding dated changelog entry. Do not move existing release tags.
Do not change the permanent plugin ID casually: existing installations and
marketplace records depend on it.
