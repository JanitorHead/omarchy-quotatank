pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons

// Meter style "Live ticker" (feature layout: the card's large figure leads, best with Display → Live figure,
// whose decimals climb with the rate). Card: a 2 px line that follows the live estimate (the reading plus
// what the rate has added since), the forecast to the reset in a translucent stretch (past the estimate
// under Used, over the part of the fill it will spend under Remaining; red when it runs out) and, while the
// account spends, a bright head tick at the estimate whose glow beats with the pace. Row: a 1.5 px line with
// the same head while spending.
//
// Host contract: see MeterProjection.qml.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property var motion: host ? host.motion : null

  // Motion only while the account spends; the still frame is the line and its forecast.
  readonly property bool moving: !!model && model.moving
  readonly property bool animating: moving && !!motion && !motion.reduced
  readonly property real seconds: animating ? motion.liveSeconds : 0
  readonly property real period: model ? Math.max(0.2, model.period) : 1
  readonly property real beat: animating ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((seconds / period) % 1)) : 0
  readonly property bool remaining: !!model && model.quotaMode === "Remaining"
  readonly property color tone: host ? host.tone : "transparent"
  readonly property color foreground: host ? host.foreground : "transparent"
  readonly property color urgent: host ? host.urgent : "transparent"
  // The live estimate on the chosen side (0-1): where the line ends and the head stands.
  readonly property real liveFill: model ? model.liveFill : 0
  readonly property bool forecastShown: !!model && model.forecastShown
  readonly property real forecastFrom: forecastShown ? model.forecastFrom : 0
  readonly property real forecastTo: forecastShown ? model.forecastTo : 0
  // The stretch still ahead of the estimate: past it under Used, inside it under Remaining.
  readonly property real aheadFrom: remaining ? forecastFrom : liveFill
  readonly property real aheadTo: remaining ? liveFill : forecastTo
  readonly property bool aheadShown: forecastShown && aheadTo > aheadFrom
  readonly property real solidEnd: remaining && aheadShown ? aheadFrom : liveFill
  readonly property bool runsOut: !!model && model.runsOut
  readonly property bool tickShown: !!host && host.markShown && !!model && model.markValue >= 0
  readonly property real markValue: tickShown ? model.markValue : 0

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  // The gallery's lift: towards the theme's foreground (white on dark themes, dark on light ones).
  function lift(color, amount) { return Qt.tint(color, alpha(foreground, amount)) }

  implicitHeight: variant === "row" ? Style.space(6) : Style.space(10)

  // The head: a bright tick in a glow of two wider low-alpha bars (no blur) that swells with `glow`.
  component Head: Item {
    id: head
    property real glow: 0
    property real tickWidth: 2
    property color color: "transparent"
    property color glowColor: "transparent"

    Rectangle {
      anchors.centerIn: parent
      width: head.tickWidth + head.glow * 2
      height: parent.height + head.glow
      radius: width / 2
      color: Qt.rgba(head.glowColor.r, head.glowColor.g, head.glowColor.b, 0.12)
    }

    Rectangle {
      anchors.centerIn: parent
      width: head.tickWidth + head.glow
      height: parent.height + head.glow / 2
      radius: width / 2
      color: Qt.rgba(head.glowColor.r, head.glowColor.g, head.glowColor.b, 0.22)
    }

    Rectangle {
      objectName: "tickerHeadTick"
      anchors.centerIn: parent
      width: head.tickWidth
      height: parent.height
      color: head.color
    }
  }

  // Card: the 2 px line.
  Item {
    id: card
    visible: root.variant === "card" && !!root.model && root.model.hasMeter
    anchors.fill: parent
    readonly property int lineHeight: Style.space(2)
    readonly property real lineY: Math.round((height - lineHeight) / 2)
    readonly property real liveX: Math.round(width * root.liveFill)

    LiveClaim {
      motion: root.motion
      active: card.visible && root.moving
    }

    Rectangle {
      y: card.lineY
      width: parent.width
      height: card.lineHeight
      color: root.alpha(root.foreground, 0.12)
    }

    Rectangle {
      objectName: "tickerForecast"
      readonly property real fromX: Math.round(card.width * root.aheadFrom)
      visible: root.aheadShown
      x: fromX
      y: card.lineY
      width: Math.max(0, Math.round(card.width * root.aheadTo) - fromX)
      height: card.lineHeight
      color: root.runsOut ? root.alpha(root.urgent, 0.5) : root.alpha(root.tone, 0.28)
    }

    Rectangle {
      objectName: "tickerFill"
      y: card.lineY
      width: Math.round(card.width * root.solidEnd)
      height: card.lineHeight
      color: root.tone
    }

    Rectangle {
      objectName: "tickerPaceTick"
      visible: root.tickShown
      x: Math.round(card.width * root.markValue - width / 2)
      y: card.lineY - Style.space(3)
      width: Style.spaceReal(1.5)
      height: card.lineHeight + Style.space(6)
      color: root.alpha(root.foreground, 0.85)
    }

    Head {
      objectName: "tickerHead"
      visible: root.animating
      x: card.liveX - width / 2
      y: card.lineY - Style.space(2)
      width: Style.space(2)
      height: card.lineHeight + Style.space(4)
      tickWidth: Style.space(2)
      glow: Style.spaceReal(4 + 6 * root.beat)
      color: root.lift(root.tone, 0.85)
      glowColor: root.tone
    }
  }

  // Row: the 1.5 px line and, while spending, the head.
  Item {
    id: row
    visible: root.variant === "row" && !!root.model
    anchors.fill: parent
    readonly property real lineHeight: Style.spaceReal(1.5)
    readonly property real lineY: Math.round((height - lineHeight) / 2)

    LiveClaim {
      motion: root.motion
      active: row.visible && root.moving
    }

    Rectangle {
      y: row.lineY
      width: parent.width
      height: row.lineHeight
      color: root.alpha(root.foreground, 0.12)
    }

    Rectangle {
      objectName: "tickerRowFill"
      y: row.lineY
      width: Math.round(row.width * root.liveFill)
      height: row.lineHeight
      color: root.tone
    }

    Rectangle {
      visible: root.tickShown
      x: Math.round(row.width * root.markValue - width / 2)
      width: Style.spaceReal(1.5)
      height: row.height
      color: root.alpha(root.foreground, 0.85)
    }

    Head {
      visible: root.animating
      x: Math.round(row.width * root.liveFill) - width / 2
      y: Math.round((row.height - height) / 2)
      width: Style.space(2)
      height: Style.spaceReal(4.5)
      tickWidth: Style.space(2)
      glow: Style.spaceReal(2 + 3 * root.beat)
      color: root.lift(root.tone, 0.85)
      glowColor: root.tone
    }
  }
}
