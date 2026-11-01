pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import "UsageLogic.js" as UsageLogic

// Meter style "Battery" (feature layout: the card puts a large figure above it). A battery body with a cap
// and ten cells charged to the figure on the chosen side: under Remaining the classic battery, what is left
// as charge; under Used the charge the limit has taken. A partly charged cell lights whole, dimmer. Hatched
// cells are what this pace spends by the reset (charged cells it will drain under Remaining, empty cells it
// will fill under Used), red when the limit runs out first. While the account spends, a shine runs over the
// charge in the direction of use (leftward as it drains under Remaining) and the charge's edge flashes on
// the beat and on each omp request. Row: a small battery without hatching.
//
// Host contract: see MeterProjection.qml.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property var motion: host ? host.motion : null

  // Motion only while the account spends; the still frame is the charge and the hatched forecast.
  readonly property bool moving: !!model && model.moving
  readonly property bool animating: moving && !!motion && !motion.reduced
  readonly property real seconds: animating ? motion.liveSeconds : 0
  readonly property real period: model ? Math.max(0.2, model.period) : 1
  readonly property real beat: animating ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((seconds / period) % 1)) : 0
  // A request flash: 1 at an omp request, fading over 0.8 s.
  readonly property real requestFlash: animating && model.requestAt > 0 && seconds >= model.requestAt
    ? Math.max(0, 1 - (seconds - model.requestAt) / 0.8) : 0
  readonly property real pulse: Math.max(beat, requestFlash)
  // The shine's run over the charge, 0-1: quicker as the pace presses on the limit, at most one pass in 2 s.
  readonly property real shine: animating ? (seconds * (0.2 + 0.15 * Math.min(2, model.tempo))) % 1 : 0
  readonly property bool remaining: !!model && model.quotaMode === "Remaining"
  readonly property color tone: host ? host.tone : "transparent"
  readonly property color foreground: host ? host.foreground : "transparent"
  readonly property color urgent: host ? host.urgent : "transparent"
  readonly property real fill: model ? model.fill : 0
  readonly property bool forecastShown: !!model && model.forecastShown
  readonly property real forecastFrom: forecastShown ? model.forecastFrom : 0
  readonly property real forecastTo: forecastShown ? model.forecastTo : 0
  readonly property bool runsOut: !!model && model.runsOut
  readonly property bool tickShown: !!host && host.markShown && !!model && model.markValue >= 0
  readonly property real markValue: tickShown ? model.markValue : 0
  readonly property int cells: 10

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  // The gallery's lift: towards the theme's foreground (white on dark themes, dark on light ones).
  function lift(color, amount) { return Qt.tint(color, alpha(foreground, amount)) }
  function clamp01(value) { return Math.max(0, Math.min(1, value)) }

  // LimitCard's hover readout maps the pointer linearly over the meter's width; the cells skip their gaps
  // and the cap, so the battery answers itself (LimitCard.meterScrubs): the share under the pointer, or the
  // pace line when the pointer is on the pace triangle.
  function scrubTextAt(fraction) {
    if (variant !== "card" || !model || !model.window || !host || typeof host.clock !== "function") return ""
    var x = fraction * width
    if (model.markValue >= 0 && UsageLogic.paceShowsMark(model.pace)
        && Math.abs(x - card.xOf(model.markValue)) <= Style.space(4)) {
      return "now " + host.clock(model.nowSeconds) + " · " + UsageLogic.expectedText(model.pace, model.quotaMode)
        + " · " + UsageLogic.paceBadgeText(model.pace)
    }
    return UsageLogic.scrubText(UsageLogic.meterScrub(model.window, card.valueAt(x) * 100, model.quotaMode, model.nowSeconds),
      model.quotaMode, host.clock)
  }

  implicitHeight: variant === "row" ? Style.space(7) : Style.space(36)

  component BatteryBody: Item {
    id: body
    property var meter: null
    property bool small: false
    readonly property int cellCount: meter ? meter.cells : 10
    readonly property real stroke: small ? Style.spaceReal(1) : Style.spaceReal(1.5)
    readonly property real capWidth: small ? Style.spaceReal(2) : Style.space(5)
    readonly property real capGap: small ? Style.spaceReal(1) : Style.space(2)
    readonly property real bodyWidth: Math.max(0, width - capWidth - capGap)
    readonly property real pad: small ? Style.spaceReal(1.2) : Style.space(4)
    readonly property real gap: small ? Style.spaceReal(1.2) : Style.space(3)
    readonly property real cellWidth: Math.max(1, (bodyWidth - pad * 2 - gap * (cellCount - 1)) / cellCount)
    readonly property real cellHeight: Math.max(1, height - pad * 2)
    readonly property real cellRadius: small ? Style.spaceReal(0.5) : Style.space(2)
    readonly property color charge: meter ? meter.tone : "transparent"
    // Where the charge's edge stands, inside its cell; the shine runs between the first cell and it.
    readonly property real edgeX: xOf(meter ? meter.fill : 0)
    readonly property real shineWidth: small ? Style.space(12) : Style.space(30)
    readonly property real shineX: {
      var start = pad, span = edgeX - start, run = meter ? meter.shine : 0
      return meter && meter.remaining ? edgeX - run * span : start + run * span - shineWidth
    }

    function cellX(index) { return pad + index * (cellWidth + gap) }
    // A 0-1 value as a position on the cells, skipping the gaps between them.
    function xOf(value) {
      if (value >= 1) return cellX(cellCount - 1) + cellWidth
      var scaled = Math.max(0, value) * cellCount, index = Math.floor(scaled)
      return cellX(index) + cellWidth * (scaled - index)
    }
    // The inverse: the 0-1 value at a position, a gap counting as the end of the cell before it.
    function valueAt(x) {
      var pitch = cellWidth + gap, offset = x - pad
      if (offset <= 0) return 0
      var index = Math.floor(offset / pitch)
      if (index >= cellCount) return 1
      return Math.min(1, (index + Math.min(1, (offset - index * pitch) / cellWidth)) / cellCount)
    }

    Rectangle {
      objectName: "batteryBody"
      width: body.bodyWidth
      height: parent.height
      radius: body.small ? Style.spaceReal(1.5) : Style.space(6)
      color: "transparent"
      border.width: body.stroke
      border.color: body.meter ? body.meter.alpha(body.meter.foreground, 0.42) : "transparent"
    }

    Rectangle {
      objectName: "batteryCap"
      x: body.bodyWidth + body.capGap
      y: Math.round(parent.height * 0.3)
      width: body.capWidth
      height: Math.round(parent.height * 0.4)
      radius: body.small ? Style.spaceReal(0.5) : Style.space(2)
      color: body.meter ? body.meter.alpha(body.meter.foreground, 0.42) : "transparent"
    }

    Repeater {
      model: body.cellCount

      Item {
        id: cell
        required property int index
        readonly property var meter: body.meter
        readonly property real lit: meter ? meter.clamp01(meter.fill * body.cellCount - index) : 0
        // The share of this cell the forecast covers.
        readonly property real hatched: !meter || !meter.forecastShown ? 0
          : Math.max(0, Math.min(index + 1, meter.forecastTo * body.cellCount) - Math.max(index, meter.forecastFrom * body.cellCount))
        readonly property bool hot: !!meter && meter.runsOut
        objectName: "batteryCell"
        x: body.cellX(index)
        y: body.pad
        width: body.cellWidth
        height: body.cellHeight
        clip: true

        Rectangle {
          anchors.fill: parent
          radius: body.cellRadius
          color: cell.meter ? cell.meter.alpha(cell.meter.foreground, 0.07) : "transparent"
        }

        // Charge: a partly charged cell lights whole, dimmer, never as a sliver.
        Rectangle {
          visible: cell.lit > 0
          anchors.fill: parent
          radius: body.cellRadius
          opacity: 0.3 + 0.7 * cell.lit
          gradient: Gradient {
            GradientStop { position: 0; color: cell.meter ? cell.meter.lift(body.charge, 0.3) : "transparent" }
            GradientStop { position: 1; color: body.charge }
          }
        }

        // What this pace spends by the reset: charged cells dimmed under Remaining, a faint wash on empty
        // ones under Used; red when the limit runs out first.
        Item {
          visible: cell.hatched > 0
          anchors.fill: parent
          opacity: 0.3 + 0.7 * cell.hatched

          Rectangle {
            anchors.fill: parent
            radius: body.cellRadius
            // Under Remaining the wash darkens the charge so the stripes over it stay readable.
            color: !cell.meter ? "transparent"
              : cell.meter.remaining ? cell.meter.alpha(cell.hot ? Qt.tint(Commons.Color.background, cell.meter.alpha(cell.meter.urgent, 0.35))
                : Commons.Color.background, cell.hot ? 0.6 : 0.5)
              : cell.hot ? cell.meter.alpha(cell.meter.urgent, 0.3)
              : cell.meter.alpha(body.charge, 0.12)
          }

          Repeater {
            model: body.small || cell.hatched <= 0 ? 0 : Math.ceil((body.cellWidth + body.cellHeight * 2) / Style.space(5))

            Rectangle {
              required property int index
              readonly property real offset: -body.cellHeight + index * Style.space(5)
              x: offset + body.cellHeight / 2 - width / 2
              y: (body.cellHeight - height) / 2
              width: Style.spaceReal(1.5)
              height: body.cellHeight * Math.SQRT2
              rotation: 45
              antialiasing: true
              color: !cell.meter ? "transparent"
                : cell.hot ? cell.meter.alpha(cell.meter.lift(cell.meter.urgent, 0.3), 0.9)
                : cell.meter.alpha(cell.meter.lift(body.charge, 0.3), 0.75)
            }
          }
        }

        // The shine, cut to the charged cells.
        Rectangle {
          objectName: "batteryShine"
          visible: !!cell.meter && cell.meter.animating && cell.lit > 0
          x: body.shineX - cell.x
          width: body.shineWidth
          height: parent.height
          gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Qt.rgba(1, 1, 1, cell.meter && cell.meter.remaining ? 0.55 : 0) }
            GradientStop { position: 1; color: Qt.rgba(1, 1, 1, cell.meter && cell.meter.remaining ? 0 : 0.55) }
          }
        }
      }
    }

    // The charge's edge (now): a bright bar in a low-alpha glow, both swelling on the beat and on requests.
    Item {
      objectName: "batteryEdge"
      visible: !!body.meter && body.meter.animating && body.meter.fill > 0
      readonly property real pulse: body.meter ? body.meter.pulse : 0
      readonly property real barWidth: body.small ? Style.spaceReal(1) : Style.space(2)
      x: Math.round(body.edgeX - barWidth / 2)
      y: body.pad
      width: barWidth
      height: body.cellHeight

      Rectangle {
        anchors.centerIn: parent
        width: parent.width + (body.small ? Style.spaceReal(4) : Style.spaceReal(10)) * parent.pulse
        height: parent.height
        radius: width / 2
        color: body.meter ? body.meter.alpha(body.charge, 0.3 * parent.pulse) : "transparent"
      }

      Rectangle {
        anchors.fill: parent
        color: Qt.rgba(1, 1, 1, 0.5 + 0.5 * parent.pulse)
      }
    }

    // The pace tick: a small triangle over the cells, pointing at where even use would be by now.
    Item {
      objectName: "batteryPaceTick"
      readonly property real half: Style.spaceReal(3)
      visible: !body.small && !!body.meter && body.meter.tickShown
      x: body.xOf(body.meter ? body.meter.markValue : 0) - half
      y: -Style.space(7)
      width: half * 2
      height: half
      clip: true

      Rectangle {
        x: parent.half - width / 2
        y: -height / 2
        width: parent.half * Math.SQRT2
        height: width
        rotation: 45
        antialiasing: true
        color: body.meter ? body.meter.alpha(body.meter.foreground, 0.9) : "transparent"
      }
    }
  }

  BatteryBody {
    id: card
    visible: root.variant === "card" && !!root.model && root.model.hasMeter
    y: Style.space(8)
    width: parent.width
    height: Style.space(26)
    meter: root

    LiveClaim {
      motion: root.motion
      active: card.visible && root.moving
    }
  }

  BatteryBody {
    id: row
    visible: root.variant === "row" && !!root.model
    width: parent.width
    height: parent.height
    meter: root
    small: true

    LiveClaim {
      motion: root.motion
      active: row.visible && root.moving
    }
  }
}
