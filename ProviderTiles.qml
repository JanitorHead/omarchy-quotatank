pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Effects
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

// Provider overview in Limits: one tile per provider with its logo, name, most pressing
// figure, and a mini meter. Every provider's state is visible at once; a click selects it.
// Options: { value, label, name, iconUrl, figure, unit, fill, alert, failed }.
Flow {
  id: root

  property var options: []
  property string value: ""
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family
  property real cardRadius: 0
  // Adaptive grid: every tile must fit the longest provider name (logo included) and figure, so the
  // row holds as many tiles as fit at that width. Rows are then balanced (five tiles that fit four
  // per row become 3 + 2, not 4 + 1), and each row stretches its tiles to the full width.
  readonly property real minTileWidth: {
    var widest = 0
    for (var i = 0; i < options.length; i++) {
      var option = options[i]
      var label = Style.space(12) + Style.spacing.sm + labelMetrics.advanceWidth(String(option.label || ""))
      var figure = option.failed ? labelMetrics.advanceWidth(String(option.figure || "")) : figureMetrics.advanceWidth(String(option.figure || ""))
      widest = Math.max(widest, label, figure)
    }
    return Math.ceil(widest) + 2 * Style.spacing.lg + 2 * Style.spacing.hairline
  }
  readonly property int fitColumns: Math.max(1, Math.floor((width + spacing) / (minTileWidth + spacing)))
  readonly property int rows: Math.max(1, Math.ceil(options.length / Math.max(1, Math.min(fitColumns, options.length))))
  readonly property int columns: Math.max(1, Math.ceil(options.length / rows))
  readonly property real tileWidth: Math.floor((width - spacing * (columns - 1)) / columns)

  FontMetrics {
    id: labelMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.weight: Font.DemiBold
  }

  FontMetrics {
    id: figureMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.heading
    font.bold: true
  }
  signal changed(string value)

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

  spacing: Style.spacing.md

  Repeater {
    model: root.options

    Ui.BorderSurface {
      id: tile
      required property var modelData
      required property int index
      readonly property bool selected: modelData.value === root.value
      readonly property color figureColor: modelData.alert ? root.urgent : root.foreground

      objectName: "providerTile-" + modelData.value
      width: root.tileWidth
      implicitHeight: tileContent.implicitHeight + contentTopInset + contentBottomInset
      radius: root.cardRadius
      padding: Style.spacing.lg
      color: selected ? root.alpha(Commons.Color.accent, 0.12)
        : tileMouse.containsMouse ? root.alpha(root.foreground, 0.06) : "transparent"
      borderSpec: selected
        ? Border.flat(Commons.Color.accent, Style.spacing.hairline)
        : Border.flat(root.alpha(modelData.alert ? root.urgent : root.foreground, modelData.alert ? 0.45 : 0.16), Style.spacing.hairline)

      Accessible.role: Accessible.PageTab
      Accessible.name: modelData.name + ", " + (modelData.failed ? modelData.figure : modelData.figure + " " + modelData.unit)
        + (modelData.alert ? ", needs attention" : "")
      Accessible.selected: selected
      activeFocusOnTab: true
      Keys.onReturnPressed: root.changed(modelData.value)
      Keys.onSpacePressed: root.changed(modelData.value)

      Column {
        id: tileContent
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: tile.contentLeftInset
        anchors.rightMargin: tile.contentRightInset
        anchors.topMargin: tile.contentTopInset
        spacing: Style.spacing.sm

        Row {
          width: parent.width
          spacing: Style.spacing.sm

          Item {
            id: mark
            width: Style.space(12)
            height: width
            anchors.verticalCenter: parent.verticalCenter

            Image {
              id: markImage
              anchors.fill: parent
              source: tile.modelData.iconUrl
              sourceSize.width: mark.width * 2
              sourceSize.height: mark.height * 2
              fillMode: Image.PreserveAspectFit
              visible: false
              layer.enabled: true
            }

            MultiEffect {
              anchors.fill: markImage
              source: markImage
              visible: markImage.status === Image.Ready
              colorization: 1.0
              colorizationColor: tile.selected ? Commons.Color.accent : tile.figureColor
            }
          }

          Text {
            width: parent.width - mark.width - parent.spacing
            anchors.verticalCenter: parent.verticalCenter
            text: tile.modelData.label
            color: tile.selected ? Commons.Color.accent : root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.weight: Font.DemiBold
            elide: Text.ElideRight
          }
        }

        Item {
          width: parent.width
          // Same height whether the tile shows a figure or a failure reason, so tiles line up.
          implicitHeight: figureMetrics.height

          FontMetrics {
            id: figureMetrics
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
            font.bold: true
          }

          // The figure shrinks to fit a narrow tile; the unit shows only when there is room beside it.
          Text {
            id: figureText
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            text: tile.modelData.figure
            color: tile.figureColor
            font.family: root.fontFamily
            font.pixelSize: tile.modelData.failed ? Style.font.bodySmall : Style.font.heading
            font.bold: true
            fontSizeMode: tile.modelData.failed ? Text.FixedSize : Text.HorizontalFit
            minimumPixelSize: Style.font.bodySmall
            elide: Text.ElideRight
          }

          Text {
            id: unitText
            visible: !tile.modelData.failed && tile.modelData.unit !== ""
              && figureText.contentWidth + Style.spacing.sm + implicitWidth <= parent.width
            anchors.left: parent.left
            anchors.leftMargin: figureText.contentWidth + Style.spacing.sm
            anchors.baseline: figureText.baseline
            text: tile.modelData.unit
            color: Qt.darker(root.foreground, 1.55)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        // Mini meter: the provider's most pressing limit on the chosen side.
        Item {
          width: parent.width
          height: Style.space(4)

          Rectangle {
            anchors.fill: parent
            color: root.alpha(root.foreground, 0.14)
          }

          Rectangle {
            visible: !tile.modelData.failed
            width: Math.round(parent.width * Math.max(0, Math.min(1, tile.modelData.fill)))
            height: parent.height
            color: tile.figureColor
          }
        }
      }

      MouseArea {
        id: tileMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.changed(tile.modelData.value)
      }
    }
  }
}
