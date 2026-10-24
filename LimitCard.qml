pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// One quota window: label, used or remaining figure, block meter, reset line and where this pace
// takes the limit. Severity and reset text are computed by the panel, which owns thresholds and the clock.
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
  property var motion: null
  // Thresholds on what is left, as the panel's settings hold them; the meter marks both.
  property real warningThreshold: 25
  property real criticalThreshold: 10
  readonly property var pace: UsageLogic.paceForWindow(root.window, root.nowSeconds)
  readonly property var forecast: UsageLogic.windowForecast(root.window, root.nowSeconds)
  readonly property var forecastSegment: UsageLogic.forecastSegment(root.forecast, root.quotaMode)
  readonly property var verdict: UsageLogic.forecastText(root.forecast, root.quotaMode, root.clock)
  readonly property var shown: root.quotaMode === "Remaining"
    ? UsageLogic.windowRemaining(root.window)
    : UsageLogic.windowUsed(root.window)
  readonly property bool known: shown !== null && shown !== undefined
  readonly property alias meter: blockMeter
  readonly property string scrubText: !blockMeter.scrubbing ? ""
    : blockMeter.scrubOnTick && UsageLogic.paceShowsMark(root.pace)
      ? "now " + root.clock(root.nowSeconds) + " · " + UsageLogic.expectedText(root.pace, root.quotaMode)
        + " · " + UsageLogic.paceBadgeText(root.pace)
      : UsageLogic.scrubText(UsageLogic.meterScrub(root.window, blockMeter.scrubFraction * 100, root.quotaMode, root.nowSeconds),
        root.quotaMode, root.clock)

  readonly property bool stressed: severity === "warning" || severity === "critical"

  function alpha(color, opacity) {
    return Qt.rgba(color.r, color.g, color.b, opacity)
  }

  // Clock times follow the panel's one rule (UsageLogic.clockPattern): the time today, the weekday
  // within the week, the date further out.
  function clock(epochSeconds) {
    var seconds = Number(epochSeconds)
    if (!isFinite(seconds)) return ""
    return Qt.formatDateTime(new Date(seconds * 1000), UsageLogic.clockPattern(seconds, root.nowSeconds, root.clockFormat))
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

  Accessible.role: Accessible.StaticText
  Accessible.name: (root.window ? String(root.window.label || "Usage limit") : "")
    + (root.known ? ", " + UsageLogic.formatPercent(root.shown) + "% " + (root.quotaMode === "Remaining" ? "left" : "used") : "")
    + (root.verdict.text !== "" ? ", " + root.verdict.text : "")

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

      PlainText {
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
        width: limitFigure.implicitWidth + (limitUnit.visible ? limitUnit.implicitWidth + Style.spacing.sm : 0)
        height: limitFigure.implicitHeight
        baselineOffset: limitFigure.baselineOffset

        RollingNumber {
          id: limitFigure
          objectName: "limitFigure"
          anchors.left: parent.left
          text: root.known ? UsageLogic.formatPercent(root.shown) + "%" : "—"
          color: root.stressed ? root.urgent : root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.heading
          font.bold: true
          motion: root.motion
        }

        PlainText {
          id: limitUnit
          visible: root.known
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
      id: blockMeter
      objectName: "limitMeter"
      visible: UsageLogic.meterFill(root.window, root.quotaMode) !== null
      width: parent.width
      height: Style.space(12)
      motion: root.motion
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
      // Thresholds hold what is left; the meter shows the chosen side.
      warningMark: UsageLogic.sideOfUsed(100 - root.warningThreshold, root.quotaMode) / 100
      criticalMark: UsageLogic.sideOfUsed(100 - root.criticalThreshold, root.quotaMode) / 100
      warningMarkColor: root.alpha(root.foreground, 0.34)
      criticalMarkColor: root.alpha(root.urgent, 0.62)
      forecastFrom: root.forecastSegment ? root.forecastSegment.from : -1
      forecastTo: root.forecastSegment ? root.forecastSegment.to : -1
      forecastColor: root.forecastSegment && root.forecastSegment.runsOut
        ? root.alpha(root.urgent, 0.85) : root.alpha(root.foreground, 0.35)
      scrubEnabled: root.window !== null && root.known
      guideColor: Commons.Color.accent
    }

    // Reset line left, the verdict right; when both do not fit on one line the verdict moves under it.
    Item {
      id: footer
      readonly property bool stacked: verdictText.visible && resetText.text !== ""
        && resetText.implicitWidth + Style.spacing.controlGap + verdictText.implicitWidth > width
      width: parent.width
      implicitHeight: stacked ? resetText.implicitHeight + Style.spacing.xxs + verdictText.implicitHeight
        : Math.max(resetText.implicitHeight, verdictText.visible ? verdictText.implicitHeight : 0)

      PlainText {
        id: resetText
        x: 0
        y: footer.stacked ? 0 : Math.round((footer.height - height) / 2)
        width: footer.stacked || !verdictText.visible ? footer.width
          : Math.max(0, footer.width - verdictText.width - Style.spacing.controlGap)
        text: root.resetLabel
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }

      // Where this pace takes the limit: "runs out 17:50 · pace 52%" or "lasts until reset". Hovering it
      // explains the tick and the projection (UsageLogic.PACING_LEGEND).
      PlainText {
        id: verdictText
        objectName: "limitVerdict"
        visible: text !== ""
        x: footer.width - width
        y: footer.stacked ? resetText.implicitHeight + Style.spacing.xxs : Math.round((footer.height - height) / 2)
        width: Math.min(implicitWidth, footer.width)
        // Usage the provider does not report has no pace either; say so rather than suggest zero.
        text: !root.known && root.window !== null ? "usage not reported" : root.verdict.text
        color: root.verdict.urgent ? root.urgent : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.weight: root.verdict.urgent ? Font.DemiBold : Font.Normal
        horizontalAlignment: Text.AlignRight
        elide: Text.ElideLeft

        HoverHandler {
          id: verdictHover
          enabled: root.known
          cursorShape: Qt.WhatsThisCursor
        }

        Ui.PanelToolTip {
          visible: verdictHover.hovered
          text: UsageLogic.PACING_LEGEND
        }
      }
    }

    PlainText {
      visible: text !== ""
      width: parent.width
      text: root.window ? String(root.window.detail || "") : ""
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }
  }

  // Scrub readout: what the hovered point on the meter means, just above it.
  Ui.BorderSurface {
    id: scrubChip
    objectName: "limitScrubReadout"
    readonly property real anchorX: blockMeter.x + limitContent.x + blockMeter.scrubX
    visible: root.scrubText !== ""
    z: 2
    x: Math.round(Math.max(0, Math.min(root.width - width, anchorX - width / 2)))
    y: Math.round(limitContent.y + blockMeter.y - height - Style.spacing.md - blockMeter.tickOvershoot * 2)
    implicitWidth: scrubLabel.implicitWidth + contentLeftInset + contentRightInset
    implicitHeight: scrubLabel.implicitHeight + contentTopInset + contentBottomInset
    width: implicitWidth
    height: implicitHeight
    color: Commons.Color.tooltip.background
    borderSpec: Border.flat(root.alpha(root.foreground, 0.24), Style.spacing.hairline)
    radius: Style.cornerRadius
    leftPadding: Style.spacing.md
    rightPadding: Style.spacing.md
    topPadding: Style.spacing.xxs
    bottomPadding: Style.spacing.xxs

    PlainText {
      id: scrubLabel
      x: scrubChip.contentLeftInset
      y: scrubChip.contentTopInset
      text: root.scrubText
      color: Commons.Color.tooltip.text
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }
}
