pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as Controls
import qs.Commons
import qs.Commons as Commons

Controls.TabBar {
  id: root

  property var options: []
  property string value: ""
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.bodySmall
  property var motion: null
  signal changed(string value)

  // The indicator only slides once the tabs have been laid out, so opening the panel draws it in place.
  property bool settled: false
  Component.onCompleted: Qt.callLater(function() { root.settled = true })

  implicitHeight: Style.spacing.controlHeight + Style.spacing.sm
  spacing: Style.spacing.md
  currentIndex: {
    for (var i = 0; i < options.length; i++)
      if (options[i].value === value) return i
    return -1
  }
  // One accent indicator that slides to the chosen tab.
  background: Item {
    Rectangle {
      visible: root.currentItem !== null
      x: (root.contentItem ? root.contentItem.x - (Number(root.contentItem.contentX) || 0) : 0)
        + (root.currentItem ? root.currentItem.x : 0)
      width: root.currentItem ? root.currentItem.width : 0
      anchors.bottom: parent.bottom
      height: Style.space(2)
      color: Commons.Color.accent

      Behavior on x {
        enabled: root.settled
        XAnimator {
          duration: root.motion ? root.motion.duration(root.motion.row) : 0
          easing.type: Easing.InOutCubic
        }
      }
      Behavior on width {
        enabled: root.settled
        NumberAnimation {
          duration: root.motion ? root.motion.duration(root.motion.row) : 0
          easing.type: Easing.InOutCubic
        }
      }
    }
  }
  onCurrentIndexChanged: {
    if (currentIndex >= 0 && currentIndex < options.length
        && options.some(function(option) { return option.value === root.value })
        && options[currentIndex].value !== value)
      changed(options[currentIndex].value)
  }

  Repeater {
    model: root.options

    Controls.TabButton {
      id: viewTab
      required property var modelData
      text: modelData.label
      width: implicitWidth
      height: root.height
      implicitHeight: root.height
      leftPadding: Style.spacing.md
      rightPadding: Style.spacing.md
      topPadding: Style.spacing.sm
      bottomPadding: Style.spacing.md
      Accessible.name: text

      contentItem: PlainText {
        text: viewTab.text
        color: viewTab.checked ? Commons.Color.accent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: root.fontSize
        // Reserve bold label widths so changing tabs doesn't move controls.
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter

        Behavior on color {
          ColorAnimation { duration: root.motion ? root.motion.duration(root.motion.micro) : 0 }
        }
      }

      background: Rectangle {
        color: viewTab.hovered || viewTab.visualFocus
          ? Style.hoverFillFor(root.foreground, Commons.Color.accent) : "transparent"
        border.width: viewTab.visualFocus ? Style.spacing.hairline : 0
        border.color: Commons.Color.accent
      }
    }
  }
}
