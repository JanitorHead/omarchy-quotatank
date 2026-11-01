pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons

// Meter style "Pill": a thick pill, like a modern app's progress bar. Card: the fill with a gloss, its end
// cut straight into a tinted, dashed continuation to where this pace takes the limit by its reset (urgent
// when it runs out): one capsule, never two bubbles. The pace tick, under the pointer, cuts through it.
// While the account spends, a diagonal sheen sweeps the fill, the outline crawls and the fill's tip
// breathes on the beat and rings once per request; all faster as the pace presses on the limit.
// Row: a thin pill whose tip glows while spending.
// See MeterProjection.qml for the host contract.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property var motion: host ? host.motion : null

  readonly property bool remaining: !!model && model.quotaMode === "Remaining"
  readonly property bool moving: !!model && model.moving && visible
  readonly property bool running: moving && !!motion && !motion.reduced
  readonly property real seconds: running ? motion.liveSeconds : 0
  // How hard the pace presses on the limit, capped so a burst does not turn the sheen into a flicker.
  readonly property real ratio: model ? Math.max(0, Math.min(2.5, model.pressure)) : 0
  readonly property real beat: running && model.period > 0
    ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((seconds / model.period) % 1)) : 0
  readonly property real requestAge: running && model.requestAt > 0 ? seconds - model.requestAt : -1
  property real edgeFill: model ? model.fill : 0
  // The solid part: the fill under Used; under Remaining what is left by the reset at this pace, the
  // stretch to the fill's edge being the forecast (as the block meter draws it).
  readonly property real solidFill: model && remaining && model.forecastShown ? Math.min(edgeFill, model.forecastFrom) : edgeFill

  readonly property bool lightTheme: Commons.Color.background.hslLightness > 0.5
  readonly property color tone: host ? host.tone : "transparent"
  readonly property color forecastTone: !host ? "transparent" : model && model.runsOut ? host.urgent : host.tone

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function mix(a, b, k) { return Qt.rgba(a.r + (b.r - a.r) * k, a.g + (b.g - a.g) * k, a.b + (b.b - a.b) * k, 1) }
  // Towards white on a dark theme, towards black on a light one: a highlight that reads on either.
  function lift(color, k) { return lightTheme ? mix(color, Qt.rgba(0, 0, 0, 1), k * 0.45) : mix(color, Qt.rgba(1, 1, 1, 1), k) }

  implicitHeight: variant === "row" ? Style.space(9) : Style.space(28)

  LiveClaim {
    motion: root.motion
    active: root.moving
  }

  Behavior on edgeFill {
    NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
  }

  Item {
    id: card
    objectName: "pillCard"
    visible: root.variant === "card" && !!root.model && root.model.hasMeter
    anchors.fill: parent

    readonly property real inset: Style.space(1)
    readonly property real span: Math.max(0, width - 2 * inset)
    readonly property real pillY: Style.space(3)
    readonly property real pillHeight: Style.space(22)
    readonly property real pillRadius: pillHeight / 2
    // Any fill at all shows at least a round tip, never a sliver.
    readonly property real solidWidth: root.solidFill > 0 ? Math.max(pillHeight, xAt(root.solidFill) - inset) : 0
    readonly property real edgeX: root.edgeFill > 0 ? inset + Math.max(pillHeight, xAt(root.edgeFill) - inset) : inset
    readonly property bool forecastShown: !!root.model && root.model.forecastShown
    readonly property real forecastStart: inset + solidWidth
    readonly property real forecastEnd: Math.max(forecastStart + pillRadius,
      root.remaining ? edgeX : xAt(forecastShown ? root.model.forecastTo : 0))
    // The forecast continues the fill: one capsule, the fill's end cut straight where the forecast takes over,
    // so use and projection never read as two bubbles.
    readonly property bool joined: forecastShown && solidWidth > 0
    // The fill's shape is drawn this much wider and clipped, which squares its right end when joined.
    readonly property real fillOverhang: joined ? pillHeight : 0

    function xAt(fraction) { return inset + span * Math.max(0, Math.min(1, fraction)) }

    Rectangle {
      x: card.inset
      y: card.pillY
      width: card.span
      height: card.pillHeight
      radius: card.pillRadius
      color: root.host ? root.alpha(root.host.foreground, root.lightTheme ? 0.09 : 0.07) : "transparent"
    }

    // Forecast: a faint tint and a dashed outline from the fill's end to where this pace takes the limit;
    // under Remaining the stretch of the fill this pace spends. Open on the side it joins the fill; the
    // outline crawls while spending.
    Item {
      visible: card.forecastShown
      x: card.forecastStart
      y: card.pillY
      width: card.forecastEnd - card.forecastStart
      height: card.pillHeight
      clip: true

      Rectangle {
        x: -card.fillOverhang
        width: parent.width + card.fillOverhang
        height: parent.height
        radius: card.pillRadius
        color: root.alpha(root.forecastTone, root.remaining ? 0.16 : 0.08)
      }
    }

    Shape {
      id: forecastOutline
      objectName: "pillForecast"
      readonly property real dashPeriod: Style.spaceReal(7)
      readonly property real march: root.running
        ? ((root.seconds * Style.spaceReal(10 + 14 * root.ratio)) % dashPeriod) * (root.remaining ? 1 : -1) : 0
      readonly property real inner: outlinePath.strokeWidth / 2
      readonly property real bend: Math.max(0, height / 2 - inner)
      readonly property real rightX: Math.max(inner, width - height / 2)
      visible: card.forecastShown
      x: card.forecastStart
      y: card.pillY
      width: card.forecastEnd - card.forecastStart
      height: card.pillHeight
      // The curve renderer drops this dashed stroke while its offset moves (seen in the harness, Qt 6.12).
      preferredRendererType: Shape.GeometryRenderer

      ShapePath {
        id: outlinePath
        strokeColor: root.alpha(root.forecastTone, root.model && root.model.runsOut ? 0.85 : 0.45)
        strokeWidth: Style.spaceReal(1.2)
        strokeStyle: ShapePath.DashLine
        dashPattern: [4 / 1.2, 3 / 1.2]
        dashOffset: forecastOutline.march / outlinePath.strokeWidth
        fillColor: "transparent"

        // Joined: top edge, the round end, bottom edge, open where the fill is. Alone: a whole capsule.
        PathSvg {
          readonly property real t: forecastOutline.inner
          readonly property real b: forecastOutline.height - forecastOutline.inner
          readonly property real r: forecastOutline.bend
          readonly property real right: forecastOutline.rightX
          readonly property real left: Math.min(right, forecastOutline.height / 2)
          path: card.joined
            ? "M 0 " + t + " L " + right + " " + t + " A " + r + " " + r + " 0 0 1 " + right + " " + b + " L 0 " + b
            : "M " + left + " " + t + " L " + right + " " + t + " A " + r + " " + r + " 0 0 1 " + right + " " + b
              + " L " + left + " " + b + " A " + r + " " + r + " 0 0 1 " + left + " " + t + " Z"
        }
      }
    }

    // The fill, deepening towards its start, with a gloss over its upper half.
    Item {
      id: fillClip
      visible: card.solidWidth > 0
      x: card.inset
      y: card.pillY
      width: card.solidWidth
      height: card.pillHeight
      clip: true

      Rectangle {
        objectName: "pillFill"
        width: fillClip.width + card.fillOverhang
        height: fillClip.height
        radius: card.pillRadius
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0; color: root.mix(root.tone, Commons.Color.background, 0.25) }
          GradientStop { position: 1; color: root.tone }
        }
      }

      Rectangle {
        width: fillClip.width + card.fillOverhang
        height: fillClip.height
        radius: card.pillRadius
        gradient: Gradient {
          GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0.22) }
          GradientStop { position: 0.55; color: Qt.rgba(1, 1, 1, 0) }
        }
      }
    }

    // Spending: a diagonal sheen sweeps the fill, a gradient band cut to the fill's shape.
    Shape {
      id: sheen
      objectName: "pillSheen"
      readonly property real band: Style.spaceReal(30)
      readonly property real travel: Math.max(1, width + 2 * Style.spaceReal(40))
      readonly property real run: (root.seconds * Style.spaceReal(60 + 120 * root.ratio)) % travel
      // The band's middle at half height; under Remaining it runs back towards the start.
      readonly property real centre: root.remaining ? width + Style.spaceReal(40) - run : run - Style.spaceReal(40)
      visible: root.running && card.solidWidth > 0
      clip: true
      x: card.inset
      y: card.pillY
      width: card.solidWidth
      height: card.pillHeight

      ShapePath {
        strokeWidth: -1
        strokeColor: "transparent"
        // Across the band, which leans about 54° like the gallery's.
        fillGradient: LinearGradient {
          x1: sheen.centre - sheen.band * 0.59
          y1: sheen.height / 2 - sheen.band * 0.81
          x2: sheen.centre + sheen.band * 0.59
          y2: sheen.height / 2 + sheen.band * 0.81
          GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0) }
          GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.28) }
          GradientStop { position: 1; color: Qt.rgba(1, 1, 1, 0) }
        }

        PathRectangle {
          width: sheen.width + card.fillOverhang
          height: sheen.height
          radius: sheen.height / 2
        }
      }
    }

    // Spending: the tip breathes, a soft light swelling on the beat.
    Shape {
      id: tipGlow
      readonly property real reach: card.pillRadius + Style.spaceReal(6)
      visible: root.running && root.edgeFill > 0
      x: card.edgeX - card.pillRadius - reach
      y: card.pillY + card.pillRadius - reach
      width: reach * 2
      height: reach * 2
      scale: (card.pillRadius + Style.spaceReal(6) * root.beat) / reach

      ShapePath {
        strokeWidth: -1
        strokeColor: "transparent"
        fillGradient: RadialGradient {
          centerX: tipGlow.reach
          centerY: tipGlow.reach
          centerRadius: tipGlow.reach
          focalX: tipGlow.reach
          focalY: tipGlow.reach
          GradientStop { position: 0; color: root.alpha(root.lift(root.tone, 0.35), 0.45) }
          GradientStop { position: 1; color: root.alpha(root.lift(root.tone, 0.35), 0) }
        }

        PathRectangle {
          width: tipGlow.width
          height: tipGlow.height
        }
      }
    }

    // A request: a ring spreads from the tip.
    Rectangle {
      objectName: "pillRipple"
      readonly property real progress: root.requestAge >= 0 && root.requestAge < 0.8 ? root.requestAge / 0.8 : -1
      readonly property real reach: card.pillRadius - Style.spaceReal(2) + Style.spaceReal(14) * Math.max(0, progress)
      visible: progress >= 0
      x: card.edgeX - card.pillRadius - reach
      y: card.pillY + card.pillRadius - reach
      width: reach * 2
      height: reach * 2
      radius: reach
      color: "transparent"
      border.width: Style.spacing.hairline
      border.color: root.alpha(root.lift(root.tone, 0.3), 1 - Math.max(0, progress))
    }

    // Pace tick: a cut through the pill where even use would be by now, with caps above and below so it
    // reads on the fill and on the track alike.
    Item {
      id: paceTick
      objectName: "pillPaceTick"
      readonly property real at: Math.round(card.xAt(root.model ? root.model.markValue : 0) - width / 2)
      visible: !!root.model && root.model.markValue >= 0 && !!root.host && root.host.markShown
      x: at
      y: card.pillY - Style.space(3)
      width: Style.space(2)
      height: card.pillHeight + Style.space(6)

      Rectangle {
        width: parent.width
        height: parent.height
        color: root.host ? root.alpha(root.host.foreground, 0.9) : "transparent"
      }

      // Over the solid fill the tick is a dark cut, as on the block meter.
      Rectangle {
        visible: paceTick.at + paceTick.width <= card.inset + card.solidWidth
        y: Style.space(3)
        width: parent.width
        height: card.pillHeight
        color: Commons.Color.background
      }
    }
  }

  Item {
    id: rowPill
    objectName: "pillRow"
    visible: root.variant === "row" && !!root.model
    anchors.fill: parent

    readonly property real pillHeight: Style.space(6)
    readonly property real pillY: Math.round((height - pillHeight) / 2)
    readonly property real fillWidth: root.edgeFill > 0 ? Math.max(pillHeight, Math.round(width * Math.min(1, root.edgeFill))) : 0

    Rectangle {
      y: rowPill.pillY
      width: parent.width
      height: rowPill.pillHeight
      radius: height / 2
      color: root.host ? root.alpha(root.host.foreground, 0.1) : "transparent"
    }

    // Spending: the tip glows over the fill, swelling on the beat.
    Shape {
      id: rowGlow
      z: 1
      readonly property real reach: Style.spaceReal(9)
      visible: root.running && rowPill.fillWidth > 0
      x: rowPill.fillWidth - rowPill.pillHeight / 2 - reach
      y: rowPill.pillY + rowPill.pillHeight / 2 - reach
      width: reach * 2
      height: reach * 2
      scale: (6 + 3 * root.beat) / 9

      ShapePath {
        strokeWidth: -1
        strokeColor: "transparent"
        fillGradient: RadialGradient {
          centerX: rowGlow.reach
          centerY: rowGlow.reach
          centerRadius: rowGlow.reach
          focalX: rowGlow.reach
          focalY: rowGlow.reach
          GradientStop { position: 0; color: root.alpha(root.lift(root.tone, 0.35), 0.6) }
          GradientStop { position: 1; color: root.alpha(root.lift(root.tone, 0.35), 0) }
        }

        PathRectangle {
          width: rowGlow.width
          height: rowGlow.height
        }
      }
    }

    Rectangle {
      objectName: "pillRowFill"
      visible: rowPill.fillWidth > 0
      y: rowPill.pillY
      width: rowPill.fillWidth
      height: rowPill.pillHeight
      radius: height / 2
      color: root.tone
    }
  }
}
