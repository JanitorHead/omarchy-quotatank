pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons
import "UsageLogic.js" as UsageLogic

// Meter style "Rings" (group): the account's limits as concentric rings, like a watch's activity rings, the
// shortest window outside, with a legend beside them. Each ring fills to the figure on the chosen side,
// brightening towards its head; a thin arc carries on to where this pace takes the limit by its reset,
// urgent when it runs out first (under Remaining it lies on the stretch of the fill this pace spends). The
// centre says how long until the first limit runs out, "used up", or ✓ when every limit lasts. While the
// account spends, a glint runs along each fill to its head (back from the head under Remaining), the head
// breathes on the beat and each request rings from it, all faster as the pace presses on the limit. The
// legend gives each ring's label, figure, verdict and live rate. Row: at about 60×6 px a ring segment is a
// smudge, so it is the gallery's bar: the fill on a tinted track, its head breathing while spending.
// Card: nothing, limit cards hide under group styles. See MeterProjection.qml for the host contract.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property var motion: host ? host.motion : null
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family
  readonly property bool lightTheme: Commons.Color.background.hslLightness > 0.5
  // White on a dark theme, the background on a light one: the head reads on any fill.
  readonly property color headColor: lightTheme ? Commons.Color.background : Qt.rgba(1, 1, 1, 0.95)

  // Group: the rings on the left, outermost first, and a legend entry per window on the right.
  readonly property var windows: variant === "group" && host && host.windows ? host.windows : []
  readonly property int count: windows.length
  readonly property real ringSize: Math.round(Math.min(Style.spaceReal(140), Math.max(Style.spaceReal(96), width * 0.42)))
  // The rings share what lies outside the centre's hole; thinner as they get more.
  readonly property real holeRadius: Style.spaceReal(30)
  readonly property real ringPitch: count > 0 ? (ringSize / 2 - holeRadius) / count : 0
  readonly property real ringWidth: Math.min(Style.spaceReal(13), ringPitch * 0.7)
  readonly property real legendX: ringSize + Style.spaceReal(14)
  readonly property real entryGap: Style.spaceReal(count > 2 ? 8 : 12)
  // The legend's first line: label and figure.
  readonly property real lineHeight: Math.max(bodyMetrics.height, headingMetrics.height)
  readonly property real groupHeight: Math.ceil(Math.max(ringSize, legend.height))
  readonly property real ringTop: Math.round((groupHeight - ringSize) / 2)

  // The centre: how long until the first limit runs out at this pace, "used up", or ✓ when all last.
  readonly property var centre: {
    var now = host ? host.nowSeconds : 0
    var soonest = -1
    var known = false
    for (var i = 0; i < count; i++) {
      var forecast = UsageLogic.windowForecast(windows[i], now)
      if (!forecast) continue
      known = true
      if (forecast.pace.exhausted) return { kind: "out", text: "used up", note: "" }
      if (forecast.runsOut && (soonest < 0 || forecast.runsOutAt < soonest)) soonest = forecast.runsOutAt
    }
    if (soonest >= 0) return { kind: "runs", text: UsageLogic.formatDuration(soonest - now), note: "to empty" }
    return known ? { kind: "lasts", text: "✓", note: "lasts" } : { kind: "", text: "", note: "" }
  }

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function mix(a, b, k) { return Qt.rgba(a.r + (b.r - a.r) * k, a.g + (b.g - a.g) * k, a.b + (b.b - a.b) * k, 1) }
  // Towards white on a dark theme, towards black on a light one: a highlight that reads on either.
  function lift(color, k) { return lightTheme ? mix(color, Qt.rgba(0, 0, 0, 1), k * 0.45) : mix(color, Qt.rgba(1, 1, 1, 1), k) }
  function beatOf(seconds, period) { return period > 0 ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((seconds / period) % 1)) : 0 }
  // A ring's colour: urgent at a threshold, else the tone, stepping towards the background ring by ring
  // inwards so neighbours read apart (the gallery's second colour).
  function ringTone(index, row) {
    if (!host || !row) return "transparent"
    var tone = host.toneOf(row)
    return host.stressed(row) || index === 0 ? tone : mix(tone, Commons.Color.background, index === 1 ? 0.3 : 0.48)
  }

  implicitHeight: variant === "row" ? Style.space(6) : variant === "group" ? group.height : 0

  FontMetrics {
    id: bodyMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
    font.bold: true
  }

  FontMetrics {
    id: headingMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.heading
    font.bold: true
  }

  Item {
    id: group
    objectName: "ringGroup"
    visible: root.variant === "group"
    width: parent.width
    height: root.count > 0 ? root.groupHeight : 0

    // The rings. Each legend entry owns its window's LimitModel and hands its ring in here.
    Item {
      id: ringArea
      objectName: "ringArea"
      y: root.ringTop
      width: root.ringSize
      height: root.ringSize
    }

    // The legend, a column so a verdict too long for one line wraps.
    Column {
      id: legend
      objectName: "ringLegend"
      x: root.legendX
      y: Math.round((root.groupHeight - height) / 2)
      width: Math.max(0, parent.width - root.legendX)
      spacing: root.entryGap

      Repeater {
        model: root.count

        Item {
          id: ring
          required property int index
          readonly property var row: root.windows[index] || null
          readonly property LimitModel limit: LimitModel {
            window: ring.row
            nowSeconds: root.host ? root.host.nowSeconds : 0
            quotaMode: root.host ? root.host.quotaMode : "Used"
            spending: !!root.host && root.host.spending
            readingAt: root.host ? root.host.readingAt : 0
            requestAt: root.host ? root.host.requestAt : 0
            account: root.host ? root.host.account : null
          }
          readonly property color tone: root.ringTone(index, row)
          readonly property bool remaining: limit.quotaMode === "Remaining"
          readonly property bool moving: limit.moving && group.visible
          readonly property bool running: moving && !!root.motion && !root.motion.reduced
          readonly property real seconds: running ? root.motion.liveSeconds : 0
          readonly property real beat: running ? root.beatOf(seconds, limit.period) : 0
          property real edge: limit.fill
          // The solid ring: the fill under Used; under Remaining what this pace leaves by the reset, the
          // rest of the fill being the forecast.
          readonly property real solid: limit.forecastShown ? Math.min(edge, limit.forecastFrom) : edge
          // The glint: a short sheen running the fill to its head over 1.4 beats, fading in and out; back
          // from the head under Remaining, where spending eats the fill from its head.
          readonly property real glintSpan: Math.min(20, 360 * edge)
          readonly property real glintTravel: 360 * edge - glintSpan
          readonly property bool glinting: running && glintTravel > 2
          readonly property real glintPhase: glinting ? (seconds / (limit.period * 1.4)) % 1 : 0
          readonly property real requestAge: running && limit.requestAt > 0 ? seconds - limit.requestAt : -1

          objectName: "ringEntry-" + index
          width: legend.width
          height: chip.visible ? chip.y + chip.height : verdict.y + verdict.height

          LiveClaim {
            motion: root.motion
            active: ring.moving
          }

          Behavior on edge {
            NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
          }

          Item {
            id: dial
            objectName: "ringDial"
            parent: ringArea
            width: root.ringSize
            height: root.ringSize

            readonly property real centre: width / 2
            readonly property real radius: root.ringSize / 2 - root.ringWidth / 2 - ring.index * root.ringPitch
            readonly property real outer: radius + root.ringWidth / 2
            readonly property real inner: radius - root.ringWidth / 2
            readonly property point head: pointAt(ring.edge, radius)

            // Degrees clockwise from three o'clock, the ring starting at twelve.
            function angleOf(fraction) { return -90 + 360 * Math.max(0, Math.min(1, fraction)) }
            function pointAt(fraction, distance) {
              var angle = angleOf(fraction) * Math.PI / 180
              return Qt.point(centre + distance * Math.cos(angle), centre + distance * Math.sin(angle))
            }

            // The track, tinted with the ring's colour, and under Remaining the stretch of the fill this
            // pace spends, kept faintly lit under the forecast.
            Shape {
              anchors.fill: parent
              preferredRendererType: Shape.CurveRenderer

              ShapePath {
                strokeColor: root.alpha(ring.tone, root.lightTheme ? 0.18 : 0.14)
                strokeWidth: root.ringWidth
                fillColor: "transparent"

                PathAngleArc {
                  centerX: dial.centre
                  centerY: dial.centre
                  radiusX: dial.radius
                  radiusY: dial.radius
                  startAngle: 0
                  sweepAngle: 360
                }
              }

              ShapePath {
                strokeColor: ring.remaining && ring.edge > ring.solid ? root.alpha(ring.tone, 0.3) : "transparent"
                strokeWidth: root.ringWidth
                fillColor: "transparent"
                capStyle: ShapePath.FlatCap

                PathAngleArc {
                  centerX: dial.centre
                  centerY: dial.centre
                  radiusX: dial.radius
                  radiusY: dial.radius
                  startAngle: dial.angleOf(ring.solid)
                  sweepAngle: 360 * Math.max(0, ring.edge - ring.solid)
                }
              }
            }

            // The fill, a ring-shaped area with round ends so its gradient can follow it from deep at its
            // start to lifted at its head (a conical gradient runs anticlockwise, here from twelve o'clock).
            Shape {
              objectName: "ringFill"
              visible: ring.solid > 0
              anchors.fill: parent
              preferredRendererType: Shape.CurveRenderer

              ShapePath {
                id: fillPath
                readonly property real share: Math.min(0.999, ring.solid)
                readonly property real endRadians: dial.angleOf(share) * Math.PI / 180
                strokeWidth: -1
                strokeColor: "transparent"
                fillRule: ShapePath.WindingFill
                fillGradient: ConicalGradient {
                  centerX: dial.centre
                  centerY: dial.centre
                  angle: 90
                  GradientStop { position: 0; color: root.mix(ring.tone, Commons.Color.background, 0.3) }
                  GradientStop { position: 1 - fillPath.share; color: root.lift(ring.tone, 0.12) }
                  GradientStop { position: 1; color: root.mix(ring.tone, Commons.Color.background, 0.3) }
                }
                startX: dial.centre
                startY: dial.centre - dial.outer

                PathAngleArc {
                  centerX: dial.centre
                  centerY: dial.centre
                  radiusX: dial.outer
                  radiusY: dial.outer
                  startAngle: -90
                  sweepAngle: 360 * fillPath.share
                  moveToStart: false
                }
                PathArc {
                  x: dial.centre + dial.inner * Math.cos(fillPath.endRadians)
                  y: dial.centre + dial.inner * Math.sin(fillPath.endRadians)
                  radiusX: root.ringWidth / 2
                  radiusY: root.ringWidth / 2
                }
                PathAngleArc {
                  centerX: dial.centre
                  centerY: dial.centre
                  radiusX: dial.inner
                  radiusY: dial.inner
                  startAngle: -90 + 360 * fillPath.share
                  sweepAngle: -360 * fillPath.share
                  moveToStart: false
                }
                PathArc {
                  x: fillPath.startX
                  y: fillPath.startY
                  radiusX: root.ringWidth / 2
                  radiusY: root.ringWidth / 2
                }
              }
            }

            // The forecast: a thin arc from the fill's edge to where this pace takes the limit by its reset.
            Shape {
              objectName: "ringForecast"
              visible: ring.limit.forecastShown
              anchors.fill: parent
              preferredRendererType: Shape.CurveRenderer

              ShapePath {
                strokeColor: !root.host ? "transparent"
                  : ring.limit.runsOut ? root.alpha(root.host.urgent, 0.85) : root.alpha(ring.tone, ring.remaining ? 0.75 : 0.45)
                strokeWidth: root.ringWidth * 0.32
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap

                PathAngleArc {
                  centerX: dial.centre
                  centerY: dial.centre
                  radiusX: dial.radius
                  radiusY: dial.radius
                  startAngle: dial.angleOf(ring.limit.forecastFrom)
                  sweepAngle: 360 * Math.max(0, ring.limit.forecastTo - ring.limit.forecastFrom)
                }
              }
            }

            // The glint, drawn once ending at three o'clock and turned into place, so only its rotation and
            // opacity change from frame to frame.
            Item {
              id: glint
              objectName: "ringGlint"
              readonly property real size: 2 * (dial.radius + root.ringWidth)
              readonly property real half: size / 2
              visible: ring.glinting
              x: dial.centre - half
              y: dial.centre - half
              width: size
              height: size
              // Its leading end: up to the head, or from the head back to the start.
              rotation: ring.remaining ? -90 + ring.glintTravel * (1 - ring.glintPhase)
                : -90 + ring.glintSpan + ring.glintTravel * ring.glintPhase
              opacity: 0.4 * Math.sin(Math.PI * ring.glintPhase)

              Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                transform: Scale {
                  origin.x: glint.half
                  origin.y: glint.half
                  yScale: ring.remaining ? -1 : 1
                }

                ShapePath {
                  strokeColor: root.lift(ring.tone, 0.85)
                  strokeWidth: Math.max(Style.spaceReal(2), root.ringWidth - Style.spaceReal(4))
                  fillColor: "transparent"
                  capStyle: ShapePath.RoundCap

                  PathAngleArc {
                    centerX: glint.half
                    centerY: glint.half
                    radiusX: dial.radius
                    radiusY: dial.radius
                    startAngle: -ring.glintSpan
                    sweepAngle: ring.glintSpan
                  }
                }
              }
            }

            // Spending: a soft light at the head, swelling on the beat.
            Shape {
              id: halo
              objectName: "ringHalo"
              readonly property real reach: Style.spaceReal(15)
              visible: ring.running
              x: dial.head.x - reach
              y: dial.head.y - reach
              width: reach * 2
              height: reach * 2
              scale: (Style.spaceReal(9) + Style.spaceReal(6) * ring.beat) / reach
              preferredRendererType: Shape.CurveRenderer

              ShapePath {
                strokeWidth: -1
                strokeColor: "transparent"
                fillGradient: RadialGradient {
                  centerX: halo.reach
                  centerY: halo.reach
                  centerRadius: halo.reach
                  focalX: halo.reach
                  focalY: halo.reach
                  GradientStop { position: 0; color: root.alpha(root.lift(ring.tone, 0.3), 0.6) }
                  GradientStop { position: 1; color: root.alpha(root.lift(ring.tone, 0.3), 0) }
                }

                PathAngleArc {
                  centerX: halo.reach
                  centerY: halo.reach
                  radiusX: halo.reach
                  radiusY: halo.reach
                  startAngle: 0
                  sweepAngle: 360
                }
              }
            }

            // A request: a ring spreads from the head.
            Rectangle {
              objectName: "ringRipple"
              readonly property real progress: ring.requestAge >= 0 && ring.requestAge < 0.8 ? ring.requestAge / 0.8 : -1
              readonly property real reach: Style.spaceReal(4) + Style.spaceReal(10) * Math.max(0, progress)
              visible: progress >= 0
              x: dial.head.x - reach
              y: dial.head.y - reach
              width: reach * 2
              height: reach * 2
              radius: reach
              color: "transparent"
              border.width: Style.spacing.hairline
              border.color: root.alpha(root.lift(ring.tone, 0.3), 0.8 * (1 - Math.max(0, progress)))
            }

            Rectangle {
              objectName: "ringHead"
              readonly property real diameter: Style.spaceReal(5)
              visible: ring.limit.hasMeter
              x: dial.head.x - diameter / 2
              y: dial.head.y - diameter / 2
              width: diameter
              height: diameter
              radius: diameter / 2
              color: root.headColor
            }

            // Pace tick: a bar across the ring where even use would be by now.
            Rectangle {
              id: paceTick
              objectName: "ringPace"
              readonly property real from: dial.inner - Style.spaceReal(2)
              visible: !!root.host && root.host.markShown && ring.limit.markValue >= 0
              x: dial.centre + from
              y: dial.centre - height / 2
              width: dial.outer + Style.spaceReal(2) - from
              height: Style.spaceReal(2)
              antialiasing: true
              color: root.host ? root.alpha(root.host.foreground, 0.95) : "transparent"
              transform: Rotation {
                origin.x: -paceTick.from
                origin.y: paceTick.height / 2
                angle: dial.angleOf(ring.limit.markValue)
              }
            }
          }

          Rectangle {
            id: swatch
            readonly property real diameter: Style.spaceReal(9)
            y: Math.round((root.lineHeight - diameter) / 2)
            width: diameter
            height: diameter
            radius: diameter / 2
            color: ring.tone
          }

          PlainText {
            id: unit
            visible: ring.limit.known
            anchors.right: parent.right
            anchors.baseline: figure.baseline
            text: root.host ? root.host.unitText() : ""
            color: root.host ? root.host.dim : "transparent"
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          PlainText {
            id: figure
            objectName: "ringFigure"
            anchors.right: unit.visible ? unit.left : parent.right
            anchors.rightMargin: unit.visible ? Style.spacing.sm : 0
            y: Math.round((root.lineHeight - height) / 2)
            text: root.host ? root.host.figureText(ring.limit) : ""
            color: !root.host ? "transparent" : ring.row && root.host.stressed(ring.row) ? root.host.urgent : root.host.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
            font.bold: true
          }

          PlainText {
            id: label
            objectName: "ringLabel"
            anchors.left: swatch.right
            anchors.leftMargin: Style.spacing.lg
            anchors.right: figure.left
            anchors.rightMargin: Style.spacing.controlGap
            anchors.baseline: figure.baseline
            text: root.host && ring.row ? root.host.labelOf(ring.row) : ""
            color: root.host ? root.host.foreground : "transparent"
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
            elide: Text.ElideRight
          }

          PlainText {
            id: verdict
            objectName: "ringVerdict"
            readonly property var answer: root.host ? root.host.verdictOf(ring.limit) : null
            x: label.x
            y: root.lineHeight + Style.spacing.xxs
            width: Math.max(0, parent.width - x)
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
            text: answer ? answer.text : ""
            color: !root.host ? "transparent" : answer && answer.urgent ? root.host.urgent : root.host.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          // The live rate; a used-up limit says so in its verdict already.
          RateChip {
            id: chip
            visible: !ring.limit.exhausted
            x: label.x
            y: verdict.y + verdict.height + Style.spacing.xxs
            model: ring.limit
            motion: root.motion
            foreground: root.host ? root.host.foreground : "transparent"
            accent: ring.tone
            urgent: root.host ? root.host.urgent : "transparent"
            fontFamily: root.fontFamily
          }
        }
      }
    }

    // The centre, over the innermost ring's hole.
    Column {
      objectName: "ringCentre"
      x: Math.round((root.ringSize - width) / 2)
      y: root.ringTop + Math.round((root.ringSize - height) / 2)
      spacing: 0

      PlainText {
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.centre.text
        color: !root.host ? "transparent" : root.centre.kind === "lasts" ? root.host.tone : root.host.urgent
        font.family: root.fontFamily
        font.pixelSize: root.centre.kind === "lasts" ? Style.font.heading : Style.font.body
        font.bold: true
      }

      PlainText {
        visible: text !== ""
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.centre.note
        color: root.host ? root.host.dim : "transparent"
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }

  // Row: the fill on a track tinted with its colour; while spending its head breathes on the beat.
  Item {
    id: rowBar
    objectName: "ringRow"
    visible: root.variant === "row" && !!root.model
    anchors.fill: parent

    readonly property real barHeight: Style.spaceReal(4)
    readonly property real barY: Math.round((height - barHeight) / 2)
    readonly property color tone: root.host ? root.host.tone : "transparent"
    readonly property bool moving: visible && !!root.model && root.model.moving
    readonly property bool running: moving && !!root.motion && !root.motion.reduced
    readonly property real beat: running ? root.beatOf(root.motion.liveSeconds, root.model.period) : 0
    property real edge: root.model ? root.model.fill : 0
    readonly property real fillWidth: edge > 0 ? Math.max(barHeight, width * Math.min(1, edge)) : 0

    LiveClaim {
      motion: root.motion
      active: rowBar.moving
    }

    Behavior on edge {
      NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
    }

    Rectangle {
      y: rowBar.barY
      width: parent.width
      height: rowBar.barHeight
      radius: height / 2
      color: root.alpha(rowBar.tone, root.lightTheme ? 0.2 : 0.16)
    }

    Rectangle {
      objectName: "ringRowFill"
      visible: rowBar.fillWidth > 0
      y: rowBar.barY
      width: rowBar.fillWidth
      height: rowBar.barHeight
      radius: height / 2
      color: rowBar.tone
    }

    Shape {
      id: rowHalo
      readonly property real reach: Style.spaceReal(9)
      visible: rowBar.running
      x: rowBar.fillWidth - rowBar.barHeight / 2 - reach
      y: rowBar.barY + rowBar.barHeight / 2 - reach
      width: reach * 2
      height: reach * 2
      scale: (Style.spaceReal(4) + Style.spaceReal(5) * rowBar.beat) / reach
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeWidth: -1
        strokeColor: "transparent"
        fillGradient: RadialGradient {
          centerX: rowHalo.reach
          centerY: rowHalo.reach
          centerRadius: rowHalo.reach
          focalX: rowHalo.reach
          focalY: rowHalo.reach
          GradientStop { position: 0; color: root.alpha(root.lift(rowBar.tone, 0.3), 0.75) }
          GradientStop { position: 1; color: root.alpha(root.lift(rowBar.tone, 0.3), 0) }
        }

        PathAngleArc {
          centerX: rowHalo.reach
          centerY: rowHalo.reach
          radiusX: rowHalo.reach
          radiusY: rowHalo.reach
          startAngle: 0
          sweepAngle: 360
        }
      }
    }

    Rectangle {
      objectName: "ringRowHead"
      readonly property real diameter: Style.spaceReal(3)
      visible: rowBar.running
      x: rowBar.fillWidth - rowBar.barHeight / 2 - diameter / 2
      y: rowBar.barY + rowBar.barHeight / 2 - diameter / 2
      width: diameter
      height: diameter
      radius: diameter / 2
      color: root.headColor
    }
  }
}
