pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import "UsageLogic.js" as UsageLogic

// The OMP ROUTING block under the account rows (UsageLogic.ompRouting): omp's next account and why, the share at
// which another account takes over, and one warning. Three fixed lines keep the height still while their text
// changes. Hidden when there is nothing to say: no omp account, or a proxy pool.
Column {
  id: root

  property var provider: null
  property real nowSeconds: 0
  property string mode: "single"
  property string extraKeys: "{}"
  property bool hideEmails: true
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  readonly property string switchTooltip: "Running sessions keep their account while active."

  readonly property var lines: UsageLogic.ompRouting(root.provider, {
    nowSeconds: root.nowSeconds, mode: root.mode, extraKeys: root.extraKeys, hideEmails: root.hideEmails })

  visible: lines.next !== "" || lines.switchPoint !== "" || lines.warning !== ""
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
    text: root.lines.next || " "
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }

  PlainText {
    objectName: "ompRoutingLine-1"
    width: root.width
    text: root.lines.switchPoint || " "
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.7)
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap

    MouseArea {
      id: switchHover
      objectName: "ompRoutingSwitchHover"
      anchors.fill: parent
      hoverEnabled: true
      ToolTip.visible: containsMouse && root.lines.switchPoint !== ""
      ToolTip.text: root.switchTooltip
    }
  }

  PlainText {
    objectName: "ompRoutingLine-2"
    width: root.width
    text: root.lines.warning || " "
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }
}
