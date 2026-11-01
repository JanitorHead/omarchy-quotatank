pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons

// Omarchy-native segmented quota meter. Every segment is a single track item; the block being filled
// lights up as a whole, its opacity following how full it is. Keep quota blocks square regardless of
// the theme's corner radius.
//
// Marks: the fill, the forecast dashes (where this pace takes the limit by its reset) and, when asked for
// or while the pointer is on the meter, the pace tick. While the account is spending (`live`, from
// UsageLogic.liveMeter) the fill never moves on its own: the block being filled breathes on the beat, and a
// soft glow travels along the forecast dashes from the fill's edge, fading in before the first dash and out
// after the last so each pass starts unseen. When the limit runs out before its reset, the last dash glows
// in the alert colour as the glow arrives.
Item {
  id: root

  property real value: 0
  property color fillColor: Commons.Color.foreground
  property color trackColor: Qt.rgba(fillColor.r, fillColor.g, fillColor.b, 0.14)
  property int blockWidth: Math.max(2, Style.space(5))
  property int blockGap: Math.max(1, Style.space(2))
  // Shared Motion helper; without one the fill moves at once and nothing sweeps, as with reduced motion.
  property var motion: null
  property real animatedValue: Math.max(0, Math.min(1, value))
  // Pace tick: a centred mark on the block at `markValue` (0-1), shown while `markShown` (the pointer on the
  // owner's meter). Negative hides it.
  property real markValue: -1
  property bool markShown: false
  property color markColor: Commons.Color.foreground
  // Forecast: blocks between these fractions are drawn as dashes, the use this pace adds by reset.
  property real forecastFrom: -1
  property real forecastTo: -1
  property color forecastColor: Qt.rgba(markColor.r, markColor.g, markColor.b, 0.35)
  // Spending: UsageLogic.liveMeter's answer; null or not moving keeps the meter still.
  property var live: null
  property color liveColor: fillColor
  property color highlightColor: Qt.lighter(fillColor, 1.45)
  property color urgentColor: Commons.Color.urgent
  readonly property int tickOvershoot: Style.space(2)
  readonly property bool tickVisible: markValue >= 0 && markShown
  readonly property real tickX: root.markBlock * root.pitch + Math.floor((root.blockWidth - 2) / 2)
  readonly property int markBlock: Math.min(root.blockCount - 1, Math.floor(Math.max(0, root.markValue) * root.blockCount))

  readonly property int pitch: blockWidth + blockGap
  readonly property int blockCount: Math.max(1, Math.floor((width + blockGap) / pitch))
  readonly property real filledBlocks: animatedValue * blockCount
  readonly property int completeBlocks: Math.floor(filledBlocks)
  readonly property real boundaryFraction: filledBlocks - completeBlocks
  // Whole blocks the forecast covers. It starts after a partly filled block, and always shows at
  // least one block once it reaches past the fill.
  readonly property bool forecastActive: forecastFrom >= 0 && forecastTo > forecastFrom
  readonly property int forecastFromBlock: forecastActive ? Math.min(blockCount, Math.ceil(forecastFrom * blockCount - 0.001)) : 0
  readonly property int forecastToBlock: forecastActive
    ? Math.min(blockCount, Math.max(forecastFromBlock + 1, Math.ceil(forecastTo * blockCount - 0.001))) : 0
  readonly property int dashHeight: Math.max(2, Math.round(height * 0.34))

  // Spending moves the edge and the forecast only: rightward under Used, leftward under Remaining (where
  // the forecast lies inside the fill).
  readonly property bool sweeping: !!live && live.moving === true && live.start >= 0 && forecastActive
    && !!motion && !motion.reduced && visible && width > 0
  readonly property int sweepDirection: live && live.end < live.start ? -1 : 1
  // Never negative, even while a resize updates one end before the other.
  readonly property int sweepLength: Math.max(0, forecastToBlock - forecastFromBlock)
  readonly property int sweepFirst: sweepDirection > 0 ? forecastFromBlock : forecastToBlock - 1
  // The glow's pass: one every two beats, so it holds still between real changes of pace (the forecast's
  // length drifts with the clock and must not set the timing), with 0.6 s of rest. It starts 1.5 dashes
  // before the first and ends 1.5 after the last, so it fades in and out instead of appearing.
  readonly property real glowCycle: live ? Math.max(2.4, Math.min(5.2, 2 * live.period)) : 4
  readonly property real glowRun: glowCycle - 0.6
  readonly property real glowPhase: sweeping ? motion.liveSeconds % glowCycle : 0
  readonly property real glowHead: sweeping && glowPhase < glowRun ? -1.5 + (sweepLength + 3) * glowPhase / glowRun : -100
  // The edge's breath, 0-1, on the account's beat, on the block being spent: the fill's partly filled block
  // (or its last full one) under Used; under Remaining the forecast's first dash, at the fill's end.
  readonly property real breath: sweeping && live.period > 0
    ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((motion.liveSeconds / live.period) % 1)) : 0
  readonly property int edgeBlock: sweepDirection > 0
    ? (boundaryFraction > 0.001 && !inForecast(completeBlocks) ? completeBlocks : completeBlocks - 1)
    : forecastToBlock - 1
  // The limit runs out before its reset: once the glow reaches the last dash, that dash holds the alert
  // colour and fades over 0.6 s.
  readonly property bool endsAtLimit: !!live && live.runsOut === true
    && (sweepDirection > 0 ? forecastToBlock >= blockCount : forecastFromBlock <= 0)
  readonly property real arrival: glowRun * (sweepLength + 0.5) / (sweepLength + 3)
  readonly property real landing: sweeping && endsAtLimit && glowPhase >= arrival
    ? Math.exp(-(glowPhase - arrival) / 0.6) : 0

  function glowAt(index) {
    var d = index - glowHead
    return Math.exp(-d * d / 2.4)
  }

  function inForecast(index) {
    return forecastActive && index >= forecastFromBlock && index < forecastToBlock
  }

  // How a partly filled block shows: lit as a whole, dim when just started. Never a detached sliver.
  function partialOpacity(fraction) {
    return 0.3 + 0.7 * Math.max(0, Math.min(1, fraction))
  }

  implicitHeight: Math.max(Style.space(8), Math.round(Style.spacing.controlHeight * 0.3))
  clip: false

  LiveClaim {
    motion: root.motion
    active: !!root.live && root.live.moving === true && root.forecastActive && root.visible && root.width > 0
  }

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
      color: !root.inForecast(index) && index < root.completeBlocks ? root.fillColor : root.trackColor
    }
  }

  Rectangle {
    objectName: "meterBoundary"
    visible: root.completeBlocks < root.blockCount && root.boundaryFraction > 0.001 && !root.inForecast(root.completeBlocks)
    x: root.completeBlocks * root.pitch
    width: root.blockWidth
    height: root.height
    radius: 0
    color: root.fillColor
    opacity: root.partialOpacity(root.boundaryFraction)
  }

  // Forecast dashes: a short bar through each block the current pace still fills before the reset.
  Repeater {
    objectName: "meterForecast"
    model: root.forecastActive ? Math.max(0, root.forecastToBlock - root.forecastFromBlock) : 0

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

  // The edge: the block being filled breathes towards the highlight while the account spends.
  Rectangle {
    objectName: "meterLiveEdge"
    visible: root.sweeping && root.edgeBlock >= 0 && root.edgeBlock < root.blockCount
    x: root.edgeBlock * root.pitch
    width: root.blockWidth
    height: root.height
    radius: 0
    color: root.highlightColor
    opacity: 0.12 + 0.5 * root.breath
  }

  // The glow: each forecast dash brightens and swells a little as it passes, then settles back.
  Repeater {
    objectName: "meterSweep"
    model: root.sweeping ? root.sweepLength : 0

    Rectangle {
      required property int index
      readonly property real glow: root.glowAt(index)
      readonly property real lift: root.dashHeight * 0.6 * glow
      x: (root.sweepFirst + root.sweepDirection * index) * root.pitch
      y: Math.round((root.height - root.dashHeight - lift) / 2)
      width: root.blockWidth
      height: root.dashHeight + lift
      radius: 0
      visible: glow > 0.02
      color: root.highlightColor
      opacity: 0.9 * glow
    }
  }

  Rectangle {
    objectName: "meterLanding"
    readonly property real lift: (root.height - root.dashHeight) * root.landing
    visible: root.landing > 0.02
    x: (root.sweepDirection > 0 ? root.blockCount - 1 : 0) * root.pitch
    y: Math.round((root.height - root.dashHeight - lift) / 2)
    width: root.blockWidth
    height: root.dashHeight + lift
    radius: 0
    color: root.urgentColor
    opacity: root.landing
  }

  // Pace tick: a cut through filled blocks, with caps above and below so it reads on any fill.
  Rectangle {
    visible: root.tickVisible
    x: root.tickX
    width: 2
    height: root.height
    radius: 0
    color: root.markBlock < root.completeBlocks ? Commons.Color.background : root.markColor
  }

  Rectangle {
    visible: root.tickVisible
    x: root.tickX
    y: -root.tickOvershoot
    width: 2
    height: root.tickOvershoot
    radius: 0
    color: root.markColor
  }

  Rectangle {
    visible: root.tickVisible
    x: root.tickX
    y: root.height
    width: 2
    height: root.tickOvershoot
    radius: 0
    color: root.markColor
  }
}
