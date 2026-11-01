pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons
import "UsageLogic.js" as UsageLogic

// Meter style "Burn chart". Card: the window as a chart, time from its start to the reset left to right,
// use (or, under Remaining, what is left) bottom to top. The area is the history up to now, a dashed line
// runs on at this pace to the reset (red, ending in a dot and the time, when it reaches the limit first),
// a dashed ceiling marks 100 % and with the pace tick a dotted diagonal shows even use. While the account
// spends, the "now" point breathes on the beat, rings on each request and a bright head runs along the
// forecast. Row: the same history as a thin line ending in a dot that breathes while spending.
//
// The charts are Shapes that rebuild only when the samples, the size, the side or the "now" pixel change;
// everything that moves is a plain Item over them, driven by the shared clock.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  // The pace tick on the chosen side (0-1), drawn only while the host asks for it.
  readonly property real markValue: model ? model.markValue : -1
  readonly property bool markShown: !!host && host.markShown && markValue >= 0
  readonly property bool remaining: !!model && model.quotaMode === "Remaining"

  // Time axis: the window from its start to the reset. Without a known span the history cannot be placed
  // in time; the line then spans the whole width up to the current use and draws no forecast.
  readonly property real windowSeconds: model ? model.windowSeconds : 0
  readonly property real windowStart: model && model.windowSeconds > 0 && model.resetsAt > 0 ? model.resetsAt - model.windowSeconds : 0
  readonly property bool timed: windowStart > 0
  readonly property real nowShare: !model ? 0 : timed ? clamp01((model.nowSeconds - windowStart) / windowSeconds) : 1
  readonly property real used: model ? Math.max(0, Math.min(100, model.used)) : 0

  // Where this pace takes the limit: the reset at the projected use, or the moment it reaches 100.
  readonly property var forecastEnd: {
    var forecast = model ? model.forecast : null
    if (!timed || !forecast || !(forecast.rate > 0) || forecast.projected === null || forecast.pace.exhausted) return null
    var runsOut = forecast.runsOut && forecast.runsOutAt !== null
    var at = runsOut ? forecast.runsOutAt : forecast.resetsAt
    return { share: clamp01((at - windowStart) / windowSeconds), used: runsOut ? 100 : forecast.projected, runsOut: runsOut, at: at }
  }

  // Motion only while the account spends, on the shared clock.
  readonly property bool running: visible && !!model && model.moving
    && !!host && !!host.motion && !host.motion.reduced
  readonly property real liveSeconds: running ? host.motion.liveSeconds : 0
  readonly property real period: model && model.period > 0 ? model.period : 3.2
  readonly property real phase: running ? (liveSeconds / period) % 1 : 0
  readonly property real beat: running ? 0.5 - 0.5 * Math.cos(2 * Math.PI * phase) : 0
  // Fades from 1 to 0 over 0.8 s after each omp request (the request ring).
  readonly property real requestAge: running && model.requestAt > 0 ? liveSeconds - model.requestAt : -1
  readonly property real ring: requestAge >= 0 && requestAge < 0.8 ? requestAge / 0.8 : -1

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function clamp01(value) { return Math.max(0, Math.min(1, value)) }
  function sideOf(usedValue) { return remaining ? 100 - usedValue : usedValue }

  // The window's use as [[share of the window, used %], …] from its start (at 0, the reset) to now,
  // at most one point per pixel column. Too few readings leave a straight line from the start to now.
  function usePoints(nowAt, columns) {
    var result = [[0, 0]]
    var list = model && model.samples ? model.samples : []
    if (timed) {
      for (var i = 0; i < list.length; i++) {
        var sample = list[i]
        var stamp = Number(sample[0])
        var value = Number(sample[1])
        if (!isFinite(stamp) || !isFinite(value) || stamp < windowStart) continue
        var share = Math.min(nowAt, (stamp - windowStart) / windowSeconds)
        var point = [share, Math.max(0, Math.min(100, value))]
        // Readings in the same pixel column collapse into the newest; the start point stays.
        if (result.length > 1 && (share - result[result.length - 1][0]) * columns < 0.75) result[result.length - 1] = point
        else result.push(point)
      }
    }
    result.push([nowAt, used])
    return result
  }

  function chartPath(points, left, top, plotWidth, plotHeight) {
    var path = []
    for (var i = 0; i < points.length; i++)
      path.push(Qt.point(left + plotWidth * points[i][0], top + plotHeight * (1 - sideOf(points[i][1]) / 100)))
    return path
  }

  // The card's hover readout (LimitCard asks the meter, since x here is time, not a share of the limit).
  // `fraction` is the pointer's x over the meter's width. Before now: the use the samples had then; at now:
  // the reading; after: where this pace takes it, or when it runs out once the pointer passes that moment.
  function scrubTextAt(fraction) {
    if (variant !== "card" || !model || !host || typeof host.clock !== "function") return ""
    var unit = remaining ? "% left" : "% used"
    var nowText = "now " + host.clock(model.nowSeconds) + " · " + UsageLogic.formatPercent(sideOf(used)) + unit
    if (!timed) return nowText
    var x = Number(fraction) * width
    if (Math.abs(x - card.nowX) <= Style.space(4)) return nowText
    var share = clamp01((x - card.plotLeft) / card.plotWidth)
    var at = windowStart + share * windowSeconds
    if (share < nowShare) {
      // Every reading counts here, not one per pixel column as drawn.
      var points = usePoints(nowShare, 1e9)
      var value = used
      for (var i = 1; i < points.length; i++) {
        if (points[i][0] < share) continue
        var a = points[i - 1]
        var b = points[i]
        value = b[0] > a[0] ? a[1] + (b[1] - a[1]) * (share - a[0]) / (b[0] - a[0]) : b[1]
        break
      }
      return host.clock(at) + " · " + UsageLogic.formatPercent(sideOf(value)) + unit
    }
    if (model.exhausted) return host.clock(at) + " · used up"
    var forecast = model.forecast
    if (!forecastEnd || !forecast) return host.clock(at) + " · no forecast"
    if (forecastEnd.runsOut && at >= forecastEnd.at) return "runs out " + host.clock(forecastEnd.at)
    var ahead = Math.min(100, forecast.used + forecast.rate * Math.max(0, at - model.nowSeconds))
    return host.clock(at) + " · " + UsageLogic.formatPercent(sideOf(ahead)) + (remaining ? "% left" : "%") + " at this pace"
  }

  implicitHeight: variant === "row" ? Style.space(10) : Style.space(60)

  LiveClaim {
    motion: root.host ? root.host.motion : null
    active: root.visible && !!root.model && root.model.moving
  }

  Item {
    id: card
    objectName: "burnChart"
    visible: root.variant === "card" && !!root.model && root.model.hasMeter
    anchors.fill: parent

    readonly property real plotLeft: 1
    readonly property real plotWidth: Math.max(1, width - 2)
    readonly property real plotTop: Style.space(12)
    readonly property real plotBottom: height - Style.space(4)
    readonly property real plotHeight: Math.max(1, plotBottom - plotTop)
    // Rounded to the pixel so the chart rebuilds when "now" moves a pixel, not on every clock second.
    readonly property int nowPx: Math.round(root.nowShare * plotWidth)
    readonly property var path: visible ? root.chartPath(root.usePoints(nowPx / plotWidth, plotWidth), plotLeft, plotTop, plotWidth, plotHeight) : []
    readonly property real nowX: plotLeft + nowPx
    readonly property real nowY: plotTop + plotHeight * (1 - root.sideOf(root.used) / 100)
    readonly property real limitY: plotTop + plotHeight * (1 - root.sideOf(100) / 100)
    readonly property real endX: root.forecastEnd ? Math.round(plotLeft + plotWidth * root.forecastEnd.share) : nowX
    readonly property real endY: root.forecastEnd ? Math.round(plotTop + plotHeight * (1 - root.sideOf(root.forecastEnd.used) / 100)) : nowY
    readonly property color forecastColor: !root.host ? "transparent"
      : root.forecastEnd && root.forecastEnd.runsOut ? root.alpha(root.host.urgent, 0.95) : root.alpha(root.host.foreground, 0.55)
    readonly property real lineWidth: Math.max(1, Style.spaceReal(1.6))
    readonly property int labelSize: Math.max(8, Math.round(Style.font.caption * 0.85))

    // The scale: a dashed ceiling at 100 %, a dashed right edge at the reset and the floor.
    Shape {
      anchors.fill: parent
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeColor: root.host ? root.alpha(root.host.foreground, 0.22) : "transparent"
        strokeWidth: Style.spacing.hairline
        strokeStyle: ShapePath.DashLine
        dashPattern: [2, 3]
        fillColor: "transparent"
        startX: 0; startY: Math.round(card.plotTop) + 0.5
        PathLine { x: card.width; y: Math.round(card.plotTop) + 0.5 }
        PathMove { x: card.width - 0.5; y: card.plotTop }
        PathLine { x: card.width - 0.5; y: card.plotBottom }
      }
    }

    Rectangle {
      y: Math.round(card.plotBottom)
      width: card.width
      height: Style.spacing.hairline
      color: root.host ? root.alpha(root.host.foreground, 0.14) : "transparent"
    }

    // Under the ceiling, as in the gallery; under Remaining the line starts there, so it sits above.
    PlainText {
      x: Style.space(3)
      y: root.remaining ? Math.round(card.plotTop / 2 - implicitHeight / 2) : Math.round(card.plotTop) + Style.space(2)
      text: "100%"
      color: root.host ? root.host.dim : "transparent"
      font.family: root.host ? root.host.fontFamily : Style.font.family
      font.pixelSize: card.labelSize
    }

    // Even use (the pace tick asked for): a dotted diagonal from the start to the limit at the reset,
    // crossing "now" at the tick.
    Shape {
      objectName: "burnPace"
      visible: root.markShown && root.timed
      anchors.fill: parent
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeColor: root.host ? root.alpha(root.host.foreground, 0.35) : "transparent"
        strokeWidth: Style.spacing.hairline
        strokeStyle: ShapePath.DashLine
        dashPattern: [1, 3]
        fillColor: "transparent"
        startX: card.plotLeft; startY: card.plotTop + card.plotHeight * (1 - root.sideOf(0) / 100)
        PathLine { x: card.plotLeft + card.plotWidth; y: card.limitY }
      }
    }

    // The history: a soft area under a bright line.
    Shape {
      objectName: "burnHistory"
      anchors.fill: parent
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeColor: "transparent"
        fillGradient: LinearGradient {
          x1: 0; y1: card.plotTop
          x2: 0; y2: card.plotBottom
          GradientStop { position: 0; color: root.host ? root.alpha(root.host.tone, 0.34) : "transparent" }
          GradientStop { position: 1; color: root.host ? root.alpha(root.host.tone, 0.02) : "transparent" }
        }
        PathPolyline {
          path: card.path.length < 2 ? [] : [Qt.point(card.path[0].x, card.plotBottom)].concat(card.path, [Qt.point(card.nowX, card.plotBottom)])
        }
      }

      ShapePath {
        strokeColor: root.host ? root.host.tone : "transparent"
        strokeWidth: card.lineWidth
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        joinStyle: ShapePath.RoundJoin
        PathPolyline { path: card.path }
      }
    }

    // Now: a faint vertical line through the chart.
    Rectangle {
      x: Math.round(card.nowX - width / 2)
      y: card.plotTop
      width: Style.spacing.hairline
      height: card.plotHeight
      color: root.host ? root.alpha(root.host.foreground, 0.12) : "transparent"
    }

    Shape {
      objectName: "burnForecast"
      visible: !!root.forecastEnd
      anchors.fill: parent
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeColor: card.forecastColor
        strokeWidth: Math.max(1, Style.spaceReal(1.4))
        strokeStyle: ShapePath.DashLine
        dashPattern: [3, 2]
        fillColor: "transparent"
        startX: card.nowX; startY: card.nowY
        PathLine { x: card.endX; y: card.endY }
      }
    }

    // Where the limit runs out: a red dot on the limit with its time beside it.
    Rectangle {
      objectName: "burnRunsOut"
      visible: !!root.forecastEnd && root.forecastEnd.runsOut
      readonly property real size: Style.space(6)
      x: card.endX - size / 2
      y: card.endY - size / 2
      width: size
      height: size
      radius: size / 2
      color: root.host ? root.host.urgent : "transparent"

      Rectangle {
        anchors.centerIn: parent
        width: parent.size * 2.2
        height: width
        radius: width / 2
        color: root.host ? root.alpha(root.host.urgent, 0.18) : "transparent"
      }
    }

    PlainText {
      objectName: "burnForecastLabel"
      readonly property bool runsOut: !!root.forecastEnd && root.forecastEnd.runsOut
      readonly property bool leftOfPoint: runsOut && card.endX + Style.space(6) + implicitWidth > card.width
      visible: !!root.forecastEnd
      x: !runsOut ? card.width - Style.space(4) - implicitWidth
        : leftOfPoint ? card.endX - Style.space(6) - implicitWidth : card.endX + Style.space(6)
      y: Math.round((runsOut ? card.limitY + (root.remaining ? -Style.space(9) : Style.space(9)) : card.endY - Style.space(7)) - implicitHeight / 2)
      text: !root.forecastEnd ? ""
        : runsOut ? (root.host && typeof root.host.clock === "function" ? root.host.clock(root.forecastEnd.at) : "")
        : Math.round(root.sideOf(root.forecastEnd.used)) + "%"
      color: !root.host ? "transparent" : runsOut ? root.host.urgent : root.host.dim
      font.family: root.host ? root.host.fontFamily : Style.font.family
      font.pixelSize: card.labelSize
      font.bold: runsOut
    }

    // The pace tick: where even use would be by now, on the now line.
    Rectangle {
      objectName: "burnPaceTick"
      visible: root.markShown
      x: Math.round(card.nowX - width / 2)
      y: Math.round(card.plotTop + card.plotHeight * (1 - root.markValue) - height / 2)
      width: Style.space(7)
      height: Style.space(2)
      color: root.host ? root.alpha(root.host.foreground, 0.85) : "transparent"
    }

    // The moving head: a bright point running along the forecast once per beat, fading as it arrives.
    Repeater {
      model: card.visible && root.running && root.forecastEnd ? 3 : 0

      Rectangle {
        required property int index
        readonly property real at: Math.max(0, root.phase - index * 0.045)
        readonly property real size: Style.space(5) - index
        objectName: index === 0 ? "burnHead" : ""
        x: card.nowX + (card.endX - card.nowX) * at - size / 2
        y: card.nowY + (card.endY - card.nowY) * at - size / 2
        width: size
        height: size
        radius: size / 2
        color: !root.host ? "transparent" : root.forecastEnd && root.forecastEnd.runsOut ? root.host.urgent : Qt.lighter(root.host.tone, 1.4)
        opacity: (index === 0 ? 1 : index === 1 ? 0.5 : 0.25) * (root.phase < 0.8 ? 1 : (1 - root.phase) / 0.2)
      }
    }

    // Now: the point breathes on the beat and rings on each request while the account spends.
    Rectangle {
      objectName: "burnNowHalo"
      visible: root.running
      readonly property real size: 2 * (Style.space(6) + Style.space(5) * root.beat)
      x: card.nowX - size / 2
      y: card.nowY - size / 2
      width: size
      height: size
      radius: size / 2
      color: root.host ? root.alpha(Qt.lighter(root.host.tone, 1.3), 0.14) : "transparent"

      Rectangle {
        anchors.centerIn: parent
        width: parent.size * 0.55
        height: width
        radius: width / 2
        color: root.host ? root.alpha(Qt.lighter(root.host.tone, 1.3), 0.3) : "transparent"
      }
    }

    Rectangle {
      objectName: "burnRequestRing"
      visible: root.ring >= 0
      readonly property real size: 2 * (Style.space(4) + Style.space(12) * Math.max(0, root.ring))
      x: card.nowX - size / 2
      y: card.nowY - size / 2
      width: size
      height: size
      radius: size / 2
      color: "transparent"
      border.width: Math.max(1, Style.spaceReal(1.2))
      border.color: root.host ? root.alpha(Qt.lighter(root.host.tone, 1.3), 0.8 * (1 - Math.max(0, root.ring))) : "transparent"
    }

    Rectangle {
      objectName: "burnNow"
      readonly property real size: Style.space(6)
      x: card.nowX - size / 2
      y: card.nowY - size / 2
      width: size
      height: size
      radius: size / 2
      color: !root.host ? "transparent" : root.running ? Qt.lighter(root.host.tone, 1.6) : Qt.lighter(root.host.tone, 1.2)
    }
  }

  // Row: the history as a thin line over a faint floor, the forecast as a fainter line, and the "now"
  // dot, which breathes while the account spends.
  Item {
    id: row
    objectName: "burnRow"
    visible: root.variant === "row" && !!root.model
    anchors.fill: parent

    readonly property real plotTop: Style.space(1)
    readonly property real plotBottom: height - Style.space(2)
    readonly property real plotHeight: Math.max(1, plotBottom - plotTop)
    readonly property real plotWidth: Math.max(1, width)
    readonly property int nowPx: Math.round(root.nowShare * plotWidth)
    readonly property var path: visible ? root.chartPath(root.usePoints(nowPx / plotWidth, plotWidth), 0, plotTop, plotWidth, plotHeight) : []
    readonly property real nowX: nowPx
    readonly property real nowY: plotTop + plotHeight * (1 - root.sideOf(root.used) / 100)

    Rectangle {
      y: Math.round(row.plotBottom)
      width: row.width
      height: Style.spacing.hairline
      color: root.host ? root.alpha(root.host.foreground, 0.12) : "transparent"
    }

    Shape {
      anchors.fill: parent
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeColor: !root.host || !root.forecastEnd ? "transparent"
          : root.forecastEnd.runsOut ? root.alpha(root.host.urgent, 0.85) : root.alpha(root.host.foreground, 0.3)
        strokeWidth: Style.spacing.hairline
        fillColor: "transparent"
        startX: row.nowX; startY: row.nowY
        PathLine {
          x: root.forecastEnd ? Math.round(row.plotWidth * root.forecastEnd.share) : row.nowX
          y: root.forecastEnd ? Math.round(row.plotTop + row.plotHeight * (1 - root.sideOf(root.forecastEnd.used) / 100)) : row.nowY
        }
      }

      ShapePath {
        strokeColor: root.host ? root.host.tone : "transparent"
        strokeWidth: Math.max(1, Style.spaceReal(1.2))
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        joinStyle: ShapePath.RoundJoin
        PathPolyline { path: row.path }
      }
    }

    Rectangle {
      objectName: "burnRowGlow"
      visible: root.running
      readonly property real size: Style.space(4) + Style.space(6) * root.beat
      x: row.nowX - size / 2
      y: row.nowY - size / 2
      width: size
      height: size
      radius: size / 2
      color: root.host ? root.alpha(root.host.tone, 0.35) : "transparent"
    }

    Rectangle {
      objectName: "burnRowNow"
      readonly property real size: Style.space(4)
      x: row.nowX - size / 2
      y: row.nowY - size / 2
      width: size
      height: size
      radius: size / 2
      color: !root.host ? "transparent" : root.running ? Qt.lighter(root.host.tone, 1.6) : Qt.lighter(root.host.tone, 1.2)
    }
  }
}
