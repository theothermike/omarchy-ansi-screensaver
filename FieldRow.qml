import QtQuick
import qs.Commons

// Label + description on the left, a control slot on the right.
Item {
  id: root
  property string label: ""
  property string description: ""
  property color foreground: Color.menu.text
  property color muted: Color.muted
  property real controlWidth: Style.space(300)
  default property alias content: slot.data

  width: parent ? parent.width : Style.space(600)
  height: Math.max(labels.height, slot.childrenRect.height) + Style.spacing.sm * 2

  Column {
    id: labels
    anchors.left: parent.left
    anchors.verticalCenter: parent.verticalCenter
    width: parent.width - root.controlWidth - Style.spacing.controlGap
    spacing: Style.spacing.xxs
    Text { text: root.label; color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body; width: parent.width; elide: Text.ElideRight }
    Text { visible: root.description !== ""; text: root.description; color: root.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption; width: parent.width; wrapMode: Text.WordWrap }
  }
  Item {
    id: slot
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    width: root.controlWidth
    height: childrenRect.height
  }
}
