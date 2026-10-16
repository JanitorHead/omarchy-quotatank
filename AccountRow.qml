pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

// One account in the ACCOUNTS list: state dot · name and one status line · 24 h sparkline · short and
// long limits · action (the "in use" tag, a Use button, or a proxy account's banked resets).
Ui.BorderSurface {
  id: root

  property var account: null
  property string name: ""
  property bool selected: false
  // Counted by the chip (filled dot); otherwise a hollow ring in the account's state colour.
  property bool counted: false
  property bool spending: false
  // The account's ring (UsageLogic.accountRingState): "ok" | "warning" | "critical" | "error" | "unknown"
  property string severity: "unknown"
  property string statusText: ""
  property string statusTone: "dim"
  property var sparkValues: []
  property real sparkEnd: 0
  property bool inUse: false
  property bool canUse: false
  property bool useBusy: false
  // Banked resets of a proxy account; empty hides the badge.
  property int resetCount: -1
  property bool resetEnabled: false
  property string quotaMode: "Used"
  property real warningThreshold: 25
  property real criticalThreshold: 10
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property color accent: Commons.Color.accent
  property string fontFamily: Style.font.family
  property string clockFormat: "HH:mm"
  property real cardRadius: 0
  property var motion: null

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property bool hovered: rowMouse.containsMouse
  readonly property color valueColor: severity === "warning" || severity === "critical" ? urgent : foreground
  readonly property bool hasAction: inUse || canUse || resetCount >= 0
  readonly property alias useButton: useButton

  signal selectRequested()
  signal useRequested()
  signal resetRequested()

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

  implicitHeight: content.implicitHeight + contentTopInset + contentBottomInset
  leftPadding: Style.spacing.xl
  rightPadding: Style.spacing.lg
  topPadding: Style.spacing.md
  bottomPadding: Style.spacing.md
  radius: root.cardRadius
  color: root.selected ? root.alpha(root.accent, 0.07) : root.hovered ? root.alpha(root.foreground, 0.04) : "transparent"
  borderSpec: Border.flat(root.selected ? root.accent : root.alpha(root.foreground, root.hovered ? 0.28 : 0.16), Style.spacing.hairline)

  Behavior on color {
    ColorAnimation { duration: root.motion ? root.motion.duration(root.motion.micro) : 0 }
  }

  Accessible.role: Accessible.ListItem
  Accessible.name: root.name + (root.inUse ? ", in use" : "") + (root.statusText !== "" ? ", " + root.statusText : "")
  Accessible.selected: root.selected

  MouseArea {
    id: rowMouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: root.selectRequested()
  }

  Item {
    id: content
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.leftMargin: root.contentLeftInset
    anchors.rightMargin: root.contentRightInset
    anchors.topMargin: root.contentTopInset
    implicitHeight: Math.max(textColumn.implicitHeight, meters.implicitHeight, spark.height, action.implicitHeight)

    // State dot: filled when the chip counts this account, a ring in its state colour otherwise.
    Item {
      id: dot
      objectName: "accountDot"
      readonly property real size: Style.space(8)
      readonly property bool dashed: root.severity === "error"
      readonly property color ringColor: root.severity === "critical" ? root.urgent
        : root.severity === "warning" ? root.alpha(root.urgent, 0.7)
        : dashed ? root.dim : root.alpha(root.foreground, 0.55)
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      width: size
      height: size

      // Spending now: a soft accent halo behind the dot.
      Rectangle {
        objectName: "accountHalo"
        anchors.centerIn: parent
        width: dot.size * 2.1
        height: width
        radius: width / 2
        color: root.accent
        opacity: root.spending ? 0.22 : 0

        Behavior on opacity {
          OpacityAnimator { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
        }
      }

      Rectangle {
        anchors.fill: parent
        radius: width / 2
        visible: !dot.dashed
        color: root.counted ? root.valueColor : "transparent"
        border.width: root.counted ? 0 : Math.max(1, Style.spaceReal(1.25))
        border.color: dot.ringColor

        Behavior on color {
          ColorAnimation { duration: root.motion ? root.motion.duration(root.motion.micro) : 0 }
        }
      }

      Shape {
        anchors.fill: parent
        visible: dot.dashed
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
          strokeColor: dot.ringColor
          strokeWidth: Math.max(1, Style.spaceReal(1.25))
          strokeStyle: ShapePath.DashLine
          dashPattern: [1.6, 1.6]
          fillColor: "transparent"

          PathAngleArc {
            centerX: dot.size / 2
            centerY: dot.size / 2
            radiusX: dot.size / 2 - 0.75
            radiusY: dot.size / 2 - 0.75
            startAngle: 0
            sweepAngle: 360
          }
        }
      }
    }

    Column {
      id: textColumn
      anchors.left: dot.right
      anchors.leftMargin: Style.spacing.controlGap
      anchors.right: spark.left
      anchors.rightMargin: Style.spacing.lg
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.spacing.xxs

      PlainText {
        objectName: "accountName"
        width: parent.width
        text: root.name
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.weight: Font.DemiBold
        elide: Text.ElideRight
      }

      PlainText {
        objectName: "accountStatus"
        width: parent.width
        text: root.statusText
        color: root.statusTone === "urgent" ? root.urgent : root.statusTone === "accent" ? root.accent : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }

    Sparkline {
      id: spark
      objectName: "accountSparkline"
      anchors.right: meters.left
      anchors.rightMargin: Style.spacing.xl
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(52)
      height: Style.space(18)
      values: root.sparkValues
      endSeconds: root.sparkEnd
      lineColor: root.spending ? root.accent : root.alpha(root.foreground, 0.5)
      dotColor: root.spending ? root.accent : root.foreground
      guideColor: root.foreground
      fontFamily: root.fontFamily
      clockFormat: root.clockFormat
      motion: root.motion
    }

    AccountMeters {
      id: meters
      objectName: "accountMeters"
      anchors.right: action.left
      anchors.rightMargin: root.hasAction ? Style.spacing.lg : 0
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(92)
      account: root.account
      quotaMode: root.quotaMode
      warningThreshold: root.warningThreshold
      criticalThreshold: root.criticalThreshold
      foreground: root.foreground
      urgent: root.urgent
      fontFamily: root.fontFamily
      motion: root.motion
    }

    Item {
      id: action
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      width: !root.hasAction ? 0 : Math.max(useMetrics.advanceWidth("in use"),
        useButton.visible ? useButton.implicitWidth : 0, resetBadge.visible ? resetBadge.implicitWidth : 0)
      implicitHeight: useButton.visible ? useButton.implicitHeight : resetBadge.visible ? resetBadge.implicitHeight : inUseTag.implicitHeight

      FontMetrics {
        id: useMetrics
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.weight: Font.DemiBold
      }

      PlainText {
        id: inUseTag
        objectName: "accountInUse"
        visible: root.inUse
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: "in use"
        color: root.accent
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.weight: Font.DemiBold
      }

      Ui.Button {
        id: useButton
        objectName: "accountUseButton"
        visible: root.canUse && !root.inUse
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: root.useBusy ? "" : "Use"
        iconText: root.useBusy ? "󰑐" : ""
        iconSpinning: root.useBusy && !(root.motion && root.motion.reduced)
        iconSize: Style.font.caption
        bordered: true
        enabled: !root.useBusy
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.caption
        horizontalPadding: Style.spacing.md
        verticalPadding: Style.spacing.xxs
        tooltipText: root.useBusy ? "Switching new sessions to " + root.name + "…" : "Start new sessions with " + root.name
        Accessible.name: "Use " + root.name
        onClicked: if (!root.useBusy) root.useRequested()
      }

      // Banked resets of a proxy account: the count, and one click starts applying one.
      Rectangle {
        id: resetBadge
        objectName: "accountResetBadge"
        visible: root.resetCount >= 0
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        implicitWidth: resetLabel.implicitWidth + Style.spacing.lg * 2
        implicitHeight: resetLabel.implicitHeight + Style.spacing.xs * 2
        width: implicitWidth
        height: implicitHeight
        radius: height / 2
        color: resetClick.containsMouse && resetClick.enabled || activeFocus ? root.alpha(root.foreground, 0.08) : "transparent"
        border.width: Style.spacing.hairline
        border.color: root.alpha(root.foreground, activeFocus ? 0.6 : 0.18)
        activeFocusOnTab: resetClick.enabled
        Accessible.role: Accessible.Button
        Accessible.name: root.resetCount + " banked reset" + (root.resetCount === 1 ? "" : "s") + ": apply a reset"
        Keys.onReturnPressed: resetClick.activate()
        Keys.onSpacePressed: resetClick.activate()

        MouseArea {
          id: resetClick
          objectName: "accountResetAction"
          anchors.fill: parent
          enabled: root.resetEnabled
          hoverEnabled: true
          cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
          function activate() {
            if (enabled) root.resetRequested()
          }
          onClicked: activate()
        }

        ToolTip.visible: resetClick.containsMouse
        ToolTip.text: root.resetCount + " banked reset" + (root.resetCount === 1 ? "" : "s")
          + (resetClick.enabled ? " · click to apply one" : " · none to apply now")

        PlainText {
          id: resetLabel
          objectName: "accountResetLabel"
          anchors.centerIn: parent
          text: root.resetCount + (root.resetCount === 1 ? " reset" : " resets")
          color: root.resetCount > 0 ? root.foreground : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}
