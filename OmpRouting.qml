pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Commons as Commons
// The OMP ROUTING block under the account rows: omp's next account and why, the share at which another account
// takes over, and one warning. The lines are accountState(...).routing: one {text, tooltip} or null per line.
// Three fixed slots keep the height still while their text changes; each line is one line, elided, with its
// full text as the tooltip. Hidden when there is nothing to say: no omp account, or a proxy pool.
Column {
  id: root

  property var routing: null
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  readonly property var nextLine: routing ? routing.next : null
  readonly property var switchLine: routing ? routing.switchPoint : null
  readonly property var warningLine: routing ? routing.warning : null
  readonly property string switchTooltip: "Running sessions keep their account while active."

  visible: !!(nextLine || switchLine || warningLine)
  spacing: Style.spacing.xs

  PlainText {
    objectName: "ompRoutingHeading"
    width: root.width
    text: "OMP ROUTING"
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  PlainText {
    objectName: "ompRoutingLine-0"
    width: root.width
    // A space keeps the slot's height while the line is empty.
    text: root.nextLine ? root.nextLine.text : " "
    elide: Text.ElideRight
    maximumLineCount: 1
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      ToolTip.visible: containsMouse && !!root.nextLine
      ToolTip.text: root.nextLine ? root.nextLine.tooltip : ""
    }
  }

  PlainText {
    objectName: "ompRoutingLine-1"
    width: root.width
    text: root.switchLine ? root.switchLine.text : " "
    elide: Text.ElideRight
    maximumLineCount: 1
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.7)
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption

    MouseArea {
      id: switchHover
      objectName: "ompRoutingSwitchHover"
      anchors.fill: parent
      hoverEnabled: true
      ToolTip.visible: containsMouse && !!root.switchLine
      ToolTip.text: root.switchLine ? root.switchLine.tooltip + "\n" + root.switchTooltip : ""
    }
  }

  PlainText {
    objectName: "ompRoutingLine-2"
    width: root.width
    text: root.warningLine ? root.warningLine.text : " "
    elide: Text.ElideRight
    maximumLineCount: 1
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      ToolTip.visible: containsMouse && !!root.warningLine
      ToolTip.text: root.warningLine ? root.warningLine.tooltip : ""
    }
  }
}
