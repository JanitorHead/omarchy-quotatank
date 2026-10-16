pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui as Ui

// Hover card of a menu bar chip whose provider has two or more accounts (DESIGN §2.4), drawn from
// UsageLogic.barHoverModel(). Same surface as Omarchy's popup cards. A header with the provider, the
// account count and how accounts are chosen; a row per account (at most six, then "+N more") with its
// dot, name, one status line, a 24 h sparkline and compact meters; a footer with when the reading was
// taken. Rows are keyed by account, so a new reading updates them in place. It fades and scales in from
// the chip, and it never takes focus or input.
Ui.BorderSurface {
  id: root

  property var model: null
  property bool open: false
  property var motion: null
  property string quotaMode: "Used"
  property int warningThreshold: 25
  property int criticalThreshold: 10
  property color foreground: Color.popups.text
  property color urgent: Color.urgent
  property color accent: Color.accent
  property color dim: Qt.darker(foreground, 1.55)
  property string fontFamily: Style.font.family
  property string clockFormat: "HH:mm"
  // Epoch seconds of the reading, the newest point of every sparkline.
  property real endSeconds: 0
  // Grows from the edge that faces the chip.
  property string barPosition: "top"

  readonly property var rows: model && model.rows ? model.rows : []
  // Row keys (account ids) joined, so the rows' Repeater only rebuilds when the accounts shown change.
  readonly property string rowKeys: rows.map(function(row) { return row.key }).join("\n")
  readonly property var rowByKey: {
    var map = {}
    for (var i = 0; i < rows.length; i++) map[rows[i].key] = rows[i]
    return map
  }
  readonly property int moreCount: model ? Number(model.more) || 0 : 0
  readonly property int contentWidth: Style.space(320)

  implicitWidth: contentWidth + contentLeftInset + contentRightInset
  implicitHeight: body.implicitHeight + contentTopInset + contentBottomInset
  color: Color.popups.background
  borderSpec: Border.localOrSurfaceSpec("popups", "border", Color.popups.border, Color.popups.border, Math.max(1, Style.space(2)))
  padding: Style.spacing.popupPadding
  radius: Style.cornerRadius
  transformOrigin: barPosition === "bottom" ? Item.Bottom : Item.Top
  opacity: open ? 1 : 0
  scale: open ? 1 : 0.97

  // The property keeps its old value until an Animator ends, so it still tells the direction here.
  // Without Panel's Motion nothing animates.
  Behavior on opacity {
    OpacityAnimator {
      duration: root.motion ? root.motion.duration(root.opacity < 0.5 ? root.motion.popIn : root.motion.popOut) : 0
      easing.type: root.opacity < 0.5 ? Easing.OutCubic : Easing.InCubic
    }
  }
  Behavior on scale {
    ScaleAnimator {
      duration: root.motion ? root.motion.duration(root.opacity < 0.5 ? root.motion.popIn : root.motion.popOut) : 0
      easing.type: root.opacity < 0.5 ? Easing.OutCubic : Easing.InCubic
    }
  }

  function toneColor(tone) {
    if (tone === "urgent") return urgent
    if (tone === "accent") return accent
    return dim
  }

  Column {
    id: body
    x: root.contentLeftInset
    y: root.contentTopInset
    width: root.contentWidth
    spacing: Style.spacing.lg

    Item {
      width: parent.width
      height: Math.max(cardTitle.implicitHeight, cardMode.implicitHeight)

      PlainText {
        id: cardTitle
        objectName: "hoverCardTitle"
        width: parent.width - (cardMode.text !== "" ? cardMode.implicitWidth + Style.spacing.lg : 0)
        text: root.model ? String(root.model.title || "") : ""
        color: root.foreground
        elide: Text.ElideRight
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.weight: Font.DemiBold
      }

      PlainText {
        id: cardMode
        objectName: "hoverCardMode"
        anchors.right: parent.right
        anchors.baseline: cardTitle.baseline
        text: root.model ? String(root.model.modeText || "") : ""
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Column {
      width: parent.width
      spacing: Style.spacing.lg

      Repeater {
        model: root.rowKeys === "" ? [] : root.rowKeys.split("\n")

        delegate: Item {
          id: accountRow
          required property string modelData
          required property int index
          readonly property var row: root.rowByKey[modelData]
            || ({ name: "", inUse: false, counted: false, state: "unknown", status: "", tone: "dim", spark: [], account: null })
          readonly property bool spending: row.tone === "accent"

          objectName: "hoverCardRow-" + index
          width: parent.width
          height: Math.max(nameColumn.implicitHeight, meters.implicitHeight, spark.implicitHeight)

          AccountDots {
            id: rowDot
            objectName: "hoverCardDot-" + accountRow.index
            y: Math.round(nameLine.y + (nameLine.height - height) / 2)
            strip: ({ dots: [{ index: accountRow.index, state: accountRow.row.state,
                               counted: accountRow.row.counted, spending: accountRow.spending }], extra: 0 })
            mode: "together"
            stale: !!(root.model && root.model.stale)
            motion: root.motion
            foreground: root.foreground
            urgent: root.urgent
            accent: root.accent
            dim: root.dim
            fontFamily: root.fontFamily
          }

          Column {
            id: nameColumn
            x: rowDot.diameter + Style.spacing.lg
            width: spark.x - x - Style.spacing.lg
            spacing: Style.spacing.xxs

            Item {
              id: nameLine
              width: parent.width
              height: accountName.implicitHeight

              PlainText {
                id: accountName
                width: Math.min(implicitWidth, parent.width - (inUse.visible ? inUse.implicitWidth + Style.spacing.md : 0))
                text: String(accountRow.row.name)
                color: root.foreground
                elide: Text.ElideRight
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                font.weight: Font.Medium
              }

              PlainText {
                id: inUse
                visible: !!accountRow.row.inUse
                x: accountName.width + Style.spacing.md
                anchors.baseline: accountName.baseline
                text: "in use"
                color: root.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.weight: Font.DemiBold
              }
            }

            PlainText {
              objectName: "hoverCardStatus-" + accountRow.index
              width: parent.width
              text: String(accountRow.row.status)
              color: root.toneColor(accountRow.row.tone)
              elide: Text.ElideRight
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          Sparkline {
            id: spark
            anchors.right: meters.left
            anchors.rightMargin: Style.spacing.lg
            anchors.verticalCenter: parent.verticalCenter
            values: accountRow.row.spark
            endSeconds: root.endSeconds
            lineColor: accountRow.spending ? root.accent : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.55)
            guideColor: root.foreground
            fontFamily: root.fontFamily
            clockFormat: root.clockFormat
            scrubEnabled: false
            motion: root.motion
          }

          AccountMeters {
            id: meters
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(96)
            account: accountRow.row.account
            quotaMode: root.quotaMode
            warningThreshold: root.warningThreshold
            criticalThreshold: root.criticalThreshold
            foreground: root.foreground
            urgent: root.urgent
            fontFamily: root.fontFamily
            motion: root.motion
          }
        }
      }
    }

    Rectangle {
      width: parent.width
      height: Style.spacing.hairline
      color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)
    }

    Item {
      width: parent.width
      height: Math.max(readLabel.implicitHeight, detailsLabel.implicitHeight)

      PlainText {
        id: readLabel
        objectName: "hoverCardRead"
        text: root.model ? String(root.model.readText || "") : ""
        color: root.model && root.model.stale ? root.urgent : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      PlainText {
        id: detailsLabel
        objectName: "hoverCardMore"
        anchors.right: parent.right
        text: (root.moreCount > 0 ? "+" + root.moreCount + " more · " : "") + "Click for details"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
}
