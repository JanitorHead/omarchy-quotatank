pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons

// Meter style "Race": time against use. Card: a thin time rail on top (how much of the window has gone,
// the ring is now, labelled "time 59%" and how far use runs ahead of or behind it) over a thick bar with
// the fill; a dashed outline and a ◆ mark where this pace takes the limit by its reset. While the account
// spends, white stripes march through the fill, the outline crawls, the fill's edge glows on the beat and
// rings once per request; all faster as the pace presses on the limit. Row: the same two rails, thin.
//
// The time rail is what this style compares against, so it shows whenever the window has a pace; the pace
// tick proper (a dashed drop from the ring through the bar) follows `host.markShown`. See
// MeterProjection.qml for the host contract.
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
  // How hard the pace presses on the limit, capped so a burst does not turn the stripes into a blur.
  readonly property real ratio: model ? Math.max(0, Math.min(2.5, model.pressure)) : 0
  readonly property real beat: running && model.period > 0
    ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((seconds / model.period) % 1)) : 0
  // Where even use would be by now on the chosen side (the time rail), -1 without a pace.
  readonly property real markValue: model ? model.markValue : -1
  readonly property bool hasMark: markValue >= 0
  property real edgeFill: model ? model.fill : 0
  // The solid part of the bar: the fill under Used; under Remaining what is left by the reset at this pace,
  // the stretch to the fill's edge being the forecast (as the block meter draws it).
  readonly property real solidFill: model && remaining && model.forecastShown ? Math.min(edgeFill, model.forecastFrom) : edgeFill
  // A request rings the fill's edge for a moment.
  readonly property real requestAge: running && model.requestAt > 0 ? seconds - model.requestAt : -1

  readonly property bool lightTheme: Commons.Color.background.hslLightness > 0.5
  readonly property color tone: host ? host.tone : "transparent"
  readonly property color hi: !host ? "transparent"
    : model && (model.runsOut || model.pressure > 1) ? lift(host.urgent, 0.25) : lift(host.tone, 0.3)
  readonly property color forecastColor: !host ? "transparent"
    : model && model.runsOut ? alpha(host.urgent, 0.9) : alpha(host.foreground, 0.42)

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function mix(a, b, k) { return Qt.rgba(a.r + (b.r - a.r) * k, a.g + (b.g - a.g) * k, a.b + (b.b - a.b) * k, 1) }
  // Towards white on a dark theme, towards black on a light one: a highlight that reads on either.
  function lift(color, k) { return lightTheme ? mix(color, Qt.rgba(0, 0, 0, 1), k * 0.45) : mix(color, Qt.rgba(1, 1, 1, 1), k) }

  implicitHeight: variant === "row" ? Style.space(9) : card.implicitHeight

  LiveClaim {
    motion: root.motion
    active: root.moving
  }

  Behavior on edgeFill {
    NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
  }

  FontMetrics {
    id: captionMetrics
    font.family: root.host ? root.host.fontFamily : Style.font.family
    font.pixelSize: Style.font.caption
  }

  Item {
    id: card
    objectName: "raceCard"
    visible: root.variant === "card" && !!root.model && root.model.hasMeter
    anchors.fill: parent

    // Room for the ring and the ◆ at either end.
    readonly property real inset: Style.space(4)
    readonly property real span: Math.max(0, width - 2 * inset)
    readonly property real railY: root.hasMark ? captionMetrics.height + Style.space(3) : 0
    readonly property real railHeight: Style.space(3)
    readonly property real barY: root.hasMark ? railY + railHeight + Style.space(7) : 0
    readonly property real barHeight: Style.space(12)
    readonly property real barRadius: barHeight / 2
    readonly property real footY: barY + barHeight + Style.space(3)
    readonly property real timeX: xAt(root.markValue)
    readonly property real edgeX: xAt(root.edgeFill)
    readonly property real solidWidth: root.solidFill > 0 ? xAt(root.solidFill) - inset : 0
    readonly property bool forecastShown: !!root.model && root.model.forecastShown
    // The forecast continues the fill as one capsule: the fill's end is cut straight where it takes over.
    readonly property bool joined: forecastShown && solidWidth > 0
    readonly property real fillOverhang: joined ? barHeight : 0
    // Use against time, in points of the limit: positive means ahead of an even pace.
    readonly property int delta: !root.model || !root.hasMark ? 0
      : Math.round((root.remaining ? root.markValue - root.model.fill : root.model.fill - root.markValue) * 100)

    function xAt(fraction) { return inset + span * Math.max(0, Math.min(1, fraction)) }

    implicitHeight: forecastShown ? footY + captionMetrics.height : barY + barHeight + Style.space(2)

    // Time labels above the rail: what share of the window has gone (or is left) and the gap to use.
    PlainText {
      id: timeLabel
      visible: root.hasMark
      x: Math.max(0, card.timeX - Style.space(8) - implicitWidth)
      y: 0
      text: "time " + Math.round(root.markValue * 100) + "%" + (root.remaining ? " left" : "")
      color: root.host ? root.host.dim : "transparent"
      font.family: captionMetrics.font.family
      font.pixelSize: Style.font.caption
    }

    PlainText {
      objectName: "raceDelta"
      readonly property bool far: card.delta > 5
      visible: root.hasMark && x > timeLabel.x + timeLabel.implicitWidth + Style.space(6)
      x: Math.min(card.width - implicitWidth, card.timeX + Style.space(8))
      y: 0
      text: card.delta >= 0 ? "+" + card.delta + " ahead" : -card.delta + " behind"
      color: !root.host ? "transparent" : !far ? root.host.dim
        : root.model.runsOut ? root.host.urgent : root.host.foreground
      font.family: captionMetrics.font.family
      font.pixelSize: Style.font.caption
      font.bold: far
    }

    // The time rail: the window's elapsed share (left share under Remaining) up to the ring.
    Rectangle {
      visible: root.hasMark
      x: card.inset
      y: card.railY
      width: card.span
      height: card.railHeight
      radius: height / 2
      color: root.host ? root.alpha(root.host.foreground, 0.1) : "transparent"
    }

    Rectangle {
      objectName: "raceTime"
      visible: root.hasMark
      x: card.inset
      y: card.railY
      width: card.timeX - card.inset
      height: card.railHeight
      radius: height / 2
      color: root.host ? root.alpha(root.host.foreground, 0.5) : "transparent"
    }

    // The bar's track.
    Rectangle {
      x: card.inset
      y: card.barY
      width: card.span
      height: card.barHeight
      radius: card.barRadius
      color: root.host ? root.alpha(root.host.foreground, 0.08) : "transparent"
    }

    // Forecast: a dashed outline from the fill's end to where this pace takes the limit, open where it
    // joins the fill; under Remaining the stretch of the fill this pace spends by the reset. It crawls while
    // spending.
    Shape {
      id: forecastOutline
      objectName: "raceForecast"
      readonly property real startX: card.inset + card.solidWidth
      readonly property real endX: Math.max(startX + card.barRadius,
        root.remaining ? card.edgeX : card.xAt(card.forecastShown ? root.model.forecastTo : 0))
      readonly property real dashPeriod: Style.spaceReal(7)
      readonly property real march: root.running
        ? ((root.seconds * Style.spaceReal(10 + 14 * root.ratio)) % dashPeriod) * (root.remaining ? 1 : -1) : 0
      readonly property real inner: outlinePath.strokeWidth / 2
      readonly property real bend: Math.max(0, height / 2 - inner)
      readonly property real rightX: Math.max(inner, width - height / 2)
      visible: card.forecastShown
      x: startX
      y: card.barY
      width: endX - startX
      height: card.barHeight
      // The curve renderer drops this dashed stroke while its offset moves (seen in the harness, Qt 6.12).
      preferredRendererType: Shape.GeometryRenderer

      ShapePath {
        id: outlinePath
        strokeColor: root.forecastColor
        strokeWidth: Style.spaceReal(1.2)
        strokeStyle: ShapePath.DashLine
        dashPattern: [4 / 1.2, 3 / 1.2]
        dashOffset: forecastOutline.march / outlinePath.strokeWidth
        fillColor: "transparent"

        // Joined: top edge, the round end, bottom edge. Alone: a whole capsule.
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

    // The fill, brightening towards its edge, with a gloss on its upper half.
    Item {
      id: fillClip
      visible: card.solidWidth > 0
      x: card.inset
      y: card.barY
      width: card.solidWidth
      height: card.barHeight
      clip: true

      Rectangle {
        objectName: "raceFill"
        width: fillClip.width + card.fillOverhang
        height: fillClip.height
        radius: card.barRadius
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0; color: root.alpha(root.tone, 0.45) }
          GradientStop { position: 1; color: root.running ? root.hi : root.tone }
        }
      }

      Rectangle {
        width: fillClip.width + card.fillOverhang
        height: fillClip.height
        radius: card.barRadius
        gradient: Gradient {
          GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0.13) }
          GradientStop { position: 0.45; color: Qt.rgba(1, 1, 1, 0.13) }
          GradientStop { position: 0.46; color: Qt.rgba(1, 1, 1, 0) }
        }
      }
    }

    // Spending: diagonal stripes march through the fill, a repeating gradient cut to the fill's shape.
    Shape {
      id: stripes
      objectName: "raceStripes"
      readonly property real period: Style.spaceReal(12)
      readonly property real shift: ((root.seconds * Style.spaceReal(14 + 26 * root.ratio)) % period) * (root.remaining ? -1 : 1)
      visible: root.running && card.solidWidth > 0
      clip: true
      x: card.inset
      y: card.barY
      width: card.solidWidth
      height: card.barHeight

      ShapePath {
        strokeWidth: -1
        strokeColor: "transparent"
        fillGradient: LinearGradient {
          spread: ShapeGradient.RepeatSpread
          x1: stripes.shift
          y1: 0
          x2: stripes.shift + stripes.period / 2
          y2: stripes.period / 2
          GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0) }
          GradientStop { position: 0.26; color: Qt.rgba(1, 1, 1, 0) }
          GradientStop { position: 0.27; color: Qt.rgba(1, 1, 1, 0.17) }
          GradientStop { position: 0.73; color: Qt.rgba(1, 1, 1, 0.17) }
          GradientStop { position: 0.74; color: Qt.rgba(1, 1, 1, 0) }
        }

        PathRectangle {
          width: stripes.width + card.fillOverhang
          height: stripes.height
          radius: stripes.height / 2
        }
      }
    }

    // Spending: a soft light on the fill's edge, swelling on the beat.
    Shape {
      id: edgeGlow
      readonly property real reach: Style.spaceReal(20)
      visible: root.running
      x: card.edgeX - Style.space(3) - reach
      y: card.barY + card.barRadius - reach
      width: reach * 2
      height: reach * 2
      scale: (14 + 6 * root.beat) / 20

      ShapePath {
        strokeWidth: -1
        strokeColor: "transparent"
        fillGradient: RadialGradient {
          centerX: edgeGlow.reach
          centerY: edgeGlow.reach
          centerRadius: edgeGlow.reach
          focalX: edgeGlow.reach
          focalY: edgeGlow.reach
          GradientStop { position: 0; color: root.alpha(root.hi, 0.55) }
          GradientStop { position: 1; color: root.alpha(root.hi, 0) }
        }

        PathRectangle {
          width: edgeGlow.width
          height: edgeGlow.height
        }
      }
    }

    // A request: a ring spreads from the fill's edge.
    Rectangle {
      objectName: "raceRipple"
      readonly property real progress: root.requestAge >= 0 && root.requestAge < 0.65 ? root.requestAge / 0.65 : -1
      readonly property real reach: Style.spaceReal(4 + 16 * Math.max(0, progress))
      visible: progress >= 0
      x: card.edgeX - Style.space(3) - reach
      y: card.barY + card.barRadius - reach
      width: reach * 2
      height: reach * 2
      radius: reach
      color: "transparent"
      border.width: Style.spacing.hairline
      border.color: Qt.rgba(1, 1, 1, 0.6 * (1 - Math.max(0, progress)))
    }

    // Pace tick: a dashed drop from the ring through the bar.
    Repeater {
      objectName: "racePaceTick"
      model: root.hasMark && !!root.host && root.host.markShown
        ? Math.max(0, Math.floor((card.barY + card.barHeight + Style.space(2) - card.railY - card.railHeight) / Style.space(4))) : 0

      Rectangle {
        required property int index
        x: Math.round(card.timeX)
        y: card.railY + card.railHeight + index * Style.space(4) + Style.space(1)
        width: Style.spacing.hairline
        height: Style.space(2)
        color: root.host ? root.alpha(root.host.foreground, 0.6) : "transparent"
      }
    }

    // Now on the time rail: a ring.
    Rectangle {
      objectName: "raceNow"
      readonly property real size: Style.space(7) + 1
      visible: root.hasMark
      x: card.timeX - size / 2
      y: card.railY + card.railHeight / 2 - size / 2
      width: size
      height: size
      radius: size / 2
      color: Commons.Color.background
      border.width: Math.max(1, Style.spaceReal(1.3))
      border.color: root.host ? root.alpha(root.host.foreground, 0.95) : "transparent"
    }

    // Where this pace takes the limit by its reset: ◆ and a short label.
    Item {
      id: landing
      objectName: "raceLanding"
      readonly property real at: !card.forecastShown ? 0 : card.xAt(root.remaining ? root.model.forecastFrom : root.model.forecastTo)
      readonly property color ink: !root.host || !root.model ? "transparent"
        : root.model.runsOut ? root.host.urgent : root.alpha(root.host.foreground, 0.7)
      readonly property bool leftward: at + Style.space(7) + landingText.implicitWidth > card.width
      visible: card.forecastShown
      anchors.fill: parent

      Rectangle {
        readonly property real size: Style.space(5)
        x: landing.at - size / 2
        y: card.footY + captionMetrics.height / 2 - size / 2
        width: size
        height: size
        rotation: 45
        antialiasing: true
        color: landing.ink
      }

      PlainText {
        id: landingText
        x: landing.leftward ? landing.at - Style.space(7) - implicitWidth : landing.at + Style.space(7)
        y: card.footY
        text: !card.forecastShown ? ""
          : root.model.runsOut ? "runs out"
          : root.remaining ? Math.round(root.model.forecastFrom * 100) + "% left at reset"
          : Math.round(root.model.forecastTo * 100) + "% at reset"
        color: landing.ink
        font.family: captionMetrics.font.family
        font.pixelSize: Style.font.caption
      }
    }
  }

  Item {
    id: rowBar
    objectName: "raceRow"
    visible: root.variant === "row" && !!root.model
    anchors.fill: parent

    readonly property real railHeight: Style.space(2)
    readonly property real barY: railHeight + Style.space(2)
    readonly property real barHeight: Math.max(2, height - barY)
    readonly property real fillWidth: Math.round(width * Math.max(0, Math.min(1, root.edgeFill)))

    // The time rail.
    Rectangle {
      visible: root.hasMark
      width: parent.width
      height: rowBar.railHeight
      color: root.host ? root.alpha(root.host.foreground, 0.1) : "transparent"
    }

    Rectangle {
      visible: root.hasMark
      width: Math.round(parent.width * root.markValue)
      height: rowBar.railHeight
      color: root.host ? root.alpha(root.host.foreground, 0.55) : "transparent"
    }

    Rectangle {
      y: rowBar.barY
      width: parent.width
      height: rowBar.barHeight
      radius: height / 2
      color: root.host ? root.alpha(root.host.foreground, 0.08) : "transparent"
    }

    Rectangle {
      visible: rowBar.fillWidth > 0
      y: rowBar.barY
      width: rowBar.fillWidth
      height: rowBar.barHeight
      radius: height / 2
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: root.alpha(root.tone, 0.5) }
        GradientStop { position: 1; color: root.running ? root.hi : root.tone }
      }
    }

    Shape {
      id: rowStripes
      objectName: "raceRowStripes"
      readonly property real period: Style.spaceReal(8)
      readonly property real shift: ((root.seconds * Style.spaceReal(10 + 18 * root.ratio)) % period) * (root.remaining ? -1 : 1)
      visible: root.running && rowBar.fillWidth > 0
      y: rowBar.barY
      width: rowBar.fillWidth
      height: rowBar.barHeight

      ShapePath {
        strokeWidth: -1
        strokeColor: "transparent"
        fillGradient: LinearGradient {
          spread: ShapeGradient.RepeatSpread
          x1: rowStripes.shift
          y1: 0
          x2: rowStripes.shift + rowStripes.period / 2
          y2: rowStripes.period / 2
          GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0) }
          GradientStop { position: 0.3; color: Qt.rgba(1, 1, 1, 0) }
          GradientStop { position: 0.31; color: Qt.rgba(1, 1, 1, 0.22) }
          GradientStop { position: 0.69; color: Qt.rgba(1, 1, 1, 0.22) }
          GradientStop { position: 0.7; color: Qt.rgba(1, 1, 1, 0) }
        }

        PathRectangle {
          width: rowStripes.width
          height: rowStripes.height
          radius: rowStripes.height / 2
        }
      }
    }
  }
}
