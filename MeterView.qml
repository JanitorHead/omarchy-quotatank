import QtQuick
import "UsageLogic.js" as UsageLogic

// Loads the meter of Display → Meter style (UsageLogic.METER_STYLES) for a card, a row or a group card.
// The host is the owning card or row; see MeterProjection.qml for the contract every style follows.
// A style chosen while the meter is on screen (Settings' preview arrows) fades in rather than cutting in.
Loader {
  id: root

  property var host: null
  property string variant: "card"
  property string styleId: "projection"
  readonly property var meterStyle: UsageLogic.meterStyle(styleId)
  property bool shownOnce: false

  source: "Meter" + meterStyle.file + ".qml"
  onLoaded: {
    item.host = Qt.binding(function() { return root.host })
    item.variant = Qt.binding(function() { return root.variant })
    var motion = root.host ? root.host.motion : null
    if (root.shownOnce && motion && !motion.reduced) {
      item.opacity = 0
      fadeIn.target = item
      fadeIn.duration = motion.row
      fadeIn.restart()
    }
    root.shownOnce = true
  }

  OpacityAnimator {
    id: fadeIn
    from: 0
    to: 1
    easing.type: Easing.OutCubic
  }
}
