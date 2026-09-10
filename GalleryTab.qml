import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Library grid with search/filter/sort, a hover preview pane and an import row.
Item {
  id: tab
  property var overlay: null
  readonly property var service: overlay ? overlay.service : null
  readonly property var library: overlay ? overlay.library : []
  readonly property color foreground: overlay ? overlay.foreground : Color.foreground
  readonly property color accent: overlay ? overlay.accent : Color.accent
  readonly property color muted: overlay ? overlay.muted : Color.muted
  readonly property color selectedBackground: overlay ? overlay.selectedBackground : Color.menu.selectedBackground

  property string search: ""
  property string filter: "all"
  property string sortKey: "added"
  property bool importOpen: false
  property var previewItem: null
  // The grid's model is a list of piece ids that only changes when the
  // membership/order changes; card data comes from `byId`, so toggling
  // enabled/favourite refreshes cards in place without resetting the scroll.
  readonly property var byId: {
    var m = {}
    for (var i = 0; i < tab.library.length; i++) m[tab.library[i].id] = tab.library[i]
    return m
  }
  readonly property var filtered: Model.filterLibrary(tab.library, tab.search, tab.filter, tab.sortKey)
  property var rows: []
  property string rowsKey: ""
  onFilteredChanged: refreshRows()
  function refreshRows() {
    var ids = tab.filtered.map(function(p) { return p.id })
    var key = ids.join("\n")
    if (key === tab.rowsKey) return
    var sameLength = ids.length === tab.rows.length
    var y = grid.contentY, idx = grid.currentIndex
    tab.rowsKey = key
    tab.rows = ids
    if (sameLength || tab.rows.length > 0) Qt.callLater(function() { grid.contentY = Math.min(y, Math.max(0, grid.contentHeight - grid.height)); grid.currentIndex = Math.min(idx, tab.rows.length - 1) })
  }
  readonly property var current: (grid.currentIndex >= 0 && grid.currentIndex < rows.length) ? (tab.byId[rows[grid.currentIndex]] || null) : null
  readonly property var shown: previewItem ? (tab.byId[previewItem.id] || previewItem) : current

  function onShown() {}
  function focusSearch() { searchField.forceActiveFocus() }
  function onEscape() {
    if (tab.search !== "") { searchField.text = ""; return true }
    if (tab.importOpen) { tab.importOpen = false; return true }
    return false
  }
  function move(delta) {
    if (tab.rows.length === 0) return
    grid.currentIndex = Math.max(0, Math.min(tab.rows.length - 1, grid.currentIndex + delta))
    grid.positionViewAtIndex(grid.currentIndex, GridView.Contain)
  }
  function columns() { return Math.max(1, Math.floor(grid.width / grid.cellWidth)) }
  function preview(p) {
    if (!p || !tab.service) return
    tab.service.runCli(["preview", p.id], { reloadAfter: false })
    if (tab.overlay) { tab.overlay.status("previewing " + p.title); tab.overlay.dismiss() }
  }
  function toggleEnabled(p) { if (p && tab.service) { tab.service.libraryAction(p.enabled ? "disable" : "enable", p.id); tab.overlay.status((p.enabled ? "disabled " : "enabled ") + p.title) } }
  function toggleFavorite(p) { if (p && tab.service) { tab.service.libraryAction(p.favorite ? "unfavorite" : "favorite", p.id); tab.overlay.status((p.favorite ? "unstarred " : "starred ") + p.title) } }
  function remove(p) {
    if (!p || !tab.overlay) return
    var doRemove = function() {
      tab.service.libraryAction("remove", p.id)
      tab.overlay.status("removed " + p.title)
      if (tab.previewItem && tab.previewItem.id === p.id) tab.previewItem = null
    }
    if (Model.get(tab.overlay.config, "confirm_remove", true) === false) doRemove()
    else tab.overlay.confirm("Remove “" + p.title + "” from the library?", doRemove)
  }
  function handleKey(event) {
    var k = event.key
    if (k === Qt.Key_Left || k === Qt.Key_H) { tab.move(-1); event.accepted = true }
    else if (k === Qt.Key_Right || k === Qt.Key_L) { tab.move(1); event.accepted = true }
    else if (k === Qt.Key_Up || k === Qt.Key_K) { tab.move(-tab.columns()); event.accepted = true }
    else if (k === Qt.Key_Down || k === Qt.Key_J) { tab.move(tab.columns()); event.accepted = true }
    else if (k === Qt.Key_PageDown) { tab.move(tab.columns() * 3); event.accepted = true }
    else if (k === Qt.Key_PageUp) { tab.move(-tab.columns() * 3); event.accepted = true }
    else if (k === Qt.Key_Home) { grid.currentIndex = 0; grid.positionViewAtBeginning(); event.accepted = true }
    else if (k === Qt.Key_End) { grid.currentIndex = tab.rows.length - 1; grid.positionViewAtEnd(); event.accepted = true }
    else if (k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space) { tab.preview(tab.current); event.accepted = true }
    else if (k === Qt.Key_E) { tab.toggleEnabled(tab.current); event.accepted = true }
    else if (k === Qt.Key_F) { tab.toggleFavorite(tab.current); event.accepted = true }
    else if (k === Qt.Key_Delete) { tab.remove(tab.current); event.accepted = true }
    else if (k === Qt.Key_Slash) { tab.focusSearch(); event.accepted = true }
    else if (event.text && event.text.length === 1 && event.text >= " " && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) {
      searchField.forceActiveFocus(); searchField.text += event.text; event.accepted = true
    }
  }

  Column {
    anchors.fill: parent
    spacing: Style.spacing.sm

    // ---- toolbar ----------------------------------------------------------
    Row {
      id: toolbar
      width: parent.width
      spacing: Style.spacing.controlGap

      TextField {
        id: searchField
        width: Style.space(220)
        placeholderText: "search title, author, group, tags…"
        foreground: tab.foreground
        accent: tab.accent
        onTextChanged: { tab.search = text; Qt.callLater(function() { grid.currentIndex = 0; grid.positionViewAtBeginning() }) }
        Keys.onDownPressed: tab.move(tab.columns())
        Keys.onUpPressed: tab.move(-tab.columns())
        Keys.onReturnPressed: { if (tab.overlay) tab.overlay.focusKeys() }
        Keys.onEscapePressed: function(event) { if (text !== "") text = ""; else if (tab.overlay) tab.overlay.dismiss(); event.accepted = true }
      }
      ButtonGroup {
        anchors.verticalCenter: parent.verticalCenter
        options: [{ value: "all", label: "All" }, { value: "enabled", label: "Enabled" }, { value: "disabled", label: "Disabled" },
                  { value: "favorites", label: "★" }, { value: "ansi", label: "ANSI" }, { value: "ascii", label: "ASCII" }]
        value: tab.filter
        foreground: tab.foreground; accent: tab.accent
        onChanged: function(v) { tab.filter = v; Qt.callLater(function() { grid.currentIndex = 0; grid.positionViewAtBeginning() }) }
      }
      Dropdown {
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(130)
        showLabel: false
        value: tab.sortKey
        options: [{ value: "added", label: "newest" }, { value: "title", label: "title" }, { value: "author", label: "author" },
                  { value: "year", label: "year" }, { value: "size", label: "height" }, { value: "rating", label: "rating" }]
        onChanged: function(v) { tab.sortKey = v }
      }
      Button {
        anchors.verticalCenter: parent.verticalCenter
        text: "Import…"; bordered: true; selected: tab.importOpen; fontSize: Style.font.caption
        foreground: tab.foreground; accent: tab.accent
        onClicked: { tab.importOpen = !tab.importOpen; if (tab.importOpen) importField.forceActiveFocus() }
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: tab.rows.length + " shown"
        color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
      }
    }

    // ---- import row ---------------------------------------------------------
    Row {
      width: parent.width
      visible: tab.importOpen
      height: visible ? implicitHeight : 0
      spacing: Style.spacing.controlGap
      TextField {
        id: importField
        width: parent.width - pickButton.width - importButton.width - Style.spacing.controlGap * 2
        placeholderText: "file, folder, zip or URL (.ans .asc .txt .zip, 16colo.rs archive links…)"
        foreground: tab.foreground; accent: tab.accent
        Keys.onReturnPressed: tab.runImport(text)
        Keys.onEscapePressed: function(event) { tab.importOpen = false; event.accepted = true }
      }
      Button { id: pickButton; text: "Pick…"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: picker.running = true }
      Button { id: importButton; text: "Import"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: tab.runImport(importField.text) }
    }

    // ---- grid + preview -------------------------------------------------------
    Row {
      width: parent.width
      height: parent.height - toolbar.height - (tab.importOpen ? importField.height + Style.spacing.sm : 0) - Style.spacing.sm
      spacing: Style.spacing.panelGap

      GridView {
        id: grid
        width: parent.width - previewPane.width - Style.spacing.panelGap
        height: parent.height
        clip: true
        cellWidth: Style.space(226)
        cellHeight: Style.space(224)
        cacheBuffer: cellHeight * 2
        boundsBehavior: Flickable.StopAtBounds
        model: tab.rows
        currentIndex: 0
        delegate: ArtCard {}

        Text {
          anchors.centerIn: parent
          visible: tab.rows.length === 0
          text: tab.library.length === 0 ? "The library is empty — seed the bundled art or import some pieces." : "Nothing matches."
          color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.body
        }
      }

      // preview pane
      Item {
        id: previewPane
        width: Style.space(360)
        height: parent.height
        Column {
          anchors.fill: parent
          spacing: Style.spacing.sm
          Rectangle {
            width: parent.width
            height: parent.height * 0.62
            color: "#000000"
            radius: Style.cornerRadius
            clip: true
            Image {
              anchors.fill: parent
              anchors.margins: Style.spacing.xs
              source: tab.shown && tab.shown.render ? Model.fileUrl(tab.shown.render) : ""
              asynchronous: true
              cache: true
              fillMode: Image.PreserveAspectFit
              verticalAlignment: Image.AlignTop
              sourceSize.width: Math.round(width * Screen.devicePixelRatio)
              smooth: true
            }
            Text {
              anchors.centerIn: parent
              visible: !tab.shown || !tab.shown.render
              text: tab.shown ? "no render yet (thumbnails need Pillow)" : "hover or select a piece"
              color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
            }
          }
          Text { width: parent.width; text: tab.shown ? tab.shown.title : ""; color: tab.foreground; font.family: Style.font.menuFamily; font.pixelSize: Style.font.title; elide: Text.ElideRight }
          Text { width: parent.width; text: tab.shown ? Model.credits(tab.shown) : ""; color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.body; elide: Text.ElideRight }
          Text {
            width: parent.width; wrapMode: Text.WordWrap
            text: tab.shown ? (tab.shown.cols + "×" + tab.shown.rows + " · " + tab.shown.format + (tab.shown.animated ? " · animated" : "") + " · " + (tab.shown.encoding || "")
                   + (tab.shown.pack ? " · " + tab.shown.pack : "") + (tab.shown.source ? " · " + tab.shown.source : "")
                   + (tab.shown.tags && tab.shown.tags.length ? "\n" + tab.shown.tags.join(", ") : "")
                   + (tab.shown.warnings && tab.shown.warnings.length ? "\n⚠ " + tab.shown.warnings.join("; ") : "")) : ""
            color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
          }
          Flow {
            width: parent.width
            spacing: Style.spacing.xs
            visible: !!tab.shown
            Button { text: "▶ Preview"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: tab.preview(tab.shown) }
            Button { text: tab.shown && tab.shown.enabled ? "Disable" : "Enable"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: tab.toggleEnabled(tab.shown) }
            Button { text: tab.shown && tab.shown.favorite ? "★ Unstar" : "☆ Star"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: tab.toggleFavorite(tab.shown) }
            Button { text: "Remove"; bordered: true; fontSize: Style.font.caption; foreground: Color.urgent; accent: Color.urgent; onClicked: tab.remove(tab.shown) }
          }
        }
      }
    }
  }

  // ---- helpers ------------------------------------------------------------------
  function runImport(target) {
    var t = String(target || "").trim()
    if (t === "" || !tab.service) return
    tab.service.startJob("import", ["import", t])
    tab.overlay.status("importing " + t)
    importField.text = ""
  }

  Process {
    id: picker
    command: ["omarchy-file-select", "--multiple"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var lines = String(text || "").trim().split("\n").filter(function(l) { return l.trim() !== "" })
        if (lines.length > 0 && tab.service) {
          tab.service.startJob("import", ["import"].concat(lines))
          tab.overlay.status("importing " + lines.length + " file(s)")
        }
      }
    }
  }

  Timer { id: hoverTimer; interval: 300; property var candidate: null; onTriggered: tab.previewItem = candidate }

  component ArtCard: Item {
    id: cardRoot
    required property string modelData
    required property int index
    readonly property var piece: tab.byId[modelData] || ({ id: modelData, title: modelData, enabled: true, favorite: false, format: "ansi", thumb: null })
    readonly property bool current: grid.currentIndex === index
    width: grid.cellWidth
    height: grid.cellHeight

    Rectangle {
      anchors.fill: parent
      anchors.margins: Style.spacing.xs
      radius: Style.cornerRadius
      color: cardRoot.current ? tab.selectedBackground : "transparent"
      border.width: cardRoot.current ? Math.max(1, Style.space(1)) : 0
      border.color: tab.accent

      Column {
        anchors.fill: parent
        anchors.margins: Style.spacing.sm
        spacing: Style.spacing.xxs

        Rectangle {
          width: parent.width
          height: parent.height - titleText.height - creditText.height - actionRow.height - Style.spacing.xxs * 3
          color: "#000000"
          radius: Style.cornerRadius / 2
          clip: true
          opacity: cardRoot.piece.enabled ? 1 : 0.35
          Image {
            anchors.fill: parent
            anchors.margins: Style.spacing.xxs
            source: cardRoot.piece.thumb ? Model.fileUrl(cardRoot.piece.thumb) : ""
            asynchronous: true
            cache: true
            fillMode: Image.PreserveAspectFit
            verticalAlignment: Image.AlignTop
            sourceSize.width: Math.round(width * Screen.devicePixelRatio)
            smooth: true
          }
          Text {
            anchors.centerIn: parent
            visible: !cardRoot.piece.thumb
            text: cardRoot.piece.format.toUpperCase()
            color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
          }
          Text {
            anchors.top: parent.top; anchors.left: parent.left; anchors.margins: Style.spacing.xxs
            text: cardRoot.piece.format === "ansi" ? "ANSI" : "ASCII"
            color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
          }
          Text {
            anchors.top: parent.top; anchors.right: parent.right; anchors.margins: Style.spacing.xxs
            text: cardRoot.piece.favorite ? "★" : (hover.containsMouse ? "☆" : "")
            color: cardRoot.piece.favorite ? tab.accent : tab.muted
            font.pixelSize: Style.font.title
            MouseArea { anchors.fill: parent; onClicked: tab.toggleFavorite(cardRoot.piece) }
          }
          Text {
            anchors.bottom: parent.bottom; anchors.right: parent.right; anchors.margins: Style.spacing.xxs
            visible: !cardRoot.piece.enabled
            text: "off"
            color: Color.urgent; font.family: Style.font.family; font.pixelSize: Style.font.caption
          }
        }
        Text { id: titleText; width: parent.width; text: cardRoot.piece.title; color: tab.foreground; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall; elide: Text.ElideRight }
        Text { id: creditText; width: parent.width; text: Model.credits(cardRoot.piece); color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption; elide: Text.ElideRight }

        // quick actions, always visible: preview · star · enable · remove
        Row {
          id: actionRow
          width: parent.width
          height: Style.space(22)
          spacing: Style.spacing.xs
          PanelActionButton {
            iconText: "▶"; tooltipText: "preview on screen"; size: Style.space(22); fontSize: Style.font.bodySmall
            foreground: tab.muted; hoverColor: tab.accent
            onClicked: tab.preview(cardRoot.piece)
          }
          PanelActionButton {
            iconText: cardRoot.piece.favorite ? "★" : "☆"; tooltipText: cardRoot.piece.favorite ? "unstar" : "star (favourites play more often)"
            size: Style.space(22); fontSize: Style.font.body
            foreground: cardRoot.piece.favorite ? tab.accent : tab.muted; hoverColor: tab.accent
            onClicked: tab.toggleFavorite(cardRoot.piece)
          }
          PanelActionButton {
            iconText: cardRoot.piece.enabled ? "●" : "○"; tooltipText: cardRoot.piece.enabled ? "enabled — click to skip in the slideshow" : "disabled — click to enable"
            size: Style.space(22); fontSize: Style.font.bodySmall
            foreground: cardRoot.piece.enabled ? tab.foreground : Color.urgent; hoverColor: tab.accent
            onClicked: tab.toggleEnabled(cardRoot.piece)
          }
          Item { width: parent.width - Style.space(22) * 4 - Style.spacing.xs * 4; height: 1 }
          PanelActionButton {
            iconText: "✕"; tooltipText: "remove from the library"; size: Style.space(22); fontSize: Style.font.bodySmall
            foreground: tab.muted; hoverColor: Color.urgent
            onClicked: tab.remove(cardRoot.piece)
          }
        }
      }

      MouseArea {
        id: hover
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        z: -1
        onClicked: function(mouse) {
          grid.currentIndex = cardRoot.index
          if (mouse.button === Qt.RightButton) tab.toggleEnabled(cardRoot.piece)
        }
        onDoubleClicked: tab.preview(cardRoot.piece)
        onEntered: { hoverTimer.candidate = cardRoot.piece; hoverTimer.restart() }
        onExited: hoverTimer.stop()
      }
    }
  }
}
