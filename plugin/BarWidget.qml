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

  // Plugin icon: the square toggle knob inside a sync loop, drawn as a
  // vector so it follows the bar colour. BarIconButton loads it into its
  // 16 px optical canvas in place of a font glyph.
  //
  // This is the bar's optical size of plugin/icons/omarchy-settings-sync-symbolic.svg:
  // the same shape with slightly heavier lines, drawn at 13/16 of the canvas
  // and lifted 0.6/16 so its size, weight and centre line match the font
  // glyphs beside it (those sit a little above the canvas centre).
  Component {
    id: syncIcon

    Item {
      id: syncGlyph
      readonly property color tint: button.active && button.useActiveColor ? button.activeColor : button.foreground
      readonly property real drawSize: height * 13 / 16

      Shape {
        id: syncShape
        width: 24
        height: 24
        x: (syncGlyph.width - syncGlyph.drawSize) / 2
        y: (syncGlyph.height - syncGlyph.drawSize) / 2 - syncGlyph.height * 0.6 / 16
        scale: syncGlyph.drawSize / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
          fillColor: syncGlyph.tint
          strokeColor: "transparent"
          strokeWidth: -1
          PathSvg { path: "M2.25 14.75V4.75h15.23l-2.25-2.25L17 .73l6.52 6.52H4.75v7.5zM21.75 9.25v10H6.52l2.25 2.25L7 23.27.48 16.75h18.77v-7.5zM12 9.25h5.5v5.5H12z" }
        }
      }

      // Waiting for the user's reply: the same icon in the bar's active
      // colour, plus a dot just outside its top-right corner.
      Rectangle {
        visible: root.waiting
        x: syncShape.x + syncGlyph.drawSize - 1
        y: syncShape.y - 2
        width: 4
        height: 4
        radius: 2
        color: syncGlyph.tint
      }
    }
  }
}
