pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons

// Meter style "Flow". Card: the block meter with its forecast dashes; while the account spends, a flash runs
// over the used side of the meter once per beat and lands on the fill's edge, which lights up as it arrives:
// you see the use coming in. The flash runs faster and more often as the pace presses on the limit (several
// may be under way at once), and a glint drifts over the forecast dashes the way the run is heading, red when
// the limit runs out first. Under Remaining the flashes come in from the right end, over what is gone, onto
// the edge of what is left. Row: the thin bar with the same flashes as short streaks. Still (quiet, used up,
// reduced motion): the plain block meter.
//
// Gallery requests are not streamed to the plugin, so a flash marks each beat (LimitModel.period), which
// follows the rate the same way.
//
// Host contract: see MeterProjection.qml.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property alias blocks: blockMeter
  readonly property var motion: host ? host.motion : null

  // The account spends on a limit that is not used up and motion is allowed: flashes run.
  readonly property bool moving: !!model && model.moving && model.period > 0 && !!motion && !motion.reduced
  // Under Remaining the flashes come from the right end, over what is used, toward the fill's edge.
  readonly property bool fromEnd: !!model && model.quotaMode === "Remaining"
  readonly property real period: model && model.period > 0 ? model.period : 1
  // Seconds into the current beat, on the shared 30 Hz clock.
  readonly property real beatTime: moving ? motion.liveSeconds % period : 0
  // Blocks a second, faster as the pace presses on the limit; capped so the flash stays a sweep, not a blink.
  readonly property real speed: model ? Math.max(10, Math.min(24, 14 * Math.sqrt(Math.max(0, model.pressure)))) : 10
  readonly property bool lightTheme: !!host && 0.299 * host.foreground.r + 0.587 * host.foreground.g + 0.114 * host.foreground.b < 0.5
  readonly property color highlight: !host ? "transparent"
    : model && (model.runsOut || model.pressure > 1) ? lift(host.urgent, 0.25) : lift(host.tone, 0.3)
  // The flash's head: nearly white on a dark theme.
  readonly property color headColor: host ? lift(highlight, 0.7) : "transparent"

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function mix(a, b, t) { return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, 1) }
  function lift(color, amount) { return lightTheme ? mix(color, Qt.rgba(0, 0, 0, 1), amount * 0.45) : mix(color, Qt.rgba(1, 1, 1, 1), amount) }
  // Flashes in flight: one leaves every beat and lives while it runs plus about a second of landing glow.
  function flights(travelSeconds) { return Math.max(1, Math.min(4, Math.ceil((travelSeconds + 1) / period))) }

  implicitHeight: variant === "row" ? Style.space(3) : Style.space(12)

  LiveClaim {
    motion: root.motion
    active: root.moving && root.visible && (root.variant === "row" || root.model.hasMeter)
  }

  // A pace tick drawn above every motion layer: a cut through filled blocks, caps above and below.
  component PaceTick: Item {
    id: tick
    property real tickX: 0
    property bool overFill: false
    property color markColor: "transparent"
    readonly property int overshoot: Style.space(2)

    Rectangle {
      x: tick.tickX
      width: 2
      height: tick.height
      color: tick.overFill ? Commons.Color.background : tick.markColor
    }

    Rectangle {
      x: tick.tickX
      y: -tick.overshoot
      width: 2
      height: tick.overshoot
      color: tick.markColor
    }

    Rectangle {
      x: tick.tickX
      y: tick.height
      width: 2
      height: tick.overshoot
      color: tick.markColor
    }
  }

  BlockMeter {
    id: blockMeter
    objectName: "limitMeter"
    visible: root.variant === "card" && !!root.model && root.model.hasMeter
    anchors.fill: parent
    motion: root.motion
    value: root.model ? root.model.fill : 0
    fillColor: root.host ? root.host.tone : "transparent"
    trackColor: root.host ? root.alpha(root.host.foreground, 0.14) : "transparent"
    markValue: root.model ? root.model.markValue : -1
    // The tick is drawn above the flashes instead (cardFlow's PaceTick).
    markShown: false
    forecastFrom: root.model ? root.model.forecastFrom : -1
    forecastTo: root.model ? root.model.forecastTo : -1
    forecastColor: !root.host ? "transparent"
      : root.model && root.model.runsOut ? root.alpha(root.host.urgent, 0.85) : root.alpha(root.host.foreground, 0.35)
    // The flashes replace Projection's sweep.
    live: null
  }

  Item {
    id: cardFlow
    visible: blockMeter.visible
    anchors.fill: parent
    // The block at the fill's edge: the partly filled one, else the last full one.
    readonly property int edge: blockMeter.boundaryFraction > 0.001
      ? Math.min(blockMeter.completeBlocks, blockMeter.blockCount - 1) : Math.max(0, blockMeter.completeBlocks - 1)
    // The flash's path, in blocks, ending on the edge: from the left end under Used, the right end under Remaining.
    readonly property int pathLength: root.fromEnd ? blockMeter.blockCount - edge : edge + 1
    function blockAt(step) { return root.fromEnd ? blockMeter.blockCount - 1 - step : step }

    Repeater {
      objectName: "flowFlashes"
      model: root.moving && cardFlow.visible ? root.flights(cardFlow.pathLength / root.speed) : 0

      Item {
        id: flash
        required property int index
        // This flash left `index` beats before the latest one.
        readonly property real head: (root.beatTime + index * root.period) * root.speed
        readonly property bool running: head <= cardFlow.pathLength
        // Arrived: the edge glows and fades within a few tenths of a second.
        readonly property real landing: running ? 0 : Math.exp(-(head - cardFlow.pathLength) / root.speed / 0.3)
        width: cardFlow.width
        height: cardFlow.height

        // Head and a fading tail of four blocks behind it.
        Repeater {
          model: flash.running ? 5 : 0

          Rectangle {
            required property int index
            readonly property int step: Math.floor(flash.head) - index
            visible: step >= 0 && step < cardFlow.pathLength
            x: cardFlow.blockAt(step) * blockMeter.pitch
            width: blockMeter.blockWidth
            height: cardFlow.height
            color: index === 0 ? root.headColor : root.highlight
            opacity: (1 - index / 5) * 0.9
          }
        }

        Rectangle {
          visible: flash.landing > 0.02
          x: cardFlow.edge * blockMeter.pitch - Style.space(2)
          y: -Style.space(1)
          width: blockMeter.blockWidth + Style.space(4)
          height: parent.height + Style.space(2)
          color: root.highlight
          opacity: 0.35 * flash.landing
        }

        Rectangle {
          objectName: "flowLanding"
          visible: flash.landing > 0.02
          x: cardFlow.edge * blockMeter.pitch
          width: blockMeter.blockWidth
          height: parent.height
          color: root.highlight
          opacity: flash.landing
        }
      }
    }

    // A glint drifting over the forecast dashes once per beat, the way the live run heads.
    Item {
      id: glint
      readonly property int from: blockMeter.forecastFromBlock
      readonly property int to: blockMeter.forecastToBlock
      readonly property real span: to - from + 4
      readonly property real phase: root.beatTime / root.period
      readonly property real pos: root.fromEnd ? to + 1 - phase * span : from - 2 + phase * span
      readonly property int dashHeight: blockMeter.dashHeight
      visible: root.moving && blockMeter.forecastActive && to > from
      anchors.fill: parent

      Repeater {
        model: glint.visible ? 6 : 0

        Rectangle {
          required property int index
          readonly property int block: Math.floor(glint.pos) - 2 + index
          readonly property real strength: Math.max(0, 1 - Math.abs(block - glint.pos) / 2.5)
          visible: block >= glint.from && block < glint.to && strength > 0
          x: block * blockMeter.pitch
          y: Math.round((cardFlow.height - glint.dashHeight) / 2)
          width: blockMeter.blockWidth
          height: glint.dashHeight
          color: !root.host ? "transparent" : root.model.runsOut ? root.lift(root.host.urgent, 0.25) : root.lift(root.host.foreground, 0.3)
          opacity: 0.7 * strength
        }
      }
    }

    PaceTick {
      anchors.fill: parent
      visible: !!root.host && root.host.markShown && !!root.model && root.model.markValue >= 0
      tickX: blockMeter.tickX
      overFill: blockMeter.markBlock < blockMeter.completeBlocks
      markColor: root.host ? root.host.foreground : "transparent"
    }
  }

  Item {
    id: rowBar
    visible: root.variant === "row" && !!root.model
    anchors.fill: parent
    // Pixels a second: the card's pace, scaled from the gallery's 137 px row to this one.
    readonly property real speed: root.speed * 5 * width / 137
    // The streak's path: from the left end to the fill's edge, or from the right end under Remaining.
    readonly property real pathLength: root.fromEnd ? width - rowFill.width : rowFill.width
    readonly property int tail: Style.space(8)

    Rectangle {
      anchors.fill: parent
      color: root.host ? root.alpha(root.host.foreground, 0.14) : "transparent"
    }

    Rectangle {
      id: rowFill
      width: Math.round(parent.width * (root.model ? root.model.fill : 0))
      height: parent.height
      color: root.host ? root.host.tone : "transparent"

      Behavior on width {
        NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
      }
    }

    Repeater {
      objectName: "accountMeterFlow"
      model: root.moving && rowBar.visible && rowBar.speed > 0 ? root.flights(rowBar.pathLength / rowBar.speed - 1) : 0

      // A streak brightening toward its head, cut at the path's start and gone once it reaches the edge.
      Rectangle {
        required property int index
        readonly property real run: (root.beatTime + index * root.period) * rowBar.speed
        readonly property real length: Math.min(rowBar.tail, run)
        visible: run <= rowBar.pathLength && length > 0
        x: root.fromEnd ? rowBar.width - run : run - length
        width: length
        height: rowBar.height
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0; color: root.fromEnd ? root.alpha(root.headColor, 0.95) : root.alpha(root.highlight, 0) }
          GradientStop { position: 1; color: root.fromEnd ? root.alpha(root.highlight, 0) : root.alpha(root.headColor, 0.95) }
        }
      }
    }
  }
}
