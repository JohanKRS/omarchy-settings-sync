# Changelog

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
