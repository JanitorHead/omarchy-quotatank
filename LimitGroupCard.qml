pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// One card for every limit of the account, for the group meter styles (Tanks, Gauges, Rings, Compact).
// The style draws the limits side by side, nested or as lines; each builds a LimitModel per window from
// what this host gives it (see MeterProjection.qml for the shared part of the contract).
Ui.BorderSurface {
  id: root

  // The account's windows, in card order (shortest first).
  property var windows: []
  property string quotaMode: "Used"
  // The account the windows belong to: its subscription end bounds each limit's leftover (LimitModel.account).
  property var account: null
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property color providerColor: foreground
  property color dim: Qt.darker(foreground, 1.55)
  property string fontFamily: Style.font.family
  property real cardRadius: 0
  property real nowSeconds: 0
  property string clockFormat: "HH:mm"
  property var motion: null
  property bool spending: false
  property real readingAt: 0
  property real requestAt: 0
  property bool liveFigure: false
  property string meterStyle: "tanks"
  // The panel's severity and reset line for a window.
  property var severityOf: function(row) { return "none" }
  property var resetLabelOf: function(row) { return "" }

  // Host contract for group styles: `markShown` (pace ticks), `tone` (the provider colour) and the helpers
  // below; `model` stays null, each window gets its own LimitModel.
  readonly property var model: null
  readonly property color tone: root.providerColor
  readonly property bool markShown: groupHover.hovered
  readonly property bool anyStressed: {
    for (var i = 0; i < root.windows.length; i++) if (root.stressed(root.windows[i])) return true
    return false
  }
  readonly property bool anyCritical: {
    for (var i = 0; i < root.windows.length; i++) if (root.severityOf(root.windows[i]) === "critical") return true
    return false
  }

  function alpha(color, opacity) {
    return Qt.rgba(color.r, color.g, color.b, opacity)
  }

  function clock(epochSeconds) {
    var seconds = Number(epochSeconds)
    if (!isFinite(seconds)) return ""
    return Qt.formatDateTime(new Date(seconds * 1000), UsageLogic.clockPattern(seconds, root.nowSeconds, root.clockFormat))
  }

  function stressed(row) {
    var severity = root.severityOf(row)
    return severity === "warning" || severity === "critical"
  }

  // Fill colour of one window: urgent at a threshold, else the provider colour.
  function toneOf(row) {
    return root.stressed(row) ? root.urgent : root.providerColor
  }

  // Short tag ("5h", "7d") or the label when the period is unknown.
  function tagOf(row) {
    return UsageLogic.rowPeriodTag(row) || String(row && row.label || "")
  }

  function labelOf(row) {
    return String(row && row.label || "Usage limit")
  }

  // The figure of a LimitModel on the chosen side: "72%", or "72.03%" with Live figure.
  function figureText(limit) {
    if (!limit || !limit.known) return "—"
    if (root.liveFigure && !!limit.forecast) return (Math.floor(Math.max(0, limit.liveShown) * 100 + 1e-6) / 100).toFixed(2) + "%"
    return UsageLogic.formatPercent(limit.shown) + "%"
  }

  function unitText() {
    return root.quotaMode === "Remaining" ? "left" : "used"
  }

  // Where this pace takes the limit (UsageLogic.forecastText): { text, urgent }.
  function verdictOf(limit) {
    if (limit && !limit.known && limit.window) return { text: "usage not reported", urgent: false }
    return UsageLogic.forecastText(limit ? limit.forecast : null, root.quotaMode, root.clock, limit ? limit.leftover : null)
  }

  implicitHeight: meterView.implicitHeight + contentTopInset + contentBottomInset
  color: root.anyCritical ? alpha(root.urgent, 0.09) : Style.normalFillFor(root.foreground, Commons.Color.accent, root.urgent)
  borderSpec: root.anyStressed
    ? Border.flat(alpha(root.urgent, root.anyCritical ? 0.45 : 0.28), Style.spacing.hairline)
    : Border.controlSpec("normal", root.foreground, Commons.Color.accent, root.urgent)
  padding: Style.spacing.xxl
  radius: root.cardRadius

  Accessible.role: Accessible.StaticText
  Accessible.name: {
    var parts = []
    for (var i = 0; i < root.windows.length; i++) {
      var row = root.windows[i]
      var shown = root.quotaMode === "Remaining" ? UsageLogic.windowRemaining(row) : UsageLogic.windowUsed(row)
      parts.push(root.labelOf(row) + (shown === null ? "" : ", " + UsageLogic.formatPercent(shown) + "% " + root.unitText()))
    }
    return parts.join("; ")
  }

  HoverHandler { id: groupHover }

  MeterView {
    id: meterView
    objectName: "limitGroupMeter"
    x: root.contentLeftInset
    y: root.contentTopInset
    width: root.width - root.contentLeftInset - root.contentRightInset
    host: root
    variant: "group"
    styleId: root.meterStyle
  }
}
