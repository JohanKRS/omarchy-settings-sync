# Security and data handling

Omarchy Settings Sync asks a local agent to synchronize configuration between Omarchy
installations. It launches code with your user permissions and is not a security
boundary around the selected agent.

## Report a concern

Use the repository's **Security → Report a vulnerability** option when private
vulnerability reporting is enabled. If that option is unavailable, open an issue
requesting a private reporting channel without including exploit details or
sensitive information. Do not publish tokens, private configuration, conversation
logs or account details in an issue or screenshot.

Reports should identify the affected plugin version/commit, relevant agent CLI
version, observed behavior and a minimal reproduction with synthetic data.
Fixes target the latest development version; older versions have no separate
maintenance guarantee.

## Processes and permissions

- The QML bar widget runs in Omarchy's existing Quickshell process. It starts a
  Python GTK panel on demand, not another Quickshell instance.
- The panel launches the selected agent CLI as your user. No root daemon, custom
  passwordless sudo rule or permanent background sync service is installed.
- The dependency bootstrap runs `omarchy pkg add python-gobject gtk4 vte4
  gtk4-layer-shell` in a visible terminal. Package installation may require
  administrator authentication through Omarchy's normal flow.
- Codex uses `workspace-write` with automatic approval review by default. Manual
  approval and read-only modes are available. Claude uses `--permission-mode auto`
  with a stdio permission callback. The panel does not pass bypass/yolo flags.
- Automatic review can approve actions without a separate manual question.
  Agents and configured MCP servers may modify files, use the network or request
  elevated operations according to their own profile and policy.

## Data flow

The plugin uses existing CLI authentication; it does not ask for an API key or
copy credentials from another application. Local settings, conversations,
activity records and logs are stored under the XDG locations documented in the
README. Newly written state files use owner-only permissions.

The configured agent/provider receives prompts and may read or transmit relevant
configuration content. Enabled MCP servers have their own access and data
policies. The plugin adds no telemetry endpoint, hosted backend or web server.

Model metadata is queried without sending a user prompt. Claude metadata queries
disable hooks, exclude MCP configuration and use a temporary working directory.
Normal agent conversations preserve the user's CLI profile. Bar status contains
only open/waiting state, the monitor name and a heartbeat timestamp.

## Configuration synchronization

The **Sync** button authorizes applying compatible configuration from the chosen
repository on the current installation. **Push changes** authorizes the
agent to publish reusable changes after validation. These choices are expressed
in the agent prompt; they do not replace provider permissions or enforce a Git
policy independently.

The workflow asks the agent to preserve local edits, back up affected files,
review conflicts and avoid copying secrets or hardware-specific state. Treat
repository instructions and scripts as code you are choosing to run. A
successful conversation response is not independent evidence of a completed
sync; inspect the reported validation and pending work.

## Distribution

Omarchy's updater follows the upstream Git branch. A marketplace review applies
to a specific commit and does not automatically cover later changes. Review
updates before applying them. Do not publish local settings, logs, authentication
files or personal configuration in this plugin repository.
