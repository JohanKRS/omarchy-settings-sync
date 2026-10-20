import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui as Ui

Ui.BarWidget {
  id: root
  moduleName: "community.agent-settings"
  readonly property string language: (Quickshell.env("AGENT_SETTINGS_LANGUAGE") || Quickshell.env("LANGUAGE") || Quickshell.env("LC_ALL") || Quickshell.env("LC_MESSAGES") || Quickshell.env("LANG") || "en").substring(0, 2)
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  property var attention: ({})
  property real now: Date.now()
  readonly property var hostWindow: button.QsWindow.window
  readonly property var hostBar: root.bar
  readonly property bool fresh: now / 1000 - (attention.updated || 0) < 30
  readonly property bool waiting: attention.waiting === true && fresh
  readonly property bool opened: attention.opened === true && fresh
    && (!attention.monitor || (hostWindow && hostWindow.screen && attention.monitor === hostWindow.screen.name))
  readonly property bool popoutSwitchClosing: false

  function open() { launch("") }
  function close() { launch("--hide") }
  function toggle() { launch("--toggle") }
  function closeForPopoutSwitch() { close() }

  onOpenedChanged: {
    if (!root.hostBar) return
    if (root.opened) root.hostBar.requestPopout(root)
    else root.hostBar.releasePopout(root)
  }
  Component.onDestruction: {
    if (root.opened) root.close()
    if (root.hostBar) root.hostBar.releasePopout(root)
  }

  FileView {
    id: attentionFile
    path: (Quickshell.env("XDG_STATE_HOME") || (Quickshell.env("HOME") + "/.local/state")) + "/omarchy-agent-settings/attention.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try { root.attention = JSON.parse(text()) }
      catch (error) { root.attention = ({}) }
    }
    onLoadFailed: root.attention = ({})
  }
  Timer { interval: 1000; running: root.waiting || root.opened; repeat: true; onTriggered: root.now = Date.now() }

  function launch(action) {
    var path = decodeURIComponent(Qt.resolvedUrl("launch.sh").toString().replace(/^file:\/\//, ""))
    var command = ["bash", path]
    var window = root.hostWindow
    if (window && window.screen) command.push("--monitor=" + window.screen.name)
    var point = button.mapToItem(null, button.width / 2, button.height)
    command.push("--anchor-x=" + Math.round(point.x))
    command.push("--edge=" + (root.hostBar ? root.hostBar.position : "top"))
    command.push("--bar-size=" + root.barSize)
    if (action) command.push(action)
    Quickshell.execDetached(command)
  }

  Ui.BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.waiting ? "\uf059" : "\uf1de"
    active: root.waiting
    tooltipText: root.waiting
               ? (root.language === "pt" ? "Omarchy Settings Sync\nAguardando sua resposta · clique para abrir"
                  : root.language === "es" ? "Omarchy Settings Sync\nEsperando tu respuesta · clic para abrir"
                  : "Omarchy Settings Sync\nWaiting for your reply · click to open")
               : root.language === "pt" ? "Omarchy Settings Sync\nClique para abrir"
               : root.language === "es" ? "Omarchy Settings Sync\nClic para abrir"
               : "Omarchy Settings Sync\nClick to open"
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton) {
        if (root.waiting) root.open()
        else root.toggle()
      }
    }
  }
}
