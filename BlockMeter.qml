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
// UsageLogic.liveMeter) a sweep runs over the forecast from the fill's edge, faster as the pace presses on
// the limit, and the last block flashes when the limit runs out before its reset.
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

  // The sweep runs over the forecast blocks from the fill's edge: rightward under Used, leftward under
  // Remaining (where the forecast lies inside the fill).
  readonly property bool sweeping: !!live && live.moving === true && live.start >= 0 && forecastActive
    && !!motion && !motion.reduced && visible && width > 0
  readonly property int sweepDirection: live && live.end < live.start ? -1 : 1
  // Never negative, even while a resize updates one end before the other.
  readonly property int sweepLength: Math.max(0, forecastToBlock - forecastFromBlock)
  readonly property int sweepFirst: sweepDirection > 0 ? forecastFromBlock : forecastToBlock - 1
  // Blocks a second: 7 when the pace is easy, up to 40 when it presses hard on the limit.
  readonly property real sweepSpeed: live ? Math.max(7, Math.min(40, 14 * Math.pow(Math.max(0.01, live.pressure), 0.6))) : 14
  readonly property real sweepRun: sweepLength / sweepSpeed
  readonly property real sweepPause: 0.8
  readonly property real sweepPhase: sweeping ? motion.liveSeconds % (sweepRun + sweepPause) : 0
  readonly property real sweepHead: Math.min(sweepPhase, sweepRun) * sweepSpeed
  readonly property real sweepFade: sweepPhase > sweepRun ? Math.max(0, 1 - (sweepPhase - sweepRun) / sweepPause) : 1
  // The limit runs out before its reset: the block at the end flashes red as each sweep lands.
  readonly property bool endsAtLimit: !!live && live.runsOut === true
    && (sweepDirection > 0 ? forecastToBlock >= blockCount : forecastFromBlock <= 0)
  readonly property real landing: sweeping && endsAtLimit && sweepPhase > sweepRun ? Math.exp(-(sweepPhase - sweepRun) / 0.25) : 0

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

  // The sweep: blocks light up behind a bright head running from the fill's edge to the forecast's end,
  // then fade before the next run.
  Repeater {
    objectName: "meterSweep"
    model: root.sweeping ? root.sweepLength : 0

    Rectangle {
      required property int index
      // Steps from the fill's edge.
      readonly property real behind: root.sweepHead - index
      readonly property bool isHead: root.sweepPhase < root.sweepRun && index === Math.min(root.sweepLength - 1, Math.floor(root.sweepHead))
      x: (root.sweepFirst + root.sweepDirection * index) * root.pitch
      width: root.blockWidth
      height: root.height
      radius: 0
      visible: index < Math.ceil(root.sweepHead)
      color: isHead ? root.highlightColor : root.liveColor
      opacity: isHead ? 0.95 : Math.max(0.16, 0.75 * Math.exp(-behind / root.sweepSpeed * 2.2)) * root.sweepFade
    }
  }

  Rectangle {
    objectName: "meterLanding"
    visible: root.landing > 0.01
    x: (root.sweepDirection > 0 ? root.blockCount - 1 : 0) * root.pitch - Style.space(1)
    y: -Style.space(1)
    width: root.blockWidth + Style.space(2)
    height: root.height + Style.space(2)
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
