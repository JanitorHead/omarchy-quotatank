pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// One line that explains a part of the panel the first time it appears (UsageLogic.HINT_TEXT).
// "Got it" dismisses it for good; Settings → Advanced → Run setup again brings it back.
Item {
  id: root

  property string hintId: ""
  property bool shown: false
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family

  signal dismissed(string hintId)

  visible: shown
  implicitHeight: shown ? Math.max(hintText.implicitHeight, dismiss.implicitHeight) : 0
  height: implicitHeight

  Accessible.role: Accessible.StaticText
  Accessible.name: hintText.text

  PlainText {
    id: hintText
    objectName: "hintText"
    anchors.left: parent.left
    anchors.right: dismiss.left
    anchors.rightMargin: Style.spacing.md
    anchors.verticalCenter: parent.verticalCenter
    text: UsageLogic.HINT_TEXT[root.hintId] || ""
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.7)
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }

  Ui.Button {
    id: dismiss
    objectName: "hintDismiss"
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    text: "Got it"
    foreground: root.foreground
    fontFamily: root.fontFamily
    fontSize: Style.font.caption
    horizontalPadding: Style.spacing.sm
    verticalPadding: Style.spacing.xxs
    Accessible.name: "Dismiss this explanation"
    onClicked: root.dismissed(root.hintId)
  }
}
