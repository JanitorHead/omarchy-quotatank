pragma ComponentBehavior: Bound
import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui

// A settings text box that never lets the shell fetch clipboard text on its own. In Qt 6.11 and
// 6.12.0 an editable TextInput (what TextField is built on) pulls the whole clipboard text on every
// clipboard change, with no size or time limit, which a foreign clipboard owner can use to stall or
// exhaust the shared shell. A TextEdit does not, so plain fields edit natively in a single-line
// TextEdit (undo, input methods, selection). A TextEdit cannot mask, so secret fields keep a
// TextField that stays read-only, with typing applied here. Either way the clipboard is read only on
// an explicit paste (Ctrl+V, Shift+Insert), by `wl-paste` in a separate process, capped at 64 KiB
// and two seconds; middle-click and dropped text are refused. The input exists only while the field
// is on screen, and the typed text survives here when it is unloaded.
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
  readonly property alias pasting: clipboardReader.pending
  readonly property int pasteByteLimit: 65536
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

  function utf8Length(value) {
    return unescape(encodeURIComponent(value)).length
  }

  // Puts text in place of the selection, or at the cursor; false when it would pass maximumLength.
  // The secret input is read-only, so its text is rebuilt here; the plain one edits natively, which
  // keeps its undo history.
  function insertText(field, typed) {
    var start = field.selectionStart
    var end = field.selectionEnd
    if (root.text.length - (end - start) + typed.length > root.maximumLength) return false
    if (field.readOnly) {
      root.text = root.text.slice(0, start) + typed + root.text.slice(end)
      field.cursorPosition = start + typed.length
      root.textEdited()
    } else {
      if (end > start) field.remove(start, end)
      field.insert(start, typed)
    }
    return true
  }

  function erase(field, forward) {
    if (field.selectionStart !== field.selectionEnd) return insertText(field, "")
    var at = field.cursorPosition
    if (forward ? at >= root.text.length : at <= 0) return false
    field.select(forward ? at : at - 1, forward ? at + 1 : at)
    return insertText(field, "")
  }

  function paste(field) {
    if (clipboardReader.pending) return
    clipboardReader.pending = true
    clipboardReader.target = field
    clipboardReader.body = ""
    clipboardReader.tooLarge = false
    clipboardReader.running = true
  }

  function finishPaste() {
    var field = clipboardReader.target
    clipboardReader.target = null
    clipboardReader.pending = false
    if (!field || clipboardReader.tooLarge || clipboardReader.body === "") return
    insertText(field, clipboardReader.body.replace(/[\r\n]+/g, " "))
  }

  // Keys both inputs share: Enter finishes the edit, paste goes through the bounded reader. The
  // read-only secret input also takes its typing here; the plain one handles the rest itself.
  function handleKey(field, event) {
    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      root.accepted()
      root.editingFinished()
    } else if (event.matches(StandardKey.Paste)) {
      paste(field)
    } else if (!field.readOnly) {
      // A TextEdit would type a tab character; move along the focus chain like a text field.
      if (event.key !== Qt.Key_Tab && event.key !== Qt.Key_Backtab) return
      var next = field.nextInFocusChain(event.key === Qt.Key_Tab && !(event.modifiers & Qt.ShiftModifier))
      if (next) next.forceActiveFocus(event.key === Qt.Key_Tab ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    } else if (event.matches(StandardKey.Cut)) {
      // A masked field never copies its secret out.
      if (!root.password && field.selectionStart !== field.selectionEnd) {
        field.copy()
        insertText(field, "")
      }
    } else if (event.key === Qt.Key_Backspace) {
      erase(field, false)
    } else if (event.key === Qt.Key_Delete) {
      erase(field, true)
    } else if (event.text.length > 0 && event.text.charCodeAt(0) >= 0x20 && event.text.charCodeAt(0) !== 0x7f
        && (!(event.modifiers & Qt.ControlModifier) || (event.modifiers & Qt.AltModifier))) {
      insertText(field, event.text)
    } else {
      // Cursor movement, selection, Copy, and Tab stay with the input and the focus chain.
      return
    }
    event.accepted = true
  }

  Process {
    id: clipboardReader
    property var target: null
    property bool pending: false
    property string body: ""
    property bool tooLarge: false
    // Fixed command, no user input. `timeout` bounds the time and `head` the size; one byte over the
    // limit marks the paste as too large instead of silently cutting it.
    command: ["sh", "-c", "timeout -s KILL 2 wl-paste --no-newline --type text 2>/dev/null | head -c " + (root.pasteByteLimit + 1)]
    stdout: SplitParser {
      splitMarker: ""
      onRead: function(data) {
        if (clipboardReader.tooLarge) return
        if (root.utf8Length(clipboardReader.body) + root.utf8Length(data) > root.pasteByteLimit) {
          clipboardReader.tooLarge = true
          clipboardReader.body = ""
        } else {
          clipboardReader.body += data
        }
      }
    }
    stderr: SplitParser { splitMarker: "" }
    onRunningChanged: if (!running) root.finishPaste()
  }

  Loader {
    id: input
    anchors.fill: parent
    active: false
    focus: true
    sourceComponent: root.password ? secretInput : plainInput
  }

  Component {
    id: plainInput

    FocusScope {
      id: box
      readonly property alias readOnly: edit.readOnly
      readonly property var spec: Border.controlSpec(edit.activeFocus ? "focus" : hover.hovered ? "hover-cursor" : "normal", root.foreground, Color.accent)
      readonly property real padX: Style.spacing.controlPaddingX
      readonly property real padY: Style.spacing.inputPaddingY
      property real scrollX: 0
      objectName: root.objectName === "" ? "" : root.objectName + "Input"
      focus: true
      implicitWidth: Style.space(160)
      implicitHeight: Math.ceil(edit.implicitHeight) + padY * 2 + Border.top(spec) + Border.bottom(spec)

      Ui.BorderSurface {
        anchors.fill: parent
        color: Style.controlFill(edit.activeFocus, hover.hovered, root.foreground, Color.accent)
        borderSpec: box.spec
        radius: Style.space(6)
      }
      HoverHandler { id: hover; cursorShape: Qt.IBeamCursor }
      // Clicks in the padding still focus the text.
      MouseArea {
        anchors.fill: parent
        onPressed: edit.forceActiveFocus()
      }

      Item {
        id: viewport
        anchors.fill: parent
        anchors.leftMargin: box.padX + Border.left(box.spec)
        anchors.rightMargin: box.padX + Border.right(box.spec)
        clip: true

        Text {
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width
          visible: edit.text === "" && edit.preeditText === ""
          text: root.placeholderText
          color: Qt.darker(root.foreground, 1.6)
          font: root.font
          elide: Text.ElideRight
        }

        TextEdit {
          id: edit
          property bool syncing: false
          x: -box.scrollX
          anchors.verticalCenter: parent.verticalCenter
          width: Math.max(viewport.width, implicitWidth)
          focus: true
          activeFocusOnTab: true
          wrapMode: TextEdit.NoWrap
          textFormat: TextEdit.PlainText
          selectByMouse: root.selectByMouse
          persistentSelection: false
          inputMethodHints: root.inputMethodHints
          color: root.foreground
          selectionColor: Style.selectionFillFor(root.foreground, Color.accent)
          selectedTextColor: root.foreground
          font: root.font
          Accessible.name: root.Accessible.name
          // Text set from outside leaves the cursor at the end, as a text field does.
          function load(value) { syncing = true; text = value; cursorPosition = length; syncing = false }
          Component.onCompleted: load(root.text)
          onTextChanged: {
            if (syncing) return
            if (text.length > root.maximumLength) { remove(root.maximumLength, text.length); return }
            root.text = text
            root.textEdited()
          }
          // Keep the cursor in view as the line scrolls under it.
          onCursorRectangleChanged: {
            var x = cursorRectangle.x
            if (x - box.scrollX > viewport.width - cursorRectangle.width)
              box.scrollX = x - viewport.width + cursorRectangle.width
            else if (x < box.scrollX)
              box.scrollX = x
            box.scrollX = Math.max(0, Math.min(box.scrollX, contentWidth + cursorRectangle.width - viewport.width))
          }
          Keys.onPressed: function(event) { root.handleKey(box, event) }
          onEditingFinished: root.editingFinished()
        }
        // Middle-click would paste the primary selection, and a drop would insert foreign text, both
        // read in the shell without a limit: take them here and do nothing.
        MouseArea {
          anchors.fill: parent
          acceptedButtons: Qt.MiddleButton
          onPressed: edit.forceActiveFocus()
        }
        DropArea { anchors.fill: parent }
      }

      Connections {
        target: root
        function onTextChanged() { if (edit.text !== root.text) edit.load(root.text) }
      }

      // The shared key and paste helpers address this item like a text input.
      readonly property alias selectionStart: edit.selectionStart
      readonly property alias selectionEnd: edit.selectionEnd
      property alias cursorPosition: edit.cursorPosition
      function remove(start, end) { edit.remove(start, end) }
      function insert(position, value) { edit.insert(position, value) }
      function nextInFocusChain(forward) { return edit.nextItemInFocusChain(forward) }
    }
  }

  Component {
    id: secretInput

    Ui.TextField {
      id: field
      focus: true
      objectName: root.objectName === "" ? "" : root.objectName + "Input"
      readOnly: true
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
