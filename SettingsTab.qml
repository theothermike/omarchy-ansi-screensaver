import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "Model.js" as Model

Item {
  id: tab
  property var overlay: null
  readonly property var service: overlay ? overlay.service : null
  readonly property var config: overlay ? overlay.config : ({})
  readonly property color foreground: overlay ? overlay.foreground : Color.foreground
  readonly property color accent: overlay ? overlay.accent : Color.accent
  readonly property color muted: overlay ? overlay.muted : Color.muted

  function onShown() {}
  function handleKey(event) {
    if (event.key === Qt.Key_Down || event.key === Qt.Key_J) { flick.contentY = Math.min(flick.contentHeight - flick.height, flick.contentY + 60); event.accepted = true }
    else if (event.key === Qt.Key_Up || event.key === Qt.Key_K) { flick.contentY = Math.max(0, flick.contentY - 60); event.accepted = true }
  }
  function set(key, value) { if (tab.service) tab.service.setConfig(key, JSON.stringify(value)); if (tab.overlay) tab.overlay.status(key + " → " + JSON.stringify(value)) }
  function setIdle(key, seconds) { if (tab.service) { var r = tab.service.setOmarchyIdle(key, seconds); tab.overlay.status(r === "ok" ? ("Omarchy idle." + key + " → " + seconds + " s") : r) } }
  function fmtSeconds(sec) {
    if (sec >= 86400 * 20) return "never"
    if (sec % 3600 === 0) return (sec / 3600) + " h"
    if (sec % 60 === 0) return (sec / 60) + " min"
    return sec + " s"
  }

  // Preset dropdown + exact seconds field, both bound to the same value.
  component TimeoutControl: Row {
    id: tc
    property int seconds: 0
    property bool allowNever: false
    signal committed(int value)
    spacing: Style.spacing.controlGap
    readonly property var presets: {
      var base = [30, 60, 120, 180, 300, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200, 10800, 14400]
      var out = base.map(function(v) { return { value: String(v), label: tab.fmtSeconds(v) } })
      if (tc.allowNever) out.push({ value: String(30 * 86400), label: "never (30 days)" })
      var known = base.slice(); if (tc.allowNever) known.push(30 * 86400)
      if (known.indexOf(tc.seconds) === -1) out.unshift({ value: String(tc.seconds), label: "custom · " + tab.fmtSeconds(tc.seconds) })
      return out
    }
    Dropdown {
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(180)
      showLabel: false
      value: String(tc.seconds)
      options: tc.presets
      onChanged: function(v) { var n = parseInt(v); if (isFinite(n) && n !== tc.seconds) tc.committed(n) }
    }
    NumberField {
      anchors.verticalCenter: parent.verticalCenter
      label: "seconds"
      value: tc.seconds
      from: 10; to: 30 * 86400; stepSize: 30
      fieldWidth: Style.space(90)
      onModified: function(v) { if (v !== tc.seconds) tc.committed(v) }
    }
  }
  function get(key, fallback) { return Model.get(tab.config, key, fallback) }
  function doctorFind(name) {
    var d = tab.service ? tab.service.doctor : []
    for (var i = 0; i < d.length; i++) if (d[i].name === name) return d[i]
    return null
  }

  Flickable {
    id: flick
    anchors.fill: parent
    contentHeight: col.height
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    Column {
      id: col
      width: flick.width - Style.spacing.md
      spacing: Style.spacing.xs

      PanelSectionHeader { text: "Slideshow"; foreground: tab.muted }
      FieldRow { label: "Hold each piece"; description: "seconds a piece stays on screen after its reveal"; foreground: tab.foreground; muted: tab.muted
        NumberField { value: tab.get("hold_seconds", 20); from: 1; to: 600; onModified: function(v) { tab.set("hold_seconds", v) } } }
      FieldRow { label: "Scroll speed"; description: "rows per second for pieces taller than the screen"; foreground: tab.foreground; muted: tab.muted
        NumberField { value: tab.get("scroll_rows_per_second", 2); from: 1; to: 30; onModified: function(v) { tab.set("scroll_rows_per_second", v) } } }
      FieldRow { label: "Hold before scrolling"; description: "seconds to show the top of a tall piece first"; foreground: tab.foreground; muted: tab.muted
        NumberField { value: tab.get("hold_top_seconds", 4); from: 0; to: 120; onModified: function(v) { tab.set("hold_top_seconds", v) } } }
      FieldRow { label: "Order"; foreground: tab.foreground; muted: tab.muted
        ButtonGroup { options: [{ value: "shuffle", label: "Shuffle" }, { value: "ordered", label: "Ordered" }, { value: "favorites", label: "Favourites ×3" }]; value: tab.get("order", "shuffle"); foreground: tab.foreground; accent: tab.accent; onChanged: function(v) { tab.set("order", v) } } }
      FieldRow { label: "Caption"; description: "title — artist / group, year in a corner during the hold"; foreground: tab.foreground; muted: tab.muted
        Row { spacing: Style.spacing.controlGap
          ToggleSwitch { checked: tab.get("caption", true) === true; foreground: tab.foreground; accent: tab.accent; onToggled: tab.set("caption", !(tab.get("caption", true) === true)) }
          Dropdown { width: Style.space(140); showLabel: false; value: tab.get("caption_position", "br"); options: [{ value: "br", label: "bottom right" }, { value: "bl", label: "bottom left" }, { value: "tr", label: "top right" }, { value: "tl", label: "top left" }]; onChanged: function(v) { tab.set("caption_position", v) } }
        } }
      FieldRow { label: "Omarchy logo interstitial"; description: "show ~/.config/omarchy/branding/screensaver.txt every N pieces (0 = never)"; foreground: tab.foreground; muted: tab.muted
        NumberField { value: tab.get("include_branding", 0); from: 0; to: 100; onModified: function(v) { tab.set("include_branding", v) } } }
      FieldRow { label: "Plain ASCII colouring"; description: "how uncoloured pieces are tinted"; foreground: tab.foreground; muted: tab.muted
        ButtonGroup { options: [{ value: "theme-gradient", label: "Theme gradient" }, { value: "theme-foreground", label: "Theme fg" }, { value: "vga-grey", label: "VGA grey" }]; value: tab.get("ascii_color", "theme-gradient"); foreground: tab.foreground; accent: tab.accent; onChanged: function(v) { tab.set("ascii_color", v) } } }

      PanelSectionHeader { text: "Gallery"; foreground: tab.muted }
      FieldRow { label: "Confirm before removing"; description: "off = the ✕ on a card and the Delete key remove a piece immediately"; foreground: tab.foreground; muted: tab.muted
        ToggleSwitch { checked: tab.get("confirm_remove", true) === true; foreground: tab.foreground; accent: tab.accent; onToggled: tab.set("confirm_remove", !(tab.get("confirm_remove", true) === true)) } }

      PanelSectionHeader { text: "Display"; foreground: tab.muted }
      FieldRow { label: "Columns"; description: "terminal width the font is sized for; 80 = classic, auto = widest enabled piece"; foreground: tab.foreground; muted: tab.muted
        ButtonGroup { options: [{ value: "80", label: "80" }, { value: "100", label: "100" }, { value: "132", label: "132" }, { value: "auto", label: "auto" }]; value: String(tab.get("columns", 80)); foreground: tab.foreground; accent: tab.accent; onChanged: function(v) { tab.set("columns", v === "auto" ? "auto" : parseInt(v)) } } }
      FieldRow { label: "Font"; description: "auto = IBM VGA when installed, else the terminal font with 1:2 cells"; foreground: tab.foreground; muted: tab.muted
        Row { spacing: Style.spacing.controlGap
          ButtonGroup { options: [{ value: "auto", label: "Auto" }, { value: "vga", label: "IBM VGA" }, { value: "terminal", label: "Terminal" }]; value: tab.get("font", "auto"); foreground: tab.foreground; accent: tab.accent; onChanged: function(v) { tab.set("font", v) } }
          Button { text: (tab.doctorFind("vga font") && tab.doctorFind("vga font").ok) ? "VGA font installed" : "Install VGA font"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent
            onClicked: { if (tab.service) tab.service.runCli(["fonts", "install"], {}); tab.overlay.status("installing Px437 IBM VGA 8x16…") } }
        } }
      FieldRow { label: "Pieces wider than the screen"; foreground: tab.foreground; muted: tab.muted
        ButtonGroup { options: [{ value: "skip", label: "Skip" }, { value: "clip", label: "Clip" }]; value: tab.get("wide_pieces", "skip"); foreground: tab.foreground; accent: tab.accent; onChanged: function(v) { tab.set("wide_pieces", v) } } }
      FieldRow { label: "Multiple monitors"; foreground: tab.foreground; muted: tab.muted
        ButtonGroup { options: [{ value: "independent", label: "Different art each" }, { value: "mirrored", label: "Mirrored" }]; value: tab.get("multi_monitor", "independent"); foreground: tab.foreground; accent: tab.accent; onChanged: function(v) { tab.set("multi_monitor", v) } } }

      PanelSectionHeader { text: "Idle timeouts (Omarchy shell.json)"; foreground: tab.muted }
      FieldRow { label: "Screensaver after"; description: "seconds of no input before the screensaver starts (Omarchy's idle.screensaver)"; foreground: tab.foreground; muted: tab.muted; controlWidth: Style.space(340)
        TimeoutControl { seconds: tab.service ? tab.service.screensaverSeconds : 150; onCommitted: function(v) { tab.setIdle("screensaver", v) } } }
      FieldRow { label: "Lock after"; description: (tab.service && tab.service.lockSeconds <= tab.service.screensaverSeconds) ? "⚠ lock fires before the screensaver — counted from the start of idleness, not after the screensaver" : "seconds of no input before the lock screen (idle.lock); counted from the start of idleness"; foreground: tab.foreground; muted: tab.muted; controlWidth: Style.space(340)
        TimeoutControl { seconds: tab.service ? tab.service.lockSeconds : 300; allowNever: true; onCommitted: function(v) { tab.setIdle("lock", v) } } }

      PanelSectionHeader { text: "Idle takeover"; foreground: tab.muted }
      FieldRow { label: "Take over the idle screensaver"; description: tab.service ? ("this screensaver launches at " + tab.service.timeoutSeconds + " s idle, " + tab.service.leadSeconds + " s before Omarchy's own · " + (tab.service.armed ? "armed" : tab.service.screensaverOff ? "screensaver-off toggle is set" : tab.service.stayAwake ? "stay-awake is on" : "off")) : ""; foreground: tab.foreground; muted: tab.muted
        ToggleSwitch { checked: tab.get("idle.takeover", true) === true; foreground: tab.foreground; accent: tab.accent; onToggled: tab.set("idle.takeover", !(tab.get("idle.takeover", true) === true)) } }
      FieldRow { label: "Lead time"; description: "seconds before Omarchy's own timer that ours fires"; foreground: tab.foreground; muted: tab.muted
        NumberField { value: tab.get("idle.lead_seconds", 2); from: 1; to: 60; onModified: function(v) { tab.set("idle.lead_seconds", v) } } }
      FieldRow { label: "Omarchy screensaver toggle"; description: "the stock screensaver-off flag (also disarms this one)"; foreground: tab.foreground; muted: tab.muted
        ToggleSwitch { checked: !(tab.service && tab.service.screensaverOff); foreground: tab.foreground; accent: tab.accent; onToggled: { Quickshell.execDetached(["omarchy-toggle-screensaver"]); tab.overlay.status("toggled screensaver-off") } } }
      FieldRow { label: "Test idle takeover"; description: "arms a 10 s idle timer once; leave the mouse alone"; foreground: tab.foreground; muted: tab.muted
        Row { spacing: Style.spacing.xs
          Button { text: "Test in 10 s"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: { if (tab.service) tab.overlay.status(tab.service.armTest(10)) } }
          Button { text: "Cancel"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: { if (tab.service) tab.service.disarmTest(); tab.overlay.status("test cancelled") } }
        } }

      PanelSectionHeader { text: "Maintenance"; foreground: tab.muted }
      Flow {
        width: parent.width
        spacing: Style.spacing.xs
        Button { text: "Run doctor"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: { if (tab.service) tab.service.reload(); tab.overlay.status("doctor refreshed") } }
        Button { text: "Rebuild thumbnails"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: { if (tab.service) tab.overlay.status(tab.service.startJob("thumbs", ["thumbs", "--all", "--force"])) } }
        Button { text: "Render missing thumbnails"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: { if (tab.service) tab.overlay.status(tab.service.startJob("thumbs", ["thumbs", "--all", "--missing"])) } }
        Button { text: "Seed bundled art"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: { if (tab.service) tab.overlay.status(tab.service.startJob("seed", ["seed"])) } }
        Button { text: "Open config folder"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: Quickshell.execDetached(["xdg-open", Quickshell.env("HOME") + "/.config/omarchy/ansi-screensaver"]) }
        Button { text: "Stop screensaver"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: { if (tab.service) tab.service.runCli(["stop", "--previews"], { reloadAfter: false }) } }
      }
      Column {
        width: parent.width
        spacing: Style.spacing.xxs
        Repeater {
          model: tab.service ? tab.service.doctor : []
          delegate: Text {
            required property var modelData
            width: col.width
            text: (modelData.ok ? "●  " : "○  ") + modelData.name + ": " + modelData.detail + (!modelData.ok && modelData.fix ? "   →  " + modelData.fix : "")
            color: modelData.ok ? tab.muted : Color.urgent
            font.family: Style.font.family; font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
        }
      }
      Item { width: 1; height: Style.spacing.lg }
    }
  }
}
