pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// Settings → Display: the chosen meter style, live, on made-up limits of an account that is spending: a
// 5-hour limit that runs out before its reset and a weekly one that lasts, as a card (or the group card) and
// as an account row. It sits in its own frame, labelled as a preview, with arrows that step through the styles.
Rectangle {
  id: root

  property string styleId: "projection"
  property string quotaMode: "Used"
  property bool liveFigure: false
  property var motion: null
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property color providerColor: foreground
  property string fontFamily: Style.font.family
  property real cardRadius: 0

  // The arrows ask for the previous or next style; the form saves it and the preview follows.
  signal styleRequested(string id)

  readonly property int styleIndex: {
    for (var i = 0; i < UsageLogic.METER_STYLES.length; i++) if (UsageLogic.METER_STYLES[i].id === styleId) return i
    return 0
  }
  function step(by) {
    var count = UsageLogic.METER_STYLES.length
    root.styleRequested(UsageLogic.METER_STYLES[(styleIndex + by + count) % count].id)
  }

  readonly property bool group: UsageLogic.meterStyle(styleId).layout === "group"
  // The made-up readings are taken when the preview opens; the clock runs on so live figures climb.
  readonly property real start: Date.now() / 1000
  property real nowSeconds: start

  function rising(id, label, used, ratePerSecond, burstSeconds, resetsIn, windowSeconds) {
    var samples = []
    var windowStart = root.start + resetsIn - windowSeconds
    var base = used - ratePerSecond * burstSeconds
    for (var t = windowStart; t < root.start; t += 300) {
      var v = t >= root.start - burstSeconds ? base + ratePerSecond * (t - (root.start - burstSeconds))
        : base * (t - windowStart) / Math.max(1, root.start - burstSeconds - windowStart)
      samples.push([t, Math.max(0, Math.min(100, v))])
    }
    samples.push([root.start, used])
    return { id: id, label: label, used: used, remaining: 100 - used, windowSeconds: windowSeconds,
      resetsAt: root.start + resetsIn, samples: samples }
  }

  readonly property var windows: [
    rising("session", "5-hour limit", 72, 0.0062, 3000, 2 * 3600 + 4 * 60, 18000),
    rising("weekly", "Weekly limit", 31, 0.00004, 86400, 3 * 86400 + 3 * 3600, 604800)
  ]

  function severity(row) {
    var left = 100 - row.used
    return left <= 10 ? "critical" : left <= 25 ? "warning" : "none"
  }

  function resetText(row) {
    var left = Math.max(0, row.resetsAt - root.nowSeconds)
    var hours = Math.floor(left / 3600)
    var days = Math.floor(hours / 24)
    return "Resets in " + (days > 0 ? days + "d " + (hours % 24) + "h" : hours + "h " + Math.floor(left % 3600 / 60) + "m")
  }

  readonly property real pad: Style.spacing.lg
  implicitHeight: content.implicitHeight + 2 * pad
  radius: cardRadius
  color: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.035)
  border.width: Style.spacing.hairline
  border.color: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.16)

  Timer {
    interval: 1000
    repeat: true
    running: root.visible
    onTriggered: root.nowSeconds = Date.now() / 1000
  }

  Column {
    id: content
    x: root.pad
    y: root.pad
    width: root.width - 2 * root.pad
    spacing: Style.spacing.lg

    // "PREVIEW" and what it shows on the left; the arrows and the style's place in the list on the right.
    Item {
      width: content.width
      height: Math.max(badge.height, stepper.height)

      Row {
        anchors.left: parent.left
        anchors.right: stepper.left
        anchors.rightMargin: Style.spacing.controlGap
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.spacing.md

        Rectangle {
          id: badge
          anchors.verticalCenter: parent.verticalCenter
          width: badgeText.implicitWidth + Style.space(12)
          height: badgeText.implicitHeight + Style.space(4)
          radius: height / 2
          color: Qt.rgba(Commons.Color.accent.r, Commons.Color.accent.g, Commons.Color.accent.b, 0.18)

          PlainText {
            id: badgeText
            anchors.centerIn: parent
            text: "PREVIEW"
            color: Commons.Color.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: Style.spaceReal(1.2)
          }
        }

        PlainText {
          anchors.verticalCenter: parent.verticalCenter
          width: Math.max(0, parent.width - badge.width - parent.spacing)
          text: "Sample account, spending now"
          color: Qt.darker(root.foreground, 1.55)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      Row {
        id: stepper
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.spacing.xs

        Ui.Button {
          objectName: "meterStylePrevious"
          anchors.verticalCenter: parent.verticalCenter
          text: "‹"
          tooltipText: "Previous style"
          foreground: root.foreground
          fontFamily: root.fontFamily
          focusable: true
          onClicked: root.step(-1)
        }

        PlainText {
          anchors.verticalCenter: parent.verticalCenter
          text: (root.styleIndex + 1) + " / " + UsageLogic.METER_STYLES.length
          color: Qt.darker(root.foreground, 1.55)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Ui.Button {
          objectName: "meterStyleNext"
          anchors.verticalCenter: parent.verticalCenter
          text: "›"
          tooltipText: "Next style"
          foreground: root.foreground
          fontFamily: root.fontFamily
          focusable: true
          onClicked: root.step(1)
        }
      }
    }

    Repeater {
      model: root.group ? 0 : root.windows.length

      LimitCard {
        required property int index
        readonly property var row: root.windows[index]
        objectName: "meterPreviewCard-" + index
        width: content.width
        window: row
        severity: root.severity(row)
        resetLabel: root.resetText(row)
        quotaMode: root.quotaMode
        foreground: root.foreground
        urgent: root.urgent
        providerColor: root.providerColor
        fontFamily: root.fontFamily
        cardRadius: root.cardRadius
        nowSeconds: root.nowSeconds
        motion: root.motion
        spending: true
        readingAt: root.start
        liveFigure: root.liveFigure
        meterStyle: root.styleId
      }
    }

    LimitGroupCard {
      objectName: "meterPreviewGroup"
      visible: root.group
      width: content.width
      windows: root.group ? root.windows : []
      quotaMode: root.quotaMode
      foreground: root.foreground
      urgent: root.urgent
      providerColor: root.providerColor
      fontFamily: root.fontFamily
      cardRadius: root.cardRadius
      nowSeconds: root.nowSeconds
      motion: root.motion
      spending: true
      readingAt: root.start
      liveFigure: root.liveFigure
      meterStyle: root.styleId
      severityOf: function(row) { return root.severity(row) }
      resetLabelOf: function(row) { return root.resetText(row) }
    }

    // The same account as a row in the Limits list.
    Item {
      width: content.width
      height: previewRow.implicitHeight

      PlainText {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: "In the account list"
        color: Qt.darker(root.foreground, 1.55)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      AccountMeters {
        id: previewRow
        objectName: "meterPreviewRow"
        anchors.right: parent.right
        width: Style.space(112)
        account: ({ windows: root.windows })
        quotaMode: root.quotaMode
        spending: true
        nowSeconds: root.nowSeconds
        meterStyle: root.styleId
        foreground: root.foreground
        urgent: root.urgent
        fontFamily: root.fontFamily
        motion: root.motion
      }
    }
  }
}
