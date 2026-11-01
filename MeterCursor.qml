pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons

// Meter style "Cursor". Card: the block meter with its forecast dashes; while the account spends, the block at
// the fill's edge beats like a terminal cursor, once per beat (faster as the pace presses on the limit), with
// a soft halo; it turns red when the limit runs out first. Row: the thin bar with a tick beating at the fill's
// edge. Still (quiet, used up, reduced motion): the plain block meter.
//
// Host contract: see MeterProjection.qml.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property alias blocks: blockMeter
  readonly property var motion: host ? host.motion : null

  // The account spends on a limit that is not used up and motion is allowed: the edge beats.
  readonly property bool moving: !!model && model.moving && !!motion && !motion.reduced
  // 0 → 1 → 0 once per beat (LimitModel.period), on the shared 30 Hz clock.
  readonly property real beat: moving && model.period > 0
    ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((motion.liveSeconds / model.period) % 1)) : 0
  // A light theme lifts colours toward black instead of white, so the highlight still stands out.
  readonly property bool lightTheme: !!host && 0.299 * host.foreground.r + 0.587 * host.foreground.g + 0.114 * host.foreground.b < 0.5
  // The beat's colour: the fill lifted, or the alert when this pace empties the limit before its reset.
  readonly property color highlight: !host ? "transparent"
    : model && (model.runsOut || model.pressure > 1) ? lift(host.urgent, 0.25) : lift(host.tone, 0.3)

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function mix(a, b, t) { return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, 1) }
  function lift(color, amount) { return lightTheme ? mix(color, Qt.rgba(0, 0, 0, 1), amount * 0.45) : mix(color, Qt.rgba(1, 1, 1, 1), amount) }

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
    // The tick is drawn above the cursor instead (cardCursor's PaceTick).
    markShown: false
    forecastFrom: root.model ? root.model.forecastFrom : -1
    forecastTo: root.model ? root.model.forecastTo : -1
    forecastColor: !root.host ? "transparent"
      : root.model && root.model.runsOut ? root.alpha(root.host.urgent, 0.85) : root.alpha(root.host.foreground, 0.35)
    // The cursor replaces Projection's sweep.
    live: null
  }

  Item {
    id: cardCursor
    visible: blockMeter.visible
    anchors.fill: parent
    // The block at the fill's edge: the partly filled one, else the last full one.
    readonly property int edge: blockMeter.boundaryFraction > 0.001
      ? Math.min(blockMeter.completeBlocks, blockMeter.blockCount - 1) : Math.max(0, blockMeter.completeBlocks - 1)
    readonly property bool edgePartial: blockMeter.boundaryFraction > 0.001 && blockMeter.completeBlocks < blockMeter.blockCount

    // Halo: a wider low-alpha block behind the cursor stands in for a glow.
    Rectangle {
      visible: root.moving
      x: cardCursor.edge * blockMeter.pitch - Style.space(2)
      y: -Style.space(1)
      width: blockMeter.blockWidth + Style.space(4)
      height: parent.height + Style.space(2)
      color: root.highlight
      opacity: 0.3 * root.beat
    }

    Rectangle {
      objectName: "cursorBlock"
      visible: root.moving
      x: cardCursor.edge * blockMeter.pitch
      width: blockMeter.blockWidth
      height: parent.height
      color: root.host ? root.mix(root.host.tone, root.highlight, 0.25 + 0.75 * root.beat) : "transparent"
      // A partly filled edge keeps its dim look at the low of the beat and lights fully at the peak.
      opacity: cardCursor.edgePartial ? Math.max(blockMeter.partialOpacity(blockMeter.boundaryFraction), root.beat) : 1
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

    Rectangle {
      visible: root.moving
      x: Math.round(rowFill.width - width / 2)
      y: -Style.space(1)
      width: Style.space(7)
      height: parent.height + Style.space(2)
      color: root.highlight
      opacity: 0.25 * root.beat
    }

    // The cursor: a tick just inside the fill's edge, overshooting the bar a little.
    Rectangle {
      objectName: "accountMeterCursor"
      visible: root.moving
      x: Math.max(0, Math.round(rowFill.width - Style.space(2)))
      y: -Style.space(1)
      width: Style.space(3)
      height: parent.height + Style.space(2)
      color: root.highlight
      opacity: 0.35 + 0.65 * root.beat
    }
  }
}
