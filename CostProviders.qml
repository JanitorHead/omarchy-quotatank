pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Effects
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// Providers in the scan: mark in its chart colour, name, share bar and value. Hovering a row focuses
// the chart on that provider (the others dim); clicking isolates it (the chart rescales to it) and
// clicking again shows them all.
Column {
  id: root

  // [{ id, name, color, valueText, share (0-1), meta }] in the payload's provider order.
  property var rows: []
  property string focusedProvider: ""
  property string isolatedProvider: ""
  property bool hintSeen: false
  property real valueWidth: Style.space(64)
  property real barWidth: Style.space(96)
  property var motion: null
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property bool interactive: rows.length > 1
  readonly property int microMs: motion ? motion.duration(motion.micro) : 0
  readonly property int rowMs: motion ? motion.duration(motion.row) : 0
  // Rows key by provider id, so a refresh keeps them and only animates changed share bars.
  readonly property string rowIds: rows.map(function(row) { return row.id }).join("\n")
  readonly property var rowById: {
    var map = {}
    for (var i = 0; i < rows.length; i++) map[rows[i].id] = rows[i]
    return map
  }
  readonly property string isolatedName: isolatedProvider !== "" && rowById[isolatedProvider]
    ? String(rowById[isolatedProvider].name) : ""
  // Widest value shown, so the panel can line the value columns of both lists up.
  readonly property real widestValue: {
    var widest = 0
    for (var i = 0; i < rows.length; i++) widest = Math.max(widest, valueMetrics.advanceWidth(String(rows[i].valueText || "")))
    return Math.ceil(widest)
  }

  signal focusRequested(string providerId)
  signal isolateRequested(string providerId)

  spacing: Style.spacing.xxs

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

  FontMetrics {
    id: valueMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    font.weight: Font.Medium
  }

  Item {
    width: parent.width
    implicitHeight: Math.max(title.implicitHeight, hint.implicitHeight) + Style.spacing.md

    Ui.PanelSectionHeader {
      id: title
      anchors.left: parent.left
      anchors.top: parent.top
      text: "BY PROVIDER"
      foreground: root.foreground
      fontFamily: root.fontFamily
    }

    Text {
      id: hint
      objectName: "costProviderHint"
      anchors.right: parent.right
      anchors.left: title.right
      anchors.leftMargin: Style.spacing.controlGap
      anchors.baseline: title.baseline
      horizontalAlignment: Text.AlignRight
      text: root.isolatedName !== "" ? root.isolatedName + " only · click again for all"
        : root.interactive && !root.hintSeen ? "hover to focus · click to isolate" : ""
      textFormat: Text.PlainText
      elide: Text.ElideLeft
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  Repeater {
    model: root.rowIds === "" ? [] : root.rowIds.split("\n")

    delegate: Item {
      id: row
      required property string modelData
      readonly property var entry: root.rowById[modelData] || ({})
      readonly property bool isolated: root.isolatedProvider === modelData
      readonly property bool dimmed: root.isolatedProvider !== "" && !isolated
      readonly property bool hot: mouse.containsMouse || activeFocus

      objectName: "costProvider-" + modelData
      width: root.width
      implicitHeight: line.height + (meta.visible ? Style.spacing.xxs + meta.implicitHeight : 0) + Style.spacing.sm * 2
      opacity: dimmed && !hot ? 0.45 : 1
      activeFocusOnTab: root.interactive
      Accessible.role: Accessible.Button
      Accessible.checkable: root.interactive
      Accessible.checked: isolated
      Accessible.name: String(entry.name || "") + ", " + String(entry.valueText || "")
        + (root.interactive ? ", " + Math.round(Number(entry.share || 0) * 100) + "% of the total" : "")
        + (isolated ? ", shown alone" : "")
      Keys.onReturnPressed: if (root.interactive) root.isolateRequested(modelData)
      Keys.onSpacePressed: if (root.interactive) root.isolateRequested(modelData)
      onActiveFocusChanged: if (root.interactive) root.focusRequested(activeFocus ? modelData : "")

      Behavior on opacity {
        OpacityAnimator { duration: root.microMs; easing.type: Easing.OutCubic }
      }

      Rectangle {
        anchors.fill: parent
        radius: Math.min(Style.cornerRadius, Style.space(4))
        color: row.isolated ? root.alpha(Commons.Color.accent, 0.08)
          : row.hot && root.interactive ? Style.hoverFillFor(root.foreground, Commons.Color.accent) : "transparent"
        border.width: row.isolated || (row.activeFocus && root.interactive) ? Style.spacing.hairline : 0
        border.color: row.isolated ? root.alpha(Commons.Color.accent, 0.6) : Commons.Color.accent

        Behavior on color {
          ColorAnimation { duration: root.microMs }
        }
      }

      Item {
        id: line
        x: Style.spacing.md
        y: Style.spacing.sm
        width: parent.width - Style.spacing.md * 2
        height: Math.max(name.implicitHeight, value.implicitHeight)

        Item {
          id: mark
          width: Style.space(12)
          height: width
          anchors.verticalCenter: parent.verticalCenter
          readonly property string iconUrl: UsageLogic.localProvider(row.modelData)
            ? Qt.resolvedUrl("assets/" + row.modelData + "-bar.svg") : ""

          Image {
            id: markImage
            anchors.fill: parent
            source: mark.iconUrl
            sourceSize.width: mark.width * 2
            sourceSize.height: mark.height * 2
            fillMode: Image.PreserveAspectFit
            visible: false
            layer.enabled: true
          }

          MultiEffect {
            anchors.fill: markImage
            source: markImage
            visible: markImage.status === Image.Ready
            colorization: 1.0
            colorizationColor: row.entry.color || root.foreground
          }

          // No mark file: the swatch alone ties the row to its colour in the chart.
          Rectangle {
            visible: markImage.status !== Image.Ready
            anchors.centerIn: parent
            width: Style.space(8)
            height: width
            radius: Math.min(Style.cornerRadius, Style.space(2))
            color: row.entry.color || root.foreground
          }
        }

        Text {
          id: name
          anchors.left: mark.right
          anchors.leftMargin: Style.spacing.lg
          anchors.right: bar.left
          anchors.rightMargin: Style.spacing.controlGap
          anchors.verticalCenter: parent.verticalCenter
          text: String(row.entry.name || row.modelData)
          textFormat: Text.PlainText
          elide: Text.ElideRight
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          font.weight: Font.Medium
        }

        Item {
          id: bar
          anchors.right: value.left
          anchors.rightMargin: Style.spacing.controlGap
          anchors.verticalCenter: parent.verticalCenter
          width: root.barWidth
          height: Style.space(4)

          Rectangle {
            anchors.fill: parent
            radius: Math.min(Style.cornerRadius, height / 2)
            color: root.alpha(root.foreground, 0.08)
          }

          Rectangle {
            width: Math.round(parent.width * Math.max(0, Math.min(1, Number(row.entry.share || 0))))
            height: parent.height
            radius: Math.min(Style.cornerRadius, height / 2)
            color: row.entry.color || root.foreground

            Behavior on width {
              NumberAnimation { duration: root.rowMs; easing.type: Easing.InOutCubic }
            }
          }
        }

        Text {
          id: value
          objectName: "costProviderValue-" + row.modelData
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: Math.max(root.valueWidth, implicitWidth)
          horizontalAlignment: Text.AlignRight
          text: String(row.entry.valueText || "")
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          font.weight: Font.Medium
          font.features: { "tnum": 1 }
        }
      }

      Text {
        id: meta
        visible: String(row.entry.meta || "") !== ""
        anchors.left: line.left
        anchors.leftMargin: mark.width + Style.spacing.lg
        anchors.right: line.right
        anchors.top: line.bottom
        anchors.topMargin: Style.spacing.xxs
        text: String(row.entry.meta || "")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      MouseArea {
        id: mouse
        anchors.fill: parent
        enabled: root.interactive
        hoverEnabled: true
        cursorShape: root.interactive ? Qt.PointingHandCursor : Qt.ArrowCursor
        onContainsMouseChanged: root.focusRequested(containsMouse ? row.modelData : "")
        onClicked: root.isolateRequested(row.modelData)
      }
    }
  }
}
