import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// One tree browser for every art source (16colo.rs, Demozoo, archives, HTML
// galleries…). The engine's `browse` contract makes them all look alike:
// collections (folders/packs) and items (pieces) with a thumbnail, a text
// preview, or an on-demand render.
Item {
  id: tab
  property var overlay: null
  readonly property var service: overlay ? overlay.service : null
  readonly property var sources: service ? service.sources : []
  readonly property var library: overlay ? overlay.library : []
  readonly property color foreground: overlay ? overlay.foreground : Color.foreground
  readonly property color accent: overlay ? overlay.accent : Color.accent
  readonly property color muted: overlay ? overlay.muted : Color.muted
  readonly property color selectedBackground: overlay ? overlay.selectedBackground : Color.menu.selectedBackground

  property string sourceId: ""
  property var pathSegs: []
  property var crumbs: []
  property string search: ""
  property int page: 1
  property var entries: []
  property var listing: null
  property bool busy: false
  property bool addOpen: false
  property string addKind: "github_repo"
  property int browseSeq: 0
  property var pageCache: ({})
  property var previewCache: ({})
  // Per-item UI state lives in side maps so the grid's model array (and with
  // it the scroll position) is never replaced just to mark one card.
  property var addingIds: ({})
  property var localPngs: ({})
  property var thumbFailed: ({})
  property var previewQueue: []
  property bool previewing: false
  property int previewTotal: 0
  function needsPreview(e) {
    return e.type === "item" && !e.text_preview && !tab.localPngs[tab.sourceId + "|" + e.id]
      && (!e.thumb_url || !!tab.thumbFailed[e.id])
  }
  readonly property int previewable: { var n = 0; for (var i = 0; i < tab.entries.length; i++) if (tab.needsPreview(tab.entries[i])) n++; return n }
  function markThumbFailed(id) { var m = Object.assign({}, tab.thumbFailed); m[id] = true; tab.thumbFailed = m }
  // "Preview all": render every item on this page that has no picture, one
  // at a time (each is a download from the remote endpoint).
  function previewAll() {
    var q = []
    for (var i = 0; i < tab.entries.length; i++) if (tab.needsPreview(tab.entries[i])) q.push(tab.entries[i])
    if (q.length === 0) { tab.status("nothing to preview"); return }
    tab.previewQueue = q
    tab.previewTotal = q.length
    tab.previewing = true
    tab.nextPreview()
  }
  function stopPreviewAll() { tab.previewQueue = []; tab.previewing = false; tab.status("preview all stopped") }
  function nextPreview() {
    if (!tab.previewing) return
    if (tab.previewQueue.length === 0) { tab.previewing = false; tab.status("previews done"); return }
    var q = tab.previewQueue.slice(); var entry = q.shift(); tab.previewQueue = q
    tab.status("previewing " + (tab.previewTotal - q.length) + "/" + tab.previewTotal + " · " + entry.label)
    tab.renderPreview(entry, tab.nextPreview, tab.nextPreview)
  }
  function renderPreview(entry, onOk, onFail) {
    var key = tab.sourceId + "|" + entry.id
    if (tab.previewCache[key]) { if (onOk) onOk(); return }
    var mySource = tab.sourceId
    tab.service.runCli(["preview", "--source", mySource, "--entry", entry.id, "--json"], { reloadAfter: false, onDone: function(rc, out) {
      try {
        var res = JSON.parse(out)
        if (res.error) { if (onFail) onFail(); return }
        var c = tab.previewCache; c[key] = res; tab.previewCache = c
        if (res.png) { var m = Object.assign({}, tab.localPngs); m[key] = res.png; tab.localPngs = m }
        if (onOk) onOk()
      } catch (err) { if (onFail) onFail() }
    } })
  }
  readonly property var source: {
    for (var i = 0; i < tab.sources.length; i++) if (tab.sources[i].id === tab.sourceId) return tab.sources[i]
    return null
  }
  readonly property var current: (grid.currentIndex >= 0 && grid.currentIndex < entries.length) ? entries[grid.currentIndex] : null

  function onShown() {
    var nav = tab.overlay ? tab.overlay.pendingNavigate : null
    if (nav) { tab.overlay.pendingNavigate = null; tab.navigateTo(nav.source, nav.path || []); return }
    if (tab.sourceId === "" && tab.sources.length > 0) tab.selectSource(tab.sources[0].id)
  }
  function navigateTo(sourceId, path) {
    tab.sourceId = sourceId
    tab.search = ""
    searchField.text = ""
    tab.browse(path || [], "", 1, false)
  }
  function onEscape() {
    if (tab.search !== "") { searchField.text = ""; return true }
    if (tab.pathSegs.length > 0) { tab.up(); return true }
    return false
  }
  function focusSearch() { searchField.forceActiveFocus() }
  function status(msg) { if (tab.overlay) tab.overlay.status(msg) }

  function selectSource(id) {
    tab.sourceId = id
    tab.pathSegs = []
    tab.search = ""
    searchField.text = ""
    tab.browse([], "", 1, false)
  }
  function cacheKey(src, segs, q, pg) { return src + "|" + segs.join("/") + "|" + q + "|" + pg }
  function browse(segs, q, pg, append) {
    if (!tab.service || tab.sourceId === "") return
    var key = tab.cacheKey(tab.sourceId, segs, q, pg)
    tab.pathSegs = segs
    tab.page = pg
    var cached = tab.pageCache[key]
    if (cached) { tab.applyListing(cached, append); return }
    tab.busy = true
    var seq = ++tab.browseSeq
    var args = ["browse", "--source", tab.sourceId]
    for (var i = 0; i < segs.length; i++) args.push("--path", segs[i])
    if (q) args.push("--search", q)
    args.push("--page", String(pg), "--json")
    var mySource = tab.sourceId
    tab.service.runCli(args, { reloadAfter: false, onDone: function(rc, out) {
      if (seq !== tab.browseSeq) return            // superseded by a later navigation
      tab.busy = false
      if (mySource !== tab.sourceId) return
      var listing = null
      try { listing = JSON.parse(out) } catch (e) { tab.status("browse failed: " + String(out).slice(0, 120)); return }
      if (listing && listing.error) { tab.status(listing.error); return }
      var cache = tab.pageCache; cache[key] = listing; tab.pageCache = cache
      tab.applyListing(listing, append)
    } })
  }
  function applyListing(listing, append) {
    tab.listing = listing
    tab.crumbs = listing.breadcrumbs || []
    var list = listing.entries || []
    if (append) {
      var y = grid.contentY, idx = grid.currentIndex
      tab.entries = tab.entries.concat(list)
      Qt.callLater(function() { grid.contentY = y; grid.currentIndex = idx })
    } else {
      tab.entries = list
      grid.currentIndex = 0
      grid.positionViewAtBeginning()
    }
    if (listing.notice) tab.status(listing.notice)
  }
  function setAdding(id, on) {
    var m = Object.assign({}, tab.addingIds)
    if (on) m[id] = true; else delete m[id]
    tab.addingIds = m
  }
  function enter(entry) {
    if (!entry) return
    if (entry.type === "collection") { tab.browse(tab.pathSegs.concat([entry.id]), "", 1, false); return }
    tab.previewEntry(entry)
  }
  function up() { if (tab.pathSegs.length > 0) tab.browse(tab.pathSegs.slice(0, -1), "", 1, false) }
  function loadMore() { if (tab.listing && tab.listing.next_page) tab.browse(tab.pathSegs, tab.search, tab.listing.next_page, true) }
  function libraryIdFor(entry) { return Model.libraryHas(tab.library, tab.sourceId, entry.id, entry.source_url) }
  function add(entry) {
    if (!entry || !tab.service) return
    if (entry.type === "collection") {
      if (!entry.can_add_all) { tab.enter(entry); return }
      tab.overlay.confirm("Add every piece in “" + entry.label + "” to the library?", function() {
        tab.status(tab.service.startJob("add " + entry.label, ["add", "--source", tab.sourceId, "--entry", entry.id, "--all"]))
      })
      return
    }
    if (tab.libraryIdFor(entry)) { tab.status("already in the library"); return }
    if (tab.addingIds[entry.id]) return
    tab.setAdding(entry.id, true)
    tab.status("adding " + entry.label + "…")
    tab.service.runCli(["add", "--source", tab.sourceId, "--entry", entry.id, "--json"], { onDone: function(rc, out) {
      tab.setAdding(entry.id, false)
      tab.status(rc === 0 ? "added " + entry.label : "add failed: " + String(out).slice(0, 100))
    } })
  }
  function previewEntry(entry) {
    if (!entry || entry.type !== "item" || !tab.service) return
    var key = tab.sourceId + "|" + entry.id
    if (tab.previewCache[key]) { tab.previewItem = Object.assign({}, entry, tab.previewCache[key]); return }
    tab.status("rendering preview…")
    tab.renderPreview(entry,
      function() { tab.previewItem = Object.assign({}, entry, tab.previewCache[key]); tab.status("") },
      function() { tab.status("preview failed for " + entry.label) })
  }
  property var previewItem: null
  function move(delta) {
    if (tab.entries.length === 0) return
    grid.currentIndex = Math.max(0, Math.min(tab.entries.length - 1, grid.currentIndex + delta))
    grid.positionViewAtIndex(grid.currentIndex, GridView.Contain)
  }
  function columns() { return Math.max(1, Math.floor(grid.width / grid.cellWidth)) }
  function handleKey(event) {
    var k = event.key
    if (k === Qt.Key_Left || k === Qt.Key_H) { tab.move(-1); event.accepted = true }
    else if (k === Qt.Key_Right || k === Qt.Key_L) { tab.move(1); event.accepted = true }
    else if (k === Qt.Key_Up || k === Qt.Key_K) { tab.move(-tab.columns()); event.accepted = true }
    else if (k === Qt.Key_Down || k === Qt.Key_J) { tab.move(tab.columns()); event.accepted = true }
    else if (k === Qt.Key_Return || k === Qt.Key_Enter) { tab.enter(tab.current); event.accepted = true }
    else if (k === Qt.Key_Backspace) { tab.up(); event.accepted = true }
    else if (k === Qt.Key_A) { tab.add(tab.current); event.accepted = true }
    else if (k === Qt.Key_Slash) { tab.focusSearch(); event.accepted = true }
    else if (k === Qt.Key_N) { tab.loadMore(); event.accepted = true }
    else if (k === Qt.Key_P) { tab.previewing ? tab.stopPreviewAll() : tab.previewAll(); event.accepted = true }
  }

  Row {
    anchors.fill: parent
    spacing: Style.spacing.panelGap

    // ---- source list ------------------------------------------------------
    Column {
      id: left
      width: Style.space(230)
      height: parent.height
      spacing: Style.spacing.xs
      PanelSectionHeader { text: "Sources"; foreground: tab.muted }
      ListView {
        width: parent.width
        height: parent.height - Style.space(120)
        clip: true
        model: tab.sources
        spacing: Style.spacing.xxs
        delegate: Rectangle {
          required property var modelData
          width: ListView.view.width
          height: Style.space(40)
          radius: Style.cornerRadius
          color: modelData.id === tab.sourceId ? tab.selectedBackground : "transparent"
          Row {
            anchors.fill: parent
            anchors.margins: Style.spacing.sm
            spacing: Style.spacing.sm
            Rectangle { anchors.verticalCenter: parent.verticalCenter; width: Style.space(8); height: width; radius: width / 2
              color: modelData.online === false ? Color.urgent : (modelData.online ? tab.accent : tab.muted) }
            Column {
              anchors.verticalCenter: parent.verticalCenter
              width: parent.width - Style.space(16)
              Text { width: parent.width; text: modelData.name; color: tab.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body; elide: Text.ElideRight }
              Text { width: parent.width; text: modelData.kind + (modelData.has_thumbnails ? " · thumbnails" : "") + (modelData.has_search ? " · search" : ""); color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
            }
          }
          MouseArea { anchors.fill: parent; onClicked: tab.selectSource(modelData.id) }
        }
        Text { anchors.centerIn: parent; visible: tab.sources.length === 0; text: "no sources (engine not ready)"; color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption }
      }
      Button { text: tab.addOpen ? "Cancel" : "Add source…"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: tab.addOpen = !tab.addOpen }
      Column {
        visible: tab.addOpen
        width: parent.width
        spacing: Style.spacing.xs
        Dropdown { width: parent.width; showLabel: false; value: tab.addKind; options: [{ value: "github_repo", label: "GitHub repository" }, { value: "http_index", label: "HTTP directory index" }]; onChanged: function(v) { tab.addKind = v } }
        TextField { id: addUrl; width: parent.width; placeholderText: tab.addKind === "github_repo" ? "owner/repo or https://github.com/…" : "https://…/"; foreground: tab.foreground; accent: tab.accent }
        Button { text: "Add"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent
          onClicked: { if (addUrl.text.trim() !== "" && tab.service) { tab.service.runCli(["sources", "add", "--kind", tab.addKind, "--url", addUrl.text.trim()], {}); tab.status("adding source " + addUrl.text.trim()); addUrl.text = ""; tab.addOpen = false } } }
      }
    }

    // ---- browser ----------------------------------------------------------
    Column {
      width: parent.width - left.width - Style.spacing.panelGap
      height: parent.height
      spacing: Style.spacing.sm

      Row {
        id: crumbRow
        width: parent.width
        spacing: Style.spacing.xs
        Button { text: "⌂ " + (tab.source ? tab.source.name : "…"); bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: tab.browse([], "", 1, false) }
        Repeater {
          model: tab.crumbs
          delegate: Button {
            required property var modelData
            required property int index
            text: "› " + modelData
            bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent
            onClicked: tab.browse(tab.pathSegs.slice(0, index + 1), "", 1, false)
          }
        }
        TextField {
          id: searchField
          visible: !!(tab.source && tab.source.has_search)
          width: Style.space(200)
          placeholderText: "search " + (tab.source ? tab.source.name : "") + "…"
          foreground: tab.foreground; accent: tab.accent
          // Return runs the search and hands the keyboard back to the grid so
          // Enter / arrows / `a` act on the results, not on the text.
          onAccepted: { tab.search = text; tab.browse([], text, 1, false); if (tab.overlay) tab.overlay.focusKeys() }
          Keys.onEscapePressed: function(event) { if (text !== "") { text = ""; tab.search = ""; tab.browse([], "", 1, false) } else if (tab.overlay) tab.overlay.dismiss(); event.accepted = true }
        }
        Text { anchors.verticalCenter: parent.verticalCenter; text: tab.busy ? "loading…" : (tab.entries.length + " entries"); color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption }
        Button {
          anchors.verticalCenter: parent.verticalCenter
          visible: tab.previewing || tab.previewable > 0
          text: tab.previewing ? ("Stop (" + tab.previewQueue.length + " left)") : ("Preview all (" + tab.previewable + ")")
          tooltipText: "render a picture for every item on this page that has none — one download per item"
          bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent
          onClicked: tab.previewing ? tab.stopPreviewAll() : tab.previewAll()
        }
      }

      Row {
        width: parent.width
        height: parent.height - crumbRow.height - Style.spacing.sm
        spacing: Style.spacing.panelGap

        GridView {
          id: grid
          width: parent.width - pane.width - Style.spacing.panelGap
          height: parent.height
          clip: true
          cellWidth: Style.space(226)
          cellHeight: Style.space(206)
          cacheBuffer: cellHeight * 2
          boundsBehavior: Flickable.StopAtBounds
          model: tab.entries
          delegate: SourceCard {}
          footer: Item {
            width: grid.width
            height: (tab.listing && tab.listing.next_page) ? Style.space(44) : 0
            Button { anchors.centerIn: parent; visible: !!(tab.listing && tab.listing.next_page); text: "Load more"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: tab.loadMore() }
          }
          Text { anchors.centerIn: parent; visible: tab.entries.length === 0 && !tab.busy; text: tab.sourceId === "" ? "pick a source" : "nothing here"; color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.body }
        }

        Item {
          id: pane
          width: Style.space(320)
          height: parent.height
          Column {
            anchors.fill: parent
            spacing: Style.spacing.sm
            Rectangle {
              width: parent.width; height: parent.height * 0.6; color: "#000000"; radius: Style.cornerRadius; clip: true
              Image {
                anchors.fill: parent; anchors.margins: Style.spacing.xs
                source: tab.previewItem ? (tab.previewItem.render ? Model.fileUrl(tab.previewItem.render) : (tab.previewItem.image_url || tab.previewItem.thumb_url || "")) : ""
                asynchronous: true; cache: true; fillMode: Image.PreserveAspectFit; verticalAlignment: Image.AlignTop
                sourceSize.width: Math.round(width * Screen.devicePixelRatio); smooth: true
              }
              Text { anchors.centerIn: parent; visible: !tab.previewItem; text: "Enter / double-click an item to preview it"; color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption; width: parent.width - Style.spacing.md; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap }
            }
            Text { width: parent.width; text: tab.previewItem ? tab.previewItem.label : ""; color: tab.foreground; font.family: Style.font.menuFamily; font.pixelSize: Style.font.title; elide: Text.ElideRight }
            Text { width: parent.width; wrapMode: Text.WordWrap; text: tab.previewItem ? [tab.previewItem.sublabel, tab.previewItem.meta ? [tab.previewItem.meta.author, tab.previewItem.meta.group, tab.previewItem.meta.year, tab.previewItem.meta.cols && tab.previewItem.meta.rows ? tab.previewItem.meta.cols + "×" + tab.previewItem.meta.rows : ""].filter(function(x) { return x }).join(" · ") : ""].filter(function(x) { return x }).join("\n") : ""; color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption }
            Row { spacing: Style.spacing.xs; visible: !!tab.previewItem
              Button { text: tab.previewItem && tab.libraryIdFor(tab.previewItem) ? "added ✓" : "Add to library"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: tab.add(tab.previewItem) }
            }
          }
        }
      }
    }
  }

  component SourceCard: Item {
    id: cardRoot
    required property var modelData
    required property int index
    readonly property var entry: modelData
    readonly property bool current: grid.currentIndex === index
    readonly property string inLibrary: entry.type === "item" ? tab.libraryIdFor(entry) : ""
    readonly property bool adding: !!tab.addingIds[entry.id]
    readonly property bool thumbBroken: !!tab.thumbFailed[entry.id]
    readonly property string localPng: tab.localPngs[tab.sourceId + "|" + entry.id] || ""
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
          height: parent.height - labelText.height - subText.height - actionRow.height - Style.spacing.xxs * 3
          color: cardRoot.entry.type === "collection" ? "transparent" : "#000000"
          radius: Style.cornerRadius / 2
          clip: true
          Text {
            anchors.centerIn: parent
            visible: cardRoot.entry.type === "collection"
            text: "󰉋"
            color: tab.accent
            font.family: Style.font.family; font.pixelSize: Style.space(48)
          }
          Image {
            anchors.fill: parent; anchors.margins: Style.spacing.xxs
            visible: cardRoot.entry.type === "item" && (cardRoot.localPng !== "" || (!!cardRoot.entry.thumb_url && !cardRoot.thumbBroken))
            source: cardRoot.localPng !== "" ? Model.fileUrl(cardRoot.localPng) : ((cardRoot.entry.thumb_url && !cardRoot.thumbBroken) ? cardRoot.entry.thumb_url : "")
            asynchronous: true; cache: true; fillMode: Image.PreserveAspectFit; verticalAlignment: Image.AlignTop
            sourceSize.width: Math.round(width * Screen.devicePixelRatio); smooth: true
            onStatusChanged: if (status === Image.Error && cardRoot.localPng === "") tab.markThumbFailed(cardRoot.entry.id)
          }
          Text {
            anchors.fill: parent; anchors.margins: Style.spacing.xs
            visible: cardRoot.entry.type === "item" && cardRoot.localPng === "" && (!cardRoot.entry.thumb_url || cardRoot.thumbBroken) && !!cardRoot.entry.text_preview
            text: cardRoot.entry.text_preview || ""
            textFormat: Text.PlainText
            color: tab.foreground
            font.family: "monospace"; font.pixelSize: Style.font.caption
            wrapMode: Text.NoWrap; clip: true; lineHeight: 1.0
          }
          Button {
            anchors.centerIn: parent
            visible: cardRoot.entry.type === "item" && cardRoot.localPng === "" && (!cardRoot.entry.thumb_url || cardRoot.thumbBroken) && !cardRoot.entry.text_preview
            text: "Preview"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent
            onClicked: tab.previewEntry(cardRoot.entry)
          }
          Text {
            anchors.top: parent.top; anchors.right: parent.right; anchors.margins: Style.spacing.xxs
            visible: cardRoot.inLibrary !== ""
            text: "✓"; color: tab.accent; font.pixelSize: Style.font.title
          }
        }
        Text { id: labelText; width: parent.width; text: cardRoot.entry.label; color: tab.foreground; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall; elide: Text.ElideRight }
        Text { id: subText; width: parent.width; text: cardRoot.entry.sublabel || (cardRoot.entry.meta ? [cardRoot.entry.meta.author, cardRoot.entry.meta.year].filter(function(x) { return x }).join(" · ") : ""); color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
        Row {
          id: actionRow
          spacing: Style.spacing.xs
          height: Style.space(22)
          Button {
            visible: cardRoot.entry.type === "item"
            text: cardRoot.inLibrary !== "" ? "added ✓" : (cardRoot.adding ? "adding…" : "Add")
            bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent
            enabled: cardRoot.inLibrary === "" && !cardRoot.adding
            onClicked: tab.add(cardRoot.entry)
          }
          Button {
            visible: cardRoot.entry.type === "collection" && !!cardRoot.entry.can_add_all
            text: "Add all"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent
            onClicked: tab.add(cardRoot.entry)
          }
          Button {
            visible: cardRoot.entry.type === "collection"
            text: "Open"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent
            onClicked: tab.enter(cardRoot.entry)
          }
        }
      }
      MouseArea {
        anchors.fill: parent
        z: -1
        hoverEnabled: true
        onClicked: grid.currentIndex = cardRoot.index
        onDoubleClicked: tab.enter(cardRoot.entry)
        onEntered: { if (cardRoot.entry.type === "item" && (cardRoot.entry.thumb_url || cardRoot.entry.image_url || cardRoot.localPng !== "")) tab.previewItem = Object.assign({}, cardRoot.entry, tab.previewCache[tab.sourceId + "|" + cardRoot.entry.id] || {}) }
      }
    }
  }
}
