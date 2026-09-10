import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Model.js" as Model

// The fullscreen configuration overlay: Gallery / Sources / Effects / Settings.
// Skeleton follows the plugin-explorer overlay (scrim, key catcher, card).
Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null
  property var service: null

  readonly property string pluginId: "io.github.theothermike.ansi-screensaver"
  property bool opened: false
  property string tab: "gallery"
  property string statusText: ""
  readonly property var tabs: [
    { value: "gallery", label: "Gallery" }, { value: "sources", label: "Sources" },
    { value: "effects", label: "Effects" }, { value: "settings", label: "Settings" }]

  // --- theme ------------------------------------------------------------
  readonly property color background: Color.menu.background
  readonly property color foreground: Color.menu.text
  readonly property color borderColor: Color.menu.border
  readonly property color scrimColor: Color.menu.scrim
  readonly property color selectedBackground: Color.menu.selectedBackground
  readonly property color accent: Color.accent
  readonly property color muted: Color.muted
  readonly property var borderSpec: Border.surfaceSpec("menu", "border", borderColor, Math.max(1, Style.space(2)))
  readonly property int pad: Style.spacing.panelPadding

  readonly property var library: service ? service.library : []
  readonly property var config: service ? service.config : ({})

  function status(msg) { root.statusText = msg || "" }
  function focusKeys() { keyCatcher.forceActiveFocus() }

  // --- lifecycle --------------------------------------------------------
  function open(payloadJson) {
    var payload = {}
    try { payload = JSON.parse(payloadJson || "{}") } catch (e) {}
    if (payload.tab && ["gallery", "sources", "effects", "settings"].indexOf(payload.tab) !== -1) root.tab = payload.tab
    root.opened = true
    root.statusText = ""
    root.pendingNavigate = payload.source ? { source: payload.source, path: payload.path || [] } : null
    if (root.service) root.service.reload()
    Qt.callLater(function() { keyCatcher.forceActiveFocus(); root.focusTab() })
  }
  function close() { root.opened = false }
  function dismiss() {
    root.opened = false
    if (root.shell && typeof root.shell.hide === "function") root.shell.hide(root.pluginId)
  }
  function activeTab() {
    if (root.tab === "gallery") return galleryTab
    if (root.tab === "sources") return sourcesLoader.item
    if (root.tab === "effects") return effectsLoader.item
    return settingsLoader.item
  }
  function focusTab() { var t = root.activeTab(); if (t && typeof t.onShown === "function") t.onShown() }
  function switchTab(delta) {
    var i = 0
    for (var k = 0; k < root.tabs.length; k++) if (root.tabs[k].value === root.tab) i = k
    i = (i + delta + root.tabs.length) % root.tabs.length
    root.tab = root.tabs[i].value
    keyCatcher.forceActiveFocus()
    Qt.callLater(root.focusTab)
  }

  // --- confirm dialog (shared) -------------------------------------------
  // deep link into the Sources tab (IPC `browse <source> <pathJson>`)
  property var pendingNavigate: null
  property var confirmAction: null
  function confirm(message, action) {
    root.confirmAction = action
    confirmDialog.message = message
    confirmDialog.selectedIndex = 1
    confirmDialog.opened = true
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omarchy-ansi-screensaver"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle { anchors.fill: parent; color: root.scrimColor }
    MouseArea { anchors.fill: parent; onClicked: root.dismiss() }

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: root.opened

      Keys.onPressed: function(event) {
        if (confirmDialog.opened) { confirmDialog.handleKey(event); event.accepted = true; return }
        var ctrl = event.modifiers & Qt.ControlModifier
        if (event.key === Qt.Key_Escape) {
          var t = root.activeTab()
          if (t && typeof t.onEscape === "function" && t.onEscape()) { event.accepted = true; return }
          root.dismiss(); event.accepted = true
        } else if (ctrl && event.key >= Qt.Key_1 && event.key <= Qt.Key_4) {
          root.tab = root.tabs[event.key - Qt.Key_1].value; Qt.callLater(root.focusTab); event.accepted = true
        } else if (event.key === Qt.Key_Tab) {
          root.switchTab(1); event.accepted = true
        } else if (event.key === Qt.Key_Backtab) {
          root.switchTab(-1); event.accepted = true
        } else if (event.key === Qt.Key_F5) {
          if (root.service) root.service.reload(); event.accepted = true
        } else {
          var tab = root.activeTab()
          if (tab && typeof tab.handleKey === "function") tab.handleKey(event)
        }
      }

      BorderSurface {
        id: card
        width: Math.min(Style.space(1240), panel.width - Style.gapsOut * 2)
        height: Math.min(Style.space(820), panel.height - Style.gapsOut * 2)
        anchors.centerIn: parent
        radius: Style.cornerRadius
        color: root.background
        borderSpec: root.borderSpec
        padding: root.pad

        MouseArea { anchors.fill: parent }

        Column {
          id: column
          anchors.fill: parent
          anchors.margins: card.contentTopInset
          spacing: Style.spacing.md

          // ---- header --------------------------------------------------
          Item {
            width: parent.width
            height: header.height
            Row {
              id: header
              width: parent.width
              spacing: Style.spacing.controlGap

              Column {
                width: parent.width - tabGroup.width - actions.width - Style.spacing.controlGap * 2
                spacing: Style.spacing.xxs
                Text { text: "ANSI Screensaver"; color: root.foreground; font.family: Style.font.menuFamily; font.pixelSize: Style.font.heading }
                Text {
                  text: {
                    if (!root.service || !root.service.snapshot) return root.service && root.service.loading ? "loading…" : "no snapshot"
                    var lib = root.library, en = 0
                    for (var i = 0; i < lib.length; i++) if (lib[i].enabled) en++
                    return lib.length + " pieces · " + en + " enabled · " + (root.service.sources || []).length + " sources · "
                      + (root.service.armed ? "idle takeover armed at " + root.service.timeoutSeconds + " s" : "idle takeover off")
                  }
                  color: root.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
                }
              }

              ButtonGroup {
                id: tabGroup
                anchors.verticalCenter: parent.verticalCenter
                options: root.tabs
                value: root.tab
                foreground: root.foreground
                accent: root.accent
                onChanged: function(v) { root.tab = v; keyCatcher.forceActiveFocus(); Qt.callLater(root.focusTab) }
              }

              Row {
                id: actions
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.spacing.xs
                Button {
                  text: "Launch now"; bordered: true; fontSize: Style.font.caption
                  foreground: root.foreground; accent: root.accent
                  onClicked: { if (root.service) root.service.launch(true); root.dismiss() }
                }
                Button {
                  text: "Preview random"; bordered: true; fontSize: Style.font.caption
                  foreground: root.foreground; accent: root.accent
                  onClicked: { if (root.service) root.service.runCli(["preview", "--random"], { reloadAfter: false }); root.dismiss() }
                }
              }
            }
          }

          Rectangle { width: parent.width; height: Math.max(1, Style.space(1)); color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.15) }

          // ---- body ----------------------------------------------------
          Item {
            id: body
            width: parent.width
            height: parent.height - y - jobBar.height - footer.height - Style.spacing.md * 2

            GalleryTab { id: galleryTab; anchors.fill: parent; visible: root.tab === "gallery"; overlay: root }
            Loader { id: sourcesLoader; anchors.fill: parent; active: root.tab === "sources"; sourceComponent: SourcesTab { overlay: root } }
            Loader { id: effectsLoader; anchors.fill: parent; active: root.tab === "effects"; sourceComponent: EffectsTab { overlay: root } }
            Loader { id: settingsLoader; anchors.fill: parent; active: root.tab === "settings"; sourceComponent: SettingsTab { overlay: root } }
          }

          JobBar { id: jobBar; width: parent.width; job: root.service ? root.service.job : null; service: root.service; foreground: root.foreground; accent: root.accent; muted: root.muted }

          // ---- footer --------------------------------------------------
          Item {
            id: footer
            width: parent.width
            height: Style.space(20)
            Row {
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              width: parent.width * 0.42
              clip: true
              spacing: Style.spacing.sm
              Repeater {
                model: root.service ? root.service.doctor.filter(function(c) { return ["ttfx", "vga font", "library", "screensaver-off toggle", "stay-awake"].indexOf(c.name) !== -1 || c.name.indexOf("monitor") === 0 }) : []
                delegate: Text {
                  required property var modelData
                  text: (modelData.ok ? "● " : "○ ") + modelData.name + (modelData.name.indexOf("monitor") === 0 ? " " + modelData.detail.split("->").pop().trim() : "")
                  color: modelData.ok ? root.muted : Color.urgent
                  font.family: Style.font.family; font.pixelSize: Style.font.caption
                }
              }
            }
            Text {
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              width: parent.width * 0.55
              horizontalAlignment: Text.AlignRight
              elide: Text.ElideLeft
              text: root.statusText !== "" ? root.statusText
                : (root.service && root.service.lastError ? root.service.lastError
                : "←↑↓→ browse   Enter preview   e enable   f favourite   / search   Tab switch tab   Esc close")
              color: root.statusText !== "" ? root.accent : (root.service && root.service.lastError ? Color.urgent : root.muted)
              font.family: Style.font.family; font.pixelSize: Style.font.caption
            }
          }
        }
      }

      ConfirmDialog {
        id: confirmDialog
        anchors.fill: parent
        background: root.background
        foreground: root.foreground
        onConfirmed: { var a = root.confirmAction; root.confirmAction = null; opened = false; if (a) a() }
        onCanceled: { root.confirmAction = null; opened = false }
      }
    }
  }
}
