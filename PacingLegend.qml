pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// One Pacing row for all limit cards of a provider: label, ⓘ badge, and the legend on hover or click.
// Each card keeps only its own status line; what the tick and projection mean is said once here.
Row {
  id: root

  property color foreground: Color.foreground
  property color dim: Qt.darker(foreground, 1.55)
  property string fontFamily: Style.font.family
  // Legend pinned open by a click on the badge; a second click closes it.
  property bool paceOpen: false

  function alpha(color, opacity) {
    return Qt.rgba(color.r, color.g, color.b, opacity)
  }

  spacing: Style.spacing.controlGap

  Text {
    id: paceLabel
    anchors.verticalCenter: parent.verticalCenter
    text: "Pacing"
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Rectangle {
    id: paceInfo
    anchors.verticalCenter: parent.verticalCenter
    height: paceLabel.implicitHeight
    width: height
    radius: height / 2
    color: paceInfoMouse.containsMouse || root.paceOpen ? root.alpha(root.foreground, 0.14) : "transparent"
    border.color: root.dim
    border.width: Style.normalBorderWidth

    Text {
      anchors.centerIn: parent
      text: "i"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }

    MouseArea {
      id: paceInfoMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.paceOpen = !root.paceOpen
    }

    Ui.PanelToolTip {
      visible: paceInfoMouse.containsMouse || root.paceOpen
      text: UsageLogic.PACING_LEGEND
    }
  }
}
