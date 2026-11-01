pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons

// Meter style "Trail". Card: the block meter with its forecast dashes, where what the last hour (windows up to
// half a day) or the last day (longer windows) spent is painted in a brighter colour beside the fill's edge:
// the trail's length is the recent pace. It is bright while the account spends and softer once it is quiet,
// and it shortens as that spend leaves the last hour or day. While spending, a gleam runs along the trail
// once per beat toward the edge. Under Remaining the trail lies past the fill's edge, over what was left an
// hour ago. Row: the thin bar with the same trail and gleam. Still (quiet, used up, reduced motion): the
// trail without the gleam.
//
// Host contract: see MeterProjection.qml.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property alias blocks: blockMeter
  readonly property var motion: host ? host.motion : null

  // The account spends on a limit that is not used up and motion is allowed: the gleam runs.
  readonly property bool moving: !!model && model.moving && model.period > 0 && !!motion && !motion.reduced
  readonly property bool fromEnd: !!model && model.quotaMode === "Remaining"
  // 0-1 through the current beat, on the shared 30 Hz clock.
  readonly property real phase: moving ? (motion.liveSeconds / model.period) % 1 : 0
  readonly property real trailSeconds: model && model.windowSeconds > 0 && model.windowSeconds <= 12 * 3600 ? 3600 : 86400
  // Use spent within the trail's span (0-100), from the window's readings; the rate's share while spending
  // when there are none. Nothing once the limit is used up.
  readonly property real trailUsed: model ? spentSince(model.samples, model.nowSeconds - trailSeconds, model.used) : 0
  // The trail on the chosen side as 0-1 fractions, `low` < `high`, ending at the fill's edge.
  readonly property real trailLow: !model ? 0 : fromEnd ? model.fill : Math.max(0, model.fill - trailUsed / 100)
  readonly property real trailHigh: !model ? 0 : fromEnd ? Math.min(1, model.fill + trailUsed / 100) : model.fill
  readonly property bool lightTheme: !!host && 0.299 * host.foreground.r + 0.587 * host.foreground.g + 0.114 * host.foreground.b < 0.5
  // Spending: the fill lifted toward the highlight. Quiet: halfway back to the fill, a record of the last
  // hour or day that shortens as that spend leaves the span.
  readonly property real trailStrength: model && model.moving ? 1 : 0.45
  readonly property color trailColor: host ? mix(host.tone, lift(host.tone, 0.35), trailStrength) : "transparent"
  // Fully lifted, so the gleam still shows over a pale trail.
  readonly property color gleamColor: host ? lift(host.tone, 1) : "transparent"

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function mix(a, b, t) { return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, 1) }
  function lift(color, amount) { return lightTheme ? mix(color, Qt.rgba(0, 0, 0, 1), amount * 0.45) : mix(color, Qt.rgba(1, 1, 1, 1), amount) }

  function spentSince(samples, since, usedNow) {
    if (!model || model.exhausted || !(usedNow > 0)) return 0
    // Readings before the window's start belong to the previous window.
    var windowStart = model.resetsAt > 0 && model.windowSeconds > 0 ? model.resetsAt - model.windowSeconds : -Infinity
    var base = null
    if (since <= windowStart) base = 0
    else {
      var before = null
      var after = null
      for (var i = 0; i < samples.length; i++) {
        var stamp = Number(samples[i][0])
        var value = Number(samples[i][1])
        if (!isFinite(stamp) || !isFinite(value) || stamp < windowStart) continue
        if (stamp <= since) before = [stamp, value]
        else if (after === null) after = [stamp, value]
      }
      if (before && after) base = before[1] + (after[1] - before[1]) * (since - before[0]) / Math.max(1, after[0] - before[0])
      else if (before) base = before[1]
      else if (after && windowStart > -Infinity) base = after[1] * (since - windowStart) / Math.max(1, after[0] - windowStart)
    }
    var spent = base === null ? (model.moving ? model.ratePerHour * trailSeconds / 3600 : 0) : usedNow - base
    return Math.max(0, Math.min(usedNow, spent))
  }

  implicitHeight: variant === "row" ? Style.space(3) : Style.space(12)

  LiveClaim {
    motion: root.motion
    active: root.moving && root.visible && root.trailUsed > 0 && (root.variant === "row" || root.model.hasMeter)
  }

  // A pace tick drawn above the trail: a cut through filled blocks, caps above and below.
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
    // The tick is drawn above the trail instead (cardTrail's PaceTick).
    markShown: false
    forecastFrom: root.model ? root.model.forecastFrom : -1
    forecastTo: root.model ? root.model.forecastTo : -1
    forecastColor: !root.host ? "transparent"
      : root.model && root.model.runsOut ? root.alpha(root.host.urgent, 0.85) : root.alpha(root.host.foreground, 0.35)
    // The gleam replaces Projection's sweep.
    live: null
  }

  Item {
    id: cardTrail
    visible: blockMeter.visible
    anchors.fill: parent
    readonly property int count: blockMeter.blockCount
    // Whole blocks the trail covers; a block it only partly covers lights as a whole, dimmer.
    // Under Remaining the trail starts after the fill's partly filled block, which keeps its own look.
    readonly property int first: Math.max(0, Math.min(count - 1, root.fromEnd
      ? Math.ceil(root.trailLow * count - 0.001) : Math.floor(root.trailLow * count + 0.001)))
    readonly property int last: Math.min(count - 1, Math.ceil(root.trailHigh * count - 0.001) - 1)
    readonly property bool shown: root.trailUsed > 0 && last >= first

    // How lit a trail block is. Under Used the trail is the fill's last stretch: only the fill's partly filled
    // block shows dimmer. Under Remaining it lies over what is gone, so it fades away from the edge like an
    // afterimage instead of reading as more fill.
    function lit(index) {
      if (root.fromEnd) return 0.1 + 0.4 * (1 - (index - first) / Math.max(1, last - first + 1))
      return index === blockMeter.completeBlocks && blockMeter.boundaryFraction > 0.001
        ? blockMeter.partialOpacity(blockMeter.boundaryFraction) : 1
    }

    Repeater {
      objectName: "trailBlocks"
      model: cardTrail.shown ? cardTrail.last - cardTrail.first + 1 : 0

      Item {
        id: trailBlock
        required property int index
        readonly property int block: cardTrail.first + index
        readonly property bool inForecast: blockMeter.inForecast(block)
        readonly property real lit: cardTrail.lit(block)
        x: block * blockMeter.pitch
        width: blockMeter.blockWidth
        height: cardTrail.height

        // Masks the fill beneath, so the trail's colour reads as is.
        Rectangle {
          anchors.fill: parent
          visible: !trailBlock.inForecast && !root.fromEnd
          color: Commons.Color.background
        }

        Rectangle {
          anchors.fill: parent
          visible: !trailBlock.inForecast && !root.fromEnd
          color: blockMeter.trackColor
        }

        Rectangle {
          anchors.fill: parent
          color: root.trailColor
          opacity: trailBlock.lit
        }
      }
    }

    // The gleam: a soft light running along the trail toward the edge once per beat.
    Item {
      id: gleam
      readonly property real span: cardTrail.last - cardTrail.first + 1 + 4
      readonly property real pos: root.fromEnd ? cardTrail.last + 2 - root.phase * span : cardTrail.first - 2 + root.phase * span
      visible: root.moving && cardTrail.shown
      anchors.fill: parent

      Repeater {
        model: gleam.visible ? 5 : 0

        Rectangle {
          required property int index
          readonly property int block: Math.floor(gleam.pos) - 2 + index
          readonly property real strength: Math.max(0, 1 - Math.abs(block - gleam.pos) / 1.8)
          visible: block >= cardTrail.first && block <= cardTrail.last && strength > 0
          x: block * blockMeter.pitch
          width: blockMeter.blockWidth
          height: cardTrail.height
          color: root.gleamColor
          opacity: 0.75 * strength * (root.fromEnd ? 0.7 : cardTrail.lit(block))
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
    readonly property real low: Math.round(width * root.trailLow)
    readonly property real high: Math.round(width * root.trailHigh)
    readonly property bool shown: root.trailUsed > 0 && high > low

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

    Item {
      id: rowTrail
      objectName: "accountMeterTrail"
      visible: rowBar.shown
      x: rowBar.low
      width: rowBar.high - rowBar.low
      height: parent.height
      clip: true

      Rectangle {
        anchors.fill: parent
        visible: !root.fromEnd
        color: Commons.Color.background
      }

      Rectangle {
        anchors.fill: parent
        visible: !root.fromEnd
        color: root.trailColor
      }

      // Under Remaining the trail is gone use: it fades away from the edge instead of reading as more fill.
      Rectangle {
        anchors.fill: parent
        visible: root.fromEnd
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0; color: root.alpha(root.trailColor, 0.5) }
          GradientStop { position: 1; color: root.alpha(root.trailColor, 0.08) }
        }
      }

      // The gleam, a soft 12 px light crossing the trail toward the edge.
      Rectangle {
        visible: root.moving
        readonly property real travel: rowTrail.width + 12
        x: root.fromEnd ? rowTrail.width + 6 - root.phase * travel - width / 2 : -6 + root.phase * travel - width / 2
        width: 12
        height: parent.height
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0; color: root.alpha(root.gleamColor, 0) }
          GradientStop { position: 0.5; color: root.alpha(root.gleamColor, 0.85) }
          GradientStop { position: 1; color: root.alpha(root.gleamColor, 0) }
        }
      }
    }
  }
}
