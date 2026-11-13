pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import "UsageLogic.js" as UsageLogic

// The account's next dates in order (UsageLogic.comingUpItems): a banked reset that expires, the limit's
// reset with what it leaves over, and the subscription's end. Hidden when there is nothing to list.
Column {
  id: root

  property var account: null
  property real nowSeconds: 0
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family

  readonly property var items: UsageLogic.comingUpItems(root.account, root.nowSeconds)

  visible: items.length > 0
  spacing: Style.spacing.xs

  PlainText {
    objectName: "comingUpHeading"
    width: root.width
    text: "Coming up"
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Repeater {
    model: root.items

    PlainText {
      required property var modelData
      required property int index

      objectName: "comingUpItem-" + index
      width: root.width
      text: modelData.text
      color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.7)
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
  }
}
