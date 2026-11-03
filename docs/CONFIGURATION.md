# A configuration repository for multiple Omarchy installations

The configuration repository is the source of portable preferences shared
between your Omarchy installations. Keep it separate from this plugin's code.
An existing repository can keep its current layout and installation strategy.

## Bring existing customizations

Use **Settings → Review existing customizations** to ask the agent to compare
current system and app settings with available defaults and your repository.
This includes apps bundled with Omarchy and third-party apps installed later.
It summarizes portable candidates and asks what to include before saving them.
This is a review of current files, not a complete history of past changes.
Active settings stay in place; publishing still follows **Push changes**.

## Suggested layout for a new repository

```text
dotfiles/
├── README.md
├── SYNC.md
├── .gitignore
├── apps/
│   └── terminal/
├── desktop/
│   ├── keyboard/
│   └── theme/
└── system/
    └── power/
```

Keep native configuration files, small helper scripts, tests and explanations
next to the component they configure. In `SYNC.md`, document:

- Each source file and its destination on the current installation.
- Whether to copy a whole file or merge a particular block.
- Required packages and commands that verify a successful application.
- Hardware requirements, optional components and machine-specific overrides.
- How to undo the change using the local backup.

## Customizations catalog

A `features.toml` file at the root turns each customization into a switch in
the panel's **Customizations** tab. Each machine turns features on or off
independently, and Sync applies only what is on for that machine. In a
repository without a catalog, the tab offers **Create catalog**, which asks the
agent to convert the existing inventory; afterwards the agent keeps the catalog current whenever it creates
or changes a setting.

```toml
version = 1

[[feature]]
id = "lock-shortcut"
title = "Super+L locks the screen"
summary = "Super+Ctrl+L toggles the workspace layout."
group = "desktop"            # desktop, apps or system
areas = ["hyprland"]
default = "on"               # for other machines: on, off or ask
when = ["command:hyprctl"]   # package:, command:, path:, omarchy>=4.1; ! negates

[[feature.part]]
kind = "block"
dest = "~/.config/hypr/bindings.lua"
source = "desktop/hyprland/lock-bindings.lua"

[[feature]]
id = "idle-timers"
title = "Screensaver after 5 minutes, lock after 10"
group = "desktop"

[[feature.part]]
kind = "json"
dest = "~/.config/omarchy/shell.json"
values = { "idle.screensaver" = 300, "idle.lock" = 600 }
```

| Part kind | Applied by | Turning off |
| --- | --- | --- |
| `file` | Plugin | Restores the Omarchy default or deletes the file it created |
| `line`, `block` | Plugin, inside markers | Removes the line or block |
| `json`, `ini` (`format = "toml"` for simple TOML), `mime` | Plugin | Returns each key to the Omarchy default or its previous value |
| `user-service` | Plugin | Disables the unit if the plugin enabled it |
| `system-file`, `package` | Plugin, one password prompt | Removes the file or restores the backup; restores base packages |
| `agent` | The agent, with `instructions` | The agent, with the recorded state |

Optional parts have an `id` and `optional = true` and get their own switch.
When turning a feature off you can return to the Omarchy default, stop syncing
and keep the current state, or restore the backup taken before it was first
applied. A destination edited outside the plugin is shown as **Edited locally**
and is never overwritten; the agent reconciles it.

Choices are stored in `machines/<name>.toml`. The name starts as the hostname.
**Manage machines** in the Customizations tab lists every machine in the
repository with its hostname, Omarchy version and last update, and lets you
rename or remove one, create a new one, or link this installation to an
existing machine. After a reinstall the tab asks which machine the new
installation is: use its previous choices, or **Start fresh** to keep the name
but clear its choices. Sync waits for that answer. A new or fresh machine
installs nothing by itself: every customization starts as **New** until you
turn it on, one by one or with **Turn all on**, and apply. A short, non-reversible id derived from `/etc/machine-id` tells a new
installation apart from the old one without publishing the machine id:

```toml
name = "desktop"

[features]
"printing-filter" = "off"

[off]
"lock-shortcut" = "keep"     # default, keep or previous

[parts]
"firefox-popups.profile-module" = "off"
```

**Remove from repository**, in a customization's details, deletes it
everywhere: the panel undoes it on this machine, returning to the Omarchy
default, and asks the agent to delete its catalog entry, its source files, its
documentation and its machine entries, then publish. Every other machine
undoes it on its next Sync, using its own record of what was applied.

Validate a catalog with `python3 plugin/features.py validate <repository>`.
Customizations saved with **Push changes** disabled go to a local catalog on
that machine and are marked **this machine only**.

## What to share

Share preferences that make sense on another installation: application settings,
portable shortcuts, theme choices and documented system behavior. Use variables
or local overrides for user-specific paths.

Keep monitor connector names, resolutions, GPU choices, physical microphone
identifiers, device paths and other hardware details local unless the component
explicitly detects the target hardware. Credentials, cookies, complete agent
profiles, conversations, caches and downloaded models do not belong in the
shared repository.

## First and subsequent syncs

Select the same repository and branch in the plugin on each installation. The
agent is instructed to compare existing configuration before changing anything,
adopt matching components, preserve unpublished local edits and ask about
unresolved conflicts. Each installation keeps its own backups and sync record.

After a completed sync, the workflow checks the remote commit first. If it is
unchanged, it asks the agent to return a short “No changes.” response. If it has
changed, the agent should apply and verify the relevant changes. An interrupted
or partial sync is not treated as completed.

This fast path checks the recorded repository revision, not local configuration
drift. If you changed files outside the plugin, explicitly ask the agent to
compare and reconcile those local changes even when the remote commit is the same.

## Publish changes from an installation

Describe the change and enable **Push changes** to authorize publishing the
portable configuration after validation. Other installations receive it when
you click **Sync** there. Disable publishing for a local-only adjustment.

Publishing and the backup/validation procedure are instructions sent to the
agent, not a separate Git enforcement layer. Review its result, permissions and
any pending steps. The plugin never treats a finished response alone as proof
that every setting was applied successfully.
