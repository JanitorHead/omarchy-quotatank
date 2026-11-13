pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons

// Meter style "Gauges" (group): every limit of the account side by side as a dashboard dial. A 270° arc
// fills to the figure on the chosen side, deepening towards its start; dashes carry on to where this pace
// takes the limit by its reset, urgent when it runs out first. The figure, its unit and the rate sit
// inside the dial, the label, verdict and reset line under it. While the account spends, the head breathes
// on the beat and, on a beat about once a second, a comet leaves it along the dashes (backwards under
// Remaining, where the dashes lie on the fill); where the limit runs out, the comet's landing flashes, and
// each request rings from the head; all faster as the pace presses on the limit. Row: at about 60×6 px an
// arc is a flat smudge, so it is the gallery's bar: the same deepening fill and, while spending, the head
// and the comet. Card: nothing, limit cards hide under group styles. See MeterProjection.qml for the host
// contract.
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

  // Group: one dial per window, side by side, all one size so they read alike.
  readonly property var windows: variant === "group" && host && host.windows ? host.windows : []
  readonly property int count: windows.length
  readonly property real columnGap: Style.spaceReal(12)
  readonly property real columnWidth: count > 0 ? Math.max(0, (width - columnGap * (count - 1)) / count) : 0
  readonly property real arcWidth: Style.spaceReal(count > 2 ? 8 : 9)
  // Ticks every 10% outside the arc, longer at 0, 50 and 100%.
  readonly property real tickGap: Style.spaceReal(3)
  readonly property real tickReach: tickGap + Style.spaceReal(5)
  readonly property real dialRadius: Math.max(Style.spaceReal(24),
    Math.min(Style.spaceReal(54), columnWidth / 2 - arcWidth / 2 - tickReach - Style.spaceReal(2)))
  // From a dial's top (its longest tick) to its centre.
  readonly property real dialTop: dialRadius + arcWidth / 2 + tickReach
  readonly property int figureSize: dialRadius >= Style.spaceReal(46) ? Style.font.display : Style.font.heading
  // Inside the dial, below its centre: the figure, its unit, then the rate in the arc's opening.
  readonly property real figureCentre: Style.spaceReal(2)
  readonly property real unitCentre: figureCentre + figureSize * 0.5 + Style.font.caption * 0.75
  readonly property real rateCentre: unitCentre + Style.font.caption * 1.3
  readonly property real dialHeight: Math.ceil(dialTop + Math.max(dialTop * Math.SQRT1_2, rateCentre + captionMetrics.height / 2))

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function mix(a, b, k) { return Qt.rgba(a.r + (b.r - a.r) * k, a.g + (b.g - a.g) * k, a.b + (b.b - a.b) * k, 1) }
  // Towards white on a dark theme, towards black on a light one: a highlight that reads on either.
  function lift(color, k) { return lightTheme ? mix(color, Qt.rgba(0, 0, 0, 1), k * 0.45) : mix(color, Qt.rgba(1, 1, 1, 1), k) }
  // The fill's start, sunk towards the background.
  function deep(color) { return mix(color, Commons.Color.background, 0.45) }
  // Where a fraction lands on a dial, in degrees clockwise from three o'clock: 135° (lower left) over the
  // top to 405° (lower right).
  function angleOf(fraction) { return 135 + 270 * Math.max(0, Math.min(1, fraction)) }
  function beatOf(seconds, period) { return period > 0 ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((seconds / period) % 1)) : 0 }
  // Beats per comet: the next whole number that spaces launches about a second apart.
  function cometBeats(period) { return period > 0 ? Math.max(1, Math.ceil(1 / period)) : 1 }

  implicitHeight: variant === "row" ? Style.space(6) : variant === "group" ? dials.height : 0

  FontMetrics {
    id: captionMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Item {
    id: dials
    objectName: "gaugeDials"
    visible: root.variant === "group"
    width: parent.width
    height: childrenRect.height

    Repeater {
      model: root.count

      Item {
        id: column
        required property int index
        readonly property var row: root.windows[index] || null
        readonly property LimitModel limit: LimitModel {
          window: column.row
          nowSeconds: root.host ? root.host.nowSeconds : 0
          quotaMode: root.host ? root.host.quotaMode : "Used"
          spending: !!root.host && root.host.spending
          readingAt: root.host ? root.host.readingAt : 0
          requestAt: root.host ? root.host.requestAt : 0
          account: root.host ? root.host.account : null
        }
        readonly property color tone: root.host && row ? root.host.toneOf(row) : "transparent"
        readonly property color highlight: root.lift(tone, 0.45)
        readonly property bool remaining: limit.quotaMode === "Remaining"
        readonly property bool moving: limit.moving && dials.visible
        readonly property bool running: moving && !!root.motion && !root.motion.reduced
        readonly property real seconds: running ? root.motion.liveSeconds : 0
        readonly property real beat: running ? root.beatOf(seconds, limit.period) : 0
        property real edge: limit.fill
        // The solid arc: the fill under Used; under Remaining what this pace leaves by the reset, the rest
        // of the fill being the forecast (as the block meter draws it).
        readonly property real solid: limit.forecastShown ? Math.min(edge, limit.forecastFrom) : edge
        // The comet leaves the head as the beat peaks, on whole beats about a second apart at most (a hard
        // pace beats faster than that), runs for 70% of its cycle to where this pace takes the limit, easing
        // in to land, then fades there.
        readonly property var live: limit.live
        readonly property bool sweeping: running && live.start >= 0 && Math.abs(live.end - live.start) > 0.002
        readonly property real cometRun: 0.7
        readonly property real cometCycle: limit.period * root.cometBeats(limit.period)
        readonly property real cometPhase: sweeping ? ((seconds / limit.period - 0.5) / root.cometBeats(limit.period)) % 1 : 0
        readonly property real cometProgress: 1 - Math.pow(1 - Math.min(1, cometPhase / cometRun), 2)
        readonly property real cometFraction: sweeping ? live.start + (live.end - live.start) * cometProgress : 0
        readonly property real cometOpacity: cometPhase < 0.08 ? cometPhase / 0.08
          : cometPhase <= cometRun ? 1 : Math.max(0, 1 - (cometPhase - cometRun) / (1 - cometRun))
        // The pace runs the limit out before its reset: the end of the arc flashes as the comet lands.
        readonly property real landing: sweeping && live.runsOut && cometPhase > cometRun
          ? Math.exp(-(cometPhase - cometRun) * cometCycle / 0.25) : 0
        readonly property real requestAge: running && limit.requestAt > 0 ? seconds - limit.requestAt : -1

        objectName: "gaugeColumn-" + index
        x: index * (root.columnWidth + root.columnGap)
        width: root.columnWidth
        height: captions.y + captions.height

        LiveClaim {
          motion: root.motion
          active: column.moving
        }

        Behavior on edge {
          NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
        }

        Item {
          id: dial
          objectName: "gaugeDial"
          width: parent.width
          height: root.dialHeight

          readonly property real cx: width / 2
          readonly property real cy: root.dialTop
          readonly property real outer: root.dialRadius + root.arcWidth / 2
          readonly property real inner: root.dialRadius - root.arcWidth / 2
          readonly property point head: pointAt(column.edge, root.dialRadius)
          readonly property var tickLines: {
            var lines = []
            var from = outer + root.tickGap
            for (var step = 0; step <= 10; step++) {
              var to = step % 5 === 0 ? outer + root.tickReach : from + Style.spaceReal(2)
              lines.push([pointAt(step / 10, from), pointAt(step / 10, to)])
            }
            return lines
          }

          function pointAt(fraction, radius) {
            var angle = root.angleOf(fraction) * Math.PI / 180
            return Qt.point(cx + radius * Math.cos(angle), cy + radius * Math.sin(angle))
          }

          // Ticks, track, a faint glow under the fill and, under Remaining, the stretch of the fill this
          // pace spends, kept faintly lit under its dashes.
          Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
              strokeColor: root.host ? root.alpha(root.host.foreground, 0.25) : "transparent"
              strokeWidth: Style.spacing.hairline
              fillColor: "transparent"
              capStyle: ShapePath.FlatCap

              PathMultiline { paths: dial.tickLines }
            }

            ShapePath {
              strokeColor: root.host ? root.alpha(root.host.foreground, root.lightTheme ? 0.1 : 0.08) : "transparent"
              strokeWidth: root.arcWidth
              fillColor: "transparent"
              capStyle: ShapePath.RoundCap

              PathAngleArc {
                centerX: dial.cx
                centerY: dial.cy
                radiusX: root.dialRadius
                radiusY: root.dialRadius
                startAngle: 135
                sweepAngle: 270
              }
            }

            ShapePath {
              strokeColor: column.solid > 0 ? root.alpha(column.tone, 0.12) : "transparent"
              strokeWidth: root.arcWidth + Style.spaceReal(6)
              fillColor: "transparent"
              capStyle: ShapePath.RoundCap

              PathAngleArc {
                centerX: dial.cx
                centerY: dial.cy
                radiusX: root.dialRadius
                radiusY: root.dialRadius
                startAngle: 135
                sweepAngle: 270 * column.solid
              }
            }

            ShapePath {
              strokeColor: column.remaining && column.edge > column.solid ? root.alpha(column.tone, 0.3) : "transparent"
              strokeWidth: root.arcWidth
              fillColor: "transparent"
              capStyle: ShapePath.FlatCap

              PathAngleArc {
                centerX: dial.cx
                centerY: dial.cy
                radiusX: root.dialRadius
                radiusY: root.dialRadius
                startAngle: root.angleOf(column.solid)
                sweepAngle: 270 * Math.max(0, column.edge - column.solid)
              }
            }
          }

          // The fill, an arc-shaped area with round ends so its gradient can follow the dial: deep at 0%,
          // lifted at 100% (a conical gradient runs anticlockwise, here from the dial's end back to its start).
          Shape {
            objectName: "gaugeFill"
            visible: column.solid > 0
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
              id: fillPath
              readonly property real end: root.angleOf(column.solid)
              readonly property real endRadians: end * Math.PI / 180
              strokeWidth: -1
              strokeColor: "transparent"
              fillRule: ShapePath.WindingFill
              fillGradient: ConicalGradient {
                centerX: dial.cx
                centerY: dial.cy
                angle: -45
                GradientStop { position: 0; color: root.lift(column.tone, 0.15) }
                GradientStop { position: 0.75; color: root.deep(column.tone) }
                GradientStop { position: 1; color: root.lift(column.tone, 0.15) }
              }
              startX: dial.cx - dial.outer * Math.SQRT1_2
              startY: dial.cy + dial.outer * Math.SQRT1_2

              PathAngleArc {
                centerX: dial.cx
                centerY: dial.cy
                radiusX: dial.outer
                radiusY: dial.outer
                startAngle: 135
                sweepAngle: fillPath.end - 135
                moveToStart: false
              }
              PathArc {
                x: dial.cx + dial.inner * Math.cos(fillPath.endRadians)
                y: dial.cy + dial.inner * Math.sin(fillPath.endRadians)
                radiusX: root.arcWidth / 2
                radiusY: root.arcWidth / 2
              }
              PathAngleArc {
                centerX: dial.cx
                centerY: dial.cy
                radiusX: dial.inner
                radiusY: dial.inner
                startAngle: fillPath.end
                sweepAngle: 135 - fillPath.end
                moveToStart: false
              }
              PathArc {
                x: fillPath.startX
                y: fillPath.startY
                radiusX: root.arcWidth / 2
                radiusY: root.arcWidth / 2
              }
            }
          }

          // The forecast: dashes from the fill's edge to where this pace takes the limit by its reset.
          Shape {
            objectName: "gaugeForecast"
            visible: column.limit.forecastShown
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
              id: dashPath
              strokeColor: !root.host ? "transparent"
                : column.limit.runsOut ? root.alpha(root.host.urgent, 0.9) : root.alpha(root.host.foreground, 0.4)
              strokeWidth: root.arcWidth / 2
              strokeStyle: ShapePath.DashLine
              dashPattern: [Style.spaceReal(3) / dashPath.strokeWidth, Style.spaceReal(4) / dashPath.strokeWidth]
              fillColor: "transparent"
              capStyle: ShapePath.FlatCap

              PathAngleArc {
                centerX: dial.cx
                centerY: dial.cy
                radiusX: root.dialRadius
                radiusY: root.dialRadius
                startAngle: root.angleOf(column.limit.forecastFrom)
                sweepAngle: 270 * Math.max(0, column.limit.forecastTo - column.limit.forecastFrom)
              }
            }
          }

          // Spending: a soft light at the head, swelling on the beat.
          Shape {
            id: halo
            objectName: "gaugeHalo"
            readonly property real reach: Style.spaceReal(18)
            visible: column.running
            x: dial.head.x - reach
            y: dial.head.y - reach
            width: reach * 2
            height: reach * 2
            scale: (Style.spaceReal(11) + Style.spaceReal(7) * column.beat) / reach
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
                GradientStop { position: 0; color: root.alpha(root.lift(column.tone, 0.3), 0.7) }
                GradientStop { position: 1; color: root.alpha(root.lift(column.tone, 0.3), 0) }
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

          // The comet: a bright head with a fading tail, drawn once at three o'clock and turned into place,
          // so only its rotation changes from frame to frame.
          Item {
            id: comet
            objectName: "gaugeComet"
            readonly property real size: 2 * (root.dialRadius + root.arcWidth)
            readonly property real centre: size / 2
            readonly property real tail: 24
            visible: column.sweeping
            x: dial.cx - centre
            y: dial.cy - centre
            width: size
            height: size
            rotation: root.angleOf(column.cometFraction)
            opacity: column.cometOpacity

            Item {
              anchors.fill: parent
              // Drawn heading clockwise; mirrored to head anticlockwise under Remaining.
              transform: Scale {
                origin.x: comet.centre
                origin.y: comet.centre
                yScale: column.remaining ? -1 : 1
              }

              Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer

                ShapePath {
                  id: tailPath
                  readonly property real outer: root.dialRadius + root.arcWidth / 4
                  readonly property real inner: root.dialRadius - root.arcWidth / 4
                  readonly property real tailRadians: comet.tail * Math.PI / 180
                  strokeWidth: -1
                  strokeColor: "transparent"
                  fillGradient: ConicalGradient {
                    centerX: comet.centre
                    centerY: comet.centre
                    angle: 0
                    GradientStop { position: 0; color: root.alpha(column.highlight, 0.9) }
                    GradientStop { position: comet.tail / 360; color: root.alpha(column.highlight, 0) }
                    GradientStop { position: 1; color: root.alpha(column.highlight, 0.9) }
                  }
                  startX: comet.centre + tailPath.outer
                  startY: comet.centre

                  PathAngleArc {
                    centerX: comet.centre
                    centerY: comet.centre
                    radiusX: tailPath.outer
                    radiusY: tailPath.outer
                    startAngle: 0
                    sweepAngle: -comet.tail
                    moveToStart: false
                  }
                  PathLine {
                    x: comet.centre + tailPath.inner * Math.cos(tailPath.tailRadians)
                    y: comet.centre - tailPath.inner * Math.sin(tailPath.tailRadians)
                  }
                  PathAngleArc {
                    centerX: comet.centre
                    centerY: comet.centre
                    radiusX: tailPath.inner
                    radiusY: tailPath.inner
                    startAngle: -comet.tail
                    sweepAngle: comet.tail
                    moveToStart: false
                  }
                  PathLine {
                    x: tailPath.startX
                    y: tailPath.startY
                  }
                }
              }

              Rectangle {
                readonly property real diameter: root.arcWidth * 0.75
                x: comet.centre + root.dialRadius - diameter / 2
                y: comet.centre - diameter / 2
                width: diameter
                height: diameter
                radius: diameter / 2
                color: column.highlight
              }
            }
          }

          Rectangle {
            objectName: "gaugeLanding"
            readonly property real diameter: root.arcWidth * 1.8
            readonly property point at: dial.pointAt(column.live.end, root.dialRadius)
            visible: column.landing > 0.01
            x: at.x - diameter / 2
            y: at.y - diameter / 2
            width: diameter
            height: diameter
            radius: diameter / 2
            color: root.host ? root.host.urgent : "transparent"
            opacity: column.landing
          }

          // A request: a ring spreads from the head.
          Rectangle {
            objectName: "gaugeRipple"
            readonly property real progress: column.requestAge >= 0 && column.requestAge < 0.7 ? column.requestAge / 0.7 : -1
            readonly property real reach: root.arcWidth * (0.45 + 1.8 * Math.max(0, progress))
            visible: progress >= 0
            x: dial.head.x - reach
            y: dial.head.y - reach
            width: reach * 2
            height: reach * 2
            radius: reach
            color: "transparent"
            border.width: Style.spacing.hairline
            border.color: root.alpha(root.lift(column.tone, 0.3), 0.8 * (1 - Math.max(0, progress)))
          }

          Rectangle {
            objectName: "gaugeHead"
            readonly property real diameter: root.arcWidth * 0.72
            visible: column.limit.hasMeter
            x: dial.head.x - diameter / 2
            y: dial.head.y - diameter / 2
            width: diameter
            height: diameter
            radius: diameter / 2
            color: root.headColor
          }

          // Pace tick: a needle across the arc where even use would be by now.
          Rectangle {
            id: paceNeedle
            objectName: "gaugePace"
            readonly property real from: dial.inner - Style.spaceReal(5)
            visible: !!root.host && root.host.markShown && column.limit.markValue >= 0
            x: dial.cx + from
            y: dial.cy - height / 2
            width: dial.outer + Style.spaceReal(2) - from
            height: Style.spaceReal(2)
            antialiasing: true
            color: root.host ? root.alpha(root.host.foreground, 0.95) : "transparent"
            transform: Rotation {
              origin.x: -paceNeedle.from
              origin.y: paceNeedle.height / 2
              angle: root.angleOf(column.limit.markValue)
            }
          }

          PlainText {
            objectName: "gaugeFigure"
            x: dial.cx - width / 2
            y: dial.cy + root.figureCentre - height / 2
            width: Math.max(0, 2 * dial.inner - Style.spaceReal(6))
            horizontalAlignment: Text.AlignHCenter
            fontSizeMode: Text.HorizontalFit
            minimumPixelSize: Style.font.caption
            text: root.host ? root.host.figureText(column.limit) : ""
            color: !root.host ? "transparent" : column.row && root.host.stressed(column.row) ? root.host.urgent : root.host.foreground
            font.family: root.fontFamily
            font.pixelSize: root.figureSize
            font.bold: true
          }

          PlainText {
            visible: column.limit.known
            x: dial.cx - width / 2
            y: dial.cy + root.unitCentre - height / 2
            text: root.host ? root.host.unitText() : ""
            color: root.host ? root.host.dim : "transparent"
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          // The rate: "+24%/h" while spending ("−" under Remaining), else idle or quiet; nothing used up.
          PlainText {
            objectName: "gaugeRate"
            readonly property bool rising: column.limit.moving && column.limit.ratePerHour > 0
            x: dial.cx - width / 2
            y: dial.cy + root.rateCentre - height / 2
            text: column.limit.exhausted ? "" : (rising ? (column.remaining ? "−" : "+") : "") + column.limit.rateText
            color: !root.host ? "transparent" : !rising ? root.host.dim
              : column.limit.runsOut ? root.host.urgent : root.lift(column.tone, 0.2)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: rising
          }
        }

        Column {
          id: captions
          y: dial.height + Style.spacing.xs
          width: parent.width
          spacing: Style.spacing.xxs

          PlainText {
            objectName: "gaugeLabel"
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: root.host && column.row ? root.host.labelOf(column.row) : ""
            color: root.host ? root.host.foreground : "transparent"
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
            // Three dials leave a column too narrow for "Opus weekly limit" on one line.
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
          }

          PlainText {
            objectName: "gaugeVerdict"
            readonly property var verdict: root.host ? root.host.verdictOf(column.limit) : null
            visible: text !== ""
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
            text: verdict ? verdict.text : ""
            color: !root.host ? "transparent" : verdict && verdict.urgent ? root.host.urgent : root.host.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          PlainText {
            objectName: "gaugeReset"
            visible: text !== ""
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
            text: root.host && column.row ? root.host.resetLabelOf(column.row) : ""
            color: root.host ? root.host.dim : "transparent"
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }

  // Row: a rounded bar, deepening towards its start like the dial's arc. While spending, the head glows on
  // the beat and a comet runs from it to where this pace takes the limit (leftward under Remaining).
  Item {
    id: rowBar
    objectName: "gaugeRow"
    visible: root.variant === "row" && !!root.model
    anchors.fill: parent

    readonly property real barHeight: Style.spaceReal(4)
    readonly property real barY: Math.round((height - barHeight) / 2)
    readonly property color tone: root.host ? root.host.tone : "transparent"
    readonly property color highlight: root.lift(tone, 0.45)
    readonly property var live: root.model ? root.model.live : null
    readonly property bool moving: visible && !!root.model && root.model.moving
    readonly property bool running: moving && !!root.motion && !root.motion.reduced
    readonly property real seconds: running ? root.motion.liveSeconds : 0
    readonly property real beat: running ? root.beatOf(seconds, root.model.period) : 0
    property real edge: root.model ? root.model.fill : 0
    readonly property real fillWidth: edge > 0 ? Math.max(barHeight, width * Math.min(1, edge)) : 0
    // The comet's run, timed as the dial's.
    readonly property bool sweeping: running && !!live && live.start >= 0 && Math.abs(live.end - live.start) > 0.002
    readonly property bool leftward: !!live && live.end < live.start
    readonly property real cycle: sweeping ? root.model.period * root.cometBeats(root.model.period) : 1
    readonly property real phase: sweeping ? ((seconds / root.model.period - 0.5) / root.cometBeats(root.model.period)) % 1 : 0
    readonly property real progress: 1 - Math.pow(1 - Math.min(1, phase / 0.7), 2)
    readonly property real runFrom: sweeping ? width * live.start : 0
    readonly property real runTo: sweeping ? width * live.end : 0
    readonly property real runHead: runFrom + (runTo - runFrom) * progress
    readonly property real runOpacity: phase < 0.08 ? phase / 0.08 : phase <= 0.7 ? 1 : Math.max(0, 1 - (phase - 0.7) / 0.3)
    readonly property real landing: sweeping && live.runsOut && phase > 0.7 ? Math.exp(-(phase - 0.7) * cycle / 0.25) : 0

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
      color: root.host ? root.alpha(root.host.foreground, 0.12) : "transparent"
    }

    // The gradient spans the whole bar: the fill's end takes the colour of where it stands.
    Rectangle {
      objectName: "gaugeRowFill"
      visible: rowBar.fillWidth > 0
      y: rowBar.barY
      width: rowBar.fillWidth
      height: rowBar.barHeight
      radius: height / 2
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: root.deep(rowBar.tone) }
        GradientStop { position: 1; color: root.mix(root.deep(rowBar.tone), root.lift(rowBar.tone, 0.15), Math.min(1, rowBar.edge)) }
      }
    }

    Rectangle {
      readonly property real length: Math.min(Style.spaceReal(12), Math.abs(rowBar.runHead - rowBar.runFrom))
      visible: rowBar.sweeping
      x: rowBar.leftward ? rowBar.runHead : rowBar.runHead - length
      y: rowBar.barY
      width: length
      height: rowBar.barHeight
      opacity: rowBar.runOpacity
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: root.alpha(rowBar.highlight, rowBar.leftward ? 0.85 : 0) }
        GradientStop { position: 1; color: root.alpha(rowBar.highlight, rowBar.leftward ? 0 : 0.85) }
      }
    }

    Rectangle {
      objectName: "gaugeRowRun"
      visible: rowBar.sweeping
      x: Math.round(rowBar.runHead - width / 2)
      y: rowBar.barY - Style.spaceReal(1)
      width: Style.spaceReal(2)
      height: rowBar.barHeight + Style.spaceReal(2)
      radius: width / 2
      color: rowBar.highlight
      opacity: rowBar.runOpacity
    }

    Rectangle {
      readonly property real diameter: rowBar.barHeight + Style.spaceReal(2)
      visible: rowBar.landing > 0.01
      x: (rowBar.leftward ? 0 : rowBar.width) - diameter / 2
      y: rowBar.barY + rowBar.barHeight / 2 - diameter / 2
      width: diameter
      height: diameter
      radius: diameter / 2
      color: root.host ? root.host.urgent : "transparent"
      opacity: rowBar.landing
    }

    Shape {
      id: rowHalo
      readonly property real reach: Style.spaceReal(9)
      visible: rowBar.running
      x: rowBar.fillWidth - rowBar.barHeight / 2 - reach
      y: rowBar.barY + rowBar.barHeight / 2 - reach
      width: reach * 2
      height: reach * 2
      scale: (Style.spaceReal(5) + Style.spaceReal(4) * rowBar.beat) / reach
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
      objectName: "gaugeRowHead"
      readonly property real diameter: rowBar.barHeight
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
