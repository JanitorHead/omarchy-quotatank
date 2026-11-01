pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import "UsageLogic.js" as UsageLogic

// An account's two limits at a glance: its short window and its main long one, each as a tag, a thin
// meter of Display → Meter style and the figure on the chosen side ("5h ▬▬▬ 72%", "7d ▬▬▬ 31%"). While the
// account spends, the meters move as the style's row variant says (MeterProjection.qml: a bright tick runs
// to where this pace takes the limit by its reset).
Column {
  id: root

  property var account: null
  property string quotaMode: "Used"
  property bool spending: false
  property real nowSeconds: 0
  // When omp last sent a request for this account (Unix seconds, 0 when unknown).
  property real requestAt: 0
  property string meterStyle: "projection"
  // Thresholds on what is left, as the panel's settings hold them.
  property real warningThreshold: 25
  property real criticalThreshold: 10
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family
  property var motion: null

  readonly property var meterRows: {
    var pair = UsageLogic.accountMeterRows(root.account)
    var rows = []
    if (pair.short) rows.push(pair.short)
    if (pair.long) rows.push(pair.long)
    return rows
  }

  spacing: Style.spacing.xs

  FontMetrics {
    id: captionMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Repeater {
    model: root.meterRows.length

    Item {
      id: meterRow
      required property int index
      readonly property var row: root.meterRows[index] || null
      readonly property real remaining: UsageLogic.windowRemaining(row) === null ? 100 : UsageLogic.windowRemaining(row)
      readonly property bool stressed: remaining <= root.warningThreshold
      // Meter host contract (MeterProjection.qml).
      readonly property LimitModel model: LimitModel {
        window: meterRow.row
        nowSeconds: root.nowSeconds
        quotaMode: root.quotaMode
        spending: root.spending
        requestAt: root.requestAt
      }
      readonly property var motion: root.motion
      readonly property color tone: stressed ? root.urgent : root.foreground
      readonly property color foreground: root.foreground
      readonly property color urgent: root.urgent
      readonly property color dim: Qt.darker(root.foreground, 1.55)
      readonly property bool markShown: false
      readonly property string fontFamily: root.fontFamily

      objectName: "accountMeter-" + index
      width: root.width
      height: Math.max(tag.implicitHeight, figure.implicitHeight, meterView.height)

      PlainText {
        id: tag
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: captionMetrics.advanceWidth("30d")
        text: UsageLogic.rowPeriodTag(meterRow.row) || "—"
        color: Qt.darker(root.foreground, 1.55)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      MeterView {
        id: meterView
        objectName: "accountMeterView-" + meterRow.index
        anchors.left: tag.right
        anchors.leftMargin: Style.spacing.sm
        anchors.right: figure.left
        anchors.rightMargin: Style.spacing.sm
        anchors.verticalCenter: parent.verticalCenter
        host: meterRow
        variant: "row"
        styleId: root.meterStyle
      }

      PlainText {
        id: figure
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: captionMetrics.advanceWidth("100%")
        horizontalAlignment: Text.AlignRight
        text: UsageLogic.windowUsed(meterRow.row) === null ? "—" : UsageLogic.compactPercent(UsageLogic.windowUsed(meterRow.row), root.quotaMode) + "%"
        color: meterRow.stressed ? root.urgent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
}
