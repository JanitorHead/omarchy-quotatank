pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

// Omarchy-native segmented quota meter. Every segment is a single track item;
// only the boundary fragment is overlaid, so the strip is not rendered twice.
// Keep quota blocks square regardless of the theme's corner radius.
Item {
  id: root

  property real value: 0
  property color fillColor: Commons.Color.foreground
  property color trackColor: Qt.rgba(fillColor.r, fillColor.g, fillColor.b, 0.14)
  property int blockWidth: Math.max(2, Style.space(5))
  property int blockGap: Math.max(1, Style.space(2))
  property real animatedValue: Math.max(0, Math.min(1, value))
  // Pace tick: a centred mark on the block at `markValue` (0-1). Negative hides it.
  property real markValue: -1
  property color markColor: Commons.Color.foreground
  // Usage past the tick is shaded so the excess over pace reads at a glance.
  property bool markAhead: false
  // Hover text for the tick; empty disables it.
  property string markTooltip: ""
  readonly property int tickOvershoot: Style.space(2)
  readonly property real tickX: root.markBlock * root.pitch + Math.floor((root.blockWidth - 2) / 2)
  readonly property color aheadColor: Qt.rgba(root.fillColor.r, root.fillColor.g, root.fillColor.b, 0.4)
  readonly property int markBlock: Math.min(root.blockCount - 1, Math.floor(Math.max(0, root.markValue) * root.blockCount))

  readonly property int pitch: blockWidth + blockGap
  readonly property int blockCount: Math.max(1, Math.floor((width + blockGap) / pitch))
  readonly property real filledBlocks: animatedValue * blockCount
  readonly property int completeBlocks: Math.floor(filledBlocks)
  readonly property real boundaryFraction: filledBlocks - completeBlocks
  // Blocks between the fill's end and the tick, the tick block excluded. Under Used the fill runs past the tick; under Remaining it stops short of it.
  readonly property bool fillPastMark: completeBlocks > markBlock
  readonly property bool aheadActive: markAhead && markValue >= 0
  readonly property int aheadFrom: fillPastMark ? markBlock + 1 : completeBlocks
  readonly property int aheadTo: fillPastMark ? completeBlocks : markBlock

  implicitHeight: Math.max(Style.space(8), Math.round(Style.spacing.controlHeight * 0.3))
  clip: false

  Behavior on animatedValue {
    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
  }

  Repeater {
    model: root.blockCount

    Rectangle {
      required property int index
      x: index * root.pitch
      width: root.blockWidth
      height: root.height
      radius: 0
      color: root.aheadActive && index >= root.aheadFrom && index < root.aheadTo ? root.aheadColor : (index < root.completeBlocks ? root.fillColor : root.trackColor)
    }
  }

  Rectangle {
    visible: root.completeBlocks < root.blockCount && root.boundaryFraction > 0.001
    x: root.completeBlocks * root.pitch
    width: Math.round(root.blockWidth * root.boundaryFraction)
    height: root.height
    radius: 0
    color: root.aheadActive && root.fillPastMark ? root.aheadColor : root.fillColor
  }

  // Pace tick: a cut through filled blocks, with caps above and below so it reads on any fill.
  Rectangle {
    visible: root.markValue >= 0
    x: root.tickX
    width: 2
    height: root.height
    radius: 0
    color: root.markBlock < root.completeBlocks ? Commons.Color.background : root.markColor
  }

  Rectangle {
    visible: root.markValue >= 0
    x: root.tickX
    y: -root.tickOvershoot
    width: 2
    height: root.tickOvershoot
    radius: 0
    color: root.markColor
  }

  Rectangle {
    visible: root.markValue >= 0
    x: root.tickX
    y: root.height
    width: 2
    height: root.tickOvershoot
    radius: 0
    color: root.markColor
  }

  MouseArea {
    id: tickMouse
    anchors.fill: parent
    anchors.topMargin: -root.tickOvershoot
    anchors.bottomMargin: -root.tickOvershoot
    hoverEnabled: true
    readonly property bool onTick: root.markValue >= 0 && containsMouse && Math.abs(mouseX - (root.tickX + 1)) <= root.pitch / 2
  }

  Ui.PanelToolTip {
    visible: tickMouse.onTick && root.markTooltip !== ""
    text: root.markTooltip
  }
}
