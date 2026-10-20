# Changelog

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
