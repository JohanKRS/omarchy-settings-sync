pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Io
import qs.Commons as Commons
import qs.Ui as Ui

// The bar widget itself. BarWidget.qml, the entry point the shell loads,
// creates it and passes itself as `widget`; see that file for why.
Item {
  id: root
  required property Ui.BarWidget widget
  readonly property string language: (Quickshell.env("AGENT_SETTINGS_LANGUAGE") || Quickshell.env("LANGUAGE") || Quickshell.env("LC_ALL") || Quickshell.env("LC_MESSAGES") || Quickshell.env("LANG") || "en").substring(0, 2)
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  property var attention: ({})
  property real now: Date.now()
  readonly property var hostWindow: button.QsWindow.window
  readonly property var hostBar: root.widget.bar
  readonly property bool fresh: now / 1000 - (attention.updated || 0) < 30
  readonly property bool waiting: attention.waiting === true && fresh
  readonly property bool opened: attention.opened === true && fresh
    && (!attention.monitor || (hostWindow && hostWindow.screen && attention.monitor === hostWindow.screen.name))
  // How the last task ended while the panel was hidden: "done" or "failed".
  // Not a heartbeat: the panel clears it when it is shown, so it stays while
  // the panel's process is closed.
  readonly property string finished: waiting || opened ? ""
    : attention.finished === "done" || attention.finished === "failed" ? attention.finished : ""
  // A question or a failure needs you; a finished task only waits for you.
  readonly property bool needsYou: waiting || finished === "failed"
  readonly property string statusText: {
    var texts = root.language === "pt"
      ? ["Aguardando sua resposta · clique para abrir", "A tarefa parou com um erro · clique para ver",
         "Tarefa concluída · clique para ver", "Clique para abrir"]
      : root.language === "es"
      ? ["Esperando tu respuesta · clic para abrir", "La tarea se detuvo con un error · clic para ver",
         "Tarea terminada · clic para ver", "Clic para abrir"]
      : ["Waiting for your reply · click to open", "The task stopped with an error · click to see",
         "Task finished · click to see", "Click to open"]
    return texts[root.waiting ? 0 : root.finished === "failed" ? 1 : root.finished === "done" ? 2 : 3]
  }

  function open() { launch("") }
  function close() { launch("--hide") }
  function toggle() { launch("--toggle") }

  // The bar knows the widget, not this item: it owns the popout.
  onOpenedChanged: {
    if (!root.hostBar) return
    if (root.opened) root.hostBar.requestPopout(root.widget)
    else root.hostBar.releasePopout(root.widget)
  }
  Component.onDestruction: {
    if (root.opened) root.close()
    if (root.hostBar) root.hostBar.releasePopout(root.widget)
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
    command.push("--bar-size=" + root.widget.barSize)
    if (action) command.push(action)
    Quickshell.execDetached(command)
  }

  Ui.BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.widget.bar
    iconComponent: syncIcon
    active: root.needsYou
    tooltipText: "Omarchy Settings Sync\n" + root.statusText
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton) {
        if (root.waiting || root.finished !== "") root.open()
        else root.toggle()
      }
    }
  }

  // Plugin icon: the square toggle knob inside a sync loop, drawn as a
  // vector so it follows the bar colour. BarIconButton loads it into its
  // 16 px optical canvas in place of a font glyph.
  //
  // The bar's other icons are hinted font glyphs: their 1 px strokes sit on
  // whole pixels. This draws plugin/icons/omarchy-settings-sync-symbolic.svg
  // at 12/16 of the canvas, where its 2-unit strokes are exactly one logical
  // pixel like theirs, and snaps it to the device pixel grid so the edges
  // stay as crisp. It is lifted to the glyphs' slightly raised centre line.
  Component {
    id: syncIcon

    Item {
      id: syncGlyph
      readonly property color tint: button.active && button.useActiveColor ? button.activeColor : button.foreground
      readonly property real dpr: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1
      readonly property real drawSize: height * 12 / 16

      function place() {
        var origin = syncGlyph.mapToItem(null, 0, 0)
        var left = (width - drawSize) / 2
        var top = (height - drawSize) / 2 - Math.round(height / 16)
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
        width: 24
        height: 24
        scale: syncGlyph.drawSize / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.GeometryRenderer
        antialiasing: true

        ShapePath {
          fillColor: syncGlyph.tint
          strokeColor: "transparent"
          strokeWidth: -1
          PathSvg { path: "M2.25 14.75V4.75h15.23l-2.25-2.25L17 .73l6.52 6.52H4.75v7.5zM21.75 9.25v10H6.52l2.25 2.25L7 23.27.48 16.75h18.77v-7.5zM12 9.25h5.5v5.5H12z" }
        }
      }

      // Marks just outside the icon's top-right corner. They are parented
      // beside the icon rather than inside it, in the same coordinates, so
      // that Omarchy, which fits an icon by the bounds of what it paints,
      // keeps the icon the same size and place when one appears.

      // A question or a failure needs you: the same icon in the bar's active
      // colour, plus a dot.
      Rectangle {
        parent: syncGlyph.parent
        visible: root.needsYou
        x: syncShape.x + syncGlyph.drawSize - 1
        y: syncShape.y - 2
        width: 4
        height: 4
        radius: 2
        color: syncGlyph.tint
      }

      // The task finished and the agent waits for you: a check in the
      // theme's accent colour, the colour of the bar's open-panel mark.
      Shape {
        parent: syncGlyph.parent
        visible: root.finished === "done"
        x: syncShape.x + syncGlyph.drawSize - 0.5
        y: syncShape.y - 3.5
        width: 6
        height: 5
        preferredRendererType: Shape.GeometryRenderer
        antialiasing: true

        ShapePath {
          fillColor: "transparent"
          strokeColor: Commons.Color.accent
          strokeWidth: 1.75
          capStyle: ShapePath.FlatCap
          joinStyle: ShapePath.MiterJoin
          PathSvg { path: "M0.75 2.5L2.5 4.25L5.5 1.25" }
        }
      }
    }
  }
}
