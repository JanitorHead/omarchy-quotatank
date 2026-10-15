pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// Provider overview in Limits: one tile per provider with its logo, name, most pressing
// figure, and a mini meter. Every provider's state is visible at once; a click selects it.
// Options: { value, label, name, iconUrl, mark, figure, unit, fill, alert, failed, dots }.
// `dots` ({dots: [{state, counted}], extra}, from UsageLogic.accountState) marks a provider with several
// accounts, like its chip. Tiles live in a ListModel keyed by provider id: new figures every second keep
// each tile, its focus and its hover; only a provider added, removed or moved changes the tiles.
Flow {
  id: root

  property var options: []
  property string value: ""
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family
  property real cardRadius: 0
  property var motion: null
  readonly property var optionById: {
    var map = {}
    for (var i = 0; i < options.length; i++) map[String(options[i].value)] = options[i]
    return map
  }
  readonly property alias tileModel: tiles
  // Past six providers the tiles get smaller figures and padding, so more fit in each row and the
  // overview does not push the limits far down.
  readonly property bool dense: options.length > 6
  readonly property real tilePadding: dense ? Style.spacing.md : Style.spacing.lg
  // Adaptive grid: every tile must fit the longest provider name (logo included) and figure, so the
  // row holds as many tiles as fit at that width. Rows are then balanced (five tiles that fit four
  // per row become 3 + 2, not 4 + 1), and each row stretches its tiles to the full width.
  readonly property real minTileWidth: {
    var widest = 0
    for (var i = 0; i < options.length; i++) {
      var option = options[i]
      var label = Style.space(12) + Style.spacing.sm + labelMetrics.advanceWidth(String(option.label || ""))
      var dots = option.dots ? option.dots.dots.length : 0
      if (dots > 0)
        label += Style.spacing.sm + dots * Style.space(5) + (dots - 1) * Style.space(3)
          + (Number(option.dots.extra) > 0 ? Style.space(3) + labelMetrics.advanceWidth("+" + option.dots.extra) : 0)
      var figure = option.failed ? labelMetrics.advanceWidth(String(option.figure || "")) : figureMetrics.advanceWidth(String(option.figure || ""))
      widest = Math.max(widest, label, figure)
    }
    return Math.ceil(widest) + 2 * tilePadding + 2 * Style.spacing.hairline
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
    font.pixelSize: root.dense ? Style.font.body : Style.font.heading
    font.bold: true
  }
  signal changed(string value)

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

  // Brings the tiles to the options' order by moves and inserts (UsageLogic.syncKeyedOrder).
  function sync() {
    var keys = []
    for (var i = 0; i < options.length; i++) keys.push(String(options[i].value))
    UsageLogic.syncKeyedOrder({
      count: function() { return tiles.count },
      keyAt: function(index) { return tiles.get(index).tileKey },
      move: function(from, to) { tiles.move(from, to, 1) },
      insert: function(index, key) { tiles.insert(index, { tileKey: key }) }
    }, keys)
    while (tiles.count > keys.length) tiles.remove(tiles.count - 1)
  }

  onOptionsChanged: sync()
  Component.onCompleted: sync()

  spacing: Style.spacing.md

  ListModel { id: tiles }

  Repeater {
    model: tiles

    Ui.BorderSurface {
      id: tile
      required property string tileKey
      readonly property var modelData: root.optionById[tileKey]
        || ({ value: tileKey, label: "", name: tileKey, iconUrl: "", mark: "", figure: "", unit: "", fill: 0, alert: false, failed: false, dots: null })
      readonly property bool selected: tileKey === root.value
      readonly property color figureColor: modelData.alert ? root.urgent : root.foreground

      objectName: "providerTile-" + tileKey
      width: root.tileWidth
      implicitHeight: tileContent.implicitHeight + contentTopInset + contentBottomInset
      radius: root.cardRadius
      padding: root.tilePadding
      color: selected ? root.alpha(Commons.Color.accent, 0.12)
        : tileMouse.containsMouse ? root.alpha(root.foreground, 0.06) : "transparent"
      borderSpec: selected
        ? Border.flat(Commons.Color.accent, Style.spacing.hairline)
        : Border.flat(root.alpha(modelData.alert ? root.urgent : root.foreground, modelData.alert ? 0.45 : 0.16), Style.spacing.hairline)

      Accessible.role: Accessible.PageTab
      Accessible.name: modelData.name + ", " + (modelData.failed ? modelData.figure : modelData.figure + " " + modelData.unit)
        + (modelData.dots ? ", " + (modelData.dots.dots.length + modelData.dots.extra) + " accounts" : "")
        + (modelData.alert ? ", needs attention" : "")
      Accessible.selected: selected
      activeFocusOnTab: true
      Keys.onReturnPressed: root.changed(tileKey)
      Keys.onSpacePressed: root.changed(tileKey)

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

            // A provider without a mark file keeps its letter instead of an empty slot.
            Text {
              anchors.centerIn: parent
              visible: markImage.status !== Image.Ready
              text: String(tile.modelData.mark || "")
              color: tile.selected ? Commons.Color.accent : tile.figureColor
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }
          }

          Text {
            width: parent.width - mark.width - parent.spacing - (accountDots.visible ? accountDots.width + parent.spacing : 0)
            anchors.verticalCenter: parent.verticalCenter
            text: tile.modelData.label
            color: tile.selected ? Commons.Color.accent : root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.weight: Font.DemiBold
            elide: Text.ElideRight
          }

          // One dot per account: filled for the ones the chip counts, a ring in the account's state
          // colour for the others (dashed when its reading failed). The dots are drawn by count, so a
          // new reading recolours them instead of rebuilding them.
          Row {
            id: accountDots
            objectName: "tileDots-" + tile.tileKey
            readonly property var dotList: tile.modelData.dots ? tile.modelData.dots.dots : []
            readonly property int extra: tile.modelData.dots ? Number(tile.modelData.dots.extra) || 0 : 0
            visible: dotList.length > 0
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(3)

            Repeater {
              model: accountDots.dotList.length

              Item {
                id: dot
                required property int index
                readonly property var info: accountDots.dotList[index] || ({ state: "unknown", counted: false })
                readonly property bool counted: !!info.counted
                readonly property bool dashed: info.state === "error"
                readonly property color ring: info.state === "critical" ? root.urgent
                  : info.state === "warning" ? root.alpha(root.urgent, 0.7)
                  : dashed ? Qt.darker(root.foreground, 1.55)
                  : info.state === "unknown" ? root.alpha(root.foreground, 0.3) : root.alpha(root.foreground, 0.55)
                objectName: "tileDot-" + index
                width: Style.space(5)
                height: width

                Rectangle {
                  anchors.fill: parent
                  visible: !dot.dashed
                  radius: width / 2
                  color: dot.counted ? tile.figureColor : "transparent"
                  border.width: dot.counted ? 0 : Style.spacing.hairline
                  border.color: dot.ring
                }

                Shape {
                  anchors.fill: parent
                  visible: dot.dashed
                  preferredRendererType: Shape.CurveRenderer

                  ShapePath {
                    strokeColor: dot.ring
                    strokeWidth: Style.spacing.hairline
                    strokeStyle: ShapePath.DashLine
                    dashPattern: [1.5, 1.5]
                    fillColor: "transparent"

                    PathAngleArc {
                      centerX: dot.width / 2
                      centerY: dot.height / 2
                      radiusX: dot.width / 2 - 0.5
                      radiusY: dot.height / 2 - 0.5
                      sweepAngle: 360
                    }
                  }
                }
              }
            }

            Text {
              visible: accountDots.extra > 0
              anchors.verticalCenter: parent.verticalCenter
              text: "+" + accountDots.extra
              color: Qt.darker(root.foreground, 1.55)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }

        Item {
          width: parent.width
          // Same height whether the tile shows a figure or a failure reason, so tiles line up.
          implicitHeight: figureMetrics.height

          // The figure shrinks to fit a narrow tile; the unit shows only when there is room beside it.
          Text {
            id: figureText
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            text: tile.modelData.figure
            color: tile.figureColor
            font.family: root.fontFamily
            font.pixelSize: tile.modelData.failed ? Style.font.bodySmall : root.dense ? Style.font.body : Style.font.heading
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

            Behavior on width {
              NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
            }
          }
        }
      }

      MouseArea {
        id: tileMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.changed(tile.tileKey)
      }
    }
  }
}
