pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
// The OMP ROUTING block under the account rows: omp's next account and why, the share at which another account
// takes over, and one warning. The lines are accountState(...).routing: one {text, tooltip} or null per line.
// Three slots keep the height still and fill from the top, so the warning sits under the next account when there
// is no switch point. Each line is one line, elided, with its full text in a plain-text tooltip. Hidden when there
// is nothing to say: no omp account, or a proxy pool.
Column {
  id: root

  property var routing: null
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  readonly property var nextLine: routing ? routing.next : null
  readonly property var switchLine: routing ? routing.switchPoint : null
  readonly property var warningLine: routing ? routing.warning : null
  readonly property string switchTooltip: "Running sessions keep their account while active."

  // The lines that have something to say, in slot order: next, switch point, warning. Slots fill from the top.
  readonly property var entries: {
    var list = []
    if (nextLine) list.push({ text: nextLine.text, tooltip: nextLine.tooltip, dim: false })
    if (switchLine) list.push({ text: switchLine.text, tooltip: switchLine.tooltip + "\n" + switchTooltip, dim: true })
    if (warningLine) list.push({ text: warningLine.text, tooltip: warningLine.tooltip, dim: false })
    return list
  }

  visible: !!(nextLine || switchLine || warningLine)
  spacing: Style.spacing.xs

  PlainText {
    objectName: "ompRoutingHeading"
    width: root.width
    text: "OMP ROUTING"
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Repeater {
    // Slot i shows entries[i]; a blank slot keeps its height.
    model: 3

    PlainText {
      id: slot
      required property int index
      readonly property var line: slot.index < root.entries.length ? root.entries[slot.index] : null

      objectName: "ompRoutingLine-" + slot.index
      width: root.width
      text: slot.line ? slot.line.text : " "
      elide: Text.ElideRight
      maximumLineCount: 1
      color: slot.line && slot.line.dim ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.7) : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption

      HoverHandler {
        id: lineHover
      }

      Ui.PanelToolTip {
        objectName: "ompRoutingTooltip-" + slot.index
        visible: lineHover.hovered && !!slot.line
        text: slot.line ? slot.line.tooltip : ""
      }
    }
  }
}
