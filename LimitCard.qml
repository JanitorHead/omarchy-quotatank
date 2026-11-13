pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// One quota window: label, used or remaining figure, the meter of Display → Meter style, reset line and
// where this pace takes the limit. Severity and reset text are computed by the panel, which owns
// thresholds and the clock. Every style shares this frame; only the meter between header and footer changes.
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
  // The account the window belongs to (its subscription end bounds the leftover).
  property var account: null
  property string clockFormat: "HH:mm"
  property var motion: null
  // The account is spending now (UsageLogic.spendingNow), when its reading was taken and when omp last
  // sent a request for it (Unix seconds): the meter moves while it spends, the live figure extrapolates.
  property bool spending: false
  property real readingAt: 0
  property real requestAt: 0
  // Display → Live figure: the figure carries two decimals that climb with the current rate.
  property bool liveFigure: false
  // Display → Meter style (UsageLogic.METER_STYLES id).
  property string meterStyle: "projection"

  readonly property LimitModel model: LimitModel {
    window: root.window
    account: root.account
    nowSeconds: root.nowSeconds
    quotaMode: root.quotaMode
    spending: root.spending
    readingAt: root.readingAt
    requestAt: root.requestAt
  }
  readonly property var pace: model.pace
  readonly property var forecast: model.forecast
  readonly property var forecastSegment: model.forecastSegment
  readonly property var live: model.live
  readonly property real liveShown: model.liveShown
  readonly property bool figureLive: root.liveFigure && root.known && !!root.forecast
  // The live figure in hundredths, so the whole part and the decimals never disagree.
  readonly property int liveHundredths: Math.floor(Math.max(0, root.liveShown) * 100 + 1e-6)
  // The meter draws a forecast (the Limits forecast hint follows this).
  readonly property bool forecastShown: model.forecastShown
  readonly property var verdict: UsageLogic.forecastText(root.forecast, root.quotaMode, root.clock, model.leftover)
  readonly property var shown: model.shown
  readonly property bool known: model.known
  readonly property alias meter: meterView.item
  readonly property bool stressed: severity === "warning" || severity === "critical"
  // Meter host contract (MeterProjection.qml): the fill colour, and the pace tick while the pointer is on the meter.
  readonly property color tone: root.stressed ? root.urgent : root.providerColor
  readonly property bool markShown: meterMouse.containsMouse
  // Hover scrub over the meter: a guide follows the pointer and a readout says what that point means.
  readonly property bool scrubbing: meterMouse.containsMouse && root.window !== null && root.known && meterView.width > 0
  readonly property real scrubX: Math.max(0, Math.min(meterView.width, meterMouse.mouseX))
  readonly property real scrubFraction: meterView.width > 0 ? root.scrubX / meterView.width : 0
  readonly property bool scrubOnTick: root.model.markValue >= 0
    && Math.abs(root.scrubX - root.model.markValue * meterView.width) <= Style.space(4)
  // A meter whose x is not the quota's share (Burn chart: x is time) answers itself with `scrubTextAt(fraction)`.
  readonly property bool meterScrubs: !!root.meter && typeof root.meter.scrubTextAt === "function"
  readonly property string scrubText: !root.scrubbing ? ""
    : root.meterScrubs ? root.meter.scrubTextAt(root.scrubFraction)
    : root.scrubOnTick && UsageLogic.paceShowsMark(root.pace)
      ? "now " + root.clock(root.nowSeconds) + " · " + UsageLogic.expectedText(root.pace, root.quotaMode)
        + " · " + UsageLogic.paceBadgeText(root.pace)
      : UsageLogic.scrubText(UsageLogic.meterScrub(root.window, root.scrubFraction * 100, root.quotaMode, root.nowSeconds),
        root.quotaMode, root.clock)

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

    // Label left, the figure right: the same for every meter style.
    Item {
      id: headerRow
      width: parent.width
      implicitHeight: Math.max(limitLabel.implicitHeight, figureGroup.implicitHeight)

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

      // The figure: "72%", or with Live figure "72" and ".03%" rolling as the estimate climbs.
      Item {
        id: figureGroup
        anchors.right: parent.right
        width: limitFigure.implicitWidth + (limitDecimals.visible ? limitDecimals.implicitWidth : 0)
          + (limitUnit.visible ? limitUnit.implicitWidth + Style.spacing.sm : 0)
        implicitHeight: limitFigure.implicitHeight
        height: implicitHeight
        baselineOffset: limitFigure.baselineOffset

        RollingNumber {
          id: limitFigure
          objectName: "limitFigure"
          anchors.left: parent.left
          text: !root.known ? "—"
            : root.figureLive ? String(Math.floor(root.liveHundredths / 100))
            : UsageLogic.formatPercent(root.shown) + "%"
          color: root.stressed ? root.urgent : root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.heading
          font.bold: true
          motion: root.motion
        }

        RollingNumber {
          id: limitDecimals
          objectName: "limitDecimals"
          visible: root.figureLive
          anchors.left: limitFigure.right
          anchors.baseline: limitFigure.baseline
          text: {
            var cents = root.liveHundredths % 100
            return "." + (cents < 10 ? "0" : "") + cents + "%"
          }
          color: root.stressed ? root.urgent : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
          motion: root.motion
        }

        PlainText {
          id: limitUnit
          visible: root.known
          anchors.left: limitDecimals.visible ? limitDecimals.right : limitFigure.right
          anchors.leftMargin: Style.spacing.sm
          anchors.baseline: limitFigure.baseline
          text: root.quotaMode === "Remaining" ? "left" : "used"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }

    MeterView {
      id: meterView
      visible: root.model.hasMeter
      width: parent.width
      host: root
      variant: "card"
      styleId: root.meterStyle

      MouseArea {
        id: meterMouse
        z: 2
        anchors.fill: parent
        anchors.topMargin: -Style.space(2)
        anchors.bottomMargin: -Style.space(2)
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        cursorShape: root.window !== null && root.known ? Qt.CrossCursor : Qt.ArrowCursor
      }

      Rectangle {
        objectName: "meterScrubGuide"
        z: 3
        visible: root.scrubbing
        x: Math.round(root.scrubX - Style.spacing.hairline / 2)
        y: -Style.space(4)
        width: Style.spacing.hairline
        height: parent.height + Style.space(8)
        color: Commons.Color.accent
      }
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
    readonly property real anchorX: meterView.x + limitContent.x + root.scrubX
    visible: root.scrubText !== ""
    z: 2
    x: Math.round(Math.max(0, Math.min(root.width - width, anchorX - width / 2)))
    y: Math.round(limitContent.y + meterView.y - height - Style.spacing.md - Style.space(4))
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
