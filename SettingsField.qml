pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui as Ui

// A settings text box whose editable input exists only while it is on screen. A live Qt text
// input follows the clipboard and reads what other applications offer, so hidden pages, collapsed
// sections, and the closed panel keep no input at all; the typed text survives here meanwhile.
FocusScope {
  id: root
  property string text: ""
  property string placeholderText: ""
  property int maximumLength: 32767
  property bool password: false
  property int inputMethodHints: Qt.ImhNone
  property bool selectByMouse: true
  property color foreground: Color.foreground
  property font font
  signal textEdited()
  signal editingFinished()
  signal accepted()

  implicitWidth: input.item ? input.item.implicitWidth : 0
  implicitHeight: input.item ? input.item.implicitHeight : 0

  // Hiding a focused input used to finish its edit through the focus loss; unloading it must too.
  onVisibleChanged: {
    if (!visible && input.item && input.item.activeFocus) root.editingFinished()
    input.active = visible
  }
  Component.onCompleted: input.active = visible

  Loader {
    id: input
    anchors.fill: parent
    active: false
    focus: true
    sourceComponent: Ui.TextField {
      id: field
      focus: true
      objectName: root.objectName === "" ? "" : root.objectName + "Input"
      text: root.text
      placeholderText: root.placeholderText
      maximumLength: root.maximumLength
      password: root.password
      inputMethodHints: root.inputMethodHints
      selectByMouse: root.selectByMouse
      foreground: root.foreground
      font: root.font
      Accessible.name: root.Accessible.name
      background: Ui.BorderSurface {
        color: Style.controlFill(field.activeFocus, field.hovered, field.foreground, field.accent)
        borderSpec: Border.controlSpec(field.activeFocus ? "focus" : field.hovered ? "hover-cursor" : "normal", field.foreground, field.accent)
        radius: Style.space(6)
      }
      onTextEdited: { root.text = text; root.textEdited() }
      onEditingFinished: root.editingFinished()
      onAccepted: root.accepted()
    }
  }
}
