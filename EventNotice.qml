pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

// One persistent notice for something that just happened to an account (Omarchy switched it, a limit
// reset, omp lost a sign-in). It opens and closes by height and opacity, and keeps its text while
// closing so nothing jumps.
Item {
  id: root

  property string text: ""
  property bool shown: false
  property color foreground: Commons.Color.foreground
  property color accent: Commons.Color.accent
  property string fontFamily: Style.font.family
  property real cardRadius: 0
  property var motion: null
  property string lastText: ""

  signal dismissed()

  onTextChanged: if (text !== "") lastText = text
  Component.onCompleted: if (text !== "") lastText = text

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

  readonly property bool open: shown && lastText !== ""
  visible: height > 0.5
  implicitHeight: open ? card.implicitHeight : 0
  height: implicitHeight
  clip: true
  opacity: open ? 1 : 0

  Behavior on implicitHeight {
    NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
  }
  Behavior on opacity {
    OpacityAnimator { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
  }

  Accessible.role: Accessible.AlertMessage
  Accessible.name: root.lastText

  Ui.BorderSurface {
    id: card
    objectName: "eventNoticeCard"
    width: root.width
    implicitHeight: Math.max(noticeText.implicitHeight, dismiss.implicitHeight) + contentTopInset + contentBottomInset
    height: implicitHeight
    color: root.alpha(root.accent, 0.07)
    borderSpec: Border.flat(root.alpha(root.accent, 0.5), Style.spacing.hairline)
    radius: root.cardRadius
    leftPadding: Style.spacing.xl
    rightPadding: Style.spacing.xs
    topPadding: Style.spacing.md
    bottomPadding: Style.spacing.md

    PlainText {
      id: noticeText
      objectName: "eventNoticeText"
      anchors.left: parent.left
      anchors.right: dismiss.left
      anchors.top: parent.top
      anchors.leftMargin: card.contentLeftInset
      anchors.rightMargin: Style.spacing.sm
      anchors.topMargin: card.contentTopInset + Math.max(0, (dismiss.implicitHeight - implicitHeight) / 2)
      text: root.lastText
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
      lineHeight: 1.1
    }

    Ui.Button {
      id: dismiss
      objectName: "eventNoticeDismiss"
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.rightMargin: card.contentRightInset
      anchors.topMargin: card.contentTopInset
      text: "×"
      foreground: Qt.darker(root.foreground, 1.3)
      fontFamily: root.fontFamily
      fontSize: Style.font.body
      horizontalPadding: Style.spacing.md
      verticalPadding: Style.spacing.xxs
      tooltipText: "Dismiss"
      Accessible.name: "Dismiss notice"
      onClicked: root.dismissed()
    }
  }
}
