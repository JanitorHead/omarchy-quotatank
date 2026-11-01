import QtQuick
import qs.Commons

// A limit's live rate as a small chip: a dot that beats with the meter while the account spends and the
// rate ("24%/h"), or "idle", "quiet", "used up". Red when the limit runs out before its reset.
Item {
  id: root

  property var model: null
  property var motion: null
  property color foreground: "white"
  property color accent: foreground
  property color urgent: "red"
  property string fontFamily: Style.font.family

  readonly property bool moving: !!model && model.moving
  readonly property color tone: !model ? foreground : model.exhausted || model.runsOut ? urgent : moving ? accent : Qt.darker(foreground, 1.55)
  readonly property bool beating: moving && !!motion && !motion.reduced
  readonly property real beat: beating ? 0.5 - 0.5 * Math.cos(2 * Math.PI * ((motion.liveSeconds / model.period) % 1)) : 1

  implicitWidth: dot.width + Style.spacing.sm + label.implicitWidth
  implicitHeight: label.implicitHeight

  LiveClaim {
    motion: root.motion
    active: root.moving && root.visible
  }

  Rectangle {
    id: dot
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(6)
    height: width
    radius: width / 2
    color: root.tone
    opacity: root.moving ? 0.4 + 0.6 * root.beat : 0.6
  }

  PlainText {
    id: label
    objectName: "rateChip"
    anchors.left: dot.right
    anchors.leftMargin: Style.spacing.sm
    anchors.verticalCenter: parent.verticalCenter
    color: root.tone
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: root.moving
    text: root.model ? root.model.rateText : ""
  }
}
