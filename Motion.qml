import QtQuick
import qs.Commons

// Stand-in for the Motion helper QmlBar owns (same API): every duration goes through `duration()`,
// which is zero when motion is reduced. The panel owns one instance and passes it down.
QtObject {
  id: root

  // "system" follows the desktop; "reduced" turns every animation off.
  property string preference: "system"
  // The real helper re-reads Hyprland's animation setting whenever the panel opens.
  property bool panelOpen: false
  property bool reduced: preference === "reduced" || Style["reduceMotion"] === true

  readonly property int micro: 160
  readonly property int row: 260
  readonly property int morph: 420
  readonly property int digit: 350
  readonly property int popIn: 180
  readonly property int popOut: 120
  readonly property int flash: 600
  readonly property int ping: 700

  function duration(ms) {
    return reduced ? 0 : ms
  }
}
