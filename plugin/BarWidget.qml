import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "community.agent-settings"
  readonly property string language: (Quickshell.env("AGENT_SETTINGS_LANGUAGE") || Quickshell.env("LANGUAGE") || Quickshell.env("LC_ALL") || Quickshell.env("LC_MESSAGES") || Quickshell.env("LANG") || "en").substring(0, 2)
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function launch(sync) {
    var path = decodeURIComponent(Qt.resolvedUrl("launch.sh").toString().replace(/^file:\/\//, ""))
    var command = ["bash", path]
    var window = button.QsWindow.window
    if (window && window.screen) command.push("--monitor=" + window.screen.name)
    var point = button.mapToItem(null, button.width / 2, button.height)
    command.push("--anchor-x=" + Math.round(point.x))
    command.push("--edge=" + (root.bar ? root.bar.position : "top"))
    command.push("--bar-size=" + root.barSize)
    command.push("--toggle")
    if (sync) command.push("--sync")
    Quickshell.execDetached(command)
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf1de"
    slotSize: Style.bar.statusSlot
    tooltipText: root.language === "pt" ? "Agent Settings\nAbrir · botão direito: sincronizar"
               : root.language === "es" ? "Agent Settings\nAbrir · clic derecho: sincronizar"
               : "Agent Settings\nOpen · right-click to sync"
    onPressed: function(mouseButton) { root.launch(mouseButton === Qt.RightButton) }
  }
}
