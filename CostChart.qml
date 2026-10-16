pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// Stacked bars per provider, keyed by bucket time so a bar keeps its delegate: when the period
// changes, bars both ranges share move and resize, new ones grow from the baseline and old ones
// shrink away. Hover shows a guide and a readout; a focused provider dims the others, an isolated
// one rescales the chart to itself. Routine refreshes only change bar heights that changed.
Item {
  id: root

  property var periods: []
  // Series in stack order, bottom first: [{ id, name, color }].
  property var series: []
  property string metric: "cost"
  property bool hourly: false
  property string focusedProvider: ""
  property string isolatedProvider: ""
  // Requests since the scan (UsageLogic.costLiveTotals), added to the newest bucket.
  property var live: null
  property var motion: null
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family
  property string clockFormat: "HH:mm"
  property int hoveredIndex: -1

  readonly property color dim: Qt.darker(foreground, 1.55)
  // Without Panel's Motion nothing animates, as with reduced motion.
  readonly property int microMs: motion ? motion.duration(motion.micro) : 0
  readonly property int rowMs: motion ? motion.duration(motion.row) : 0
  readonly property int morphMs: motion ? motion.duration(motion.morph) : 0
  readonly property var buckets: buildBuckets()
  readonly property var bucketByKey: {
    var map = {}
    for (var i = 0; i < buckets.length; i++) map[buckets[i].key] = buckets[i]
    return map
  }
  readonly property real chartMaximum: {
    var maximum = 0
    for (var i = 0; i < buckets.length; i++) maximum = Math.max(maximum, buckets[i].shownTotal)
    return maximum
  }
  readonly property real plotHeight: plot.height
  readonly property int barCount: bars.count
  readonly property var hoveredBucket: hoveredIndex >= 0 && hoveredIndex < buckets.length ? buckets[hoveredIndex] : null
  // The readout keeps showing the last hovered bucket while it fades out.
  property int readoutIndex: -1
  readonly property var readoutBucket: readoutIndex >= 0 && readoutIndex < buckets.length ? buckets[readoutIndex] : null
  onHoveredIndexChanged: if (hoveredIndex >= 0) readoutIndex = hoveredIndex
  // Stack order as a string: a refresh with the same providers keeps every segment delegate, so only
  // changed heights animate.
  readonly property string stackIds: series.map(function(entry) { return entry.id }).reverse().join("\n")
  // Where each bucket key sits, replaced in one assignment per change so bars move straight to their
  // new place; bars that leave keep the geometry they had.
  property var layout: ({ slots: 0, index: {} })
  property bool morphing: false
  readonly property int barDuration: morphing ? morphMs : rowMs
  property var modelKeys: []

  implicitHeight: plot.height + Style.spacing.sm + axis.implicitHeight

  onBucketsChanged: sync()
  onIsolatedProviderChanged: startMorph()
  onMetricChanged: startMorph()
  onVisibleChanged: if (!visible) hoveredIndex = -1

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }

  function amountOf(row) {
    if (!row) return 0
    if (metric === "tokens") return Math.max(0, Number(row.totalTokens) || 0)
    return row.costUsd === null || row.costUsd === undefined ? 0 : Math.max(0, Number(row.costUsd) || 0)
  }

  function format(value) {
    return metric === "tokens" ? UsageLogic.formatTokens(value) : UsageLogic.formatUsd(value)
  }

  function buildBuckets() {
    var result = []
    var used = {}
    var rows = UsageLogic.listOrEmpty(periods)
    var extra = live ? (metric === "tokens" ? live.tokens : live.cost) || {} : {}
    for (var i = 0; i < rows.length; i++) {
      var period = rows[i] || {}
      var key = UsageLogic.costBucketKey(period.start)
      if (key === "" || used[key]) key = "i" + i
      used[key] = true
      var raw = {}
      var cells = UsageLogic.listOrEmpty(period.providers)
      for (var j = 0; j < cells.length; j++) {
        var id = String(cells[j] && cells[j].id || "")
        raw[id] = (raw[id] || 0) + amountOf(cells[j])
      }
      if (i === rows.length - 1)
        for (var liveId in extra) raw[liveId] = (raw[liveId] || 0) + Math.max(0, Number(extra[liveId]) || 0)
      var shown = {}
      var total = 0
      var shownTotal = 0
      for (var k = 0; k < series.length; k++) {
        var seriesId = series[k].id
        var value = raw[seriesId] || 0
        total += value
        shown[seriesId] = isolatedProvider !== "" && isolatedProvider !== seriesId ? 0 : value
        shownTotal += shown[seriesId]
      }
      result.push({
        key: key, index: i, start: period.start, date: UsageLogic.costBucketDate(period.start),
        raw: raw, shown: shown, total: total, shownTotal: shownTotal,
        gap: period.historyStatus === "unavailable",
        unpricedRecords: metric === "cost" ? Math.max(0, Number(period.unpricedRecords) || 0) : 0,
        unpriced: metric === "cost" && period.costUsd === null && Number(period.records || 0) > 0
      })
    }
    return result
  }

  function gapFor(slots) {
    return slots > 1 ? Math.max(Style.spacing.xxs, Math.min(Style.space(10), plot.width / slots * 0.18)) : 0
  }

  function barWidthFor(slots) {
    if (slots <= 0) return 0
    return Math.max(1, Math.min(Style.space(56), Math.floor((plot.width - gapFor(slots) * (slots - 1)) / slots)))
  }

  // Bars keep one width; the remainder spreads across the gaps so both ends sit on the plot edges.
  function slotX(index, slots) {
    var width = barWidthFor(slots)
    if (slots <= 1) return Math.round((plot.width - width) / 2)
    return Math.round(index * (plot.width - width) / (slots - 1))
  }

  function slotAt(x) {
    var slots = layout.slots
    if (slots <= 0) return -1
    if (slots === 1) return 0
    var step = (plot.width - barWidthFor(slots)) / (slots - 1)
    return Math.max(0, Math.min(slots - 1, Math.round((x - barWidthFor(slots) / 2) / step)))
  }

  function startMorph() {
    if (!visible || morphMs <= 0) return
    morphing = true
    morphTimer.restart()
  }

  // Keeps the bar model in bucket order with moves and inserts, never clear()+append(), so the bars of
  // timestamps both ranges share keep their delegates and glide to their new place. Bars that leave
  // stay where they were for a moment and shrink away; new ones grow from the baseline.
  function sync() {
    var keys = []
    var index = {}
    for (var i = 0; i < buckets.length; i++) {
      keys.push(buckets[i].key)
      index[buckets[i].key] = i
    }
    var same = keys.length === layout.slots
    for (var s = 0; same && s < keys.length; s++) same = layout.index[keys[s]] === s
    if (same) return
    var animate = visible && layout.slots > 0 && morphMs > 0
    if (animate) startMorph()
    var revive = []
    for (var m = modelKeys.length - 1; m >= 0; m--) {
      var entry = bars.get(m)
      if (index[modelKeys[m]] !== undefined) {
        if (entry.leaving) revive.push(modelKeys[m])
        continue
      }
      if (entry.leaving) continue
      if (animate) {
        // Geometry first: the bar must stay exactly where it stands once it is flagged as leaving.
        bars.setProperty(m, "exitX", slotX(layout.index[modelKeys[m]], layout.slots))
        bars.setProperty(m, "exitWidth", barWidthFor(layout.slots))
        bars.setProperty(m, "leaving", true)
      } else {
        bars.remove(m, 1)
        modelKeys.splice(m, 1)
      }
    }
    layout = { slots: keys.length, index: index }
    for (var r = 0; r < revive.length; r++) bars.setProperty(modelKeys.indexOf(revive[r]), "leaving", false)
    UsageLogic.syncKeyedOrder({
      count: function() { return root.modelKeys.length },
      keyAt: function(position) { return root.modelKeys[position] },
      move: function(from, to) {
        bars.move(from, to, 1)
        root.modelKeys.splice(to, 0, root.modelKeys.splice(from, 1)[0])
      },
      insert: function(position, key) {
        bars.insert(position, { key: key, leaving: false, entering: animate, exitX: 0, exitWidth: 0 })
        root.modelKeys.splice(position, 0, key)
      }
    }, keys)
    if (bars.count > keys.length) purgeTimer.restart()
    if (hoveredIndex >= keys.length) hoveredIndex = -1
  }

  function purgeLeaving() {
    for (var i = bars.count - 1; i >= 0; i--) {
      if (!bars.get(i).leaving) continue
      bars.remove(i, 1)
      modelKeys.splice(i, 1)
    }
  }

  // For tests and the mock harness: the live bar drawn for a bucket key, or null.
  function barItem(key) {
    for (var i = 0; i < barRepeater.count; i++) {
      var item = barRepeater.itemAt(i)
      if (item && item.key === key && !item.leaving) return item
    }
    return null
  }

  // The tallest segment drawn for a provider, in pixels.
  function maxSegmentHeight(providerId) {
    var tallest = 0
    for (var i = 0; i < barRepeater.count; i++) {
      var item = barRepeater.itemAt(i)
      if (item && !item.leaving) tallest = Math.max(tallest, item.segmentHeight(providerId))
    }
    return tallest
  }

  function bucketLabel(bucket) {
    if (!bucket || !bucket.date) return ""
    var last = bucket.index === buckets.length - 1
    if (hourly) {
      var start = Qt.formatTime(bucket.date, clockFormat)
      return start + " – " + (last ? "now" : Qt.formatTime(new Date(bucket.date.getTime() + 3600000), clockFormat))
    }
    return last ? "Today" : UsageLogic.costDayName(bucket.date) + ", " + UsageLogic.costMonthDay(bucket.date)
  }

  function axisLabel(index) {
    var bucket = index >= 0 && index < buckets.length ? buckets[index] : null
    if (!bucket || !bucket.date) return ""
    return hourly ? Qt.formatTime(bucket.date, clockFormat) : UsageLogic.costMonthDay(bucket.date)
  }

  function colorFor(providerId) {
    for (var i = 0; i < series.length; i++) if (series[i].id === providerId) return series[i].color
    return foreground
  }

  ListModel { id: bars }

  // Covers the whole morph, including new bars that start growing half a row step late.
  Timer {
    id: morphTimer
    interval: root.morphMs + Math.round(root.rowMs / 2) + 40
    onTriggered: root.morphing = false
  }

  Timer {
    id: purgeTimer
    interval: root.morphMs + 60
    onTriggered: root.purgeLeaving()
  }

  Item {
    id: plot
    width: parent.width
    height: Style.space(96)

    Rectangle {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      height: Style.spacing.hairline
      color: root.alpha(root.foreground, 0.14)
    }

    Repeater {
      id: barRepeater
      model: bars

      delegate: Item {
        id: bar
        required property string key
        required property bool leaving
        required property bool entering
        required property real exitX
        required property real exitWidth
        readonly property int slot: leaving || root.layout.index[key] === undefined ? -1 : root.layout.index[key]
        readonly property var info: leaving ? null : root.bucketByKey[key] || null
        readonly property bool newest: slot >= 0 && slot === root.layout.slots - 1
        property bool revealed: !entering
        // Bars appear at their size; only later changes animate (a period switch, a rescale, a refresh).
        property bool animated: false

        function segmentHeight(providerId) {
          for (var i = 0; i < segments.count; i++) {
            var segment = segments.itemAt(i)
            if (segment && segment.modelData === providerId) return segment.height
          }
          return 0
        }

        x: leaving || slot < 0 ? exitX : root.slotX(slot, root.layout.slots)
        width: leaving || slot < 0 ? exitWidth : root.barWidthFor(root.layout.slots)
        height: plot.height
        // Leaving bars shrink and fade where they stood, quickly and under the bars moving in.
        opacity: leaving ? 0 : 1
        z: leaving ? -1 : 0
        Component.onCompleted: Qt.callLater(function() {
          bar.animated = true
          if (!bar.entering) bar.revealed = true
          else revealDelay.start()
        })

        // New bars start growing once the bars they replace have mostly moved out of their way.
        Timer {
          id: revealDelay
          interval: Math.round(root.rowMs / 2)
          onTriggered: bar.revealed = true
        }

        Behavior on x {
          enabled: root.morphing && bar.animated && !bar.leaving
          XAnimator { duration: root.morphMs; easing.type: Easing.InOutCubic }
        }
        Behavior on width {
          enabled: root.morphing && bar.animated && !bar.leaving
          NumberAnimation { duration: root.morphMs; easing.type: Easing.InOutCubic }
        }
        Behavior on opacity {
          enabled: bar.animated
          OpacityAnimator {
            duration: bar.leaving ? root.rowMs : root.morphMs
            easing.type: bar.leaving ? Easing.InCubic : Easing.OutCubic
          }
        }

        // Outlined: history for this bucket is unavailable, which is not a zero.
        Rectangle {
          objectName: bar.slot >= 0 ? "costHistoryGap-" + bar.slot : ""
          anchors.fill: parent
          visible: !!bar.info && bar.info.gap
          color: root.alpha(root.foreground, 0.035)
          border.width: Style.spacing.hairline
          border.color: root.alpha(root.foreground, 0.15)

          PlainText {
            anchors.centerIn: parent
            text: "—"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Column {
          id: stack
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom

          Repeater {
            id: segments
            // Top of the stack first: the Column grows upward from the baseline.
            model: root.stackIds === "" ? [] : root.stackIds.split("\n")

            delegate: Rectangle {
              required property string modelData
              readonly property real amount: bar.revealed && bar.info ? Number(bar.info.shown[modelData] || 0) : 0
              width: stack.width
              height: root.chartMaximum > 0 ? amount / root.chartMaximum * plot.height : 0
              color: root.colorFor(modelData)
              opacity: root.focusedProvider !== "" && root.focusedProvider !== modelData ? 0.18 : 1

              // New bars grow out (enter), leaving ones shrink away (exit), the rest resize (move).
              Behavior on height {
                enabled: bar.animated
                NumberAnimation {
                  duration: bar.leaving ? root.rowMs : root.barDuration
                  easing.type: bar.leaving ? Easing.InCubic : bar.entering ? Easing.OutCubic : Easing.InOutCubic
                }
              }
              Behavior on opacity {
                OpacityAnimator { duration: root.microMs; easing.type: Easing.OutCubic }
              }
            }
          }
        }

        // The newest bucket (this hour, today) keeps growing until the next scan: a hairline marks its top.
        Rectangle {
          visible: bar.newest && stack.height >= Style.spacing.hairline
          y: stack.y - Style.spacing.hairline * 2
          width: parent.width
          height: Style.spacing.hairline
          color: root.alpha(root.foreground, 0.7)
        }

        // Requests the price table could not price, in a bucket that otherwise reads as no cost.
        Rectangle {
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          height: Math.max(2, Style.spacing.hairline)
          visible: !!bar.info && bar.info.unpriced
          color: root.urgent
          opacity: 0.8
        }
      }
    }

    Rectangle {
      id: guide
      visible: root.hoveredBucket !== null
      x: root.hoveredIndex >= 0
        ? root.slotX(root.hoveredIndex, root.layout.slots) + Math.floor(root.barWidthFor(root.layout.slots) / 2) : 0
      width: Style.spacing.hairline
      height: plot.height
      color: root.alpha(root.foreground, 0.55)
    }

    HoverHandler {
      id: hover
      onPointChanged: if (hovered) root.hoveredIndex = root.slotAt(point.position.x)
      onHoveredChanged: root.hoveredIndex = hovered ? root.slotAt(point.position.x) : -1
    }

    Ui.BorderSurface {
      id: readout
      objectName: "costChartReadout"
      readonly property bool shown: root.hoveredBucket !== null
      readonly property var bucket: root.readoutBucket
      readonly property real anchorX: root.readoutIndex >= 0
        ? root.slotX(root.readoutIndex, root.layout.slots) + Math.floor(root.barWidthFor(root.layout.slots) / 2) : 0
      readonly property bool leftSide: anchorX > plot.width * 0.55
      z: 2
      opacity: shown ? 1 : 0
      x: Math.max(0, Math.min(plot.width - width,
        leftSide ? anchorX - width - Style.spacing.md : anchorX + Style.spacing.md))
      y: 0
      width: Math.max(Style.space(150), readoutColumn.implicitWidth + contentLeftInset + contentRightInset)
      implicitHeight: readoutColumn.implicitHeight + contentTopInset + contentBottomInset
      color: Commons.Color.tooltip.background
      borderSpec: Border.localOrSurfaceSpec("tooltip", "border", Commons.Color.tooltip.border,
        Commons.Color.tooltip.border, Style.normalBorderWidth)
      radius: Style.cornerRadius
      padding: Style.spacing.md

      Behavior on opacity {
        OpacityAnimator {
          duration: !root.motion ? 0 : root.motion.duration(readout.shown ? root.motion.popIn : root.motion.popOut)
          easing.type: readout.shown ? Easing.OutCubic : Easing.InCubic
        }
      }

      Column {
        id: readoutColumn
        x: readout.contentLeftInset
        y: readout.contentTopInset
        width: readout.width - readout.contentLeftInset - readout.contentRightInset
        spacing: Style.spacing.xs

        ReadoutLine {
          objectName: "costChartReadoutTitle"
          width: parent.width
          label: root.bucketLabel(readout.bucket)
          value: readout.bucket
            ? root.format(root.isolatedProvider !== "" ? readout.bucket.shownTotal : readout.bucket.total) : ""
          strong: true
        }

        Repeater {
          model: readout.bucket ? root.series.filter(function(entry) {
            return (root.isolatedProvider === "" || root.isolatedProvider === entry.id)
              && Number(readout.bucket.raw[entry.id] || 0) > 0
          }).reverse() : []

          delegate: ReadoutLine {
            required property var modelData
            width: readoutColumn.width
            swatch: modelData.color
            label: modelData.name
            value: root.format(readout.bucket ? readout.bucket.raw[modelData.id] || 0 : 0)
          }
        }

        PlainText {
          visible: !!readout.bucket && readout.bucket.gap
          text: "History unavailable"
          color: Qt.darker(Commons.Color.tooltip.text, 1.25)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        PlainText {
          visible: !!readout.bucket && readout.bucket.unpricedRecords > 0
          text: readout.bucket ? UsageLogic.costRequestsText(readout.bucket.unpricedRecords) + " not priced" : ""
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  Item {
    id: axis
    anchors.top: plot.bottom
    anchors.topMargin: Style.spacing.sm
    width: parent.width
    implicitHeight: axisStart.implicitHeight

    PlainText {
      id: axisStart
      anchors.left: parent.left
      text: root.axisLabel(0)
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }

    PlainText {
      anchors.horizontalCenter: parent.horizontalCenter
      text: root.axisLabel(Math.floor(root.buckets.length / 2))
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }

    PlainText {
      anchors.right: parent.right
      text: root.hourly ? "now" : "today"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  // One readout row: optional series swatch, label, value on the right.
  component ReadoutLine: Item {
    id: line
    property color swatch: "transparent"
    property string label: ""
    property string value: ""
    property bool strong: false
    readonly property bool hasSwatch: swatch.a > 0

    implicitWidth: (hasSwatch ? mark.width + Style.spacing.sm : 0) + labelText.implicitWidth
      + Style.spacing.xxl + valueText.implicitWidth
    implicitHeight: Math.max(labelText.implicitHeight, valueText.implicitHeight)

    Rectangle {
      id: mark
      visible: line.hasSwatch
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(6)
      height: width
      radius: Math.min(Style.cornerRadius, Style.space(1))
      color: line.swatch
    }

    PlainText {
      id: labelText
      anchors.left: parent.left
      anchors.leftMargin: line.hasSwatch ? mark.width + Style.spacing.sm : 0
      anchors.right: valueText.left
      anchors.rightMargin: Style.spacing.lg
      anchors.verticalCenter: parent.verticalCenter
      text: line.label
      elide: Text.ElideRight
      color: line.strong ? Commons.Color.tooltip.text : Qt.darker(Commons.Color.tooltip.text, 1.25)
      font.family: root.fontFamily
      font.pixelSize: line.strong ? Style.font.bodySmall : Style.font.caption
      font.weight: line.strong ? Font.DemiBold : Font.Normal
    }

    PlainText {
      id: valueText
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: line.value
      color: Commons.Color.tooltip.text
      font.family: root.fontFamily
      font.pixelSize: line.strong ? Style.font.bodySmall : Style.font.caption
      font.weight: line.strong ? Font.DemiBold : Font.Medium
      font.features: { "tnum": 1 }
    }
  }
}
