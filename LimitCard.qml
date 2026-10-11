pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
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
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property color providerColor: foreground
  property color dim: Qt.darker(foreground, 1.55)
  property string fontFamily: Style.font.family
  property real cardRadius: 0
  property real nowSeconds: 0
  property string clockFormat: "HH:mm"
  readonly property var pace: UsageLogic.paceForWindow(root.window, root.nowSeconds)

  readonly property bool stressed: severity === "warning" || severity === "critical"

  function alpha(color, opacity) {
    return Qt.rgba(color.r, color.g, color.b, opacity)
  }

  implicitHeight: limitContent.implicitHeight + contentTopInset + contentBottomInset
  color: severity === "critical"
    ? alpha(root.urgent, 0.09)
    : Style.normalFillFor(root.foreground, Commons.Color.accent, root.urgent)
  borderSpec: stressed
    ? Border.flat(alpha(root.urgent, severity === "critical" ? 0.45 : 0.28), Style.spacing.hairline)
    : Border.controlSpec("normal", root.foreground, Commons.Color.accent, root.urgent)
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
      implicitHeight: Math.max(limitLabel.implicitHeight, limitFigure.implicitHeight)

      Text {
        id: limitLabel
        anchors.left: parent.left
        anchors.right: figureGroup.left
        anchors.rightMargin: Style.spacing.controlGap
        anchors.baseline: figureGroup.baseline
        text: root.window ? String(root.window.label || "Usage limit") : ""
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }

      Item {
        id: figureGroup
        anchors.right: parent.right
        width: limitFigure.implicitWidth + limitUnit.implicitWidth + Style.spacing.sm
        height: limitFigure.implicitHeight
        baselineOffset: limitFigure.baselineOffset
        readonly property var shown: root.quotaMode === "Remaining"
          ? UsageLogic.windowRemaining(root.window)
          : UsageLogic.windowUsed(root.window)

        Text {
          id: limitFigure
          anchors.left: parent.left
          text: figureGroup.shown === null || figureGroup.shown === undefined ? "—" : UsageLogic.formatPercent(figureGroup.shown) + "%"
          color: root.stressed ? root.urgent : root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.heading
          font.bold: true
        }

        Text {
          id: limitUnit
          anchors.left: limitFigure.right
          anchors.leftMargin: Style.spacing.sm
          anchors.baseline: limitFigure.baseline
          text: root.quotaMode === "Remaining" ? "left" : "used"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }

    BlockMeter {
      id: meter
      visible: UsageLogic.meterFill(root.window, root.quotaMode) !== null
      width: parent.width
      height: Style.space(12)
      value: UsageLogic.meterFill(root.window, root.quotaMode) || 0
      fillColor: root.stressed ? root.urgent : root.providerColor
      trackColor: root.alpha(root.foreground, 0.14)
      markValue: UsageLogic.meterMark(root.pace, root.quotaMode)
      markAhead: UsageLogic.paceShowsMark(root.pace) && root.pace.used > root.pace.expected
      markColor: root.foreground
      markTooltip: {
        var tick = UsageLogic.paceTickText(root.pace, root.quotaMode)
        return tick === "" ? "" : "Now " + Qt.formatTime(new Date(root.nowSeconds * 1000), root.clockFormat) + "\n" + tick
      }
    }

    Item {
      width: parent.width
      implicitHeight: Math.max(resetText.implicitHeight, paceBadge.visible ? paceBadge.height : 0)

      Text {
        id: resetText
        anchors.left: parent.left
        anchors.right: paceBadge.visible ? paceBadge.left : parent.right
        anchors.rightMargin: Style.spacing.controlGap
        anchors.verticalCenter: parent.verticalCenter
        text: root.resetLabel
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }

      // Ahead or behind pace in points, at a glance; the line below says what that means.
      Rectangle {
        id: paceBadge
        readonly property string label: UsageLogic.paceBadgeText(root.pace)
        readonly property bool hot: !!root.pace && root.pace.runsOut === true
        visible: label !== ""
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: badgeText.implicitWidth + Style.spacing.lg * 2
        height: badgeText.implicitHeight + Style.spacing.sm
        radius: height / 2
        color: root.alpha(hot ? root.urgent : root.foreground, hot ? 0.16 : 0.08)
        border.width: Style.spacing.hairline
        border.color: root.alpha(hot ? root.urgent : root.foreground, hot ? 0.55 : 0.22)

        Text {
          id: badgeText
          anchors.centerIn: parent
          text: paceBadge.label
          color: paceBadge.hot ? root.urgent : root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.weight: Font.DemiBold
        }
      }
    }

    Text {
      id: paceLine
      visible: root.window !== null
      width: parent.width
      text: UsageLogic.paceStatusText(root.pace, root.quotaMode)
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
