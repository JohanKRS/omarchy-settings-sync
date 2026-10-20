# A configuration repository for multiple Omarchy installations

The configuration repository is the source of portable preferences shared
between your Omarchy installations. Keep it separate from this plugin's code.
An existing repository can keep its current layout and installation strategy.

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
