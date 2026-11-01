pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons

// Meter style "Split-flap". A strip of flaps like a departure board (20 on the card, on a dark board; up to
// 12 on the row): lit flaps are the share on the chosen side, a part-lit flap lights whole at
// 0.3 + 0.7 × its part, dim flaps in the fill's colour are where this pace takes the limit by the reset (red
// when it runs out). Under Remaining the forecast lies inside the fill, so those flaps stay lit but fade.
// While the account spends, the flap at the fill's edge pulses on the beat and, once per beat, a flip runs
// across the forecast flaps from the fill's edge to where this pace ends (leftward under Remaining): each
// flap's top leaf folds down onto the split and the bottom leaf falls open.
//
// Cost: the flaps bind to the reading only; the 30 Hz clock drives two overlay items (pulse and leaf).
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property bool card: variant === "card"

  // The card sits on its own dark board; `pad` is the board's margin and the room for the pace marks.
  readonly property int pad: card ? Style.space(5) : 0
  readonly property int gap: card ? Math.max(2, Style.space(3)) : Math.max(1, Style.space(2))
  readonly property int flapHeight: card ? Style.space(14) : Style.space(6)
  readonly property int count: card ? 20
    : Math.max(6, Math.min(12, Math.floor((width + gap) / (Style.space(5) + gap))))
  readonly property int stripWidth: Math.max(0, width - pad * 2)
  readonly property int flapWidth: Math.max(1, Math.floor((stripWidth - gap * (count - 1)) / count))
  // Even flaps read as a board; the leftover (under one flap per side) splits between both ends.
  readonly property int stripLeft: pad + Math.max(0, Math.floor((stripWidth - count * flapWidth - (count - 1) * gap) / 2))
  readonly property int halfHeight: Math.floor(flapHeight / 2)

  readonly property bool remaining: !!model && model.quotaMode === "Remaining"
  property real shownFill: model ? Math.max(0, Math.min(1, model.fill)) : 0
  readonly property real units: shownFill * count
  readonly property int full: Math.floor(units + 1e-6)
  readonly property real part: Math.max(0, units - full)
  readonly property bool hasPart: part > 0.02 && full < count
  readonly property bool forecastShown: !!model && model.forecastShown
  readonly property int forecastFromFlap: forecastShown ? Math.round(model.forecastFrom * count) : -1
  readonly property int forecastToFlap: forecastShown ? Math.round(model.forecastTo * count) : -1

  readonly property color tone: host ? host.tone : "transparent"
  readonly property color baseColor: host ? alpha(host.foreground, card ? 0.09 : 0.1) : "transparent"
  readonly property color forecastColor: !host ? "transparent"
    : model && model.runsOut ? alpha(host.urgent, 0.5) : alpha(host.tone, 0.28)
  readonly property color spentColor: !host ? "transparent"
    : model && model.runsOut ? alpha(host.urgent, 0.6) : alpha(host.tone, 0.45)
  readonly property color highlight: !host ? "transparent"
    : model && (model.runsOut || model.pressure > 1) ? lift(host.urgent, 0.25) : lift(host.tone, 0.3)
  // The split between the two leaves of every flap.
  readonly property color splitColor: card ? Qt.rgba(0.02, 0.02, 0.03, 0.85) : Qt.rgba(0, 0, 0, 0.45)

  // Motion, on the shared clock while a claim is held.
  readonly property bool moving: visible && !!model && model.moving
  readonly property bool running: moving && !!host && !!host.motion && !host.motion.reduced
  readonly property real seconds: running ? host.motion.liveSeconds : 0
  // The flap at the fill's edge: the next to light under Used, the last lit under Remaining.
  readonly property int head: remaining ? (hasPart ? full : full - 1) : Math.min(count - 1, full)
  readonly property real beat: running ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((seconds / model.period) % 1)) : 0
  // The flip: one run per beat from the fill's edge to the forecast's end, in flaps (fractional).
  readonly property var live: model ? model.live : null
  readonly property bool flipping: running && !!live && live.start >= 0 && live.end !== live.start
  readonly property real flipAt: flipping
    ? (live.start + (live.end - live.start) * ((seconds / model.period) % 1)) * count : -1
  readonly property int flipFlap: flipping ? Math.max(0, Math.min(count - 1, Math.floor(flipAt))) : -1
  // How far the current flap has flipped, 0-1, whichever way the run goes.
  readonly property real flipProgress: !flipping ? 0
    : live.end > live.start ? flipAt - Math.floor(flipAt) : 1 - (flipAt - Math.floor(flipAt))

  readonly property int markFlap: model && model.markValue >= 0 ? Math.min(count - 1, Math.floor(model.markValue * count)) : -1

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function lift(color, amount) { return Qt.tint(color, Qt.rgba(1, 1, 1, amount)) }
  function flapX(index) { return stripLeft + index * (flapWidth + gap) }

  // A flap's colour from the reading alone.
  function paint(index) {
    if (!host) return "transparent"
    var partial = hasPart && index === full
    if (remaining) {
      var spent = forecastShown && index >= forecastFromFlap && index < forecastToFlap
      if (index < full) return spent ? spentColor : tone
      if (partial) return alpha(spent ? spentColor : tone, (spent ? spentColor.a : 1) * (0.3 + 0.7 * part))
      return baseColor
    }
    if (index < full) return tone
    if (partial) return alpha(tone, 0.3 + 0.7 * part)
    if (forecastShown && index < forecastToFlap) return forecastColor
    return baseColor
  }

  implicitHeight: flapHeight + pad * 2

  Behavior on shownFill {
    NumberAnimation { duration: root.host && root.host.motion ? root.host.motion.duration(root.host.motion.row) : 0; easing.type: Easing.OutCubic }
  }

  LiveClaim {
    motion: root.host ? root.host.motion : null
    active: root.moving
  }

  Rectangle {
    objectName: "flapBoard"
    visible: root.card
    anchors.fill: parent
    radius: Style.space(3)
    color: Qt.rgba(0, 0, 0, 0.3)
  }

  Repeater {
    objectName: "flapStrip"
    model: root.model && root.model.hasMeter ? root.count : 0

    Rectangle {
      required property int index
      x: root.flapX(index)
      y: root.pad
      width: root.flapWidth
      height: root.flapHeight
      radius: root.card ? Style.space(2) : Style.space(1)
      color: root.paint(index)

      Rectangle {
        y: root.halfHeight
        width: parent.width
        height: Math.max(1, Style.space(1))
        color: root.splitColor
      }
    }
  }

  // The edge flap's pulse on the beat.
  Rectangle {
    objectName: "flapPulse"
    visible: root.running && root.head >= 0
    x: root.flapX(Math.max(0, root.head))
    y: root.pad
    width: root.flapWidth
    height: root.flapHeight
    radius: root.card ? Style.space(2) : Style.space(1)
    color: root.highlight
    opacity: 0.4 + 0.6 * root.beat
  }

  // The flipping leaf: the top leaf shrinks onto the split, then the bottom leaf falls open below it.
  Rectangle {
    objectName: "flapLeaf"
    readonly property bool falling: root.flipProgress < 0.5
    visible: root.flipping && height > 0
    x: root.flapX(Math.max(0, root.flipFlap))
    y: root.pad + root.halfHeight - (falling ? height : 0)
    width: root.flapWidth
    height: Math.round(root.halfHeight * Math.abs(1 - 2 * root.flipProgress))
    radius: root.card ? Style.space(1) : 0
    color: root.highlight
    // Edge-on, a leaf catches less light.
    opacity: 0.45 + 0.45 * Math.abs(1 - 2 * root.flipProgress)
  }

  // The pace tick where even use would be by now: short marks on the board above and below that flap on
  // the card, a hairline in the gap after it on the row, which has no room to spare.
  Repeater {
    objectName: "flapPaceTick"
    model: root.markFlap >= 0 && !!root.host && root.host.markShown ? (root.card ? 2 : 1) : 0

    Rectangle {
      required property int index
      x: root.card ? root.flapX(root.markFlap) + Math.round((root.flapWidth - width) / 2)
        : root.flapX(root.markFlap) + root.flapWidth + Math.floor((root.gap - width) / 2)
      y: !root.card || index === 0 ? 0 : root.height - height
      width: root.card ? Math.max(1, Style.space(2)) : Math.max(1, Style.space(1))
      height: root.card ? root.pad - Math.max(1, Style.space(1)) : root.height
      color: root.host ? root.alpha(root.host.foreground, 0.9) : "transparent"
    }
  }
}
