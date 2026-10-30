import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons

ShellRoot {
  id: root

  readonly property string resultPath: Quickshell.env("QUOTATANK_TEST_RESULT")
  readonly property string panelUrl: Quickshell.env("QUOTATANK_PANEL_URL")
  readonly property string meterUrl: Quickshell.env("QUOTATANK_METER_URL")
  readonly property string backendUrl: Quickshell.env("QUOTATANK_BACKEND_URL")
  readonly property string costBackendUrl: Quickshell.env("QUOTATANK_COST_BACKEND_URL")
  readonly property string costViewUrl: Quickshell.env("QUOTATANK_COST_VIEW_URL")
  readonly property bool screenshotMode: Quickshell.env("QUOTATANK_SCREENSHOT_MODE") === "1"
  property var failures: []
  property var objects: []
  property var widget: null
  property var malformedBackend: null
  property var proxyBackend: null
  property var proxyWidget: null
  property var richCostBackend: null
  property var malformedCostBackend: null
  property var backendErrorCostBackend: null
  property var costView: null
  property int waitAttempts: 0
  property int lastGoodWaitAttempts: 0
  readonly property var panelPositions: Quickshell.env("QUOTATANK_TEST_ALL_EDGES") === "1"
    ? ["top", "bottom", "left", "right"] : ["top"]
  property int panelPositionIndex: 0
  property bool settingsPanelChecks: false

  function fail(message) { failures.push(String(message)) }
  function assertTrue(condition, message) { if (!condition) fail(message) }
  function assertEqual(actual, expected, message) {
    if (actual !== expected) fail(message + " expected=" + expected + " actual=" + actual)
  }
  function finite(value) { return isFinite(Number(value)) && Number(value) >= 0 }

  function namedChild(item, name) {
    if (item.objectName === name) return item
    var children = item.children || []
    for (var i = 0; i < children.length; i++) {
      var found = namedChild(children[i], name)
      if (found) return found
    }
    return null
  }

  function positiveChartSegments(item) {
    if (!item) return 0
    var count = 0
    try {
      if (Number(item.amount) > 0 && Number(item.height) > 0) count++
    } catch (error) {}
    var descendants = item.children || []
    for (var index = 0; index < descendants.length; index++)
      count += positiveChartSegments(descendants[index])
    return count
  }

  function loadComponent(url, properties, label) {
    var component = Qt.createComponent(url, Component.PreferSynchronous)
    if (component.status !== Component.Ready) {
      fail(label + " failed to load: " + component.errorString())
      return null
    }
    var object = component.createObject(host, properties || {})
    if (!object) {
      fail(label + " failed to instantiate: " + component.errorString())
      return null
    }
    objects.push(object)
    return object
  }

  function formControl(name) {
    var item = namedChild(widget.settingsForm, name)
    assertTrue(item !== null, "settings control exists: " + name)
    return item
  }
  function enter(name, text) {
    var field = formControl(name)
    if (!field) return
    field.text = text
    field.textEdited()
    field.editingFinished()
  }

  function checkSettings() {
    var original = JSON.parse(JSON.stringify(widget.settings))
    widget.settings = Object.assign({}, original, { unrelatedPreference: "keep" })
    mockShell.saveCount = 0
    widget.showSettings()
    assertTrue(widget.configuring, "settings opens from the panel")
    var form = widget.settingsForm

    form.open("advanced")
    assertEqual(String(formControl("refreshMinutesField").text), "60", "refresh interval is presented in minutes")
    enter("refreshMinutesField", "")
    assertTrue(formControl("refreshMinutes").error !== "", "an empty refresh interval is refused")
    form.open("alerts")
    enter("criticalThresholdField", "50")
    assertTrue(formControl("criticalThreshold").error !== "", "a critical threshold before the warning is refused")
    assertEqual(mockShell.saveCount, 0, "refused input never reaches persistence")

    enter("criticalThresholdField", "95")
    assertEqual(mockShell.saveCount, 1, "a valid threshold saves as soon as it is entered")
    assertEqual(mockShell.savedSettings.criticalThreshold, 5, "Used entries save as % left: 95 used is 5 left")
    assertEqual(mockShell.savedSettings.warningThreshold, 25, "the untouched warning keeps its value")
    assertEqual(widget.criticalThreshold, 5, "the live widget follows the saved threshold at once")

    form.open("display")
    formControl("hideAccountEmailsToggle").toggled()
    assertTrue(widget.hideAccountEmails, "the privacy switch applies at once")
    assertEqual(mockShell.savedSettings.hideAccountEmails, true, "and is saved at once")
    assertEqual(mockShell.savedId, widget.moduleName, "settings are saved to this widget only")
    assertEqual(mockShell.savedSettings.unrelatedPreference, "keep", "saving keeps unrelated settings")

    form.open("providers")
    formControl("bar-codex").toggled()
    var savedBar = mockShell.savedSettings.barProviders || []
    assertTrue(savedBar.indexOf("codex") < 0 && savedBar.indexOf("claude") >= 0 && savedBar.indexOf("kimi") >= 0,
      "the menu bar selection is saved at once: " + savedBar.join(","))
    assertEqual(widget.percentageProviders.length, 2, "a provider taken off the bar leaves it immediately")
    assertEqual(widget.providers.length, 3, "taking a provider off the bar keeps it in the popup")

    var savesBefore = mockShell.saveCount
    mockShell.rejectSave = true
    form.open("display")
    formControl("hideAccountEmailsToggle").toggled()
    assertTrue(form.errorText !== "", "a failed save is explained")
    assertTrue(widget.hideAccountEmails, "a failed save leaves the live setting as it was")
    assertEqual(mockShell.saveCount, savesBefore, "a failed save stores nothing")
    mockShell.rejectSave = false

    widget.leaveSettings()
    assertEqual(widget.viewMode, "limits", "leaving settings returns to Limits")
    widget.settings = JSON.parse(JSON.stringify(mockShell.savedSettings))
    widget.showSettings("providers")
    assertTrue(!formControl("bar-codex").checked, "reopening shows the saved bar selection")
    form.set("barProviders", [])
    assertTrue(!widget.percentageMode, "hiding every chip retains the widget icon")
    form.set("enabledProviders", [])
    assertEqual(widget.providers.length, 0, "turning monitoring off removes popup providers immediately")
    widget.leaveSettings()
    widget.showSettings()
    assertTrue(widget.configuring, "settings remain reachable with no providers")
    widget.leaveSettings()

    widget.settings = Object.assign({}, original, { sources: proxySources("https://proxy.test/prefix", "", "", "") })
    savesBefore = mockShell.saveCount
    widget.showSettings("sources")
    assertTrue(form.proxyEntry !== null && form.proxyEntry.on, "a proxy source shows its connection fields")
    enter("proxyUrlField", "https://user:secret@proxy.test")
    assertTrue(formControl("proxyUrl").error !== "", "a proxy URL with credentials is refused")
    formControl("managementKeyRowField").text = "invalid\nkey"
    formControl("managementKeyRow").submit()
    assertTrue(formControl("managementKeyRow").error !== "", "a multiline management key is refused")
    assertTrue(!form.saving, "a refused key is never written")
    assertEqual(mockShell.saveCount, savesBefore, "refused connection input never reaches persistence")
    formControl("managementKeyRowField").text = ""
    widget.leaveSettings()

    widget.settings = original
    widget.showCosts()
    widget.showSettings()
    widget.leaveSettings()
    assertEqual(widget.viewMode, "costs", "leaving settings returns to Costs")
    widget.showLimits()
    widget.close()
  }

  function setup() {
    widget = loadComponent(panelUrl, {
      moduleName: "janitorhead.quotatank",
      bar: fakeBar,
      settings: {
        enabledProviders: ["claude", "codex", "kimi"],
        hideAccountEmails: false,
        refreshIntervalSec: 3600,
        barDisplayMode: "Percentages",
        warningThreshold: 25,
        criticalThreshold: 10
      }
    }, "Panel.qml")
    malformedBackend = loadComponent(backendUrl, {
      settings: { enabledProviders: ["kimi"], refreshIntervalSec: 3600 }
    }, "UsageBackend.qml malformed boundary")
    proxyBackend = loadComponent(backendUrl, {
      settings: { enabledProviders: ["claude", "codex"],
        sources: proxySources("https://proxy.test/prefix", "/private/proxy key", "", "") }
    }, "UsageBackend.qml CLIProxyAPI settings")
    proxyWidget = loadComponent(panelUrl, {
      moduleName: "test.proxy-widget", ipcTarget: "test.proxy-widget", bar: fakeBar,
      settings: { enabledProviders: ["claude", "codex", "kimi"],
        sources: proxySources("https://proxy.test/prefix", "/private/proxy key", "", "") }
    }, "Panel.qml proxy accounts")
    if (malformedBackend) {
      malformedBackend.settings = { enabledProviders: ["kimi"], refreshIntervalSec: 3600 }
      malformedBackend.refresh()
    }
    richCostBackend = loadComponent(costBackendUrl, {
      settings: { costLocalProviders: ["claude", "codex", "kimi"] },
      periodDays: 30
    }, "CostBackend.qml rich contract")
    if (richCostBackend) richCostBackend.refresh()
    malformedCostBackend = loadComponent(costBackendUrl, {
      settings: { costLocalProviders: [] },
      periodDays: 30
    }, "CostBackend.qml malformed boundary")
    if (malformedCostBackend) {
      malformedCostBackend.settings = { costLocalProviders: [] }
      malformedCostBackend.refresh()
    }
    backendErrorCostBackend = loadComponent(costBackendUrl, {
      settings: { costLocalProviders: ["claude", "codex", "kimi"] },
      periodDays: 30
    }, "CostBackend.qml last-known-good boundary")
    if (backendErrorCostBackend) backendErrorCostBackend.refresh()
    waitForBackend.running = true
  }

  function runChecks() {
    if (proxyBackend) {
      assertEqual(proxyBackend.fetchError, "", "CLIProxyAPI settings reach the backend")
      assertEqual(proxyBackend.providers.length, 2, "a proxy reads the monitored providers")
      if (proxyBackend.providers.length > 0) {
        assertEqual(proxyBackend.providers[0].source, "CLIProxyAPI management API", "proxy source is retained")
        assertEqual(proxyBackend.providers[0].proxy.id, "p-1a2b3c4d", "a proxy reading names its proxy")
      }
    }
    if (proxyWidget) {
      assertEqual(proxyWidget.providers.length, 3, "the popup shows the monitored providers the proxy reads")
      proxyWidget.selectProviderId("codex")
      assertEqual(proxyWidget.proxyAccounts.length, 3, "all three Codex subscriptions are available together")
      assertEqual(proxyWidget.accountList.view.count, 3, "three separate Codex account rows are rendered")
      assertTrue(proxyWidget.accountOverview, "proxy defaults to account overview")
      assertEqual(proxyWidget.accountMode, "together", "proxy accounts are used together")
      var expectedAccounts = { "0": { remaining: 20, resets: "0 resets" }, "1": { remaining: 55, resets: "1 reset" },
        "2": { remaining: 90, resets: "2 resets" } }
      proxyWidget.proxyAccounts.forEach(function (account) {
        var id = String(account.accountId)
        var expected = expectedAccounts[id]
        var row = proxyWidget.accountList.rowFor(id)
        assertTrue(expected !== undefined, "account " + id + " is one of the fixture's")
        assertTrue(row !== null, "account " + id + " has a row")
        if (!expected || !row) return
        var weekly = (row.account.windows || []).filter(function (window) { return window.id === "codex-secondary" })[0]
        assertEqual(weekly ? weekly.remaining : null, expected.remaining, "account " + id + " keeps its own quota")
        var badge = namedChild(row, "accountResetBadge")
        var label = namedChild(row, "accountResetLabel")
        assertTrue(badge !== null && badge.width > 0 && badge.height > 0, "account " + id + " reset badge has a visible size")
        assertEqual(label ? label.text : "", expected.resets, "account " + id + " shows its own banked resets, including zero")
      })
      assertEqual(proxyWidget.accountList.rowModel.get(0).rowKey, "codex@0", "least headroom first")
      proxyWidget.selectAccount("2")
      assertEqual(proxyWidget.selectedAccount.accountId, "2", "a row selects the account the detail shows")
      assertEqual(proxyWidget.limitCards.count, 4, "the detail shows every limit of the selected account")
      proxyWidget.selectProviderId("kimi")
      assertEqual(proxyWidget.selectedAccountId, "", "provider navigation returns to the counted account")
      assertEqual(proxyWidget.viewOptions.length, 2, "Limits and Costs")
      assertTrue(proxyWidget.hideAccountEmails, "account emails are hidden by default")
      assertEqual(proxyWidget.accountDisplayName({account: "secret@example.invalid"}, 2), "Account 2", "hidden label contains no account identity")
      assertTrue(proxyWidget.accountTooltip({account: "secret@example.invalid"}).indexOf("secret") < 0, "settings cannot reveal hidden account identity")
      proxyWidget.settings = Object.assign({}, proxyWidget.settings,
        {barDisplayMode: "Percentages", barProviders: ["codex"], quotaMode: "Remaining"})
      proxyWidget.selectProviderId("codex")
      var nowSeconds = Date.now() / 1000
      proxyWidget.accountActivity.providers = [{id: "codex", status: "ok", accountId: "0", lastUsedAt: nowSeconds}]
      var barLabel = namedChild(proxyWidget, "barAccountLabel")
      var barRemaining = namedChild(proxyWidget, "barAccountRemaining")
      assertTrue(barLabel === null, "bar contains no account name label")
      assertEqual(proxyWidget.lastAccount(proxyWidget.provider).label, "Account 1", "tooltip respects hidden account emails")
      assertEqual(barRemaining ? barRemaining.text : "", "20%", "bar quota belongs to the account that just served a request")
      proxyWidget.accountActivity.providers = [{id: "codex", status: "ok", accountId: "1", lastUsedAt: nowSeconds + 1}]
      assertEqual(proxyWidget.lastAccount(proxyWidget.provider).label, "Account 2", "tooltip follows account switches")
      assertEqual(barRemaining.text, "55%", "account switch updates quota together with label")
      proxyWidget.settings = Object.assign({}, proxyWidget.settings, {hideAccountEmails: false})
      assertEqual(proxyWidget.accountDisplayName({account: "secret@example.invalid"}, 2), "secret@example.invalid", "privacy setting can reveal account labels")
      assertEqual(proxyWidget.lastAccount(proxyWidget.provider).label, "codex-1@example.invalid", "tooltip reveals email only when requested")
      assertTrue(namedChild(proxyWidget, "barAccountLabel") === null, "emails stay out of the bar when privacy is disabled")
      proxyWidget.accountActivity.providers = []
      assertEqual(barRemaining.text, "20%", "without recent activity the chip counts the account closest to its limit, as Limits does")
      var codexChip = namedChild(proxyWidget, "barChip-codex")
      assertTrue(codexChip !== null && codexChip.tooltipText === "", "accounts get the hover card instead of the plain tooltip")
      proxyWidget.accountActivity.providers = [{id: "codex", status: "ambiguous", lastUsedAt: nowSeconds}]
      assertEqual(barRemaining.text, "20%", "ambiguous activity names no account")
    }
    if (widget) {
      assertEqual(widget.moduleName, "janitorhead.quotatank", "moduleName injection")
      assertEqual(widget.ipcTarget, "janitorhead.quotatank", "IPC target")
      assertEqual(widget.setting("missing", "fallback"), "fallback", "setting fallback")
      assertTrue(finite(widget.implicitWidth), "horizontal implicitWidth is finite")
      assertTrue(finite(widget.implicitHeight), "horizontal implicitHeight is finite")
      assertEqual(widget.providers.length, 3, "all normalized providers render")
      assertEqual(widget.provider.id, "claude", "first provider is selected")
      assertEqual(widget.provider.windows.length, 3, "arbitrary Claude windows render")
      assertEqual(widget.heroMeta(widget.provider), "Claude Max 20x",
        "hero keeps the subscription type visible")
      assertTrue(widget.heroMeta(widget.provider).indexOf("fixture@example.invalid") < 0,
        "hero hides account identity")
      assertTrue(widget.accountTooltip(widget.provider).indexOf("Account: fixture@example.invalid") >= 0,
        "account identity is available in settings")
      assertTrue(widget.accountTooltip(widget.provider).indexOf("Source: Claude OAuth usage API") >= 0,
        "account source is available in settings")
      assertEqual(widget.percentageMode, true, "percentages show with meaningful horizontal data")
      assertEqual(widget.percentageProviders.length, 3, "compact mode includes every meaningful provider")
      assertTrue(widget.alarming, "critical provider activates urgent state")
      widget.nextProvider()
      assertEqual(widget.provider.id, "codex", "next selects Codex")
      assertEqual(widget.provider.windows.length, 4, "additional Codex windows render")
      assertTrue(widget.provider.credits !== null, "Codex credits render")
      widget.nextProvider()
      assertEqual(widget.provider.id, "kimi", "next selects Kimi")
      assertTrue(widget.provider.credits !== null, "Kimi extra usage renders")
      widget.handleProviderChipPress("codex", Qt.LeftButton)
      assertEqual(widget.provider.id, "codex", "provider chip opens its provider directly")
      assertTrue(widget.opened, "provider chip opens the panel")
      widget.handleProviderChipPress("codex", Qt.LeftButton)
      assertTrue(!widget.opened, "selected provider chip toggles the panel closed")
      assertEqual(widget.windowSeverity({ remaining: 9 }), "critical", "critical quota state")
      assertEqual(widget.windowSeverity({ remaining: 20 }), "warning", "warning quota state")
      assertTrue(widget.errorBody({ message: "Expired", errorKind: "expired", authCommand: "kimi login" }).indexOf("kimi login") >= 0,
        "auth command is shown for expired credentials")
      assertEqual(widget.errorBody({ message: "Sign in through CLIProxyAPI.", errorKind: "expired", authCommand: "" }),
        "Sign in through CLIProxyAPI.", "managed credentials do not suggest local CLI login")
      widget.showCosts()
      assertEqual(widget.viewMode, "costs", "Costs IPC/view helper selects the isolated tab")
      widget.showCostSettings()
      assertTrue(widget.configuring && widget.settingsForm.page === "costs", "the Costs gear opens Settings on its Costs page")
      widget.leaveSettings()
      assertEqual(widget.viewMode, "costs", "leaving settings restores Costs")
      widget.showLimits()
      assertEqual(widget.viewMode, "limits", "Limits IPC/view helper restores quota view")
      widget.close()

      checkSettings()

      var positions = ["top", "bottom", "left", "right"]
      for (var i = 0; i < positions.length; i++) {
        fakeBar.position = positions[i]
        fakeBar.vertical = positions[i] === "left" || positions[i] === "right"
        assertTrue(finite(widget.implicitWidth), positions[i] + " implicitWidth is finite")
        assertTrue(finite(widget.implicitHeight), positions[i] + " implicitHeight is finite")
        if (fakeBar.vertical) assertEqual(widget.percentageMode, false, positions[i] + " falls back to icon mode")
      }

      Color.foreground = "#171717"
      Color.background = "#fafafa"
      Color.accent = "#7c3aed"
      Color.urgent = "#dc2626"
      Style.fontBaseSize = 16
      Style.spacingScale = 1.35
      assertTrue(finite(widget.implicitWidth), "light/scaled theme implicitWidth is finite")
      Color.foreground = "#f4f4f5"
      Color.background = "#09090b"
      Color.accent = "#22d3ee"
      Style.fontBaseSize = 11
      Style.spacingScale = 0.85
      assertTrue(finite(widget.implicitHeight), "dark/compact theme implicitHeight is finite")
    }

    if (malformedBackend) {
      assertEqual(malformedBackend.providers.length, 0,
        "malformed backend data cannot replace the initial safe payload")
      assertTrue(malformedBackend.fetchError.indexOf("unreadable") >= 0,
        "malformed backend data gets a clean error")
    }

    if (richCostBackend) {
      assertEqual(richCostBackend.providers.length, 2, "cost backend exposes every selected provider")
      assertEqual(richCostBackend.payload.totals.costUsd, 12.34, "cost backend preserves estimated cost")
      assertTrue(richCostBackend.payload.periods.length > 0, "cost chart periods are available")
      costView = loadComponent(costViewUrl, {
        width: 420,
        periodDays: 30,
        metric: "cost"
      }, "UsageCosts.qml chart")
      if (costView)
        costView.payload = JSON.parse(JSON.stringify(richCostBackend.payload))
    }

    if (malformedCostBackend) {
      assertEqual(malformedCostBackend.providers.length, 0,
        "malformed cost data cannot replace the initial safe payload")
      assertTrue(malformedCostBackend.fetchError.indexOf("unreadable") >= 0,
        "malformed cost data gets a clean error")
    }

    if (backendErrorCostBackend) {
      assertEqual(backendErrorCostBackend.providers.length, 2,
        "last-known-good backend starts with a rich payload")
    }

    var meter = loadComponent(meterUrl, { width: 243, height: 10, value: 0.635 }, "BlockMeter.qml")
    if (meter) {
      assertTrue(meter.blockCount > 8, "meter renders fixed blocks")
      assertTrue(meter.completeBlocks > 0, "meter fills complete blocks")
      assertTrue(meter.boundaryFraction > 0 && meter.boundaryFraction < 1,
        "meter keeps a partially filled boundary block")
    }

    if (costView) costChartSettle.restart()
    else startLastGoodCheck()
  }

  function startLastGoodCheck() {
    if (!backendErrorCostBackend) {
      startPanelChecks()
      return
    }
    backendErrorCostBackend.settings = { costLocalProviders: ["claude", "codex"], costPriceOverrides: "synthetic-failure" }
    lastGoodWaitAttempts = 0
    waitForLastGood.running = true
  }

  function startPanelChecks() {
    if (widget) {
      if (screenshotMode) widget.selectProviderId("claude")
      panelPositionIndex = 0
      mapPanelAtCurrentEdge()
    } else {
      writeResult()
    }
  }

  // The Sources entry that holds the proxy: the old proxy mode is one switched-on proxy row.
  function proxySources(url, keyFile, keeperUrl, keeperPasswordFile) {
    return JSON.stringify([{ id: "p-1a2b3c4d", kind: "proxy", url: url, keyFile: keyFile,
      keeperUrl: keeperUrl, keeperPasswordFile: keeperPasswordFile, on: true }])
  }
  function proxyRow(settings) {
    var rows = JSON.parse(String(settings.sources || "[]"))
    for (var i = 0; i < rows.length; i++) if (rows[i].kind === "proxy") return rows[i]
    return {}
  }

  property var beforeKeySettings: ({})
  property int keySavePhase: 0
  property string keyPathBeforeFailure: ""
  function startKeySaveCheck() {
    beforeKeySettings = JSON.parse(JSON.stringify(widget.settings))
    widget.settings = Object.assign({}, beforeKeySettings,
      { sources: proxySources("https://proxy.test/prefix", "", "https://keeper.example/keeper", "") })
    widget.showSettings("sources")
    formControl("managementKeyRowField").text = "qml-synthetic-management-key"
    formControl("managementKeyRow").submit()
    keySavePhase = 0
    waitForKeySave.restart()
  }

  // The key writer starts asynchronously, so `saving` alone can read false before it has begun.
  function keySaveSettled() {
    var form = widget.settingsForm
    if (form.saving) return false
    if (form.errorText !== "") return true
    var proxy = proxyRow(mockShell.savedSettings)
    if (keySavePhase === 0) return String(proxy.keyFile || "") !== ""
    if (keySavePhase === 1) return String(proxy.keeperPasswordFile || "") !== ""
    return false
  }

  function writeResult() {
    writer.command = ["python3", "-c",
      "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2], encoding='utf-8')",
      resultPath, JSON.stringify({ ok: failures.length === 0, failures: failures })]
    writer.running = true
  }

  function mapPanelAtCurrentEdge() {
    var position = panelPositions[panelPositionIndex]
    fakeBar.position = position
    fakeBar.vertical = position === "left" || position === "right"
    if (settingsPanelChecks) widget.showSettings()
    else widget.open()
    assertTrue(widget.opened, position + " panel opens through the native controller")
    panelCloseTimer.restart()
  }

  PanelWindow {
    id: testBarWindow
    visible: true
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    implicitWidth: fakeBar.vertical ? fakeBar.barSize : 1
    implicitHeight: fakeBar.vertical ? 1 : fakeBar.barSize
    anchors.top: fakeBar.position !== "bottom"
    anchors.bottom: fakeBar.position !== "top"
    anchors.left: fakeBar.position !== "right"
    anchors.right: fakeBar.position !== "left"
    mask: Region { width: 0; height: 0 }

    Item {
      id: host
      anchors.fill: parent
    }
  }

  QtObject {
    id: mockShell
    property var bar: fakeBar
    property var barConfig: ({ position: fakeBar.position })
    property var shellConfig: ({ version: 1, plugins: [], bar: { layout: { left: [], center: [], right: [] } } })
    function firstPartyServiceFor(id) { return null }
    function serviceFor(id) { return null }
    property bool rejectSave: false
    property int saveCount: 0
    property string savedId: ""
    property var savedSettings: ({})
    function updateEntryInline(moduleName, settings) {
      if (rejectSave) return false
      saveCount++
      savedId = moduleName
      savedSettings = JSON.parse(JSON.stringify(settings))
      return true
    }
  }

  QtObject {
    id: fakeBar
    property bool vertical: false
    property int barSize: 26
    property string position: "top"
    property string fontFamily: "monospace"
    property color foreground: "#f4f4f5"
    property color barForeground: foreground
    property color background: "#09090b"
    property color urgent: "#ef4444"
    property bool foregroundAnimationEnabled: false
    property var activePopout: null
    property var clickTargets: []
    property var shell: mockShell
    function run(command) {}
    function showTooltip(target, text) {}
    function hideTooltip(target) {}
    function requestPopout(owner) { activePopout = owner }
    function releasePopout(owner) { if (activePopout === owner) activePopout = null }
    function registerClickTarget(target) { clickTargets.push(target) }
    function unregisterClickTarget(target) {}
    function switchPanelFrom(owner, direction) { return false }
  }

  Process {
    id: writer
    running: false
    onExited: Qt.quit()
  }

  Timer {
    interval: 1
    running: true
    repeat: false
    onTriggered: root.setup()
  }

  Timer {
    id: waitForBackend
    interval: 25
    running: false
    repeat: true
    onTriggered: {
      root.waitAttempts++
      var richReady = root.widget && root.widget.providers.length === 3
      var malformedReady = root.malformedBackend && root.malformedBackend.fetchError !== ""
      var costReady = root.richCostBackend && root.richCostBackend.providers.length === 2
      var malformedCostReady = root.malformedCostBackend && root.malformedCostBackend.fetchError !== ""
      var lastGoodReady = root.backendErrorCostBackend && root.backendErrorCostBackend.providers.length === 2
      var proxyReady = root.proxyBackend && root.proxyBackend.providers.length === 2
        && root.proxyWidget && root.proxyWidget.providers.length === 3
      if ((richReady && malformedReady && costReady && malformedCostReady && lastGoodReady && proxyReady)
          || root.waitAttempts >= 120) {
        stop()
        if (root.proxyWidget) root.proxyWidget.selectProviderId("codex")
        accountRowsSettle.restart()
      }
    }
  }

  // Account rows follow the selected provider a frame later (AccountList syncs through Qt.callLater).
  Timer {
    id: accountRowsSettle
    interval: 50
    repeat: false
    onTriggered: root.runChecks()
  }

  Timer {
    id: costChartSettle
    interval: 25
    repeat: false
    onTriggered: {
      root.assertTrue(root.costView.chartMaximum > 0,
        "cost chart computes a positive scale from the fixture")
      root.assertTrue(root.positiveChartSegments(root.costView) > 0,
        "cost chart renders positive-height provider segments from nested period data")
      root.startLastGoodCheck()
    }
  }

  Timer {
    id: waitForLastGood
    interval: 25
    running: false
    repeat: true
    onTriggered: {
      root.lastGoodWaitAttempts++
      if ((root.backendErrorCostBackend
          && root.backendErrorCostBackend.fetchError === "Synthetic estimated-cost failure")
          || root.lastGoodWaitAttempts >= 120) {
        stop()
        root.assertEqual(root.backendErrorCostBackend.providers.length, 2,
          "backendError preserves the last-known-good cost payload")
        root.startKeySaveCheck()
      }
    }
  }

  Timer {
    id: waitForKeySave
    interval: 25
    repeat: true
    property int attempts: 0
    onTriggered: {
      attempts++
      if (!root.keySaveSettled() && attempts < 300) return
      stop()
      var form = root.widget.settingsForm
      if (root.keySavePhase === 0) {
        root.assertEqual(form.errorText, "", "the management key saves without an error")
        root.assertTrue(root.widget.configuring, "saving a key keeps Settings open")
        root.assertEqual(root.formControl("managementKeyRowField").text, "", "a saved key leaves the editor")
        root.assertTrue(String(root.proxyRow(mockShell.savedSettings).keyFile).indexOf("/management-keys/key-") > 0,
          "the key is saved as a generated private file path")
        root.assertTrue(JSON.stringify(mockShell.savedSettings).indexOf("qml-synthetic-management-key") < 0,
          "the management key never reaches the widget settings")
        var savedPath = String(root.proxyRow(root.widget.settings).keyFile)
        root.formControl("managementKeyRow").submit()
        root.assertTrue(root.formControl("managementKeyRow").error !== "" && !form.saving, "an empty key is refused")
        root.assertEqual(String(root.proxyRow(root.widget.settings).keyFile), savedPath, "and the saved key stays")
        root.formControl("keeperPasswordRowField").text = "qml-synthetic-keeper-password"
        root.formControl("keeperPasswordRow").submit()
        root.keySavePhase = 1
        attempts = 0
        restart()
      } else if (root.keySavePhase === 1) {
        root.assertEqual(form.errorText, "", "the Keeper password saves without an error")
        root.assertEqual(root.formControl("keeperPasswordRowField").text, "", "a saved Keeper password leaves the editor")
        root.assertTrue(JSON.stringify(mockShell.savedSettings).indexOf("qml-synthetic-keeper-password") < 0,
          "the Keeper password never reaches the widget settings")
        root.assertTrue(String(root.proxyRow(mockShell.savedSettings).keeperPasswordFile).indexOf("/management-keys/key-") > 0,
          "the Keeper password is saved only as a private file path")
        root.keyPathBeforeFailure = String(root.proxyRow(mockShell.savedSettings).keyFile)
        root.formControl("managementKeyRowField").text = "replacement-that-must-be-rolled-back"
        mockShell.rejectSave = true
        root.formControl("managementKeyRow").submit()
        root.keySavePhase = 2
        attempts = 0
        restart()
      } else {
        root.assertTrue(form.errorText !== "", "a key whose settings cannot be saved is explained")
        root.assertEqual(String(root.proxyRow(mockShell.savedSettings).keyFile), root.keyPathBeforeFailure,
          "and the saved key path stays")
        mockShell.rejectSave = false
        root.widget.leaveSettings()
        root.widget.settings = root.beforeKeySettings
        root.startPanelChecks()
      }
    }
  }

  Timer {
    id: panelCloseTimer
    interval: root.screenshotMode ? 600000 : 120
    repeat: false
    onTriggered: {
      root.widget.close()
      root.assertTrue(!root.widget.opened,
        root.panelPositions[root.panelPositionIndex] + " panel closes through the native controller")
      root.panelPositionIndex++
      if (root.panelPositionIndex < root.panelPositions.length) panelNextTimer.restart()
      else if (!root.settingsPanelChecks) {
        root.settingsPanelChecks = true
        root.panelPositionIndex = 0
        panelNextTimer.restart()
      } else {
        root.widget.showCostSettings()
        root.formControl("customPricesSection").expanded = true
        root.widget.settingsForm.priceEditor.begin("{}")
        for (var i = 0; i < 16; i++) root.widget.settingsForm.priceEditor.addPrice()
        settingsScrollCheck.restart()
      }
    }
  }

  Timer {
    id: settingsScrollCheck
    interval: 250
    onTriggered: {
      var editor = root.widget.settingsForm.priceEditor
      var field = editor.findItem(editor, "costModel-15")
      var flick = field
      while (flick && flick.contentY === undefined) flick = flick.parent
      root.assertTrue(!!flick, "settings editor is in a scrollable view")
      if (flick) {
        var point = field.mapToItem(flick, 0, 0)
        root.assertTrue(flick.contentY > 0, "adding a price scrolls a long form")
        root.assertTrue(point.y >= 0 && point.y + field.height <= flick.height,
          "new price field is fully visible above the fixed settings footer")
      }
      root.widget.leaveSettings()
      root.widget.close()
      root.writeResult()
    }
  }

  Timer {
    id: panelNextTimer
    interval: 180
    repeat: false
    onTriggered: root.mapPanelAtCurrentEdge()
  }

  Timer {
    interval: 250
    running: root.screenshotMode
    repeat: true
    onTriggered: {
      if (root.widget && !root.widget.opened) root.widget.open()
    }
  }

  Component.onDestruction: {
    for (var i = 0; i < objects.length; i++) {
      if (objects[i] && typeof objects[i].destroy === "function") objects[i].destroy()
    }
  }
}
