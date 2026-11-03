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
  // The bar draws its other icons from a hinted font, so their edges sit on
  // whole screen pixels. This version of plugin/icons/omarchy-settings-sync-symbolic.svg
  // is drawn on a coarse grid whose unit is a whole number of physical
  // pixels, and its origin is snapped to the pixel grid, so its strokes are
  // as crisp as the glyphs beside it. It is 9 x 8 units, about the size of
  // those glyphs, and sits on their slightly raised centre line.
  Component {
    id: syncIcon

    Item {
      id: syncGlyph
      readonly property color tint: button.active && button.useActiveColor ? button.activeColor : button.foreground
      readonly property real dpr: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1
      // One grid unit in physical pixels; 10 units span about 12/16 of the canvas.
      readonly property int unit: Math.max(1, Math.round(height * 12 / 16 * dpr / 10))
      readonly property real step: unit / dpr
      readonly property real lift: Math.round(height * 0.9 / 16 * dpr) / dpr

      function px(x, y) { return (x * unit) + " " + (y * unit) }

      function place() {
        // Centre the 9 x 8 unit drawing (x 0.5-9.5, y 1-9), then snap to physical pixels.
        var origin = syncGlyph.mapToItem(null, 0, 0)
        var left = width / 2 - 5 * step
        var top = height / 2 - 5 * step - lift
        syncShape.x = Math.round((origin.x + left) * dpr) / dpr - origin.x
        syncShape.y = Math.round((origin.y + top) * dpr) / dpr - origin.y
      }

      onWidthChanged: place()
      onHeightChanged: place()
      Component.onCompleted: place()

      Timer {
        // The bar may still be laying out when the icon first loads.
        interval: 300
        running: true
        onTriggered: syncGlyph.place()
      }

      Shape {
        id: syncShape
        width: 10 * syncGlyph.unit
        height: 10 * syncGlyph.unit
        scale: 1 / syncGlyph.dpr
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.GeometryRenderer
        antialiasing: true

        ShapePath {
          fillColor: syncGlyph.tint
          strokeColor: "transparent"
          strokeWidth: -1
          PathSvg {
            path: "M" + syncGlyph.px(0.5, 7) + "L" + syncGlyph.px(0.5, 2) + "L" + syncGlyph.px(8, 2) + "L" + syncGlyph.px(8, 3)
                  + "L" + syncGlyph.px(1.5, 3) + "L" + syncGlyph.px(1.5, 7) + "Z"
                  + "M" + syncGlyph.px(8, 1) + "L" + syncGlyph.px(9.5, 2.5) + "L" + syncGlyph.px(8, 4) + "Z"
                  + "M" + syncGlyph.px(9.5, 3) + "L" + syncGlyph.px(9.5, 8) + "L" + syncGlyph.px(2, 8) + "L" + syncGlyph.px(2, 7)
                  + "L" + syncGlyph.px(8.5, 7) + "L" + syncGlyph.px(8.5, 3) + "Z"
                  + "M" + syncGlyph.px(2, 6) + "L" + syncGlyph.px(0.5, 7.5) + "L" + syncGlyph.px(2, 9) + "Z"
                  + "M" + syncGlyph.px(5, 4) + "L" + syncGlyph.px(7, 4) + "L" + syncGlyph.px(7, 6) + "L" + syncGlyph.px(5, 6) + "Z"
          }
        }
      }

      // Waiting for the user's reply: the same icon in the bar's active
      // colour, plus a dot just outside its top-right corner.
      Rectangle {
        visible: root.waiting
        x: syncShape.x + 9.5 * syncGlyph.step - 1
        y: syncShape.y + syncGlyph.step - 3
        width: 4
        height: 4
        radius: 2
        color: syncGlyph.tint
      }
    }
  }
}
