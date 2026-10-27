pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons

// The account dots and hint of a menu bar chip (DESIGN §2.1–2.2), drawn from UsageLogic.barAccountStrip().
// A filled dot is an account the chip counts; a hollow ring is another account, coloured by its state;
// a dashed ring is an account that failed (or every ring while the reading is stale). Five or more
// accounts show three dots and "+N". Once every account is used up the dots become one clock pie that
// fills towards the earliest reset, and the hint names the time left. Shapes, not colour alone, carry
// every state.
Item {
  id: root

  property var strip: null
  property string mode: "single"
  property bool stale: false
  property var motion: null
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property color accent: Commons.Color.accent
  property color dim: Qt.darker(foreground, 1.55)
  property string fontFamily: Style.font.family
  property int fontSize: Style.font.bodySmall

  readonly property var dots: strip && strip.dots ? strip.dots : []
  readonly property int dotCount: dots.length
  readonly property int extra: strip ? Number(strip.extra) || 0 : 0
  readonly property bool allUsedUp: !!(strip && strip.allUsedUp)
  readonly property real pieFraction: strip ? Number(strip.pieFraction) : -1
  readonly property string hintKind: strip ? String(strip.hintKind || "") : ""
  readonly property string hint: strip ? String(strip.hint || "") : ""
  // A switch suggestion from an old reading could point the wrong way; the reset countdown still holds.
  readonly property bool hintShown: hint !== "" && !(stale && hintKind === "switch")
  // The hint keeps its last words while it closes, so it does not empty out mid-slide.
  property string shownHint: ""
  property string shownHintKind: ""
  onHintChanged: if (hint !== "") { shownHint = hint; shownHintKind = hintKind }
  onHintKindChanged: if (hint !== "") shownHintKind = hintKind
  Component.onCompleted: { shownHint = hint; shownHintKind = hintKind }

  readonly property int diameter: Style.space(5)
  readonly property int gap: Style.space(3)
  readonly property int pitch: diameter + gap
  readonly property int ringWidth: Math.max(1, Style.space(1))
  readonly property int pieDiameter: diameter + Style.space(2)
  readonly property int haloDiameter: Style.space(11)
  readonly property int dotsWidth: dotCount > 0 ? dotCount * diameter + (dotCount - 1) * gap : 0
  readonly property int countedSlot: {
    for (var i = 0; i < dots.length; i++) if (dots[i].counted) return i
    return -1
  }
  // Last ring per account, so a reading taken every few seconds cannot fire a ring each time.
  property var lastPingAt: ({})

  implicitWidth: content.implicitWidth
  implicitHeight: Math.max(pieDiameter, hintLabel.implicitHeight)

  // Without Panel's Motion nothing animates, as with reduced motion.
  function duration(token) {
    return motion ? motion.duration(token) : 0
  }

  function stateColor(state) {
    if (stale) return dim
    if (state === "critical") return urgent
    if (state === "warning") return Qt.rgba(urgent.r, urgent.g, urgent.b, 0.7)
    if (state === "error") return dim
    if (state === "unknown") return Qt.rgba(foreground.r, foreground.g, foreground.b, 0.3)
    return Qt.rgba(foreground.r, foreground.g, foreground.b, 0.55)
  }

  function fillColor(state) {
    if (state === "critical" || state === "warning") return urgent
    if (state === "error" || state === "unknown") return dim
    return foreground
  }

  // One ring from the dot of `accountIndex` (or the counted dot when that account has none) for one live
  // request: at most every three seconds per account, never in reduced motion, on stale data, or once
  // everything is used up, because then nothing can be spending.
  function ping(accountIndex) {
    if (stale || allUsedUp || dotCount === 0 || (motion && motion.reduced)) return false
    var slot = -1
    for (var i = 0; i < dots.length; i++) if (dots[i].index === accountIndex) slot = i
    if (slot < 0) slot = countedSlot
    if (slot < 0) return false
    var key = String(dots[slot].index)
    var now = Date.now()
    if (lastPingAt[key] !== undefined && now - lastPingAt[key] < 3000) return false
    var stamps = Object.assign({}, lastPingAt)
    stamps[key] = now
    lastPingAt = stamps
    var item = slotRepeater.itemAt(slot)
    if (item) item.ring()
    return !!item
  }

  Row {
    id: content
    height: root.height
    anchors.verticalCenter: parent.verticalCenter

    Item {
      id: dotsArea
      objectName: "accountDotsArea"
      width: root.allUsedUp ? root.pieDiameter : root.dotsWidth
      height: root.height

      Item {
        id: dotLayer
        anchors.fill: parent
        opacity: root.allUsedUp ? 0 : 1

        Behavior on opacity {
          OpacityAnimator { duration: root.duration(root.motion ? root.motion.row : 0); easing.type: Easing.InOutCubic }
        }

        // Soft accent glow behind each counted dot whose account is spending, under every ring.
        Repeater {
          id: haloRepeater
          model: root.dotCount

          delegate: Shape {
            id: halo
            required property int index
            readonly property var info: root.dots[index] || null
            readonly property bool shown: !!info && !!info.counted && !!info.spending && !root.stale

            objectName: "accountHalo-" + index
            x: index * root.pitch + Math.round((root.diameter - root.haloDiameter) / 2)
            y: Math.round((root.height - root.haloDiameter) / 2)
            width: root.haloDiameter
            height: root.haloDiameter
            preferredRendererType: Shape.CurveRenderer
            opacity: shown ? 1 : 0

            Behavior on opacity {
              OpacityAnimator { duration: root.duration(root.motion ? root.motion.row : 0); easing.type: Easing.InOutCubic }
            }

            ShapePath {
              strokeWidth: -1
              fillGradient: RadialGradient {
                centerX: root.haloDiameter / 2
                centerY: root.haloDiameter / 2
                centerRadius: root.haloDiameter / 2
                focalX: root.haloDiameter / 2
                focalY: root.haloDiameter / 2
                GradientStop { position: 0.0; color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.34) }
                GradientStop { position: 0.55; color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.22) }
                GradientStop { position: 1.0; color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0) }
              }
              PathAngleArc {
                centerX: root.haloDiameter / 2
                centerY: root.haloDiameter / 2
                radiusX: root.haloDiameter / 2
                radiusY: root.haloDiameter / 2
                startAngle: 0
                sweepAngle: 360
              }
            }
          }
        }

        Repeater {
          id: slotRepeater
          model: root.dotCount

          delegate: Item {
            id: slot
            required property int index
            readonly property var info: root.dots[index] || ({ index: -1, state: "unknown", counted: false, spending: false })
            readonly property string dotState: String(info.state)
            readonly property bool counted: !!info.counted
            readonly property bool filled: counted && !root.stale
            readonly property bool dashed: root.stale || dotState === "error"

            objectName: "accountDot-" + index
            x: index * root.pitch
            y: Math.round((root.height - root.diameter) / 2)
            width: root.diameter
            height: root.diameter

            function ring() {
              pingAnimation.restart()
            }
            Rectangle {
              id: solidRing
              anchors.fill: parent
              visible: !slot.dashed
              radius: width / 2
              color: "transparent"
              antialiasing: true
              border.width: root.ringWidth
              border.color: root.stateColor(slot.dotState)

              Behavior on border.color {
                ColorAnimation { duration: root.duration(root.motion ? root.motion.micro : 0) }
              }
            }

            // Six short arcs: a dashed ring that still reads at five pixels.
            Shape {
              id: dashedRing
              anchors.fill: parent
              visible: slot.dashed
              preferredRendererType: Shape.CurveRenderer

              ShapePath {
                strokeWidth: root.ringWidth
                strokeColor: root.stateColor(slot.dotState)
                fillColor: "transparent"
                capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: root.diameter / 2; centerY: root.diameter / 2; radiusX: (root.diameter - root.ringWidth) / 2; radiusY: radiusX; startAngle: -90; sweepAngle: 32 }
                PathAngleArc { centerX: root.diameter / 2; centerY: root.diameter / 2; radiusX: (root.diameter - root.ringWidth) / 2; radiusY: radiusX; startAngle: -30; sweepAngle: 32 }
                PathAngleArc { centerX: root.diameter / 2; centerY: root.diameter / 2; radiusX: (root.diameter - root.ringWidth) / 2; radiusY: radiusX; startAngle: 30; sweepAngle: 32 }
                PathAngleArc { centerX: root.diameter / 2; centerY: root.diameter / 2; radiusX: (root.diameter - root.ringWidth) / 2; radiusY: radiusX; startAngle: 90; sweepAngle: 32 }
                PathAngleArc { centerX: root.diameter / 2; centerY: root.diameter / 2; radiusX: (root.diameter - root.ringWidth) / 2; radiusY: radiusX; startAngle: 150; sweepAngle: 32 }
                PathAngleArc { centerX: root.diameter / 2; centerY: root.diameter / 2; radiusX: (root.diameter - root.ringWidth) / 2; radiusY: radiusX; startAngle: 210; sweepAngle: 32 }
              }
            }

            // Together mode: every counted account fills in place. Single mode uses the sliding fill below.
            Rectangle {
              anchors.fill: parent
              radius: width / 2
              antialiasing: true
              color: root.fillColor(slot.dotState)
              opacity: slot.filled && root.mode === "together" ? 1 : 0

              Behavior on opacity {
                OpacityAnimator { duration: root.duration(root.motion ? root.motion.micro : 0); easing.type: Easing.OutCubic }
              }
            }

            // One ring per live request, from the dot outwards. The ring grows; its stroke stays one pixel.
            Rectangle {
              id: pingRing
              property real size: root.diameter
              anchors.centerIn: parent
              width: size
              height: size
              radius: size / 2
              color: "transparent"
              antialiasing: true
              border.width: root.ringWidth
              border.color: root.accent
              opacity: 0
              visible: pingAnimation.running

              ParallelAnimation {
                id: pingAnimation
                NumberAnimation {
                  target: pingRing
                  property: "size"
                  from: root.diameter
                  to: root.diameter * 2.6
                  duration: root.duration(root.motion ? root.motion.ping : 0)
                  easing.type: Easing.OutCubic
                }
                OpacityAnimator {
                  target: pingRing
                  from: 0.9
                  to: 0
                  duration: root.duration(root.motion ? root.motion.ping : 0)
                  easing.type: Easing.OutCubic
                }
              }
            }
          }
        }

        // Single mode: the one filled dot slides to the account new sessions use.
        Rectangle {
          id: travellingFill
          objectName: "accountDotsFill"
          readonly property var info: root.countedSlot >= 0 ? root.dots[root.countedSlot] : null
          x: Math.max(0, root.countedSlot) * root.pitch
          y: Math.round((root.height - root.diameter) / 2)
          width: root.diameter
          height: root.diameter
          radius: width / 2
          antialiasing: true
          color: root.fillColor(info ? String(info.state) : "ok")
          readonly property bool shown: root.mode !== "together" && root.countedSlot >= 0 && !root.stale
          opacity: shown ? 1 : 0

          Behavior on x {
            XAnimator { duration: root.duration(root.motion ? root.motion.row : 0); easing.type: Easing.InOutCubic }
          }
          Behavior on opacity {
            OpacityAnimator { duration: root.duration(root.motion ? root.motion.micro : 0); easing.type: Easing.OutCubic }
          }
          Behavior on color {
            ColorAnimation { duration: root.duration(root.motion ? root.motion.micro : 0) }
          }
        }
      }

      // Every account used up: a clock face that fills towards the earliest reset.
      Shape {
        id: pie
        objectName: "accountDotsPie"
        readonly property real fraction: root.pieFraction
        readonly property color tint: root.stale ? root.dim : root.urgent
        y: Math.round((root.height - root.pieDiameter) / 2)
        width: root.pieDiameter
        height: root.pieDiameter
        preferredRendererType: Shape.CurveRenderer
        readonly property bool shown: root.allUsedUp
        opacity: shown ? 1 : 0

        Behavior on opacity {
          OpacityAnimator { duration: root.duration(root.motion ? root.motion.row : 0); easing.type: Easing.InOutCubic }
        }

        ShapePath {
          strokeWidth: root.ringWidth
          strokeColor: pie.tint
          fillColor: "transparent"
          PathAngleArc {
            centerX: root.pieDiameter / 2
            centerY: root.pieDiameter / 2
            radiusX: (root.pieDiameter - root.ringWidth) / 2
            radiusY: radiusX
            startAngle: -90
            sweepAngle: 360
          }
        }

        ShapePath {
          strokeWidth: -1
          fillColor: pie.fraction > 0 ? pie.tint : "transparent"
          startX: root.pieDiameter / 2
          startY: root.pieDiameter / 2
          PathAngleArc {
            centerX: root.pieDiameter / 2
            centerY: root.pieDiameter / 2
            radiusX: root.pieDiameter / 2 - root.ringWidth - 0.5
            radiusY: radiusX
            startAngle: -90
            sweepAngle: Math.max(0, Math.min(1, pie.fraction)) * 360
            moveToStart: false
          }
          PathLine { x: root.pieDiameter / 2; y: root.pieDiameter / 2 }
        }
      }
    }

    // Five or more accounts: three dots, then how many more.
    PlainText {
      id: moreLabel
      objectName: "accountDotsMore"
      visible: root.extra > 0 && !root.allUsedUp
      leftPadding: root.gap
      height: root.height
      verticalAlignment: Text.AlignVCenter
      text: "+" + root.extra
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.weight: Font.Medium
    }

    // "→ Personal" or the time to the earliest reset. It slides open and shut with its width; while it
    // shows, a countdown that gets shorter or longer resizes it at once, so a routine tick never
    // animates the bar.
    Item {
      id: hintBox
      objectName: "accountDotsHint"
      readonly property bool shown: root.hintShown
      readonly property string text: hintLabel.text
      property real openness: shown ? 1 : 0
      width: Math.round((Math.ceil(hintLabel.implicitWidth) + Style.spacing.sm) * openness)
      height: root.height
      clip: true
      opacity: shown ? 1 : 0
      visible: width > 0

      Behavior on openness {
        NumberAnimation { duration: root.duration(root.motion ? root.motion.row : 0); easing.type: Easing.OutCubic }
      }
      Behavior on opacity {
        OpacityAnimator { duration: root.duration(root.motion ? root.motion.row : 0); easing.type: Easing.OutCubic }
      }

      PlainText {
        id: hintLabel
        x: Style.spacing.sm
        height: parent.height
        verticalAlignment: Text.AlignVCenter
        text: root.shownHint
        color: root.shownHintKind === "switch" ? root.foreground : root.dim
        font.family: root.fontFamily
        font.pixelSize: root.fontSize
        font.weight: Font.Medium
      }
    }
  }
}
