pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui as Ui

// A settings text box that never follows the clipboard. An editable Qt text input reads every
// text another application copies (to update canPaste), even unfocused, while a read-only one
// does not. So the input stays read-only and this component applies the typing itself; the
// clipboard is read only on an explicit paste (Ctrl+V or Shift+Insert). The input also exists
// only while the field is on screen, and the typed text survives here when it is unloaded.
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

  // Replaces the selection (or inserts at the cursor) and reports the edit; false when the result
  // would pass maximumLength.
  function replaceSelection(field, typed) {
    var start = field.selectionStart
    var end = field.selectionEnd
    var next = root.text.slice(0, start) + typed + root.text.slice(end)
    if (next.length > root.maximumLength) return false
    root.text = next
    field.cursorPosition = start + typed.length
    root.textEdited()
    return true
  }

  function erase(field, forward) {
    if (field.selectionStart !== field.selectionEnd) return replaceSelection(field, "")
    var at = field.cursorPosition
    if (forward ? at >= root.text.length : at <= 0) return false
    field.select(forward ? at : at - 1, forward ? at + 1 : at)
    return replaceSelection(field, "")
  }

  function paste(field) {
    field.pasting = true
    field.paste()
    field.pasting = false
    if (field.text !== root.text) {
      root.text = field.text
      root.textEdited()
    }
  }

  function handleKey(field, event) {
    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      root.accepted()
      root.editingFinished()
    } else if (event.matches(StandardKey.Paste)) {
      paste(field)
    } else if (event.matches(StandardKey.Cut)) {
      if (field.selectionStart !== field.selectionEnd && !root.password) {
        field.copy()
        replaceSelection(field, "")
      }
    } else if (event.key === Qt.Key_Backspace) {
      erase(field, false)
    } else if (event.key === Qt.Key_Delete) {
      erase(field, true)
    } else if (event.text.length > 0 && event.text.charCodeAt(0) >= 0x20 && event.text.charCodeAt(0) !== 0x7f
        && (!(event.modifiers & Qt.ControlModifier) || (event.modifiers & Qt.AltModifier))) {
      replaceSelection(field, event.text)
    } else {
      // Cursor movement, selection, Copy, and Tab stay with the input and the focus chain.
      return
    }
    event.accepted = true
  }

  Loader {
    id: input
    anchors.fill: parent
    active: false
    focus: true
    sourceComponent: Ui.TextField {
      id: field
      property bool pasting: false
      focus: true
      objectName: root.objectName === "" ? "" : root.objectName + "Input"
      readOnly: !pasting
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
      // A read-only input draws no cursor of its own, and this one is edited: draw it here. Qt
      // creates the delegate once cursorVisible turns on, which a read-only input never does itself.
      onActiveFocusChanged: cursorVisible = activeFocus
      onReadOnlyChanged: cursorVisible = activeFocus
      cursorDelegate: Rectangle {
        id: caret
        property bool blinkOn: true
        width: Math.max(1, Math.round(field.font.pixelSize / 12))
        color: field.foreground
        visible: field.activeFocus && blinkOn
        Timer {
          running: field.activeFocus
          interval: 530
          repeat: true
          onTriggered: caret.blinkOn = !caret.blinkOn
          onRunningChanged: caret.blinkOn = true
        }
        Connections {
          target: field
          function onCursorPositionChanged() { caret.blinkOn = true }
        }
      }
      Keys.onPressed: function(event) { root.handleKey(field, event) }
      onEditingFinished: root.editingFinished()
    }
  }
}
