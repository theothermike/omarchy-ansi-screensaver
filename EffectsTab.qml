import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Item {
  id: tab
  property var overlay: null
  readonly property var service: overlay ? overlay.service : null
  readonly property var config: overlay ? overlay.config : ({})
  readonly property var effects: service && service.effects ? service.effects : null
  readonly property color foreground: overlay ? overlay.foreground : Color.foreground
  readonly property color accent: overlay ? overlay.accent : Color.accent
  readonly property color muted: overlay ? overlay.muted : Color.muted
  readonly property var ttfxNames: effects && effects.ttfx ? effects.ttfx : Model.TTFX_EFFECTS
  readonly property var transitionNames: effects && effects.transitions ? effects.transitions : Model.TRANSITIONS
  property string tryEffect: "wipe"

  function onShown() {}
  function handleKey(event) {
    if (event.key === Qt.Key_Down || event.key === Qt.Key_J) { flick.contentY = Math.min(flick.contentHeight - flick.height, flick.contentY + 60); event.accepted = true }
    else if (event.key === Qt.Key_Up || event.key === Qt.Key_K) { flick.contentY = Math.max(0, flick.contentY - 60); event.accepted = true }
  }
  function set(key, value) { if (tab.service) tab.service.setConfig(key, JSON.stringify(value)); if (tab.overlay) tab.overlay.status(key + " → " + JSON.stringify(value)) }
  function get(key, fallback) { return Model.get(tab.config, key, fallback) }
  function defaultWeight(kind, name) {
    var d = tab.effects && tab.effects.defaults ? tab.effects.defaults[kind] : null
    var v = d && (name in d) ? d[name] : 2
    return v > 0 ? v : 2
  }
  function weight(kind, name) {
    var key = (kind === "ttfx" ? "ttfx.effects." : "transitions.out.") + name
    return Number(tab.get(key, tab.effects && tab.effects.defaults && tab.effects.defaults[kind] ? tab.effects.defaults[kind][name] : 0)) || 0
  }
  function toggle(kind, name) {
    var key = (kind === "ttfx" ? "ttfx.effects." : "transitions.out.") + name
    tab.set(key, tab.weight(kind, name) > 0 ? 0 : tab.defaultWeight(kind, name))
  }
  function setAll(kind, names, on) {
    for (var i = 0; i < names.length; i++) {
      var key = (kind === "ttfx" ? "ttfx.effects." : "transitions.out.") + names[i]
      var want = on === "recommended" ? (tab.effects && tab.effects.defaults ? (tab.effects.defaults[kind][names[i]] || 0) : 2) : (on ? tab.defaultWeight(kind, names[i]) : 0)
      if (tab.service) tab.service.setConfig(key, JSON.stringify(want))
    }
    if (tab.overlay) tab.overlay.status(kind + " effects updated")
  }
  function countOn(kind, names) { var n = 0; for (var i = 0; i < names.length; i++) if (tab.weight(kind, names[i]) > 0) n++; return n }

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

      PanelSectionHeader { text: "Reveal"; foreground: tab.muted }
      FieldRow { label: "ttfx effect vs. BBS baud draw"; description: "relative weights: how often a piece is revealed by a ttfx effect versus drawn at modem speed (animations always use baud)"; foreground: tab.foreground; muted: tab.muted
        Row { spacing: Style.spacing.controlGap
          NumberField { label: "ttfx"; value: tab.get("reveal.ttfx", 70); from: 0; to: 100; stepSize: 5; onModified: function(v) { tab.set("reveal.ttfx", v) } }
          NumberField { label: "baud"; value: tab.get("reveal.baud", 30); from: 0; to: 100; stepSize: 5; onModified: function(v) { tab.set("reveal.baud", v) } }
        } }
      FieldRow { label: "Art colours during effects"; description: "always = the art's own colours throughout · dynamic = the effect's palette while animating, art colours at the end"; foreground: tab.foreground; muted: tab.muted
        ButtonGroup { options: [{ value: "always", label: "Always" }, { value: "dynamic", label: "Dynamic" }]; value: tab.get("ttfx.existing_color_handling", "always"); foreground: tab.foreground; accent: tab.accent; onChanged: function(v) { tab.set("ttfx.existing_color_handling", v) } } }
      FieldRow { label: "Effect speed"; description: "frame-rate multiplier for every ttfx effect (percent)"; foreground: tab.foreground; muted: tab.muted
        NumberField { value: Math.round(Number(tab.get("ttfx.frame_rate_scale", 1.0)) * 100); from: 25; to: 400; stepSize: 25; onModified: function(v) { tab.set("ttfx.frame_rate_scale", v / 100) } } }
      FieldRow { label: "Baud rate"; description: "auto picks the slowest rate that finishes within ~20 s"; foreground: tab.foreground; muted: tab.muted
        Dropdown { width: Style.space(140); showLabel: false; value: String(tab.get("baud.rate", "auto")); options: ["auto", "2400", "9600", "14400", "28800", "57600"]; onChanged: function(v) { tab.set("baud.rate", v) } } }

      PanelSectionHeader { text: "ttfx effects (" + tab.countOn("ttfx", tab.ttfxNames) + " of " + tab.ttfxNames.length + " enabled)"; foreground: tab.muted }
      Row {
        spacing: Style.spacing.xs
        Button { text: "All"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: tab.setAll("ttfx", tab.ttfxNames, true) }
        Button { text: "None"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: tab.setAll("ttfx", tab.ttfxNames, false) }
        Button { text: "Recommended"; bordered: true; fontSize: Style.font.caption; foreground: tab.foreground; accent: tab.accent; onClicked: tab.setAll("ttfx", tab.ttfxNames, "recommended") }
        Text { anchors.verticalCenter: parent.verticalCenter; text: "click to toggle · ~seconds measured on a dense full-screen piece · effects over 10 s are off in Recommended"; color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption }
      }
      Flow {
        width: parent.width
        spacing: Style.spacing.xs
        Repeater {
          model: tab.ttfxNames
          delegate: Button {
            required property string modelData
            readonly property real secs: tab.effects && tab.effects.seconds && tab.effects.seconds[modelData] ? tab.effects.seconds[modelData] : 0
            text: modelData + (secs > 0 ? " ~" + Math.round(secs) + "s" : "") + (tab.weight("ttfx", modelData) > 1 ? " ×" + tab.weight("ttfx", modelData) : "")
            tooltipText: secs > 10 ? "slow: about " + Math.round(secs) + " s to reveal a dense full-screen piece" : (secs > 0 ? "about " + Math.round(secs) + " s on a dense piece" : "")
            selected: tab.weight("ttfx", modelData) > 0
            bordered: true; fontSize: Style.font.caption
            foreground: tab.foreground; accent: tab.accent
            onClicked: tab.toggle("ttfx", modelData)
            onRightClicked: { tab.tryEffect = modelData; if (tab.service) tab.service.runCli(["preview", "--random", "--effect", modelData], { reloadAfter: false }); tab.overlay.status("previewing with " + modelData); tab.overlay.dismiss() }
          }
        }
      }
      Text { text: "right-click a chip to preview a random piece with that effect"; color: tab.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption }

      PanelSectionHeader { text: "Out transitions (" + tab.countOn("out", tab.transitionNames) + " of " + tab.transitionNames.length + " enabled)"; foreground: tab.muted }
      Flow {
        width: parent.width
        spacing: Style.spacing.xs
        Repeater {
          model: tab.transitionNames
          delegate: Button {
            required property string modelData
            text: modelData + (tab.weight("out", modelData) > 1 ? " ×" + tab.weight("out", modelData) : "")
            selected: tab.weight("out", modelData) > 0
            bordered: true; fontSize: Style.font.caption
            foreground: tab.foreground; accent: tab.accent
            onClicked: tab.toggle("out", modelData)
          }
        }
      }
      FieldRow { label: "Transition frame rate"; foreground: tab.foreground; muted: tab.muted
        NumberField { value: tab.get("transitions.fps", 30); from: 5; to: 120; stepSize: 5; onModified: function(v) { tab.set("transitions.fps", v) } } }
      FieldRow { label: "Effect time limit"; description: "seconds before a slow effect is cut short and the piece painted directly"; foreground: tab.foreground; muted: tab.muted
        NumberField { value: tab.get("ttfx.max_seconds", 30); from: 3; to: 300; onModified: function(v) { tab.set("ttfx.max_seconds", v) } } }
      Item { width: 1; height: Style.spacing.lg }
    }
  }
}
