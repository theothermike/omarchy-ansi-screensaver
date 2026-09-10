import QtQuick
import qs.Commons
import qs.Ui

// Progress strip for the one long-running CLI job (add --all, thumbs, fetch).
Item {
  id: root
  property var job: null
  property var service: null
  property color foreground: Color.menu.text
  property color accent: Color.accent
  property color muted: Color.muted

  visible: job !== null
  width: parent ? parent.width : 0
  height: visible ? Style.space(26) : 0

  Rectangle {
    anchors.left: parent.left
    anchors.right: cancel.left
    anchors.rightMargin: Style.spacing.controlGap
    anchors.verticalCenter: parent.verticalCenter
    height: Math.max(4, Style.space(6))
    radius: height / 2
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.15)
    Rectangle {
      width: parent.width * (root.job && root.job.total ? Math.min(1, root.job.n / root.job.total) : 0.05)
      height: parent.height
      radius: parent.radius
      color: root.accent
      Behavior on width { NumberAnimation { duration: 120 } }
    }
  }
  Text {
    anchors.left: parent.left
    anchors.bottom: parent.bottom
    text: root.job ? (root.job.name + " · " + root.job.n + (root.job.total ? "/" + root.job.total : "") + "  " + (root.job.label || "")) : ""
    color: root.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    elide: Text.ElideRight
    width: parent.width - cancel.width - Style.spacing.controlGap
  }
  Button {
    id: cancel
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    text: "Cancel"
    bordered: true
    fontSize: Style.font.caption
    foreground: root.foreground
    accent: root.accent
    onClicked: if (root.service) root.service.cancelJob()
  }
}
