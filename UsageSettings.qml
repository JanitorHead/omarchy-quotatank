pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Effects
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// Settings: an index of pages, each one level deep. Every control saves the moment it changes, so
// the bar and Limits can be compared without leaving the page. Secrets are the exception: they are
// written to a private file by scripts/management-key.py and need an explicit Save.
Column {
  id: root

  property var settings: ({})
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property color surface: Commons.Color.popups.background
  property string fontFamily: Style.font.family
  property string accountDetails: ""
  property var proxyProviders: []
  // The local backend's latest payload ({ providers, detected, generatedAt }) and whether a refresh
  // is running: Settings → Providers shows each provider's state from them.
  property var usagePayload: null
  property bool usageLoading: false
  property var costSources: []
  // "" is the index; otherwise one of the page ids below.
  property string page: ""
  property string errorText: ""
  readonly property bool saving: keyWriter.running
  property alias priceEditor: prices
  readonly property string proxyName: "CLIProxyAPI"
  readonly property bool proxyMode: value("usageSource", "direct") === "cliproxy"
  readonly property string quotaMode: String(value("quotaMode", "Used")) === "Remaining" ? "Remaining" : "Used"
  // Each monitored provider is a card like the ones in Limits (same fill, border, and corners), so
  // its switches, key, and Customize read as one block.
  readonly property real providerCardRadius: value("squareUsageCards", true) === true ? 0 : Style.cornerRadius
  readonly property real providerCardPadding: Style.spacing.lg
  readonly property real providerCardInset: providerCardPadding
    + Border.right(Border.controlSpec("normal", foreground, Commons.Color.accent, urgent))
  readonly property bool percentageDisplay: String(value("barDisplayMode", "Percentages")) === "Percentages"
  readonly property var enabledProviders: UsageLogic.listOrEmpty(value("enabledProviders", UsageLogic.DEFAULT_SETTINGS.enabledProviders))
  readonly property var barProviders: UsageLogic.listOrEmpty(value("barProviders", UsageLogic.DEFAULT_SETTINGS.barProviders))
  readonly property var dismissedProviders: UsageLogic.listOrEmpty(value("dismissedProviders", UsageLogic.DEFAULT_SETTINGS.dismissedProviders))
  readonly property var moneyProviderNames: {
    var names = []
    if (proxyMode) return names
    for (var i = 0; i < UsageLogic.LOCAL_PROVIDERS.length; i++)
      if (UsageLogic.LOCAL_PROVIDERS[i].money && monitored(UsageLogic.LOCAL_PROVIDERS[i].id)) names.push(UsageLogic.LOCAL_PROVIDERS[i].name)
    return names
  }
  readonly property bool moneyMonitored: moneyProviderNames.length > 0
  readonly property var providerOptions: UsageLogic.orderProviders(proxyMode ? UsageLogic.listOrEmpty(proxyProviders) : UsageLogic.LOCAL_PROVIDERS, value("providerOrder", "[]"))
  readonly property var allProviderIds: {
    var ids = UsageLogic.LOCAL_PROVIDER_IDS.slice()
    for (var i = 0; i < proxyProviders.length; i++)
      if (!UsageLogic.contains(ids, proxyProviders[i].id)) ids.push(proxyProviders[i].id)
    return ids
  }
  // Saving a key clears the backend's payload until the next refresh; placing providers from the last
  // payload that arrived keeps the rows from jumping in the meantime.
  property var lastPayload: null
  readonly property var shownReadings: lastPayload ? UsageLogic.listOrEmpty(lastPayload.providers) : []
  readonly property var shownDetected: lastPayload ? UsageLogic.listOrEmpty(lastPayload.detected) : []
  readonly property var shownInstalled: lastPayload && lastPayload.installed !== undefined ? UsageLogic.listOrEmpty(lastPayload.installed) : null
  // The provider whose sign-in or install was just started from here, until its next good reading.
  property string pendingSetup: ""
  onShownReadingsChanged: {
    var reading = UsageLogic.readingFor(shownReadings, pendingSetup)
    if (pendingSetup !== "" && reading && reading.status === "ok") pendingSetup = ""
  }
  readonly property var sections: UsageLogic.providerSections(proxyMode ? [] : providerOptions,
    enabledProviders, dismissedProviders, shownReadings, shownDetected, settings)
  // The draggable rows: every proxy provider, or the local providers in use.
  readonly property var providerRows: proxyMode ? providerOptions : sections.listed
  property string providerFilter: ""
  readonly property int moreCount: sections.moreSignIns.length + sections.moreKeys.length
  readonly property var moreSignIns: UsageLogic.filterProviders(sections.moreSignIns, providerFilter)
  readonly property var moreKeys: UsageLogic.filterProviders(sections.moreKeys, providerFilter)
  readonly property var pages: [
    { id: "providers", title: "Providers", summary: providersSummary() },
    { id: "bar", title: "Menu bar", summary: menuBarSummary() },
    { id: "alerts", title: "Alerts", summary: alertsSummary() },
    { id: "display", title: "Display", summary: displaySummary() },
    { id: "costs", title: "Costs", summary: costsSummary() },
    { id: "advanced", title: "Advanced", summary: "Refresh every " + Math.round(Number(value("refreshIntervalSec", 900)) / 60) + " min" }
  ]
  readonly property string pageTitle: {
    for (var i = 0; i < pages.length; i++) if (pages[i].id === page) return pages[i].title
    return "Settings"
  }
  // Motion (DESIGN §1): durations come from the panel's Motion; without one, the Display setting decides.
  property var motion: null
  readonly property bool reducedMotion: motion ? motion.reduced === true : String(value("motion", "system")) === "reduced"
  readonly property int microMs: reducedMotion ? 0 : (motion ? motion.micro : 160)
  readonly property int rowMs: reducedMotion ? 0 : (motion ? motion.row : 260)
  readonly property int staggerMs: reducedMotion ? 0 : 60

  // ---- omp (Oh My Pi): its accounts, read here and through its auth gateway (Providers), and its
  // statistics and live feed from another computer (Costs). The panel passes its live feed in.
  property var ompActivity: null
  readonly property var omp: UsageLogic.ompSettings(settings)
  readonly property var ompStatus: lastPayload && lastPayload.omp && typeof lastPayload.omp === "object" ? lastPayload.omp : null
  // true, false, or null while no refresh has said.
  readonly property var ompFound: UsageLogic.ompFound(ompStatus)
  readonly property var ompLocalLine: UsageLogic.ompLocalStatus(ompStatus, omp.local, usageLoading)
  readonly property var ompRemoteSource: UsageLogic.readingFor(costSources, "omp-remote")
  readonly property string ompLiveState: ompActivity ? String(ompActivity.state) : ""
  // How omp stats is reached on the Costs page; only the commands shown depend on it.
  property string ompStatsVia: "tailscale"
  readonly property var ompStatsRecipe: UsageLogic.ompStatsRecipe(ompStatsVia)
  readonly property string usageFetchPath: decodeURIComponent(String(Qt.resolvedUrl("scripts/usage-fetch.py")).replace(/^file:\/\//, ""))
  readonly property string costFetchPath: decodeURIComponent(String(Qt.resolvedUrl("scripts/cost-fetch.py")).replace(/^file:\/\//, ""))

  // Changes are batched per control: { key: value }. The host persists them and reports back
  // through finishSave(), which also commits or discards a staged secret.
  signal changeRequested(var values)
  signal closeRequested()
  signal revealRequested(var item)
  // Sign in to or install a provider: the host opens the terminal and watches for the sign-in.
  signal setupRequested(var entry, var action)

  spacing: Style.spacing.xxl
  Keys.onEscapePressed: root.back()

  function value(key, fallback) {
    var raw = settings ? settings[key] : undefined
    return raw === undefined || raw === null ? fallback : raw
  }

  function monitored(id) {
    return proxyMode || UsageLogic.contains(enabledProviders, id)
  }

  function set(key, next) {
    var values = {}
    values[key] = next
    setMany(values)
  }

  function setMany(values) {
    var changed = {}
    var any = false
    for (var key in values) {
      if (JSON.stringify(value(key, undefined)) === JSON.stringify(values[key])) continue
      changed[key] = values[key]
      any = true
    }
    errorText = ""
    if (any) changeRequested(changed)
  }

  function toggleProvider(key, id) {
    var current = UsageLogic.listOrEmpty(value(key, UsageLogic.DEFAULT_SETTINGS[key] || []))
    set(key, UsageLogic.withMember(current, id, !UsageLogic.contains(current, id), allProviderIds))
  }

  // Monitoring a provider also gives it a menu bar chip and forgets an earlier dismissal. Turning one
  // off declines it, so a provider found on this computer is not suggested again.
  function setMonitored(id, on) {
    var values = {
      enabledProviders: UsageLogic.withMember(enabledProviders, id, on, allProviderIds),
      dismissedProviders: UsageLogic.withMember(dismissedProviders, id, !on, allProviderIds)
    }
    if (on) values.barProviders = UsageLogic.withMember(barProviders, id, true, allProviderIds)
    setMany(values)
  }

  function dismissProvider(id) {
    set("dismissedProviders", UsageLogic.withMember(dismissedProviders, id, true, allProviderIds))
  }

  // Sign in, install, or open the tool's page. Starting a sign-in also monitors the provider: the
  // user asked for it, so it should appear in Limits as soon as the sign-in lands.
  function runSetup(entry, action) {
    if (!entry || !action || action.kind === "") return
    if (action.kind === "link") {
      Qt.openUrlExternally(action.url)
      return
    }
    if (!monitored(entry.id)) setMonitored(entry.id, true)
    pendingSetup = entry.id
    setupRequested(entry, action)
  }

  function rememberPayload() {
    if (usagePayload && usagePayload.generatedAt) lastPayload = usagePayload
  }
  onUsagePayloadChanged: rememberPayload()

  // ---- provider order: the list model moves rows in place (delegates survive the move), and the
  // full order is saved when a drag ends or a key moves a row.
  ListModel { id: providerListModel }

  function providerListIds() {
    var ids = []
    for (var i = 0; i < providerListModel.count; i++) ids.push(providerListModel.get(i).providerId)
    return ids
  }

  // Rebuilds the rows from settings, unless they already show that order (or a drag is under way).
  function syncProviderList() {
    if (providerList.draggingId !== "") return
    var rows = providerRows
    var ids = rows.map(function (row) { return String(row.id) })
    if (ids.join(",") === providerListIds().join(",")) return
    providerListModel.clear()
    for (var i = 0; i < rows.length; i++)
      providerListModel.append({ providerId: String(rows[i].id), name: String(rows[i].name || rows[i].id), money: rows[i].money === true })
  }
  onProviderRowsChanged: syncProviderList()
  Component.onCompleted: {
    rememberPayload()
    syncProviderList()
  }

  // Only the rows on screen are saved; providers that join them later follow in their natural order.
  function saveProviderOrder() {
    set("providerOrder", JSON.stringify(providerListIds()))
  }

  // Keyboard move on a focused grip: one place up or down.
  function moveProvider(id, delta) {
    var from = providerListIds().indexOf(String(id))
    var to = from + delta
    if (from === -1 || to < 0 || to >= providerListModel.count) return
    providerListModel.move(from, to, 1)
    providerList.forceLayout()
    saveProviderOrder()
  }

  // Mouse drag: the row takes the slot under the pointer once the pointer passes that row's middle,
  // so rows of different heights do not swap back and forth.
  function dragProviderTo(row, y) {
    var target = providerList.indexAt(Style.spacing.lg, y)
    if (target === -1) target = y < 0 ? 0 : (y > providerList.contentHeight ? providerListModel.count - 1 : -1)
    if (target === -1 || target === row.index) return
    var item = providerList.itemAtIndex(target)
    if (item) {
      var middle = item.y + item.height / 2
      if ((target > row.index && y < middle) || (target < row.index && y > middle)) return
    }
    providerListModel.move(row.index, target, 1)
    providerList.forceLayout()
  }

  function finishProviderDrag() {
    if (providerList.draggingId === "") return
    providerList.draggingId = ""
    var current = providerRows.map(function (row) { return String(row.id) }).join(",")
    if (providerListIds().join(",") !== current) saveProviderOrder()
    // Rows that changed while the drag held the list back appear now.
    syncProviderList()
  }

  function open(pageId) {
    errorText = ""
    page = pageId
    Qt.callLater(function() { root.forceActiveFocus() })
  }

  function back() {
    if (saving) return
    errorText = ""
    if (page !== "") { page = ""; Qt.callLater(function() { root.forceActiveFocus() }) }
    else closeRequested()
  }

  function begin(pageId) {
    discardKey()
    errorText = ""
    priceError = ""
    page = pageId || ""
    providerFilter = ""
    providerFilterField.text = ""
    servers.load(String(value("costT3Servers", "[]")))
    lastPricesJson = String(value("costPriceOverrides", "{}"))
    prices.begin(lastPricesJson)
    // Test results describe the moment they ran; opening Settings again starts without them.
    ompGatewayLines = []
    ompStatsLines = []
    ompStatsVia = UsageLogic.ompLoopbackHost(UsageLogic.ompHost(omp.statsUrl)) ? "ssh" : "tailscale"
  }

  function focusFirst() { root.forceActiveFocus() }

  // ---- secrets: staged by management-key.py, committed once the host has persisted the paths
  property var pendingKeys: ({})
  property var pendingPrevious: ({})
  property var pendingApply: null
  property bool keySaveDecided: false

  function stageKeys(keys, previous, apply) {
    if (saving) return
    pendingKeys = keys
    pendingPrevious = previous
    pendingApply = apply
    keySaveDecided = false
    errorText = ""
    keyWriter.running = true
  }

  function discardKey() {
    pendingKeys = ({})
    pendingApply = null
    if (keyWriter.running && !keySaveDecided) keyWriter.running = false
  }

  function finishSave(saved) {
    if (keyWriter.running && !keySaveDecided) {
      keySaveDecided = true
      keyWriter.write(saved ? "commit\n" : "abort\n")
    }
    pendingApply = null
  }

  function removeKey(settingKey) {
    var path = String(value(settingKey, ""))
    set(settingKey, "")
    if (path !== "") {
      var request = {}
      request[settingKey] = path
      keyRemover.request = request
      keyRemover.running = true
    }
  }

  // Forgets one of a provider's extra keys and deletes its private file.
  function removeExtraKey(providerId, key) {
    set("extraKeys", UsageLogic.removeExtraKey(value("extraKeys", "{}"), providerId, key.id))
    var request = {}
    request["extraKey_" + providerId + "_" + key.id] = key.file
    keyRemover.request = request
    keyRemover.running = true
  }

  function validSecret(text) {
    var secret = String(text).trim()
    return secret !== "" && secret.length <= 8191 && !/[^\x20-\x7e]/.test(secret)
  }

  Process {
    id: keyWriter
    command: ["python3", "-u", decodeURIComponent(String(Qt.resolvedUrl("scripts/management-key.py")).replace(/^file:\/\//, ""))]
    stdinEnabled: true
    onStarted: {
      write(JSON.stringify({ keys: root.pendingKeys, previousPaths: root.pendingPrevious }) + "\n")
      root.pendingKeys = ({})
    }
    stdout: SplitParser {
      onRead: function(data) {
        if (!root.pendingApply || root.keySaveDecided) return
        var response = null
        try { response = JSON.parse(data) } catch (error) {}
        if (!response || !response.paths) return
        root.pendingApply(response.paths)
      }
    }
    stderr: SplitParser { splitMarker: "" }
    onRunningChanged: if (!running) {
      root.pendingKeys = ({})
      if (root.pendingApply && !root.keySaveDecided)
        root.errorText = "Could not save the key. Check that your configuration directory is writable and try again."
      root.pendingApply = null
    }
  }

  Timer {
    interval: 7000
    running: keyWriter.running
    onTriggered: keyWriter.running = false
  }

  Process {
    id: keyRemover
    property var request: ({})
    command: ["python3", "-u", decodeURIComponent(String(Qt.resolvedUrl("scripts/management-key.py")).replace(/^file:\/\//, ""))]
    stdinEnabled: true
    onStarted: write(JSON.stringify({ remove: request }) + "\n")
    stdout: SplitParser { onRead: function(data) {} }
    stderr: SplitParser { splitMarker: "" }
  }

  // ---- header: back to the index, or close from it
  Item {
    width: parent.width
    implicitHeight: Math.max(headerTitle.implicitHeight, closeButton.implicitHeight, backButton.implicitHeight)

    Ui.Button {
      id: backButton
      objectName: "settingsBackButton"
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      visible: root.page !== ""
      text: "‹ Settings"
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      horizontalPadding: Style.spacing.sm
      verticalPadding: Style.spacing.xs
      focusable: true
      Accessible.name: "Back to settings"
      onClicked: root.back()
      onActiveFocusChanged: if (activeFocus) root.revealRequested(backButton)
    }

    PlainText {
      id: headerTitle
      anchors.left: backButton.visible ? backButton.right : parent.left
      anchors.leftMargin: backButton.visible ? Style.spacing.md : 0
      anchors.right: closeButton.left
      anchors.verticalCenter: parent.verticalCenter
      text: root.pageTitle
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      font.bold: true
      elide: Text.ElideRight
    }

    Ui.PanelActionButton {
      id: closeButton
      objectName: "settingsCloseButton"
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      iconText: "󰅖"
      tooltipText: "Close settings"
      foreground: root.foreground
      fontFamily: root.fontFamily
      focusable: true
      onClicked: root.closeRequested()
      onActiveFocusChanged: if (activeFocus) root.revealRequested(closeButton)
    }
  }

  PlainText {
    visible: root.errorText !== ""
    width: parent.width
    text: root.errorText
    wrapMode: Text.WordWrap
    color: root.urgent
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  // ---- index
  Column {
    visible: root.page === ""
    width: parent.width
    spacing: Style.spacing.xs

    Repeater {
      model: root.pages
      delegate: PageRow {
        required property var modelData
        objectName: "settingsPage-" + modelData.id
        title: modelData.title
        summary: modelData.summary
        onOpened: root.open(modelData.id)
      }
    }

    Hint { topPadding: Style.spacing.lg; text: "Changes apply as you make them." }
  }

  // ---- Providers
  Column {
    visible: root.page === "providers"
    width: parent.width
    spacing: Style.spacing.lg

    SelectRow {
      id: sourceControl
      objectName: "usageSourceControl"
      label: "Source"
      options: [{ value: "direct", label: "Local sign-ins" }, { value: "cliproxy", label: root.proxyName }]
      value: String(root.value("usageSource", "direct"))
      onChanged: function(next) { root.set("usageSource", next) }
    }
    Hint { text: root.proxyMode ? "Limits come from every account on your " + root.proxyName + " server." : "Limits come from the CLIs, apps, and IDEs you are signed in to on this computer, plus API keys saved here or set in the environment." }

    // Like the proxy's settings below, the source ends with a rule before the providers.
    Ui.PanelSeparator { visible: !root.proxyMode; width: parent.width; foreground: root.foreground }

    Column {
      visible: root.proxyMode
      width: parent.width
      spacing: Style.spacing.lg

      TextRow {
        id: proxyUrlField
        objectName: "cliproxyUrl"
        label: root.proxyName + " server URL"
        placeholder: "http://127.0.0.1:8317"
        source: String(root.value("cliproxyUrl", "http://127.0.0.1:8317"))
        validate: function(text) {
          return UsageLogic.secretServerUrlProblem(text, "Enter an HTTP or HTTPS server URL without credentials, query, or fragment.")
        }
        onApplied: function(text) { root.set("cliproxyUrl", text) }
      }
      KeyRow {
        id: managementCredential
        objectName: "managementKeyRow"
        label: "Management API key"
        settingKey: "cliproxyKeyFile"
        hint: "The key is saved privately on this device and lets the widget list the proxy's providers and accounts."
      }
      Hint { text: "CPA Usage Keeper tells which account served the latest request. Without it, every account still gets its own card." }
      TextRow {
        id: keeperUrlField
        objectName: "costKeeperUrl"
        label: "CPA Usage Keeper URL"
        placeholder: "https://proxy.example.com/keeper"
        source: String(root.value("costKeeperUrl", ""))
        validate: function(text) {
          return text === "" ? "" : UsageLogic.secretServerUrlProblem(text, "Enter the Keeper HTTP or HTTPS URL, or leave it empty.")
        }
        onApplied: function(text) { root.set("costKeeperUrl", text) }
      }
      KeyRow {
        id: keeperCredential
        objectName: "keeperPasswordRow"
        label: "Keeper login password"
        settingKey: "costKeeperPasswordFile"
      }
      Ui.PanelSeparator { width: parent.width; foreground: root.foreground }
    }

    // One click to monitor what is already set up here; Ignore stops suggesting it.
    Column {
      objectName: "foundProviders"
      visible: !root.proxyMode && root.sections.found.length > 0
      width: parent.width
      spacing: Style.spacing.md

      Label { text: "Found on this computer"; font.bold: true }
      Repeater {
        model: root.proxyMode ? [] : root.sections.found
        delegate: Row {
          id: foundRow
          required property var modelData
          width: parent.width
          spacing: Style.spacing.sm
          ProviderMark { providerId: foundRow.modelData.id; anchors.verticalCenter: parent.verticalCenter }
          Label {
            width: parent.width - Style.space(14) - foundMonitor.width - foundIgnore.width - parent.spacing * 3
            anchors.verticalCenter: parent.verticalCenter
            text: foundRow.modelData.name
          }
          Ui.Button {
            id: foundIgnore
            objectName: "ignore-" + foundRow.modelData.id
            anchors.verticalCenter: parent.verticalCenter
            text: "Ignore"
            foreground: root.foreground
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            focusable: true
            Accessible.name: "Do not suggest " + foundRow.modelData.name
            onClicked: root.dismissProvider(foundRow.modelData.id)
            onActiveFocusChanged: if (activeFocus) root.revealRequested(foundIgnore)
          }
          Ui.Button {
            id: foundMonitor
            objectName: "found-" + foundRow.modelData.id
            anchors.verticalCenter: parent.verticalCenter
            text: "Monitor"
            bordered: true
            selected: true
            foreground: root.foreground
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            focusable: true
            Accessible.name: "Monitor " + foundRow.modelData.name
            onClicked: root.setMonitored(foundRow.modelData.id, true)
            onActiveFocusChanged: if (activeFocus) root.revealRequested(foundMonitor)
          }
        }
      }
      Hint { text: "Set up on this computer but not monitored. Ignored providers stay under More providers." }
    }

    // Headings sit over the switches inside the cards, so they share the cards' inner edges.
    Row {
      visible: root.providerRows.length > 0
      width: parent.width
      leftPadding: root.providerCardInset
      rightPadding: root.providerCardInset
      Label { width: parent.width - parent.leftPadding - parent.rightPadding - monitorHeading.width - barHeading.width; text: root.proxyMode ? "Provider" : "Monitored"; font.bold: true }
      Label { id: monitorHeading; visible: !root.proxyMode; width: visible ? Style.space(82) : 0; text: "Monitor"; horizontalAlignment: Text.AlignHCenter }
      Label { id: barHeading; visible: root.percentageDisplay; width: visible ? Style.space(82) : 0; text: "Menu bar"; horizontalAlignment: Text.AlignHCenter }
    }
    Hint {
      visible: !root.proxyMode && root.providerRows.length === 0
      text: "Nothing monitored is set up yet. Sign in to a provider's CLI or app, or turn one on below."
    }

    // Rows reorder by dragging their grip (or arrow keys on a focused grip). The order is the one
    // the tiles, chips, and provider cycling use. A ListView keeps each delegate alive while it moves.
    ListView {
      id: providerList
      objectName: "providerList"
      property string draggingId: ""
      width: parent.width
      height: contentHeight
      interactive: false
      spacing: Style.spacing.md
      cacheBuffer: 100000
      model: providerListModel
      moveDisplaced: Transition { NumberAnimation { properties: "y"; duration: 150; easing.type: Easing.OutCubic } }
      move: Transition { NumberAnimation { properties: "y"; duration: 150; easing.type: Easing.OutCubic } }

      delegate: Ui.BorderSurface {
        id: providerRow
        required property string providerId
        required property string name
        required property bool money
        required property int index
        readonly property bool on: root.proxyMode || UsageLogic.contains(root.enabledProviders, providerId)
        readonly property var entry: root.proxyMode ? null : UsageLogic.localProvider(providerId)
        readonly property bool hasKey: UsageLogic.keySaved(root.settings, providerId)
        readonly property var reading: UsageLogic.readingFor(root.shownReadings, providerId)
        readonly property var setup: reading ? UsageLogic.setupAction(entry, reading, root.shownInstalled) : UsageLogic.setupAction(null, null, null)
        readonly property var status: entry ? UsageLogic.providerStatus(entry, reading, hasKey, root.usageLoading,
          setup.kind === "signin" || setup.kind === "install") : null
        // A provider that also has a sign-in of its own only needs the editor while that sign-in is
        // not what connects it.
        readonly property bool keyEditor: !!entry && entry.auth !== "signin"
          && (entry.auth === "key" || hasKey || !reading || reading.status !== "ok")
        readonly property bool dragging: providerList.draggingId === providerId
        // This provider's accounts in the last reading (Omarchy sign-ins, extra keys, omp, a proxy).
        readonly property var accountReading: root.proxyMode ? UsageLogic.readingFor(root.proxyProviders, providerId) : reading
        readonly property var accountList: accountReading ? UsageLogic.listOrEmpty(accountReading.accounts) : []
        readonly property int accountCount: accountList.length
        readonly property var hiddenIds: UsageLogic.parseHiddenAccounts(root.value("hiddenAccounts", "{}"))[providerId] || []
        readonly property int shownAccountCount: Array.prototype.filter.call(accountList, function (account) {
          return hiddenIds.indexOf(String(account && account.accountId || "")) < 0 }).length
        // Key editor and Customize line up with the name, under the grip and the mark.
        readonly property real indent: grip.width + mark.width + Style.spacing.sm * 2
        width: providerList.width
        height: rowContent.implicitHeight + contentTopInset + contentBottomInset
        z: dragging ? 2 : 1
        padding: root.providerCardPadding
        radius: root.providerCardRadius
        color: dragging ? Style.hoverFillFor(root.foreground, Commons.Color.accent, root.urgent)
          : Style.normalFillFor(root.foreground, Commons.Color.accent, root.urgent)
        borderSpec: Border.controlSpec(dragging ? "hover-cursor" : "normal", root.foreground, Commons.Color.accent, root.urgent)

        Column {
          id: rowContent
          x: providerRow.contentLeftInset
          y: providerRow.contentTopInset
          width: providerRow.width - providerRow.contentLeftInset - providerRow.contentRightInset
          spacing: Style.spacing.md

          // Grip, mark, and switches line up with the name, not with the middle of the text block,
          // so a status line or a Sign in button below the name does not push them down.
          Row {
            id: providerHeader
            readonly property real band: Math.max(nameLabel.implicitHeight, grip.height, monitorSwitch.implicitHeight)
            width: parent.width
            spacing: Style.spacing.sm

            Item {
              id: grip
              objectName: "dragHandle-" + providerRow.providerId
              readonly property bool hot: gripArea.containsMouse || gripArea.pressed || activeFocus
              width: Style.space(16)
              height: Style.space(24)
              anchors.top: parent.top
              anchors.topMargin: (providerHeader.band - height) / 2
              activeFocusOnTab: true
              Accessible.role: Accessible.Button
              Accessible.name: "Reorder " + providerRow.name + ". Drag, or use the up and down arrow keys."
              Keys.onUpPressed: root.moveProvider(providerRow.providerId, -1)
              Keys.onDownPressed: root.moveProvider(providerRow.providerId, 1)
              onActiveFocusChanged: if (activeFocus) root.revealRequested(grip)

              Rectangle {
                anchors.fill: parent
                visible: grip.activeFocus
                color: "transparent"
                radius: Style.space(4)
                border.width: Style.spacing.hairline
                border.color: root.foreground
              }

              // Six dots: the usual drag grip.
              Grid {
                anchors.centerIn: parent
                columns: 2
                spacing: Style.space(3)
                Repeater {
                  model: 6
                  Rectangle {
                    width: Style.space(3)
                    height: width
                    radius: width / 2
                    color: grip.hot ? root.foreground : Qt.darker(root.foreground, 1.7)
                  }
                }
              }

              MouseArea {
                id: gripArea
                anchors.fill: parent
                anchors.margins: -Style.spacing.xs
                hoverEnabled: true
                preventStealing: true
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                onPressed: providerList.draggingId = providerRow.providerId
                onPositionChanged: function(mouse) {
                  if (pressed) root.dragProviderTo(providerRow, mapToItem(providerList.contentItem, mouse.x, mouse.y).y)
                }
                onReleased: root.finishProviderDrag()
                onCanceled: root.finishProviderDrag()
              }
            }
            ProviderMark {
              id: mark
              providerId: providerRow.providerId
              anchors.top: parent.top
              anchors.topMargin: (providerHeader.band - height) / 2
            }
            Column {
              width: parent.width - grip.width - mark.width - monitorSwitch.width - barSwitch.width - parent.spacing * 4
              anchors.top: parent.top
              topPadding: (providerHeader.band - nameLabel.implicitHeight) / 2
              spacing: Style.spacing.xxs
              Label { id: nameLabel; text: providerRow.name; font.bold: true }
              // What the last refresh found: connected, or what is missing and how to fix it.
              Hint {
                objectName: "status-" + providerRow.providerId
                visible: text !== ""
                text: providerRow.status ? providerRow.status.text : ""
                color: providerRow.status && providerRow.status.tone === "error" ? root.urgent : Qt.darker(root.foreground, 1.5)
                maximumLineCount: 2
                elide: Text.ElideRight
              }
              SetupAction {
                entry: providerRow.entry
                reading: providerRow.reading
                needsReading: true
              }
            }
            Toggle {
              id: monitorSwitch
              visible: !root.proxyMode
              width: visible ? Style.space(82) : 0
              anchors.top: parent.top
              anchors.topMargin: (providerHeader.band - implicitHeight) / 2
              objectName: "monitor-" + providerRow.providerId
              Accessible.name: "Monitor " + providerRow.name
              checked: providerRow.on
              onToggled: root.setMonitored(providerRow.providerId, !providerRow.on)
            }
            Toggle {
              id: barSwitch
              visible: root.percentageDisplay
              width: visible ? Style.space(82) : 0
              anchors.top: parent.top
              anchors.topMargin: (providerHeader.band - implicitHeight) / 2
              objectName: "bar-" + providerRow.providerId
              Accessible.name: "Show " + providerRow.name + " in the menu bar"
              enabled: providerRow.on
              checked: providerRow.on && UsageLogic.contains(root.barProviders, providerRow.providerId)
              opacity: enabled ? 1 : 0.4
              onToggled: root.toggleProvider("barProviders", providerRow.providerId)
            }
          }

          // API-key providers: the key editor sits right under the switch that needs it.
          Column {
            visible: providerRow.keyEditor && providerRow.on
            width: parent.width
            leftPadding: providerRow.indent
            spacing: Style.spacing.md

            KeyRow {
              width: parent.width - parent.leftPadding
              objectName: providerRow.providerId + "KeyRow"
              label: providerRow.entry ? providerRow.entry.keyLabel : "API key"
              settingKey: providerRow.providerId + "KeyFile"
              hint: providerRow.entry ? UsageLogic.keyHint(providerRow.entry) : ""
            }
            LinkButton {
              objectName: providerRow.providerId + "KeysLink"
              visible: !!providerRow.entry && providerRow.entry.keysUrl !== ""
              text: providerRow.entry ? providerRow.entry.keysLinkText : "Get a key ↗"
              url: providerRow.entry ? providerRow.entry.keysUrl : ""
            }
            // No key page to link to: the hint says where the key is created.
            Hint {
              visible: !!providerRow.entry && providerRow.entry.keysUrl === ""
              width: parent.width - parent.leftPadding
              text: providerRow.entry ? providerRow.entry.signIn : ""
            }
            ExtraKeys {
              width: parent.width - parent.leftPadding
              providerId: providerRow.providerId
              keyLabel: providerRow.entry ? providerRow.entry.keyLabel : "API key"
            }
          }

          // Overrides: the defaults from Menu bar and Display, changed for this provider only.
          Column {
            visible: providerRow.on
            width: parent.width
            leftPadding: providerRow.indent
            SettingsSection {
              id: customizeSection
              objectName: "customize-" + providerRow.providerId
              width: parent.width - parent.leftPadding
              title: "Customize"
              summary: root.overrideSummary(providerRow.providerId)
              foreground: root.foreground
              fontFamily: root.fontFamily
              onRevealRequested: function(item) { root.revealRequested(item) }

              SelectRow {
                objectName: "quotaMode-" + providerRow.providerId
                label: "Show limits as"
                options: [
                  { value: "default", label: "Default (" + UsageLogic.quotaModeLabel(root.quotaMode) + ")" },
                  { value: "Used", label: "Used (%)" },
                  { value: "Remaining", label: "Left (%)" }
                ]
                value: UsageLogic.parseQuotaModes(root.value("providerQuotaModes", "{}"))[providerRow.providerId] || "default"
                onChanged: function(next) { root.set("providerQuotaModes", UsageLogic.setQuotaMode(root.value("providerQuotaModes", "{}"), providerRow.providerId, next)) }
              }
              SelectRow {
                objectName: "barLimitTop-" + providerRow.providerId
                visible: root.percentageDisplay && !providerRow.money
                label: "Limit shown"
                options: [
                  { value: "default", label: UsageLogic.inheritedBarLimitLabel("top", root.value("barWindow", "auto")) },
                  { value: "auto", label: "Most constrained" },
                  { value: "session", label: "5-hour" },
                  { value: "weekly", label: "7-day" },
                  { value: "monthly", label: "Monthly" }
                ]
                value: root.barLimitValue(providerRow.providerId, "top")
                onChanged: function(next) { root.set("barProviderLimits", UsageLogic.setBarLimit(root.value("barProviderLimits", "{}"), providerRow.providerId, "top", next)) }
              }
              SelectRow {
                objectName: "barLimitBottom-" + providerRow.providerId
                visible: root.percentageDisplay && !providerRow.money
                label: "Second limit below"
                options: [
                  { value: "default", label: UsageLogic.inheritedBarLimitLabel("bottom", root.value("barWindowSecondary", "none")) },
                  { value: "none", label: "None" },
                  { value: "session", label: "5-hour" },
                  { value: "weekly", label: "7-day" },
                  { value: "monthly", label: "Monthly" }
                ]
                value: root.barLimitValue(providerRow.providerId, "bottom")
                onChanged: function(next) { root.set("barProviderLimits", UsageLogic.setBarLimit(root.value("barProviderLimits", "{}"), providerRow.providerId, "bottom", next)) }
              }
              SelectRow {
                objectName: "accountMode-" + providerRow.providerId
                visible: providerRow.accountCount >= 2
                label: "Accounts are used"
                options: [
                  { value: "auto", label: "Automatically" },
                  { value: "single", label: "One at a time" },
                  { value: "together", label: "Together" }
                ]
                value: UsageLogic.parseAccountModes(root.value("accountModes", "{}"))[providerRow.providerId] || "auto"
                onChanged: function(next) { root.set("accountModes", UsageLogic.setAccountMode(root.value("accountModes", "{}"), providerRow.providerId, next)) }
              }
              Hint {
                visible: providerRow.accountCount >= 2
                text: "Automatically: together while omp or a proxy spreads requests over the accounts, or when two of them spend within the same hour; otherwise one at a time."
              }
              // Each account shown or hidden. A hidden one keeps its sign-in or key; the last one shown stays.
              Label {
                visible: providerRow.accountCount >= 2
                text: "Accounts shown"
              }
              Repeater {
                model: providerRow.accountCount >= 2 ? providerRow.accountList : []
                delegate: SwitchRow {
                  id: accountSwitch
                  required property var modelData
                  required property int index
                  readonly property string accountId: String(modelData && modelData.accountId || "")
                  readonly property bool hidden: providerRow.hiddenIds.indexOf(accountId) >= 0
                  objectName: "showAccount-" + providerRow.providerId + "-" + index
                  label: UsageLogic.accountSettingsLabel(modelData, root.value("extraKeys", "{}"),
                    root.value("hideAccountEmails", true) !== false, index)
                  checked: !hidden
                  enabled: accountId !== "" && (hidden || providerRow.shownAccountCount > 1)
                  onToggled: if (enabled) root.set("hiddenAccounts", UsageLogic.setAccountHidden(
                    root.value("hiddenAccounts", "{}"), providerRow.providerId, accountId, !hidden))
                }
              }
              Hint {
                visible: providerRow.accountCount >= 2
                text: "A hidden account stays signed in and keeps its key. Limits, the menu bar and the notices leave it out; one account always stays shown."
              }
              Hint { text: "Default follows the choices under Menu bar and Display." }
            }
          }
        }
      }
    }
    Hint {
      visible: root.providerRows.length > 0
      text: root.proxyMode ? "Every provider on the server is monitored. Choose which ones get a menu bar chip, and open Customize to read one differently." : "Monitor reads a provider and shows it in Limits. Menu bar adds its chip to the bar. Customize overrides the defaults for one provider."
    }

    // Monitored sign-ins that are not signed in: they appear on their own once they are, so they
    // stay folded away instead of lengthening the list above.
    SettingsSection {
      id: waitingSection
      objectName: "waitingProviders"
      visible: !root.proxyMode && root.sections.waiting.length > 0
      width: parent.width
      title: "Waiting for a sign-in"
      summary: String(root.sections.waiting.length)
      foreground: root.foreground
      fontFamily: root.fontFamily
      onRevealRequested: function(item) { root.revealRequested(item) }

      Hint { text: "Monitored, and shown in Limits as soon as you sign in. Turn off the ones you do not use." }
      Repeater {
        model: root.proxyMode ? [] : root.sections.waiting
        delegate: ProviderOption {
          id: waitingOption
          readonly property var setup: UsageLogic.setupAction(waitingOption.modelData,
            UsageLogic.readingFor(root.shownReadings, waitingOption.modelData.id), root.shownInstalled)
          hint: UsageLogic.providerStatus(waitingOption.modelData,
            UsageLogic.readingFor(root.shownReadings, waitingOption.modelData.id), false, root.usageLoading,
            setup.kind === "signin" || setup.kind === "install").text
          keyEditable: waitingOption.modelData.auth === "both"
        }
      }
    }

    SettingsSection {
      id: moreSection
      objectName: "moreProviders"
      visible: !root.proxyMode && root.moreCount > 0
      width: parent.width
      title: "More providers"
      summary: String(root.moreCount)
      foreground: root.foreground
      fontFamily: root.fontFamily
      onRevealRequested: function(item) { root.revealRequested(item) }

      SettingsField {
        id: providerFilterField
        objectName: "providerFilterField"
        visible: root.moreCount > 8
        width: parent.width
        placeholderText: "Filter providers"
        foreground: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        Accessible.name: "Filter providers"
        onTextEdited: root.providerFilter = text
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
      Label { visible: root.moreSignIns.length > 0; text: "Sign-ins"; font.bold: true }
      Repeater {
        model: root.proxyMode ? [] : root.moreSignIns
        delegate: ProviderOption {}
      }
      Label { visible: root.moreKeys.length > 0; text: "API keys"; font.bold: true; topPadding: Style.spacing.md }
      Repeater {
        model: root.proxyMode ? [] : root.moreKeys
        delegate: ProviderOption {}
      }
      Hint {
        visible: root.moreSignIns.length + root.moreKeys.length === 0
        text: "No provider matches “" + root.providerFilter.trim() + "”."
      }
    }

    // omp (Oh My Pi) signs in to accounts of its own. Read here, they join the providers above; through
    // omp's auth gateway, so do the accounts of omp on another computer. It comes after the providers it
    // adds to, so Monitored opens the page.
    Ui.PanelSeparator { visible: !root.proxyMode; width: parent.width; foreground: root.foreground }
    Column {
      id: ompSource
      objectName: "ompSource"
      visible: !root.proxyMode
      width: parent.width
      spacing: Style.spacing.md

      Column {
        width: parent.width
        spacing: Style.spacing.xxs
        Label { text: "omp"; font.bold: true }
        StatusLine { objectName: "ompStatus"; line: root.ompLocalLine }
      }
      SwitchRow {
        objectName: "ompLocal"
        visible: !(root.ompFound === false && root.omp.local)
        label: "Read omp's accounts"
        checked: root.omp.local
        onToggled: root.set("ompLocal", !checked)
      }
      Hint {
        objectName: "ompLocalHint"
        readonly property string failure: root.ompLocalLine.tone === "error" ? UsageLogic.ompLocalMessage(root.ompStatus) : ""
        text: root.ompFound === false && root.omp.local
          ? "Install omp to add the accounts it signs in to, or read omp on another computer below."
          : failure !== "" ? failure
          : root.omp.local && root.ompStatus && root.ompStatus.local === "unused"
          ? "Once you sign in to an account in omp, its accounts join the providers above. Until then Quotatank does not run omp."
          : "Adds the accounts omp signs in to, with their limits, from omp usage on this computer. An account you also use here shows once."
        color: failure !== "" ? root.urgent : Qt.darker(root.foreground, 1.5)
      }

      SettingsSection {
        id: ompGatewaySection
        objectName: "ompGatewaySection"
        width: parent.width
        // Under the "omp" heading the name needs no repeating, which leaves the summary room.
        title: "On another computer (limits)"
        summary: UsageLogic.ompGatewaySummary(root.settings, root.ompStatus)
        foreground: root.foreground
        fontFamily: root.fontFamily
        onRevealRequested: function(item) { root.revealRequested(item) }

        Hint { text: "Reads the limits of the accounts omp uses on another computer, through omp's auth gateway. Set it up only if you already run the gateway there; without it, limits come from this computer." }
        WhereLabel { text: "On the other computer" }
        Repeater {
          model: UsageLogic.ompGatewayRecipe()
          delegate: CommandBlock {
            required property var modelData
            required property int index
            objectName: "ompGatewayCommand-" + index
            command: modelData.command
          }
        }
        TextRow {
          objectName: "ompGatewayUrl"
          label: "Gateway URL"
          placeholder: "http://100.x.y.z:" + UsageLogic.OMP_GATEWAY_PORT
          source: root.omp.gatewayUrl
          validate: function(text) { return UsageLogic.ompServerUrlProblem(text, true) }
          onApplied: function(text) { root.set("ompGatewayUrl", text) }
        }
        KeyRow {
          objectName: "ompGatewayToken"
          label: "Gateway token"
          settingKey: "ompGatewayKeyFile"
          hint: "This token can also send model requests. Quotatank only asks the gateway for /v1/usage, sends the token over plain HTTP only to this computer or over Tailscale, keeps it in a private file, and never shows it again."
        }
        TestBlock {
          objectName: "ompGatewayTest"
          ready: root.omp.gatewayUrl !== "" && root.omp.gatewayKeyFile !== "" && UsageLogic.ompServerUrlProblem(root.omp.gatewayUrl, true) === ""
          blockedReason: root.omp.gatewayUrl === "" ? "Enter the gateway URL and save its token to test it."
            : root.omp.gatewayKeyFile === "" ? "Save the gateway token to test it." : ""
          running: gatewayProbe.active
          waitingText: "Asking the gateway" + UsageLogic.ompOnHost(root.omp.gatewayUrl) + "…"
          lines: root.ompGatewayLines
          onRequested: root.testOmpGateway()
        }
      }
    }
  }

  // ---- Menu bar
  Column {
    visible: root.page === "bar"
    width: parent.width
    spacing: Style.spacing.lg

    SelectRow {
      objectName: "barDisplayControl"
      label: "Menu bar shows"
      options: [{ value: "Icon", label: "Widget icon" }, { value: "Percentages", label: "Provider chips" }]
      value: String(root.value("barDisplayMode", "Percentages"))
      onChanged: function(next) { root.set("barDisplayMode", next) }
    }
    Hint { text: "Vertical bars, and providers without data, show the widget icon instead." }

    Column {
      visible: root.percentageDisplay
      width: parent.width
      spacing: Style.spacing.lg

      SelectRow {
        objectName: "barWindowControl"
        label: "Limit shown"
        options: [
          { value: "auto", label: "Most constrained" },
          { value: "session", label: "5-hour" },
          { value: "weekly", label: "7-day" },
          { value: "monthly", label: "Monthly" }
        ]
        value: UsageLogic.normalizeBarWindow(root.value("barWindow", "auto"))
        onChanged: function(next) { root.set("barWindow", next) }
      }
      SelectRow {
        objectName: "barWindowSecondaryControl"
        label: "Second limit below"
        options: [
          { value: "none", label: "None" },
          { value: "session", label: "5-hour" },
          { value: "weekly", label: "7-day" },
          { value: "monthly", label: "Monthly" }
        ]
        value: UsageLogic.normalizeSecondaryBarWindow(root.value("barWindowSecondary", "none"))
        onChanged: function(next) { root.set("barWindowSecondary", next) }
      }
      SwitchRow {
        objectName: "barShowPeriodsToggle"
        label: "Show limit period"
        checked: root.value("barShowPeriods", true) !== false
        onToggled: root.set("barShowPeriods", !checked)
      }
      Hint { text: "Tags each chip line with the period of the limit it shows: 5h, 7d, 30d. Off, chips show only the figure and get narrower." }

      SwitchRow {
        objectName: "barShowResetsToggle"
        label: "Show when limits reset"
        checked: root.value("barShowResets", false) === true
        onToggled: root.set("barShowResets", !checked)
      }
      Hint { text: "A time for limits that reset within a day, a date for weekly and monthly ones." }
      SelectRow {
        objectName: "barResetTimeControl"
        visible: root.value("barShowResets", false) === true
        label: "Time format"
        options: [{ value: "24h", label: "24-hour (14:30)" }, { value: "12h", label: "12-hour (2:30 PM)" }]
        value: UsageLogic.normalizeBarResetChoice("time", root.value("barResetTimeFormat", "24h"))
        onChanged: function(next) { root.set("barResetTimeFormat", next) }
      }
      SelectRow {
        objectName: "barResetDateControl"
        visible: root.value("barShowResets", false) === true
        label: "Date format"
        options: [{ value: "DD/MM", label: "DD/MM (22/04)" }, { value: "MM/DD", label: "MM/DD (04/22)" }, { value: "D MMM", label: "D MMM (22 Apr)" }]
        value: UsageLogic.normalizeBarResetChoice("date", root.value("barResetDateFormat", "DD/MM"))
        onChanged: function(next) { root.set("barResetDateFormat", next) }
      }

      SelectRow {
        objectName: "barMaxChipsControl"
        label: "Chips in the bar"
        options: [
          { value: "0", label: "All" },
          { value: "2", label: "Up to 2" },
          { value: "3", label: "Up to 3" },
          { value: "4", label: "Up to 4" },
          { value: "5", label: "Up to 5" },
          { value: "6", label: "Up to 6" }
        ]
        value: String(Number(root.value("barMaxChips", UsageLogic.DEFAULT_SETTINGS.barMaxChips)))
        onChanged: function(next) { root.set("barMaxChips", Number(next)) }
      }
      Hint { text: "Past that, the bar keeps the providers closest to a limit and folds the rest into a +N chip." }

      SelectRow {
        objectName: "barAccountModeControl"
        label: "Accounts"
        options: [{ value: "dots", label: "One chip with dots" }, { value: "chips", label: "One chip per account" }]
        value: String(root.value("barAccountMode", "dots")) === "chips" ? "chips" : "dots"
        onChanged: function(next) { root.set("barAccountMode", next) }
      }
      Hint { text: "For a provider with several accounts: one chip with a dot for each account, or a chip for each account, up to 4." }

      SwitchRow {
        objectName: "hideExhaustedProvidersToggle"
        label: "Hide providers that are used up"
        checked: root.value("hideExhaustedProviders", false) === true
        onToggled: root.set("hideExhaustedProviders", !checked)
      }
      Hint { text: "Removes a chip while one of its weekly or monthly limits is used up. It returns when that limit resets; Limits still shows the provider." }

      Hint { text: "To pin different limits for one provider, open Providers → Customize." }
    }
  }

  // ---- Alerts
  Column {
    visible: root.page === "alerts"
    width: parent.width
    spacing: Style.spacing.lg

    SwitchRow {
      objectName: "notifyLimitThresholdsToggle"
      label: "Notify when limits run low"
      checked: root.value("notifyLimitThresholds", true) !== false
      onToggled: root.set("notifyLimitThresholds", !checked)
    }
    Hint { text: "A desktop notification when a limit, or a balance, crosses into warning or critical. The colours in the bar and Limits follow the same thresholds." }

    Row {
      width: parent.width
      spacing: Style.spacing.lg
      NumberRow {
        id: warningField
        objectName: "warningThreshold"
        width: (parent.width - parent.spacing) / 2
        label: root.quotaMode === "Remaining" ? "Warn at (% left)" : "Warn at (% used)"
        source: UsageLogic.thresholdInMode(Number(root.value("warningThreshold", 25)), root.quotaMode)
        minimum: UsageLogic.thresholdBounds(1, 100, root.quotaMode)[0]
        maximum: UsageLogic.thresholdBounds(1, 100, root.quotaMode)[1]
        integer: true
        validate: function(entered) {
          var left = UsageLogic.thresholdToLeft(entered, root.quotaMode)
          return left < Number(root.value("criticalThreshold", 10)) ? "Warning must come before critical." : ""
        }
        onApplied: function(entered) { root.set("warningThreshold", UsageLogic.thresholdToLeft(entered, root.quotaMode)) }
      }
      NumberRow {
        id: criticalField
        objectName: "criticalThreshold"
        width: (parent.width - parent.spacing) / 2
        label: root.quotaMode === "Remaining" ? "Critical at (% left)" : "Critical at (% used)"
        source: UsageLogic.thresholdInMode(Number(root.value("criticalThreshold", 10)), root.quotaMode)
        minimum: UsageLogic.thresholdBounds(0, 100, root.quotaMode)[0]
        maximum: UsageLogic.thresholdBounds(0, 100, root.quotaMode)[1]
        integer: true
        validate: function(entered) {
          var left = UsageLogic.thresholdToLeft(entered, root.quotaMode)
          return left > Number(root.value("warningThreshold", 25)) ? "Critical must come after warning." : ""
        }
        onApplied: function(entered) { root.set("criticalThreshold", UsageLogic.thresholdToLeft(entered, root.quotaMode)) }
      }
    }
    Hint { text: (root.quotaMode === "Remaining" ? "A limit turns warning at or below the first value and critical at or below the second." : "A limit turns warning at or above the first value and critical at or above the second.") + " The boundaries stay put when Show limits as changes." }

    Label { visible: root.moneyMonitored; text: "Low balance"; font.bold: true; topPadding: Style.spacing.md }
    Row {
      visible: root.moneyMonitored
      width: parent.width
      spacing: Style.spacing.lg
      NumberRow {
        id: moneyWarningField
        objectName: "creditWarningUsd"
        width: (parent.width - parent.spacing) / 2
        label: "Warn at or below"
        source: Number(root.value("creditWarningUsd", 5))
        minimum: 0
        maximum: 100000
        validate: function(entered) { return entered < Number(root.value("creditCriticalUsd", 1)) ? "Warning must stay above critical." : "" }
        onApplied: function(entered) { root.set("creditWarningUsd", entered) }
      }
      NumberRow {
        id: moneyCriticalField
        objectName: "creditCriticalUsd"
        width: (parent.width - parent.spacing) / 2
        label: "Critical at or below"
        source: Number(root.value("creditCriticalUsd", 1))
        minimum: 0
        maximum: 100000
        validate: function(entered) { return entered > Number(root.value("creditWarningUsd", 5)) ? "Critical must stay below warning." : "" }
        onApplied: function(entered) { root.set("creditCriticalUsd", entered) }
      }
    }
    Hint {
      visible: root.moneyMonitored
      text: "Compared with the " + UsageLogic.joinNames(root.moneyProviderNames) + (root.moneyProviderNames.length === 1 ? " balance" : " balances")
        + ", each in its own currency."
    }
  }

  // ---- Display
  Column {
    visible: root.page === "display"
    width: parent.width
    spacing: Style.spacing.lg

    SelectRow {
      objectName: "quotaModeControl"
      label: "Show limits as"
      options: [{ value: "Used", label: "Used (%)" }, { value: "Remaining", label: "Left (%)" }]
      value: root.quotaMode
      onChanged: function(next) { root.set("quotaMode", next) }
    }
    Hint { text: "Applies to cards, chips, balances, and alerts. Thresholds keep their meaning either way." }
    Hint { text: "To read one provider the other way round, open Providers → Customize." }
    SwitchRow {
      objectName: "providerColorsToggle"
      label: "Provider colors"
      checked: root.value("providerColors", false) === true
      onToggled: root.set("providerColors", !checked)
    }
    Hint { text: "Brand colors on chips and meters. Alerts keep the theme's alert color; the cost chart always uses brand colors." }
    SwitchRow {
      objectName: "squareUsageCardsToggle"
      label: "Square cards"
      checked: root.value("squareUsageCards", true) === true
      onToggled: root.set("squareUsageCards", !checked)
    }
    Hint { text: "Off follows the theme's corner style." }
    SwitchRow {
      objectName: "hideAccountEmailsToggle"
      label: "Hide account emails"
      checked: root.value("hideAccountEmails", true) !== false
      onToggled: root.set("hideAccountEmails", !checked)
    }
    Hint { text: "Shows Account 1, Account 2, … instead of account identities, on screen and in exports." }
    SelectRow {
      objectName: "motionControl"
      label: "Motion"
      options: [{ value: "system", label: "Follow Hyprland" }, { value: "reduced", label: "Reduced" }]
      value: String(root.value("motion", "system")) === "reduced" ? "reduced" : "system"
      onChanged: function(next) { root.set("motion", next) }
    }
    Hint { text: "Follow Hyprland animates changes while Hyprland's animations are on. Reduced shows every change without movement." }
  }

  // ---- Costs
  Column {
    visible: root.page === "costs"
    width: parent.width
    spacing: Style.spacing.lg

    Label { text: "Local history"; font.bold: true }
    Repeater {
      model: [{ id: "codex", name: "Codex CLI" }, { id: "claude", name: "Claude Code" }, { id: "opencode", name: "OpenCode" }]
      delegate: SwitchRow {
        required property var modelData
        objectName: "costLocal-" + modelData.id
        label: modelData.name
        checked: UsageLogic.contains(root.value("costLocalProviders", UsageLogic.DEFAULT_SETTINGS.costLocalProviders), modelData.id)
        onToggled: {
          var current = UsageLogic.listOrEmpty(root.value("costLocalProviders", UsageLogic.DEFAULT_SETTINGS.costLocalProviders))
          var next = []
          var allowed = ["claude", "codex", "opencode"]
          for (var i = 0; i < allowed.length; i++)
            if (UsageLogic.contains(current, allowed[i]) !== (allowed[i] === modelData.id)) next.push(allowed[i])
          root.set("costLocalProviders", next)
        }
      }
    }
    // omp keeps its sessions here too. They are read with the providers above, so this row has a state
    // instead of a switch, centred under the switches.
    Item {
      objectName: "costLocalOmp"
      width: parent.width
      implicitHeight: Math.max(ompLocalCostLabel.implicitHeight, ompLocalCostState.implicitHeight)
      height: implicitHeight
      Label {
        id: ompLocalCostLabel
        width: parent.width - ompLocalCostState.width
        anchors.verticalCenter: parent.verticalCenter
        text: "omp sessions on this computer"
      }
      Hint {
        id: ompLocalCostState
        objectName: "costLocalOmpState"
        width: Style.space(82)
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.NoWrap
        text: UsageLogic.ompLocalCostState(root.costSources, root.value("costLocalProviders", UsageLogic.DEFAULT_SETTINGS.costLocalProviders))
      }
    }
    Hint { text: "Include sessions recorded on this computer; omp's sessions count for the providers turned on above. Costs are an estimate of API value, not subscription spend." }

    SettingsSection {
      id: serverSection
      objectName: "remoteServersSection"
      width: parent.width
      title: "Remote T3 servers"
      summary: servers.count ? servers.count + (servers.count === 1 ? " server" : " servers") : "None"
      foreground: root.foreground
      fontFamily: root.fontFamily
      onRevealRequested: function(item) { root.revealRequested(item) }
      Hint { text: "Include history from other computers running T3 Code. A server is saved once it has a name and a URL." }
      Label { visible: servers.loadError !== ""; text: servers.loadError; color: root.urgent }
      Ui.Button {
        visible: servers.loadError !== ""
        text: "Remove invalid server settings"
        foreground: root.foreground
        fontFamily: root.fontFamily
        focusable: true
        onClicked: { servers.clear(); servers.loadError = ""; root.set("costT3Servers", "[]") }
      }
      Repeater {
        id: serverRepeater
        model: servers
        delegate: Column {
          id: serverRow
          required property int index
          required property string serverId
          required property string name
          required property string url
          required property string tokenFile
          required property bool included
          width: parent.width
          spacing: Style.spacing.md
          Row {
            width: parent.width
            Label { width: parent.width - remoteToggle.width; text: serverRow.name || "New server"; anchors.verticalCenter: parent.verticalCenter; font.bold: true }
            Toggle {
              id: remoteToggle
              objectName: "t3Included-" + serverRow.index
              checked: serverRow.included
              Accessible.name: "Include " + (serverRow.name || "this server")
              onToggled: servers.update(serverRow.index, "included", !checked)
            }
          }
          TextRow {
            objectName: "t3Name-" + serverRow.index
            label: "Name"
            placeholder: "Office desktop"
            source: serverRow.name
            maximumLength: 80
            validate: function(text) { return text === "" || /[\x00-\x1f]/.test(text) ? "Give the server a name." : "" }
            onApplied: function(text) { servers.update(serverRow.index, "name", text) }
          }
          TextRow {
            objectName: "t3Url-" + serverRow.index
            label: "URL"
            placeholder: "https://t3.example.com"
            source: serverRow.url
            maximumLength: 4096
            validate: function(text) {
              return UsageLogic.secretServerUrlProblem(text, "Enter an HTTP or HTTPS URL without credentials, query, or fragment.")
            }
            onApplied: function(text) { servers.update(serverRow.index, "url", text) }
          }
          KeyRow {
            objectName: "t3Credential-" + serverRow.index
            label: "Connection token"
            settingKey: "t3Token_" + serverRow.serverId
            savedPath: serverRow.tokenFile
            blockedReason: serverRow.name.trim() === "" || serverRow.url.trim() === "" ? "Enter a name and URL before saving a token." : ""
            onSaveKey: function(secret) {
              var keys = {}, previous = {}
              keys["t3Token_" + serverRow.serverId] = secret
              previous["t3Token_" + serverRow.serverId] = serverRow.tokenFile
              var index = serverRow.index
              root.stageKeys(keys, previous, function(paths) {
                var path = paths["t3Token_" + servers.get(index).serverId]
                if (path) servers.update(index, "tokenFile", path)
              })
            }
            onRemoveKey: {
              var path = serverRow.tokenFile
              servers.update(serverRow.index, "tokenFile", "")
              if (path !== "") {
                var request = {}
                request["t3Token_" + serverRow.serverId] = path
                keyRemover.request = request
                keyRemover.running = true
              }
            }
          }
          Ui.Button {
            text: "Remove server"
            foreground: root.foreground
            fontFamily: root.fontFamily
            focusable: true
            onClicked: servers.removeServer(serverRow.index)
            onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
          }
          Ui.PanelSeparator { width: parent.width; foreground: root.foreground }
        }
      }
      Ui.Button {
        objectName: "addT3Server"
        text: "Add T3 server"
        enabled: servers.count < 4 && servers.loadError === ""
        bordered: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        focusable: true
        onClicked: servers.addServer()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
    }

    // omp stats, omp's own dashboard, on another computer: its costs and live activity, never credentials.
    SettingsSection {
      id: ompStatsSection
      objectName: "ompStatsSection"
      width: parent.width
      title: "omp on another computer"
      summary: UsageLogic.ompStatsSummary(root.settings, root.ompRemoteSource, root.ompLiveState)
      foreground: root.foreground
      fontFamily: root.fontFamily
      onRevealRequested: function(item) { root.revealRequested(item) }

      Hint { text: "Costs and live activity from omp's dashboard, omp stats, on another computer. Quotatank reads only its statistics and live feed: it never sees credentials and cannot spend quota." }
      Item {
        width: parent.width
        implicitHeight: Math.max(viaLabel.implicitHeight, viaGroup.implicitHeight)
        height: implicitHeight
        Label {
          id: viaLabel
          width: parent.width - viaGroup.width - Style.spacing.md
          anchors.verticalCenter: parent.verticalCenter
          text: "How to reach it"
        }
        Ui.ButtonGroup {
          id: viaGroup
          objectName: "ompStatsVia"
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.spacing.sm
          options: [{ value: "tailscale", label: "Tailscale" }, { value: "ssh", label: "SSH tunnel" }]
          value: root.ompStatsVia
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.caption
          Accessible.name: "How to reach omp stats: " + (root.ompStatsVia === "ssh" ? "SSH tunnel" : "Tailscale")
          onChanged: function(next) { root.ompStatsVia = next }
          onActiveFocusChanged: if (activeFocus) root.revealRequested(viaGroup)
        }
      }
      Column {
        id: viaSteps
        objectName: "ompStatsSteps"
        width: parent.width
        spacing: Style.spacing.sm
        // Another way's commands fade in, so the switch is seen.
        Connections {
          target: root
          function onOmpStatsViaChanged() { viaFade.restart() }
        }
        OpacityAnimator { id: viaFade; target: viaSteps; from: 0; to: 1; duration: root.microMs; easing.type: Easing.OutCubic }
        Repeater {
          model: root.ompStatsRecipe.steps
          delegate: Column {
            id: viaStep
            required property var modelData
            required property int index
            width: viaSteps.width
            spacing: Style.spacing.xs
            WhereLabel { text: viaStep.modelData.where === "here" ? "On this computer" : "On the other computer" }
            CommandBlock { objectName: "ompStatsCommand-" + viaStep.index; command: viaStep.modelData.command }
          }
        }
        Hint {
          text: root.ompStatsVia === "ssh" ? "Put that computer's SSH name in place of other-computer, then enter " + root.ompStatsRecipe.url + " below."
            : "Then enter that computer's Tailscale name below."
        }
      }
      UsageDisclosure {
        id: ompUnitToggle
        objectName: "ompStatsUnitToggle"
        width: parent.width
        text: root.ompStatsVia === "ssh" ? "Start both with the computers" : "Start it with the computer"
        foreground: root.foreground
        fontFamily: root.fontFamily
        onActiveFocusChanged: if (activeFocus) root.revealRequested(ompUnitToggle)
      }
      Column {
        id: ompUnits
        objectName: "ompStatsUnits"
        visible: ompUnitToggle.checked
        width: parent.width
        spacing: Style.spacing.md
        Repeater {
          model: ompUnitToggle.checked ? root.ompStatsRecipe.units : []
          delegate: Column {
            id: unitStep
            required property var modelData
            required property int index
            width: ompUnits.width
            spacing: Style.spacing.xs
            WhereLabel { text: (unitStep.modelData.where === "here" ? "On this computer" : "On the other computer") + ", save this unit" }
            CommandBlock { objectName: "ompStatsUnit-" + unitStep.index; command: unitStep.modelData.text }
            WhereLabel { text: "Then start it, now and at every login" }
            CommandBlock { objectName: "ompStatsEnable-" + unitStep.index; command: unitStep.modelData.enable }
          }
        }
        Hint { text: "Units find omp through your login shell's PATH. If one does not start, put the path that command -v omp prints in place of omp." }
      }
      Warning {
        objectName: "ompStatsWarning"
        text: "The dashboard also serves your conversations. Keep it on Tailscale or behind an SSH tunnel, never on an open network."
      }
      TextRow {
        objectName: "ompStatsUrl"
        label: "Dashboard URL"
        placeholder: root.ompStatsRecipe.url
        source: root.omp.statsUrl
        validate: function(text) { return UsageLogic.ompServerUrlProblem(text) }
        onApplied: function(text) { root.set("ompStatsUrl", text) }
      }
      TestBlock {
        objectName: "ompStatsTest"
        ready: root.omp.statsUrl !== "" && UsageLogic.ompServerUrlProblem(root.omp.statsUrl) === ""
        blockedReason: root.omp.statsUrl === "" ? "Enter the dashboard URL to test it." : ""
        running: statsProbe.active
        waitingText: "Asking omp stats" + UsageLogic.ompOnHost(root.omp.statsUrl) + "…"
        lines: root.ompStatsLines
        // The live feed follows the saved URL; its line keeps up with it after the test.
        liveLine: root.ompStatsLines.length > 0 && root.ompStatsLines[0].tone === "ok"
          ? UsageLogic.ompLiveFeedLine(root.ompLiveState, root.ompActivity ? root.ompActivity.message : "") : null
        onRequested: root.testOmpStats()
      }
    }

    SettingsSection {
      id: priceSection
      objectName: "customPricesSection"
      width: parent.width
      title: "Custom prices"
      summary: prices.priceCount === 0 ? "Automatic pricing" : prices.priceCount + (prices.priceCount === 1 ? " model" : " models")
      foreground: root.foreground
      fontFamily: root.fontFamily
      onRevealRequested: function(item) { root.revealRequested(item) }
      CostPriceEditor {
        id: prices
        width: parent.width
        foreground: root.foreground
        urgent: root.urgent
        fontFamily: root.fontFamily
        onRevealRequested: function(item) { root.revealRequested(item) }
        onEdited: root.applyPrices()
      }
      Label { visible: root.priceError !== ""; text: root.priceError; color: root.urgent; font.pixelSize: Style.font.caption }
    }

    SettingsSection {
      objectName: "scanSection"
      width: parent.width
      title: "Last scan"
      summary: root.costSources.length ? root.costSources.length + (root.costSources.length === 1 ? " source" : " sources") : "No sources yet"
      foreground: root.foreground
      fontFamily: root.fontFamily
      onRevealRequested: function(item) { root.revealRequested(item) }
      Repeater {
        model: root.costSources
        delegate: Hint {
          required property var modelData
          objectName: "costSource-" + modelData.id
          text: root.sourceDetail(modelData)
        }
      }
      Hint { visible: root.costSources.length === 0; text: "Open Costs once to scan the configured sources." }
    }
  }

  // ---- Advanced
  Column {
    visible: root.page === "advanced"
    width: parent.width
    spacing: Style.spacing.lg

    NumberRow {
      id: refreshField
      objectName: "refreshMinutes"
      width: parent.width
      label: "Refresh interval (minutes)"
      source: Math.round(Number(root.value("refreshIntervalSec", 900)) / 60)
      minimum: 1
      maximum: 60
      integer: true
      onApplied: function(minutes) { root.set("refreshIntervalSec", Math.round(minutes * 60)) }
    }
    Hint { text: "How often limits are read. Refresh any time with R or the refresh button." }

    SettingsSection {
      objectName: "diagnosticsSection"
      width: parent.width
      title: "Diagnostics"
      foreground: root.foreground
      fontFamily: root.fontFamily
      onRevealRequested: function(item) { root.revealRequested(item) }
      Hint {
        text: (root.value("hideAccountEmails", true) !== false
          ? root.accountDetails.replace(/^Account:.*(?:\n|$)/m, "") : root.accountDetails) || "Nothing to report yet."
      }
    }

    BackupSection { width: parent.width }

    Ui.PanelSeparator { width: parent.width; foreground: root.foreground }

    // Reset asks once, in place: the button turns into a confirmation that names what is kept.
    Column {
      id: resetBlock
      objectName: "resetDefaults"
      property bool confirming: false
      readonly property int changedCount: UsageLogic.changedFromDefaults(root.settings).length
      width: parent.width
      spacing: Style.spacing.md

      Row {
        width: parent.width
        visible: !resetBlock.confirming
        Column {
          width: parent.width - resetButton.width
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.spacing.xxs
          Label { text: "Reset to defaults" }
          Hint {
            text: resetBlock.changedCount === 0 ? "Everything is at its default."
              : resetBlock.changedCount + (resetBlock.changedCount === 1 ? " setting differs" : " settings differ") + " from the default."
          }
        }
        Ui.Button {
          id: resetButton
          objectName: "resetDefaultsButton"
          anchors.verticalCenter: parent.verticalCenter
          text: "Reset…"
          enabled: resetBlock.changedCount > 0
          bordered: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.bodySmall
          focusable: true
          onClicked: { resetBlock.confirming = true; Qt.callLater(function() { cancelResetButton.forceActiveFocus() }) }
          onActiveFocusChanged: if (activeFocus) root.revealRequested(resetButton)
        }
      }

      Column {
        visible: resetBlock.confirming
        width: parent.width
        spacing: Style.spacing.md
        Label { text: "Reset every setting to its default?"; font.bold: true }
        Hint { text: "Providers, menu bar, alerts, display, refresh, and cost sources go back to their defaults, including provider order and Customize overrides. Your source, server URLs, saved keys and tokens, T3 servers, and custom prices are kept." }
        Row {
          spacing: Style.spacing.md
          Ui.Button {
            id: cancelResetButton
            objectName: "cancelResetButton"
            text: "Cancel"
            foreground: root.foreground
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            focusable: true
            onClicked: resetBlock.confirming = false
            onActiveFocusChanged: if (activeFocus) root.revealRequested(cancelResetButton)
          }
          Ui.Button {
            id: confirmResetButton
            objectName: "confirmResetButton"
            text: "Reset"
            bordered: true
            selected: true
            foreground: root.foreground
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            focusable: true
            onClicked: { root.resetToDefaults(); resetBlock.confirming = false }
            onActiveFocusChanged: if (activeFocus) root.revealRequested(confirmResetButton)
          }
        }
      }
    }
  }

  function resetToDefaults() {
    setMany(JSON.parse(JSON.stringify(UsageLogic.DEFAULT_SETTINGS)))
  }

  // ---- backup: scripts/backup.py encrypts settings and saved keys with gpg; secrets cross only its stdin
  property var backupRequest: null
  property var backupDone: null
  property var staleKeyFiles: []

  function runBackup(request, done) {
    if (backupRunner.running) return
    backupRequest = request
    backupDone = done
    backupRunner.reply = ""
    backupRunner.running = true
  }

  Process {
    id: backupRunner
    property string reply: ""
    command: ["python3", "-u", decodeURIComponent(String(Qt.resolvedUrl("scripts/backup.py")).replace(/^file:\/\//, ""))]
    stdinEnabled: true
    onStarted: {
      write(JSON.stringify(root.backupRequest) + "\n")
      root.backupRequest = null
    }
    stdout: SplitParser { onRead: function(data) { if (backupRunner.reply === "") backupRunner.reply = data } }
    stderr: SplitParser { splitMarker: "" }
    onRunningChanged: if (!running && root.backupDone) {
      var done = root.backupDone
      root.backupDone = null
      var response = null
      try { response = JSON.parse(reply) } catch (error) { response = null }
      reply = ""
      done(response || { ok: false, error: "The backup helper did not answer. Check that gpg and Python 3 are installed." })
    }
  }

  Timer {
    interval: 60000
    running: backupRunner.running
    onTriggered: backupRunner.running = false
  }

  // A restore points every key setting at new private files; the files the old settings used are
  // deleted afterwards, four at a time (the helper's limit per request).
  function removeStaleKeyFiles() {
    if (keyRemover.running || staleKeyFiles.length === 0) return
    var batch = staleKeyFiles.slice(0, 4)
    staleKeyFiles = staleKeyFiles.slice(4)
    var request = {}
    for (var i = 0; i < batch.length; i++) request["stale" + i] = batch[i]
    keyRemover.request = request
    keyRemover.running = true
  }
  Connections {
    target: keyRemover
    function onRunningChanged() { if (!keyRemover.running) Qt.callLater(root.removeStaleKeyFiles) }
  }

  // A partial restore (keys or preferences only) leaves the rest as it is, so only files that the merged
  // settings stop using are deleted; the safety backup taken before the restore still holds them.
  function applyRestoredSettings(restored) {
    var before = UsageLogic.secretPaths(settings)
    var after = UsageLogic.secretPaths(Object.assign({}, settings, restored))
    setMany(restored)
    staleKeyFiles = before.filter(function (path) { return after.indexOf(path) < 0 })
    removeStaleKeyFiles()
  }

  // ---- prices
  property string priceError: ""
  function applyPrices() {
    try {
      var json = prices.serialize()
      priceError = ""
      set("costPriceOverrides", json)
    } catch (error) {
      priceError = String(error.message || error)
    }
  }
  function sourceDetail(source) {
    var labels = { ok: "Included", partial: "Partial history", stale: "Saved history · offline",
      missing: "No transcripts", failed: "Unavailable", unavailable: "Unavailable", error: "Unavailable",
      off: "Off", duplicate: "Already included" }
    var name = source.id === "local-omp" ? "omp sessions on this computer"
      : source.id === "omp-remote" ? "omp stats" + UsageLogic.ompPlace(source.host) : source.name
    var text = name + " · " + (labels[source.status] || source.status)
    if (source.status === "stale" && source.updatedAt)
      text += " · " + Qt.formatDateTime(new Date(Number(source.updatedAt)), "MMM d, HH:mm")
    return text
  }

  // ---- T3 servers: edited locally, persisted whenever every row is complete
  ListModel {
    id: servers
    property string loadError: ""
    property string lastJson: "[]"

    function load(raw) {
      if (raw === lastJson) return
      clear()
      loadError = ""
      lastJson = raw
      try {
        var rows = JSON.parse(raw)
        if (!Array.isArray(rows) || rows.length > 4) throw new Error()
        for (var i = 0; i < rows.length; i++) {
          var row = rows[i]
          if (!row || typeof row.id !== "string" || typeof row.url !== "string" || typeof row.name !== "string") throw new Error()
          append({ serverId: row.id, name: row.name, url: row.url, tokenFile: String(row.tokenFile || ""), included: row.enabled !== false })
        }
      } catch (error) { loadError = "Saved T3 settings are invalid. Remove them to configure servers again." }
    }
    function addServer() {
      if (count >= 4) return
      append({ serverId: "t3-" + Date.now() + "-" + Math.floor(Math.random() * 1000000),
        name: "", url: "", tokenFile: "", included: true })
    }
    function update(index, key, value) {
      setProperty(index, key, value)
      persist()
    }
    function removeServer(index) {
      remove(index)
      persist()
    }
    // Rows without a name or URL are kept on screen but not saved, so a half-typed server never
    // reaches the scanner.
    function persist() {
      var rows = []
      for (var i = 0; i < count; i++) {
        var row = get(i)
        if (row.name.trim() === "" || row.url.trim() === "") continue
        rows.push({ id: row.serverId, name: row.name.trim(), url: row.url.trim(), tokenFile: row.tokenFile, enabled: row.included })
      }
      lastJson = JSON.stringify(rows)
      if (lastJson !== String(root.value("costT3Servers", "[]"))) root.set("costT3Servers", lastJson)
    }
  }
  property string lastPricesJson: ""
  onSettingsChanged: {
    servers.load(String(value("costT3Servers", "[]")))
    var raw = String(value("costPriceOverrides", "{}"))
    if (raw !== lastPricesJson) { lastPricesJson = raw; prices.begin(raw) }
    forgetStaleOmpTests()
  }

  // ---- omp: Test buttons run a backend once with only omp's flags, in a process bounded in time and
  // output, and say what it found. The lines are kept while the address and token they tested stay.
  property var ompGatewayLines: []
  property var ompStatsLines: []
  property string ompGatewayTested: ""
  property string ompStatsTested: ""

  // Read from `settings` itself: this also runs from onSettingsChanged, before `omp` has caught up.
  function ompGatewayKey() {
    var current = UsageLogic.ompSettings(settings)
    return JSON.stringify([current.gatewayUrl, current.gatewayKeyFile])
  }

  function forgetStaleOmpTests() {
    if (ompGatewayTested !== "" && ompGatewayTested !== ompGatewayKey()) { ompGatewayLines = []; ompGatewayTested = "" }
    if (ompStatsTested !== "" && ompStatsTested !== UsageLogic.ompSettings(settings).statsUrl) { ompStatsLines = []; ompStatsTested = "" }
  }

  // usage-fetch.py reads only omp's gateway (--omp-only skips every other source and the history), for
  // every provider omp signs in to, so the result names all the gateway has.
  function testOmpGateway() {
    if (gatewayProbe.active || omp.gatewayUrl === "" || omp.gatewayKeyFile === "") return
    ompGatewayLines = []
    ompGatewayTested = ompGatewayKey()
    gatewayProbe.start(["python3", usageFetchPath, "--providers", UsageLogic.OMP_PROVIDER_IDS.join(","), "--source", "direct",
      "--timeout", "12", "--omp-only", "--omp-gateway-url", omp.gatewayUrl, "--omp-gateway-key-file", omp.gatewayKeyFile])
  }

  // cost-fetch.py reads only omp stats (no local providers, no T3 server) for the last 7 days.
  function testOmpStats() {
    if (statsProbe.active || omp.statsUrl === "") return
    ompStatsLines = []
    ompStatsTested = omp.statsUrl
    statsProbe.start(["python3", costFetchPath, "--providers", "", "--days", "7", "--timeout", "15", "--t3-servers", "[]",
      "--price-overrides", prices.loadError === "" ? String(value("costPriceOverrides", "{}")) : "{}", "--omp-stats-url", omp.statsUrl])
  }

  Probe {
    id: gatewayProbe
    timeoutMs: 40000
    onFinished: function(reply) {
      if (root.ompGatewayTested === root.ompGatewayKey())
        root.ompGatewayLines = UsageLogic.ompGatewayTestLines(reply, root.omp.gatewayUrl, root.enabledProviders)
    }
  }

  Probe {
    id: statsProbe
    timeoutMs: 75000
    onFinished: function(reply) {
      if (root.ompStatsTested === root.omp.statsUrl) root.ompStatsLines = UsageLogic.ompStatsTestLines(reply, root.omp.statsUrl)
    }
  }

  // Copy writes the clipboard with wl-copy in its own process, the way a paste reads it with wl-paste:
  // the text is the widget's own command (never user input), passed as one argument without a shell,
  // and the shell process never owns or reads the clipboard.
  property var copyTarget: null
  function copyCommand(block) {
    if (clipboardWriter.running) return
    copyTarget = block
    clipboardWriter.exitCode = -1
    clipboardWriter.command = ["wl-copy", "--type", "text/plain;charset=utf-8", "--", block.command]
    clipboardWriter.running = true
    copyTimeout.restart()
  }
  function finishCopy() {
    copyTimeout.stop()
    var block = copyTarget
    copyTarget = null
    if (block) block.showCopied(clipboardWriter.exitCode === 0)
  }
  Process {
    id: clipboardWriter
    property int exitCode: -1
    stdout: SplitParser { splitMarker: "" }
    stderr: SplitParser { splitMarker: "" }
    onExited: function(code) { exitCode = code }
    onRunningChanged: if (!running) root.finishCopy()
  }
  // wl-copy hands the text to a background copy of itself and returns at once; a missing one never starts.
  Timer {
    id: copyTimeout
    interval: 2000
    onTriggered: {
      if (clipboardWriter.running) clipboardWriter.running = false
      else root.finishCopy()
    }
  }

  // ---- building blocks
  component Label: PlainText {
    width: parent.width
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  component Hint: Label {
    color: Qt.darker(root.foreground, 1.5)
    font.pixelSize: Style.font.caption
  }

  // Where the command below it runs ("On the other computer").
  component WhereLabel: Hint {
    topPadding: Style.spacing.xs
  }

  // A state mark and one line of status: a filled dot while something is found (accent) or failing
  // (alert colour), a ring otherwise. The text says the same, so colour is never the only signal.
  component StatusLine: Item {
    id: statusLine
    property var line: ({ tone: "off", text: "" })
    readonly property bool filled: line.tone === "ok" || line.tone === "error"
    readonly property color toneColor: line.tone === "error" ? root.urgent
      : line.tone === "ok" ? Commons.Color.accent : Qt.darker(root.foreground, 1.5)
    visible: String(line.text || "") !== ""
    width: parent.width
    implicitHeight: statusText.implicitHeight
    height: implicitHeight
    FontMetrics { id: statusMetrics; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
    Rectangle {
      id: statusDot
      width: Style.space(6)
      height: width
      radius: width / 2
      // Centred on the first line of text.
      y: Math.round((statusMetrics.height - height) / 2)
      color: statusLine.filled ? statusLine.toneColor : "transparent"
      border.width: statusLine.filled ? 0 : Style.spacing.hairline
      border.color: statusLine.toneColor
      Behavior on color { ColorAnimation { duration: root.microMs } }
    }
    Hint {
      id: statusText
      objectName: statusLine.objectName + "Text"
      x: statusDot.width + Style.spacing.sm
      width: parent.width - x
      text: statusLine.line.text
      color: statusLine.line.tone === "error" ? root.urgent : Qt.darker(root.foreground, 1.5)
    }
  }

  // A command for the user to run, selectable, with Copy beside it (see copyCommand).
  component CommandBlock: Item {
    id: commandBlock
    property string command: ""
    property bool copied: false
    property bool failed: false
    function showCopied(ok) {
      copied = ok
      failed = !ok
      copiedReset.restart()
    }
    width: parent.width
    implicitHeight: Math.max(copyButton.implicitHeight, commandText.implicitHeight + Style.spacing.sm * 2)
    height: implicitHeight
    Ui.BorderSurface {
      anchors.left: parent.left
      anchors.right: copyButton.left
      anchors.rightMargin: Style.spacing.sm
      height: parent.height
      radius: Style.space(4)
      color: Style.normalFillFor(root.foreground, Commons.Color.accent, root.urgent)
      borderSpec: Border.flat(Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12), Style.spacing.hairline)
      TextEdit {
        id: commandText
        objectName: commandBlock.objectName + "Text"
        x: Style.spacing.md
        width: parent.width - Style.spacing.md * 2
        anchors.verticalCenter: parent.verticalCenter
        // A file's closing newline is copied, not shown.
        text: commandBlock.command.replace(/\n+$/, "")
        textFormat: TextEdit.PlainText
        // Long commands break between words when they can, so a flag stays whole on its line.
        wrapMode: TextEdit.Wrap
        readOnly: true
        selectByMouse: true
        color: root.foreground
        selectionColor: Style.selectionFillFor(root.foreground, Commons.Color.accent)
        selectedTextColor: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
    TextMetrics { id: copyMetrics; font.family: root.fontFamily; font.pixelSize: Style.font.caption; text: "Copied" }
    Ui.Button {
      id: copyButton
      objectName: commandBlock.objectName + "Copy"
      anchors.right: parent.right
      anchors.top: parent.top
      // As wide as its widest label, so the command beside it never shifts.
      width: Math.max(implicitWidth, Math.ceil(copyMetrics.advanceWidth) + horizontalPadding * 2 + Style.spacing.hairline * 2)
      text: commandBlock.copied ? "Copied" : commandBlock.failed ? "Failed" : "Copy"
      tooltipText: commandBlock.failed ? "wl-copy could not copy it. Select the command and press Ctrl+C." : ""
      foreground: commandBlock.copied ? Commons.Color.accent : commandBlock.failed ? root.urgent : root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.caption
      horizontalPadding: Style.spacing.sm
      verticalPadding: Style.spacing.xs
      focusable: true
      Accessible.name: (commandBlock.copied ? "Copied: " : "Copy: ") + commandBlock.command
      onClicked: root.copyCommand(commandBlock)
      onActiveFocusChanged: if (activeFocus) root.revealRequested(copyButton)
    }
    Timer { id: copiedReset; interval: 1600; onTriggered: { commandBlock.copied = false; commandBlock.failed = false } }
  }

  // A caution in running text, marked by a bar in the alert colour.
  component Warning: Item {
    id: warning
    property string text: ""
    width: parent.width
    implicitHeight: warningText.implicitHeight
    height: implicitHeight
    Rectangle { width: Style.space(2); height: parent.height; color: root.urgent }
    Label {
      id: warningText
      objectName: warning.objectName + "Text"
      x: Style.space(2) + Style.spacing.md
      width: parent.width - x
      text: warning.text
      font.pixelSize: Style.font.caption
    }
  }

  // One finding of a Test: ✓ in the accent colour, ✕ and the text in the alert colour, › for a note.
  // It fades and rises in after `delay`, so a result's lines arrive one after another.
  component ResultLine: Item {
    id: result
    property var line: ({ tone: "info", text: "" })
    property int delay: 0
    function replay() {
      if (root.rowMs <= 0) { appear.stop(); opacity = 1; lift.y = 0; return }
      opacity = 0
      lift.y = Style.space(3)
      appear.restart()
    }
    width: parent.width
    implicitHeight: resultText.implicitHeight
    height: implicitHeight
    transform: Translate { id: lift }
    Component.onCompleted: replay()
    onVisibleChanged: if (visible) replay()
    PlainText {
      id: resultMark
      width: Style.space(10)
      text: result.line.tone === "ok" ? "✓" : result.line.tone === "error" ? "✕" : "›"
      color: result.line.tone === "error" ? root.urgent : result.line.tone === "ok" ? Commons.Color.accent : Qt.darker(root.foreground, 1.5)
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }
    Label {
      id: resultText
      objectName: result.objectName + "Text"
      x: resultMark.width + Style.spacing.xs
      width: parent.width - x
      // Commands such as omp auth-gateway stay whole at a line break: word joiners hold their hyphens.
      text: String(result.line.text).replace(/(\w)-(?=\w)/g, "$1\u2060-\u2060")
      font.pixelSize: Style.font.caption
      color: result.line.tone === "error" ? root.urgent : result.line.tone === "ok" ? root.foreground : Qt.darker(root.foreground, 1.5)
      Behavior on color { ColorAnimation { duration: root.microMs } }
    }
    SequentialAnimation {
      id: appear
      PauseAnimation { duration: result.delay }
      ParallelAnimation {
        OpacityAnimator { target: result; from: 0; to: 1; duration: root.rowMs; easing.type: Easing.OutCubic }
        NumberAnimation { target: lift; property: "y"; to: 0; duration: root.rowMs; easing.type: Easing.OutCubic }
      }
    }
  }

  // A Test button and what the test found: after 300 ms without an answer a spinner says what it is
  // waiting for; then one line per finding. `liveLine` follows something that keeps changing after the
  // test, such as omp's live feed.
  component TestBlock: Column {
    id: test
    property bool running: false
    property bool ready: true
    property string blockedReason: ""
    property string waitingText: "Testing…"
    property var lines: []
    property var liveLine: null
    property bool slow: false
    signal requested()
    width: parent.width
    spacing: Style.spacing.sm
    onRunningChanged: if (!running) slow = false

    TextMetrics { id: labelMetrics; font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall; text: testButton.text }
    TextMetrics { id: testingMetrics; font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall; text: "Testing…" }
    Ui.Button {
      id: testButton
      objectName: test.objectName + "Button"
      text: test.running ? "Testing…" : "Test"
      // As wide as "Testing…", so the button keeps its size while it waits.
      width: implicitWidth + Math.max(0, Math.ceil(testingMetrics.advanceWidth) - Math.ceil(labelMetrics.advanceWidth))
      enabled: test.ready && !test.running
      opacity: enabled || test.running ? 1 : 0.45
      bordered: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.bodySmall
      focusable: true
      Accessible.name: "Test" + (!test.ready && test.blockedReason !== "" ? ". " + test.blockedReason : "")
      onClicked: if (enabled) test.requested()
      onActiveFocusChanged: if (activeFocus) root.revealRequested(testButton)
    }
    Hint { objectName: test.objectName + "Blocked"; visible: !test.ready && test.blockedReason !== ""; text: test.blockedReason }
    Timer { interval: 300; running: test.running && !test.slow; onTriggered: test.slow = true }
    Item {
      objectName: test.objectName + "Spinner"
      visible: test.running && test.slow
      width: parent.width
      implicitHeight: waitingLabel.implicitHeight
      height: implicitHeight
      PlainText {
        id: spinnerGlyph
        width: Style.space(10)
        horizontalAlignment: Text.AlignHCenter
        text: "󰝲"
        color: Commons.Color.accent
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        // Turns only while a test waits (each is bounded by its timeout) and never with reduced motion.
        RotationAnimator on rotation {
          from: 0
          to: 360
          duration: 900
          loops: Animation.Infinite
          running: spinnerGlyph.visible && test.running && !root.reducedMotion
        }
      }
      Hint {
        id: waitingLabel
        objectName: test.objectName + "Waiting"
        x: spinnerGlyph.width + Style.spacing.xs
        width: parent.width - x
        text: test.waitingText
      }
    }
    Repeater {
      model: test.running ? [] : test.lines
      delegate: ResultLine {
        required property var modelData
        required property int index
        objectName: test.objectName + "Line-" + index
        line: modelData
        delay: index * root.staggerMs
      }
    }
    ResultLine {
      objectName: test.objectName + "Live"
      visible: !test.running && test.lines.length > 0 && test.liveLine !== null
      line: test.liveLine || ({ tone: "info", text: "" })
      delay: test.lines.length * root.staggerMs
    }
  }

  // One run of a backend script for a Test button, bounded in output (2 MiB) and time. `finished`
  // hands over the parsed reply, { probeError: "timeout" | "tooLarge" }, or null when nothing readable
  // came back (for example when python3 could not start).
  component Probe: QtObject {
    id: probe
    property int timeoutMs: 30000
    property bool active: false
    property string body: ""
    property bool tooLarge: false
    property bool timedOut: false
    signal finished(var reply)
    function start(command) {
      if (active) return
      active = true
      body = ""
      tooLarge = false
      timedOut = false
      probeProcess.command = command
      probeProcess.running = true
      probeTimer.restart()
    }
    function finish() {
      if (!active) return
      active = false
      probeTimer.stop()
      var reply = null
      if (timedOut) reply = { probeError: "timeout" }
      else if (tooLarge) reply = { probeError: "tooLarge" }
      else { try { reply = JSON.parse(body) } catch (error) { reply = null } }
      body = ""
      finished(reply)
    }
    property Process process: Process {
      id: probeProcess
      stdout: SplitParser {
        splitMarker: ""
        onRead: function(data) {
          if (probe.tooLarge) return
          if (probe.body.length + data.length > 2097152) {
            probe.tooLarge = true
            probe.body = ""
            probeProcess.running = false
          } else probe.body += data
        }
      }
      // Drain diagnostics in arbitrary chunks without retaining them.
      stderr: SplitParser { splitMarker: "" }
      onRunningChanged: if (!running) probe.finish()
    }
    property Timer timer: Timer {
      id: probeTimer
      interval: probe.timeoutMs
      onTriggered: {
        probe.timedOut = true
        if (probeProcess.running) probeProcess.running = false
        else probe.finish()
      }
    }
  }

  component Toggle: Ui.ToggleSwitch {
    foreground: root.foreground
    activeFocusOnTab: true
    hasCursor: activeFocus
    Accessible.role: Accessible.CheckBox
    Accessible.checked: checked
    Accessible.onToggleAction: if (enabled) toggled()
    Keys.onSpacePressed: toggled()
    Keys.onReturnPressed: toggled()
    Keys.onEnterPressed: toggled()
    onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
  }

  // One index entry: title, what it is set to, and a chevron. Enter or a click opens it.
  component PageRow: Rectangle {
    id: pageRow
    property string title: ""
    property string summary: ""
    signal opened()
    width: parent.width
    implicitHeight: pageText.implicitHeight + Style.spacing.lg * 2
    radius: Style.cornerRadius
    color: pageRow.activeFocus || pageHover.hovered ? Style.hoverFillFor(root.foreground, Commons.Color.accent, root.urgent) : "transparent"
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: title + ", " + summary
    Keys.onReturnPressed: opened()
    Keys.onEnterPressed: opened()
    Keys.onSpacePressed: opened()
    onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
    HoverHandler { id: pageHover }
    TapHandler { onTapped: pageRow.opened() }
    Column {
      id: pageText
      anchors.left: parent.left
      anchors.right: pageChevron.left
      anchors.leftMargin: Style.spacing.lg
      anchors.rightMargin: Style.spacing.md
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.spacing.xxs
      PlainText {
        width: parent.width
        text: pageRow.title
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }
      PlainText {
        width: parent.width
        visible: text !== ""
        text: pageRow.summary
        color: Qt.darker(root.foreground, 1.5)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }
    PlainText {
      id: pageChevron
      anchors.right: parent.right
      anchors.rightMargin: Style.spacing.lg
      anchors.verticalCenter: parent.verticalCenter
      text: "›"
      color: Qt.darker(root.foreground, 1.5)
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
    }
  }

  component SwitchRow: Row {
    id: switchRow
    property string label: ""
    property alias checked: switchControl.checked
    signal toggled()
    width: parent.width
    Label { width: parent.width - switchControl.width; text: switchRow.label; anchors.verticalCenter: parent.verticalCenter }
    Toggle {
      id: switchControl
      objectName: switchRow.objectName + "Switch"
      width: Style.space(82)
      Accessible.name: switchRow.label
      onToggled: switchRow.toggled()
    }
  }

  component SelectRow: Row {
    id: selectRow
    property string label: ""
    property alias options: selectControl.options
    property alias value: selectControl.value
    signal changed(string value)
    function forceActiveFocus() { selectControl.forceActiveFocus() }
    width: parent.width
    height: visible ? implicitHeight : 0
    Label { width: parent.width - selectControl.width; text: selectRow.label; anchors.verticalCenter: parent.verticalCenter }
    UsageSelect {
      id: selectControl
      objectName: selectRow.objectName + "Select"
      width: Math.min(implicitWidth, selectRow.width * 0.6)
      label: selectRow.label
      foreground: root.foreground
      surface: root.surface
      fontFamily: root.fontFamily
      alignPopupRight: true
      onChanged: function(next) { selectRow.changed(next) }
      onMenuClosed: if (root.visible) selectControl.forceActiveFocus()
      onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
    }
  }

  // A number that saves as soon as it is valid. Out-of-range or malformed text stays in the field
  // with the reason underneath; the saved value is untouched until the text is good again.
  component NumberRow: Column {
    id: numberRow
    width: parent.width
    property string label: ""
    property real source: 0
    property real minimum: 0
    property real maximum: 100
    property bool integer: false
    property var validate: null
    property string error: ""
    signal applied(real value)
    spacing: Style.spacing.sm
    onSourceChanged: if (!numberField.activeFocus) { numberField.text = String(source); error = "" }
    Label { text: numberRow.label }
    SettingsField {
      id: numberField
      objectName: numberRow.objectName + "Field"
      width: parent.width
      text: String(numberRow.source)
      foreground: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      inputMethodHints: numberRow.integer ? Qt.ImhDigitsOnly : Qt.ImhFormattedNumbersOnly
      Accessible.name: numberRow.label
      onTextEdited: numberRow.check(text)
      onEditingFinished: numberRow.apply(text)
      onActiveFocusChanged: {
        if (activeFocus) root.revealRequested(this)
        else if (numberRow.error !== "") { text = String(numberRow.source); numberRow.error = "" }
      }
    }
    Hint { visible: numberRow.error !== ""; text: numberRow.error; color: root.urgent }
    // Validity of what is typed, without saving it; "" when the value could be applied.
    function problem(text) {
      var raw = String(text).trim()
      var entered = Number(raw)
      if (raw === "" || !isFinite(entered) || (integer && Math.floor(entered) !== entered) || entered < minimum || entered > maximum)
        return "Enter " + (integer ? "a whole number" : "a number") + " from " + minimum + " to " + maximum + "."
      return validate ? validate(entered) : ""
    }
    function check(text) { error = problem(text) }
    function apply(text) {
      error = problem(text)
      if (error === "") applied(Number(String(text).trim()))
    }
  }

  // Free text that saves when editing finishes (Enter or leaving the field) and is valid.
  component TextRow: Column {
    id: textRow
    width: parent.width
    property string label: ""
    property string placeholder: ""
    property string source: ""
    property int maximumLength: 4096
    property var validate: null
    property string error: ""
    signal applied(string value)
    spacing: Style.spacing.sm
    onSourceChanged: if (!textField.activeFocus) { textField.text = source; error = "" }
    Label { text: textRow.label }
    SettingsField {
      id: textField
      objectName: textRow.objectName + "Field"
      width: parent.width
      text: textRow.source
      placeholderText: textRow.placeholder
      maximumLength: textRow.maximumLength
      foreground: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      Accessible.name: textRow.label
      onTextEdited: textRow.error = ""
      onEditingFinished: textRow.apply(text)
      onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
    }
    Hint { visible: textRow.error !== ""; text: textRow.error; color: root.urgent }
    function apply(text) {
      var trimmed = String(text).trim()
      var reason = validate ? validate(trimmed) : ""
      if (reason) { error = reason; return }
      error = ""
      if (trimmed !== source) applied(trimmed)
    }
  }

  // A secret with an explicit Save: it goes to a private file, then its path is saved as the
  // setting. Saved keys show as saved; Replace opens the editor again, Remove forgets the file.
  component KeyRow: Column {
    id: keyRow
    width: parent.width
    property string label: "Key"
    property string settingKey: ""
    property string savedPath: String(root.value(settingKey, ""))
    property string hint: ""
    readonly property bool saved: savedPath !== ""
    property bool changing: false
    property string error: ""
    signal saveKey(string secret)
    signal removeKey()
    property string blockedReason: ""
    spacing: Style.spacing.sm
    // A freshly saved path means the secret is on disk: drop it from the editor.
    onSavedPathChanged: if (savedPath !== "") reset()
    function reset() { secretField.text = ""; changing = false; error = "" }
    function focusEditor() { changing = true; Qt.callLater(function() { secretField.forceActiveFocus(); root.revealRequested(secretField) }) }
    function submit() {
      if (!root.validSecret(secretField.text)) { error = "Enter the key using ASCII characters."; return }
      error = ""
      var secret = secretField.text.trim()
      if (keyRow.settingKey.indexOf("t3Token_") === 0) { keyRow.saveKey(secret); return }
      var keys = {}, previous = {}
      keys[keyRow.settingKey] = secret
      previous[keyRow.settingKey] = keyRow.savedPath
      var key = keyRow.settingKey
      root.stageKeys(keys, previous, function(paths) { if (paths[key]) root.set(key, paths[key]) })
    }
    Label { text: keyRow.label }
    Row {
      width: parent.width
      spacing: Style.spacing.md
      visible: keyRow.saved && !keyRow.changing
      Hint { width: parent.width - replaceButton.width - removeButton.width - parent.spacing * 2; text: "Saved on this device"; anchors.verticalCenter: parent.verticalCenter }
      Ui.Button {
        id: replaceButton
        text: "Replace"
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.bodySmall
        focusable: true
        onClicked: keyRow.focusEditor()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(replaceButton)
      }
      Ui.Button {
        id: removeButton
        objectName: keyRow.objectName + "Remove"
        text: "Remove"
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.bodySmall
        focusable: true
        onClicked: {
          if (keyRow.settingKey.indexOf("t3Token_") === 0) keyRow.removeKey()
          else root.removeKey(keyRow.settingKey)
        }
        onActiveFocusChanged: if (activeFocus) root.revealRequested(removeButton)
      }
    }
    Row {
      width: parent.width
      spacing: Style.spacing.md
      visible: !keyRow.saved || keyRow.changing
      SettingsField {
        id: secretField
        objectName: keyRow.objectName + "Field"
        width: parent.width - saveButton.width - parent.spacing
        password: true
        maximumLength: 8191
        placeholderText: keyRow.saved ? "New key" : keyRow.label
        foreground: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        Accessible.name: keyRow.label
        onTextEdited: keyRow.error = ""
        onAccepted: keyRow.submit()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
      Ui.Button {
        id: saveButton
        objectName: keyRow.objectName + "Save"
        anchors.verticalCenter: parent.verticalCenter
        text: root.saving ? "Saving…" : "Save"
        enabled: !root.saving && secretField.text.trim() !== "" && keyRow.blockedReason === ""
        bordered: true
        selected: enabled
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.bodySmall
        focusable: true
        onClicked: keyRow.submit()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(saveButton)
      }
    }
    Hint { visible: keyRow.error !== ""; text: keyRow.error; color: root.urgent }
    Hint { visible: keyRow.blockedReason !== "" && !keyRow.saved; text: keyRow.blockedReason }
    Hint { visible: keyRow.hint !== ""; text: keyRow.hint }
  }

  // A provider's further keys, each read as its own account card in Limits: the saved ones by name,
  // each with Remove, and an editor that names and saves one more. The key above stays the first;
  // once there is more than one, it can be named too.
  component ExtraKeys: Column {
    id: extra
    property string providerId: ""
    property string keyLabel: "API key"
    // "key" in running text; other secrets (TypeSafe's Cookie header) keep their own name.
    readonly property string keyNoun: keyLabel === "API key" ? "key" : keyLabel.charAt(0).toLowerCase() + keyLabel.slice(1)
    readonly property var entry: UsageLogic.extraKeysFor(root.value("extraKeys", "{}"), providerId)
    readonly property bool primarySaved: UsageLogic.keySaved(root.settings, providerId)
    property bool adding: false
    property string error: ""
    objectName: providerId + "ExtraKeys"
    visible: primarySaved || entry.keys.length > 0
    spacing: Style.spacing.sm

    function save() {
      if (!root.validSecret(extraSecret.text)) { error = "Enter the key using ASCII characters."; return }
      error = ""
      var id = UsageLogic.newExtraKeyId()
      var name = "extraKey_" + providerId + "_" + id
      var provider = providerId
      var label = extraName.text.trim()
      var keys = {}
      keys[name] = extraSecret.text.trim()
      root.stageKeys(keys, {}, function(paths) {
        if (paths[name]) root.set("extraKeys", UsageLogic.addExtraKey(root.value("extraKeys", "{}"), provider, { id: id, label: label, file: paths[name] }))
      })
      extraSecret.text = ""
      extraName.text = ""
      adding = false
    }

    TextRow {
      objectName: extra.providerId + "PrimaryKeyName"
      visible: extra.entry.keys.length > 0 && extra.primarySaved
      label: "Name of the " + extra.keyNoun + " above"
      placeholder: "Main key"
      maximumLength: UsageLogic.EXTRA_KEY_LABEL_LIMIT
      source: extra.entry.primary
      onApplied: function(text) { root.set("extraKeys", UsageLogic.renamePrimaryKey(root.value("extraKeys", "{}"), extra.providerId, text)) }
    }
    Repeater {
      model: extra.entry.keys
      delegate: Row {
        id: extraRow
        required property var modelData
        required property int index
        width: extra.width
        spacing: Style.spacing.md
        Label {
          width: parent.width - extraRemove.width - parent.spacing
          anchors.verticalCenter: parent.verticalCenter
          text: (extraRow.modelData.label || "Key " + (extraRow.index + 2)) + " · saved on this device"
          elide: Text.ElideRight
          wrapMode: Text.NoWrap
        }
        Ui.Button {
          id: extraRemove
          objectName: extra.providerId + "ExtraRemove-" + extraRow.index
          text: "Remove"
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.bodySmall
          focusable: true
          Accessible.name: "Remove " + (extraRow.modelData.label || "key " + (extraRow.index + 2))
          onClicked: root.removeExtraKey(extra.providerId, extraRow.modelData)
          onActiveFocusChanged: if (activeFocus) root.revealRequested(extraRemove)
        }
      }
    }
    Ui.Button {
      id: addExtra
      objectName: extra.providerId + "AddExtraKey"
      visible: extra.primarySaved && !extra.adding && extra.entry.keys.length < UsageLogic.EXTRA_KEY_LIMIT
      text: "Add another " + extra.keyNoun + "…"
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.caption
      horizontalPadding: Style.spacing.sm
      verticalPadding: Style.spacing.xs
      focusable: true
      onClicked: { extra.adding = true; Qt.callLater(function() { extraName.forceActiveFocus() }) }
      onActiveFocusChanged: if (activeFocus) root.revealRequested(addExtra)
    }
    Column {
      visible: extra.adding
      width: extra.width
      spacing: Style.spacing.sm
      Label { text: "Name" }
      SettingsField {
        id: extraName
        objectName: extra.providerId + "ExtraName"
        width: parent.width
        placeholderText: "Work, personal, team…"
        maximumLength: UsageLogic.EXTRA_KEY_LABEL_LIMIT
        foreground: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        Accessible.name: "Name of the new key"
        onAccepted: extraSecret.forceActiveFocus()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
      Label { text: extra.keyLabel }
      Row {
        width: parent.width
        spacing: Style.spacing.md
        SettingsField {
          id: extraSecret
          objectName: extra.providerId + "ExtraSecret"
          width: parent.width - extraSave.width - extraCancel.width - parent.spacing * 2
          password: true
          maximumLength: 8191
          placeholderText: extra.keyLabel
          foreground: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          Accessible.name: "New " + extra.keyLabel
          onTextEdited: extra.error = ""
          onAccepted: extra.save()
          onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
        }
        Ui.Button {
          id: extraSave
          objectName: extra.providerId + "ExtraSave"
          anchors.verticalCenter: parent.verticalCenter
          text: root.saving ? "Saving…" : "Save"
          enabled: !root.saving && extraSecret.text.trim() !== ""
          bordered: true
          selected: enabled
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.bodySmall
          focusable: true
          onClicked: extra.save()
        }
        Ui.Button {
          id: extraCancel
          anchors.verticalCenter: parent.verticalCenter
          text: "Cancel"
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.bodySmall
          focusable: true
          onClicked: { extraSecret.text = ""; extraName.text = ""; extra.adding = false; extra.error = "" }
        }
      }
      Hint { visible: extra.error !== ""; text: extra.error; color: root.urgent }
      Hint { text: "Each key shows as its own account in Limits. The name stays on this device." }
    }
  }

  // Back up and restore: one file holding every setting and saved key, encrypted with a passphrase
  // (gpg, AES-256). Restoring checks the file first and says what it holds, then asks to apply it.
  // Sign-ins that belong to each tool (Claude Code, Codex…) are not included: sign in again there.
  component BackupSection: SettingsSection {
    id: backup
    objectName: "backupSection"
    property string status: ""
    property bool failed: false
    property var found: null
    readonly property string defaultPath: "~/quotatank-backup-" + Qt.formatDate(new Date(), "yyyy-MM-dd") + ".qtbackup"
    title: "Back up and restore"
    foreground: root.foreground
    fontFamily: root.fontFamily
    onRevealRequested: function(item) { root.revealRequested(item) }

    function report(text, isError) { status = text; failed = isError }
    function clearSecrets() { exportPass.text = ""; exportRepeat.text = ""; restorePass.text = "" }
    function describe(info) {
      var keys = info.secrets === 1 ? "1 key" : info.secrets + " keys"
      return "Saved " + Qt.formatDateTime(new Date(String(info.createdAt)), "MMM d, yyyy HH:mm")
        + (info.pluginVersion ? " by Quotatank " + info.pluginVersion : "") + ": " + info.settings + " settings and " + keys + "."
        + (info.skipped ? " " + info.skipped + " older settings will be skipped." : "")
    }

    Hint { text: "Saves every setting and every key you saved here in one file, encrypted with a passphrase, to move to another computer or keep after uninstalling. Sign-ins that belong to each tool, such as Claude Code or Codex, are not included." }

    Label { text: "Back up"; font.bold: true }
    SettingsField {
      id: exportPath
      objectName: "backupExportPath"
      width: parent.width
      text: backup.defaultPath
      foreground: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      Accessible.name: "Backup file"
      onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
    }
    SettingsField {
      id: exportPass
      objectName: "backupExportPassphrase"
      width: parent.width
      password: true
      maximumLength: 1024
      placeholderText: "Passphrase (12 characters or more)"
      foreground: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      Accessible.name: "Backup passphrase"
      onTextEdited: backup.status = ""
      onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
    }
    Row {
      width: parent.width
      spacing: Style.spacing.md
      SettingsField {
        id: exportRepeat
        objectName: "backupExportRepeat"
        width: parent.width - exportButton.width - parent.spacing
        password: true
        maximumLength: 1024
        placeholderText: "Repeat the passphrase"
        foreground: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        Accessible.name: "Repeat the backup passphrase"
        onTextEdited: backup.status = ""
        onAccepted: exportButton.clicked()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
      Ui.Button {
        id: exportButton
        objectName: "backupExportButton"
        anchors.verticalCenter: parent.verticalCenter
        text: backupRunner.running ? "Working…" : "Save backup"
        enabled: !backupRunner.running && exportPath.text.trim() !== "" && exportPass.text !== ""
        bordered: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.bodySmall
        focusable: true
        onClicked: {
          if (exportPass.text.length < 12) { backup.report("Use a passphrase of 12 characters or more.", true); return }
          if (exportPass.text !== exportRepeat.text) { backup.report("The two passphrases differ.", true); return }
          backup.report("", false)
          root.runBackup({ action: "export", path: exportPath.text.trim(), passphrase: exportPass.text, settings: root.settings },
            function(response) {
              if (response.ok) backup.report("Saved to " + response.path + ": " + response.settings + " settings and "
                + (response.secrets === 1 ? "1 key" : response.secrets + " keys") + ". Keep the passphrase: without it the keys cannot be restored.", false)
              else backup.report(String(response.error || "The backup could not be saved."), true)
            })
          exportPass.text = ""
          exportRepeat.text = ""
        }
        onActiveFocusChanged: if (activeFocus) root.revealRequested(exportButton)
      }
    }

    Label { text: "Restore"; font.bold: true; topPadding: Style.spacing.md }
    SettingsField {
      id: restorePath
      objectName: "backupRestorePath"
      width: parent.width
      text: backup.defaultPath
      foreground: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      Accessible.name: "Backup file to restore"
      onTextEdited: backup.found = null
      onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
    }
    Row {
      width: parent.width
      spacing: Style.spacing.md
      SettingsField {
        id: restorePass
        objectName: "backupRestorePassphrase"
        width: parent.width - checkButton.width - parent.spacing
        password: true
        maximumLength: 1024
        placeholderText: "Passphrase"
        foreground: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        Accessible.name: "Passphrase of the backup"
        onTextEdited: { backup.found = null; backup.status = "" }
        onAccepted: checkButton.clicked()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
      Ui.Button {
        id: checkButton
        objectName: "backupCheckButton"
        anchors.verticalCenter: parent.verticalCenter
        text: backupRunner.running ? "Working…" : "Open"
        enabled: !backupRunner.running && restorePath.text.trim() !== "" && restorePass.text !== ""
        bordered: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.bodySmall
        focusable: true
        onClicked: {
          backup.report("", false)
          root.runBackup({ action: "inspect", path: restorePath.text.trim(), passphrase: restorePass.text }, function(response) {
            if (response.ok) { backup.found = response; backup.report(backup.describe(response), false) }
            else { backup.found = null; backup.report(String(response.error || "The backup could not be read."), true) }
          })
        }
        onActiveFocusChanged: if (activeFocus) root.revealRequested(checkButton)
      }
    }
    Hint { visible: backup.status !== ""; text: backup.status; color: backup.failed ? root.urgent : Qt.darker(root.foreground, 1.5) }
    // What to bring back, like Raycast's import checklist: preferences, keys and tokens, or both.
    SwitchRow {
      id: restorePreferences
      objectName: "backupRestorePreferences"
      visible: backup.found !== null
      label: "Preferences" + (backup.found ? " (" + backup.found.preferences + ")" : "")
      checked: true
      onToggled: checked = !checked
    }
    SwitchRow {
      id: restoreKeys
      objectName: "backupRestoreKeys"
      visible: backup.found !== null
      label: "Keys and tokens" + (backup.found ? " (" + backup.found.secrets + ")" : "")
      checked: true
      onToggled: checked = !checked
    }
    Row {
      visible: backup.found !== null
      spacing: Style.spacing.md
      Ui.Button {
        id: restoreButton
        objectName: "backupRestoreButton"
        text: "Restore"
        enabled: !backupRunner.running && (restorePreferences.checked || restoreKeys.checked)
        bordered: true
        selected: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.bodySmall
        focusable: true
        onClicked: {
          var path = restorePath.text.trim()
          var passphrase = restorePass.text
          var include = { preferences: restorePreferences.checked, keys: restoreKeys.checked }
          // The current settings and keys are saved first, with the same passphrase, so a restore can be undone.
          var safety = "~/quotatank-before-restore-" + Qt.formatDateTime(new Date(), "yyyy-MM-dd-HHmmss") + ".qtbackup"
          root.runBackup({ action: "export", path: safety, passphrase: passphrase, settings: root.settings }, function(saved) {
            if (!saved.ok) {
              backup.report("Nothing was restored: the current settings could not be saved first (" + String(saved.error || "unknown error") + ").", true)
              return
            }
            // Started on the next turn of the event loop: the export's process is still finishing here.
            Qt.callLater(function() {
              root.runBackup({ action: "restore", path: path, passphrase: passphrase, include: include }, function(response) {
                backup.found = null
                backup.clearSecrets()
                if (!response.ok || !response.settings) { backup.report(String(response.error || "The backup could not be restored."), true); return }
                root.applyRestoredSettings(response.settings)
                backup.report("Restored. The previous settings and keys are in " + saved.path + ", with the same passphrase. Sign in again to tools such as Claude Code where needed.", false)
              })
            })
          })
        }
        onActiveFocusChanged: if (activeFocus) root.revealRequested(restoreButton)
      }
      Ui.Button {
        text: "Cancel"
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.bodySmall
        focusable: true
        onClicked: { backup.found = null; backup.status = ""; restorePass.text = "" }
      }
    }
    Hint { visible: backup.found !== null; text: "What you pick replaces the current one. The current settings and keys are saved to a backup first, with the same passphrase." }
  }

  component LinkButton: Ui.Button {
    id: linkButton
    property string url: ""
    tooltipText: url
    foreground: root.foreground
    fontFamily: root.fontFamily
    fontSize: Style.font.caption
    horizontalPadding: Style.spacing.sm
    verticalPadding: Style.spacing.xs
    focusable: true
    Accessible.name: "Open " + url
    onClicked: Qt.openUrlExternally(url)
    onActiveFocusChanged: if (activeFocus) root.revealRequested(linkButton)
  }

  // The one-click fix for a provider that is not signed in: Sign in (opens a terminal with its
  // sign-in command), Install and sign in (mise, then the sign-in), or a link to get the tool.
  // While a started sign-in is pending it says so; the panel refreshes on its own until it lands.
  component SetupAction: Row {
    id: setup
    property var entry: null
    property var reading: null
    // A monitored provider waits for its first check before offering a fix; one that is not
    // monitored has no reading to wait for.
    property bool needsReading: false
    readonly property var action: needsReading && !reading
      ? UsageLogic.setupAction(null, null, null) : UsageLogic.setupAction(entry, reading, root.shownInstalled)
    readonly property bool pending: !!entry && root.pendingSetup === entry.id
    visible: !root.proxyMode && action.kind !== ""
    spacing: Style.spacing.sm

    Ui.Button {
      id: setupButton
      objectName: setup.entry ? "setup-" + setup.entry.id : ""
      visible: setup.action.kind === "signin" || setup.action.kind === "install"
      anchors.verticalCenter: parent.verticalCenter
      text: setup.action.label
      bordered: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.caption
      horizontalPadding: Style.spacing.sm
      verticalPadding: Style.spacing.xs
      focusable: true
      tooltipText: setup.action.command
      Accessible.name: setup.action.label + " to " + (setup.entry ? setup.entry.name : "")
      onClicked: root.runSetup(setup.entry, setup.action)
      onActiveFocusChanged: if (activeFocus) root.revealRequested(setupButton)
    }
    LinkButton {
      visible: setup.action.kind === "link"
      anchors.verticalCenter: parent.verticalCenter
      text: setup.action.label
      url: setup.action.url
    }
    Hint {
      visible: setup.pending
      anchors.verticalCenter: parent.verticalCenter
      text: "Finish in the terminal; this updates on its own."
    }
  }

  // A provider outside the monitored rows: its name and Monitor switch, then its setup hint and,
  // when it takes a key, where to get one. `keyEditable` offers a key editor on request, for a
  // provider with a sign-in of its own that can use a key instead.
  component ProviderOption: Column {
    id: option
    required property var modelData
    property string hint: modelData.signIn
    property bool keyEditable: false
    property bool keyOpen: false
    readonly property bool on: UsageLogic.contains(root.enabledProviders, modelData.id)
    objectName: "provider-" + modelData.id
    width: parent.width
    spacing: Style.spacing.xs

    // A hairline between options keeps a long list scannable without the weight of a card.
    Rectangle {
      width: parent.width
      height: Style.spacing.hairline
      color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.08)
    }
    Row {
      width: parent.width
      spacing: Style.spacing.sm
      ProviderMark { id: optionMark; providerId: option.modelData.id; anchors.verticalCenter: parent.verticalCenter }
      Label { width: parent.width - optionMark.width - optionSwitch.width - parent.spacing * 2; anchors.verticalCenter: parent.verticalCenter; text: option.modelData.name }
      Toggle {
        id: optionSwitch
        objectName: "monitor-" + option.modelData.id
        width: Style.space(82)
        Accessible.name: "Monitor " + option.modelData.name
        checked: option.on
        onToggled: root.setMonitored(option.modelData.id, !option.on)
      }
    }
    // Details line up with the name, under the mark.
    Column {
      id: optionDetails
      readonly property real innerWidth: width - leftPadding
      width: parent.width
      leftPadding: optionMark.width + Style.spacing.sm
      spacing: Style.spacing.xs
      Row {
        // The sign-in hint is what the Sign in / Install button does, so the button replaces it.
        readonly property bool hintShown: option.hint !== ""
          && !(option.hint === option.modelData.signIn && (optionSetup.action.kind === "signin" || optionSetup.action.kind === "install"))
        visible: hintShown || optionLink.visible
        width: optionDetails.innerWidth
        spacing: Style.spacing.sm
        Hint {
          visible: parent.hintShown
          width: parent.width - (optionLink.visible ? optionLink.width + parent.spacing : 0)
          anchors.verticalCenter: parent.verticalCenter
          text: option.hint
        }
        LinkButton {
          id: optionLink
          objectName: option.modelData.id + "KeysLink"
          visible: option.modelData.keysUrl !== ""
          text: option.modelData.keysLinkText
          url: option.modelData.keysUrl
        }
      }
      SetupAction {
        id: optionSetup
        entry: option.modelData
        reading: UsageLogic.readingFor(root.shownReadings, option.modelData.id)
      }
      Ui.Button {
        id: addKeyButton
        objectName: option.modelData.id + "AddKey"
        visible: option.keyEditable && option.on && !option.keyOpen
        text: "Save a key…"
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.caption
        horizontalPadding: Style.spacing.sm
        verticalPadding: Style.spacing.xs
        focusable: true
        onClicked: option.keyOpen = true
        onActiveFocusChanged: if (activeFocus) root.revealRequested(addKeyButton)
      }
      KeyRow {
        visible: option.keyOpen
        width: optionDetails.innerWidth
        objectName: option.modelData.id + "KeyRow"
        label: option.modelData.keyLabel
        settingKey: option.modelData.id + "KeyFile"
        hint: UsageLogic.keyHint(option.modelData)
      }
    }
  }

  // A provider's mark, tinted like its tile in Limits: brand colour when provider colours are on,
  // otherwise the text colour. A provider without a mark file shows its initial.
  component ProviderMark: Item {
    id: providerMark
    property string providerId: ""
    readonly property color tint: root.value("providerColors", false) === true
      ? UsageLogic.providerAccent(providerId, root.foreground) : root.foreground
    width: Style.space(14)
    height: width

    Image {
      id: markImage
      anchors.fill: parent
      source: UsageLogic.localProvider(providerMark.providerId) ? Qt.resolvedUrl("assets/" + providerMark.providerId + "-bar.svg") : ""
      sourceSize.width: providerMark.width * 2
      sourceSize.height: providerMark.height * 2
      fillMode: Image.PreserveAspectFit
      visible: false
      layer.enabled: true
    }
    MultiEffect {
      anchors.fill: markImage
      source: markImage
      visible: markImage.status === Image.Ready
      colorization: 1.0
      colorizationColor: providerMark.tint
    }
    PlainText {
      anchors.centerIn: parent
      visible: markImage.status !== Image.Ready
      text: providerMark.providerId.charAt(0).toUpperCase()
      color: providerMark.tint
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }
  }

  // ---- index summaries: what each page is set to, so the index already answers most questions
  function providersSummary() {
    var rows = proxyMode ? providerOptions : sections.listed
    var names = []
    var shown = 0
    for (var i = 0; i < rows.length; i++) {
      var id = rows[i].id
      if (!monitored(id)) continue
      names.push(UsageLogic.providerShortName(rows[i]))
      if (UsageLogic.contains(barProviders, id)) shown++
    }
    var found = proxyMode ? 0 : sections.found.length
    if (names.length === 0)
      return proxyMode ? proxyName + " · no providers yet" : found > 0 ? found + " found on this computer" : "Nothing set up yet"
    var list = names.length <= 3 ? names.join(", ") : names.slice(0, 2).join(", ") + " +" + (names.length - 2)
    var customized = customizedCount()
    // omp counts once it adds accounts: read here, or through its gateway.
    var ompAdds = !proxyMode && ompStatus && (ompStatus.local === "ok" || ompStatus.gateway === "ok")
    return (proxyMode ? proxyName + " · " : "") + list + (percentageDisplay ? " · " + shown + " in menu bar" : "")
      + (customized > 0 ? " · " + customized + " customized" : "") + (found > 0 ? " · " + found + " found" : "")
      + (ompAdds ? " · omp" : "")
  }

  // ---- per-provider overrides: Show limits as, Limit shown, Second limit below
  function barLimitValue(providerId, slot) {
    var entry = UsageLogic.parseBarLimits(value("barProviderLimits", "{}"))[providerId]
    return entry && entry[slot] !== undefined ? entry[slot] : "default"
  }

  // What one provider overrides, for its Customize header: "Default" when nothing.
  function overrideSummary(providerId) {
    var parts = []
    var mode = UsageLogic.parseQuotaModes(value("providerQuotaModes", "{}"))[providerId]
    if (mode) parts.push(UsageLogic.quotaModeLabel(mode))
    var top = barLimitValue(providerId, "top")
    if (top !== "default") parts.push(UsageLogic.windowSelectorLabel(top))
    var bottom = barLimitValue(providerId, "bottom")
    if (bottom !== "default") parts.push("+ " + (bottom === "none" ? "none" : UsageLogic.windowSelectorLabel(bottom)))
    var accounts = UsageLogic.parseAccountModes(value("accountModes", "{}"))[providerId]
    if (accounts) parts.push(UsageLogic.accountModeLabel(accounts))
    var hidden = (UsageLogic.parseHiddenAccounts(value("hiddenAccounts", "{}"))[providerId] || []).length
    if (hidden) parts.push(hidden + " hidden")
    return parts.length ? parts.join(" · ") : "Default"
  }

  function customizedCount() {
    var ids = {}
    var modes = UsageLogic.parseQuotaModes(value("providerQuotaModes", "{}"))
    var limits = UsageLogic.parseBarLimits(value("barProviderLimits", "{}"))
    for (var id in modes) ids[id] = true
    for (var other in limits) ids[other] = true
    var accountModes = UsageLogic.parseAccountModes(value("accountModes", "{}"))
    for (var accountId in accountModes) ids[accountId] = true
    var hidden = UsageLogic.parseHiddenAccounts(value("hiddenAccounts", "{}"))
    for (var hiddenId in hidden) ids[hiddenId] = true
    return Object.keys(ids).length
  }

  function menuBarSummary() {
    if (!percentageDisplay) return "Widget icon"
    var text = UsageLogic.windowSelectorLabel(value("barWindow", "auto"))
    var bottom = UsageLogic.normalizeSecondaryBarWindow(value("barWindowSecondary", "none"))
    if (bottom !== "none") text += " + " + UsageLogic.windowSelectorLabel(bottom)
    if (value("barShowResets", false) === true) text += " · resets"
    if (value("hideExhaustedProviders", false) === true) text += " · hides used up"
    var cap = Number(value("barMaxChips", UsageLogic.DEFAULT_SETTINGS.barMaxChips))
    if (cap > 0) text += " · up to " + cap + " chips"
    if (String(value("barAccountMode", "dots")) === "chips") text += " · a chip per account"
    return text
  }

  function alertsSummary() {
    if (value("notifyLimitThresholds", true) === false) return "Notifications off"
    var unit = quotaMode === "Remaining" ? "% left" : "% used"
    var text = UsageLogic.thresholdInMode(Number(value("warningThreshold", 25)), quotaMode) + " / "
      + UsageLogic.thresholdInMode(Number(value("criticalThreshold", 10)), quotaMode) + unit
    if (moneyMonitored) text += " · " + UsageLogic.formatMoney(value("creditWarningUsd", 5)) + " / " + UsageLogic.formatMoney(value("creditCriticalUsd", 1))
    return text
  }

  function displaySummary() {
    return (quotaMode === "Remaining" ? "% left" : "% used") + " · " + (value("providerColors", false) === true ? "Brand colors" : "Theme colors")
      + (value("hideAccountEmails", true) !== false ? " · Emails hidden" : "")
      + (String(value("motion", "system")) === "reduced" ? " · Reduced motion" : "")
  }

  function costsSummary() {
    var local = UsageLogic.listOrEmpty(value("costLocalProviders", UsageLogic.DEFAULT_SETTINGS.costLocalProviders))
    var names = { codex: "Codex", claude: "Claude", opencode: "OpenCode" }
    var parts = []
    for (var i = 0; i < local.length; i++) if (names[local[i]]) parts.push(names[local[i]])
    var text = parts.length ? parts.join(", ") : "No local history"
    if (servers.count > 0) text += " · " + servers.count + (servers.count === 1 ? " server" : " servers")
    if (prices.priceCount > 0) text += " · " + prices.priceCount + " custom " + (prices.priceCount === 1 ? "price" : "prices")
    if (omp.statsUrl !== "") text += " · omp stats" + UsageLogic.ompPlace(omp.statsUrl)
    return text
  }
}
