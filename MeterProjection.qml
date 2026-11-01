pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons

// Meter style "Projection" (the default). Card: the block meter and its forecast dashes; while the account
// spends, the block being filled breathes and a glow travels the dashes (BlockMeter.qml). Row: a thin bar
// with the forecast as a faint stretch after the fill; while spending, the fill's edge breathes and a soft
// glow travels the stretch, fading in and out at its ends; red when the limit runs out first.
//
// Every Meter*.qml follows one contract: `host` gives `model` (LimitModel; `models` for group styles),
// `motion`, `tone` (the fill colour, urgent at a threshold), `foreground`, `urgent`, `dim`, `markShown`
// (pace tick) and `fontFamily`; `variant` is "card", "row" or "group".
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property alias blocks: blockMeter

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

  implicitHeight: variant === "row" ? Style.space(3) : Style.space(12)

  BlockMeter {
    id: blockMeter
    objectName: "limitMeter"
    visible: root.variant === "card" && !!root.model && root.model.hasMeter
    anchors.fill: parent
    motion: root.host ? root.host.motion : null
    value: root.model ? root.model.fill : 0
    fillColor: root.host ? root.host.tone : "transparent"
    trackColor: root.host ? root.alpha(root.host.foreground, 0.14) : "transparent"
    markValue: root.model ? root.model.markValue : -1
    markShown: !!root.host && root.host.markShown
    markColor: root.host ? root.host.foreground : "transparent"
    forecastFrom: root.model ? root.model.forecastFrom : -1
    forecastTo: root.model ? root.model.forecastTo : -1
    forecastColor: !root.host ? "transparent"
      : root.model && root.model.runsOut ? root.alpha(root.host.urgent, 0.85) : root.alpha(root.host.foreground, 0.35)
    live: root.model ? root.model.live : null
    liveColor: fillColor
    highlightColor: Qt.lighter(fillColor, 1.45)
    urgentColor: root.host ? root.host.urgent : "transparent"
  }

  Item {
    id: rowBar
    visible: root.variant === "row" && !!root.model
    anchors.fill: parent
    readonly property var live: root.model ? root.model.live : null
    // On the shared 30 Hz clock while a claim is held: one pass of the glow a beat (1.1 to 2.6 s), then
    // half a second of rest.
    readonly property bool running: visible && !!live && live.moving && live.start >= 0
      && !!root.host && !!root.host.motion && !root.host.motion.reduced
    readonly property real seconds: running ? root.host.motion.liveSeconds : 0
    readonly property real passTime: running ? Math.max(1.1, Math.min(2.6, live.period)) : 1
    readonly property real passPhase: running ? seconds % (passTime + 0.5) : 0
    readonly property real breath: running ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((seconds / live.period) % 1)) : 0

    LiveClaim {
      motion: root.host ? root.host.motion : null
      active: rowBar.visible && !!rowBar.live && rowBar.live.moving && rowBar.live.start >= 0
    }

    Rectangle {
      anchors.fill: parent
      color: root.host ? root.alpha(root.host.foreground, 0.14) : "transparent"
    }

    Rectangle {
      width: Math.round(parent.width * (root.model ? root.model.fill : 0))
      height: parent.height
      color: root.host ? root.host.tone : "transparent"

      Behavior on width {
        NumberAnimation { duration: root.host && root.host.motion ? root.host.motion.duration(root.host.motion.row) : 0; easing.type: Easing.OutCubic }
      }
    }

    // The forecast: where this pace takes the limit by its reset, a faint stretch after the fill.
    Item {
      id: run
      readonly property real from: rowBar.running ? Math.round(parent.width * rowBar.live.start) : 0
      readonly property real to: rowBar.running ? Math.round(parent.width * rowBar.live.end) : 0
      readonly property color ink: !root.host ? "transparent"
        : rowBar.live && rowBar.live.runsOut ? root.host.urgent : Qt.lighter(root.host.tone, 1.4)
      // The glow's centre runs from a little before the edge to a little past the end.
      readonly property real reach: Math.abs(to - from)
      readonly property real spread: Math.max(Style.space(6), reach * 0.18)
      readonly property real centre: rowBar.passPhase < rowBar.passTime
        ? from + Math.sign(to - from) * (-spread + (reach + 2 * spread) * rowBar.passPhase / rowBar.passTime) : -10000
      visible: rowBar.running
      anchors.fill: parent

      Rectangle {
        x: Math.min(run.from, run.to)
        width: run.reach
        height: parent.height
        color: run.ink
        opacity: 0.25
      }

      Item {
        x: Math.min(run.from, run.to)
        width: run.reach
        height: parent.height
        clip: true

        Rectangle {
          objectName: "accountMeterRun"
          x: run.centre - run.spread - parent.x
          width: 2 * run.spread
          height: parent.height
          gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Qt.rgba(run.ink.r, run.ink.g, run.ink.b, 0) }
            GradientStop { position: 0.5; color: Qt.rgba(run.ink.r, run.ink.g, run.ink.b, 0.9) }
            GradientStop { position: 1; color: Qt.rgba(run.ink.r, run.ink.g, run.ink.b, 0) }
          }
        }
      }

      // The edge being spent breathes on the beat.
      Rectangle {
        objectName: "accountMeterEdge"
        x: run.from - (rowBar.live && rowBar.live.end < rowBar.live.start ? width : 0)
        y: -Style.space(1)
        width: Style.space(2)
        height: parent.height + Style.space(2)
        color: Qt.lighter(root.host ? root.host.tone : "transparent", 1.4)
        opacity: 0.35 + 0.6 * rowBar.breath
      }
    }
  }
}
