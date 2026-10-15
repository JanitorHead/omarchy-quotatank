pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// The Costs tab (DESIGN §4): controls, the total with its change against the previous window, the
// live omp line, the chart, providers, breakdown, when, cache and token details. Panel's footer shows
// `sourceSummary` beside the update time.
Item {
  id: root

  property var payload: ({})
  property bool loading: false
  property string errorText: ""
  property int periodDays: 30
  property string metric: "cost"
  property bool tokenDetailsExpanded: false
  property bool modelsExpanded: false
  property string breakdownMode: "model"
  // Hovering a provider row dims the others in the chart; clicking isolates and rescales to it.
  property string focusedProvider: ""
  property string isolatedProvider: ""
  property bool isolateHintSeen: false
  // Panel's Motion (DESIGN §1) and OmpActivity (live omp requests); either may be null.
  property var motion: null
  property var ompActivity: null
  property string clockFormat: "HH:mm"
  readonly property bool menuOpen: metricMenu.menuOpen
  readonly property int displayedPeriodDays: payload && payload.period && Number(payload.period.days) > 0
    ? Number(payload.period.days) : periodDays
  readonly property bool incompletePricing: Number(totals.unpricedRecords || 0) > 0
  readonly property bool lowPricingCoverage: incompletePricing && priceCoverage(totals) < 0.9
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property color surface: Commons.Color.popups.background
  property string fontFamily: Style.font.family

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property var totals: payload && payload.totals ? payload.totals : ({})
  readonly property var providers: payload ? UsageLogic.listOrEmpty(payload.providers) : []
  readonly property var models: payload ? UsageLogic.listOrEmpty(payload.models) : []
  readonly property var periods: payload ? UsageLogic.listOrEmpty(payload.periods) : []
  readonly property bool hasResult: !!(payload && payload.generatedAt && periods.length > 0)
  readonly property bool hourly: displayedPeriodDays === 1
  readonly property real chartMaximum: chart.chartMaximum
  // Chart series in the payload's provider order: brand colours (the cost chart always uses them),
  // theme colours for sources without one.
  readonly property var series: {
    var list = []
    var spare = 0
    var fallbacks = [Commons.Color.accent, alpha(foreground, 0.7), alpha(Commons.Color.accent, 0.5), alpha(foreground, 0.4)]
    for (var i = 0; i < providers.length; i++) {
      var id = String(providers[i] && providers[i].id || "")
      if (id === "") continue
      var brand = UsageLogic.providerAccent(id, "")
      list.push({ id: id, name: String(providers[i].name || id), color: brand !== "" ? brand : fallbacks[spare++ % fallbacks.length] })
    }
    return list
  }
  readonly property var seriesColors: {
    var map = {}
    for (var i = 0; i < series.length; i++) map[series[i].id] = series[i].color
    return map
  }
  readonly property var breakdownModes: UsageLogic.costBreakdownModes(payload)
  readonly property string shownBreakdownMode: breakdownModes.some(function(mode) { return mode.value === root.breakdownMode })
    ? breakdownMode : "model"
  // What omp's live requests add to this scan (UsageLogic.costLiveTotals over OmpActivity's request
  // log): only when the scan read the omp sessions on this computer, and only the requests after the
  // scan started, so one that came in while the scan ran is never lost. Null without any.
  readonly property bool scanHasOmp: UsageLogic.costScanHasOmp(payload ? payload.sources : [])
  // The log grows in place; its revision says when.
  readonly property int liveRevision: ompActivity && typeof ompActivity.requestRevision === "number" ? ompActivity.requestRevision : 0
  readonly property var live: {
    var revision = liveRevision
    if (!hasResult || !scanHasOmp || !ompActivity || revision <= 0) return null
    var totals = UsageLogic.costLiveTotals(ompActivity.requestLog, Date.parse(String(payload.generatedAt)) / 1000,
      series.map(function(entry) { return entry.id }))
    return totals.requests > 0 ? totals : null
  }
  property real nowSeconds: Date.now() / 1000
  readonly property bool liveActive: !!live && nowSeconds - live.lastAt <= 120
  readonly property var delta: UsageLogic.costDelta(currentTotal(),
    payload && payload.previous ? (metric === "tokens" ? payload.previous.totalTokens : payload.previous.costUsd) : null)
  readonly property string deltaText: hasResult ? UsageLogic.costDeltaText(delta, displayedPeriodDays) : ""
  readonly property var cache: UsageLogic.costCacheSummary(totals)
  // "· live" only where something here follows omp as it happens: live requests on top of a scan of
  // this computer's omp sessions, or omp stats elsewhere whose news starts a new scan.
  readonly property var remoteSource: payload ? UsageLogic.readingFor(payload.sources, "omp-remote") : null
  readonly property string sourceSummary: hasResult ? UsageLogic.costSourceSummary(payload.sources, !!ompActivity
    && ompActivity.state === "live" && (scanHasOmp || (!!remoteSource && remoteSource.status === "ok"))) : ""
  // Providers and breakdown share their bar and value columns, so both lists line up.
  readonly property real valueColumnWidth: Math.max(Style.space(40), providerList.widestValue, breakdown.widestValue)
  readonly property real barColumnWidth: Style.space(72)
  readonly property var providerRows: {
    var values = []
    var total = 0
    for (var i = 0; i < providers.length; i++) {
      var row = providers[i] || {}
      var base = UsageLogic.costMetricValue(row, metric)
      var extra = liveAmount(String(row.id || ""))
      var value = unavailable(row) ? null : base === null ? (extra > 0 ? extra : null) : base + extra
      values.push(value)
      if (value !== null) total += value
    }
    var rows = []
    for (var j = 0; j < providers.length; j++) {
      var item = providers[j] || {}
      var id = String(item.id || "")
      if (id === "") continue
      rows.push({
        id: id, name: String(item.name || id), color: seriesColors[id] || foreground,
        valueText: unavailable(item) ? "—" : format(values[j]),
        share: total > 0 && values[j] !== null ? values[j] / total : 0,
        meta: unavailable(item) ? providerMetaText(item) : ""
      })
    }
    return rows
  }

  signal periodRequested(int days)
  signal menuClosed()

  implicitHeight: content.implicitHeight
  onMetricChanged: tokenDetailsExpanded = metric === "tokens"
  onVisibleChanged: if (!visible) {
    closeMenu()
    focusedProvider = ""
  }
  // A new request starts the live line's two minutes again.
  onLiveRevisionChanged: {
    nowSeconds = Date.now() / 1000
    liveExpiry.restart()
  }
  onProvidersChanged: {
    var known = providers.some(function(row) { return row && String(row.id) === root.isolatedProvider })
    if (!known) isolatedProvider = ""
    if (!providers.some(function(row) { return row && String(row.id) === root.focusedProvider })) focusedProvider = ""
  }

  function openMetricMenu() { metricMenu.openMenu() }
  function closeMenu() { metricMenu.closeMenu() }

  function alpha(color, opacity) {
    return Qt.rgba(color.r, color.g, color.b, opacity)
  }

  function priceCoverage(row) {
    if (!row || Number(row.records) <= 0) return 1
    return Math.max(0, Math.min(1, Number(row.pricedRecords || 0) / Number(row.records)))
  }

  function unavailable(row) {
    return !!row && (row.status === "missing" || row.status === "failed" || row.historyStatus === "unavailable")
  }

  function format(value) {
    return metric === "tokens" ? UsageLogic.formatTokens(value) : UsageLogic.formatUsd(value)
  }

  function primaryValue(row) {
    if (unavailable(row)) return "—"
    return metric === "tokens" ? UsageLogic.formatTokens(row ? row.totalTokens : 0)
      : UsageLogic.formatUsd(row ? row.costUsd : null)
  }

  // Live omp spend since the scan for one provider (or every provider), in the chosen metric.
  function liveAmount(providerId) {
    if (!live) return 0
    var values = metric === "tokens" ? live.tokens : live.cost
    if (providerId !== undefined) return Number(values[providerId] || 0)
    var sum = 0
    for (var id in values) sum += Number(values[id] || 0)
    return sum
  }

  function currentTotal() {
    if (unavailable(totals)) return null
    var base = UsageLogic.costMetricValue(totals, metric)
    return base === null ? null : base + liveAmount()
  }

  function totalText() {
    var base = primaryValue(totals)
    if (base === "—" || liveAmount() <= 0) return base
    return format(currentTotal())
  }

  function liveText() {
    var amount = liveAmount()
    if (amount <= 0) return "Live from omp"
    return "Live from omp · +" + (metric === "tokens" ? UsageLogic.formatTokens(amount) + " tokens" : UsageLogic.formatUsd(amount))
      + " since the last scan"
  }

  function toggleIsolation(providerId) {
    if (providers.length < 2) return
    isolateHintSeen = true
    focusedProvider = ""
    isolatedProvider = isolatedProvider === providerId ? "" : providerId
  }

  function providerMetaText(row) {
    if (!row) return ""
    if (row.status === "missing" || row.status === "failed")
      return String(row.message || "Usage coverage unavailable")
    if (row.historyStatus === "unavailable") return "History unavailable"
    return UsageLogic.formatTokens(row.totalTokens) + " tokens"
      + (Number(row.records || 0) > 0
        ? " · " + pricingPercent(row) + " of requests priced" : "")
  }

  function pricingPercent(row) {
    // A small unpriced remainder must never round up to complete coverage.
    return Math.min(Number(row.unpricedRecords || 0) > 0 ? 99 : 100,
      Math.floor(priceCoverage(row) * 100)) + "%"
  }

  function pricingNotice() {
    if (!lowPricingCoverage) return ""
    if (Number(totals.pricedRecords || 0) === 0) return "Pricing unavailable · tokens are still included"
    return "Incomplete estimate · " + pricingPercent(totals) + " of requests priced"
  }

  // The period behind the figures, which can differ from the selected tab while a new scan runs.
  function summaryDetail() {
    var records = Number(totals.records || 0)
    var parts = [displayedPeriodDays === 1 ? "24 hours" : displayedPeriodDays + " days",
      UsageLogic.costRequestsText(records)]
    if (totals.sessions !== null && totals.sessions !== undefined)
      parts.push(UsageLogic.costCount(totals.sessions) + (Number(totals.sessions) === 1 ? " session" : " sessions"))
    return parts.join(" · ")
  }

  function summaryLine() {
    var requests = UsageLogic.costRequestsText(Number(totals.records || 0) + (live ? live.requests : 0))
    return (metric === "cost" ? "Estimated API value, not subscription spend" : "Tokens processed, cache reads included")
      + " · " + requests
  }

  function chartRange() {
    if (periods.length === 0) return ""
    if (hourly) return "last 24 hours"
    var first = UsageLogic.costBucketDate(periods[0].start)
    var last = UsageLogic.costBucketDate(periods[periods.length - 1].start)
    return first && last ? UsageLogic.costMonthDay(first) + " – " + UsageLogic.costMonthDay(last) : ""
  }

  // Ends the live line two minutes after the last request; one shot per request, never a loop.
  Timer {
    id: liveExpiry
    interval: Math.max(1000, root.live ? Math.ceil((root.live.lastAt + 121) * 1000 - Date.now()) : 1000)
    onTriggered: root.nowSeconds = Date.now() / 1000
  }

  Column {
    id: content
    width: parent.width
    spacing: Style.spacing.xxl

    Item {
      id: costControls
      width: parent.width
      implicitHeight: Math.max(metricMenu.implicitHeight, periodSwitch.implicitHeight)

      UsageSelect {
        id: metricMenu
        objectName: "costMetricMenu"
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, Math.max(0, costControls.width - periodSwitch.width - Style.spacing.md))
        options: [
          { value: "cost", label: "API estimate" },
          { value: "tokens", label: "Tokens" }
        ]
        value: root.metric
        label: "Metric"
        foreground: root.foreground
        surface: root.surface
        fontFamily: root.fontFamily
        onChanged: function(value) { root.metric = value }
        onMenuClosed: root.menuClosed()
      }

      UsageTabs {
        id: periodSwitch
        objectName: "costPeriodTabs"
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        options: [
          { value: "1", label: "24H" },
          { value: "7", label: "7D" },
          { value: "30", label: "30D" }
        ]
        value: String(root.periodDays)
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.caption
        motion: root.motion
        onChanged: function(value) { root.periodRequested(Number(value)) }
      }
    }

    Text {
      visible: root.loading && !root.hasResult
      width: parent.width
      topPadding: Style.spacing.huge
      bottomPadding: Style.spacing.huge
      text: "Loading session history…"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      horizontalAlignment: Text.AlignHCenter
    }

    Ui.BorderSurface {
      id: errorCard
      visible: root.errorText !== "" && !root.hasResult
      width: parent.width
      implicitHeight: errorText.implicitHeight + contentTopInset + contentBottomInset
      color: root.alpha(root.urgent, 0.09)
      borderSpec: Border.flat(root.alpha(root.urgent, 0.4), Style.spacing.hairline)
      padding: Style.spacing.xxl
      radius: Style.cornerRadius

      Text {
        id: errorText
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: errorCard.contentLeftInset
        anchors.rightMargin: errorCard.contentRightInset
        anchors.topMargin: errorCard.contentTopInset
        text: root.errorText
        textFormat: Text.PlainText
        color: root.urgent
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }
    }

    Column {
      visible: root.hasResult
      width: parent.width
      spacing: Style.spacing.labelGap

      Item {
        width: parent.width
        implicitHeight: Math.max(total.implicitHeight, deltaChip.visible ? deltaChip.height : 0)

        RollingNumber {
          id: total
          objectName: "costSummaryValue"
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          width: Math.min(implicitWidth, parent.width)
          text: root.totalText()
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.display
          font.weight: Font.DemiBold
          motion: root.motion

          HoverHandler { id: totalHover }
          Ui.PanelToolTip {
            visible: totalHover.hovered
            text: root.summaryDetail()
            fontFamily: root.fontFamily
          }
        }

        // Change against the equal window before; a direction, not a verdict, so it stays neutral.
        Rectangle {
          id: deltaChip
          objectName: "costDelta"
          readonly property string text: root.deltaText
          visible: text !== ""
          anchors.left: total.right
          anchors.leftMargin: Style.spacing.lg
          anchors.verticalCenter: total.verticalCenter
          width: deltaLabel.implicitWidth + Style.spacing.lg * 2
          height: deltaLabel.implicitHeight + Style.spacing.sm
          radius: height / 2
          color: root.alpha(root.foreground, 0.08)
          border.width: Style.spacing.hairline
          border.color: root.alpha(root.foreground, 0.22)
          Accessible.role: Accessible.StaticText
          Accessible.name: root.delta ? (root.delta.direction === 0 ? text
            : (root.delta.direction > 0 ? "Up " : "Down ") + Math.abs(root.delta.percent) + "% on the previous "
              + UsageLogic.costPeriodPhrase(root.displayedPeriodDays)) : ""

          Text {
            id: deltaLabel
            anchors.centerIn: parent
            text: deltaChip.text
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
          }
        }
      }

      Text {
        objectName: "costSummaryLine"
        width: parent.width
        text: root.summaryLine()
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Text {
        objectName: "costPricingNotice"
        visible: root.metric === "cost" && root.lowPricingCoverage
        width: parent.width
        text: root.pricingNotice()
        color: root.urgent
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      // Only while omp reports requests (last 2 minutes); the dot is static, the figures move.
      Item {
        id: liveLine
        objectName: "costLiveLine"
        readonly property bool shown: root.liveActive
        width: parent.width
        height: shown ? liveRow.implicitHeight + Style.spacing.xs : 0
        visible: height > 0
        clip: true
        opacity: shown ? 1 : 0

        Behavior on height {
          NumberAnimation { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
        }
        Behavior on opacity {
          OpacityAnimator { duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
        }

        Row {
          id: liveRow
          y: Style.spacing.xs
          spacing: Style.spacing.md

          Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(6)
            height: width
            radius: width / 2
            color: Commons.Color.accent
          }

          Text {
            objectName: "costLiveText"
            text: root.liveText()
            color: Commons.Color.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.weight: Font.Medium
          }
        }
      }
    }

    Column {
      visible: root.hasResult
      width: parent.width
      spacing: Style.spacing.lg

      Item {
        width: parent.width
        implicitHeight: chartTitle.implicitHeight

        Ui.PanelSectionHeader {
          id: chartTitle
          anchors.left: parent.left
          text: root.hourly ? "BY HOUR" : "BY DAY"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Text {
          anchors.right: parent.right
          anchors.baseline: chartTitle.baseline
          text: root.chartRange()
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }

      CostChart {
        id: chart
        objectName: "costChart"
        width: parent.width
        periods: root.periods
        series: root.series
        metric: root.metric
        hourly: root.hourly
        focusedProvider: root.focusedProvider
        isolatedProvider: root.isolatedProvider
        live: root.live
        motion: root.motion
        foreground: root.foreground
        urgent: root.urgent
        fontFamily: root.fontFamily
        clockFormat: root.clockFormat
      }

      Text {
        visible: root.periods.some(function(row) { return row.historyStatus === "unavailable" })
        width: parent.width
        text: "Outlined gaps: history unavailable"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }

    CostProviders {
      id: providerList
      objectName: "costProviders"
      visible: root.hasResult && root.providers.length > 0
      width: parent.width
      rows: root.providerRows
      focusedProvider: root.focusedProvider
      isolatedProvider: root.isolatedProvider
      hintSeen: root.isolateHintSeen
      valueWidth: root.valueColumnWidth
      barWidth: root.barColumnWidth
      motion: root.motion
      foreground: root.foreground
      urgent: root.urgent
      fontFamily: root.fontFamily
      onFocusRequested: function(providerId) { if (root.isolatedProvider === "") root.focusedProvider = providerId }
      onIsolateRequested: function(providerId) { root.toggleIsolation(providerId) }
    }

    CostBreakdown {
      id: breakdown
      objectName: "costBreakdown"
      visible: root.hasResult && allRows.length > 0
      width: parent.width
      payload: root.payload
      metric: root.metric
      mode: root.shownBreakdownMode
      modes: root.breakdownModes
      expanded: root.modelsExpanded
      colors: root.seriesColors
      surface: root.surface
      valueWidth: root.valueColumnWidth
      barWidth: root.barColumnWidth
      motion: root.motion
      foreground: root.foreground
      fontFamily: root.fontFamily
      onModeRequested: function(mode) { root.breakdownMode = mode }
      onExpandRequested: function(expanded) { root.modelsExpanded = expanded }
    }

    CostHeatmap {
      objectName: "costWhen"
      visible: root.hasResult && hasActivity
      width: parent.width
      heatmap: root.payload ? root.payload.heatmap : null
      metric: root.metric
      clockFormat: root.clockFormat
      foreground: root.foreground
      urgent: root.urgent
      fontFamily: root.fontFamily
    }

    // Laid out like the list rows above: label, then the share in the bar and value columns.
    Item {
      objectName: "costCacheLine"
      visible: root.hasResult && root.cache !== null
      width: parent.width
      implicitHeight: Math.max(cacheTitle.implicitHeight, cacheValue.implicitHeight)
      Accessible.role: Accessible.StaticText
      Accessible.name: root.cache ? root.cache.text : ""

      Ui.PanelSectionHeader {
        id: cacheTitle
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: "CACHE"
        foreground: root.foreground
        fontFamily: root.fontFamily
      }

      Text {
        anchors.left: cacheTitle.right
        anchors.leftMargin: Style.spacing.controlGap
        anchors.right: cacheMeter.left
        anchors.rightMargin: Style.spacing.controlGap
        anchors.verticalCenter: parent.verticalCenter
        text: root.cache ? root.cache.label : ""
        elide: Text.ElideRight
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      Item {
        id: cacheMeter
        anchors.right: cacheValue.left
        anchors.rightMargin: Style.spacing.controlGap
        anchors.verticalCenter: parent.verticalCenter
        width: root.barColumnWidth
        height: Style.space(4)

        Rectangle {
          anchors.fill: parent
          radius: Math.min(Style.cornerRadius, height / 2)
          color: root.alpha(root.foreground, 0.08)
        }

        Rectangle {
          width: Math.round(parent.width * (root.cache ? root.cache.share : 0))
          height: parent.height
          radius: Math.min(Style.cornerRadius, height / 2)
          color: root.alpha(root.foreground, 0.55)
        }
      }

      Text {
        id: cacheValue
        anchors.right: parent.right
        anchors.rightMargin: Style.spacing.md
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(root.valueColumnWidth, implicitWidth)
        horizontalAlignment: Text.AlignRight
        text: root.cache ? root.cache.percent : ""
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.weight: Font.Medium
        font.features: { "tnum": 1 }
      }
    }

    Column {
      visible: root.hasResult
      width: parent.width
      spacing: Style.spacing.lg

      UsageDisclosure {
        objectName: "costTokenDisclosure"
        width: parent.width
        text: "Token details"
        checked: root.tokenDetailsExpanded
        foreground: root.foreground
        fontFamily: root.fontFamily
        onToggled: root.tokenDetailsExpanded = checked
      }

      Grid {
        objectName: "costTokenDetails"
        visible: root.tokenDetailsExpanded
        width: parent.width
        columns: 2
        columnSpacing: Style.spacing.xxl
        rowSpacing: Style.spacing.lg

        Repeater {
          model: [
            { label: "Processed", value: UsageLogic.formatTokens(root.totals.totalTokens) },
            { label: "Cached input", value: UsageLogic.formatTokens(root.totals.cachedInputTokens) },
            { label: "Uncached input", value: UsageLogic.formatTokens(root.totals.uncachedInputTokens) },
            { label: "Output", value: UsageLogic.formatTokens(root.totals.outputTokens) },
            { label: "Reasoning output", value: UsageLogic.formatTokens(root.totals.reasoningTokens) },
            { label: "Cache savings", value: UsageLogic.formatUsd(root.totals.cacheSavingsUsd) }
          ]

          delegate: Column {
            required property var modelData
            width: (content.width - Style.spacing.xxl) / 2
            spacing: Style.spacing.labelGap

            Text {
              text: parent.modelData.label
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
            Text {
              text: parent.modelData.value
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              font.weight: Font.Medium
            }
          }
        }
      }
      Column {
        visible: root.tokenDetailsExpanded
        width: parent.width
        spacing: Style.spacing.md

        Repeater {
          model: root.providers
          delegate: Text {
            required property var modelData
            width: parent.width
            text: String(modelData.name || modelData.id || "") + " · " + root.providerMetaText(modelData)
            textFormat: Text.PlainText
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }
    }

    Text {
      visible: root.hasResult && Number(root.totals.records || 0) === 0
      width: parent.width
      topPadding: Style.spacing.huge
      bottomPadding: Style.spacing.huge
      text: root.totals.historyStatus === "unavailable"
        ? "Session history is unavailable for this period." : "No transcript usage was found in this period."
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.WordWrap
    }
  }
}
