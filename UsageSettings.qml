pragma ComponentBehavior: Bound

import QtQuick
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
  property string proxyImplementation: ""
  property var costSources: []
  // "" is the index; otherwise one of the page ids below.
  property string page: ""
  property string errorText: ""
  readonly property bool saving: keyWriter.running
  property alias priceEditor: prices
  readonly property string proxyName: UsageLogic.proxyName(proxyImplementation)
  readonly property bool proxyMode: value("usageSource", "direct") === "cliproxy"
  readonly property string quotaMode: String(value("quotaMode", "Used")) === "Remaining" ? "Remaining" : "Used"
  readonly property bool percentageDisplay: String(value("barDisplayMode", "Percentages")) === "Percentages"
  readonly property var enabledProviders: UsageLogic.listOrEmpty(value("enabledProviders", ["claude", "codex", "kimi", "opencode"]))
  readonly property var barProviders: UsageLogic.listOrEmpty(value("barProviders", ["claude", "codex", "kimi", "opencode"]))
  readonly property bool moneyMonitored: !proxyMode && (monitored("openrouter") || monitored("deepseek"))
  readonly property var providerOptions: proxyMode ? UsageLogic.listOrEmpty(proxyProviders) : UsageLogic.LOCAL_PROVIDERS
  readonly property var allProviderIds: {
    var ids = UsageLogic.LOCAL_PROVIDER_IDS.slice()
    for (var i = 0; i < proxyProviders.length; i++)
      if (!UsageLogic.contains(ids, proxyProviders[i].id)) ids.push(proxyProviders[i].id)
    return ids
  }
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
  readonly property string fuseboxRepositoryUrl: "https://github.com/DigitalPals/Fusebox"
  readonly property string openrouterKeysUrl: "https://openrouter.ai/settings/keys"
  readonly property string deepseekKeysUrl: "https://platform.deepseek.com/api_keys"

  // Changes are batched per control: { key: value }. The host persists them and reports back
  // through finishSave(), which also commits or discards a staged secret.
  signal changeRequested(var values)
  signal closeRequested()
  signal revealRequested(var item)

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
    var selected = UsageLogic.listOrEmpty(value(key, []))
    var result = []
    for (var i = 0; i < allProviderIds.length; i++) {
      var candidate = allProviderIds[i]
      if (UsageLogic.contains(selected, candidate) !== (candidate === id)) result.push(candidate)
    }
    set(key, result)
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
    servers.load(String(value("costT3Servers", "[]")))
    lastPricesJson = String(value("costPriceOverrides", "{}"))
    prices.begin(lastPricesJson)
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

    Text {
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

  Text {
    visible: root.errorText !== ""
    width: parent.width
    text: root.errorText
    textFormat: Text.PlainText
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
    Hint { text: root.proxyMode ? "Limits come from every account on your " + root.proxyName + " server." : "Limits come from the CLIs you are signed in to on this computer, plus any API keys saved below." }

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
          return /^https?:\/\/[^\s/?#@]+(?::[0-9]+)?(?:\/[^\s?#]*)?$/.test(text)
            ? "" : "Enter an HTTP or HTTPS server URL without credentials, query, or fragment."
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
      LinkButton { objectName: "fuseboxRepositoryLink"; text: "Fusebox on GitHub ↗"; url: root.fuseboxRepositoryUrl }

      SwitchRow {
        objectName: "liveAccountActivityToggle"
        label: "Live account activity"
        checked: root.value("liveAccountActivity", true) !== false
        onToggled: root.set("liveAccountActivity", !checked)
      }
      Hint { text: "Fusebox streams which account serves each request. CLIProxyAPI needs CPA Usage Keeper for that." }
      TextRow {
        id: keeperUrlField
        objectName: "costKeeperUrl"
        label: "CPA Usage Keeper URL"
        placeholder: "https://proxy.example.com/keeper"
        source: String(root.value("costKeeperUrl", ""))
        validate: function(text) {
          return text === "" || /^https?:\/\/[^\s/?#@]+(?::[0-9]+)?(?:\/[^\s?#]*)?$/.test(text)
            ? "" : "Enter the Keeper HTTP or HTTPS URL, or leave it empty."
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

    Row {
      width: parent.width
      Label { width: parent.width - monitorHeading.width - barHeading.width; text: "Provider"; font.bold: true }
      Label { id: monitorHeading; visible: !root.proxyMode; width: visible ? Style.space(82) : 0; text: "Monitor"; horizontalAlignment: Text.AlignHCenter }
      Label { id: barHeading; visible: root.percentageDisplay; width: visible ? Style.space(82) : 0; text: "Menu bar"; horizontalAlignment: Text.AlignHCenter }
    }

    Repeater {
      model: root.providerOptions
      delegate: Column {
        id: providerRow
        required property var modelData
        readonly property string providerId: String(modelData.id)
        readonly property bool money: modelData.money === true
        readonly property bool on: root.proxyMode || UsageLogic.contains(root.enabledProviders, providerId)
        width: parent.width
        spacing: Style.spacing.md

        Row {
          width: parent.width
          Label {
            width: parent.width - monitorSwitch.width - barSwitch.width
            anchors.verticalCenter: parent.verticalCenter
            text: providerRow.modelData.name
          }
          Toggle {
            id: monitorSwitch
            visible: !root.proxyMode
            width: visible ? Style.space(82) : 0
            objectName: "monitor-" + providerRow.providerId
            Accessible.name: "Monitor " + providerRow.modelData.name
            checked: providerRow.on
            onToggled: root.toggleProvider("enabledProviders", providerRow.providerId)
          }
          Toggle {
            id: barSwitch
            visible: root.percentageDisplay
            width: visible ? Style.space(82) : 0
            objectName: "bar-" + providerRow.providerId
            Accessible.name: "Show " + providerRow.modelData.name + " in the menu bar"
            enabled: providerRow.on
            checked: providerRow.on && UsageLogic.contains(root.barProviders, providerRow.providerId)
            opacity: enabled ? 1 : 0.4
            onToggled: root.toggleProvider("barProviders", providerRow.providerId)
          }
        }

        // API-key providers: the key editor sits right under the switch that needs it.
        Column {
          visible: providerRow.money && providerRow.on && !root.proxyMode
          width: parent.width
          leftPadding: Style.spacing.xl
          spacing: Style.spacing.md

          KeyRow {
            width: parent.width - parent.leftPadding
            objectName: providerRow.providerId + "KeyRow"
            label: "API key"
            settingKey: providerRow.providerId + "KeyFile"
            hint: providerRow.providerId === "openrouter"
              ? "Any OpenRouter key shows the balance, the key's spending limit, and spend. OPENROUTER_API_KEY in the environment takes precedence."
              : "Shows the DeepSeek platform balance. DEEPSEEK_API_KEY in the environment takes precedence."
          }
          LinkButton {
            objectName: providerRow.providerId + "KeysLink"
            text: "Create a key on " + providerRow.modelData.name + " ↗"
            url: providerRow.providerId === "openrouter" ? root.openrouterKeysUrl : root.deepseekKeysUrl
          }
        }
      }
    }
    Hint { text: root.proxyMode ? "Every provider on the server is monitored. Choose which ones get a menu bar chip." : "Monitor reads a provider and shows it in Limits. Menu bar adds its chip to the bar." }
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
      Hint { text: "Each chip line is tagged with the period of the limit it shows: 5h, 7d, 30d." }

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

      SwitchRow {
        objectName: "hideExhaustedProvidersToggle"
        label: "Hide providers that are used up"
        checked: root.value("hideExhaustedProviders", false) === true
        onToggled: root.set("hideExhaustedProviders", !checked)
      }
      Hint { text: "Removes a chip while one of its weekly or monthly limits is used up. It returns when that limit resets; Limits still shows the provider." }

      SettingsSection {
        id: barLimitsSection
        objectName: "barLimitsSection"
        width: parent.width
        title: "Per provider"
        summary: Object.keys(UsageLogic.parseBarLimits(root.value("barProviderLimits", "{}"))).length === 0
          ? "Same for all" : Object.keys(UsageLogic.parseBarLimits(root.value("barProviderLimits", "{}"))).length + " customized"
        foreground: root.foreground
        fontFamily: root.fontFamily
        onRevealRequested: function(item) { root.revealRequested(item) }
        Hint { text: "Pick different limits for one provider. Default follows the choices above." }
        Repeater {
          model: root.providerOptions
          delegate: Column {
            id: limitRow
            required property var modelData
            readonly property string providerId: String(modelData.id)
            readonly property var entry: UsageLogic.parseBarLimits(root.value("barProviderLimits", "{}"))[providerId] || ({})
            visible: !(modelData.money === true)
            width: parent.width
            spacing: Style.spacing.sm
            Label { text: limitRow.modelData.name }
            Row {
              width: parent.width
              spacing: Style.spacing.lg
              Column {
                width: (parent.width - parent.spacing) / 2
                spacing: Style.spacing.sm
                Label { text: "Limit shown" }
                UsageSelect {
                  objectName: "barLimitTop-" + limitRow.providerId
                  width: parent.width
                  label: limitRow.modelData.name + " limit shown"
                  options: [
                    { value: "default", label: UsageLogic.inheritedBarLimitLabel("top", root.value("barWindow", "auto")) },
                    { value: "auto", label: "Most constrained" },
                    { value: "session", label: "5-hour" },
                    { value: "weekly", label: "7-day" },
                    { value: "monthly", label: "Monthly" }
                  ]
                  value: limitRow.entry.top === undefined ? "default" : String(limitRow.entry.top)
                  foreground: root.foreground
                  surface: root.surface
                  fontFamily: root.fontFamily
                  onChanged: function(next) { root.set("barProviderLimits", UsageLogic.setBarLimit(root.value("barProviderLimits", "{}"), limitRow.providerId, "top", next)) }
                  onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
                }
              }
              Column {
                width: (parent.width - parent.spacing) / 2
                spacing: Style.spacing.sm
                Label { text: "Second limit below" }
                UsageSelect {
                  objectName: "barLimitBottom-" + limitRow.providerId
                  width: parent.width
                  label: limitRow.modelData.name + " second limit below"
                  options: [
                    { value: "default", label: UsageLogic.inheritedBarLimitLabel("bottom", root.value("barWindowSecondary", "none")) },
                    { value: "none", label: "None" },
                    { value: "session", label: "5-hour" },
                    { value: "weekly", label: "7-day" },
                    { value: "monthly", label: "Monthly" }
                  ]
                  value: limitRow.entry.bottom === undefined ? "default" : String(limitRow.entry.bottom)
                  foreground: root.foreground
                  surface: root.surface
                  fontFamily: root.fontFamily
                  onChanged: function(next) { root.set("barProviderLimits", UsageLogic.setBarLimit(root.value("barProviderLimits", "{}"), limitRow.providerId, "bottom", next)) }
                  onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
                }
              }
            }
          }
        }
      }
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
    Hint { visible: root.moneyMonitored; text: "Amounts in the balance's currency: dollars for OpenRouter and DeepSeek USD accounts." }
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
    Hint { text: "Applies to cards, chips, balances, and alerts." }
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
        checked: UsageLogic.contains(root.value("costLocalProviders", ["claude", "codex"]), modelData.id)
        onToggled: {
          var current = UsageLogic.listOrEmpty(root.value("costLocalProviders", ["claude", "codex"]))
          var next = []
          var allowed = ["claude", "codex", "opencode"]
          for (var i = 0; i < allowed.length; i++)
            if (UsageLogic.contains(current, allowed[i]) !== (allowed[i] === modelData.id)) next.push(allowed[i])
          root.set("costLocalProviders", next)
        }
      }
    }
    Hint { text: "Include sessions recorded on this computer. Costs are an estimate of API value, not subscription spend." }

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
              return /^https?:\/\/[^\s/?#@]+(?:\/[^\s?#]*)?$/.test(text) && !/(?:^|\/)\.{1,2}(?:\/|$)/.test(text)
                ? "" : "Enter an HTTP or HTTPS URL without credentials, query, or fragment."
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
      missing: "No transcripts", failed: "Unavailable", unavailable: "Unavailable", duplicate: "Already included" }
    var text = source.name + " · " + (labels[source.status] || source.status)
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
  }

  // ---- building blocks
  component Label: Text {
    width: parent.width
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
  }

  component Hint: Label {
    color: Qt.darker(root.foreground, 1.5)
    font.pixelSize: Style.font.caption
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
      Text {
        width: parent.width
        text: pageRow.title
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }
      Text {
        width: parent.width
        visible: text !== ""
        text: pageRow.summary
        color: Qt.darker(root.foreground, 1.5)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }
    Text {
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

  // ---- index summaries: what each page is set to, so the index already answers most questions
  function providersSummary() {
    var names = []
    var shown = 0
    for (var i = 0; i < providerOptions.length; i++) {
      var id = providerOptions[i].id
      if (!monitored(id)) continue
      names.push(UsageLogic.providerShortName(providerOptions[i]))
      if (UsageLogic.contains(barProviders, id)) shown++
    }
    if (names.length === 0) return proxyMode ? proxyName + " · no providers yet" : "Nothing monitored"
    var list = names.length <= 3 ? names.join(", ") : names.slice(0, 2).join(", ") + " +" + (names.length - 2)
    return (proxyMode ? proxyName + " · " : "") + list + (percentageDisplay ? " · " + shown + " in menu bar" : "")
  }

  function menuBarSummary() {
    if (!percentageDisplay) return "Widget icon"
    var text = UsageLogic.windowSelectorLabel(value("barWindow", "auto"))
    var bottom = UsageLogic.normalizeSecondaryBarWindow(value("barWindowSecondary", "none"))
    if (bottom !== "none") text += " + " + UsageLogic.windowSelectorLabel(bottom)
    if (value("barShowResets", false) === true) text += " · resets"
    if (value("hideExhaustedProviders", false) === true) text += " · hides used up"
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
  }

  function costsSummary() {
    var local = UsageLogic.listOrEmpty(value("costLocalProviders", ["claude", "codex"]))
    var names = { codex: "Codex", claude: "Claude", opencode: "OpenCode" }
    var parts = []
    for (var i = 0; i < local.length; i++) if (names[local[i]]) parts.push(names[local[i]])
    var text = parts.length ? parts.join(", ") : "No local history"
    if (servers.count > 0) text += " · " + servers.count + (servers.count === 1 ? " server" : " servers")
    if (prices.priceCount > 0) text += " · " + prices.priceCount + " custom " + (prices.priceCount === 1 ? "price" : "prices")
    return text
  }
}
