# Changelog

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
