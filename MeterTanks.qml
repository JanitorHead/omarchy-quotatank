pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons
import "UsageLogic.js" as UsageLogic

// Meter style "Tanks", a group style. The group card stands every limit side by side as a glass tank whose
// level is the figure on the chosen side, with label and figure above and the verdict, rate and reset line
// below (beside it for a lone limit). A dashed line marks the level this pace reaches by the reset, labelled
// "95% at reset" or, red, "full 13:02" when the tank fills first. Under Used a faint band fills the glass up
// to it; under Remaining the liquid above the line is pale, what this pace drains ("empty 13:02" when it runs
// dry). While the account spends the surface rolls, higher and quicker as the pace presses on the limit,
// bubbles rise and each omp request drops in with a ripple; otherwise the tanks stand still. Row (account
// rows): a tiny tank, a rounded bar whose meniscus sways while the account spends. Card: that bar at card
// height (the panel shows group styles in the group card only).
//
// Liquid and bands are Shapes cut to the rounded glass by geometry, never by layers or effects; only the
// rolling surface rebuilds on the shared clock, and only while the account spends.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  // Group: the account's windows in card order, one tank each.
  readonly property var windows: variant === "group" && host && host.windows ? host.windows : []
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family
  // Light themes deepen a colour where dark ones brighten it, and get a paler glass.
  readonly property bool lightTheme: !!host && host.foreground.hslLightness < 0.5

  readonly property int columnGap: Style.space(16)
  readonly property real columnWidth: Math.max(0, (width - columnGap * Math.max(0, windows.length - 1)) / Math.max(1, windows.length))
  readonly property int tankWidth: Math.round(Math.max(Style.space(34), Math.min(Style.space(56), columnWidth * 0.4)))
  readonly property int tankHeight: Style.space(124)
  // A lone limit would leave most of the card empty: its verdict, rate and reset line stand beside the tank,
  // past side labels kept to the room "100% at reset" takes (longer ones wrap).
  readonly property bool single: windows.length === 1
  readonly property int singleLabelRoom: Math.ceil(captionMetrics.advanceWidth("100% at reset"))
  // Label and figure share a line while the widest label and the widest figure fit side by side;
  // otherwise (three limits, a live figure) every figure moves under its label.
  readonly property bool stackedHeads: {
    if (!host || windows.length === 0) return false
    var widest = 0
    for (var i = 0; i < windows.length; i++) widest = Math.max(widest, labelMetrics.advanceWidth(host.labelOf(windows[i])))
    var figure = figureMetrics.advanceWidth(host.liveFigure ? "100.00%" : "100%") + Style.spacing.sm
      + captionMetrics.advanceWidth(host.unitText())
    return widest + Style.spacing.controlGap + figure > columnWidth
  }
  // Every head as tall as the tallest, so the tanks line up when a long label wraps.
  readonly property real headHeight: {
    var tallest = 0
    for (var i = 0; i < tankColumns.count; i++) {
      var column = tankColumns.itemAt(i)
      if (column) tallest = Math.max(tallest, column.headNatural)
    }
    return tallest
  }

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function mix(a, b, k) { return Qt.rgba(a.r + (b.r - a.r) * k, a.g + (b.g - a.g) * k, a.b + (b.b - a.b) * k, 1) }
  function lift(color, k) { return lightTheme ? mix(color, Qt.rgba(0, 0, 0, 1), k * 0.45) : mix(color, Qt.rgba(1, 1, 1, 1), k) }
  // A steady pseudo-random 0-1 from two numbers: where a bubble rises, where a request drops in.
  function hash(a, b) {
    var s = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453
    return s - Math.floor(s)
  }
  function clockText(epochSeconds) {
    return host && typeof host.clock === "function" ? host.clock(epochSeconds) : ""
  }
  // How many caption lines `text` takes wrapped at its spaces into `room` (as Text.Wrap breaks it);
  // Infinity when a single word is wider than the room.
  function linesFor(text, room) {
    var words = String(text).split(" ")
    var lines = 1
    var line = ""
    for (var i = 0; i < words.length; i++) {
      if (captionMetrics.advanceWidth(words[i]) > room) return Infinity
      var joined = line === "" ? words[i] : line + " " + words[i]
      if (line !== "" && captionMetrics.advanceWidth(joined) > room) {
        lines++
        line = words[i]
      } else {
        line = joined
      }
    }
    return lines
  }
  // A side label: the first of `texts`, longest first, that fits two lines of `room`; "" when none does.
  function fitted(texts, room) {
    for (var i = 0; i < texts.length; i++) if (linesFor(texts[i], room) <= 2) return texts[i]
    return ""
  }

  implicitHeight: variant === "group" ? tankRow.implicitHeight : variant === "row" ? Style.space(5) : Style.space(10)

  FontMetrics {
    id: labelMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
    font.bold: true
  }

  FontMetrics {
    id: figureMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.heading
    font.bold: true
  }

  FontMetrics {
    id: captionMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  // Row and card: a tiny tank, the level as a rounded bar of the tone, its forecast stretch faint.
  Item {
    id: bar
    objectName: "tankBar"
    readonly property var limit: root.model
    readonly property bool remaining: !!limit && limit.quotaMode === "Remaining"
    readonly property bool forecastShown: !!limit && limit.forecastShown
    readonly property real forecastFrom: forecastShown ? limit.forecastFrom : 0
    readonly property real forecastTo: forecastShown ? limit.forecastTo : 0
    readonly property bool runsOut: !!limit && limit.runsOut
    readonly property color tone: root.host ? root.host.tone : "transparent"
    readonly property bool running: visible && !!limit && limit.moving && !!root.host && !!root.host.motion && !root.host.motion.reduced
    readonly property real now: running ? root.host.motion.liveSeconds : 0
    readonly property real pressure: limit ? Math.max(0, Math.min(2, limit.tempo)) : 0
    readonly property real beat: running ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((now / limit.period) % 1)) : 0
    // The meniscus sways while the account spends, quicker as the pace presses on the limit.
    readonly property real wobble: running ? Math.sin(now * (2.5 + 1.5 * pressure)) * Style.spaceReal(1.6) : 0
    property real level: limit && limit.hasMeter ? Math.max(0, Math.min(1, limit.fill)) : 0
    readonly property real surfaceX: Math.max(0, Math.min(width, width * level + wobble))

    visible: root.variant !== "group" && !!limit
    anchors.fill: parent

    Behavior on level {
      NumberAnimation { duration: root.host && root.host.motion ? root.host.motion.duration(root.host.motion.row) : 0; easing.type: Easing.OutCubic }
    }

    LiveClaim {
      motion: root.host ? root.host.motion : null
      active: bar.visible && !!bar.limit && bar.limit.moving
    }

    Rectangle {
      anchors.fill: parent
      radius: height / 2
      color: root.host ? root.alpha(root.host.foreground, 0.1) : "transparent"
    }

    // The forecast: what this pace adds past the level (Used), or drains from it (Remaining).
    Rectangle {
      objectName: "tankBarForecast"
      readonly property real from: bar.remaining ? bar.width * bar.forecastFrom - bar.height / 2 : bar.surfaceX - bar.height / 2
      readonly property real to: bar.remaining ? bar.surfaceX : bar.width * bar.forecastTo
      visible: bar.forecastShown
      x: Math.round(from)
      width: Math.max(0, Math.round(to - from))
      height: parent.height
      radius: height / 2
      color: !root.host ? "transparent" : bar.runsOut ? root.alpha(root.host.urgent, 0.45) : root.alpha(bar.tone, 0.22)
    }

    Rectangle {
      objectName: "tankBarLevel"
      width: Math.round(bar.remaining && bar.forecastShown ? bar.width * bar.forecastFrom : bar.surfaceX)
      height: parent.height
      radius: height / 2
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: root.alpha(bar.tone, 0.55) }
        GradientStop { position: 1; color: bar.tone }
      }
    }

    // The meniscus: a bright line at the level with a soft glow on the beat while the account spends.
    Rectangle {
      visible: bar.running && bar.level > 0
      x: Math.round(bar.surfaceX - width / 2)
      y: -Style.space(1)
      width: Style.space(5)
      height: parent.height + Style.space(2)
      radius: width / 2
      color: root.alpha(root.lift(bar.tone, 0.3), 0.35 * bar.beat)
    }

    Rectangle {
      objectName: "tankBarMeniscus"
      visible: bar.running && bar.level > 0
      x: Math.round(bar.surfaceX - width)
      width: Math.max(1, Math.round(Style.spaceReal(1.5)))
      height: parent.height
      color: root.lightTheme ? bar.tone : Qt.rgba(1, 1, 1, 0.85)
    }

    Rectangle {
      objectName: "tankBarPace"
      visible: !!root.host && root.host.markShown && !!bar.limit && bar.limit.markValue >= 0
      x: Math.round(bar.width * (bar.limit ? Math.max(0, bar.limit.markValue) : 0) - width / 2)
      y: -Style.space(2)
      width: Math.max(1, Math.round(Style.spaceReal(1.5)))
      height: parent.height + Style.space(4)
      color: root.host ? root.alpha(root.host.foreground, 0.85) : "transparent"
    }
  }

  // Group: a column per window: label and figure, the tank with its forecast and pace labels, then the
  // verdict, the rate and the reset line (beside the tank for a lone window).
  Row {
    id: tankRow
    objectName: "tankGroup"
    visible: root.variant === "group"
    width: parent.width
    spacing: root.columnGap

    Repeater {
      id: tankColumns
      model: root.windows.length

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
        }
        readonly property color tone: root.host ? root.host.toneOf(row) : "transparent"
        readonly property bool stressed: !!root.host && root.host.stressed(row)
        readonly property var verdict: root.host ? root.host.verdictOf(limit) : ({ text: "", urgent: false })
        readonly property real headNatural: head.natural

        objectName: "tankColumn-" + index
        width: root.columnWidth
        height: root.single ? tank.y + Math.max(tank.height, info.height) : info.y + info.height

        Item {
          id: head
          readonly property real natural: root.stackedHeads
            ? label.implicitHeight + Style.spacing.xxs + figure.height
            : Math.max(label.implicitHeight, figure.height)
          width: parent.width
          height: root.headHeight

          PlainText {
            id: label
            y: root.stackedHeads ? 0 : Math.round((Math.max(implicitHeight, figure.height) - implicitHeight) / 2)
            width: root.stackedHeads ? parent.width : Math.max(0, parent.width - figure.width - Style.spacing.controlGap)
            text: root.host ? root.host.labelOf(column.row) : ""
            color: root.host ? root.host.foreground : "transparent"
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
            wrapMode: root.stackedHeads ? Text.Wrap : Text.NoWrap
            maximumLineCount: root.stackedHeads ? 2 : 1
            elide: Text.ElideRight
          }

          // The figure: "72%" (or the live "72.03%") and its unit, beside the label or, stacked, at the foot
          // of the head so the figures line up across columns.
          Item {
            id: figure
            x: root.stackedHeads ? 0 : parent.width - width
            y: root.stackedHeads ? parent.height - height : 0
            width: number.implicitWidth + Style.spacing.sm + figureUnit.implicitWidth
            height: number.implicitHeight

            PlainText {
              id: number
              objectName: "tankFigure"
              text: root.host ? root.host.figureText(column.limit) : ""
              color: !root.host ? "transparent" : column.stressed ? root.host.urgent : root.host.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.heading
              font.bold: true
            }

            PlainText {
              id: figureUnit
              visible: column.limit.known
              anchors.left: number.right
              anchors.leftMargin: Style.spacing.sm
              anchors.baseline: number.baseline
              text: root.host ? root.host.unitText() : ""
              color: root.host ? root.host.dim : "transparent"
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }

        Item {
          id: tank
          objectName: "tank"
          readonly property LimitModel limit: column.limit
          readonly property bool remaining: limit.quotaMode === "Remaining"
          readonly property bool forecastShown: limit.forecastShown
          readonly property bool runsOut: limit.runsOut
          readonly property real unit: Style.spaceReal(1)
          // The glass: a rounded rectangle at the column's left, its labels to the right.
          readonly property real gx: Style.space(4)
          readonly property real gw: root.tankWidth
          readonly property real gh: height
          readonly property real gr: Math.round(gw / 4)
          readonly property real labelX: gx + gw + Style.space(15)
          // Room right of the glass for the forecast and pace labels; a lone tank keeps to a fixed share so the
          // verdict beside it keeps its place.
          readonly property real sideRoom: root.single ? Math.min(root.singleLabelRoom, Math.max(0, root.columnWidth / 2 - labelX))
            : Math.max(0, root.columnWidth - labelX)
          // Side label wordings, longest first; the labels take the first that fits two lines of the room.
          readonly property string runsOutClock: runsOut && limit.forecast ? root.clockText(limit.forecast.runsOutAt) : ""
          readonly property var forecastTexts: !forecastShown ? []
            : runsOut ? [(remaining ? "empty " : "full ") + runsOutClock, runsOutClock]
            : [Math.round(atReset * 100) + "% at reset", Math.round(atReset * 100) + "%"]
          readonly property var paceTexts: !paceShown ? []
            : [UsageLogic.expectedText(limit.pace, limit.quotaMode), "pace " + Math.round(UsageLogic.sideOfUsed(limit.pace.expected, limit.quotaMode)) + "%"]
          readonly property color tone: column.tone
          readonly property color topColor: root.lift(tone, 0.3)
          readonly property color bottomColor: root.mix(tone, Commons.Color.background, 0.5)
          property real level: limit.hasMeter ? Math.max(0, Math.min(1, limit.fill)) : 0
          readonly property real surfaceY: levelY(level)
          // The level this pace reaches by the reset, on the chosen side.
          readonly property real atReset: !forecastShown ? -1 : remaining ? limit.forecastFrom : limit.forecastTo
          readonly property bool paceShown: !!root.host && root.host.markShown && limit.markValue >= 0 && !limit.exhausted

          // Motion, on the shared clock and only while the account spends.
          readonly property bool running: visible && limit.moving && !!root.host && !!root.host.motion && !root.host.motion.reduced
          readonly property real now: running ? root.host.motion.liveSeconds : 0
          readonly property real pressure: Math.max(0, Math.min(2, limit.tempo))
          // An omp request drops in over a quarter second, then rings out on the surface.
          readonly property real requestAge: running && limit.requestAt > 0 ? now - limit.requestAt : -1
          readonly property real dropShare: requestAge >= 0 && requestAge < 0.25 ? requestAge / 0.25 : -1
          readonly property real rippleShare: requestAge >= 0.25 && requestAge < 0.8 ? (requestAge - 0.25) / 0.55 : -1
          readonly property real dropX: gw * (0.3 + 0.4 * root.hash(limit.requestAt, 1))
          // The surface rolls higher and quicker as the pace presses on the limit, and splashes as a drop lands.
          readonly property real amplitude: !running ? 0
            : unit * Math.min(3.6, 1 + 1.4 * pressure) + (rippleShare >= 0 ? unit * 2.4 * (1 - rippleShare) : 0)
          readonly property real phase: running ? (now * (2 + 1.2 * pressure)) % (2 * Math.PI) : 0
          readonly property real dashPitch: 6 * unit
          readonly property real march: running ? (now * (6 + 5 * pressure) * unit) % dashPitch : 0

          // The glass's outline as sample columns, denser around the corners, and how far its rounded
          // corners pull the top and bottom edges in at each.
          readonly property var columns: {
            var xs = []
            var steps = 6
            var inner = Math.max(1, Math.round((gw - 2 * gr) / (3 * unit)))
            for (var i = 0; i <= steps; i++) xs.push(gx + gr - gr * Math.cos(Math.PI / 2 * i / steps))
            for (var j = 1; j < inner; j++) xs.push(gx + gr + (gw - 2 * gr) * j / inner)
            for (var k = steps; k >= 0; k--) xs.push(gx + gw - gr + gr * Math.cos(Math.PI / 2 * k / steps))
            return xs
          }
          readonly property var arcs: columns.map(function(x) { return tank.arcAt(x) })
          readonly property var floor: lowerEdge(gh)
          readonly property var surface: wave(surfaceY, amplitude, phase)
          // Under Remaining the solid liquid stops at the reset level and the rest of it, pale, drains.
          readonly property var liquidPath: remaining && forecastShown ? wave(levelY(atReset), 0, 0).concat(floor) : surface.concat(floor)
          readonly property var drainPath: remaining && forecastShown ? surface.concat(lowerEdge(levelY(atReset))) : []
          readonly property var bandPath: !remaining && forecastShown ? wave(levelY(atReset), 0, 0).concat(lowerEdge(surfaceY)) : []
          // Where the side labels sit: at their own level where they can; otherwise pushed apart evenly by their
          // real (possibly wrapped) heights. They always stay within the glass's height. When both cannot fit,
          // the pace keeps only its arrow.
          readonly property var spots: {
            var gap = Style.space(6)
            var forecastHeight = forecastLabel.text !== "" ? forecastLabel.implicitHeight : 0
            var paceHeight = paceLabel.text !== "" ? paceLabel.implicitHeight : 0
            var forecastY = forecastHeight > 0 ? Math.max(forecastHeight / 2, Math.min(gh - forecastHeight / 2, levelY(atReset))) : -1
            var paceY = paceHeight > 0 ? Math.max(paceHeight / 2, Math.min(gh - paceHeight / 2, levelY(limit.markValue))) : -1
            if (forecastY < 0 || paceY < 0) return { forecast: forecastY, pace: paceY }
            var forecastAbove = forecastY <= paceY
            var upperHalf = (forecastAbove ? forecastHeight : paceHeight) / 2
            var lowerHalf = (forecastAbove ? paceHeight : forecastHeight) / 2
            var upper = Math.min(forecastY, paceY)
            var lower = Math.max(forecastY, paceY)
            var need = upperHalf + lowerHalf + gap
            if (lower - upper < need) {
              upper = Math.max(upperHalf, (upper + lower - need) / 2)
              lower = upper + need
              if (lower > gh - lowerHalf) {
                lower = gh - lowerHalf
                upper = lower - need
              }
              if (upper < upperHalf) return { forecast: forecastY, pace: -1 }
            }
            return forecastAbove ? { forecast: upper, pace: lower } : { forecast: lower, pace: upper }
          }

          function levelY(value) { return tank.gh * (1 - Math.max(0, Math.min(1, value))) }
          function arcAt(x) {
            var d = Math.min(x - tank.gx, tank.gx + tank.gw - x)
            if (d >= tank.gr) return 0
            var c = tank.gr - Math.max(0, d)
            return tank.gr - Math.sqrt(Math.max(0, tank.gr * tank.gr - c * c))
          }
          // How far the corners pull the glass's sides in at height y.
          function insetAt(y) {
            var c = y < tank.gr ? tank.gr - y : y > tank.gh - tank.gr ? y - (tank.gh - tank.gr) : 0
            return c <= 0 ? 0 : tank.gr - Math.sqrt(Math.max(0, tank.gr * tank.gr - c * c))
          }
          // A level across the glass, left to right, rolling by `amp` around `meanY`, kept inside the glass.
          function wave(meanY, amp, turn) {
            var points = []
            for (var i = 0; i < tank.columns.length; i++) {
              var x = tank.columns[i]
              var u = (x - tank.gx) / tank.unit
              var y = amp > 0 ? meanY + amp * (0.6 * Math.sin(u * 0.16 + turn) + 0.25 * Math.sin(u * 0.29 - 1.3 * turn)) : meanY
              points.push(Qt.point(x, Math.max(tank.arcs[i], Math.min(tank.gh - tank.arcs[i], y))))
            }
            return points
          }
          // A flat level right to left, closing a band.
          function lowerEdge(y) {
            var points = []
            for (var i = tank.columns.length - 1; i >= 0; i--)
              points.push(Qt.point(tank.columns[i], Math.max(tank.arcs[i], Math.min(tank.gh - tank.arcs[i], y))))
            return points
          }
          function leader(fromY, toY) {
            var edge = tank.gx + tank.gw
            return [Qt.point(edge + 2 * tank.unit, fromY), Qt.point(edge + 8 * tank.unit, fromY), Qt.point(edge + 12 * tank.unit, toY)]
          }

          y: head.height + Style.spacing.lg
          width: !root.single ? parent.width : forecastLabel.text !== "" || paceLabel.text !== "" ? labelX + sideRoom : gx + gw
          height: root.tankHeight

          Behavior on level {
            NumberAnimation { duration: root.host && root.host.motion ? root.host.motion.duration(root.host.motion.row) : 0; easing.type: Easing.OutCubic }
          }

          LiveClaim {
            motion: root.host ? root.host.motion : null
            active: tank.visible && tank.limit.moving
          }

          Rectangle {
            x: tank.gx
            width: tank.gw
            height: tank.gh
            radius: tank.gr
            color: root.lightTheme ? root.alpha(root.host.foreground, 0.06) : Qt.rgba(0, 0, 0, 0.32)
          }

          // Used: the glass this pace fills by the reset, faintly tinted (red when it fills first).
          Shape {
            objectName: "tankForecastBand"
            visible: tank.bandPath.length > 0
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
              strokeWidth: -1
              fillColor: !root.host ? "transparent" : root.alpha(tank.runsOut ? root.host.urgent : tank.topColor, 0.13)
              PathPolyline { path: tank.bandPath }
            }
          }

          // Remaining: the liquid this pace drains by the reset, pale above the dashed line.
          Shape {
            objectName: "tankDrain"
            visible: tank.drainPath.length > 0 && tank.level > 0
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            opacity: 0.4

            ShapePath {
              strokeWidth: -1
              fillGradient: LinearGradient {
                x1: 0
                y1: tank.surfaceY - Style.space(4)
                x2: 0
                y2: tank.gh
                GradientStop { position: 0; color: root.alpha(tank.topColor, 0.95) }
                GradientStop { position: 1; color: root.alpha(tank.bottomColor, 0.95) }
              }
              PathPolyline { path: tank.drainPath }
            }
          }

          Shape {
            objectName: "tankLiquid"
            visible: tank.level > 0
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
              strokeWidth: -1
              fillGradient: LinearGradient {
                x1: 0
                y1: tank.surfaceY - Style.space(4)
                x2: 0
                y2: tank.gh
                GradientStop { position: 0; color: root.alpha(tank.topColor, 0.95) }
                GradientStop { position: 1; color: root.alpha(tank.bottomColor, 0.95) }
              }
              PathPolyline { path: tank.liquidPath }
            }
          }

          // The surface: a bright line, with a wider faint one behind it while it rolls (no blur).
          Shape {
            visible: tank.running && tank.level > 0 && tank.level < 1
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
              strokeColor: root.alpha(tank.topColor, 0.35)
              strokeWidth: 3.5 * tank.unit
              fillColor: "transparent"
              capStyle: ShapePath.RoundCap
              joinStyle: ShapePath.RoundJoin
              PathPolyline { path: tank.surface }
            }
          }

          Shape {
            objectName: "tankSurface"
            visible: tank.level > 0 && tank.level < 1
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
              strokeColor: Qt.rgba(1, 1, 1, 0.7)
              strokeWidth: 1.3 * tank.unit
              fillColor: "transparent"
              capStyle: ShapePath.RoundCap
              joinStyle: ShapePath.RoundJoin
              PathPolyline { path: tank.surface }
            }
          }

          // The dashed level at the reset, marching while the account spends.
          Item {
            id: forecastLine
            objectName: "tankForecastLine"
            readonly property real lineY: Math.round(Math.max(Style.space(1), Math.min(tank.gh - Style.space(2), tank.levelY(tank.atReset))))
            readonly property real inset: tank.insetAt(lineY) + Style.space(1)
            visible: tank.forecastShown
            x: tank.gx + inset
            y: lineY
            width: Math.max(0, tank.gw - 2 * inset)
            height: Math.max(1, Math.round(1.2 * tank.unit))
            clip: true

            Repeater {
              model: forecastLine.visible ? Math.ceil(forecastLine.width / tank.dashPitch) + 1 : 0

              Rectangle {
                required property int index
                x: (index - 1) * tank.dashPitch + tank.march
                width: tank.dashPitch / 2
                height: forecastLine.height
                color: !root.host ? "transparent" : tank.runsOut ? root.alpha(root.host.urgent, 0.95) : root.alpha(root.host.foreground, 0.55)
              }
            }
          }

          // Inside the glass while the account spends: rising bubbles, more as the pace presses on the
          // limit, and the drop and ripple of the newest request.
          Item {
            id: inside
            readonly property real depth: tank.gh - Style.space(3) - (tank.surfaceY + Style.space(2))
            visible: tank.running && tank.level > 0
            x: tank.gx
            width: tank.gw
            height: tank.gh
            clip: true

            Repeater {
              model: inside.visible && inside.depth > Style.space(8) ? (tank.pressure < 0.6 ? 1 : tank.pressure < 1.2 ? 2 : 3) : 0

              Rectangle {
                required property int index
                readonly property real speed: tank.unit * (12 + 10 * root.hash(index, 3)) * (1 + 0.35 * tank.pressure)
                readonly property real cycle: inside.depth / speed + 0.6 + 1.4 * root.hash(index, 5)
                readonly property real clock: tank.now + 7.3 * index
                readonly property real lap: Math.floor(clock / cycle)
                readonly property real age: clock - lap * cycle
                readonly property real size: tank.unit * (1.6 + 3.2 * root.hash(index, lap))
                objectName: "tankBubble"
                visible: age * speed < inside.depth
                x: Style.space(8) + root.hash(lap, index + 11) * (tank.gw - Style.space(16)) + Math.sin(tank.now * 3.3 + index) * tank.unit - width / 2
                y: tank.gh - Style.space(3) - age * speed - height / 2
                width: size
                height: size
                radius: size / 2
                color: "transparent"
                border.width: Math.max(1, Math.round(0.8 * tank.unit))
                border.color: Qt.rgba(1, 1, 1, 0.5)
              }
            }

            Rectangle {
              objectName: "tankDrop"
              readonly property real size: 4.6 * tank.unit
              visible: tank.dropShare >= 0
              x: tank.dropX - size / 2
              y: Style.space(3) + (tank.surfaceY - Style.space(3)) * Math.max(0, tank.dropShare) * Math.max(0, tank.dropShare) - size / 2
              width: size
              height: size
              radius: size / 2
              color: tank.topColor

              Rectangle {
                x: (parent.size - width) / 2
                y: -6 * tank.unit
                width: 1.6 * tank.unit
                height: 6 * tank.unit
                color: root.alpha(tank.topColor, 0.35)
              }
            }

            Rectangle {
              objectName: "tankRipple"
              readonly property real spread: Math.max(0, tank.rippleShare)
              visible: tank.rippleShare >= 0
              x: tank.dropX - width / 2
              y: tank.surfaceY - height / 2
              width: 2 * tank.unit * (3 + 14 * spread)
              height: 2 * tank.unit * (1 + 3 * spread)
              radius: height / 2
              color: "transparent"
              border.width: Math.max(1, Math.round(tank.unit))
              border.color: Qt.rgba(1, 1, 1, 0.7 * (1 - spread))
            }
          }

          // Glass sheen, outline and quarter ticks.
          Rectangle {
            x: tank.gx + Style.space(4)
            y: Style.space(8)
            width: Style.space(10)
            height: Math.max(0, tank.gh - Style.space(16))
            gradient: Gradient {
              orientation: Gradient.Horizontal
              GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0.14) }
              GradientStop { position: 1; color: Qt.rgba(1, 1, 1, 0) }
            }
          }

          Rectangle {
            objectName: "tankGlass"
            x: tank.gx
            width: tank.gw
            height: tank.gh
            radius: tank.gr
            color: "transparent"
            border.width: Style.spacing.hairline
            border.color: root.host ? root.alpha(root.host.foreground, 0.38) : "transparent"
          }

          Repeater {
            model: 3

            Rectangle {
              required property int index
              x: tank.gx + tank.gw - Style.space(7)
              y: Math.round(tank.levelY((index + 1) / 4))
              width: Style.space(6)
              height: Style.spacing.hairline
              color: root.host ? root.alpha(root.host.foreground, 0.25) : "transparent"
            }
          }

          // Leaders from the glass to the labels, and the pace mark: a small arrow at even use.
          Shape {
            visible: tank.forecastShown || tank.paceShown
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
              strokeColor: forecastLabel.visible && root.host ? root.alpha(root.host.foreground, 0.35) : "transparent"
              strokeWidth: Style.spacing.hairline
              fillColor: "transparent"
              PathPolyline { path: forecastLabel.visible ? tank.leader(tank.levelY(tank.atReset), tank.spots.forecast) : [] }
            }

            ShapePath {
              strokeColor: paceLabel.visible && root.host ? root.alpha(root.host.foreground, 0.35) : "transparent"
              strokeWidth: Style.spacing.hairline
              fillColor: "transparent"
              PathPolyline { path: paceLabel.visible ? tank.leader(tank.levelY(tank.limit.markValue), tank.spots.pace) : [] }
            }

            ShapePath {
              strokeWidth: -1
              fillColor: tank.paceShown && root.host ? root.alpha(root.host.foreground, 0.95) : "transparent"
              PathPolyline {
                path: {
                  if (!tank.paceShown) return []
                  var edge = tank.gx + tank.gw
                  var y = tank.levelY(tank.limit.markValue)
                  return [Qt.point(edge + tank.unit, y), Qt.point(edge + 6 * tank.unit, y - 3.5 * tank.unit),
                    Qt.point(edge + 6 * tank.unit, y + 3.5 * tank.unit), Qt.point(edge + tank.unit, y)]
                }
              }
            }
          }

          PlainText {
            id: forecastLabel
            objectName: "tankForecastLabel"
            visible: text !== ""
            x: tank.labelX
            y: Math.round(tank.spots.forecast - height / 2)
            width: tank.sideRoom
            text: root.fitted(tank.forecastTexts, tank.sideRoom)
            color: !root.host ? "transparent" : tank.runsOut ? root.host.urgent : root.host.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
          }

          PlainText {
            id: paceLabel
            objectName: "tankPaceLabel"
            visible: text !== "" && tank.spots.pace >= 0
            x: tank.labelX
            y: Math.round(tank.spots.pace - height / 2)
            width: tank.sideRoom
            text: root.fitted(tank.paceTexts, tank.sideRoom)
            color: root.host ? root.alpha(root.host.foreground, 0.9) : "transparent"
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
          }
        }

        // Verdict, rate and reset line: under the tank, or beside a lone tank, centred on it.
        Column {
          id: info
          objectName: "tankInfo"
          x: root.single ? Math.round(tank.width + Style.space(16)) : 0
          y: root.single ? tank.y + Math.max(0, Math.round((tank.height - height) / 2)) : tank.y + tank.height + Style.spacing.lg
          width: Math.max(0, column.width - x)
          spacing: Style.spacing.xs

          PlainText {
            objectName: "tankVerdict"
            visible: text !== ""
            width: parent.width
            text: column.verdict.text
            color: !root.host ? "transparent" : column.verdict.urgent ? root.host.urgent : root.host.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.weight: column.verdict.urgent ? Font.DemiBold : Font.Normal
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
          }

          RateChip {
            visible: column.limit.known
            model: column.limit
            motion: root.host ? root.host.motion : null
            foreground: root.host ? root.host.foreground : "white"
            accent: root.host ? root.host.providerColor : "white"
            urgent: root.host ? root.host.urgent : "red"
            fontFamily: root.fontFamily
          }

          PlainText {
            visible: text !== ""
            width: parent.width
            text: root.host ? root.host.resetLabelOf(column.row) : ""
            color: root.host ? root.host.dim : "transparent"
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
          }

          PlainText {
            visible: text !== ""
            width: parent.width
            text: column.row ? String(column.row.detail || "") : ""
            color: root.host ? root.host.dim : "transparent"
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
          }
        }
      }
    }
  }
}
