#!/usr/bin/env python3
"""Forward to a warm panel through D-Bus before importing the GTK interface."""
import os
from pathlib import Path
import subprocess
import sys

APP_ID = os.environ.get("AGENT_SETTINGS_APP_ID", "org.omarchy.AgentSettings")


def forward(arguments, application_id=APP_ID):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    path = "/" + application_id.replace(".", "/")
    try:
        bus.call_sync(application_id, path, "org.gtk.Actions", "Activate",
                      GLib.Variant("(sava{sv})", ("panel", [GLib.Variant("as", arguments)], {})),
                      None, Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
        return True
    except GLib.Error:
        return False


def main(arguments=None, application_id=APP_ID):
    arguments = list(sys.argv if arguments is None else arguments)
    try:
        import gi
        if "--quit" not in arguments and forward(arguments, application_id):
            return 0
        if "--hide" in arguments:
            return 0  # Closing an absent panel never creates one or installs packages.
        gi.require_version("Vte", "3.91")
        from app import Application
    except (ImportError, ValueError, OSError) as error:
        if "--hide" in arguments or "--quit" in arguments:
            return 0
        if os.environ.get("AGENT_SETTINGS_DEPENDENCIES_ATTEMPTED") == "1":
            print("Omarchy Settings Sync could not load its GTK dependencies: " + str(error), file=sys.stderr)
            return 1
        subprocess.Popen(["xdg-terminal-exec", "--title=Omarchy Settings Sync", "--", "bash",
                          str(Path(__file__).with_name("launch.sh")), "--install-dependencies",
                          *arguments[1:]], start_new_session=True)
        return 0
    return Application(application_id=application_id).run(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
