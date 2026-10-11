pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons

// Limits/Costs switch, with the provider overview beneath it in Limits.
// Every provider is a visible tile with its current figure: one press selects it, nothing hides in a menu.
Column {
  id: root

  property string viewMode: "limits"
  property var viewOptions: []
  property var providerOptions: []
  property string providerId: ""
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family
  property real cardRadius: 0
  readonly property bool providerVisible: viewMode === "limits" && providerOptions.length > 1

  signal viewRequested(string value)
  signal providerRequested(string value)

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

  UsageTabs {
    id: viewTabs
    objectName: "usageViewTabs"
    width: parent.width
    options: root.viewOptions
    value: root.viewMode
    foreground: root.foreground
    fontFamily: root.fontFamily
    onChanged: function(value) { root.viewRequested(value) }
  }

  Rectangle {
    width: parent.width
    height: Style.spacing.hairline
    color: root.alpha(root.foreground, 0.14)
  }

  ProviderTiles {
    id: providerTiles
    objectName: "usageProviderTiles"
    visible: root.providerVisible
    width: parent.width
    topPadding: Style.spacing.xl
    options: root.providerOptions
    value: root.providerId
    foreground: root.foreground
    urgent: root.urgent
    fontFamily: root.fontFamily
    cardRadius: root.cardRadius
    onChanged: function(value) { root.providerRequested(value) }
  }
}
