pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// How long the accounts last until the binding short window resets, as lanes on one time axis from
// now (left) to the reset (right). One at a time, each account takes over where the previous one
// runs out; together, all run down side by side. A gap lane shows the time with nothing left.
Ui.BorderSurface {
  id: root

  // UsageLogic.accountRunway(); null hides the lanes.
  property var runway: null
  // Names by account index; a provider without accounts passes its own name at index 0.
  property var names: []
  property var counted: []
  property string poolText: ""
  property real nowSeconds: 0
  property string clockFormat: "HH:mm"
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family
  property real cardRadius: 0
  property var motion: null

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property var lanes: runway ? UsageLogic.listOrEmpty(runway.lanes) : []
  readonly property real horizon: runway ? Math.max(1, Number(runway.horizon)) : 1
  readonly property bool hasGap: !!runway && runway.gap > 0
  readonly property real laneHeight: Style.space(18)
  readonly property real barHeight: Style.space(7)
  readonly property real labelWidth: {
    var widest = labelMetrics.advanceWidth("Gap")
    for (var i = 0; i < lanes.length; i++) widest = Math.max(widest, labelMetrics.advanceWidth(nameOf(lanes[i].index)))
    return Math.min(Math.ceil(widest), Math.round(width * 0.3))
  }
  readonly property alias laneModel: laneRows

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

  function nameOf(index) {
    return String(names[index] || "")
  }

  function clock(epochSeconds) {
    var seconds = Number(epochSeconds)
    return Qt.formatDateTime(new Date(seconds * 1000), UsageLogic.clockPattern(seconds, nowSeconds, clockFormat))
  }

  function laneFor(key) {
    if (key === "gap") return hasGap
      ? { index: -1, kind: "gap", start: runway.gapStart, end: runway.horizon, startAt: nowSeconds + runway.gapStart, endAt: runway.resetsAt }
      : null
    for (var i = 0; i < lanes.length; i++)
      if ("account-" + lanes[i].index === key) return lanes[i]
    return null
  }

  function noteFor(lane) {
    if (!lane) return ""
    if (lane.kind === "gap") return UsageLogic.formatDuration(lane.end - lane.start) + " with nothing left"
    if (lane.kind === "runs") return "empty " + clock(lane.endAt)
    if (lane.kind === "lasts") return lane.idle === true || !(runway && runway.spending) ? "not being spent" : "lasts until reset"
    if (lane.kind === "takesover") return "takes over " + clock(lane.startAt)
    if (lane.kind === "notneeded") return "not needed"
    if (lane.kind === "usedup") return "used up"
    return "no reading"
  }

  readonly property string hint: {
    if (!runway) return ""
    if (runway.gap >= runway.horizon - 1) return lanes.length > 1 ? "Every account is used up until the reset." : ""
    if (!runway.spending) return lanes.length > 1 ? "Nothing is being spent: every account lasts until the reset." : ""
    if (runway.mode === "together") return "Used together: the accounts run down at the same time."
    if (lanes.length < 2) return ""
    var first = lanes[0]
    var next = lanes[1]
    if (first.kind === "lasts") return nameOf(first.index) + " lasts until the reset at this pace."
    if (next.kind === "takesover" || next.kind === "runs")
      return "One at a time: " + nameOf(next.index) + " takes over when " + nameOf(first.index) + " runs out."
    return ""
  }

  function sync() {
    var keys = []
    for (var i = 0; i < lanes.length; i++) keys.push("account-" + lanes[i].index)
    if (hasGap) keys.push("gap")
    UsageLogic.syncKeyedOrder({
      count: function() { return laneRows.count },
      keyAt: function(index) { return laneRows.get(index).laneKey },
      move: function(from, to) { laneRows.move(from, to, 1) },
      insert: function(index, value) { laneRows.insert(index, { laneKey: value }) }
    }, keys)
    while (laneRows.count > keys.length) laneRows.remove(laneRows.count - 1)
  }

  onRunwayChanged: Qt.callLater(sync)
  Component.onCompleted: sync()

  implicitHeight: runwayContent.implicitHeight + contentTopInset + contentBottomInset
  color: Style.normalFillFor(root.foreground, Commons.Color.accent, root.urgent)
  borderSpec: Border.controlSpec("normal", root.foreground, Commons.Color.accent, root.urgent)
  padding: Style.spacing.xxl
  radius: root.cardRadius

  Accessible.role: Accessible.StaticText
  Accessible.name: titleText.text + ", " + root.hint

  ListModel { id: laneRows }

  FontMetrics {
    id: labelMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.weight: Font.DemiBold
  }

  FontMetrics {
    id: noteMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Column {
    id: runwayContent
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.leftMargin: root.contentLeftInset
    anchors.rightMargin: root.contentRightInset
    anchors.topMargin: root.contentTopInset
    spacing: Style.spacing.lg

    Item {
      width: parent.width
      implicitHeight: Math.max(titleText.implicitHeight, resetClock.implicitHeight)

      PlainText {
        id: titleText
        objectName: "runwayTitle"
        anchors.left: parent.left
        anchors.right: resetClock.left
        anchors.rightMargin: Style.spacing.controlGap
        anchors.baseline: resetClock.baseline
        text: root.runway ? "Runway until the " + UsageLogic.windowPhrase(root.runway.window) + " reset" : "Runway"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }

      PlainText {
        id: resetClock
        anchors.right: parent.right
        text: root.runway ? root.clock(root.runway.resetsAt) : ""
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Item {
      id: laneArea
      objectName: "runwayLanes"
      readonly property real trackX: root.labelWidth + Style.spacing.lg
      readonly property real trackWidth: Math.max(1, width - trackX)
      width: parent.width
      height: laneColumn.height

      Column {
        id: laneColumn
        width: parent.width

        Repeater {
          model: laneRows

          Item {
            id: lane
            required property string laneKey
            required property int index
            readonly property var laneData: root.laneFor(laneKey)
            readonly property bool gap: laneKey === "gap"
            readonly property bool primary: !!laneData && (gap ? false : UsageLogic.contains(root.counted, laneData.index))
            readonly property string kind: laneData ? String(laneData.kind) : ""
            readonly property real startX: laneData ? Math.round(laneArea.trackWidth * Math.max(0, Math.min(1, laneData.start / root.horizon))) : 0
            // An account not being spent keeps its lane but draws no bar: only its note.
            readonly property real endX: !laneData || laneData.idle === true ? startX
              : Math.round(laneArea.trackWidth * Math.max(0, Math.min(1, laneData.end / root.horizon)))
            readonly property color barColor: gap ? root.alpha(root.urgent, 0.55)
              : primary ? root.foreground : Qt.darker(root.foreground, 1.35)
            readonly property string note: root.noteFor(laneData)
            readonly property real noteWidth: noteMetrics.advanceWidth(note)
            readonly property real noteGap: Style.spacing.sm
            readonly property real markWidth: kind === "usedup" ? Math.max(2, Style.space(2)) : 0
            // The note goes after the bar when it fits there, else before a bar that starts late. An account bar
            // that runs to the reset needs no note: reaching the dashed reset line already says it lasts. The
            // gap's note can sit on its own bar, which is translucent.
            readonly property string placement: endX + markWidth + noteGap + noteWidth <= laneArea.trackWidth ? "after"
              : startX >= noteWidth + noteGap * 2 ? "before"
              : gap && endX - startX >= noteWidth + Style.spacing.md * 2 ? "inside" : "none"
            readonly property real noteX: placement === "before" ? startX - noteGap - noteWidth
              : placement === "inside" ? endX - noteWidth - Style.spacing.md
              : Math.min(endX + markWidth + noteGap, Math.max(0, laneArea.trackWidth - noteWidth))

            objectName: "runwayLane-" + laneKey
            width: laneColumn.width
            height: root.laneHeight

            PlainText {
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              width: root.labelWidth
              text: lane.gap ? "Gap" : root.nameOf(lane.laneData ? lane.laneData.index : -1)
              color: lane.gap ? root.urgent : root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.weight: Font.DemiBold
              elide: Text.ElideRight
            }

            Item {
              id: track
              x: laneArea.trackX
              width: laneArea.trackWidth
              height: parent.height

              // Waiting its turn: the stretch before an account takes over, broken where its note sits.
              Rectangle {
                visible: !lane.gap && root.runway && root.runway.mode === "single" && lane.startX > 0
                  && (lane.kind === "runs" || lane.kind === "takesover")
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(0, lane.placement === "before" ? lane.noteX - lane.noteGap : lane.startX)
                height: Style.spacing.hairline
                color: root.alpha(root.foreground, 0.22)
              }

              Rectangle {
                id: bar
                objectName: "runwayBar"
                anchors.verticalCenter: parent.verticalCenter
                x: lane.startX
                width: Math.max(0, lane.endX - lane.startX)
                height: root.barHeight
                color: lane.barColor
                visible: width > 0

                Behavior on x {
                  XAnimator { duration: root.motion ? root.motion.duration(root.motion.morph) : 0; easing.type: Easing.InOutCubic }
                }
                Behavior on width {
                  NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.morph) : 0; easing.type: Easing.InOutCubic }
                }
              }

              // A used-up account: a short urgent mark where its turn would start.
              Rectangle {
                visible: lane.kind === "usedup"
                anchors.verticalCenter: parent.verticalCenter
                x: lane.startX
                width: lane.markWidth
                height: root.barHeight
                color: root.urgent
              }

              PlainText {
                objectName: "runwayNote"
                visible: lane.placement !== "none"
                anchors.verticalCenter: parent.verticalCenter
                x: lane.noteX
                text: lane.note
                color: lane.placement === "inside" ? root.foreground
                  : lane.gap || lane.kind === "usedup" || (lane.kind === "runs" && lane.primary) ? root.urgent : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }
          }
        }
      }

      // Now (left) and the reset (right) bound the time axis.
      Rectangle {
        x: laneArea.trackX - Math.round(width / 2)
        y: -Style.spacing.xs
        width: Math.max(1, Style.space(2))
        height: laneColumn.height + Style.spacing.xs * 2
        color: root.alpha(root.foreground, 0.7)
      }

      Column {
        x: laneArea.width - Style.spacing.hairline
        y: -Style.spacing.xs
        spacing: Style.space(2)

        Repeater {
          model: Math.max(1, Math.floor((laneColumn.height + Style.spacing.xs * 2) / Style.space(5)))

          Rectangle {
            width: Style.spacing.hairline
            height: Style.space(3)
            color: root.alpha(root.foreground, 0.45)
          }
        }
      }
    }

    Item {
      width: parent.width
      implicitHeight: nowLabel.implicitHeight

      PlainText {
        id: nowLabel
        x: laneArea.trackX - Math.round(implicitWidth / 2)
        text: "now"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      PlainText {
        anchors.right: parent.right
        text: "reset"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    PlainText {
      objectName: "runwayHint"
      visible: text !== ""
      width: parent.width
      text: root.hint
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }

    PlainText {
      objectName: "runwayPool"
      visible: text !== ""
      width: parent.width
      text: root.poolText
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
  }
}
