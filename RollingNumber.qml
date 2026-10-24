pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons

// Drop-in replacement for a value Text whose digits roll when the value changes (DESIGN §2.3). Each digit
// is a clipped 0–9 column moved on y; only digits that changed move, up when the value rises and down when
// it falls. A change of shape (95% → 3%, "—" → 72%) cannot roll digit by digit, so the new text slides in
// from the side the value moved to. Figures are tabular, so a rolling value never shifts what follows it.
// Reads font.family, font.pixelSize and font.weight; implicit size is the text's.
Item {
  id: root

  property string text: ""
  property color color: Commons.Color.foreground
  property font font
  property var motion: null
  property int horizontalAlignment: Text.AlignLeft
  // True while any digit rolls or the text slides in.
  readonly property bool rolling: activeAnimations > 0

  property int activeAnimations: 0
  // The text the cells show, split into digit cells and runs of other characters.
  property string shownText: ""
  property var cells: []
  property bool ready: false

  readonly property int pixelSize: root.font.pixelSize > 0 ? root.font.pixelSize : Style.font.body
  readonly property real lineHeight: Math.ceil(metrics.height)
  readonly property real digitWidth: {
    var widest = 0
    for (var digit = 0; digit < 10; digit++) widest = Math.max(widest, metrics.advanceWidth(String(digit)))
    return Math.ceil(widest)
  }
  readonly property string column: "0\n1\n2\n3\n4\n5\n6\n7\n8\n9\n0\n1\n2\n3\n4\n5\n6\n7\n8\n9"

  implicitWidth: cellRow.implicitWidth
  implicitHeight: lineHeight
  // Same font and line height as the cells, so baseline anchors line up with the drawn digits.
  baselineOffset: probe.baselineOffset
  clip: slide.running

  Accessible.role: Accessible.StaticText
  Accessible.name: text

  // Without Panel's Motion nothing animates: digits change in place, as with reduced motion.
  Behavior on color {
    ColorAnimation { duration: root.motion ? root.motion.duration(root.motion.micro) : 0 }
  }

  function rollDuration() {
    return root.motion ? root.motion.duration(root.motion.digit) : 0
  }

  function shapeOf(value) {
    var source = String(value)
    var result = []
    for (var i = 0; i < source.length; i++) {
      var character = source.charAt(i)
      var digit = character >= "0" && character <= "9"
      if (!digit && result.length > 0 && !result[result.length - 1].digit) result[result.length - 1].text += character
      else result.push({ digit: digit, text: character })
    }
    return result
  }

  function sameShape(left, right) {
    if (left.length !== right.length) return false
    for (var i = 0; i < left.length; i++)
      if (left[i].digit !== right[i].digit || (!left[i].digit && left[i].text !== right[i].text)) return false
    return true
  }

  // The first number in the text ("72%" → 72, "$1,234.50" → 1234.5); NaN when there is none.
  function numericValue(value) {
    var match = String(value).match(/-?\d[\d,]*(?:\.\d+)?/)
    return match ? Number(match[0].replace(/,/g, "")) : NaN
  }

  function directionOf(from, to) {
    var before = numericValue(from)
    var after = numericValue(to)
    if (!isFinite(before) || !isFinite(after) || before === after) return 0
    return after > before ? 1 : -1
  }

  // What the cells draw right now; equals `text` once nothing rolls.
  function renderedText() {
    var result = ""
    for (var i = 0; i < cells.length; i++) {
      var cell = cellRepeater.itemAt(i)
      if (cell) result += cell.shown()
    }
    return result
  }

  function update() {
    if (!ready || text === shownText) return
    var next = shapeOf(text)
    var direction = directionOf(shownText, text)
    var duration = rollDuration()
    if (sameShape(cells, next)) {
      for (var i = 0; i < next.length; i++) {
        if (!next[i].digit) continue
        var cell = cellRepeater.itemAt(i)
        if (cell) cell.rollTo(Number(next[i].text), direction, duration)
      }
    } else {
      for (var j = 0; j < cells.length; j++) {
        var old = cellRepeater.itemAt(j)
        if (old) old.stopRoll()
      }
      slide.stop()
      cellRow.y = 0
      cellRow.opacity = 1
      cells = next
      if (direction !== 0 && duration > 0) {
        slide.offset = Math.round(lineHeight * 0.6) * direction
        slide.duration = duration
        slide.restart()
      }
    }
    shownText = text
  }

  onTextChanged: update()
  Component.onCompleted: {
    cells = shapeOf(text)
    shownText = text
    ready = true
  }

  FontMetrics {
    id: metrics
    font.family: root.font.family
    font.pixelSize: root.pixelSize
    font.weight: root.font.weight
    font.features: ({ "tnum": 1 })
  }

  PlainText {
    id: probe
    visible: false
    text: "0"
    lineHeightMode: Text.FixedHeight
    lineHeight: root.lineHeight
    font.family: root.font.family
    font.pixelSize: root.pixelSize
    font.weight: root.font.weight
    font.features: ({ "tnum": 1 })
  }

  Row {
    id: cellRow
    x: root.horizontalAlignment === Text.AlignRight ? root.width - width
      : root.horizontalAlignment === Text.AlignHCenter ? Math.round((root.width - width) / 2) : 0

    Repeater {
      id: cellRepeater
      model: root.cells

      delegate: Item {
        id: cell
        required property var modelData
        required property int index
        readonly property bool isDigit: modelData.digit
        readonly property real pitch: root.lineHeight
        // The digit this column settles on.
        property int digit: isDigit ? Number(modelData.text) : 0

        width: isDigit ? root.digitWidth : runText.implicitWidth
        height: root.lineHeight
        clip: isDigit

        function snap() {
          if (isDigit) digitColumn.y = -digit * pitch
        }

        function shown() {
          if (!isDigit) return String(modelData.text)
          var position = pitch > 0 ? Math.round(-digitColumn.y / pitch) : digit
          return String(((position % 10) + 10) % 10)
        }

        function stopRoll() {
          if (roll.running) roll.stop()
        }

        // Rising rolls up through 9 → 0, falling rolls down through 0 → 9. The column repeats 0–9
        // twice, so moving by ten rows is invisible and keeps every roll inside it.
        function rollTo(target, direction, duration) {
          if (!isDigit) return
          if (roll.running) roll.stop()
          if (digitColumn.y < -9.5 * pitch) digitColumn.y += 10 * pitch
          var position = pitch > 0 ? -digitColumn.y / pitch : digit
          digit = target
          if (duration <= 0 || direction === 0 || pitch <= 0) {
            snap()
            return
          }
          var stop = target
          if (direction > 0 && target < position - 0.01) stop = target + 10
          if (direction < 0 && target > position + 0.01) digitColumn.y -= 10 * pitch
          if (Math.abs(-stop * pitch - digitColumn.y) < 0.5) {
            snap()
            return
          }
          roll.from = digitColumn.y
          roll.to = -stop * pitch
          roll.duration = duration
          roll.start()
        }

        onPitchChanged: snap()
        Component.onCompleted: snap()

        PlainText {
          id: digitColumn
          visible: cell.isDigit
          width: cell.width
          text: cell.isDigit ? root.column : ""
          color: root.color
          horizontalAlignment: Text.AlignHCenter
          lineHeightMode: Text.FixedHeight
          lineHeight: cell.pitch
          font.family: root.font.family
          font.pixelSize: root.pixelSize
          font.weight: root.font.weight
          font.features: ({ "tnum": 1 })
        }

        PlainText {
          id: runText
          visible: !cell.isDigit
          text: cell.isDigit ? "" : String(cell.modelData.text)
          color: root.color
          lineHeightMode: Text.FixedHeight
          lineHeight: cell.pitch
          font.family: root.font.family
          font.pixelSize: root.pixelSize
          font.weight: root.font.weight
          font.features: ({ "tnum": 1 })
        }

        YAnimator {
          id: roll
          target: digitColumn
          easing.type: root.motion ? root.motion.easeEnter : Easing.OutCubic
          onRunningChanged: {
            root.activeAnimations += running ? 1 : -1
            if (!running) cell.snap()
          }
        }
      }
    }
  }

  ParallelAnimation {
    id: slide
    property real offset: 0
    property int duration: 350

    YAnimator {
      target: cellRow
      from: slide.offset
      to: 0
      duration: slide.duration
      easing.type: root.motion ? root.motion.easeEnter : Easing.OutCubic
    }
    OpacityAnimator {
      target: cellRow
      from: 0
      to: 1
      duration: slide.duration
      easing.type: root.motion ? root.motion.easeEnter : Easing.OutCubic
    }
    onRunningChanged: root.activeAnimations += running ? 1 : -1
  }
}
