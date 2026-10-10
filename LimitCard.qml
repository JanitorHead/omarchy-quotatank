pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// One quota window: label, used or remaining figure, block meter, reset line and detail.
// Severity and reset text are computed by the panel, which owns thresholds and the clock.
Ui.BorderSurface {
  id: root

  property var window: null
  property string severity: "none"
  property string resetLabel: ""
  property string quotaMode: "Used"
  property color foreground: Color.foreground
  property color urgent: Color.urgent
  property color dim: Qt.darker(foreground, 1.55)
  property string fontFamily: Style.font.family
  property real cardRadius: 0
  property real nowSeconds: 0
  readonly property var pace: UsageLogic.paceForWindow(root.window, root.nowSeconds)

  readonly property bool stressed: severity === "warning" || severity === "critical"

  function alpha(color, opacity) {
    return Qt.rgba(color.r, color.g, color.b, opacity)
  }

  implicitHeight: limitContent.implicitHeight + contentTopInset + contentBottomInset
  color: severity === "critical"
    ? alpha(root.urgent, 0.09)
    : Style.normalFillFor(root.foreground, Color.accent, root.urgent)
  borderSpec: stressed
    ? Border.flat(alpha(root.urgent, severity === "critical" ? 0.45 : 0.28), Style.spacing.hairline)
    : Border.controlSpec("normal", root.foreground, Color.accent, root.urgent)
  padding: Style.spacing.xxl
  radius: root.cardRadius

  Column {
    id: limitContent
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.leftMargin: root.contentLeftInset
    anchors.rightMargin: root.contentRightInset
    anchors.topMargin: root.contentTopInset
    spacing: Style.spacing.md

    Item {
      width: parent.width
      implicitHeight: Math.max(limitLabel.implicitHeight, limitPercent.implicitHeight)

      Text {
        id: limitLabel
        anchors.left: parent.left
        anchors.right: limitPercent.left
        anchors.rightMargin: Style.spacing.controlGap
        anchors.verticalCenter: parent.verticalCenter
        text: root.window ? String(root.window.label || "Usage limit") : ""
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        id: limitPercent
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        readonly property var shown: root.quotaMode === "Remaining"
          ? UsageLogic.windowRemaining(root.window)
          : UsageLogic.windowUsed(root.window)
        text: UsageLogic.quotaText(shown, root.quotaMode) || "—"
        color: root.stressed ? root.urgent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: root.stressed
      }
    }

    BlockMeter {
      id: meter
      visible: UsageLogic.windowUsed(root.window) !== null
      width: parent.width
      value: UsageLogic.windowUsed(root.window) / 100
      fillColor: root.stressed ? root.urgent : root.foreground
      trackColor: root.alpha(root.foreground, 0.14)
      markValue: UsageLogic.paceShowsMark(root.pace) ? root.pace.expected / 100 : -1
      markAhead: UsageLogic.paceShowsMark(root.pace) && root.pace.used > root.pace.expected
      markColor: root.foreground
      markTooltip: UsageLogic.paceTickText(root.pace)
    }

    Text {
      visible: text !== ""
      width: parent.width
      text: root.resetLabel
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }

    Text {
      id: paceLine
      visible: root.window !== null
      width: parent.width
      text: UsageLogic.paceStatusText(root.pace)
      color: root.pace && root.pace.runsOut ? root.urgent : root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }

    Text {
      visible: text !== ""
      width: parent.width
      text: root.window ? String(root.window.detail || "") : ""
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }
  }
}
