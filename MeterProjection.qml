pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons

// Meter style "Projection" (the default). Card: the block meter, its forecast dashes and, while the account
// spends, a sweep from the fill's edge to where this pace takes the limit. Row: a thin bar where a bright
// tick makes the same run once per beat, leaving a faint trail; red when the limit runs out first.
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
    // The run, on the shared 30 Hz clock while a claim is held.
    readonly property bool running: visible && !!live && live.moving && live.start >= 0
      && !!root.host && !!root.host.motion && !root.host.motion.reduced
    readonly property real phase: running ? (root.host.motion.liveSeconds / live.period) % 1 : 0

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

    // The run: a faint trail behind a bright tick heading for the forecast's end.
    Item {
      id: run
      readonly property real from: rowBar.running ? Math.round(parent.width * rowBar.live.start) : 0
      readonly property real to: rowBar.running ? Math.round(parent.width * rowBar.live.end) : 0
      readonly property real head: from + (to - from) * rowBar.phase
      visible: rowBar.running
      anchors.fill: parent

      Rectangle {
        x: Math.min(run.from, run.head)
        width: Math.abs(run.head - run.from)
        height: parent.height
        color: root.host ? root.host.tone : "transparent"
        opacity: 0.3
      }

      Rectangle {
        objectName: "accountMeterRun"
        x: Math.round(run.head - width / 2)
        y: -Style.space(1)
        width: Style.space(2)
        height: parent.height + Style.space(2)
        color: !root.host ? "transparent" : rowBar.live && rowBar.live.runsOut ? root.host.urgent : Qt.lighter(root.host.tone, 1.4)
      }
    }
  }
}
