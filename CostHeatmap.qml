pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// When the spending happens: the last 7 local days x 24 hours, each cell's strength following its
// cost (requests for Tokens, which the grid does not carry). Hovering a cell reads it out below;
// otherwise the line names the busiest hour.
Column {
  id: root

  property var heatmap: null
  property string metric: "cost"
  property string clockFormat: "HH:mm"
  property int hoveredCell: -1
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property var grid: UsageLogic.costHeatmapGrid(heatmap, metric)
  readonly property var cells: grid ? grid.cells : []
  readonly property int cellCount: cellRepeater.count
  readonly property bool hasActivity: grid !== null && grid.busiest >= 0
  readonly property int labelWidth: Math.ceil(labelMetrics.advanceWidth("Wed")) + Style.spacing.md
  readonly property int cellGap: Style.spacing.xxs
  readonly property int cellWidth: Math.max(2, Math.floor((width - labelWidth - cellGap * 23) / 24))
  readonly property int cellHeight: Math.max(Style.space(8), Math.min(cellWidth, Style.space(10)))
  readonly property string readoutText: {
    if (!grid) return ""
    if (hoveredCell >= 0 && hoveredCell < cells.length)
      return UsageLogic.costHeatmapText(cells[hoveredCell], hourLabel(cells[hoveredCell].hour))
    if (!hasActivity) return "No requests in the last 7 days"
    return "Busiest: " + UsageLogic.costHeatmapText(cells[grid.busiest], hourLabel(cells[grid.busiest].hour))
  }

  spacing: Style.spacing.sm
  Accessible.role: Accessible.Table
  Accessible.name: "Spending by hour over the last 7 days. " + readoutText

  onGridChanged: if (hoveredCell >= cells.length) hoveredCell = -1

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

  function hourLabel(hour) {
    return Qt.formatTime(new Date(2000, 0, 1, hour, 0), clockFormat)
  }

  function cellX(hour) {
    return labelWidth + Math.round(hour * (width - labelWidth - cellWidth) / 23)
  }

  function cellAt(x, y) {
    if (x < labelWidth - cellGap) return -1
    var hour = Math.max(0, Math.min(23, Math.round((x - labelWidth - cellWidth / 2) / ((width - labelWidth - cellWidth) / 23))))
    var day = Math.max(0, Math.min(6, Math.floor(y / (cellHeight + cellGap))))
    return day * 24 + hour
  }

  FontMetrics {
    id: labelMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Item {
    width: parent.width
    implicitHeight: Math.max(title.implicitHeight, range.implicitHeight)

    Ui.PanelSectionHeader {
      id: title
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      text: "WHEN"
      foreground: root.foreground
      fontFamily: root.fontFamily
    }

    PlainText {
      id: range
      anchors.right: parent.right
      anchors.baseline: title.baseline
      text: "last 7 days, by hour"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  Item {
    id: gridArea
    objectName: "costHeatmap"
    width: parent.width
    height: 7 * root.cellHeight + 6 * root.cellGap

    Repeater {
      model: root.grid ? root.grid.dayNames : []

      delegate: PlainText {
        required property string modelData
        required property int index
        y: index * (root.cellHeight + root.cellGap) + Math.round((root.cellHeight - implicitHeight) / 2)
        text: modelData
        // Today, the row still filling in, reads a step brighter.
        color: index === 6 ? root.foreground : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Repeater {
      id: cellRepeater
      model: root.cells.length

      delegate: Rectangle {
        required property int index
        readonly property var cell: root.cells[index] || null
        objectName: "costHeatCell-" + index
        x: root.cellX(index % 24)
        y: Math.floor(index / 24) * (root.cellHeight + root.cellGap)
        width: root.cellWidth
        height: root.cellHeight
        radius: Math.min(Style.cornerRadius, Style.space(2))
        color: !cell ? "transparent"
          : cell.level > 0 ? root.alpha(Commons.Color.accent, 0.14 + 0.86 * cell.level)
          : cell.unpriced && root.metric === "cost" ? root.alpha(root.urgent, 0.28)
          : root.alpha(root.foreground, 0.05)
      }
    }

    Rectangle {
      visible: root.hoveredCell >= 0 && root.hoveredCell < root.cells.length
      x: root.cellX(root.hoveredCell % 24) - Style.spacing.hairline
      y: Math.floor(root.hoveredCell / 24) * (root.cellHeight + root.cellGap) - Style.spacing.hairline
      width: root.cellWidth + Style.spacing.hairline * 2
      height: root.cellHeight + Style.spacing.hairline * 2
      radius: Math.min(Style.cornerRadius, Style.space(2))
      color: "transparent"
      border.width: Style.spacing.hairline
      border.color: root.foreground
    }

    HoverHandler {
      id: hover
      onPointChanged: if (hovered) root.hoveredCell = root.cellAt(point.position.x, point.position.y)
      onHoveredChanged: root.hoveredCell = hovered ? root.cellAt(point.position.x, point.position.y) : -1
    }
  }

  Item {
    width: parent.width
    implicitHeight: labelMetrics.height

    Repeater {
      model: [0, 6, 12, 18]

      delegate: PlainText {
        required property int modelData
        x: root.cellX(modelData)
        text: root.hourLabel(modelData)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }

  PlainText {
    objectName: "costHeatReadout"
    width: parent.width
    text: root.readoutText
    elide: Text.ElideRight
    color: root.hoveredCell >= 0 ? root.foreground : root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }
}
