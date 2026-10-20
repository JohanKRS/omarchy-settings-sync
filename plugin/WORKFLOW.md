# Workflow: sync configuration across Omarchy installations

The primary goal is to synchronize portable configuration across different
Omarchy installations through the user's own configuration repository. You may
also change system or application settings as requested and publish reusable
preferences for other installations to receive. Use the locally configured
agent, model, authentication, tools, skills, plugins and connections. Reply in
the user's language. The request identifies the authorized CONFIGURATION
repository, which is separate from this plugin's source code.

## Choose the path before acting

The request includes local context: previous use, last attempt, resumed
conversation, last applied commit and `sync_record_path`. This is local evidence,
not proof that the remote is reachable or that an earlier task succeeded.

- **A sync was completed on this installation:** first query only the remote SHA
  for the selected branch. If it equals the last SHA applied with status
  `complete`, reply only with “No changes.” in the interface language and stop.
  Do not inspect the system, back up files, clone/pull, reinstall, test, reload,
  commit or rewrite the record. Network/authentication failure is not evidence
  of no changes. An explicit request to reconcile local drift takes priority.
- **First use of the plugin:** do not assume a new system or empty repository.
  Read the existing repository and compare it with installed configuration.
  Adopt equivalent components without rewriting them. Preserve earlier
  customization and apply only what is missing or different.
- **An organized repository already exists:** preserve its names, structure,
  documentation, scripts and installation strategy. Do not create a second
  repository or dotfiles framework. Reuse the complete checkout if its remote
  matches the authorized repository.
- **A specific request in an existing conversation:** continue the context and
  change only what is needed. Do not repeat onboarding, a full sync, a global
  inventory or installation of dependencies already verified.
- **An incomplete/interrupted attempt:** inspect completed steps and backups
  before continuing. Resume pending work without repeating cumulative actions.
  A finished response or an exited CLI is not proof of a completed sync.
- **Create a repository:** this must be explicit in the request. Check whether
  it already exists; if so, adopt its contents. Never initialize or capture a
  baseline merely because you assume it is empty.

Do not ask for information already available in the repository, context or
current machine. When the remote changes, compare the last applied commit with
the new HEAD, including file renames. Documentation-only or organizational
changes do not require reinstalling equivalent destinations. Apply the delta
and its dependencies. If local files already match the new HEAD, record that
adoption without unnecessary writes or reloads.

## Prepare

When changes are required, read the available Omarchy skill and the configuration
repository's README, AGENTS.md and SYNC.md. The no-change fast path ends before
this preparation. Check the remote HEAD on every sync; do not assume the local
checkout is current. Use authenticated Git/gh or the Git provider's connected
tools. Never search another application's files for tokens. If authentication
is missing, use the normal login flow and explain the pending step.

Work in a complete checkout under `repository` in the workspace specified by
the request. If that directory belongs to another remote, use a separate,
repository-specific directory instead of replacing it. Connector downloads must
pin a commit, enumerate the full tree, verify Git hashes and preserve permissions.

Inspect the installed version, active files and local differences. Do not copy
another machine's monitor connectors, resolutions, scales, GPU/driver choices,
physical microphone, profile paths, usernames, sessions or credentials. Identify
portable preferences. Keep hardware adaptations local and document conditions
for shared components.

## Sync

Clicking Sync authorizes fetching and applying all documented customizations
compatible with the current installation.

1. Inventory the components, including newly documented ones in README/SYNC.md.
   On repeat use, focus on changed components. Compare the remote, active files
   and last applied version.
2. Preserve unpublished local changes and reconcile using the last applied
   version as the base. Back up and ask about genuine unresolved conflicts;
   do not silently choose one side.
3. Before the first change, mark the sync `partial` in `sync_record_path`,
   preserving the last completed SHA as the base. Back up only affected
   destinations with a manifest under `backups/<timestamp>` in the local state
   directory provided in the request.
4. Apply configuration blocks without duplicating imports, bindings or hooks.
   An integration snippet is not a whole file. Use user extensions and never
   edit packaged files under `/usr/share/omarchy`.
5. Install missing dependencies through Omarchy's normal flow. Adapt services
   and backends to the hardware. Do not start services with missing models or
   required files. Do not interrupt recordings, graphical sessions or apps
   containing open work.
6. Validate every affected component. After Hyprland changes, run `hyprctl reload`
   and `hyprctl configerrors`. Bound binding-list queries with a timeout. Check
   current documentation before creating window rules.
7. When publishing is enabled, save and publish reconciled, documented, reusable
   changes to the configuration repository.
8. Record repository, branch, applied SHA, date, files and components in the
   supplied `sync_record_path`. Use `complete` only after verifying everything
   required; otherwise use `partial` and list `pending` items. Required fields:
   `repository`, `branch`, `sha` (40 characters), `date` (ISO 8601), `status`,
   `pending`, `files` and `components`. This record belongs to this installation
   and repository; do not publish it or copy it from another machine.

## Specific configuration changes

Carry out the concrete request, back up affected files and test. If **Publish
changes** is enabled, update reusable files, README/SYNC.md and relevant tests,
then publish a commit after validation. The panel request authorizes that
publication. Keep hardware-specific adjustments local. Report the commit and
pending steps; other installations receive the change through Sync.

When publishing is disabled, apply locally without publishing or updating the
remote branch.

## Publication and data

Use only the configured URL and branch. Preserve repository visibility. Advance
the branch without force-push, checking the previous SHA. If the remote advances,
read and incorporate concurrent changes rather than overwriting them.

Do not upload passwords, tokens, cookies, histories, complete profiles, downloaded
models, agent conversations, caches or session data. Do not report success merely
because you finished responding. State what was applied, verified and published,
and what still needs authentication, an administrator password, restart or user
intervention.

## Create a configuration repository

Create only the requested repository, with PRIVATE visibility by default. Do not
replace an existing repository. Prepare a README, SYNC.md with source-to-destination
mappings and hardware conditions, a .gitignore and portable configuration. Do not
capture the home directory indiscriminately. The PLUGIN repository is never the
destination for personal configuration.

For a new repository, prefer native files under `apps/<application>/`,
`desktop/<component>/` and `system/<component>/`, with helpers, tests and README
files next to each component. Document destinations, merge boundaries and real
dependencies in SYNC.md. Avoid duplicate settings, blobs, submodules and dependence
on unrelated personal projects when native files or a small included helper
suffice. Preserve an existing layout unless reorganization was requested.

## Access and continuity

Preserve the agent profile's tools and connections. Native Codex uses
`workspace-write` with automatic approval review by default; questions and
permissions are handled in the panel. Native Claude uses the permission mode
selected in Settings and structured permission callbacks. Other agents run their
interactive CLIs with their own authentication and permission controls.

Do not disable sandboxing, review, policies or controls to bypass a block.
Explain specific blockers and continue permitted work. Do not restart or update
the plugin process during an active task.
