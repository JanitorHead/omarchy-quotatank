pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// What the period's spend went to, by model, project folder or agent: name and dim context, a bar
// against the largest row, the value. Rows live in a ListModel kept in order with moves, so a period
// or metric change slides them to their new place instead of rebuilding the list. The top five show;
// the disclosure (and Panel's "b") shows the rest.
Column {
  id: root

  property var payload: ({})
  property string metric: "cost"
  property string mode: "model"
  property bool expanded: false
  property var modes: [{ value: "model", label: "Model" }]
  // Provider id -> chart colour, so a model's bar matches its provider in the chart.
  property var colors: ({})
  property real valueWidth: Style.space(64)
  property real barWidth: Style.space(96)
  property var motion: null
  property color foreground: Commons.Color.foreground
  // The panel surface, painted behind rows only while they trade places.
  property color surface: Commons.Color.popups.background
  property string fontFamily: Style.font.family
  readonly property int collapsedRows: 5

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property int rowMs: motion ? motion.duration(motion.row) : 0
  readonly property var allRows: UsageLogic.costBreakdownRows(payload, mode, metric)
  readonly property var shownRows: expanded ? allRows : allRows.slice(0, collapsedRows)
  readonly property int rowPitch: rowMetrics.height + Style.spacing.sm * 2
  readonly property string rowPrefix: mode === "project" ? "costProject-" : mode === "agent" ? "costAgent-" : "costModel-"
  // Widest value shown, so the panel can line the value columns of both lists up.
  readonly property real widestValue: {
    var widest = 0
    for (var i = 0; i < shownRows.length; i++) widest = Math.max(widest, valueMetrics.advanceWidth(valueText(shownRows[i])))
    return Math.ceil(widest)
  }
  readonly property int count: rowModel.count
  property var modelKeys: []
  property bool populated: false
  property string shownMode: mode

  signal modeRequested(string mode)
  signal expandRequested(bool expanded)

  spacing: Style.spacing.sm

  onShownRowsChanged: sync()
  Component.onCompleted: sync()

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

  function valueText(row) {
    if (metric === "tokens") return UsageLogic.formatTokens(row.value)
    return UsageLogic.formatUsd(row.value)
  }

  // Moves, inserts and in-place updates only (never clear()+append()): kept rows slide, new ones fade in.
  function sync() {
    var rows = shownRows
    var keys = []
    var wanted = {}
    for (var i = 0; i < rows.length; i++) {
      keys.push(rows[i].key)
      wanted[rows[i].key] = i
    }
    var animate = populated && visible && rowMs > 0
    var modeChanged = shownMode !== mode
    shownMode = mode
    for (var m = modelKeys.length - 1; m >= 0; m--) {
      if (wanted[modelKeys[m]] !== undefined) continue
      rowModel.remove(m, 1)
      modelKeys.splice(m, 1)
    }
    var inserted = 0
    UsageLogic.syncKeyedOrder({
      count: function() { return root.modelKeys.length },
      keyAt: function(position) { return root.modelKeys[position] },
      move: function(from, to) {
        rowModel.move(from, to, 1)
        root.modelKeys.splice(to, 0, root.modelKeys.splice(from, 1)[0])
      },
      insert: function(position, key) {
        var row = rows[wanted[key]]
        rowModel.insert(position, { key: key, name: row.name, context: row.context, provider: row.provider,
          valueText: root.valueText(row), fraction: row.fraction, entering: animate,
          delay: animate && modeChanged ? Math.min(inserted, 6) * 40 : 0 })
        inserted++
        root.modelKeys.splice(position, 0, key)
      }
    }, keys)
    for (var u = 0; u < rows.length; u++) {
      var current = rowModel.get(u)
      var text = valueText(rows[u])
      if (current.name !== rows[u].name) rowModel.setProperty(u, "name", rows[u].name)
      if (current.context !== rows[u].context) rowModel.setProperty(u, "context", rows[u].context)
      if (current.valueText !== text) rowModel.setProperty(u, "valueText", text)
      if (current.fraction !== rows[u].fraction) rowModel.setProperty(u, "fraction", rows[u].fraction)
    }
    populated = rows.length > 0
  }

  FontMetrics {
    id: rowMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
  }

  FontMetrics {
    id: valueMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    font.weight: Font.Medium
  }

  ListModel { id: rowModel }

  Item {
    width: parent.width
    implicitHeight: Math.max(title.implicitHeight, dimensions.implicitHeight)

    Ui.PanelSectionHeader {
      id: title
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      text: "BREAKDOWN"
      foreground: root.foreground
      fontFamily: root.fontFamily
    }

    // Same light segmented control as the period switch above, with its sliding indicator.
    UsageTabs {
      id: dimensions
      objectName: "costBreakdownMode"
      visible: root.modes.length > 1
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      options: root.modes
      value: root.mode
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.caption
      motion: root.motion
      onChanged: function(value) { root.modeRequested(value) }
    }
  }

  Item {
    id: rowArea
    objectName: "costBreakdownRows"
    width: parent.width
    height: rowModel.count * root.rowPitch

    Behavior on height {
      enabled: root.populated
      NumberAnimation { duration: root.rowMs; easing.type: Easing.OutCubic }
    }

    Repeater {
      model: rowModel

      delegate: Item {
        id: row
        required property int index
        required property string key
        required property string name
        required property string context
        required property string provider
        required property string valueText
        required property real fraction
        required property bool entering
        required property int delay

        objectName: root.rowPrefix + index
        width: rowArea.width
        height: root.rowPitch
        y: index * root.rowPitch
        // While rows trade places, each one is opaque and the one climbing passes over the others.
        property int lastIndex: -1
        property int travel: 0
        z: travel < 0 ? 2 : (travel > 0 ? 1 : 0)
        Accessible.role: Accessible.StaticText
        Accessible.name: name + ", " + context + ", " + valueText
        onIndexChanged: {
          var from = lastIndex
          lastIndex = index
          if (from < 0 || !root.populated || root.rowMs <= 0) return
          travel = index - from
          settle.restart()
        }

        Timer {
          id: settle
          interval: root.rowMs
          onTriggered: row.travel = 0
        }

        Rectangle {
          anchors.fill: parent
          visible: row.travel !== 0
          color: root.surface
        }

        Behavior on y {
          enabled: root.populated
          YAnimator { duration: root.rowMs; easing.type: Easing.InOutCubic }
        }

        SequentialAnimation {
          id: enter
          PauseAnimation { duration: row.delay }
          OpacityAnimator { target: row; from: 0; to: 1; duration: root.rowMs; easing.type: Easing.OutCubic }
        }
        Component.onCompleted: {
          lastIndex = index
          if (entering) {
            opacity = 0
            enter.start()
          }
        }

        TextEdit {
          id: nameText
          anchors.left: parent.left
          anchors.leftMargin: Style.spacing.md
          anchors.verticalCenter: parent.verticalCenter
          width: Math.min(implicitWidth, Math.max(0, bar.x - Style.spacing.controlGap - x))
          text: row.name
          // Selectable, so a model id can be copied into a custom price.
          readOnly: true
          selectByMouse: true
          textFormat: TextEdit.PlainText
          wrapMode: TextEdit.NoWrap
          clip: true
          color: root.foreground
          selectionColor: Commons.Color.accent
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        PlainText {
          anchors.left: nameText.right
          anchors.leftMargin: Style.spacing.md
          anchors.right: bar.left
          anchors.rightMargin: Style.spacing.controlGap
          anchors.baseline: nameText.baseline
          visible: width > Style.space(24)
          text: row.context
          elide: Text.ElideRight
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
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
            width: Math.round(parent.width * Math.max(0, Math.min(1, row.fraction)))
            height: parent.height
            radius: Math.min(Style.cornerRadius, height / 2)
            color: row.provider !== "" && root.colors[row.provider] ? root.colors[row.provider]
              : root.alpha(root.foreground, 0.55)

            Behavior on width {
              enabled: root.populated
              NumberAnimation { duration: root.rowMs; easing.type: Easing.InOutCubic }
            }
          }
        }

        PlainText {
          id: value
          anchors.right: parent.right
          anchors.rightMargin: Style.spacing.md
          anchors.verticalCenter: parent.verticalCenter
          width: Math.max(root.valueWidth, implicitWidth)
          horizontalAlignment: Text.AlignRight
          text: row.valueText
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          font.weight: Font.Medium
          font.features: { "tnum": 1 }
        }
      }
    }
  }

  UsageDisclosure {
    objectName: "costModelDisclosure"
    visible: root.allRows.length > root.collapsedRows
    width: parent.width
    text: "All " + root.allRows.length + (root.mode === "project" ? " folders" : root.mode === "agent" ? " agents" : " models")
    checked: root.expanded
    foreground: root.foreground
    fontFamily: root.fontFamily
    onToggled: root.expandRequested(checked)
  }
}
