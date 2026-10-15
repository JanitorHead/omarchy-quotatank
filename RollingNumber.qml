pragma ComponentBehavior: Bound

import QtQuick

// Stand-in for QmlBar's RollingNumber (same file name and API; the merge keeps QmlBar's): a figure
// whose changed digits roll, up when the value rises and down when it falls. Digits sit in slots
// counted from the right, so "$9.80" -> "$10.20" keeps the cents in place; a change in length slides
// the whole figure in from the direction of change instead.
Item {
  id: root

  property string text: ""
  property color color: "white"
  property font font: Qt.font({ family: "monospace", pixelSize: 12 })
  property var motion: null
  property int horizontalAlignment: Text.AlignLeft
  readonly property bool rolling: rollTimer.running

  property real lastValue: NaN
  property int direction: 0
  property int lastLength: 0

  implicitWidth: metrics.advanceWidth(text)
  implicitHeight: metrics.height
  Accessible.role: Accessible.StaticText
  Accessible.name: text

  function numericValue(value) {
    var cleaned = String(value).replace(/[^0-9.\-]/g, "")
    var number = parseFloat(cleaned)
    return isFinite(number) ? number : NaN
  }

  onTextChanged: {
    var value = numericValue(text)
    direction = isNaN(value) || isNaN(lastValue) || value === lastValue ? 0 : (value > lastValue ? 1 : -1)
    lastValue = value
    if (lastLength !== 0 && text.length !== lastLength && direction !== 0) {
      slideIn.stop()
      content.y = direction > 0 ? root.height * 0.45 : -root.height * 0.45
      content.opacity = 0
      slideIn.start()
    }
    lastLength = text.length
    rollTimer.restart()
  }
  Component.onCompleted: {
    lastValue = numericValue(text)
    lastLength = text.length
  }

  FontMetrics {
    id: metrics
    font: root.font
  }

  // Only reports `rolling`; nothing repeats.
  Timer {
    id: rollTimer
    interval: root.motion ? root.motion.duration(root.motion.digit) : 350
  }

  ParallelAnimation {
    id: slideIn
    YAnimator {
      target: content
      to: 0
      duration: root.motion ? root.motion.duration(root.motion.digit) : 350
      easing.type: Easing.OutCubic
    }
    OpacityAnimator {
      target: content
      to: 1
      duration: root.motion ? root.motion.duration(root.motion.digit) : 350
      easing.type: Easing.OutCubic
    }
  }

  Item {
    id: content
    width: root.implicitWidth
    height: root.height
    x: root.horizontalAlignment === Text.AlignRight ? root.width - width
      : root.horizontalAlignment === Text.AlignHCenter ? Math.round((root.width - width) / 2) : 0
    clip: true

    Repeater {
      model: root.text.length

      delegate: Item {
        id: slot
        required property int index
        // Slots count from the right so digits keep their place value across length changes.
        readonly property int position: root.text.length - 1 - index
        readonly property string character: position >= 0 ? root.text.charAt(position) : ""
        readonly property bool digit: character >= "0" && character <= "9"

        x: content.width - metrics.advanceWidth(root.text.substring(position))
        width: metrics.advanceWidth(character)
        height: content.height
        clip: digit

        Text {
          visible: !slot.digit
          text: slot.character
          color: root.color
          font: root.font
        }

        Column {
          id: wheel
          visible: slot.digit
          y: slot.digit ? -Number(slot.character) * metrics.height : 0

          Behavior on y {
            enabled: root.direction !== 0
            YAnimator {
              duration: root.motion ? root.motion.duration(root.motion.digit) : 350
              easing.type: Easing.OutCubic
            }
          }

          Repeater {
            model: 10
            delegate: Text {
              required property int index
              height: metrics.height
              text: String(index)
              color: root.color
              font: root.font
            }
          }
        }
      }
    }
  }
}
