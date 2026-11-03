# Changelog

## 0.2.1 — 2026-11-03

- Align the bar icon with the icons beside it: same size, line weight and
  center line as the bar's font glyphs, with the waiting dot following it.

## 0.2.0 — 2026-11-03

- New plugin icon in the bar, panel header and window: a toggle inside a sync
  loop that follows the bar colors, with a small dot while a reply is waiting.
- Add a **Customizations** tab with a switch per customization saved in the
  configuration repository, grouped by area, searchable and filterable by state.
  Flat rows with expandable details, colored state dots and quiet actions follow
  the active Omarchy theme, light or dark. Customizations are grouped by app,
  with programs to install or uninstall in their own list of simple switches.
  Choices are staged until **Apply** and saved per machine under `machines/`.
- Read customizations from a `features.toml` catalog. The panel applies and
  reverts files, lines, marked blocks, JSON/INI/TOML keys, MIME defaults, user
  services, system files and packages itself, with one password prompt, and
  hands judgment steps and conflicts with local edits to the agent.
- Turning a customization off returns it to the Omarchy default, keeps it as
  it is, or restores the earlier backup. Optional parts have their own switch.
- After an Omarchy update, mark the customizations whose Omarchy defaults
  changed, comparing with the previous package in pacman's cache. Show the
  changed values and files, with Keep mine, Use the new default and Adjust with
  the agent, and a Changed by Omarchy filter.
- **Remove from repository** undoes a customization here and asks the agent to
  delete it from the repository; other machines undo it on their next Sync from
  their own record, even after its files are gone.
- Update the plugin automatically from GitHub releases: check once a day, and
  while idle fast-forward a clean default-branch install to the latest release
  tag, never to unreleased commits. Settings shows the state, with Check now,
  Update now and an Update automatically switch.
- Turn Settings into a tab on the right, after Conversation and Customizations,
  with flat sections for the repository, agent, existing customizations and
  version; Escape returns to the previous tab.
- Move **Sync** from the header to the bottom of the Customizations tab, which
  shows how many updates are waiting. Opening the tab fetches the repository so
  the list is current, without applying anything; the local copy appears at
  once and the fetch runs in the background.
- With a catalog, **Sync** applies what is on for this machine without
  starting the agent unless needed. Repositories without a catalog keep the
  agent-led Sync; **Create catalog** asks the agent to convert them.
- Manage machines from the Customizations tab: list, rename, remove or create
  one, and link a reinstalled installation to its earlier machine or start it
  fresh. Sync waits until a new installation is linked. New and fresh machines
  install nothing until you choose: every customization starts as **New**, and
  a brand-new machine offers **Turn all on**.

## 0.1.13 — 2026-10-27

- Browse and search local conversation history, then resume a native Codex or
  Claude session with its repository, draft, images and queued work intact.
  Keep queues separate between conversations. Older archives without session
  IDs open with an explicit option to continue from their saved transcript.
- Give Settings a distinct gear icon and place a GitHub repository link beside
  the installed version.

- Paste clipboard images into native Codex and Claude prompts, with removable
  thumbnails. Keep images with queued messages, edits, immediate direction and
  local conversation records. Support image-only requests; retain drafts when
  an attachment is missing or the selected external agent cannot receive it.
- Keep the prompt cursor visible when typing, wrapping or navigating through
  text taller than the composer, without changing the panel's fixed size.
- Measure Markdown tables at their displayed width to remove blank space below
  the last row, while preserving wrapped cells and horizontal overflow scrolling.
- Update the pinned GitHub Actions checkout and Python setup dependencies.

## 0.1.12 — 2026-10-22

- Show the installed plugin version in small, muted text at the bottom-right
  of Settings, read directly from the installed manifest.

## 0.1.11 — 2026-10-22

- Automatically name new native Codex and Claude Code conversations
  **Settings Sync · <request>** in the agent's history. Use the original request
  or a short action name, without a model call or the plugin's full instructions.
- Keep names unchanged on follow-ups and resume, preserving user renames.
  If an older CLI cannot set the name, show a short notice and continue the task.
- Include the topic and agent in local conversation archive filenames, with
  unique suffixes to preserve multiple conversations archived within a second.

## 0.1.10 — 2026-10-21

- Clarify that configuration and sync cover the system, Omarchy apps and
  third-party apps. Include those apps in the existing-customization review.
- Show **Review existing customizations** directly in Settings, without a
  collapsed Extras section. Update translations, documentation and screenshots.

## 0.1.9 — 2026-10-21

- Explain the configure, save and sync workflow in the panel and documentation.
  Add **Settings → Extras → Review existing customizations** to ask the agent
  to find portable settings already on the machine and let the user choose
  which to save. Opening Settings never starts a scan.
- Show an agent at work in the marketplace preview and add a screenshot gallery
  to the README, including Settings and its optional customization review.
- Instruct Codex and Claude Code to ask through their native structured question
  tools so the panel receives clickable options without guessing from prose.
- Enable Codex's structured question tool in normal execution for new and
  resumed plugin threads, without changing the user's global configuration.
- Dismiss Codex question panels when the server resolves or cancels the request,
  clearing the waiting indicator without sending a duplicate answer.
- Cover structured question replies, cancellation and thread configuration with
  protocol and graphical regression tests.

## 0.1.8 — 2026-10-20

- Make alternatives in explicit conversation choice questions clickable for
  native Codex and Claude. Send the question and chosen answer immediately,
  preserving composer drafts and queued work. Ignore incomplete streaming
  options, older messages and repeated clicks. Structured question dialogs
  keep their existing behavior.
- Use an upload-style arrow for the queue's **Direct now / Send now** action.
- Keep initial requests and configuration context out of every external CLI's
  process arguments. Open the interactive CLI without a prompt and provide
  **Copy request** for manual paste and send, including the standalone terminal
  fallback. Native Codex/Claude continue sending requests over stdin.
- Cover conversation choices, native direction, external launch arguments,
  manual copying and launch failures with parser and graphical regression tests.

## 0.1.7 — 2026-10-20

- Move queued messages above the composer into bounded, scrollable one-line
  previews with direction/send, edit and remove icons. Edit restores the text
  and publication choice to the main composer, preserving existing drafts.
- Render Markdown tables, links, headings, lists, checklists, quotes and inline
  formatting with native GTK widgets. Support basic inline HTML without running
  scripts or fetching images. Bundle the pinned Mistune parser and its license.
- Increase the maximum panel height from 660 to 740 logical pixels, constrained
  by the monitor, and add a discreet jump-to-latest control when scrolled up.
- Hide the activity indicator while idle or waiting for input. Recreate its
  animation after unmapping to avoid GTK 4.24 leaving a paused spinner on reopen.

## 0.1.6 — Unreleased

- Show Stop as an icon immediately before Send/Queue only while a task runs.
- Align the footer's terminal control with the right edge of Send/Queue.
- Add a separate Claude permission selector for auto review, manual approval,
  accepting edits and planning. Apply it to new/resumed sessions and terminal
  handoffs, preserving each agent's selection independently.
- Make model refresh and the configuration repository's purpose explicit in
  the settings labels.

## 0.1.5 — Unreleased

- Restore the shared hover feedback on flat controls, including Sync, model
  refresh and the workspace terminal.
- Place model information and its refresh control first in Settings.
- Rename Create with agent to Create repository and explain that the entered
  address is saved for later synchronization.
- Align Stop with Send at the right edge and status text with the Push changes
  checkbox; keep the activity spinner after the status text.

## 0.1.4 — Unreleased

- Add a durable per-agent follow-up queue with review, pause/resume, edit and
  removal controls, available for all supported agents.
- Automatically dispatch native Codex/Claude follow-ups in order after a
  successful response; pause after Stop, failure, disconnection or application
  restart. Retain messages with unconfirmed delivery for manual review.
- Steer an active Codex turn with its expected turn ID. Redirect Claude by
  interrupting and continuing in the same process and conversation.
- Keep the composer available for embedded CLIs. Copy pending messages for
  manual paste into their native inputs, without sending terminal keystrokes
  or assuming that a permission prompt is a conversation input.
- Keep a single contextual Send/Queue button and show the queue count only
  when messages are pending. Put Direct now on each queued native message;
  Ctrl+Enter also sends immediately, and Shift+Enter inserts a newline.
- Place the terminal control to the left of Stop at the footer's right edge.
- Use a flat icon-and-text Sync action in the header instead of a close button.
  Keep the repository and model refresh information in Settings, remove the
  duplicate agent selector there and align the repository actions to full width.
- Follow the final laid-out line, preserve the reading position when scrolling
  up and replace edge shadows with a subtle elastic movement.
- Preserve Escape for native CLI controls when the embedded terminal has focus.
- Translate queue controls into Portuguese and Spanish.

## 0.1.3 — Unreleased

Prepare Omarchy Settings Sync for public distribution as a tool for synchronizing
configuration across multiple Omarchy installations.

- Rename the plugin and repository to Omarchy Settings Sync, preserving the
  permanent plugin ID, settings and conversation paths.
- Discover Claude models and supported effort levels from the installed CLI;
  add metadata adapters for OpenCode and Cursor.
- Keep agent, model, effort, composer and Stop controls at stable sizes.
- Integrate native Claude conversations, structured questions, tool permissions,
  interruption and session resume.
- Show a question indicator for pending Codex/Claude interactions.
- Allow companion terminals and viewing settings during active tasks.
- Match the standard bar icon spacing and remove right-click synchronization.
- Expose shell open, hide and toggle lifecycle support for the GTK panel.
- Keep the idle interface ready for 60 seconds and use D-Bus for fast reopening;
  defer VTE loading, pause hidden theme polling and close idle agents separately.
- Add public documentation, synthetic previews, contributor checks and CI.

## 0.1.2

- Show complete dropdown options and focus the message field when opening.

## 0.1.1

- Rename the panel to Omarchy Settings and start agents on demand.

## 0.1.0

- Add the bar panel, configuration repository workflow and local agent support.
