import QtQuick
import Quickshell
import Quickshell.Io

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
  property string backupFile: ""
  property var backupReply: null
  // 1.9 Costs tab: a view over a payload with projects, agents, heatmap and previous totals.
  property var costs: null
  property var rich: null
  property var keptBars: []
  property int costsPhase: 0
  property int costsWait: 0
  property bool costsDone: false
  readonly property string custom: '{"vendor/Example[1m]":{"inputCostPerMillionTokens":2,"outputCostPerMillionTokens":8,"cacheReadCostPerMillionTokens":0}}'
  readonly property var sixProviders: ["claude", "codex", "kimi", "opencode", "openrouter", "deepseek"]

  function check(condition, message) {
    if (!condition) throw new Error("COST TEST FAILED: " + message)
  }
  function create(name, values) {
    var component = Qt.createComponent(Quickshell.env("QUOTATANK_REPO_URL") + "/" + name)
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
  // Press keys in a shown field: strings are typed characters, numbers are Qt key codes. The plain
  // input edits natively, so it is driven the way typing changes it; the read-only secret input
  // takes its keys through the field's key handler.
  function type(name, keys) {
    var field = find(form, name)
    var input = find(form, name + "Input")
    check(field !== null && input !== null, "shown field exists: " + name)
    for (var i = 0; i < keys.length; i++) {
      var typed = typeof keys[i] === "string"
      if (!input.readOnly && typed) input.insert(input.cursorPosition, keys[i])
      else if (!input.readOnly) input.remove(input.cursorPosition - 1, input.cursorPosition)
      else field.handleKey(input, { key: typed ? 0 : keys[i], text: typed ? keys[i] : "", modifiers: 0,
        accepted: false, matches: function() { return false } })
    }
  }
  // Editable TextInputs (what TextField is built on) fetch the clipboard on every change in Qt 6.11
  // and 6.12.0; a TextEdit or a read-only TextInput does not.
  function editableTextInputs(item) {
    var count = item.echoMode !== undefined && item.readOnly === false ? 1 : 0
    var children = item.children || []
    for (var i = 0; i < children.length; i++) count += editableTextInputs(children[i])
    return count
  }
  // The host: persist a change batch into the live settings and acknowledge it.
  function host(values) {
    root.saves++
    root.saved = Object.assign({}, root.form.settings, values)
    root.form.settings = root.saved
    root.form.finishSave(true)
  }

  Component.onCompleted: {
    form = create("UsageSettings.qml", { width: 420, settings: { costPriceOverrides: custom, enabledProviders: root.sixProviders },
      costModels: [{ model: "vendor/Example[2m]", costUsd: 1.5 }, { model: "free-model", costUsd: null },
        { model: "vendor/Example[2m]", costUsd: 1.5 }, { model: "Other models", costUsd: 0.2 }, { model: "Unknown model", costUsd: null }] })
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
    root.rich = JSON.parse(dimensionsFile.text())
    costs = create("UsageCosts.qml", { width: 420, payload: root.rich, ompActivity: fakeActivity,
      motion: create("Motion.qml", {}) })
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
        root.check(root.find(root.overview, "costModel-4") !== null && !root.find(root.overview, "costModelDisclosure").checked,
          "the breakdown starts with its top five models")
        root.check(!root.find(root.overview, "costTokenDetails").visible, "cost overview starts without token details")
        root.check(root.find(root.overview, "costModel-5") === null, "models past the top five are not instantiated")
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
        var keyInput = root.find(root.form, "openrouterKeyRowFieldInput")
        root.check(filterInput.echoMode === undefined && !filterInput.readOnly, "a plain field edits in a TextEdit")
        root.check(keyInput !== null && keyInput.readOnly, "a secret field keeps a read-only input")
        root.check(root.editableTextInputs(root.form) === 0, "no settings field is an editable TextInput")
        root.type("providerFilterField", ["d", "e", "e", "p", "x", Qt.Key_Backspace])
        root.type("openrouterKeyRowField", ["k", "e", "y", "x", Qt.Key_Backspace])
        root.check(root.find(root.form, "openrouterKeyRowField").text === "key", "a secret field takes typing and Backspace")
        root.check(root.form.moreKeys.map(function (entry) { return entry.id }).join(",") === "deepseek,deepinfra"
          && root.form.moreSignIns.length === 0, "the filter narrows More providers by name")
        root.form.usagePayload = null
        root.form.page = "costs"
        root.check(root.find(root.form, "providerFilterFieldInput") === null
          && root.find(root.form, "cliproxyUrlFieldInput") === null
          && root.find(root.form, "refreshMinutesFieldInput") === null, "fields on hidden pages keep no live input")
        root.savesBeforeBlankRow = root.saves
        root.check(root.find(root.overview, "costModel-9") !== null, "expanded breakdown includes models beyond the former top eight")
        root.check(root.find(root.overview, "costBreakdown").count === 10 && root.find(root.overview, "costModelDisclosure").checked,
          "expanded breakdown lists every model")
        root.overview.modelsExpanded = false
        root.check(root.find(root.overview, "costModel-9") === null, "collapsing releases model rows")
        root.check(root.find(root.form, "costSource-remote").text.indexOf("Unavailable") >= 0, "source diagnostics are available in Costs settings")
        var before = root.saves
        root.check(root.form.priceError !== "" && root.saves === root.savesBeforeBlankRow, "a blank added row is explained and not saved")
        // Editing is saved as it happens, so typing must neither steal focus to
        // the field the row still owes nor rebuild the rows under the cursor.
        var blankRow = root.find(root.form, "costModel-1")
        root.edit("costModel-1", "m")
        root.edit("costModel-1", "mi")
        root.edit("costModel-1", "mini")
        root.check(root.find(root.form, "costModel-1") === blankRow, "an edit keeps the same field object")
        root.check(root.find(root.form, "costModel-1").text === "mini", "typing a model ID keeps every keystroke")
        // The picker fills the field with an exact id from the costs view, the ones
        // without a price first; the field stays the source of truth for anything else.
        var choices = root.form.priceEditor.modelChoices
        root.check(JSON.stringify(choices.map(function(choice) { return choice.label })) === '["free-model · no price","vendor/Example[2m]"]',
          "the picker offers each model once, unpriced first, and not the view's own groups: " + JSON.stringify(choices))
        var pick = root.find(root.form, "costModelPick-1")
        root.check(pick.showingPlaceholder && pick.contentItem.text === "Pick a model from your costs…",
          "a row whose model is not listed says what the picker is for, not the first model: " + pick.contentItem.text)
        pick.changed("vendor/Example[2m]")
        root.check(root.find(root.form, "costModel-1").text === "vendor/Example[2m]", "picking a model fills its exact id")
        root.check(!pick.showingPlaceholder && pick.contentItem.text === "vendor/Example[2m]", "the picker then names that model")
        root.edit("costModel-1", "free-model")
        root.edit("costRate-1-inputCostPerMillionTokens", "0")
        var inputRate = root.find(root.form, "costRate-1-inputCostPerMillionTokens")
        root.edit("costRate-1-outputCostPerMillionTokens", "0")
        root.check(root.find(root.form, "costRate-1-inputCostPerMillionTokens") === inputRate,
          "saving a complete row does not rebuild the editor")
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
        // Paste goes through the bounded reader (tests/fake-bin/wl-paste offers a short text, then
        // one past the 64 KiB limit).
        root.form.page = "advanced"
        var refresh = root.find(root.form, "refreshMinutesField")
        refresh.text = ""
        refresh.paste(root.find(refresh, "refreshMinutesFieldInput"))
        root.phase++
      } else if (root.phase === 9 && !root.find(root.form, "refreshMinutesField").pasting) {
        var pasted = root.find(root.form, "refreshMinutesField")
        root.check(pasted.text === "seek", "an explicit paste inserts the clipboard text, got " + JSON.stringify(pasted.text))
        pasted.paste(root.find(pasted, "refreshMinutesFieldInput"))
        root.phase++
      } else if (root.phase === 10 && !root.find(root.form, "refreshMinutesField").pasting) {
        root.check(root.find(root.form, "refreshMinutesField").text === "seek", "a paste over 64 KiB is refused")
        // A second OpenRouter key: named, staged privately, and saved as an extra key the backend reads.
        root.host({ enabledProviders: ["openrouter"], openrouterKeyFile: "/private/primary.key", extraKeys: "{}" })
        root.form.page = "providers"
        root.find(root.form, "openrouterAddExtraKey").clicked()
        root.check(root.find(root.form, "openrouterExtraNameInput") !== null, "Add another key opens a named editor")
        root.find(root.form, "openrouterExtraName").text = "Work"
        root.find(root.form, "openrouterExtraSecret").text = "synthetic-second-key"
        root.saved = null
        root.find(root.form, "openrouterExtraSave").clicked()
        root.phase++
      } else if (root.phase === 11 && root.saved && root.saved.extraKeys && root.saved.extraKeys !== "{}" && !root.form.saving) {
        var extra = JSON.parse(root.saved.extraKeys).openrouter
        root.check(extra.keys.length === 1 && extra.keys[0].label === "Work" && /^k-[0-9a-f]{8}$/.test(extra.keys[0].id),
          "the named key is saved with its own id")
        root.check(extra.keys[0].file.indexOf("/management-keys/key-") >= 0 && JSON.stringify(root.saved).indexOf("synthetic-second-key") < 0,
          "the key itself is only in a private file")
        root.check(root.find(root.form, "openrouterPrimaryKeyName").visible, "with two keys, the first can be named too")
        // Back up and restore through scripts/backup.py and gpg: the widget's request line, the
        // helper's one-line reply, and the settings it hands back pointing at fresh key files.
        root.backupFile = Quickshell.env("XDG_CACHE_HOME") + "/contract.qtbackup"
        root.form.runBackup({ action: "export", path: root.backupFile, passphrase: "contract passphrase",
          settings: Object.assign({}, root.saved, { openrouterKeyFile: "" }) }, function(response) { root.backupReply = response })
        root.phase++
      } else if (root.phase === 12 && root.backupReply) {
        root.check(root.backupReply.ok && root.backupReply.secrets === 2, "the backup holds the extra key and the T3 token saved earlier: " + JSON.stringify(root.backupReply))
        root.backupReply = null
        root.form.runBackup({ action: "restore", path: root.backupFile, passphrase: "contract passphrase" },
          function(response) { root.backupReply = response })
        root.phase++
      } else if (root.phase === 13 && root.backupReply && root.costsDone) {
        root.check(root.backupReply.ok, "the backup restores: " + JSON.stringify(root.backupReply))
        var restored = JSON.parse(root.backupReply.settings.extraKeys).openrouter.keys[0]
        var original = JSON.parse(root.saved.extraKeys).openrouter.keys[0]
        root.check(restored.label === "Work" && restored.file !== original.file && restored.file.indexOf("/management-keys/key-") >= 0,
          "a restored key gets a new private file and keeps its name")
        console.log("Cost QML contract: passed")
        Qt.quit()
      }
    }
  }

  FileView {
    id: dimensionsFile
    path: Quickshell.env("QUOTATANK_COST_DIMENSIONS_FIXTURE")
    blockLoading: true
  }

  // Stands in for Panel's OmpActivity (omp-live.py): live omp requests as they happen, in its request log.
  QtObject {
    id: fakeActivity
    signal request(var event)
    signal remoteActivity()
    property string state: "live"
    property var recentByAccount: ({})
    property var requestLog: []
    property int requestRevision: 0
    function add(event) {
      requestLog.push([event.at, event.provider, event.costUsd, event.tokens, "local"])
      requestRevision++
      request(event)
    }
  }

  // The same scan over 30 days: 23 earlier days, then the 7 the week payload has.
  function month() {
    var payload = JSON.parse(JSON.stringify(root.rich))
    payload.period = { days: 30, resolution: "day", since: "2029-12-17", until: "2030-01-15", label: "Past 30 days" }
    var earlier = []
    for (var i = 0; i < 23; i++) {
      var claude = 0.3 + (i % 5) * 0.2
      var codex = 0.1 + (i % 3) * 0.15
      earlier.push({ start: new Date(Date.UTC(2029, 11, 17 + i)).toISOString().substring(0, 10),
        costUsd: claude + codex, totalTokens: 400000, records: 4, pricedRecords: 4, unpricedRecords: 0, sessions: 1,
        providers: [{ id: "claude", costUsd: claude, totalTokens: 300000 }, { id: "codex", costUsd: codex, totalTokens: 100000 }] })
    }
    payload.periods = earlier.concat(payload.periods)
    return payload
  }

  // 1.9 Costs tab, data -> what is drawn: delta chip, heatmap, breakdown dimensions, isolation that
  // rescales, bars that keep their delegates across period changes, and the live omp line.
  Timer {
    interval: 50
    running: !root.costsDone
    repeat: true
    onTriggered: {
      var chart = root.find(root.costs, "costChart")
      if (root.costsPhase === 0) {
        root.check(chart.chartMaximum > 0 && root.find(root.costs, "costSummaryValue").text === "$12.34", "the week renders its total")
        var delta = root.find(root.costs, "costDelta")
        root.check(delta.visible && delta.text === "▲ 18% vs previous 7 days", "the total shows its change on the previous week: " + delta.text)
        root.check(root.costs.sourceSummary === "Local transcripts + omp on devbox · live", "the footer names the sources: " + root.costs.sourceSummary)
        root.check(root.find(root.costs, "costCacheLine").visible && root.costs.cache.text === "81% read from cache · saved $21.50",
          "the cache line reads the totals")
        var noPrevious = JSON.parse(JSON.stringify(root.rich))
        noPrevious.previous = null
        root.costs.payload = noPrevious
        root.check(!delta.visible, "no previous window, no delta chip")
        root.costs.payload = root.rich
        root.costs.metric = "tokens"
        root.check(delta.visible && delta.text === "▲ 10% vs previous 7 days", "the delta follows the metric: " + delta.text)
        root.costs.metric = "cost"

        var when = root.find(root.costs, "costWhen")
        root.check(when.visible && when.cellCount === 168 && root.find(root.costs, "costHeatCell-167") !== null, "seven days of 24 hours")
        when.hoveredCell = 6 * 24 + 15
        var readout = root.find(root.costs, "costHeatReadout")
        root.check(readout.text === "Tue 15:00 · $4.20 · 63 requests", "hovering a cell reads it out: " + readout.text)
        when.hoveredCell = -1
        root.check(readout.text.indexOf("Busiest: Tue 15:00") === 0, "without hover the line names the busiest hour: " + readout.text)

        var dimensions = root.find(root.costs, "costBreakdownMode")
        root.check(dimensions.visible && dimensions.options.length === 3, "Model, Project and Agent are offered")
        root.check(root.find(root.costs, "costModel-0").name === "claude-opus-4-6", "models rank by cost")
        dimensions.changed("project")
        root.check(root.find(root.costs, "costModel-0") === null && root.find(root.costs, "costProject-0").name === "web-shop"
          && root.find(root.costs, "costProject-3").name === "Other", "Project lists folders, the folded rest last")
        dimensions.changed("agent")
        root.check(root.find(root.costs, "costAgent-0").name === "Main sessions" && root.find(root.costs, "costAgent-1").name === "Subagents"
          && root.find(root.costs, "costAgent-1").context === "tasks and workpools", "Agent splits main sessions from subagents")
        dimensions.changed("model")
        root.check(root.find(root.costs, "costModel-1").name === "gpt-5.6-sol", "Model comes back")

        root.find(root.costs, "costProviders").isolateRequested("codex")
        root.costsPhase++
        root.costsWait = 0
      } else if (root.costsPhase === 1 && ++root.costsWait > 14) {
        root.check(Math.abs(chart.maxSegmentHeight("codex") - chart.plotHeight) < 0.5 && chart.maxSegmentHeight("claude") === 0,
          "isolating a provider rescales the chart to it: " + chart.maxSegmentHeight("codex") + " of " + chart.plotHeight)
        root.check(root.find(root.costs, "costProviderHint").text === "OpenAI Codex only · click again for all", "the header says how to go back")
        root.find(root.costs, "costProviders").isolateRequested("codex")
        root.costsPhase++
        root.costsWait = 0
      } else if (root.costsPhase === 2 && ++root.costsWait > 14) {
        root.check(chart.maxSegmentHeight("claude") > 0 && chart.maxSegmentHeight("codex") < chart.plotHeight - 0.5,
          "clicking again shows every provider")
        root.keptBars = [chart.barItem("d2030-01-09"), chart.barItem("d2030-01-15")]
        var refreshed = JSON.parse(JSON.stringify(root.rich))
        refreshed.periods[6].providers[0].costUsd = 1.3
        root.costs.payload = refreshed
        root.check(chart.barItem("d2030-01-09") === root.keptBars[0] && !chart.morphing, "a routine refresh keeps every bar and morphs nothing")
        root.costs.payload = root.month()
        root.check(chart.barItem("d2030-01-09") === root.keptBars[0] && chart.barItem("d2030-01-15") === root.keptBars[1],
          "bars for timestamps both periods share keep their delegates")
        root.check(chart.barItem("d2029-12-17") !== null && chart.morphing, "the earlier days grow in")
        root.costsPhase++
        root.costsWait = 0
      } else if (root.costsPhase === 3 && ++root.costsWait > 14) {
        root.check(chart.barCount === 30 && root.find(root.costs, "costHistoryGap-29") !== null, "thirty days, newest on the right")
        root.costs.payload = root.rich
        root.check(chart.barItem("d2029-12-17") === null && chart.barItem("d2030-01-15") === root.keptBars[1],
          "back to the week, the earlier days leave and the shared ones stay")
        root.costsPhase++
        root.costsWait = 0
      } else if (root.costsPhase === 4 && ++root.costsWait > 14) {
        root.check(chart.barCount === 7, "bars that left are released after they shrink away")
        var scan = Date.parse(root.rich.generatedAt) / 1000
        fakeActivity.add({ type: "request", provider: "claude", model: "claude-opus-4-6", costUsd: 0.42, tokens: 1200,
          subagent: false, at: scan + 60 })
        fakeActivity.add({ type: "request", provider: "claude", costUsd: 5, tokens: 10, subagent: false, at: scan - 60 })
        root.check(root.find(root.costs, "costLiveLine").shown
          && root.find(root.costs, "costLiveText").text === "Live from omp · +$0.42 since the last scan",
          "a live omp request shows the live line: " + root.find(root.costs, "costLiveText").text)
        root.check(root.find(root.costs, "costSummaryValue").text === "$12.76", "the total includes requests after the scan, not before it")
        root.check(Math.abs(chart.buckets[6].raw.claude - 1.52) < 0.000001, "today's bar grows with the request")
        // A scan that started before the request but landed after it does not hold it: the request still counts.
        var running = JSON.parse(JSON.stringify(root.rich))
        running.generatedAt = new Date((scan + 30) * 1000).toISOString()
        root.costs.payload = running
        root.check(root.find(root.costs, "costSummaryValue").text === "$12.76", "a request that came in while a scan ran is not lost")
        var next = JSON.parse(JSON.stringify(root.rich))
        next.generatedAt = new Date((scan + 120) * 1000).toISOString()
        root.costs.payload = next
        root.check(!root.find(root.costs, "costLiveLine").shown && root.find(root.costs, "costSummaryValue").text === "$12.34",
          "the next scan takes over from the live figures")
        var remoteOnly = JSON.parse(JSON.stringify(next))
        remoteOnly.sources = remoteOnly.sources.filter(function(source) { return source.id !== "local-omp" })
        fakeActivity.add({ type: "request", provider: "claude", costUsd: 0.5, tokens: 10, subagent: false, at: scan + 180 })
        root.costs.payload = remoteOnly
        root.check(root.find(root.costs, "costSummaryValue").text === "$12.34",
          "without this computer's omp sessions in the scan, live requests add nothing")
        root.costsDone = true
      }
    }
  }
  Timer { interval: 25000; running: true; onTriggered: { root.check(false, "timed out at phase " + root.phase + "; costs phase " + root.costsPhase + "; responses=" + root.responses + "; error=" + root.backend.fetchError + "; loading=" + root.backend.loading + "; request=" + JSON.stringify(root.backend.payload.testRequest)); Qt.quit() } }
}
