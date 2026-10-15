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
  // Shared Motion helper; without one the fill moves at once, as with reduced motion.
  property var motion: null
  property real animatedValue: Math.max(0, Math.min(1, value))
  // Pace tick: a centred mark on the block at `markValue` (0-1). Negative hides it.
  property real markValue: -1
  property color markColor: Commons.Color.foreground
  // Usage past the tick is shaded so the excess over pace reads at a glance.
  property bool markAhead: false
  // Hover text for the tick; empty disables it. A scrubbing meter says it in its readout instead.
  property string markTooltip: ""
  // Faint reference lines where the warning and critical thresholds sit (0-1 on the side shown).
  property real warningMark: -1
  property real criticalMark: -1
  property color warningMarkColor: Qt.rgba(markColor.r, markColor.g, markColor.b, 0.34)
  property color criticalMarkColor: Qt.rgba(Commons.Color.urgent.r, Commons.Color.urgent.g, Commons.Color.urgent.b, 0.62)
  // Forecast: blocks between these fractions are drawn as dashes, the use this pace adds by reset.
  property real forecastFrom: -1
  property real forecastTo: -1
  property color forecastColor: Qt.rgba(markColor.r, markColor.g, markColor.b, 0.35)
  // Hover scrub: a thin guide follows the pointer; the owner reads `scrubFraction` for its readout.
  property bool scrubEnabled: false
  property color guideColor: Commons.Color.accent
  readonly property bool scrubbing: scrubEnabled && tickMouse.containsMouse && width > 0
  readonly property real scrubX: Math.max(0, Math.min(width, tickMouse.mouseX))
  readonly property real scrubFraction: width > 0 ? scrubX / width : 0
  readonly property bool scrubOnTick: tickMouse.onTick
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
  // Whole blocks the forecast covers. It starts after a partly filled block, and always shows at
  // least one block once it reaches past the fill.
  readonly property bool forecastActive: forecastFrom >= 0 && forecastTo > forecastFrom
  readonly property int forecastFromBlock: forecastActive ? Math.min(blockCount, Math.ceil(forecastFrom * blockCount - 0.001)) : 0
  readonly property int forecastToBlock: forecastActive
    ? Math.min(blockCount, Math.max(forecastFromBlock + 1, Math.ceil(forecastTo * blockCount - 0.001))) : 0
  readonly property int dashHeight: Math.max(2, Math.round(height * 0.34))

  function inForecast(index) {
    return forecastActive && index >= forecastFromBlock && index < forecastToBlock
  }

  // x of the gap before block `fraction * blockCount`; -1 when the mark would sit on an edge.
  function gapX(fraction) {
    if (fraction <= 0 || fraction >= 1) return -1
    var boundary = Math.round(fraction * blockCount)
    if (boundary <= 0 || boundary >= blockCount) return -1
    return boundary * pitch - blockGap / 2 - Style.spacing.hairline / 2
  }

  implicitHeight: Math.max(Style.space(8), Math.round(Style.spacing.controlHeight * 0.3))
  clip: false

  Behavior on animatedValue {
    NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
  }

  Repeater {
    model: root.blockCount

    Rectangle {
      required property int index
      x: index * root.pitch
      width: root.blockWidth
      height: root.height
      radius: 0
      color: root.inForecast(index) ? root.trackColor
        : root.aheadActive && index >= root.aheadFrom && index < root.aheadTo ? root.aheadColor
        : (index < root.completeBlocks ? root.fillColor : root.trackColor)
    }
  }

  Rectangle {
    visible: root.completeBlocks < root.blockCount && root.boundaryFraction > 0.001 && !root.inForecast(root.completeBlocks)
    x: root.completeBlocks * root.pitch
    width: Math.round(root.blockWidth * root.boundaryFraction)
    height: root.height
    radius: 0
    color: root.aheadActive && root.fillPastMark ? root.aheadColor : root.fillColor
  }

  // Forecast dashes: a short bar through each block the current pace still fills before the reset.
  Repeater {
    objectName: "meterForecast"
    model: root.forecastActive ? root.forecastToBlock - root.forecastFromBlock : 0

    Rectangle {
      required property int index
      x: (root.forecastFromBlock + index) * root.pitch
      y: Math.round((root.height - root.dashHeight) / 2)
      width: root.blockWidth
      height: root.dashHeight
      radius: 0
      color: root.forecastColor
    }
  }

  Rectangle {
    objectName: "meterWarningMark"
    readonly property real at: root.gapX(root.warningMark)
    visible: at >= 0
    x: at
    y: -root.tickOvershoot
    width: Style.spacing.hairline
    height: root.height + root.tickOvershoot * 2
    color: root.warningMarkColor
  }

  Rectangle {
    objectName: "meterCriticalMark"
    readonly property real at: root.gapX(root.criticalMark)
    visible: at >= 0
    x: at
    y: -root.tickOvershoot
    width: Style.spacing.hairline
    height: root.height + root.tickOvershoot * 2
    color: root.criticalMarkColor
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

  // Scrub guide.
  Rectangle {
    objectName: "meterScrubGuide"
    visible: root.scrubbing
    x: Math.round(root.scrubX - Style.spacing.hairline / 2)
    y: -root.tickOvershoot * 2
    width: Style.spacing.hairline
    height: root.height + root.tickOvershoot * 4
    color: root.guideColor
  }

  MouseArea {
    id: tickMouse
    anchors.fill: parent
    anchors.topMargin: -root.tickOvershoot
    anchors.bottomMargin: -root.tickOvershoot
    hoverEnabled: true
    cursorShape: root.scrubEnabled ? Qt.CrossCursor : Qt.ArrowCursor
    readonly property bool onTick: root.markValue >= 0 && containsMouse && Math.abs(mouseX - (root.tickX + 1)) <= root.pitch / 2
  }

  Ui.PanelToolTip {
    visible: !root.scrubEnabled && tickMouse.onTick && root.markTooltip !== ""
    text: root.markTooltip
  }
}
