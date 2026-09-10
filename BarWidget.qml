import QtQuick
import qs.Commons
import qs.Ui

// Bar entry point: a glyph that reflects whether idle takeover is armed.
// Left click opens the gallery, right click launches the screensaver now,
// middle click toggles idle takeover. Every click goes through the same
// `omarchy-shell ansisaver ...` route the CLI and keybindings use.
BarWidget {
  id: root
  moduleName: "io.github.theothermike.ansi-screensaver"

  readonly property string glyph: setting("glyph", "󱄄")
  readonly property bool armedBadge: setting("armedBadge", true) === true

  // The trusted bar hands widgets a facade with serviceFor(); the live
  // Service instance publishes the takeover state, so no polling is needed.
  property var service: null
  function resolveService() {
    if (root.bar && root.bar.shell && typeof root.bar.shell.serviceFor === "function")
      root.service = root.bar.shell.serviceFor(root.moduleName)
  }
  onBarChanged: resolveService()
  Component.onCompleted: resolveService()
  Timer { interval: 1500; repeat: true; running: !root.service; onTriggered: root.resolveService() }

  readonly property bool armed: service ? service.armed === true : false
  readonly property string stateText: !service ? "service not loaded"
    : service.screensaverOff ? "disabled (screensaver-off toggle)"
    : service.stayAwake ? "stay awake is on"
    : !service.takeoverEnabled ? "idle takeover off"
    : "armed at " + service.timeoutSeconds + " s idle"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.glyph
    dimmed: !root.armed
    tooltipText: "ANSI screensaver · " + root.stateText
    onPressed: function(mouseButton) {
      if (!root.bar) return
      if (mouseButton === Qt.RightButton) root.bar.run("omarchy-shell ansisaver launch")
      else if (mouseButton === Qt.MiddleButton) root.bar.run("omarchy-shell ansisaver toggleTakeover")
      else root.bar.run("omarchy-shell ansisaver open")
    }
  }

  Rectangle {
    visible: root.armedBadge && root.armed
    width: Math.max(4, Style.space(4))
    height: width
    radius: width / 2
    color: Color.accent
    anchors.right: button.right
    anchors.bottom: button.bottom
    anchors.rightMargin: Style.space(1)
    anchors.bottomMargin: Style.space(1)
  }
}
