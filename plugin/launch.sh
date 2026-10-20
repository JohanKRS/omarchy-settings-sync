#!/usr/bin/env bash
set -euo pipefail
plugin_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
install_attempted=0

if [[ ${1:-} == --install-dependencies ]]; then
  shift
  install_attempted=1
  printf '%s\n' 'Agent Settings: installing GTK4 + VTE…'
  omarchy pkg add python-gobject gtk4 vte4 gtk4-layer-shell
fi

if ! python3 -c 'from ctypes import CDLL; CDLL("libgtk4-layer-shell.so"); import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Vte", "3.91"); gi.require_version("Gtk4LayerShell", "1.0"); from gi.repository import Gtk, Vte, Gtk4LayerShell' >/dev/null 2>&1; then
  if (( install_attempted )); then
    printf '%s\n' 'GTK4/VTE could not be loaded. Check the package installation above.' >&2
    read -r -p 'Press Enter to close.' || true
    exit 1
  fi
  exec xdg-terminal-exec --title='Agent Settings' -- \
    bash "$plugin_dir/launch.sh" --install-dependencies "$@"
fi
exec python3 "$plugin_dir/app.py" "$@"
