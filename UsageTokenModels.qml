pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// Token activity per model for the provider whose Limits are on screen, with a
// bar behind each row scaled to the heaviest model. The numbers come from the
// same estimated-cost scan the Costs tab uses, so both views always agree.
Item {
  id: root

  property var models: []
  property string periodLabel: ""
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  // Panel's Motion; without one the bars move at once, as with reduced motion.
  property var motion: null

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property var rows: UsageLogic.listOrEmpty(models)
  readonly property real peak: {
    var highest = 0
    for (var i = 0; i < rows.length; i++) highest = Math.max(highest, Number(rows[i].totalTokens || 0))
    return highest
  }

  implicitHeight: content.implicitHeight

  function alpha(color, opacity) {
    return Qt.rgba(color.r, color.g, color.b, opacity)
  }

  function hasCost(row) {
    return !!row && row.costUsd !== null && row.costUsd !== undefined && isFinite(Number(row.costUsd))
  }

  function pricingNote(row) {
    if (!hasCost(row)) return "Pricing unavailable · tokens are still included"
    if (String(row.costSource) === "providerReported") return "Priced by OpenCode · API estimate"
    if (String(row.costSource) === "customPriced") return "Priced by your custom rate"
    if (String(row.costSource) === "mixed") return "Estimated API value · mixed pricing sources"
    return "Estimated from the public price table"
  }

  Column {
    id: content
    width: parent.width
    spacing: Style.spacing.md

    Item {
      width: parent.width
      implicitHeight: Math.max(title.implicitHeight, period.implicitHeight)

      Ui.PanelSectionHeader {
        id: title
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: "TOKENS BY MODEL"
        foreground: root.foreground
        fontFamily: root.fontFamily
      }

      Text {
        id: period
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: root.periodLabel
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Repeater {
      model: root.rows

      delegate: Item {
        id: modelRow
        required property var modelData
        required property int index
        objectName: "limitModel-" + index
        width: content.width
        implicitHeight: rowBody.implicitHeight
          + (root.hasCost(modelRow.modelData) ? 0 : otherRow.implicitHeight + Style.spacing.labelGap)

        Item {
          id: rowBody
          width: parent.width
          implicitHeight: Style.spacing.controlHeight

          // The bar sits behind the row, sized against the heaviest model.
          Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: root.peak > 0
              ? Math.max(0, Math.min(1, Number(modelRow.modelData.totalTokens || 0) / root.peak)) * parent.width
              : 0
            height: parent.height
            radius: Style.space(3)
            color: root.alpha(root.foreground, 0.10)

            Behavior on width {
              NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
            }
          }

          Text {
            id: modelName
            anchors.left: parent.left
            anchors.leftMargin: Style.spacing.md
            anchors.right: modelValue.left
            anchors.rightMargin: Style.spacing.controlGap
            anchors.verticalCenter: parent.verticalCenter
            text: String(modelRow.modelData.model || "Unknown model")
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            elide: Text.ElideRight
          }

          Text {
            id: modelValue
            anchors.right: parent.right
            anchors.rightMargin: Style.spacing.md
            anchors.verticalCenter: parent.verticalCenter
            text: UsageLogic.formatTokens(modelRow.modelData.totalTokens)
              + " · " + UsageLogic.formatUsd(root.hasCost(modelRow.modelData) ? modelRow.modelData.costUsd : null)
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.weight: Font.Medium
          }
        }

        Text {
          id: otherRow
          width: parent.width
          anchors.top: rowBody.bottom
          visible: !root.hasCost(modelRow.modelData)
          text: root.pricingNote(modelRow.modelData)
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }
}
