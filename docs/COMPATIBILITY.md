# Omarchy compatibility

The plugin is a bar entry point for an agent-assisted configuration sync panel.
It is implemented as a QML widget plus a GTK companion application, rather than
as a copy of the native clock panel tutorial.

## Contracts

| Reference requirement | Implementation |
| --- | --- |
| One repository with a root manifest | `manifest.json`, schema 1, one `bar-widget` kind |
| Permanent non-reserved ID | `community.agent-settings`; no `omarchy.*` namespace or clone-only metadata |
| Author, version, description and license | Declared in the manifest; MIT license at the root |
| Safe relative entry point; no packaged symlinks | `plugin/BarWidget.qml`; checked before release |
| Existing shell process | `Ui.BarWidget` and `Ui.BarIconButton` are hosted by Omarchy; no second Quickshell |
| Open/close lifecycle | `opened`, `open()`, `close()`, `toggle()` and `closeForPopoutSwitch()` forward to the GTK application |
| Shell IPC | `omarchy-shell shell summon`, `hide` and `toggle` route through the live bar widget |
| Popout coordination | The widget requests/releases the bar's active popout when GTK visibility changes |
| User-owned installation | Omarchy installs under `~/.config/omarchy/plugins/`; packaged system files are not modified |
| Normal package installation | The optional first-run bootstrap uses `omarchy pkg add` in a visible terminal |
| Data ownership | Personal configuration belongs in a separate repository and XDG state paths |

The current ID was absent from both active and retired IDs in the marketplace
registry checked during preparation. The marketplace makes the final uniqueness
decision; changing a published ID would require migration planning.

## GTK design and limits

The companion uses GTK4 Layer Shell for monitor-aware placement, focus, Escape
and outside-click behavior. Visibility and pending-question state are shared
through a small local heartbeat file, without conversation text. Expired state
is ignored after 30 seconds. Shell open/close calls use the normal application
entry point; a hide request never creates an absent panel.

The bar icon uses Omarchy's shared icon component and dimensions. The GTK panel
reads the active theme's palette, font and control styling. It does not implement
all QML-specific gradient/border tokens, the complete `Style.spacing` contract,
or native Tab navigation between bar popouts. Tab navigates the GTK form. These
are documented architectural differences, not a claim of pixel-identical native
QML rendering.

The interface remains available for up to 60 seconds after an idle close to
speed up reopening. Idle agent connections are closed separately. Theme polling
pauses while hidden; the VTE terminal is initialized only when an external CLI
is launched. There is no permanent background sync service.

## Validation

Portable checks cover repository packaging, links, JSON, Python/shell syntax,
protocol handling, agent argument construction, context state and model formats.
The graphical smoke test covers layout stability, approvals, questions, session
resume, cancellation, disconnection, terminals and temporary UI retention.

Run these additional checks on a real Omarchy session:

```sh
omarchy plugin validate .
bash tools/lint_qml.sh
python3 tests/ui_smoke.py
omarchy-shell shell summon community.agent-settings '{}'
omarchy-shell shell hide community.agent-settings
omarchy-shell shell toggle community.agent-settings '{}'
```

`lint_qml.sh` supplies a temporary `qs` import alias because Quickshell resolves
that namespace virtually at runtime. It creates no symlink in the plugin.
Confirm disable/re-enable, theme behavior and shell restart before release.
Removal is handled by Omarchy's plugin manager; finish active tasks first and
check that user state remains intact. Multi-monitor and non-default theme scaling
need testing on the target setup.

The local release checks used Omarchy 4.0.5-1, Codex CLI 0.163.0 and Claude Code
2.1.302. OpenCode and Cursor catalog adapters have fixture tests; other agent
accounts have not been exercised in this environment.

## Follow-up support

The 0.1.10 update makes the existing-customization review visible directly in
Settings and clarifies that system, bundled-app and third-party app settings
can be synchronized. All 46 portable tests, the Portuguese graphical test and
the launcher smoke test pass. The graphical fixture verifies that the review
button is visible immediately, validates its repository and stays disabled
during active work. Updated previews use synthetic data.

The 0.1.9 update directs Codex and Claude Code to their native structured question
tools in the shared workflow and in every request, including the short sync
path. Codex thread start/resume sets `features.default_mode_request_user_input`
for that thread; it does not write global configuration. This feature is under
development in the tested Codex CLI 0.163.0. The installed server accepted the
override on an ephemeral thread, and its prompt renderer confirmed availability
in Default mode, without making an inference request.

The 46 portable tests and Portuguese graphical test cover thread configuration,
native replies, diagnostic questions without selection keywords, and Codex
`serverRequest/resolved` cleanup, including repeated and unrelated-thread events.
Claude's structured question, free-text and multiple-choice fixtures also pass.
These checks validate the integration; the model still chooses when to call the
tool. Prose-only alternatives keep the existing conservative fallback parser.
The optional existing-customization review is an explicit Settings action. Its
fixtures cover repository validation, no automatic scan on opening, publication
preferences, and disabling the action during active work.

The 0.1.8 update adds clickable alternatives to explicit choice questions in
native Codex/Claude conversation messages. Parser tests cover numbered, bulleted
and lettered alternatives, supported languages, formatting and ordinary lists
that must stay text. Graphical fixtures cover active Codex direction, idle
continuation, Claude interrupt-and-continue, draft/queue preservation, repeated
clicks and unknown delivery. Structured question dialogs are unchanged.

External agents now start interactively without prompt-bearing arguments; the
user copies the initial request and pastes/sends it through the CLI input. The
same behavior applies when VTE is unavailable. Fixtures cover every adapter,
both launch paths, exact copied content and failed terminal launches. These
checks verify the plugin's transport and UI, not live third-party accounts.

The 0.1.7 update keeps the queue inline above the composer, limits its height and
renders message formatting with native GTK widgets. Its 38 portable tests cover
tables, nested formatting, escaping, links and partial streaming input as well as
the existing protocols. The Portuguese graphical test covers the queue's layout
and actions, Markdown tables, jump-to-latest and activity-indicator recreation.
Synthetic screenshot capture also compares activity frames after reopening to
verify animation. The GTK 4.24 spinner workaround replaces only the unmapped
indicator; it does not override the desktop's motion preference.

The 0.1.6 update adds separate native Claude permission settings using
`--permission-mode auto|default|acceptEdits|plan`. Protocol tests check launch
arguments and invalid modes; the graphical test covers independent persistence,
changing modes between turns while retaining the session, and terminal resume.
The UI also checks that Stop is visible only during work and that the terminal
and Send/Queue controls share their right edge. The 31 portable tests and the
extended graphical test passed with the installed CLI versions listed above.
These protocol checks use fixtures, rather than live model calls. Mode semantics
follow the [Claude permission documentation](https://code.claude.com/docs/en/permission-modes).

| Agent integration | Queue | Direction during work |
| --- | --- | --- |
| Codex app-server | Local durable queue, automatically dispatched after `turn/completed` | `turn/steer` with `expectedTurnId` |
| Claude stream-json | Local durable queue, automatically dispatched after a result | Interrupt acknowledgement plus terminal result, then a new input in the same session |
| All embedded CLIs | Local durable queue, manually copied into the native input | Use the running CLI's own controls; native capabilities vary |

Only a successful native completion advances the automatic queue. Stop, errors,
disconnection and restart require explicit resume. Unconfirmed transport
delivery is retained and requires review instead of automatic retry. Queue
entries retain their publication choice and cannot dispatch into a different
repository, branch or native conversation.

The installed Codex 0.163.0 schema includes `turn/steer`. Protocol fixtures and
the graphical smoke test cover native follow-up sequencing, interrupted Claude
continuation, uncertain delivery and all external agent queue/copy controls.
These checks do not establish live model behavior or queue/steering support in
every third-party CLI. Terminal automation deliberately does not guess when
those agents have finished a response or are waiting for a permission answer.

The 0.1.4 build passed 29 portable tests, the extended graphical test in
Portuguese, the D-Bus launcher test, manifest validation, QML lint and syntax
checks. The synthetic panel previews were regenerated and inspected.

Protocol references: [Codex App Server](https://learn.chatgpt.com/docs/app-server#steer-an-active-turn)
and [Claude streaming input](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode).

The prepared 0.1.3 build passed the Omarchy manifest validator, QML lint, 22
portable tests, the graphical smoke test and the D-Bus launcher smoke test.
Live shell checks passed for summon, hide, toggle, switching to the clock popout
and disabling/re-enabling the widget. Reopening reused the same process and the
bar layout remained unchanged. Synthetic screenshots were inspected before
packaging. These local checks do not replace marketplace review.

## References

- [Marketplace development guide](https://plugins.omarchy.org/develop.html)
- [Marketplace publishing guide](https://plugins.omarchy.org/publish.html)
- [Official Omarchy shell reference](https://github.com/omacom/omarchy/blob/quattro/docs/omarchy-shell.md)
- [Marketplace submission requirements](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SUBMISSION.md)
- [Marketplace security baseline](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SECURITY.md)
