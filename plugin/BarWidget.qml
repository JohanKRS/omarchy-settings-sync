pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
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
    iconComponent: syncIcon
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

  // Plugin icon: the square toggle knob inside a sync loop. Same geometry as
  // plugin/icons/omarchy-settings-sync-symbolic.svg (24-unit grid), drawn as
  // a vector so it follows the bar colour. BarIconButton loads it into its
  // 16 px optical canvas in place of a font glyph.
  Component {
    id: syncIcon

    Item {
      id: syncGlyph
      readonly property color tint: button.active && button.useActiveColor ? button.activeColor : button.foreground

      Shape {
        width: 24
        height: 24
        scale: syncGlyph.width / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
          fillColor: syncGlyph.tint
          strokeColor: "transparent"
          strokeWidth: -1
          PathSvg { path: "M2 15V5h16.59l-3-3L17 .59 23.41 7H4v8zM22 9v10H5.41l3 3L7 23.41.59 17H20V9zM12 9h6v6h-6z" }
        }
      }

      // Waiting for the user's reply: the same icon in the bar's active
      // colour, plus a dot just outside its top-right corner.
      Rectangle {
        visible: root.waiting
        x: syncGlyph.width - 1
        y: -3
        width: 4
        height: 4
        radius: 2
        color: syncGlyph.tint
      }
    }
  }
}
