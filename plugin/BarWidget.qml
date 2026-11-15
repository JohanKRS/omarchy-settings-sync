pragma ComponentBehavior: Bound
import QtQuick
import Quickshell.Io
import qs.Ui as Ui

// The entry point the shell loads. Keep this file the same in every release:
// the widget itself is in BarWidgetContent.qml.
//
// The shell compiles a plugin's widget file once per session. When the
// plugin's files change it builds the widget again, but from that compiled
// copy, which Quickshell offers no way to drop. A change here therefore shows
// only after the shell restarts. This file loads the real widget at a URL that
// changes with BarWidgetContent.qml's content, so each new version of that
// file is compiled again and an update shows on the bar at once.
Ui.BarWidget {
  id: root
  moduleName: "community.agent-settings"
  implicitWidth: content.item ? content.item.implicitWidth : 0
  implicitHeight: content.item ? content.item.implicitHeight : 0

  readonly property url contentUrl: Qt.resolvedUrl("BarWidgetContent.qml")
  property string revision: ""

  // What the bar and the shell's summon, hide and toggle use.
  readonly property bool opened: content.item ? content.item.opened : false
  readonly property bool popoutSwitchClosing: false
  function open() { if (content.item) content.item.open() }
  function close() { if (content.item) content.item.close() }
  function toggle() { if (content.item) content.item.toggle() }
  function closeForPopoutSwitch() { close() }

  function digest(text) {
    var hash = 5381
    for (var i = 0; i < text.length; i++) hash = (hash * 33 + text.charCodeAt(i)) | 0
    return (hash >>> 0).toString(16) + "-" + text.length
  }

  function load() {
    var text = contentFile.text()
    // Mid-update the file can be missing or empty: keep what is loaded.
    if (!text) return
    var revision = root.digest(text)
    if (revision === root.revision) return
    root.revision = revision
    content.setSource(root.contentUrl + "?revision=" + revision, { widget: root })
  }

  FileView {
    id: contentFile
    path: decodeURIComponent(root.contentUrl.toString().replace(/^file:\/\//, ""))
    blockLoading: true
    watchChanges: true
    printErrors: false
    // Read the new file once the update has finished writing it.
    onFileChanged: settle.restart()
    onLoaded: root.load()
  }

  Timer {
    id: settle
    interval: 300
    onTriggered: contentFile.reload()
  }

  Loader {
    id: content
    anchors.fill: parent
  }

  Component.onCompleted: load()
}
