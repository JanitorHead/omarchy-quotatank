pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

// A 24-hour use line: 0-100 % from bottom to top, newest point marked. Hovering scrubs it: a guide
// and a readout with the time and the use at that point ("16:12 · 68%").
Item {
  id: root

  // Numbers 0-100, oldest first (an account's `history.h24`).
  property var values: []
  // Epoch of the newest point; each earlier point is one step of spanSeconds / values.length before it.
  property real endSeconds: 0
  property real spanSeconds: 86400
  property color lineColor: Commons.Color.foreground
  property color guideColor: Commons.Color.foreground
  property color dotColor: lineColor
  property string fontFamily: Style.font.family
  property string clockFormat: "HH:mm"
  property bool scrubEnabled: true
  property var motion: null

  readonly property var points: {
    var result = []
    var list = values && values.length !== undefined ? values : []
    for (var i = 0; i < list.length; i++) {
      var value = Number(list[i])
      result.push(isFinite(value) ? Math.max(0, Math.min(100, value)) : 0)
    }
    return result
  }
  readonly property bool drawable: points.length > 1
  readonly property real inset: Math.max(2, Style.spaceReal(2.5))
  readonly property real lineWidth: Math.max(1, Style.spaceReal(1.5))
  readonly property bool scrubbing: scrubEnabled && drawable && sparkHover.hovered
  readonly property int scrubIndex: !scrubbing ? -1
    : Math.max(0, Math.min(points.length - 1, Math.round((sparkHover.point.position.x - inset) / Math.max(1, width - inset * 2) * (points.length - 1))))
  readonly property string scrubText: scrubIndex < 0 ? ""
    : (endSeconds > 0 ? Qt.formatTime(new Date((endSeconds - (points.length - 1 - scrubIndex) * spanSeconds / points.length) * 1000), clockFormat) + " · " : "")
      + Math.round(points[scrubIndex]) + "%"

  function xAt(index) {
    return inset + (points.length > 1 ? index * (width - inset * 2) / (points.length - 1) : 0)
  }

  function yAt(value) {
    return inset + (1 - value / 100) * (height - inset * 2)
  }

  implicitWidth: Style.space(64)
  implicitHeight: Style.space(20)

  Behavior on lineColor {
    ColorAnimation { duration: root.motion ? root.motion.duration(root.motion.micro) : 0 }
  }

  // Baseline, so a flat-zero day still reads as a line rather than a gap. Without data, nothing.
  Rectangle {
    visible: root.drawable
    x: root.inset
    y: Math.round(root.yAt(0))
    width: Math.max(0, root.width - root.inset * 2)
    height: Style.spacing.hairline
    color: Qt.rgba(root.guideColor.r, root.guideColor.g, root.guideColor.b, 0.12)
  }

  Shape {
    anchors.fill: parent
    visible: root.drawable
    preferredRendererType: Shape.CurveRenderer

    ShapePath {
      strokeColor: root.lineColor
      strokeWidth: root.lineWidth
      fillColor: "transparent"
      capStyle: ShapePath.RoundCap
      joinStyle: ShapePath.RoundJoin

      PathPolyline {
        path: {
          var result = []
          for (var i = 0; i < root.points.length; i++) result.push(Qt.point(root.xAt(i), root.yAt(root.points[i])))
          return result
        }
      }
    }
  }

  Rectangle {
    objectName: "sparklineEnd"
    visible: root.drawable
    readonly property real size: Math.max(3, Math.round(root.lineWidth * 2.6))
    x: root.xAt(root.points.length - 1) - size / 2
    y: root.yAt(root.points.length > 0 ? root.points[root.points.length - 1] : 0) - size / 2
    width: size
    height: size
    radius: size / 2
    color: root.dotColor
  }

  Rectangle {
    objectName: "sparklineGuide"
    visible: root.scrubIndex >= 0
    x: Math.round(root.xAt(Math.max(0, root.scrubIndex)) - width / 2)
    y: 0
    width: Style.spacing.hairline
    height: root.height
    color: Qt.rgba(root.guideColor.r, root.guideColor.g, root.guideColor.b, 0.55)
  }

  Rectangle {
    visible: root.scrubIndex >= 0
    readonly property real size: Math.max(3, Math.round(root.lineWidth * 2.6))
    x: root.xAt(Math.max(0, root.scrubIndex)) - size / 2
    y: root.yAt(root.scrubIndex >= 0 ? root.points[root.scrubIndex] : 0) - size / 2
    width: size
    height: size
    radius: size / 2
    color: root.guideColor
  }

  Ui.BorderSurface {
    id: readout
    objectName: "sparklineReadout"
    visible: root.scrubText !== ""
    z: 3
    x: Math.round(Math.max(-root.x, Math.min(root.xAt(Math.max(0, root.scrubIndex)) - width / 2, root.width - width)))
    y: -height - Style.spacing.sm
    width: readoutLabel.implicitWidth + contentLeftInset + contentRightInset
    height: readoutLabel.implicitHeight + contentTopInset + contentBottomInset
    color: Commons.Color.tooltip.background
    borderSpec: Border.flat(Qt.rgba(root.guideColor.r, root.guideColor.g, root.guideColor.b, 0.24), Style.spacing.hairline)
    radius: Style.cornerRadius
    leftPadding: Style.spacing.md
    rightPadding: Style.spacing.md
    topPadding: Style.spacing.xxs
    bottomPadding: Style.spacing.xxs

    PlainText {
      id: readoutLabel
      x: readout.contentLeftInset
      y: readout.contentTopInset
      text: root.scrubText
      color: Commons.Color.tooltip.text
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  HoverHandler {
    id: sparkHover
    enabled: root.scrubEnabled
  }
}
