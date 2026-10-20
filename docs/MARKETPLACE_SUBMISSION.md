### Repository URL

https://github.com/JohanKRS/omarchy-settings-sync

### Category

System

### Tags

ai, bar, system

### Suggest a missing tag

_No response_

### Maintainer notes

Omarchy Settings Sync synchronizes configuration across different Omarchy installations
using the user's own Git repository and locally authenticated agent. Each
installation applies portable preferences on demand while preserving local
hardware-specific settings. The plugin repository contains no personal dotfiles.

The QML bar widget runs in the existing Omarchy shell and starts a GTK4 Layer Shell
panel on demand. Codex and Claude have native conversations and question handling;
other supported CLIs use an embedded VTE terminal. README.md documents agent
support, permission modes, local state and data flow.

The optional dependency bootstrap invokes Omarchy's package manager in a visible
terminal for python-gobject, gtk4, vte4 and gtk4-layer-shell. This installation
capability requires reviewer attention. There is no second Quickshell instance,
root daemon, custom passwordless sudo policy or permanent background sync service.
The preview uses synthetic configuration. docs/COMPATIBILITY.md describes the
GTK design and its differences from native QML panels.

### Submission checklist

- [ ] The repository is public and contains installation and removal instructions.
- [ ] I have documented the plugin license and any external dependencies.
- [ ] I confirm that I own or have permission to submit this plugin and its preview assets.
- [ ] The plugin does not overwrite user configuration without explicit consent.
- [ ] I understand that approval is for listing and is not a security review.
