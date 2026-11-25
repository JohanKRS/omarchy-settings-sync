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
independently. Sync fetches the catalog. The switches stage choices for Apply. In a
repository without a catalog, the tab offers **Create catalog**, which asks the
agent to convert the existing inventory; afterwards the agent keeps the catalog current whenever it creates
or changes a setting.

```toml
version = 1

[[feature]]
id = "lock-shortcut"
title = "Super+L locks the screen"
summary = "Super+Ctrl+L toggles the workspace layout."
app = "hyprland"             # the panel groups customizations by app
areas = ["hyprland"]         # every area it touches
default = "on"               # catalog preference; new entries await a machine choice
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

Programs that are only installed or removed do not need a feature. List them
under `[[program]]`; each one gets a simple switch in the **Programs** group:

```toml
[[program]]
package = "papers"
title = "Papers"

[[program]]
package = "libreoffice-fresh"
title = "LibreOffice"
action = "remove"

[[program]]
package = "artcraft-launcher"
aur = true                   # installed by the agent with omarchy pkg aur add

[[program]]
id = "office-removed"        # optional; keeps machine choices when converting a feature
package = "libreoffice-fresh"
packages = ["libreoffice-fresh", "libreoffice-still"]
action = "remove"

[[program]]
package = "ai.storyteller.artcraft-launcher"
instructions = "apps/craft-launcher/README.md"   # a direct download the agent installs
```

Customizations name their `app` (such as `firefox` or `hyprland`); the panel
groups by it. Settings with `group = "system"` and no app are listed under
System.

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

A request that changes or adds options to something already in the catalog
edits that feature, keeping its `id` so every machine's choice still applies;
the agent receives the list of saved customizations with each request. Two
features that change the same file, line or key fail `features.py validate`.

**Remove from repository** is staged until **Apply**, like a switch. The panel
then undoes the feature on this machine as its off choice says, deletes its
catalog entry, its choices in `machines/` and the source files only it used, and
publishes one commit. The agent is called only for what the panel cannot judge,
such as mentions in README or SYNC.md, and is told not to ask questions.

Choices are stored in `machines/<name>.toml`. The name starts as the hostname.
**Manage machines** in the Customizations tab lists every machine in the
repository with its hostname, Omarchy version and last update, and lets you
rename or remove one, create a new one, or link this installation to an
existing machine. After a reinstall the tab asks which machine the new
installation is: use its previous choices, or **Start fresh** to keep the name
but clear its choices. Apply waits for that answer. A new or fresh machine
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
documentation and its machine entries, then publish.

### After an Omarchy update

The panel remembers which Omarchy version each machine last reviewed. When the
version changes, it compares the defaults in `/usr/share/omarchy` that each
customization depends on with the previous version, read from pacman's package
cache or from a copy saved at the last review. Affected customizations are
marked in the list, with a **Changed by Omarchy** filter. Their details show
the changed default values and files, and offer **Keep mine**, **Use the new
default** (turn it off and return to Omarchy's default) or **Adjust with the
agent**, which opens the conversation with the differences attached. A
customization whose value Omarchy now uses by default is marked as one you can
turn off; Hyprland configuration errors after the update are flagged too.

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

Select the same repository and branch on each installation. Sync refreshes the
catalog in Customizations. Previously selected switches keep their choices.
New entries appear for review, including entries with a catalog default of
`on`. Choose the settings you want and click Apply to change this machine.

Sync fetches the repository and shows its branch as it is on the remote. It
applies nothing. When the working copy is idle, Sync fast-forwards it. While
the agent works in it, or when it cannot fast-forward, the list is read from a
clean copy of that commit in the plugin's state folder instead. Local changes
that block a fast-forward are listed and never discarded. The action bar then
says what Sync brought: the new and removed customizations, or nothing new
since the repository's last change.

A customization deleted from the repository leaves the list. If this machine
still has it applied, a notice offers **Undo here**, which returns to the
Omarchy default, or **Keep here**, which keeps the files and stops tracking
them. Either one runs on Apply.

Customizations saved with **Push changes** off stay in this machine's
`features.local.toml` and never reach other machines. A switch is a choice for
one machine, so turning it on in one installation does not turn it on in
another.

## Publish changes from an installation

Describe the change and enable **Push changes** to authorize publishing the
portable configuration after validation. Other installations receive it when
you click **Sync** there. Disable publishing for a local-only adjustment.

Publishing and the backup/validation procedure are instructions sent to the
agent, not a separate Git enforcement layer. Review its result, permissions and
any pending steps. The plugin never treats a finished response alone as proof
that every setting was applied successfully.
