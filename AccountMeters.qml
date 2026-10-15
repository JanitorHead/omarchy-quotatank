pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import "UsageLogic.js" as UsageLogic

// An account's two limits at a glance: its short window and its main long one, each as a tag, a thin
// meter and the figure on the chosen side ("5h ▬▬▬ 72%", "7d ▬▬▬ 31%").
Column {
  id: root

  property var account: null
  property string quotaMode: "Used"
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

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

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
      readonly property real shown: UsageLogic.sideOfUsed(UsageLogic.windowUsed(row) || 0, root.quotaMode)
      readonly property real remaining: UsageLogic.windowRemaining(row) === null ? 100 : UsageLogic.windowRemaining(row)
      readonly property bool stressed: remaining <= root.warningThreshold
      readonly property color tone: stressed ? root.urgent : root.foreground

      objectName: "accountMeter-" + index
      width: root.width
      height: Math.max(tag.implicitHeight, figure.implicitHeight)

      Text {
        id: tag
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: captionMetrics.advanceWidth("30d")
        text: UsageLogic.rowPeriodTag(meterRow.row) || "—"
        color: Qt.darker(root.foreground, 1.55)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      Item {
        anchors.left: tag.right
        anchors.leftMargin: Style.spacing.sm
        anchors.right: figure.left
        anchors.rightMargin: Style.spacing.sm
        anchors.verticalCenter: parent.verticalCenter
        height: Style.space(3)

        Rectangle {
          anchors.fill: parent
          color: root.alpha(root.foreground, 0.14)
        }

        Rectangle {
          width: Math.round(parent.width * Math.max(0, Math.min(1, meterRow.shown / 100)))
          height: parent.height
          color: meterRow.tone

          Behavior on width {
            NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
          }
        }
      }

      Text {
        id: figure
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: captionMetrics.advanceWidth("100%")
        horizontalAlignment: Text.AlignRight
        text: UsageLogic.windowUsed(meterRow.row) === null ? "—" : Math.round(meterRow.shown) + "%"
        color: meterRow.stressed ? root.urgent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
}
