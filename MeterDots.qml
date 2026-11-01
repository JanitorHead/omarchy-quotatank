pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons

// Meter style "Dot matrix". A grid of round dots filled column by column, bottom to top: lit dots are the
// share on the chosen side, dim dots in the fill's colour are where this pace takes the limit by the reset
// (red when it runs out). While the account spends, the edge column moves: under Used the next column
// charges dot by dot, under Remaining the last lit column drains dot by dot; one cycle per 1.6 beats, so a
// faster charge is a faster pace. On the card a three-column scan runs through the forecast dots once a
// beat, rightward from the fill's edge under Used, leftward from it under Remaining (the way the fill
// drains). A new request flashes that column on the card. The pace tick is a pair of short marks above and
// below the grid.
//
// Cost: one Rectangle per dot, all bound to the reading only (fill, forecast, colours); the moving column
// and the scan are separate overlays of a few dots whose column is an int, so the 30 Hz clock re-binds them
// only when they step a column, never the grid.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property bool card: variant === "card"

  // Card: three rows of 4 px dots with a faint halo ring; row: two rows of 2 px dots, no halo.
  readonly property int rows: card ? 3 : 2
  readonly property int dot: card ? Math.max(2, Style.space(4)) : Math.max(2, Style.space(2))
  readonly property int pitch: card ? dot + Math.max(2, Style.space(3)) : dot + Math.max(1, Style.space(1))
  readonly property int glow: card ? Math.max(1, Style.space(1)) : 0
  // Room above and below the grid for the pace marks (the card only: the row has no room to spare).
  readonly property int tickRoom: card ? Style.space(5) : 0
  readonly property int gridHeight: (rows - 1) * pitch + dot
  readonly property int cols: Math.max(1, Math.floor((width - dot) / pitch) + 1)
  // Even spacing reads as a matrix; the leftover (under one pitch) splits between both ends.
  readonly property int gridLeft: Math.max(0, Math.floor((width - (cols - 1) * pitch - dot) / 2))
  readonly property int dotCount: cols * rows

  readonly property bool remaining: !!model && model.quotaMode === "Remaining"
  property real shownFill: model ? Math.max(0, Math.min(1, model.fill)) : 0
  // The fill in dots, in fill order (column by column, bottom to top): `full` whole dots and a part of
  // the next, which lights up whole at 0.3 + 0.7 × the part.
  readonly property real units: shownFill * dotCount
  readonly property int full: Math.floor(units + 1e-6)
  readonly property real part: Math.max(0, units - full)
  readonly property bool hasPart: part > 0.02 && full < dotCount
  readonly property bool forecastShown: !!model && model.forecastShown
  readonly property int forecastFromDot: forecastShown ? Math.round(model.forecastFrom * dotCount) : -1
  readonly property int forecastToDot: forecastShown ? Math.round(model.forecastTo * dotCount) : -1

  readonly property color tone: host ? host.tone : "transparent"
  readonly property color trackColor: host ? alpha(host.foreground, 0.12) : "transparent"
  readonly property color forecastColor: !host ? "transparent"
    : model && model.runsOut ? alpha(host.urgent, 0.45) : alpha(host.tone, 0.28)
  // Under Remaining the forecast lies inside the fill: those dots stay lit but fade, the share this pace spends.
  readonly property color spentColor: !host ? "transparent"
    : model && model.runsOut ? alpha(host.urgent, 0.6) : alpha(host.tone, 0.45)
  readonly property bool hotUrgent: !!model && (model.runsOut || model.pressure > 1)
  readonly property color hotColor: !host ? "transparent" : hotUrgent ? lift(host.urgent, 0.35) : lift(host.tone, 0.45)

  // The moving column, on the shared clock while a claim is held.
  readonly property bool moving: visible && !!model && model.moving
  readonly property bool running: moving && !!host && !!host.motion && !host.motion.reduced
  // Under Used, the column the next dot lands in and how many of its dots are lit; under Remaining, the
  // column of the last lit dot and how many of its dots are lit.
  readonly property int lastLit: hasPart ? full : full - 1
  readonly property int edgeCol: remaining ? (lastLit >= 0 ? Math.floor(lastLit / rows) : -1)
    : (full < dotCount ? Math.floor(full / rows) : -1)
  readonly property int edgeLit: remaining ? (lastLit >= 0 ? lastLit % rows + 1 : 0) : full % rows
  readonly property bool edgeMoving: running && edgeCol >= 0
  // Steps per cycle: charging from the lit dots to a full column, or draining the lit dots to none.
  readonly property int cycleSteps: remaining ? edgeLit + 1 : rows - edgeLit + 1
  // An int, so the overlay re-binds only when a dot changes, not on every clock tick.
  readonly property int step: edgeMoving
    ? Math.min(cycleSteps - 1, Math.floor(((host.motion.liveSeconds / (model.period * 1.6)) % 1) * cycleSteps)) : 0
  // The scan over the forecast dots (card only): the forecast's dots, the head's column (an int, so the
  // overlay re-binds once per column step) and the trail's length. Under Remaining the forecast lies inside
  // the fill, so the scan starts at its right end and runs left.
  readonly property int scanFrom: !forecastShown ? -1 : remaining ? forecastFromDot : full + (hasPart ? 1 : 0)
  readonly property int scanTo: !forecastShown ? -1 : remaining ? Math.min(forecastToDot, full) : forecastToDot
  readonly property int scanFirstCol: scanFrom >= 0 ? Math.floor(scanFrom / rows) : -1
  readonly property int scanLastCol: scanTo > 0 ? Math.floor((scanTo - 1) / rows) : -1
  readonly property int scanTrail: 3
  readonly property bool scanning: card && running && scanFirstCol >= 0 && scanLastCol - scanFirstCol >= 2
  readonly property int scanHead: {
    if (!scanning) return -1
    var span = scanLastCol - scanFirstCol + 1 + scanTrail
    var travelled = Math.floor(((host.motion.liveSeconds / model.period) % 1) * span)
    return remaining ? scanLastCol - travelled + scanTrail - 1 : scanFirstCol + travelled
  }
  // A request flash on the moving column (card only), fading over Motion.flash.
  property real flash: 0
  property real lastRequestAt: 0
  readonly property real requestAt: model ? model.requestAt : 0

  readonly property int markCol: model && model.markValue >= 0
    ? Math.min(cols - 1, Math.floor(model.markValue * dotCount / rows)) : -1

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function lift(color, amount) { return Qt.tint(color, Qt.rgba(1, 1, 1, amount)) }
  function colX(col) { return gridLeft + col * pitch }
  function dotY(fromBottom) { return tickRoom + (rows - 1 - fromBottom) * pitch }

  // A dot's colour from the reading alone; `k` is its place in fill order.
  function paint(k) {
    if (!host) return "transparent"
    var partial = hasPart && k === full
    if (remaining) {
      var spent = forecastShown && k >= forecastFromDot && k < forecastToDot
      if (k < full) return spent ? spentColor : tone
      if (partial) return alpha(spent ? spentColor : tone, (spent ? spentColor.a : 1) * (0.3 + 0.7 * part))
      return trackColor
    }
    if (k < full) return tone
    if (partial) return alpha(tone, 0.3 + 0.7 * part)
    if (forecastShown && k < forecastToDot) return forecastColor
    return trackColor
  }

  // The moving column's dots: Used charges from the lit dots up to a full column in `hotColor`; Remaining
  // burns the top lit dot in `hotColor` and puts the drained ones out, down to an empty column.
  function livePaint(fromBottom) {
    var k = edgeCol * rows + fromBottom
    var color = paint(k)
    if (remaining) {
      var left = edgeLit - step
      if (fromBottom === left - 1) color = hotColor
      else if (fromBottom >= left && fromBottom < edgeLit) color = trackColor
    } else if (fromBottom >= edgeLit && fromBottom < edgeLit + step) {
      color = alpha(hotColor, 0.95)
    }
    if (flash > 0) {
      var lit = Qt.tint(color, Qt.rgba(1, 1, 1, 0.85 * flash))
      color = alpha(lit, Math.max(color.a, flash))
    }
    return color
  }

  implicitHeight: tickRoom * 2 + gridHeight

  onRequestAtChanged: {
    if (root.card && root.edgeMoving && root.lastRequestAt > 0 && root.requestAt > root.lastRequestAt) flashAnimation.restart()
    root.lastRequestAt = root.requestAt
  }

  Behavior on shownFill {
    NumberAnimation { duration: root.host && root.host.motion ? root.host.motion.duration(root.host.motion.row) : 0; easing.type: Easing.OutCubic }
  }

  NumberAnimation {
    id: flashAnimation
    target: root
    property: "flash"
    from: 1
    to: 0
    duration: root.host && root.host.motion ? root.host.motion.duration(root.host.motion.flash) : 0
  }

  LiveClaim {
    motion: root.host ? root.host.motion : null
    active: root.moving
  }

  // One dot. A lit dot on the card carries a faint ring in its own colour (the gallery's LED halo) as the
  // Rectangle's border, so the halo costs no extra item. Qt drops a transparent border and fills the whole
  // rectangle, so only a haloed dot grows by the ring; the rest stay `dot` wide.
  component Dot: Rectangle {
    property int col: 0
    property int fromBottom: 0
    property color dotColor: "transparent"
    readonly property int ring: root.glow > 0 && dotColor.a > 0.5 ? root.glow : 0
    x: root.colX(col) - ring
    y: root.dotY(fromBottom) - ring
    width: root.dot + ring * 2
    height: width
    radius: width / 2
    color: dotColor
    border.width: ring
    border.color: ring > 0 ? root.alpha(dotColor, 0.16) : "transparent"
  }

  // The grid, still: one dot per Repeater item, in fill order.
  Repeater {
    objectName: "dotGrid"
    model: root.model && root.model.hasMeter ? root.dotCount : 0

    Dot {
      required property int index
      col: Math.floor(index / root.rows)
      fromBottom: index % root.rows
      dotColor: root.paint(index)
      // The moving column draws over this one.
      visible: !(root.edgeMoving && col === root.edgeCol)
    }
  }

  // The moving column.
  Repeater {
    objectName: "dotsEdgeColumn"
    model: root.edgeMoving ? root.rows : 0

    Dot {
      required property int index
      col: root.edgeCol
      fromBottom: index
      dotColor: root.livePaint(index)
    }
  }

  // The scan: the head and its fading trail, only over dots inside the forecast.
  Repeater {
    objectName: "dotsScan"
    model: root.scanning ? root.scanTrail * root.rows : 0

    Dot {
      required property int index
      readonly property int behind: Math.floor(index / root.rows)
      readonly property int k: col * root.rows + fromBottom
      col: root.remaining ? root.scanHead + behind : root.scanHead - behind
      fromBottom: index % root.rows
      visible: k >= root.scanFrom && k < root.scanTo && !(root.edgeMoving && col === root.edgeCol)
      dotColor: root.alpha(root.hotColor, [0.9, 0.55, 0.3][behind])
    }
  }

  // The pace tick where even use would be by now: short marks above and below that column on the card,
  // a hairline through it on the row, which has no room to spare.
  Repeater {
    objectName: "dotsPaceTick"
    model: root.markCol >= 0 && !!root.host && root.host.markShown ? (root.card ? 2 : 1) : 0

    Rectangle {
      required property int index
      x: root.card ? root.colX(root.markCol) + Math.round((root.dot - width) / 2) : root.colX(root.markCol) + root.dot
      y: !root.card || index === 0 ? 0 : root.tickRoom + root.gridHeight + root.tickRoom - height
      width: root.card ? Math.max(1, Style.space(2)) : Math.max(1, Style.space(1))
      height: root.card ? Math.max(2, root.tickRoom - Style.space(1)) : root.gridHeight
      color: root.host ? root.alpha(root.host.foreground, 0.9) : "transparent"
    }
  }
}
