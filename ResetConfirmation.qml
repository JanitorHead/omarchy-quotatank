pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

Column {
  id: root
  required property var backend
  property color foreground: Commons.Color.foreground
  property color background: Commons.Color.popups.background
  property string fontFamily: Style.font.family
  signal closeRequested()
  spacing: Style.spacing.lg
  focus: true
  Keys.onEscapePressed: function(event) { closeRequested(); event.accepted = true }

  function expiry(credit) {
    return credit.expiresAt === null ? "Does not expire"
      : "Expires " + new Date(credit.expiresAt * 1000).toLocaleString(Qt.locale(), Locale.ShortFormat)
  }
  function focusFirst() { cancelButton.forceActiveFocus() }

  PlainText {
    width: parent.width
    text: root.backend.state === "result" ? "Banked reset" : "Apply a banked reset?"
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
    font.bold: true
    wrapMode: Text.WordWrap
  }
  PlainText {
    width: parent.width
    text: root.backend.accountLabel + " · " + root.backend.planLabel
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WrapAnywhere
  }
  PlainText {
    width: parent.width
    visible: root.backend.state === "loading" || root.backend.state === "sending"
    text: root.backend.state === "loading" ? "Checking available resets…" : "Applying reset…"
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
  }
  PlainText {
    width: parent.width
    visible: root.backend.state === "ready"
    text: {
      var available = Number(root.backend.details.availableCount)
      var resets = available + " banked reset" + (available === 1 ? "" : "s")
      return root.backend.providerId === "claude"
        ? "Spends 1 of " + resets + " now; it cannot be undone. Claude spends the one it offers next."
        : "Use 1 of " + root.backend.details.availableCount + " available resets. The reset expiring soonest is selected first."
    }
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }
  Column {
    width: parent.width
    visible: root.backend.state === "ready"
    spacing: Style.spacing.md
    Repeater {
      model: root.backend.details.credits || []
      Column {
        id: option
        required property var modelData
        required property int index
        width: parent.width
        spacing: Style.spacing.sm
        Ui.Button {
          objectName: "resetCreditOption"
          text: option.modelData.title
          width: Math.min(implicitWidth, parent.width)
          bordered: true
          focusable: true
          selected: root.backend.selectedIndex === option.index
          foreground: root.foreground
          background: root.background
          fontFamily: root.fontFamily
          onClicked: root.backend.selectedIndex = option.index
        }
        PlainText {
          width: parent.width
          text: root.expiry(option.modelData) + "\n" + option.modelData.description
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }
    }
  }
  PlainText {
    width: parent.width
    visible: root.backend.message !== ""
    text: root.backend.message
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }
  Flow {
    width: parent.width
    spacing: Style.spacing.md
    Ui.Button {
      id: cancelButton
      objectName: "resetCancel"
      text: root.backend.state === "ready" || root.backend.state === "loading" ? "Cancel" : "Close"
      bordered: true
      focusable: true
      foreground: root.foreground
      background: root.background
      fontFamily: root.fontFamily
      onClicked: root.closeRequested()
    }
    Ui.Button {
      objectName: "resetApply"
      visible: root.backend.state === "ready" || root.backend.state === "uncertain"
      text: root.backend.state === "uncertain" ? "Retry same reset" : "Apply reset"
      enabled: !root.backend.busy
      bordered: true
      focusable: true
      foreground: root.foreground
      background: root.background
      fontFamily: root.fontFamily
      onClicked: root.backend.apply()
    }
  }
}
