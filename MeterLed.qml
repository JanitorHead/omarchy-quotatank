pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons

// Meter style "LED". Card: a row of round lamps; lit lamps (a soft halo, lighter on top, brightening toward the
// fill's edge) are the fill, hollow rings are what this pace still fills by the reset (red when the limit runs
// out first). While the account spends, one lamp light leaves the fill's edge once per beat, eases out toward
// where the forecast ends and fades on the way: how far it goes is the forecast, how often it leaves is the
// rate. Under Remaining the rings lie inside the fill and the light runs leftward. Row: small round lamps with
// the same light. Still (quiet, used up, reduced motion): lamps and rings only.
//
// Host contract: see MeterProjection.qml.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property var motion: host ? host.motion : null

  // The account spends on a limit that is not used up and motion is allowed: the light runs.
  readonly property bool moving: !!model && model.moving && model.period > 0 && !!motion && !motion.reduced
  // 0-1 through the current beat, on the shared 30 Hz clock.
  readonly property real phase: moving ? (motion.liveSeconds / model.period) % 1 : 0
  readonly property int direction: model && model.quotaMode === "Remaining" ? -1 : 1
  // The light eases out (fast off the edge, slowing as it arrives) and fades as it goes.
  readonly property real reach: 1 - Math.pow(1 - phase, 2.2)
  readonly property real chaseAlpha: Math.pow(1 - phase, 0.6)
  readonly property real fill: model ? Math.max(0, Math.min(1, model.fill)) : 0
  property real animatedFill: fill
  readonly property bool lightTheme: !!host && 0.299 * host.foreground.r + 0.587 * host.foreground.g + 0.114 * host.foreground.b < 0.5
  readonly property color chaseColor: !host ? "transparent" : model && model.runsOut ? host.urgent : lift(host.tone, 0.25)

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function mix(a, b, t) { return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, 1) }
  function lift(color, amount) { return lightTheme ? mix(color, Qt.rgba(0, 0, 0, 1), amount * 0.45) : mix(color, Qt.rgba(1, 1, 1, 1), amount) }
  // Where the light is, in lamps, for `count` lamps filled to `filled`: from the edge toward the forecast's
  // end, at least two and a half lamps away so a short forecast still shows a run.
  function chasePos(count, filled) {
    var live = model ? model.live : null
    var target = live && live.end >= 0 ? live.end * count : filled + 3 * direction
    var end = direction > 0 ? Math.min(count, Math.max(filled + 2.5, target)) : Math.max(0, Math.min(filled - 2.5, target))
    return filled + reach * (end - filled)
  }
  // How lit lamp `index` is by the light at `pos`: the lamp under it fully, the two behind it faintly.
  function chaseStrength(index, pos) {
    var behind = direction > 0 ? pos - index : index + 1 - pos
    return behind >= 0 && behind < 1 ? 1 : behind >= 1 && behind < 3 ? (3 - behind) / 2 * 0.35 : 0
  }
  // A partly filled lamp lights as a whole, dimmer the less it is filled.
  function partialOpacity(fraction) { return 0.3 + 0.7 * Math.max(0, Math.min(1, fraction)) }

  implicitHeight: variant === "row" ? Style.space(3) : Style.space(12)

  Behavior on animatedFill {
    NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
  }

  LiveClaim {
    motion: root.motion
    active: root.moving && root.visible && (root.variant === "row" || root.model.hasMeter)
  }

  Item {
    id: card
    objectName: "limitMeter"
    visible: root.variant === "card" && !!root.model && root.model.hasMeter
    anchors.fill: parent

    readonly property int lampSize: Style.space(7)
    readonly property int gap: Style.space(2)
    readonly property int count: Math.max(2, Math.floor((width + gap) / (lampSize + gap)))
    // Lamps spread so the last one ends flush with the card's edge.
    readonly property real step: (width - lampSize) / (count - 1)
    readonly property real lampY: Math.round((height - lampSize) / 2)
    readonly property real filled: root.animatedFill * count
    readonly property int full: Math.floor(filled)
    readonly property real part: filled - full
    // Ring lamps: the forecast, from the lamp after a partly filled one; at least one once it reaches past.
    readonly property bool forecastActive: !!root.model && root.model.forecastFrom >= 0 && root.model.forecastTo > root.model.forecastFrom
    readonly property int forecastFrom: forecastActive ? Math.min(count, Math.ceil(root.model.forecastFrom * count - 0.001)) : 0
    readonly property int forecastTo: forecastActive
      ? Math.min(count, Math.max(forecastFrom + 1, Math.ceil(root.model.forecastTo * count - 0.001))) : 0
    readonly property real chase: root.moving ? root.chasePos(count, filled) : 0
    readonly property int markLamp: Math.min(count - 1, Math.floor(Math.max(0, root.model ? root.model.markValue : 0) * count))

    function lampX(index) { return Math.round(index * step) }
    function inForecast(index) { return forecastActive && index >= forecastFrom && index < forecastTo }

    Repeater {
      objectName: "ledLamps"
      model: card.visible ? card.count : 0

      Item {
        id: lamp
        required property int index
        readonly property bool ring: card.inForecast(index)
        readonly property real lit: ring ? 0 : index < card.full ? 1 : index === card.full && card.part > 0.001 ? root.partialOpacity(card.part) : 0
        // The fill brightens toward its edge.
        readonly property color litColor: !root.host ? "transparent"
          : root.mix(root.mix(root.host.tone, Commons.Color.background, 0.3), root.host.tone, Math.min(1, index / Math.max(1, card.full)))
        x: card.lampX(index)
        y: card.lampY
        width: card.lampSize
        height: card.lampSize

        // Halo: a wider, faint disc behind a lit lamp stands in for a glow.
        Rectangle {
          visible: lamp.lit > 0
          anchors.centerIn: parent
          width: parent.width + Style.space(3)
          height: width
          radius: width / 2
          color: lamp.litColor
          opacity: 0.16 * lamp.lit
        }

        Rectangle {
          visible: lamp.lit < 1 && !lamp.ring
          anchors.fill: parent
          radius: width / 2
          color: root.host ? root.alpha(root.host.foreground, 0.12) : "transparent"
        }

        Rectangle {
          visible: lamp.lit > 0
          anchors.fill: parent
          radius: width / 2
          opacity: lamp.lit
          gradient: Gradient {
            GradientStop { position: 0; color: root.lift(lamp.litColor, 0.4) }
            GradientStop { position: 1; color: lamp.litColor }
          }
        }

        Rectangle {
          visible: lamp.ring
          anchors.fill: parent
          radius: width / 2
          color: "transparent"
          border.width: 1
          border.color: !root.host ? "transparent"
            : root.model && root.model.runsOut ? root.alpha(root.host.urgent, 0.85) : root.alpha(root.host.tone, 0.55)
        }
      }
    }

    // The light: the lamp under it and two fading behind, on the shared clock only while spending.
    Repeater {
      objectName: "ledChase"
      model: root.moving && card.visible ? 3 : 0

      Item {
        id: chaseLamp
        required property int index
        readonly property int lampIndex: Math.floor(card.chase) - root.direction * index
        // Only over the lamps the fill leaves: past the edge under Used, inside it under Remaining.
        readonly property bool onPath: lampIndex >= 0 && lampIndex < card.count
          && (root.direction > 0 ? lampIndex >= card.full : lampIndex <= card.full)
        readonly property real strength: onPath ? root.chaseStrength(lampIndex, card.chase) * root.chaseAlpha : 0
        visible: strength > 0.01
        x: card.lampX(lampIndex)
        y: card.lampY
        width: card.lampSize
        height: card.lampSize

        Rectangle {
          anchors.centerIn: parent
          width: parent.width + Style.space(3)
          height: width
          radius: width / 2
          color: root.chaseColor
          opacity: 0.3 * chaseLamp.strength
        }

        Rectangle {
          anchors.fill: parent
          radius: width / 2
          color: root.chaseColor
          opacity: 0.85 * chaseLamp.strength
        }
      }
    }

    // Pace tick: a cut through the lamp at the pace, with caps above and below.
    Item {
      objectName: "ledPaceTick"
      visible: !!root.host && root.host.markShown && !!root.model && root.model.markValue >= 0
      x: card.lampX(card.markLamp) + Math.floor(card.lampSize / 2) - 1
      width: 2
      height: parent.height

      Rectangle {
        y: card.lampY
        width: 2
        height: card.lampSize
        color: card.markLamp < card.full && !card.inForecast(card.markLamp) ? Commons.Color.background
          : root.host ? root.host.foreground : "transparent"
      }

      Rectangle {
        y: card.lampY - height
        width: 2
        height: Style.space(2)
        color: root.host ? root.host.foreground : "transparent"
      }

      Rectangle {
        y: card.lampY + card.lampSize
        width: 2
        height: Style.space(2)
        color: root.host ? root.host.foreground : "transparent"
      }
    }
  }

  Item {
    id: row
    visible: root.variant === "row" && !!root.model
    anchors.fill: parent

    readonly property int lampSize: Math.min(height, Style.space(3))
    readonly property int gap: Style.space(1)
    readonly property int count: Math.max(2, Math.floor((width + gap) / (lampSize + gap)))
    readonly property real step: (width - lampSize) / (count - 1)
    readonly property real filled: root.animatedFill * count
    readonly property int full: Math.floor(filled)
    readonly property real part: filled - full
    readonly property real chase: root.moving ? root.chasePos(count, filled) : 0

    Repeater {
      objectName: "accountMeterLamps"
      model: row.visible ? row.count : 0

      Rectangle {
        required property int index
        readonly property real lit: index < row.full ? 1 : index === row.full && row.part > 0.001 ? root.partialOpacity(row.part) : 0
        x: Math.round(index * row.step)
        y: Math.round((row.height - height) / 2)
        width: row.lampSize
        height: row.lampSize
        radius: width / 2
        color: !root.host ? "transparent" : lit > 0 ? root.alpha(root.host.tone, lit) : root.alpha(root.host.foreground, 0.14)
      }
    }

    // The light: one lamp, off the fill's edge toward the forecast's end.
    Rectangle {
      objectName: "accountMeterChase"
      readonly property int lampIndex: Math.floor(row.chase)
      readonly property bool onPath: lampIndex >= 0 && lampIndex < row.count
        && (root.direction > 0 ? lampIndex >= row.full : lampIndex <= row.full)
      readonly property real strength: root.moving && onPath && root.chaseStrength(lampIndex, row.chase) >= 1 ? root.chaseAlpha : 0
      visible: strength > 0.01
      x: Math.round(lampIndex * row.step)
      y: Math.round((row.height - height) / 2)
      width: row.lampSize
      height: row.lampSize
      radius: width / 2
      color: root.chaseColor
      opacity: 0.85 * strength
    }
  }
}
