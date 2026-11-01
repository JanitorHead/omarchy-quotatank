pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons

// Meter style "Compact", a group style. The group card holds every limit as one tight line: label, a thin
// meter and the figure, and under it the verdict left and, right, the rate while the account spends and
// the reset time. The meter's fill ends in a head; a faint stretch past it is what this pace adds by the
// reset (Used), or, under Remaining, the end of the fill this pace drains; red when the limit runs out
// first. While the account spends, a glint runs along the fill toward the head (leftward under Remaining,
// where the level falls), the head breathes on the beat and rings on each omp request; otherwise the
// lines stand still. Row (account rows): the same meter, thinner, its head shown only while spending.
// Card: the meter alone at card height (the panel shows group styles in the group card only).
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  // Group: the account's windows in card order, one line each.
  readonly property var windows: variant === "group" && host && host.windows ? host.windows : []
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family

  // The labels share one column, as wide as the widest (at most a third of the line), so the meters align.
  readonly property real labelWidth: {
    if (!host || windows.length === 0) return 0
    var widest = 0
    for (var i = 0; i < windows.length; i++) widest = Math.max(widest, labelMetrics.advanceWidth(host.labelOf(windows[i])))
    return Math.ceil(Math.min(widest + 1, width * 0.36))
  }
  readonly property real figureWidth: Math.ceil(figureMetrics.advanceWidth(variant === "group" && host && host.liveFigure ? "100.00%" : "100%"))
  readonly property int lineGap: Style.spacing.xl

  function clockText(epochSeconds) {
    return host && typeof host.clock === "function" ? host.clock(epochSeconds) : ""
  }

  implicitHeight: variant === "group" ? lines.implicitHeight : variant === "row" ? Style.space(6) : Style.space(14)

  FontMetrics {
    id: labelMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
    font.bold: true
  }

  FontMetrics {
    id: figureMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.title
    font.bold: true
  }

  // One limit as a line: track, fill, its forecast stretch and a head at the level.
  component LineMeter: Item {
    id: line

    property var limit: null
    property var motion: null
    property color tone: "white"
    property color foreground: "white"
    property color urgent: "red"
    property bool markShown: false
    property real thickness: Style.space(4)
    property real trackOpacity: 0.1
    // Room kept at both ends so the head stays whole at 0 and 100 %.
    property real inset: Style.spaceReal(3)
    // Group and card keep the head when still; account rows show it only while the account spends.
    property bool stillHead: true

    // Gallery pixels at this thickness: the head, halo and ripple scale with the line.
    readonly property real grain: thickness / 4
    readonly property bool lightTheme: foreground.hslLightness < 0.5
    readonly property real span: Math.max(0, width - 2 * inset)
    readonly property bool remaining: !!limit && limit.quotaMode === "Remaining"
    readonly property bool forecastShown: !!limit && limit.forecastShown
    readonly property real forecastFrom: forecastShown ? limit.forecastFrom : 0
    readonly property real forecastTo: forecastShown ? limit.forecastTo : 0
    readonly property bool runsOut: !!limit && limit.runsOut
    property real level: limit && limit.hasMeter ? Math.max(0, Math.min(1, limit.fill)) : 0
    readonly property real headX: xAt(level)
    readonly property real trackY: Math.round((height - thickness) / 2)
    readonly property real centerY: trackY + thickness / 2

    // Motion, on the shared clock and only while the account spends.
    readonly property bool running: visible && !!limit && limit.moving && !!motion && !motion.reduced
    readonly property real now: running ? motion.liveSeconds : 0
    readonly property real period: limit && limit.period > 0 ? limit.period : 3.2
    readonly property real beat: running ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((now / period) % 1)) : 0
    // The glint takes a little longer than a beat to run the fill.
    readonly property real glint: running ? (now / (period * 1.3)) % 1 : 0
    // Fades from 0 to 1 over 0.8 s after each omp request (the request ring); -1 otherwise.
    readonly property real ring: {
      var age = running && limit.requestAt > 0 ? now - limit.requestAt : -1
      return age >= 0 && age < 0.8 ? age / 0.8 : -1
    }
    readonly property color highlight: runsOut || (!!limit && limit.pressure > 1) ? lift(urgent, 0.25) : lift(tone, 0.3)

    function xAt(value) { return line.inset + line.span * Math.max(0, Math.min(1, value)) }
    function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
    function mix(a, b, k) { return Qt.rgba(a.r + (b.r - a.r) * k, a.g + (b.g - a.g) * k, a.b + (b.b - a.b) * k, 1) }
    // Brighter on dark themes, deeper on light ones.
    function lift(color, k) { return line.lightTheme ? line.mix(color, Qt.rgba(0, 0, 0, 1), k * 0.45) : line.mix(color, Qt.rgba(1, 1, 1, 1), k) }

    Behavior on level {
      NumberAnimation { duration: line.motion ? line.motion.duration(line.motion.row) : 0; easing.type: Easing.OutCubic }
    }

    LiveClaim {
      motion: line.motion
      active: line.visible && !!line.limit && line.limit.moving
    }

    Rectangle {
      x: line.inset
      y: line.trackY
      width: line.span
      height: line.thickness
      radius: height / 2
      color: line.alpha(line.foreground, line.trackOpacity)
    }

    // The forecast: what this pace adds past the head (Used), or the end of the fill it drains
    // (Remaining), tucked under the fill's round end.
    Rectangle {
      objectName: "compactForecast"
      readonly property real from: (line.remaining ? line.xAt(line.forecastFrom) : line.headX) - line.thickness / 2
      readonly property real to: line.remaining ? line.headX : line.xAt(line.forecastTo)
      visible: line.forecastShown
      x: from
      y: line.trackY
      width: Math.max(0, to - from)
      height: line.thickness
      radius: height / 2
      color: line.runsOut ? line.alpha(line.urgent, 0.45) : line.alpha(line.tone, 0.22)
    }

    Rectangle {
      objectName: "compactFill"
      x: line.inset
      y: line.trackY
      width: Math.max(0, (line.remaining && line.forecastShown ? line.xAt(line.forecastFrom) : line.headX) - line.inset)
      height: line.thickness
      radius: height / 2
      color: line.tone
    }

    // The glint: a bright fade running along the fill toward the head (Used) or from it (Remaining).
    Item {
      objectName: "compactGlint"
      visible: line.running && width > 1
      x: line.inset
      y: line.trackY
      width: Math.max(0, line.headX - line.inset)
      height: line.thickness
      clip: true

      Rectangle {
        readonly property real travel: parent.width * line.glint
        x: line.remaining ? parent.width - travel : travel - width
        width: 10 * line.thickness
        height: parent.height
        opacity: 0.7 * Math.sin(Math.PI * line.glint)
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0; color: Qt.rgba(1, 1, 1, line.remaining ? 1 : 0) }
          GradientStop { position: 1; color: Qt.rgba(1, 1, 1, line.remaining ? 0 : 1) }
        }
      }
    }

    Rectangle {
      objectName: "compactPace"
      visible: line.markShown && !!line.limit && line.limit.markValue >= 0 && !line.limit.exhausted
      x: Math.round(line.xAt(line.limit ? line.limit.markValue : 0) - width / 2)
      y: Math.round(line.centerY - height / 2)
      width: Math.max(1, Math.round(1.5 * line.grain))
      height: Math.round(3 * line.thickness)
      color: line.alpha(line.foreground, 0.85)
    }

    // A soft halo behind the head, breathing on the beat: drawn once, then only scaled.
    Shape {
      id: halo
      objectName: "compactHalo"
      readonly property real reach: 10 * line.grain
      visible: line.running && !!line.limit && line.limit.hasMeter
      x: line.headX - reach
      y: line.centerY - reach
      width: 2 * reach
      height: 2 * reach
      scale: 0.6 + 0.4 * line.beat
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeWidth: -1
        fillGradient: RadialGradient {
          centerX: halo.reach
          centerY: halo.reach
          centerRadius: halo.reach
          focalX: halo.reach
          focalY: halo.reach
          GradientStop { position: 0; color: line.alpha(line.highlight, 0.55) }
          GradientStop { position: 1; color: line.alpha(line.highlight, 0) }
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

    Rectangle {
      objectName: "compactRipple"
      readonly property real reach: line.grain * (3 + 8 * Math.max(0, line.ring))
      visible: line.ring >= 0
      x: line.headX - reach
      y: line.centerY - reach
      width: 2 * reach
      height: 2 * reach
      radius: reach
      color: "transparent"
      border.width: Math.max(1, Math.round(1.2 * line.grain))
      border.color: line.alpha(line.highlight, 0.8 * (1 - Math.max(0, line.ring)))
    }

    Rectangle {
      objectName: "compactHead"
      readonly property real size: Math.round(1.3 * line.thickness)
      visible: !!line.limit && line.limit.hasMeter && (line.stillHead || line.running)
      x: line.headX - size / 2
      y: line.centerY - size / 2
      width: size
      height: size
      radius: size / 2
      color: line.running && !line.lightTheme ? "white" : line.lift(line.tone, 0.25)
    }
  }

  // Row and card: the meter alone.
  LineMeter {
    objectName: "compactRowMeter"
    visible: root.variant !== "group" && !!root.model
    anchors.fill: parent
    limit: root.model
    motion: root.host ? root.host.motion : null
    tone: root.host ? root.host.tone : "transparent"
    foreground: root.host ? root.host.foreground : "transparent"
    urgent: root.host ? root.host.urgent : "transparent"
    markShown: !!root.host && root.host.markShown
    thickness: root.variant === "row" ? Style.space(3) : Style.space(4)
    trackOpacity: root.variant === "row" ? 0.12 : 0.1
    inset: root.variant === "row" ? 0 : Style.spaceReal(3)
    stillHead: root.variant !== "row"
  }

  // Group: a line per window, its verdict, rate and reset time under it.
  Column {
    id: lines
    objectName: "compactGroup"
    visible: root.variant === "group"
    width: parent.width
    spacing: Style.spacing.lg

    Repeater {
      model: root.windows.length

      Column {
        id: entry
        required property int index
        readonly property var row: root.windows[index] || null
        readonly property LimitModel limit: LimitModel {
          window: entry.row
          nowSeconds: root.host ? root.host.nowSeconds : 0
          quotaMode: root.host ? root.host.quotaMode : "Used"
          spending: !!root.host && root.host.spending
          readingAt: root.host ? root.host.readingAt : 0
          requestAt: root.host ? root.host.requestAt : 0
        }
        readonly property bool stressed: !!root.host && root.host.stressed(row)
        readonly property var verdict: root.host ? root.host.verdictOf(limit) : ({ text: "", urgent: false })
        // Verdict left, rate and reset right; the right part drops under the verdict when both do not fit.
        readonly property bool stacked: verdictText.visible && runLine.implicitWidth > 0
          && verdictText.implicitWidth + Style.spacing.controlGap + runLine.implicitWidth > width

        objectName: "compactLine-" + index
        width: lines.width
        spacing: Style.spacing.xxs

        Item {
          width: parent.width
          height: Math.max(label.implicitHeight, figure.implicitHeight, meter.height)

          PlainText {
            id: label
            anchors.verticalCenter: parent.verticalCenter
            width: root.labelWidth
            text: root.host ? root.host.labelOf(entry.row) : ""
            color: root.host ? root.host.foreground : "transparent"
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
            elide: Text.ElideRight
          }

          LineMeter {
            id: meter
            objectName: "compactMeter"
            x: root.labelWidth + root.lineGap
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, parent.width - x - root.lineGap - root.figureWidth)
            height: Style.space(14)
            limit: entry.limit
            motion: root.host ? root.host.motion : null
            tone: root.host ? root.host.toneOf(entry.row) : "transparent"
            foreground: root.host ? root.host.foreground : "transparent"
            urgent: root.host ? root.host.urgent : "transparent"
            markShown: !!root.host && root.host.markShown
          }

          PlainText {
            id: figure
            objectName: "compactFigure"
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: root.figureWidth
            horizontalAlignment: Text.AlignRight
            text: root.host ? root.host.figureText(entry.limit) : ""
            color: !root.host ? "transparent" : entry.stressed ? root.host.urgent : root.host.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
          }
        }

        Item {
          width: parent.width
          height: entry.stacked ? verdictText.implicitHeight + Style.spacing.xxs + runLine.implicitHeight
            : Math.max(verdictText.visible ? verdictText.implicitHeight : 0, runLine.implicitHeight)

          PlainText {
            id: verdictText
            objectName: "compactVerdict"
            visible: text !== ""
            width: Math.min(implicitWidth, parent.width)
            text: entry.verdict.text
            color: !root.host ? "transparent" : entry.verdict.urgent ? root.host.urgent : root.host.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.weight: entry.verdict.urgent ? Font.DemiBold : Font.Normal
            elide: Text.ElideRight
          }

          Row {
            id: runLine
            x: parent.width - width
            y: entry.stacked ? verdictText.implicitHeight + Style.spacing.xxs : 0
            spacing: Style.spacing.sm

            RateChip {
              id: chip
              visible: entry.limit.moving
              model: entry.limit
              motion: root.host ? root.host.motion : null
              foreground: root.host ? root.host.foreground : "white"
              accent: root.host ? root.host.providerColor : "white"
              urgent: root.host ? root.host.urgent : "red"
              fontFamily: root.fontFamily
            }

            PlainText {
              visible: chip.visible && resetText.text !== ""
              text: "·"
              color: root.host ? root.host.dim : "transparent"
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            PlainText {
              id: resetText
              visible: text !== ""
              text: entry.limit.resetsAt > 0 ? "resets " + root.clockText(entry.limit.resetsAt) : ""
              color: root.host ? root.host.dim : "transparent"
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }

        PlainText {
          visible: text !== ""
          width: parent.width
          text: entry.row ? String(entry.row.detail || "") : ""
          color: root.host ? root.host.dim : "transparent"
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }
}
