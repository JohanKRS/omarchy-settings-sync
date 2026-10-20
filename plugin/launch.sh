#!/usr/bin/env bash
set -euo pipefail
plugin_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ ${1:-} == --install-dependencies ]]; then
  shift
  printf '%s\n' 'Omarchy Settings Sync: installing GTK4 + VTE…'
  omarchy pkg add python-gobject gtk4 vte4 gtk4-layer-shell
  export AGENT_SETTINGS_DEPENDENCIES_ATTEMPTED=1
fi

# A warm panel can be shown without starting Python or importing GTK again.
# Escape each argument as a GVariant string; never evaluate command text.
if [[ " $* " != *" --quit "* ]] && command -v gdbus >/dev/null; then
  application_id="${AGENT_SETTINGS_APP_ID:-org.omarchy.AgentSettings}"
  application_path="/${application_id//./\/}"
  arguments='[<@as ['
  separator=''
  for argument in "$@"; do
    argument="${argument//\\/\\\\}"
    argument="${argument//\'/\\\'}"
    argument="${argument//$'\n'/\\n}"
    argument="${argument//$'\r'/\\r}"
    argument="${argument//$'\t'/\\t}"
    arguments+="${separator}'${argument}'"
    separator=', '
  done
  arguments+=']>]'
  if gdbus call --session --dest "$application_id" --object-path "$application_path" \
      --method org.gtk.Actions.Activate panel "$arguments" '{}' --timeout 1 >/dev/null 2>&1; then
    exit 0
  fi
fi

exec python3 "$plugin_dir/launcher.py" "$@"
