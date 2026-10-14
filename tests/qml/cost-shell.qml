import QtQuick
import Quickshell

ShellRoot {
  id: root
  property var form: null
  property var backend: null
  property var openingBackend: null
  property int openingResponses: 0
  property var view: null
  property var overview: null
  property string pickedClient: ""
  property var saved: null
  property int saves: 0
  property int savesBeforeBlankRow: 0
  property int responses: 0
  property int phase: 0
  readonly property string custom: '{"vendor/Example[1m]":{"inputCostPerMillionTokens":2,"outputCostPerMillionTokens":8,"cacheReadCostPerMillionTokens":0}}'
  readonly property var sixProviders: ["claude", "codex", "kimi", "opencode", "openrouter", "deepseek"]

  function check(condition, message) {
    if (!condition) throw new Error("COST TEST FAILED: " + message)
  }
  function create(name, values) {
    var component = Qt.createComponent(Quickshell.env("MODEL_USAGE_REPO_URL") + "/" + name)
    check(component.status === Component.Ready, component.errorString())
    var object = component.createObject(root, values || {})
    check(object !== null, component.errorString())
    return object
  }
  function find(item, name) {
    if (item.objectName === name) return item
    var children = item.children || []
    for (var i = 0; i < children.length; i++) {
      var child = find(children[i], name)
      if (child) return child
    }
    return null
  }
  // Type into a field; `done` also finishes editing, which is when free text saves.
  function edit(name, text, done) {
    var field = find(form, name)
    check(field !== null, "field exists: " + name)
    field.text = text
    field.textEdited()
    if (done) field.editingFinished()
  }
  // Press keys in a shown field: strings are typed characters, numbers are Qt key codes.
  function type(name, keys) {
    var field = find(form, name)
    var input = find(form, name + "Input")
    check(field !== null && input !== null, "shown field exists: " + name)
    for (var i = 0; i < keys.length; i++) {
      var typed = typeof keys[i] === "string"
      field.handleKey(input, { key: typed ? 0 : keys[i], text: typed ? keys[i] : "", modifiers: 0,
        accepted: false, matches: function() { return false } })
    }
  }
  // The host: persist a change batch into the live settings and acknowledge it.
  function host(values) {
    root.saves++
    root.saved = Object.assign({}, root.form.settings, values)
    root.form.settings = root.saved
    root.form.finishSave(true)
  }

  Component.onCompleted: {
    form = create("UsageSettings.qml", { width: 420, settings: { costPriceOverrides: custom, enabledProviders: root.sixProviders } })
    form.changeRequested.connect(host)
    form.begin("costs")
    view = create("UsageCosts.qml", {width: 420, payload: {
      source: "transcripts", generatedAt: "2030-01-15T12:00:00Z",
      totals: {records: 0, totalTokens: 0, costUsd: 0, historyStatus: "unavailable"},
      providers: [], models: [],
      sources: [{id: "remote", name: "T3 server", status: "unavailable", included: false}],
      periods: [{start: "2030-01-15", records: 0, costUsd: 0, totalTokens: 0,
        historyStatus: "unavailable", providers: []}]
    }})
    var models = []
    for (var i = 0; i < 10; i++)
      models.push({model: "model-" + i, providerName: "Example", costUsd: 10, totalTokens: 1000})
    overview = create("UsageCosts.qml", {width: 420, payload: {
      generatedAt: "2030-01-15T12:00:00Z", period: {days: 30},
      totals: {records: 1000, pricedRecords: 999, unpricedRecords: 1, costUsd: 1234.56,
        totalTokens: 1000000, sessions: 6},
      providers: [{id: "example", name: "Example", records: 1000, pricedRecords: 999,
        unpricedRecords: 1, costUsd: 1234.56, totalTokens: 1000000}],
      models: models, periods: [{start: "2030-01-15", costUsd: 1234.56, totalTokens: 1000000}]
    }})
    overview.periodRequested.connect(function(days) { root.overview.periodDays = days })
    backend = create("CostBackend.qml", {settings: {costLocalProviders: ["claude"]}})
    openingBackend = create("CostBackend.qml", {settings: {costLocalProviders: ["claude"]}})
    openingBackend.refreshed.connect(function() { root.openingResponses++ })
    openingBackend.ensureLoaded()
    openingBackend.ensureLoaded()
    openingBackend.ensureLoaded()
    backend.refreshed.connect(function() {
      root.responses++
      if (root.responses === 1) root.check(!backend.payload.testRequest.force, "automatic scan respects rate TTL")
    })
    backend.ensureLoaded()
    // A refresh and settings edit while a process is running must reach the
    // follow-up invocation together; neither may be lost or overlap it.
    backend.refresh()
    backend.settings = {costLocalProviders: ["claude"], costPriceOverrides: custom}
  }

  Timer {
    interval: 50
    running: true
    repeat: true
    onTriggered: {
      if (root.phase === 0) {
        root.check(root.form.page === "costs", "the gear in Costs opens the Costs page directly")
        root.form.moveProvider("codex", -1)
        root.check(root.saved.providerOrder === '["codex","claude","kimi","opencode","openrouter","deepseek"]', "moving a provider saves the whole order")
        root.check(root.form.providerOptions[0].id === "codex", "the saved order drives the provider list")
        root.form.moveProvider("codex", -1)
        root.check(root.saves === 1, "moving past the top changes nothing")
        root.form.set("quotaMode", "Remaining")
        root.form.resetToDefaults()
        root.check(root.saved.providerOrder === "[]" && root.saved.quotaMode === "Used", "reset restores order and preferences")
        root.check(root.saved.costPriceOverrides === root.custom, "reset keeps custom prices")
        root.form.settings = { costPriceOverrides: root.custom, enabledProviders: root.sixProviders }
        root.saves = 0
        root.check(!root.find(root.overview, "costModelDetails").visible, "model breakdown starts collapsed")
        root.check(!root.find(root.overview, "costTokenDetails").visible, "cost overview starts without token details")
        root.check(root.find(root.overview, "costModel-0") === null, "collapsed models are not instantiated")
        root.check(root.find(root.overview, "costSummaryValue").text === "$1,234.56", "currency has readable thousands separators")
        root.check(!root.find(root.overview, "costPricingNotice").visible, "high pricing coverage does not warn")
        root.check(root.overview.providerMetaText(root.overview.providers[0]).indexOf("99%") >= 0,
          "small gaps remain available in details without rounding up to complete coverage")
        var originalOverview = root.overview.payload
        var boundaryOverview = JSON.parse(JSON.stringify(originalOverview))
        boundaryOverview.totals.pricedRecords = 900
        boundaryOverview.totals.unpricedRecords = 100
        root.overview.payload = boundaryOverview
        root.check(!root.find(root.overview, "costPricingNotice").visible, "exactly 90 percent does not warn")
        boundaryOverview = JSON.parse(JSON.stringify(boundaryOverview))
        boundaryOverview.totals.pricedRecords = 899
        boundaryOverview.totals.unpricedRecords = 101
        root.overview.payload = boundaryOverview
        root.check(root.find(root.overview, "costPricingNotice").visible, "coverage below 90 percent warns")
        boundaryOverview = JSON.parse(JSON.stringify(boundaryOverview))
        boundaryOverview.totals.pricedRecords = 0
        boundaryOverview.totals.unpricedRecords = 1000
        root.overview.payload = boundaryOverview
        root.check(root.overview.pricingNotice().indexOf("Pricing unavailable") === 0, "unavailable pricing still warns")
        root.overview.payload = originalOverview
        root.find(root.overview, "costMetricMenu").changed("tokens")
        root.check(root.find(root.overview, "costTokenDetails").visible, "Tokens automatically opens token details")
        root.check(root.find(root.overview, "costSummaryValue").text === "1M", "metric selection updates the total")
        root.check(!root.find(root.overview, "costPricingNotice").visible, "unpriced costs do not qualify measured tokens")
        root.find(root.overview, "costMetricMenu").changed("cost")
        root.check(!root.find(root.overview, "costTokenDetails").visible, "returning to estimates restores the compact view")
        root.find(root.overview, "costPeriodTabs").setCurrentIndex(0)
        root.check(root.overview.periodDays === 1, "period tab requests 24 hours")
        root.check(root.overview.summaryDetail().indexOf("30 days") === 0, "old totals retain their actual period during a new scan")
        root.overview.modelsExpanded = true
        root.check(root.find(root.view, "costSummaryValue").text === "—", "missing history is not a zero estimate")
        root.check(root.find(root.view, "costHistoryGap-0").visible, "missing chart history is marked")
        root.check(root.find(root.view, "costSource-remote") === null, "source diagnostics are absent from Costs")
        root.form.costSources = root.view.payload.sources
        root.check(root.find(root.view, "costClient-t3") === null, "app filters are removed")
        root.check(root.form.priceEditor.serialize() === root.custom, "saved prices round-trip through QML model roles")
        root.edit("costRate-0-outputCostPerMillionTokens", "12")
        root.check(JSON.parse(root.saved.costPriceOverrides)["vendor/Example[1m]"].outputCostPerMillionTokens === 12,
          "editing a price saves it at once")
        root.check(root.form.priceEditor.serialize() === root.saved.costPriceOverrides, "the editor keeps showing what it saved")
        root.form.settings = Object.assign({}, root.form.settings, { costPriceOverrides: root.custom })
        root.check(root.form.priceEditor.serialize() === root.custom, "a change saved elsewhere replaces the editor contents")
        root.savesBeforeBlankRow = root.saves
        root.form.priceEditor.addPrice()
        root.form.page = "providers"
        root.phase++
      } else if (root.phase === 1) {
        var list = root.find(root.form, "providerList")
        list.forceLayout()
        var kimi = list.itemAtIndex(2), opencode = list.itemAtIndex(3)
        root.check(kimi && kimi.providerId === "kimi" && opencode, "provider rows are laid out for dragging")
        var dragSaves = root.saves
        list.draggingId = "kimi"
        root.form.dragProviderTo(kimi, opencode.y + 2)
        root.check(list.itemAtIndex(2).providerId === "kimi", "a drag that has not passed the next row's middle keeps the order")
        root.form.dragProviderTo(kimi, opencode.y + opencode.height - 2)
        root.check(list.itemAtIndex(3).providerId === "kimi", "past the middle the row moves")
        root.check(root.saves === dragSaves, "a drag does not save until it ends")
        root.form.finishProviderDrag()
        root.check(JSON.parse(root.saved.providerOrder).join(",") === "claude,codex,opencode,kimi,openrouter,deepseek", "releasing saves the dragged order")
        // The last local refresh places every provider once: in use as a row, a missing sign-in folded
        // away, set up here but unmonitored offered with one click, the rest under More providers.
        root.form.settings = Object.assign({}, root.form.settings, { enabledProviders: ["claude", "codex", "gemini", "openrouter"] })
        root.form.usagePayload = { generatedAt: "2030-01-15T12:00:00Z", detected: ["claude", "copilot", "deepseek"], providers: [
          { id: "claude", status: "ok", plan: "Max" },
          { id: "codex", status: "error", errorKind: "expired", message: "Expired." },
          { id: "gemini", status: "error", errorKind: "no_credentials", message: "No sign-in." },
          { id: "openrouter", status: "error", errorKind: "no_credentials", message: "No key." }
        ] }
        list.forceLayout()
        root.check(root.form.providerRows.map(function (row) { return row.id }).join(",") === "claude,codex,openrouter", "rows show the providers in use, in the saved order")
        root.check(root.find(root.form, "status-claude").text === "Connected · Max", "a connected provider names its plan")
        root.check(root.find(root.form, "status-codex").text === "Sign-in expired", "an expired sign-in is named beside its fix")
        var setupCommand = ""
        var takeSetup = function (entry, action) { setupCommand = action.command }
        root.form.setupRequested.connect(takeSetup)
        root.check(root.find(root.form, "setup-codex").visible, "an expired sign-in offers Sign in")
        root.find(root.form, "setup-codex").clicked()
        root.form.setupRequested.disconnect(takeSetup)
        root.check(setupCommand === "codex login", "Sign in asks the host to run the provider's own sign-in")
        root.check(root.find(root.form, "status-openrouter").text === "No key saved", "a key provider without a key says so")
        root.check(root.find(root.form, "openrouterKeyRow").visible, "the key editor sits under a key provider")
        root.check(root.form.sections.waiting.length === 1 && root.find(root.form, "provider-gemini") !== null, "a missing sign-in waits out of sight")
        root.check(root.form.sections.found.map(function (entry) { return entry.id }).join(",") === "copilot,deepseek", "set-up providers that are not monitored are offered")
        var foundSaves = root.saves
        root.find(root.form, "found-copilot").clicked()
        root.check(root.saves === foundSaves + 1 && root.saved.enabledProviders.indexOf("copilot") >= 0
          && root.saved.barProviders.indexOf("copilot") >= 0, "Monitor turns a found provider on, with a chip, in one save")
        root.find(root.form, "ignore-deepseek").clicked()
        root.check(root.saved.dismissedProviders.join(",") === "deepseek" && root.form.sections.found.length === 0, "Ignore stops the suggestion")
        root.form.setMonitored("claude", false)
        root.check(root.saved.dismissedProviders.join(",") === "claude,deepseek", "turning a provider off declines it")
        root.check(root.find(root.form, "providerFilterFieldInput") === null, "a collapsed section keeps no live input")
        root.find(root.form, "moreProviders").expanded = true
        var filterInput = root.find(root.form, "providerFilterFieldInput")
        root.check(filterInput !== null, "a shown settings field has a live input")
        root.check(filterInput.readOnly, "the live input stays read-only, so it never reads the clipboard on its own")
        root.type("providerFilterField", ["d", "e", "e", "p", "x", Qt.Key_Backspace])
        root.check(root.form.moreKeys.map(function (entry) { return entry.id }).join(",") === "deepseek,deepinfra"
          && root.form.moreSignIns.length === 0, "the filter narrows More providers by name")
        root.form.usagePayload = null
        root.form.page = "costs"
        root.check(root.find(root.form, "providerFilterFieldInput") === null
          && root.find(root.form, "cliproxyUrlFieldInput") === null
          && root.find(root.form, "refreshMinutesFieldInput") === null, "fields on hidden pages keep no live input")
        root.savesBeforeBlankRow = root.saves
        root.check(root.find(root.overview, "costModel-9") !== null, "expanded breakdown includes models beyond the former top eight")
        root.check(root.find(root.overview, "costModelDetails").visible, "expanded models render")
        root.overview.modelsExpanded = false
        root.check(root.find(root.overview, "costModel-9") === null, "collapsing releases model rows")
        root.check(root.find(root.form, "costSource-remote").text.indexOf("Unavailable") >= 0, "source diagnostics are available in Costs settings")
        var before = root.saves
        root.check(root.form.priceError !== "" && root.saves === root.savesBeforeBlankRow, "a blank added row is explained and not saved")
        root.edit("costModel-1", "free-model")
        root.edit("costRate-1-inputCostPerMillionTokens", "0")
        root.edit("costRate-1-outputCostPerMillionTokens", "0")
        root.check(root.form.priceError === "" && root.saves > before, "explicit zero prices save once the row is complete")
        root.check(JSON.parse(root.saved.costPriceOverrides)["free-model"].outputCostPerMillionTokens === 0,
          "zero survives settings serialization")
        root.form.settings = Object.assign({}, root.form.settings, { costPriceOverrides: "invalid" })
        root.check(root.form.priceEditor.loadError !== "", "invalid existing prices are reported")
        root.find(root.form, "costLocal-codexSwitch").toggled()
        root.check(root.saved.costPriceOverrides === "invalid", "an unrelated change never silently replaces invalid prices")
        root.form.priceEditor.begin("{}")
        root.form.applyPrices()
        root.check(root.saved.costPriceOverrides === "{}", "removing prices restores automatic pricing")
        root.phase++
      } else if (root.phase === 2 && root.responses >= 2 && !root.backend.loading) {
        root.check(root.openingResponses === 1 && !root.openingBackend.loading,
          "opening Costs through multiple view notifications starts only one scan")
        root.check(root.responses === 2, "overlapping requests collapse to one follow-up scan")
        root.check(root.backend.payload.testRequest.force, "queued explicit refresh forces prices")
        root.check(root.backend.payload.testRequest.prices === root.custom, "custom prices reach the process as exact JSON")
        root.backend.selectPeriod(7)
        root.phase++
      } else if (root.phase === 3 && root.responses === 3 && !root.backend.loading) {
        root.check(!root.backend.payload.testRequest.force, "period changes do not force price downloads")
        root.backend.settings = {costLocalProviders: ["codex"]}
        root.phase++
      } else if (root.phase === 4 && root.backend.fetchError !== "" && !root.backend.loading) {
        root.check(!root.backend.payload.generatedAt, "source change clears old totals even on failure")
        root.form.settings = {costLocalProviders: ["claude"], costT3Servers: '[{"id":"first","name":"Remote","url":"https://first.example","tokenFile":"","enabled":true}]'}
        root.find(root.form, "costLocal-claudeSwitch").toggled()
        root.check(root.saved.costLocalProviders.length === 0 && JSON.parse(root.saved.costT3Servers)[0].enabled, "remote-only setting round trips and is included")
        root.backend.settings = root.saved
        root.phase++
      } else if (root.phase === 5 && root.backend.loading) {
        root.backend.settings = {costLocalProviders: [], costT3Servers: '[{"id":"second","name":"Second","url":"https://second.example","tokenFile":"","enabled":true}]'}
        root.phase++
      } else if (root.phase === 6 && !root.backend.loading && root.backend.payload.generatedAt) {
        root.check(JSON.parse(root.backend.payload.testRequest.servers)[0].url === "https://second.example", "in-flight old server response is discarded")
        root.form.settings = {}
        root.form.begin("costs")
        root.find(root.form, "addT3Server").clicked()
        root.phase++
      } else if (root.phase === 7) {
        root.check(root.find(root.form, "t3Url-0Field") !== null, "a new server row appears at once")
        var before = root.saves
        root.edit("t3Url-0Field", "https://user:secret@t3.example", true)
        root.check(root.saves === before && root.find(root.form, "t3Url-0").error !== "", "a URL with credentials is refused in place")
        root.edit("t3Url-0Field", "https://t3.example", true)
        root.check(root.saves === before, "a server without a name is not saved yet")
        root.check(!root.find(root.form, "t3Credential-0Save").enabled, "a token cannot be saved before the server is complete")
        root.edit("t3Name-0Field", "Lab", true)
        root.check(root.saves > before && JSON.parse(root.saved.costT3Servers)[0].url === "https://t3.example", "a complete server saves on its own")
        root.edit("t3Credential-0Field", "synthetic-t3-token")
        root.saved = null
        root.find(root.form, "t3Credential-0Save").clicked()
        root.check(root.form.pendingApply !== null, "private token staging starts")
        root.phase++
      } else if (root.phase === 8 && root.saved && !root.form.saving) {
        var remote = JSON.parse(root.saved.costT3Servers)[0]
        root.check(remote.enabled && remote.tokenFile.indexOf("/management-keys/key-") >= 0, "token stored as private file reference")
        root.check(JSON.stringify(root.saved).indexOf("synthetic-t3-token") < 0, "raw token never enters widget settings")
        root.check(root.find(root.form, "t3Credential-0").saved, "saved token has an explicit configured state")
        root.check(!root.find(root.form, "t3Credential-0Field").visible, "saved token does not show an empty editor")
        root.form.begin("costs")
        root.check(JSON.parse(root.form.settings.costT3Servers)[0].tokenFile === remote.tokenFile, "saved token path round trips")
        console.log("Cost QML contract: passed")
        Qt.quit()
      }
    }
  }
  Timer { interval: 8000; running: true; onTriggered: { root.check(false, "timed out at phase " + root.phase + "; responses=" + root.responses + "; error=" + root.backend.fetchError + "; loading=" + root.backend.loading + "; request=" + JSON.stringify(root.backend.payload.testRequest)); Qt.quit() } }
}
