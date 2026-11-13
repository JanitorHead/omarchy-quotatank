pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Shapes
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

// One account in the ACCOUNTS list: state dot · name and one status line · short and long limits, which
// move while the account spends · action (the "in use" tag, a Use button, or a proxy account's banked resets).
// An ended subscription shows no limits: there is nothing left to spend.
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
  property bool ended: false
  property bool inUse: false
  // omp's tag for this account beside its name (UsageLogic.accountState ompTags): "next", "in reserve",
  // "5h nearly full", or "" for none; an empty tag keeps the name line's place.
  property string ompTag: ""
  readonly property real ompTagGap: ompTag === "" ? 0 : Style.spacing.xs
  property bool canUse: false
  property bool useBusy: false
  // Usable-now banked resets (`UsageLogic.accountResetBadge`); null hides the badge. `resetSlot` keeps the
  // badge's place while the account can show resets, so the row holds still when the badge comes and goes.
  property var resetBadge: null
  property bool resetSlot: false
  property bool resetEnabled: false
  property string quotaMode: "Used"
  property real warningThreshold: 25
  property real criticalThreshold: 10
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property color accent: Commons.Color.accent
  property string fontFamily: Style.font.family
  property real cardRadius: 0
  property var motion: null
  property real nowSeconds: 0
  // When omp last sent a request for this account (Unix seconds, 0 when unknown), and Display → Meter style.
  property real requestAt: 0
  property string meterStyle: "projection"

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property bool hovered: rowMouse.containsMouse
  readonly property color valueColor: severity === "warning" || severity === "critical" ? urgent : foreground
  readonly property bool hasAction: inUse || canUse || resetSlot
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
    implicitHeight: Math.max(textColumn.implicitHeight, meters.implicitHeight, action.implicitHeight)

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
      anchors.right: root.ended ? action.left : meters.left
      anchors.rightMargin: Style.spacing.lg
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.spacing.xxs

      Item {
        id: nameLine
        width: parent.width
        height: accountName.implicitHeight

        PlainText {
          id: accountName
          objectName: "accountName"
          anchors.left: parent.left
          anchors.top: parent.top
          width: Math.min(implicitWidth, parent.width - ompTagText.width - root.ompTagGap)
          text: root.name
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.weight: Font.DemiBold
          elide: Text.ElideRight
        }

        PlainText {
          id: ompTagText
          objectName: "accountOmpTag"
          anchors.left: accountName.right
          anchors.leftMargin: root.ompTagGap
          anchors.baseline: accountName.baseline
          text: root.ompTag
          color: root.ompTag === "next" ? root.accent : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
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

    AccountMeters {
      id: meters
      objectName: "accountMeters"
      visible: !root.ended
      anchors.right: action.left
      anchors.rightMargin: root.hasAction ? Style.spacing.lg : 0
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(112)
      account: root.account
      quotaMode: root.quotaMode
      spending: root.spending
      nowSeconds: root.nowSeconds
      requestAt: root.requestAt
      meterStyle: root.meterStyle
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
      readonly property real useWidth: root.inUse || root.canUse
        ? Math.max(useMetrics.advanceWidth("in use"), useButton.visible ? useButton.implicitWidth : 0) : 0
      // Reserved size of the reset chip, so the meter does not move when the chip comes and goes.
      readonly property real resetWidth: root.resetSlot ? resetMetrics.advanceWidth("10 resets") + Style.spacing.lg * 2 : 0
      width: useWidth + resetWidth + (useWidth > 0 && resetWidth > 0 ? Style.spacing.md : 0)
      implicitHeight: !root.hasAction ? 0 : Math.max(useButton.visible ? useButton.implicitHeight : inUseTag.implicitHeight,
        resetWidth > 0 ? resetMetrics.height + Style.spacing.xs * 2 : 0)

      FontMetrics {
        id: useMetrics
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.weight: Font.DemiBold
      }

      FontMetrics {
        id: resetMetrics
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      // The in-use tag or the Use button; the two never show together.
      Item {
        id: useSlot
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: action.useWidth
        height: useButton.visible ? useButton.implicitHeight : inUseTag.implicitHeight

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
      }

      // Usable-now banked resets: the count, and one click starts applying one where Quotatank can apply it.
      // Its own slot beside the use slot, so the chip never sits on the Use button.
      Item {
        id: resetHost
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: action.resetWidth
        height: resetMetrics.height + Style.spacing.xs * 2

        Rectangle {
          id: resetChip
          objectName: "accountResetBadge"
          visible: root.resetBadge !== null
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
          Accessible.name: (root.resetBadge ? root.resetBadge.tooltip : "") + (resetClick.enabled ? ": apply a reset" : "")
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
          ToolTip.text: (root.resetBadge ? root.resetBadge.tooltip : "")
            + (resetClick.enabled ? " · click to apply one" : "")

          PlainText {
            id: resetLabel
            objectName: "accountResetLabel"
            anchors.centerIn: parent
            text: root.resetBadge ? root.resetBadge.label : ""
            color: root.resetBadge && root.resetBadge.dim ? root.dim : root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }
}
