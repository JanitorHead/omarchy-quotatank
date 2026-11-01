pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons

// Meter style "Glass" (feature layout: the card puts a large figure above it). A glass capsule filled with
// an aurora: soft bands of the tone, a lighter sheen and a hue-shifted shade drift inside the fill while
// the account spends, faster as the pace presses on the limit, and stand still and dimmed at rest. The
// frosted stretch is where this pace takes the limit by its reset (past the fill under Used, over the part
// of the fill it will spend under Remaining), red when it runs out. While spending, a light breathes at the
// fill's edge (now) on the beat and flashes on each omp request. Row: the same capsule, 6 px, no rim.
//
// Host contract: see MeterProjection.qml.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property var motion: host ? host.motion : null

  // Motion only while the account spends; the still frame is the capsule, its fill and the forecast.
  readonly property bool moving: !!model && model.moving
  readonly property bool animating: moving && !!motion && !motion.reduced
  readonly property real seconds: animating ? motion.liveSeconds : 0
  readonly property real period: model ? Math.max(0.2, model.period) : 1
  readonly property real beat: animating ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((seconds / period) % 1)) : 0
  // A request flash: 1 at an omp request, fading over 0.8 s.
  readonly property real requestFlash: animating && model.requestAt > 0 && seconds >= model.requestAt
    ? Math.max(0, 1 - (seconds - model.requestAt) / 0.8) : 0
  readonly property real pulse: Math.max(beat, requestFlash)
  // The aurora's drift, in fill widths: about one pass every 5 s at an even pace, quicker under pressure.
  readonly property real flow: animating ? seconds * (0.06 + 0.14 * Math.min(3, model.pressure)) : 0
  readonly property bool remaining: !!model && model.quotaMode === "Remaining"
  readonly property color tone: host ? host.tone : "transparent"
  readonly property color foreground: host ? host.foreground : "transparent"
  readonly property color urgent: host ? host.urgent : "transparent"
  // One hue in three tones: the tone, a lighter sheen and a shade shifted a little towards magenta (from
  // either side of the colour wheel; a darker shade for a grey tone, which has no hue to shift).
  readonly property color sheen: lift(tone, 0.38)
  readonly property real shadeShift: {
    var towards = 5 / 6 - tone.hslHue
    towards -= Math.round(towards)
    return Math.max(-0.07, Math.min(0.07, towards))
  }
  readonly property color shade: tone.hslSaturation > 0.15
    ? Qt.hsla((tone.hslHue + shadeShift + 1) % 1, tone.hslSaturation, tone.hslLightness, 1) : Qt.darker(tone, 1.3)
  readonly property real fill: model ? model.fill : 0
  readonly property bool forecastShown: !!model && model.forecastShown
  readonly property real forecastFrom: forecastShown ? model.forecastFrom : 0
  readonly property real forecastTo: forecastShown ? model.forecastTo : 0
  readonly property bool runsOut: !!model && model.runsOut
  readonly property bool tickShown: !!host && host.markShown && !!model && model.markValue >= 0
  readonly property real markValue: tickShown ? model.markValue : 0

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  // The gallery's lift: towards the theme's foreground (white on dark themes, dark on light ones).
  function lift(color, amount) { return Qt.tint(color, alpha(foreground, amount)) }

  implicitHeight: variant === "row" ? Style.space(6) : Style.space(23)

  // A soft round light: one radial gradient disc, no blur. Drawn once at a fixed size and scaled, so a
  // breathing radius never rebuilds its geometry.
  component Halo: Item {
    id: halo
    property real radius: 0
    property color color: "transparent"
    property real strength: 0.5
    width: radius * 2
    height: radius * 2

    Shape {
      anchors.centerIn: parent
      width: 64
      height: 64
      scale: halo.radius / 32

      ShapePath {
        strokeWidth: -1
        strokeColor: "transparent"
        fillGradient: RadialGradient {
          centerX: 32; centerY: 32; centerRadius: 32
          focalX: 32; focalY: 32
          GradientStop { position: 0; color: Qt.rgba(halo.color.r, halo.color.g, halo.color.b, halo.strength) }
          GradientStop { position: 1; color: Qt.rgba(halo.color.r, halo.color.g, halo.color.b, 0) }
        }
        PathAngleArc { centerX: 32; centerY: 32; radiusX: 32; radiusY: 32; startAngle: 0; sweepAngle: 360 }
      }
    }
  }

  // The capsule, for the card (rim, pace tick) and the row (small, rimless).
  component GlassBar: Item {
    id: bar
    property var meter: null
    property bool small: false
    readonly property real radius: height / 2
    readonly property real fillX: Math.round(width * (meter ? meter.fill : 0))
    readonly property real fromX: Math.round(width * (meter ? meter.forecastFrom : 0))
    readonly property real toX: Math.round(width * (meter ? meter.forecastTo : 0))
    readonly property int hairline: Style.spacing.hairline
    // Under Used the forecast continues the fill as one capsule: the fill's shapes are drawn this much wider
    // and clipped, which squares its end where the frosted stretch takes over (never two bubbles).
    readonly property real overhang: !!meter && meter.forecastShown && !meter.remaining && fillX > 0 ? height : 0

    Rectangle {
      anchors.fill: parent
      radius: bar.radius
      color: bar.meter ? bar.meter.alpha(bar.meter.foreground, 0.06) : "transparent"
      border.width: bar.small ? 0 : bar.hairline
      border.color: bar.meter ? bar.meter.alpha(bar.meter.foreground, 0.16) : "transparent"
    }

    // Under Used the frosted stretch runs on from the fill's end, its own left edge cut away.
    Item {
      visible: !!bar.meter && bar.meter.forecastShown && !bar.meter.remaining
      x: bar.fillX
      width: Math.max(0, bar.toX - bar.fillX)
      height: parent.height
      clip: true

      Rectangle {
        objectName: "glassForecast"
        x: -bar.height
        width: parent.width + bar.height
        height: parent.height
        radius: bar.radius
        color: !bar.meter ? "transparent" : bar.meter.runsOut ? bar.meter.alpha(bar.meter.urgent, 0.22) : bar.meter.alpha(bar.meter.tone, 0.14)
        border.width: bar.small ? 0 : bar.hairline
        border.color: !bar.meter ? "transparent" : bar.meter.runsOut ? bar.meter.alpha(bar.meter.urgent, 0.55) : bar.meter.alpha(bar.meter.foreground, 0.25)
      }
    }

    Item {
      visible: bar.fillX > 0
      width: bar.fillX
      height: parent.height
      clip: true

      Rectangle {
        objectName: "glassFill"
        width: bar.fillX + bar.overhang
        height: parent.height
        radius: bar.radius
        color: bar.meter ? bar.meter.alpha(bar.meter.tone, 0.8) : "transparent"
      }

      // The aurora: soft bands drifting through the fill. Each band is cut to the fill as a capsule of the
      // fill's height, so where it meets the fill's rounded start it rounds with it instead of spilling.
      Item {
        id: aurora
        width: bar.fillX + bar.overhang
        height: parent.height
        readonly property real span: Math.max(Style.space(20), bar.fillX)
        readonly property real half: bar.height * (bar.small ? 4 : 3.2)

        Repeater {
          model: 4

          Rectangle {
            id: band
            required property int index
            // Each band drifts at its own speed through the fill, entering and leaving past its ends; under
            // Remaining they drift leftward, the way the fill drains.
            readonly property real phase: ((index * 0.31 + (bar.meter ? bar.meter.flow : 0) * (1 + index * 0.35)) % 1.3) - 0.15
            readonly property real centre: (bar.meter && bar.meter.remaining ? 1 - phase : phase) * aurora.span
            readonly property real startX: Math.max(0, centre - aurora.half)
            readonly property real endX: Math.min(aurora.width, centre + aurora.half)
            readonly property real peakX: Math.max(startX, Math.min(endX, centre))
            readonly property color shade: !bar.meter ? "transparent" : index % 2 ? bar.meter.shade : bar.meter.sheen
            // The band's light at x: strongest at its centre, gone at half a band's width from it.
            function lightAt(x) { return 0.7 * Math.max(0, 1 - Math.abs(x - centre) / aurora.half) }
            objectName: "glassAurora"
            visible: endX - startX >= 1
            x: startX
            width: Math.max(0, endX - startX)
            height: parent.height
            radius: height / 2
            gradient: Gradient {
              orientation: Gradient.Horizontal
              GradientStop { position: 0; color: Qt.rgba(band.shade.r, band.shade.g, band.shade.b, band.lightAt(band.startX)) }
              GradientStop {
                position: band.width > 0 ? (band.peakX - band.startX) / band.width : 0.5
                color: Qt.rgba(band.shade.r, band.shade.g, band.shade.b, band.lightAt(band.peakX))
              }
              GradientStop { position: 1; color: Qt.rgba(band.shade.r, band.shade.g, band.shade.b, band.lightAt(band.endX)) }
            }
          }
        }
      }

      // At rest the aurora is switched off: still and dimmed.
      Rectangle {
        visible: !!bar.meter && !bar.meter.moving
        width: bar.fillX + bar.overhang
        height: parent.height
        radius: bar.radius
        color: Qt.rgba(Commons.Color.background.r, Commons.Color.background.g, Commons.Color.background.b, 0.3)
      }
    }

    // Under Remaining the frosted stretch lies over the fill's end: the part this pace spends by the reset,
    // its left edge cut away so it reads as the fill's own end.
    Item {
      visible: !!bar.meter && bar.meter.forecastShown && bar.meter.remaining
      x: bar.fromX
      width: Math.max(0, bar.fillX - bar.fromX)
      height: parent.height
      clip: true

      Rectangle {
        objectName: "glassForecastInside"
        x: -bar.height
        width: parent.width + bar.height
        height: parent.height
        radius: bar.radius
        color: !bar.meter ? "transparent" : bar.meter.runsOut ? bar.meter.alpha(bar.meter.urgent, 0.35)
          : Qt.rgba(Commons.Color.background.r, Commons.Color.background.g, Commons.Color.background.b, 0.45)
        border.width: bar.small ? 0 : bar.hairline
        border.color: !bar.meter ? "transparent" : bar.meter.runsOut ? bar.meter.alpha(bar.meter.urgent, 0.55) : bar.meter.alpha(bar.meter.foreground, 0.25)
      }
    }

    // The glass's gloss over the fill.
    Item {
      visible: bar.fillX > 0
      width: bar.fillX
      height: parent.height
      clip: true

      Rectangle {
        width: bar.fillX + bar.overhang
        height: parent.height
        radius: bar.radius
        gradient: Gradient {
          GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0.3) }
          GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.05) }
          GradientStop { position: 1; color: Qt.rgba(1, 1, 1, 0) }
        }
      }
    }

    // Now: a light at the fill's edge, breathing on the beat and flashing on each request.
    Halo {
      objectName: "glassEdgeLight"
      visible: !!bar.meter && bar.meter.animating
      x: bar.fillX - bar.radius * 0.6 - radius
      y: bar.height / 2 - radius
      radius: bar.height * (0.8 + 0.6 * (bar.meter ? bar.meter.pulse : 0))
      color: bar.meter ? bar.meter.sheen : "transparent"
      strength: 0.3 + 0.4 * (bar.meter ? bar.meter.pulse : 0)
    }

    Rectangle {
      objectName: "glassPaceTick"
      visible: !!bar.meter && bar.meter.tickShown
      x: Math.round(bar.width * (bar.meter ? bar.meter.markValue : 0) - width / 2)
      y: bar.small ? 0 : -Style.space(4)
      width: Style.spaceReal(1.5)
      height: bar.height + (bar.small ? 0 : Style.space(8))
      color: bar.meter ? bar.meter.alpha(bar.meter.foreground, 0.85) : "transparent"
    }
  }

  GlassBar {
    id: card
    visible: root.variant === "card" && !!root.model && root.model.hasMeter
    y: Style.space(4)
    width: parent.width
    height: Style.space(15)
    meter: root

    LiveClaim {
      motion: root.motion
      active: card.visible && root.moving
    }
  }

  GlassBar {
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
