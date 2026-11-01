import QtQuick
import "UsageLogic.js" as UsageLogic

// Loads the meter of Display → Meter style (UsageLogic.METER_STYLES) for a card, a row or a group card.
// The host is the owning card or row; see MeterProjection.qml for the contract every style follows.
Loader {
  id: root

  property var host: null
  property string variant: "card"
  property string styleId: "projection"
  readonly property var meterStyle: UsageLogic.meterStyle(styleId)

  source: "Meter" + meterStyle.file + ".qml"
  onLoaded: {
    item.host = Qt.binding(function() { return root.host })
    item.variant = Qt.binding(function() { return root.variant })
  }
}
