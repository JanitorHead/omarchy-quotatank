pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons

// Meter style "Ruler": a precision rule. Card: a notch for every 1 % (longer every 5 and 10), the notches
// up to the fill lit, those this pace still reaches by the reset in half tone (urgent when the limit runs
// out), a needle at the fill and the scale 0 · 50 · 100 under it. While the account spends, the notches
// by the needle swell like a lens on the beat, faster as the pace presses on the limit, and a request
// rings the needle's head. Row: a notch every 4 % and, while spending, a needle pulsing at the fill.
// See MeterProjection.qml for the host contract.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property var motion: host ? host.motion : null

  readonly property bool moving: !!model && model.moving && visible
  readonly property bool running: moving && !!motion && !motion.reduced
  readonly property real seconds: running ? motion.liveSeconds : 0
  readonly property real beat: running && model.period > 0
    ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((seconds / model.period) % 1)) : 0
  readonly property real requestAge: running && model.requestAt > 0 ? seconds - model.requestAt : -1
  property real edgeFill: model ? model.fill : 0
  // Fill and forecast in notches (percent), so every notch reads them the same way.
  readonly property real fillPercent: edgeFill * 100
  readonly property bool forecastShown: !!model && model.forecastShown
  readonly property real forecastFromPercent: forecastShown ? model.forecastFrom * 100 : -1
  readonly property real forecastToPercent: forecastShown ? model.forecastTo * 100 : -1

  readonly property bool lightTheme: Commons.Color.background.hslLightness > 0.5
  readonly property color tone: host ? host.tone : "transparent"
  readonly property color hi: !host ? "transparent"
    : model && (model.runsOut || model.pressure > 1) ? lift(host.urgent, 0.25) : lift(host.tone, 0.3)
  readonly property color forecastColor: !host ? "transparent"
    : model && model.runsOut ? alpha(host.urgent, 0.7) : alpha(host.tone, 0.45)
  readonly property color trackColor: host ? alpha(host.foreground, lightTheme ? 0.3 : 0.22) : "transparent"

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function mix(a, b, k) { return Qt.rgba(a.r + (b.r - a.r) * k, a.g + (b.g - a.g) * k, a.b + (b.b - a.b) * k, 1) }
  // Towards white on a dark theme, towards black on a light one: a highlight that reads on either.
  function lift(color, k) { return lightTheme ? mix(color, Qt.rgba(0, 0, 0, 1), k * 0.45) : mix(color, Qt.rgba(1, 1, 1, 1), k) }
  // A notch at `percent`: in the forecast stretch (past the fill under Used, the part of the fill this
  // pace spends under Remaining), lit up to the fill, or bare.
  function notchColor(percent) {
    if (forecastShown && percent > forecastFromPercent + 1e-6 && percent <= forecastToPercent + 1e-6) return forecastColor
    return percent <= fillPercent + 1e-6 ? tone : trackColor
  }

  implicitHeight: variant === "row" ? Style.space(9) : card.implicitHeight

  LiveClaim {
    motion: root.motion
    active: root.moving
  }

  Behavior on edgeFill {
    NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
  }

  Item {
    id: card
    objectName: "rulerCard"
    visible: root.variant === "card" && !!root.model && root.model.hasMeter
    anchors.fill: parent

    // Room for the needle's head at either end.
    readonly property real inset: Style.space(5)
    readonly property real span: Math.max(0, width - 2 * inset)
    readonly property real base: Style.space(28)
    readonly property real needleX: xAt(root.fillPercent)
    readonly property real lensStrength: root.running ? 0.35 + 0.65 * root.beat : 0
    readonly property int lensReach: 8

    function xAt(percent) { return inset + span * Math.max(0, Math.min(100, percent)) / 100 }
    function notchHeight(index) { return Style.space(index % 10 === 0 ? 13 : index % 5 === 0 ? 9 : 5) }
    function notchWidth(index) { return index % 10 === 0 ? Style.space(2) : Style.spacing.hairline }

    implicitHeight: scaleRow.y + scaleRow.height

    Repeater {
      objectName: "rulerNotches"
      model: 101

      Rectangle {
        required property int index
        x: Math.round(card.xAt(index) - width / 2)
        y: card.base - height
        width: card.notchWidth(index)
        height: card.notchHeight(index)
        color: root.notchColor(index)
      }
    }

    // Spending: the notches by the needle swell like a lens on the beat. Only these few move; they cover
    // the still notches beneath them.
    Repeater {
      objectName: "rulerLens"
      model: card.lensStrength > 0 ? card.lensReach * 2 + 1 : 0

      Rectangle {
        required property int index
        readonly property int notch: Math.round(root.fillPercent) - card.lensReach + index
        readonly property real swell: 1 + 1.1 * card.lensStrength * Math.exp(-Math.pow((notch - root.fillPercent) / 3.2, 2))
        visible: notch >= 0 && notch <= 100
        x: Math.round(card.xAt(notch) - width / 2)
        y: card.base - height
        width: card.notchWidth(notch)
        height: Math.round(card.notchHeight(notch) * swell)
        color: root.notchColor(notch)
      }
    }

    // A faint glow along the needle while spending.
    Rectangle {
      visible: root.running
      x: Math.round(card.needleX - width / 2)
      y: Style.space(1)
      width: Style.space(7)
      height: card.base - Style.space(1)
      radius: width / 2
      color: root.alpha(root.hi, 0.3 * card.lensStrength)
    }

    // The needle: a head above the rule and a stem down to its base.
    Rectangle {
      objectName: "rulerNeedle"
      x: Math.round(card.needleX - width / 2)
      y: Style.space(6)
      width: Math.max(1, Style.space(2))
      height: card.base - y
      color: needleHead.ink
    }

    Shape {
      id: needleHead
      readonly property color ink: root.running ? root.hi : root.lift(root.tone, 0.2)
      x: card.needleX - width / 2
      y: Style.space(1)
      width: Style.space(9)
      height: Style.space(6)
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeWidth: -1
        strokeColor: "transparent"
        fillColor: needleHead.ink
        startX: 0
        startY: 0
        PathLine { x: needleHead.width; y: 0 }
        PathLine { x: needleHead.width / 2; y: needleHead.height }
        PathLine { x: 0; y: 0 }
      }
    }

    // A request: a ring spreads from the needle's head.
    Rectangle {
      objectName: "rulerRipple"
      readonly property real progress: root.requestAge >= 0 && root.requestAge < 0.8 ? root.requestAge / 0.8 : -1
      readonly property real reach: Style.spaceReal(3 + 10 * Math.max(0, progress))
      visible: progress >= 0
      x: card.needleX - reach
      y: Style.space(4) - reach
      width: reach * 2
      height: reach * 2
      radius: reach
      color: "transparent"
      border.width: Style.spacing.hairline
      border.color: root.alpha(root.hi, 1 - Math.max(0, progress))
    }

    // Pace tick: an open triangle under the rule pointing at where even use would be by now.
    Shape {
      id: paceMark
      objectName: "rulerPaceTick"
      visible: !!root.model && root.model.markValue >= 0 && !!root.host && root.host.markShown
      x: card.xAt(root.model ? root.model.markValue * 100 : 0) - width / 2
      y: card.base + Style.space(2)
      width: Style.space(7)
      height: Style.space(5)
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeColor: root.host ? root.alpha(root.host.foreground, 0.9) : "transparent"
        strokeWidth: Style.spaceReal(1.2)
        fillColor: "transparent"
        joinStyle: ShapePath.MiterJoin
        startX: paceMark.width / 2
        startY: 0
        PathLine { x: paceMark.width; y: paceMark.height }
        PathLine { x: 0; y: paceMark.height }
        PathLine { x: paceMark.width / 2; y: 0 }
      }
    }

    // The scale.
    Item {
      id: scaleRow
      y: card.base + Style.space(7)
      width: card.width
      height: scaleZero.implicitHeight

      PlainText {
        id: scaleZero
        x: Math.round(card.xAt(0) - Style.space(1))
        text: "0"
        color: root.host ? root.host.dim : "transparent"
        font.family: root.host ? root.host.fontFamily : Style.font.family
        font.pixelSize: Style.font.caption
      }

      PlainText {
        x: Math.round(card.xAt(50) - implicitWidth / 2)
        text: "50"
        color: scaleZero.color
        font: scaleZero.font
      }

      PlainText {
        x: Math.round(card.xAt(100) + Style.space(1) - implicitWidth)
        text: "100"
        color: scaleZero.color
        font: scaleZero.font
      }
    }
  }

  Item {
    id: rowRule
    objectName: "rulerRow"
    visible: root.variant === "row" && !!root.model
    anchors.fill: parent

    readonly property real base: Math.round(height * 0.85)
    readonly property real needleX: Math.round(width * Math.max(0, Math.min(1, root.edgeFill)))

    Repeater {
      model: 26

      Rectangle {
        required property int index
        readonly property int percent: index * 4
        x: Math.min(rowRule.width - width, Math.round(rowRule.width * percent / 100))
        y: rowRule.base - height
        width: Style.spacing.hairline
        height: Style.space(percent % 20 === 0 ? 7 : 4)
        color: root.notchColor(percent)
      }
    }

    // Spending: a needle at the fill, its glow swelling on the beat.
    Rectangle {
      visible: root.running
      x: rowRule.needleX - width / 2
      y: 0
      width: Style.space(6)
      height: rowRule.height
      radius: width / 2
      color: root.alpha(root.hi, 0.35 * root.beat)
    }

    Rectangle {
      objectName: "rulerRowNeedle"
      visible: root.running
      x: rowRule.needleX - width / 2
      y: 0
      width: Style.space(2)
      height: rowRule.height
      color: root.lift(root.tone, 0.3)
    }
  }
}
