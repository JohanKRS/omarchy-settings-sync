#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
shell_dir="${OMARCHY_PATH:-/usr/share/omarchy}/shell"
qml_linter="$(command -v qmllint || true)"
if [[ -z $qml_linter && -x /usr/lib/qt6/bin/qmllint ]]; then
  qml_linter=/usr/lib/qt6/bin/qmllint
fi
if [[ -z $qml_linter || ! -d $shell_dir ]]; then
  printf '%s\n' 'Install the Qt QML tools and run this check on an Omarchy system.' >&2
  exit 1
fi
# Quickshell exposes qs.* virtually at runtime. Give the standalone linter
# the same namespace without introducing a symlink into the plugin folder.
imports_dir="$(mktemp -d)"
trap 'rm -rf -- "$imports_dir"' EXIT
ln -s "$shell_dir" "$imports_dir/qs"
"$qml_linter" -I "$imports_dir" "$repo_dir/plugin/BarWidget.qml"
