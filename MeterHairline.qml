pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons

// Meter style "Hairline" (feature layout: the card puts a large figure above it). Card: a 4 px line in the
// tone, fading in from the left, with a dot of light at its tip (now). The translucent stretch is where
// this pace takes the limit by its reset: past the tip under Used, the part of the fill it will spend under
// Remaining; red with a cut at the limit's edge when it runs out first. While the account spends, the dot
// breathes on the beat inside a soft halo, a flash runs along the line in the direction of use and a ring
// opens on each omp request. Row: the same line, 2.5 px, with a breathing dot while spending.
//
// Host contract: see MeterProjection.qml.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property var motion: host ? host.motion : null

  // Motion only while the account spends; the still frame is the line, its forecast and the dot.
  readonly property bool moving: !!model && model.moving
  readonly property bool animating: moving && !!motion && !motion.reduced
  readonly property real seconds: animating ? motion.liveSeconds : 0
  readonly property real period: model ? Math.max(0.2, model.period) : 1
  readonly property real beat: animating ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((seconds / period) % 1)) : 0
  readonly property bool remaining: !!model && model.quotaMode === "Remaining"
  readonly property color tone: host ? host.tone : "transparent"
  readonly property color foreground: host ? host.foreground : "transparent"
  readonly property color urgent: host ? host.urgent : "transparent"
  readonly property real fill: model ? model.fill : 0
  // The forecast stretch on the chosen side (0-1); under Remaining it lies inside the fill, so the solid
  // part stops where the stretch begins and the stretch alone reaches the tip.
  readonly property bool forecastShown: !!model && model.forecastShown
  readonly property real forecastFrom: forecastShown ? model.forecastFrom : 0
  readonly property real forecastTo: forecastShown ? model.forecastTo : 0
  readonly property real solidEnd: forecastShown && remaining ? forecastFrom : fill
  readonly property bool runsOut: !!model && model.runsOut
  readonly property color forecastColor: runsOut ? urgent : tone
  readonly property bool tickShown: !!host && host.markShown && !!model && model.markValue >= 0
  readonly property real markValue: tickShown ? model.markValue : 0
  // Halo colour: hot when this pace outruns the limit.
  readonly property color hot: runsOut || (!!model && model.pressure > 1) ? lift(urgent, 0.25) : lift(tone, 0.3)
  // Seconds since the newest omp request, while spending (a ring opens for 0.8 s after each).
  readonly property real requestAge: animating && model.requestAt > 0 ? seconds - model.requestAt : -1

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  // The gallery's lift: towards the theme's foreground (white on dark themes, dark on light ones).
  function lift(color, amount) { return Qt.tint(color, alpha(foreground, amount)) }

  implicitHeight: variant === "row" ? Style.space(6) : Style.space(14)

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

  // Card: the 4 px line.
  Item {
    id: card
    visible: root.variant === "card" && !!root.model && root.model.hasMeter
    anchors.fill: parent
    readonly property int lineHeight: Style.space(4)
    readonly property real lineY: Math.round((height - lineHeight) / 2)
    readonly property real midY: lineY + lineHeight / 2
    readonly property real fillX: Math.round(width * root.fill)

    LiveClaim {
      motion: root.motion
      active: card.visible && root.moving
    }

    Rectangle {
      objectName: "hairlineTrack"
      y: card.lineY
      width: parent.width
      height: card.lineHeight
      radius: height / 2
      color: root.alpha(root.foreground, 0.1)
    }

    // Where this pace takes the limit: bright at now, fading towards the reset's end; red when it runs out.
    // Under Used it tucks under the fill's rounded end.
    Rectangle {
      id: forecast
      objectName: "hairlineForecast"
      readonly property real fromX: Math.round(card.width * root.forecastFrom) - (root.remaining ? 0 : Style.space(2))
      readonly property real nearAlpha: 0.5
      readonly property real farAlpha: root.runsOut ? 0.55 : 0.1
      visible: root.forecastShown
      x: fromX
      y: card.lineY
      width: Math.max(0, Math.round(card.width * root.forecastTo) - fromX)
      height: card.lineHeight
      radius: height / 2
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: root.alpha(root.forecastColor, root.remaining ? forecast.farAlpha : forecast.nearAlpha) }
        GradientStop { position: 1; color: root.alpha(root.forecastColor, root.remaining ? forecast.nearAlpha : forecast.farAlpha) }
      }
    }

    Rectangle {
      objectName: "hairlineFill"
      visible: width > 0
      y: card.lineY
      width: Math.round(card.width * root.solidEnd)
      height: card.lineHeight
      radius: height / 2
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: root.alpha(root.tone, 0.3) }
        GradientStop { position: 1; color: root.tone }
      }
    }

    // The flash: a short shine running along the line once per 1.3 beats in the direction of use (towards
    // the tip under Used, away from it under Remaining), fading in and out.
    Item {
      id: sweep
      readonly property real phase: root.animating ? (root.seconds / (root.period * 1.3)) % 1 : 0
      readonly property real headX: root.remaining ? card.fillX * (1 - phase) : card.fillX * phase
      readonly property real strength: 0.75 * Math.sin(Math.PI * phase)
      visible: root.animating && card.fillX > 0
      y: card.lineY
      width: card.fillX
      height: card.lineHeight
      clip: true

      Rectangle {
        objectName: "hairlineSweep"
        x: root.remaining ? sweep.headX : sweep.headX - width
        width: Style.space(50)
        height: parent.height
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0; color: Qt.rgba(1, 1, 1, root.remaining ? sweep.strength : 0) }
          GradientStop { position: 1; color: Qt.rgba(1, 1, 1, root.remaining ? 0 : sweep.strength) }
        }
      }
    }

    // The limit's edge, cut in red when this pace reaches it before the reset.
    Rectangle {
      objectName: "hairlineRunOut"
      visible: root.forecastShown && root.runsOut
      x: root.remaining ? 0 : card.width - width
      y: card.lineY - Style.space(4)
      width: Style.spaceReal(1.5)
      height: card.lineHeight + Style.space(8)
      color: root.alpha(root.urgent, 0.95)
    }

    Rectangle {
      objectName: "hairlinePaceTick"
      visible: root.tickShown
      x: Math.round(card.width * root.markValue - width / 2)
      y: card.lineY - Style.space(5)
      width: Style.spaceReal(1.5)
      height: card.lineHeight + Style.space(10)
      color: root.alpha(root.foreground, 0.85)
    }

    Halo {
      objectName: "hairlineHalo"
      visible: root.animating
      x: card.fillX - radius
      y: card.midY - radius
      radius: Style.spaceReal(9 + 7 * root.beat)
      color: root.hot
      strength: 0.5
    }

    // One ring per omp request, opening from the tip.
    Rectangle {
      objectName: "hairlineRipple"
      readonly property real progress: Math.max(0, root.requestAge / 0.8)
      readonly property real ringRadius: Style.spaceReal(4 + 14 * progress)
      visible: root.requestAge >= 0 && progress < 1
      x: card.fillX - ringRadius
      y: card.midY - ringRadius
      width: ringRadius * 2
      height: width
      radius: width / 2
      color: "transparent"
      border.width: Style.spaceReal(1.2)
      border.color: root.alpha(root.hot, 0.8 * (1 - progress))
    }

    // The tip: now. Larger and brighter while spending.
    Rectangle {
      objectName: "hairlineDot"
      readonly property real dotRadius: Style.spaceReal(root.moving ? 3.4 : 2.6)
      x: card.fillX - dotRadius
      y: card.midY - dotRadius
      width: dotRadius * 2
      height: width
      radius: dotRadius
      color: root.lift(root.tone, root.moving ? 0.85 : 0.4)
    }
  }

  // Row: the 2.5 px line, its forecast and, while spending, a breathing dot at the tip.
  Item {
    id: row
    visible: root.variant === "row" && !!root.model
    anchors.fill: parent
    readonly property real lineHeight: Style.spaceReal(2.5)
    readonly property real lineY: Math.round((height - lineHeight) / 2)
    readonly property real midY: lineY + lineHeight / 2
    readonly property real fillX: Math.round(width * root.fill)

    LiveClaim {
      motion: root.motion
      active: row.visible && root.moving
    }

    Rectangle {
      y: row.lineY
      width: parent.width
      height: row.lineHeight
      radius: height / 2
      color: root.alpha(root.foreground, 0.12)
    }

    Rectangle {
      objectName: "hairlineRowForecast"
      readonly property real fromX: Math.round(row.width * root.forecastFrom)
      visible: root.forecastShown
      x: fromX
      y: row.lineY
      width: Math.max(0, Math.round(row.width * root.forecastTo) - fromX)
      height: row.lineHeight
      radius: height / 2
      color: root.alpha(root.forecastColor, 0.3)
    }

    Rectangle {
      objectName: "hairlineRowFill"
      y: row.lineY
      width: Math.round(row.width * root.solidEnd)
      height: row.lineHeight
      radius: height / 2
      color: root.alpha(root.tone, 0.95)
    }

    Rectangle {
      visible: root.tickShown
      x: Math.round(row.width * root.markValue - width / 2)
      width: Style.spaceReal(1.5)
      height: row.height
      color: root.alpha(root.foreground, 0.85)
    }

    Halo {
      visible: root.animating
      x: row.fillX - radius
      y: row.midY - radius
      radius: Style.spaceReal(3 + 3 * root.beat)
      color: root.tone
      strength: 0.6
    }

    Rectangle {
      objectName: "hairlineRowDot"
      readonly property real dotRadius: Style.spaceReal(2.2)
      visible: root.animating
      x: row.fillX - dotRadius
      y: row.midY - dotRadius
      width: dotRadius * 2
      height: width
      radius: dotRadius
      color: root.lift(root.tone, 0.85)
    }
  }
}
