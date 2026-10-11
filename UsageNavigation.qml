pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons

// Limits/Costs switch, with the provider row beneath it in Limits.
// Every provider is a visible text tab: one press selects it, nothing hides in a menu.
Column {
  id: root

  property string viewMode: "limits"
  property var viewOptions: []
  property var providerOptions: []
  property string providerId: ""
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
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

  UsageTabs {
    id: providerTabs
    objectName: "usageProviderTabs"
    visible: root.providerVisible
    width: parent.width
    options: root.providerOptions
    value: root.providerId
    foreground: root.foreground
    fontFamily: root.fontFamily
    onChanged: function(value) { root.providerRequested(value) }
  }

  Rectangle {
    width: parent.width
    height: Style.spacing.hairline
    color: root.alpha(root.foreground, 0.14)
  }
}
