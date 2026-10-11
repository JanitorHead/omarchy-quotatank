pragma ComponentBehavior: Bound

import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

Column {
  id: root

  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property color surface: Commons.Color.popups.background
  property string fontFamily: Style.font.family
  property string accountDetails: ""
  property string errorText: ""
  property string refreshMinutes: "15"
  property alias connectionExpanded: connectionSection.expanded
  property alias activityExpanded: activitySection.expanded
  property alias alertsExpanded: alertsSection.expanded
  property alias refreshExpanded: refreshSection.expanded
  readonly property bool percentageDisplay: draft.barDisplayMode === "Percentages"
  readonly property string thresholdUnit: draft.quotaMode === "Remaining" ? "% left" : "% used"
  onProxyModeChanged: if (proxyMode && !draft.cliproxyKeyFile) connectionSection.expanded = true
  property var draft: ({})
  property alias managementKey: managementCredential.text
  property alias keeperPassword: keeperCredential.text
  property alias openrouterKey: openrouterCredential.text
  readonly property bool saving: keyWriter.running
  property var pendingValues: null
  property var pendingKeys: ({})
  property bool keySaveDecided: false
  property var proxyProviders: []
  property string proxyImplementation: ""
  readonly property string proxyName: UsageLogic.proxyName(proxyImplementation)
  readonly property string fuseboxRepositoryUrl: "https://github.com/DigitalPals/Fusebox"
  readonly property string openrouterKeysUrl: "https://openrouter.ai/settings/keys"
  readonly property var providerOptions: proxyMode ? UsageLogic.listOrEmpty(proxyProviders) : [
    { id: "claude", name: "Claude Code" },
    { id: "codex", name: "OpenAI Codex" },
    { id: "kimi", name: "Kimi Code" },
    { id: "opencode", name: "OpenCode Go" },
    { id: "openrouter", name: "OpenRouter" }
  ]
  readonly property var allProviderIds: {
    var ids = ["claude", "codex", "kimi", "opencode", "openrouter"]
    for (var i = 0; i < proxyProviders.length; i++)
      if (!UsageLogic.contains(ids, proxyProviders[i].id)) ids.push(proxyProviders[i].id)
    return ids
  }
  readonly property bool proxyMode: draft.usageSource === "cliproxy"
  readonly property bool openrouterMonitored: !proxyMode && UsageLogic.contains(draft.enabledProviders, "openrouter")

  signal saveRequested(var values)
  signal cancelRequested()
  signal revealRequested(var item)

  spacing: Style.spacing.xxl
  enabled: !saving
  Keys.onEscapePressed: root.cancelRequested()

  function discardKey() {
    managementCredential.reset()
    keeperCredential.reset()
    openrouterCredential.reset()
    pendingKeys = ({})
    pendingValues = null
    if (keyWriter.running && !keySaveDecided) keyWriter.running = false
  }

  function finishSave(saved) {
    if (keyWriter.running && !keySaveDecided) {
      keySaveDecided = true
      keyWriter.write(saved ? "commit\n" : "abort\n")
    }
    pendingValues = null
    if (saved) { managementKey = ""; keeperPassword = ""; openrouterKey = "" }
  }

  function begin(settings) {
    discardKey()
    function value(key, fallback) {
      return settings[key] === undefined || settings[key] === null ? fallback : settings[key]
    }
    var mode = String(value("quotaMode", "Used")) === "Remaining" ? "Remaining" : "Used"
    draft = {
      usageSource: value("usageSource", "direct") === "cliproxy" ? "cliproxy" : "direct",
      cliproxyUrl: String(value("cliproxyUrl", "http://127.0.0.1:8317")),
      cliproxyKeyFile: String(value("cliproxyKeyFile", "")),
      costKeeperUrl: String(value("costKeeperUrl", "")),
      costKeeperPasswordFile: String(value("costKeeperPasswordFile", "")),
      openrouterKeyFile: String(value("openrouterKeyFile", "")),
      creditWarningUsd: String(value("creditWarningUsd", 5)),
      creditCriticalUsd: String(value("creditCriticalUsd", 1)),
      enabledProviders: value("enabledProviders", ["claude", "codex", "kimi", "opencode"]),
      barProviders: value("barProviders", ["claude", "codex", "kimi", "opencode"]),
      liveAccountActivity: value("liveAccountActivity", true) !== false,
      barWindow: UsageLogic.normalizeBarWindow(value("barWindow", "auto")),
      barWindowSecondary: UsageLogic.normalizeSecondaryBarWindow(value("barWindowSecondary", "none")),
      barProviderLimits: UsageLogic.serializeBarLimits(UsageLogic.parseBarLimits(value("barProviderLimits", "{}"))),
      barShowResets: value("barShowResets", false) === true,
      hideExhaustedProviders: value("hideExhaustedProviders", false) === true,
      barResetTimeFormat: UsageLogic.normalizeBarResetChoice("time", value("barResetTimeFormat", "24h")),
      barResetDateFormat: UsageLogic.normalizeBarResetChoice("date", value("barResetDateFormat", "DD/MM")),
      quotaMode: mode,
      hideAccountEmails: value("hideAccountEmails", true) !== false,
      squareUsageCards: value("squareUsageCards", true) === true,
      providerColors: value("providerColors", false) === true,
      notifyLimitThresholds: value("notifyLimitThresholds", true) !== false,
      barDisplayMode: value("barDisplayMode", "Percentages"),
      refreshIntervalSec: String(value("refreshIntervalSec", 900)),
      warningThreshold: String(UsageLogic.thresholdInMode(value("warningThreshold", 25), mode)),
      criticalThreshold: String(UsageLogic.thresholdInMode(value("criticalThreshold", 10), mode))
    }
    refreshMinutes = String(Number(draft.refreshIntervalSec) / 60)
    connectionSection.expanded = proxyMode && !draft.cliproxyKeyFile
    activitySection.expanded = false
    providerSection.expanded = true
    menuBarSection.expanded = true
    barLimitsSection.expanded = false
    displaySection.expanded = false
    alertsSection.expanded = false
    refreshSection.expanded = false
    privacySection.expanded = false
    openrouterSection.expanded = !proxyMode && UsageLogic.contains(draft.enabledProviders, "openrouter") && !draft.openrouterKeyFile
    diagnosticsSection.expanded = false
    errorText = ""
  }

  function setValue(key, value) {
    var next = Object.assign({}, draft)
    next[key] = value
    draft = next
    if (key === "refreshIntervalSec") refreshMinutes = String(value).trim() === "" ? "" : String(Number(value) / 60)
    errorText = ""
  }

  // Stored thresholds are % left. Switching the unit re-expresses the drafts as 100 minus the value.
  function setQuotaMode(mode) {
    if (mode === draft.quotaMode) return
    var next = Object.assign({}, draft)
    next.quotaMode = mode
    next.warningThreshold = flipThreshold(next.warningThreshold)
    next.criticalThreshold = flipThreshold(next.criticalThreshold)
    draft = next
    errorText = ""
  }

  function flipThreshold(text) {
    var value = Number(text)
    return String(text).trim() === "" || !isFinite(value) ? text : String(100 - value)
  }

  function barLimitValue(providerId, slot) {
    var entry = UsageLogic.parseBarLimits(draft.barProviderLimits)[providerId]
    return entry && entry[slot] !== undefined ? entry[slot] : "default"
  }

  function barLimitOverrideCount() {
    return Object.keys(UsageLogic.parseBarLimits(draft.barProviderLimits)).length
  }

  // Collapsed-section summaries: the current choice, so a closed section still says what it does.
  function providersSummary() {
    var bar = UsageLogic.listOrEmpty(draft.barProviders)
    var shown = 0
    var monitored = 0
    for (var i = 0; i < providerOptions.length; i++) {
      var id = providerOptions[i].id
      var on = proxyMode || UsageLogic.contains(draft.enabledProviders, id)
      if (on) monitored++
      if (on && UsageLogic.contains(bar, id)) shown++
    }
    if (!percentageDisplay) return monitored + " monitored"
    return proxyMode ? shown + " in menu bar" : monitored + " monitored · " + shown + " in menu bar"
  }

  function menuBarSummary() {
    if (!percentageDisplay) return "Widget icon"
    var text = UsageLogic.windowSelectorLabel(draft.barWindow)
    var bottom = UsageLogic.normalizeSecondaryBarWindow(draft.barWindowSecondary)
    if (bottom !== "none") text += " + " + UsageLogic.windowSelectorLabel(bottom)
    if (draft.barShowResets === true) text += " · resets"
    if (draft.hideExhaustedProviders === true) text += " · hides used up"
    return text
  }

  function toggleProvider(key, id) {
    var selected = UsageLogic.listOrEmpty(draft[key])
    var result = []
    for (var i = 0; i < allProviderIds.length; i++) {
      var candidate = allProviderIds[i]
      if (UsageLogic.contains(selected, candidate) !== (candidate === id)) result.push(candidate)
    }
    setValue(key, result)
  }

  function focusFirst() { sourceControl.forceActiveFocus() }

  function fail(message, section, item) {
    errorText = message
    if (section) section.expanded = true
    Qt.callLater(function() {
      if (!root.visible || root.errorText !== message) return
      if (item.focusEditor) item.focusEditor()
      else { item.forceActiveFocus(); root.revealRequested(item) }
    })
    return false
  }

  function submit() {
    if (saving) return false
    var next = Object.assign({}, draft)
    var minutes = Number(refreshMinutes)
    if (refreshMinutes.trim() === "" || !isFinite(minutes) || minutes < 1 || minutes > 60)
      return fail("Enter a refresh interval from 1 to 60 minutes.", refreshSection, refreshField)
    next.refreshIntervalSec = Math.round(minutes * 60)
    var warningBounds = UsageLogic.thresholdBounds(1, 100, next.quotaMode)
    var criticalBounds = UsageLogic.thresholdBounds(0, 100, next.quotaMode)
    var ranges = [
      ["refreshIntervalSec", "Refresh interval", 60, 3600],
      ["warningThreshold", "Warning threshold", warningBounds[0], warningBounds[1]],
      ["criticalThreshold", "Critical threshold", criticalBounds[0], criticalBounds[1]]
    ]
    for (var i = 0; i < ranges.length; i++) {
      var range = ranges[i]
      var raw = String(next[range[0]]).trim()
      var value = Number(raw)
      if (raw === "" || !isFinite(value) || Math.floor(value) !== value
          || value < range[2] || value > range[3]) {
        return fail(range[1] + " must be a whole number from " + range[2] + " to " + range[3] + ".",
          range[0] === "refreshIntervalSec" ? refreshSection : alertsSection, range[0] === "warningThreshold" ? warningField : range[0] === "criticalThreshold" ? criticalField : refreshField)
      }
      next[range[0]] = value
    }
    var warningLeft = UsageLogic.thresholdToLeft(next.warningThreshold, next.quotaMode)
    var criticalLeft = UsageLogic.thresholdToLeft(next.criticalThreshold, next.quotaMode)
    if (criticalLeft > warningLeft) {
      return fail(next.quotaMode === "Remaining"
        ? "Critical threshold must be at or below the warning threshold."
        : "Critical threshold must be at or above the warning threshold.", alertsSection, criticalField)
    }
    next.warningThreshold = warningLeft
    next.criticalThreshold = criticalLeft
    var warnUsd = Number(String(next.creditWarningUsd).trim())
    var critUsd = Number(String(next.creditCriticalUsd).trim())
    if (String(next.creditWarningUsd).trim() === "" || !isFinite(warnUsd) || warnUsd < 0 || warnUsd > 100000)
      return fail("Enter a low balance warning from $0 to $100000.", alertsSection, moneyWarningField)
    if (String(next.creditCriticalUsd).trim() === "" || !isFinite(critUsd) || critUsd < 0 || critUsd > warnUsd)
      return fail("Enter a low balance critical amount from $0 up to the warning amount.", alertsSection, moneyCriticalField)
    next.creditWarningUsd = warnUsd
    next.creditCriticalUsd = critUsd
    next.cliproxyUrl = String(next.cliproxyUrl).trim()
    next.cliproxyKeyFile = String(next.cliproxyKeyFile).trim()
    if (proxyMode && !/^https?:\/\/[^\s/?#@]+(?::[0-9]+)?(?:\/[^\s?#]*)?$/.test(next.cliproxyUrl)) {
      return fail("Enter an HTTP or HTTPS server URL without credentials, query, or fragment.", connectionSection, proxyUrlField)
    }
    var key = managementKey.trim()
    if (proxyMode && managementKey !== "" && (key === "" || key.length > 8191 || /[^\x20-\x7e]/.test(key))) {
      return fail("Enter a nonempty management API key using ASCII characters.", connectionSection, managementCredential)
    }
    next.costKeeperUrl = String(next.costKeeperUrl).trim()
    var password = keeperPassword.trim()
    if ((proxyMode && (next.costKeeperUrl !== "" || password !== ""))
        && !/^https?:\/\/[^\s/?#@]+(?::[0-9]+)?(?:\/[^\s?#]*)?$/.test(next.costKeeperUrl)) {
      return fail("Enter the CPA Usage Keeper HTTP or HTTPS URL.", activitySection, keeperUrlField)
    }
    if (keeperPassword !== "" && (password === "" || password.length > 8191 || /[^\x20-\x7e]/.test(password))) {
      return fail("Enter a nonempty Keeper password using ASCII characters.", activitySection, keeperCredential)
    }
    var openrouterSecret = openrouterKey.trim()
    if (openrouterKey !== "" && (openrouterSecret === "" || openrouterSecret.length > 8191 || /[^\x20-\x7e]/.test(openrouterSecret))) {
      return fail("Enter a nonempty OpenRouter key using ASCII characters.", openrouterSection, openrouterCredential)
    }
    var keys = ({})
    if (proxyMode && key !== "") keys.cliproxyKeyFile = key
    if (proxyMode && password !== "") keys.costKeeperPasswordFile = password
    if (openrouterSecret !== "") keys.openrouterKeyFile = openrouterSecret
    errorText = ""
    if (Object.keys(keys).length > 0) {
      pendingValues = next
      pendingKeys = keys
      keySaveDecided = false
      keyWriter.running = true
    } else saveRequested(next)
    return true
  }

  Process {
    id: keyWriter
    command: ["python3", "-u", decodeURIComponent(String(Qt.resolvedUrl("scripts/management-key.py")).replace(/^file:\/\//, ""))]
    stdinEnabled: true
    onStarted: {
      write(JSON.stringify({ keys: root.pendingKeys, previousPaths: {
        cliproxyKeyFile: root.draft.cliproxyKeyFile,
        costKeeperPasswordFile: root.draft.costKeeperPasswordFile,
        openrouterKeyFile: root.draft.openrouterKeyFile
      } }) + "\n")
      root.pendingKeys = ({})
    }
    stdout: SplitParser {
      onRead: function(data) {
        if (!root.pendingValues || root.keySaveDecided) return
        var response = null
        try { response = JSON.parse(data) } catch (error) {}
        if (!response || !response.paths) return
        var values = Object.assign({}, root.pendingValues, response.paths)
        root.saveRequested(values)
      }
    }
    stderr: SplitParser { splitMarker: "" }
    onRunningChanged: if (!running) {
      root.pendingKeys = ({})
      if (root.pendingValues && !root.keySaveDecided)
        root.errorText = "Could not save credentials. Check that your configuration directory is writable and try again."
      root.pendingValues = null
    }
  }

  Timer {
    interval: 7000
    running: keyWriter.running
    onTriggered: keyWriter.running = false
  }

  SettingsHeader {
    width: parent.width
    title: "Limits settings"
    foreground: root.foreground
    fontFamily: root.fontFamily
    onCloseRequested: root.cancelRequested()
    onRevealRequested: function(item) { root.revealRequested(item) }
  }

  Row {
    width: parent.width
    Label {
      width: parent.width - sourceControl.width
      text: "Quota source"
      anchors.verticalCenter: parent.verticalCenter
    }
    UsageSelect {
      id: sourceControl
      objectName: "usageSourceControl"
      width: Math.min(implicitWidth, parent.width * 0.6)
      label: "Quota source"
      options: [{ value: "direct", label: "Local CLIs" }, { value: "cliproxy", label: root.proxyName }]
      value: String(root.draft.usageSource || "direct")
      foreground: root.foreground
      surface: root.surface
      fontFamily: root.fontFamily
      alignPopupRight: true
      onChanged: function(value) { root.setValue("usageSource", value) }
      onMenuClosed: if (root.visible) sourceControl.forceActiveFocus()
      onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
    }
  }

  Ui.Button {
    objectName: "fuseboxRepositoryLink"
    visible: root.proxyMode
    text: "Fusebox on GitHub ↗"
    tooltipText: root.fuseboxRepositoryUrl
    foreground: root.foreground
    fontFamily: root.fontFamily
    fontSize: Style.font.caption
    horizontalPadding: Style.spacing.sm
    verticalPadding: Style.spacing.xs
    focusable: true
    Accessible.name: "Open the Fusebox repository on GitHub"
    onClicked: Qt.openUrlExternally(root.fuseboxRepositoryUrl)
    onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
  }

  Section {
    id: connectionSection
    objectName: "quotaConnectionSection"
    visible: root.proxyMode
    title: "Connection details"
    summary: root.draft.cliproxyKeyFile ? "Configured" : "Setup"
    Label { text: root.proxyName + " server URL" }
    Field {
      id: proxyUrlField
      objectName: "cliproxyUrlField"
      settingKey: "cliproxyUrl"
      placeholderText: "http://127.0.0.1:8317"
      Accessible.name: root.proxyName + " server URL"
    }
    SettingsCredential {
      id: managementCredential
      width: parent.width
      label: "Management API key"
      editorObjectName: "managementKeyField"
      saved: !!root.draft.cliproxyKeyFile
      foreground: root.foreground
      fontFamily: root.fontFamily
      onEdited: root.errorText = ""
      onRevealRequested: function(item) { root.revealRequested(item) }
    }
    Hint { text: "Save to discover the proxy’s providers and accounts." }
    Section {
      title: "Learn more"
      Hint { text: "Use the management key for Fusebox or CLIProxyAPI. The implementation is detected automatically. The key is saved privately on this device. Quota limits and estimated costs use separate data sources." }
    }
  }
  Section {
    id: activitySection
    objectName: "accountActivitySection"
    visible: root.proxyMode
    title: "Account activity"
    summary: root.draft.liveAccountActivity !== false ? "Live on Fusebox" : "Last used"
    Row {
      width: parent.width
      Label { width: parent.width - liveAccountActivitySwitch.width; text: "Live account activity"; anchors.verticalCenter: parent.verticalCenter }
      ProviderToggle {
        id: liveAccountActivitySwitch
        objectName: "liveAccountActivityToggle"
        width: Style.space(82)
        checked: root.draft.liveAccountActivity !== false
        Accessible.name: "Live account activity"
        onToggled: root.setValue("liveAccountActivity", !checked)
      }
    }
    Hint { text: "Fusebox session counts appear beside the subscription title. Sessions may remain assigned after requests finish." }
    Label { text: "CPA Usage Keeper URL" }
    Field {
      id: keeperUrlField
      objectName: "costKeeperUrlField"
      settingKey: "costKeeperUrl"
      placeholderText: "https://proxy.example.com/keeper"
      Accessible.name: "CPA Usage Keeper URL"
    }
    SettingsCredential {
      id: keeperCredential
      width: parent.width
      label: "Keeper login password"
      editorObjectName: "keeperPasswordField"
      saved: !!root.draft.costKeeperPasswordFile
      foreground: root.foreground
      fontFamily: root.fontFamily
      onEdited: root.errorText = ""
      onRevealRequested: function(item) { root.revealRequested(item) }
    }
    Hint { text: "Show the last-used account in the percentage menu bar." }
    Section {
      title: "Learn more"
      Hint { text: "CLIProxyAPI uses Keeper for account activity. Fusebox streams live activity without Keeper. One connection is shared by all panels. With live activity off, last-used accounts update independently of Costs." }
    }
  }

  Section {
    id: providerSection
    objectName: "providerSection"
    visible: !root.proxyMode || root.percentageDisplay
    title: "Providers"
    expanded: true
    summary: root.providersSummary()
    Row {
      width: parent.width
      Label { width: parent.width - monitorHeading.width - barHeading.width; text: "Provider"; font.bold: true }
      Label { id: monitorHeading; visible: !root.proxyMode; width: visible ? Style.space(82) : 0; text: "Monitor"; horizontalAlignment: Text.AlignHCenter }
      Label { id: barHeading; visible: root.percentageDisplay; width: visible ? (root.proxyMode ? Style.space(82) : Style.space(100)) : 0; text: "Menu bar"; horizontalAlignment: Text.AlignHCenter }
    }
    Repeater {
      model: root.providerOptions
      delegate: Row {
        id: providerRow
        required property var modelData
        width: providerSection.width
        Label {
          width: parent.width - monitorSwitch.width - barSwitch.width
          anchors.verticalCenter: parent.verticalCenter
          text: providerRow.modelData.name
        }
        ProviderToggle {
          id: monitorSwitch
          visible: !root.proxyMode
          width: visible ? Style.space(82) : 0
          objectName: "monitor-" + providerRow.modelData.id
          Accessible.name: "Monitor " + providerRow.modelData.name
          enabled: !root.proxyMode
          checked: root.proxyMode || UsageLogic.contains(root.draft.enabledProviders, providerRow.modelData.id)
          onToggled: root.toggleProvider("enabledProviders", providerRow.modelData.id)
        }
        ProviderToggle {
          id: barSwitch
          visible: root.percentageDisplay
          width: visible ? (root.proxyMode ? Style.space(82) : Style.space(100)) : 0
          objectName: "bar-" + providerRow.modelData.id
          Accessible.name: "Show " + providerRow.modelData.id + " in menu bar"
          enabled: monitorSwitch.checked
          checked: monitorSwitch.checked && UsageLogic.contains(root.draft.barProviders, providerRow.modelData.id)
          opacity: enabled ? 1 : 0.4
          onToggled: root.toggleProvider("barProviders", providerRow.modelData.id)
        }
      }
    }
    Hint { text: root.proxyMode ? "Every provider on the server is monitored. Choose which ones get a menu bar chip." : "Monitor fetches a provider and shows it in Limits. Menu bar adds its chip to the bar." }
  }

  Section {
    id: openrouterSection
    objectName: "openrouterSection"
    visible: root.openrouterMonitored
    title: "OpenRouter"
    summary: root.draft.openrouterKeyFile ? "Key saved" : "Add a key"
    SettingsCredential {
      id: openrouterCredential
      width: parent.width
      label: "OpenRouter key"
      editorObjectName: "openrouterKeyField"
      saved: !!root.draft.openrouterKeyFile
      foreground: root.foreground
      fontFamily: root.fontFamily
      onEdited: root.errorText = ""
      onRevealRequested: function(item) { root.revealRequested(item) }
    }
    Hint { text: "Any OpenRouter API key shows the account balance, the key's spending limit, and spend. The key is saved privately on this device; OPENROUTER_API_KEY in the environment takes precedence." }
    Ui.Button {
      objectName: "openrouterKeysLink"
      text: "Create a key on OpenRouter ↗"
      tooltipText: root.openrouterKeysUrl
      foreground: root.foreground
      fontFamily: root.fontFamily
      fontSize: Style.font.caption
      horizontalPadding: Style.spacing.sm
      verticalPadding: Style.spacing.xs
      focusable: true
      Accessible.name: "Open OpenRouter key settings"
      onClicked: Qt.openUrlExternally(root.openrouterKeysUrl)
      onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
    }
  }

  Section {
    id: menuBarSection
    objectName: "menuBarSection"
    title: "Menu bar"
    expanded: true
    summary: root.menuBarSummary()
    Row {
      width: parent.width
      Label { width: parent.width - barDisplay.width; text: "Menu bar shows"; anchors.verticalCenter: parent.verticalCenter }
      UsageSelect {
        id: barDisplay
        objectName: "barDisplayControl"
        width: Math.min(implicitWidth, parent.width * 0.7)
        label: "Menu bar shows"
        options: [{ value: "Icon", label: "Widget icon" }, { value: "Percentages", label: "Provider percentages" }]
        value: String(root.draft.barDisplayMode || "Percentages")
        foreground: root.foreground
        surface: root.surface
        fontFamily: root.fontFamily
        alignPopupRight: true
        onChanged: function(value) { root.setValue("barDisplayMode", value) }
        onMenuClosed: if (root.visible) barDisplay.forceActiveFocus()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
    }
    Hint { text: "Vertical bars, and providers without data, show the widget icon instead." }
    Row {
      width: parent.width
      visible: root.percentageDisplay
      height: visible ? implicitHeight : 0
      Label { width: parent.width - barWindowSelect.width; text: "Limit shown"; anchors.verticalCenter: parent.verticalCenter }
      UsageSelect {
        id: barWindowSelect
        objectName: "barWindowControl"
        width: Math.min(implicitWidth, parent.width * 0.7)
        label: "Limit shown"
        options: [
          { value: "auto", label: "Most constrained" },
          { value: "session", label: "5-hour" },
          { value: "weekly", label: "7-day" },
          { value: "monthly", label: "Monthly" }
        ]
        value: UsageLogic.normalizeBarWindow(root.draft.barWindow)
        foreground: root.foreground
        surface: root.surface
        fontFamily: root.fontFamily
        alignPopupRight: true
        onChanged: function(value) { root.setValue("barWindow", value) }
        onMenuClosed: if (root.visible) barWindowSelect.forceActiveFocus()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
    }
    Row {
      width: parent.width
      visible: root.percentageDisplay
      height: visible ? implicitHeight : 0
      Label { width: parent.width - barWindowSecondarySelect.width; text: "Second limit below"; anchors.verticalCenter: parent.verticalCenter }
      UsageSelect {
        id: barWindowSecondarySelect
        objectName: "barWindowSecondaryControl"
        width: Math.min(implicitWidth, parent.width * 0.7)
        label: "Second limit below"
        options: [
          { value: "none", label: "None" },
          { value: "session", label: "5-hour" },
          { value: "weekly", label: "7-day" },
          { value: "monthly", label: "Monthly" }
        ]
        value: UsageLogic.normalizeSecondaryBarWindow(root.draft.barWindowSecondary)
        foreground: root.foreground
        surface: root.surface
        fontFamily: root.fontFamily
        alignPopupRight: true
        onChanged: function(value) { root.setValue("barWindowSecondary", value) }
        onMenuClosed: if (root.visible) barWindowSecondarySelect.forceActiveFocus()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
    }
    Row {
      width: parent.width
      visible: root.percentageDisplay
      height: visible ? implicitHeight : 0
      Label { width: parent.width - barResetsSwitch.width; text: "Show when limits reset"; anchors.verticalCenter: parent.verticalCenter }
      ProviderToggle {
        id: barResetsSwitch
        objectName: "barShowResetsToggle"
        width: Style.space(82)
        checked: root.draft.barShowResets === true
        Accessible.name: "Show when limits reset"
        onToggled: root.setValue("barShowResets", !checked)
      }
    }
    Hint {
      visible: root.percentageDisplay
      text: "A time for limits that reset within a day, a date for weekly and monthly ones."
    }
    Row {
      width: parent.width
      visible: root.percentageDisplay && root.draft.barShowResets === true
      height: visible ? implicitHeight : 0
      Label { width: parent.width - barResetTimeSelect.width; text: "Time format"; anchors.verticalCenter: parent.verticalCenter }
      UsageSelect {
        id: barResetTimeSelect
        objectName: "barResetTimeControl"
        width: Math.min(implicitWidth, parent.width * 0.7)
        label: "Reset time format"
        options: [
          { value: "24h", label: "24-hour (14:30)" },
          { value: "12h", label: "12-hour (2:30 PM)" }
        ]
        value: UsageLogic.normalizeBarResetChoice("time", root.draft.barResetTimeFormat)
        foreground: root.foreground
        surface: root.surface
        fontFamily: root.fontFamily
        alignPopupRight: true
        onChanged: function(value) { root.setValue("barResetTimeFormat", value) }
        onMenuClosed: if (root.visible) barResetTimeSelect.forceActiveFocus()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
    }
    Row {
      width: parent.width
      visible: root.percentageDisplay && root.draft.barShowResets === true
      height: visible ? implicitHeight : 0
      Label { width: parent.width - barResetDateSelect.width; text: "Date format"; anchors.verticalCenter: parent.verticalCenter }
      UsageSelect {
        id: barResetDateSelect
        objectName: "barResetDateControl"
        width: Math.min(implicitWidth, parent.width * 0.7)
        label: "Reset date format"
        options: [
          { value: "DD/MM", label: "DD/MM (22/04)" },
          { value: "MM/DD", label: "MM/DD (04/22)" },
          { value: "D MMM", label: "D MMM (22 Apr)" }
        ]
        value: UsageLogic.normalizeBarResetChoice("date", root.draft.barResetDateFormat)
        foreground: root.foreground
        surface: root.surface
        fontFamily: root.fontFamily
        alignPopupRight: true
        onChanged: function(value) { root.setValue("barResetDateFormat", value) }
        onMenuClosed: if (root.visible) barResetDateSelect.forceActiveFocus()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
    }

    Row {
      width: parent.width
      visible: root.percentageDisplay
      height: visible ? implicitHeight : 0
      Label { width: parent.width - hideUsedUpSwitch.width; text: "Hide providers that are used up"; anchors.verticalCenter: parent.verticalCenter }
      ProviderToggle {
        id: hideUsedUpSwitch
        objectName: "hideExhaustedProvidersToggle"
        width: Style.space(82)
        checked: root.draft.hideExhaustedProviders === true
        Accessible.name: "Hide providers whose weekly or monthly limit is used up"
        onToggled: root.setValue("hideExhaustedProviders", !checked)
      }
    }
    Hint {
      visible: root.percentageDisplay
      text: "Removes a chip while one of its weekly or monthly limits is used up. It returns when that limit resets; Limits still shows the provider."
    }

    Section {
      id: barLimitsSection
      objectName: "barLimitsSection"
      title: "Per provider"
      visible: root.percentageDisplay
      summary: root.barLimitOverrideCount() === 0 ? "Same for all" : root.barLimitOverrideCount() + " customized"
      Hint { text: "Pick different limits for one provider. Default follows the choices above." }
      Repeater {
        model: root.providerOptions
        delegate: Column {
          id: limitRow
          required property var modelData
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
                objectName: "barLimitTop-" + limitRow.modelData.id
                width: parent.width
                label: limitRow.modelData.name + " limit shown"
                options: [
                  { value: "default", label: UsageLogic.inheritedBarLimitLabel("top", root.draft.barWindow) },
                  { value: "auto", label: "Most constrained" },
                  { value: "session", label: "5-hour" },
                  { value: "weekly", label: "7-day" },
                  { value: "monthly", label: "Monthly" }
                ]
                value: root.barLimitValue(limitRow.modelData.id, "top")
                foreground: root.foreground
                surface: root.surface
                fontFamily: root.fontFamily
                onChanged: function(value) { root.setValue("barProviderLimits", UsageLogic.setBarLimit(root.draft.barProviderLimits, limitRow.modelData.id, "top", value)) }
                onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
              }
            }
            Column {
              width: (parent.width - parent.spacing) / 2
              spacing: Style.spacing.sm
              Label { text: "Second limit below" }
              UsageSelect {
                objectName: "barLimitBottom-" + limitRow.modelData.id
                width: parent.width
                label: limitRow.modelData.name + " second limit below"
                options: [
                  { value: "default", label: UsageLogic.inheritedBarLimitLabel("bottom", root.draft.barWindowSecondary) },
                  { value: "none", label: "None" },
                  { value: "session", label: "5-hour" },
                  { value: "weekly", label: "7-day" },
                  { value: "monthly", label: "Monthly" }
                ]
                value: root.barLimitValue(limitRow.modelData.id, "bottom")
                foreground: root.foreground
                surface: root.surface
                fontFamily: root.fontFamily
                onChanged: function(value) { root.setValue("barProviderLimits", UsageLogic.setBarLimit(root.draft.barProviderLimits, limitRow.modelData.id, "bottom", value)) }
                onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
              }
            }
          }
        }
      }
    }
  }

  Section {
    id: displaySection
    objectName: "displaySection"
    title: "Display"
    summary: (root.draft.quotaMode === "Remaining" ? "% left" : "% used") + " · " + (root.draft.providerColors === true ? "Brand colors" : "Theme colors")
    Row {
      width: parent.width
      Label { width: parent.width - quotaModeSelect.width; text: "Show limits as"; anchors.verticalCenter: parent.verticalCenter }
      UsageSelect {
        id: quotaModeSelect
        objectName: "quotaModeControl"
        width: Math.min(implicitWidth, parent.width * 0.7)
        label: "Show limits as"
        options: [
          { value: "Used", label: "Used (%)" },
          { value: "Remaining", label: "Left (%)" }
        ]
        value: String(root.draft.quotaMode || "Used") === "Remaining" ? "Remaining" : "Used"
        foreground: root.foreground
        surface: root.surface
        fontFamily: root.fontFamily
        alignPopupRight: true
        onChanged: function(value) { root.setQuotaMode(value) }
        onMenuClosed: if (root.visible) quotaModeSelect.forceActiveFocus()
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
    }
    Hint { text: "Applies to cards, chips, and alerts." }
    Row {
      width: parent.width
      Label { width: parent.width - providerColorsSwitch.width; text: "Provider colors"; anchors.verticalCenter: parent.verticalCenter }
      ProviderToggle {
        id: providerColorsSwitch
        objectName: "providerColorsToggle"
        width: Style.space(82)
        checked: root.draft.providerColors === true
        Accessible.name: "Provider colors"
        onToggled: root.setValue("providerColors", !checked)
      }
    }
    Hint { text: "Brand colors on chips and limit meters. Alerts keep the theme's alert color; the cost chart always uses brand colors." }
    Row {
      width: parent.width
      Label { width: parent.width - squareCardsSwitch.width; text: "Square usage cards"; anchors.verticalCenter: parent.verticalCenter }
      ProviderToggle {
        id: squareCardsSwitch
        objectName: "squareUsageCardsToggle"
        width: Style.space(82)
        checked: root.draft.squareUsageCards === true
        Accessible.name: "Square usage cards"
        onToggled: root.setValue("squareUsageCards", !checked)
      }
    }
    Hint { text: "Off follows the theme's corners." }
  }

  Section {
    id: alertsSection
    objectName: "alertsSection"
    title: "Alerts"
    summary: root.draft.notifyLimitThresholds === false ? "Off" : "Warning at " + root.draft.warningThreshold + root.thresholdUnit + " · Critical at " + root.draft.criticalThreshold + root.thresholdUnit
      + (root.openrouterMonitored ? " · Balance at $" + root.draft.creditWarningUsd : "")
    Row {
      width: parent.width
      Label { width: parent.width - notifySwitch.width; text: "Notify when limits run low"; anchors.verticalCenter: parent.verticalCenter }
      ProviderToggle {
        id: notifySwitch
        objectName: "notifyLimitThresholdsToggle"
        width: Style.space(82)
        checked: root.draft.notifyLimitThresholds !== false
        Accessible.name: "Notify when limits run low"
        onToggled: root.setValue("notifyLimitThresholds", !checked)
      }
    }
    Hint { text: "Desktop notification when a limit moves into the warning or critical threshold." }
    Row {
      width: parent.width
      spacing: Style.spacing.lg
      Column {
        width: (parent.width - parent.spacing) / 2
        spacing: Style.spacing.sm
        Label { text: root.draft.quotaMode === "Remaining" ? "Warn at or below (% left)" : "Warn at or above (% used)" }
        Field { id: warningField; objectName: "warningThresholdField"; settingKey: "warningThreshold"; Accessible.name: "Warning threshold " + root.thresholdUnit; inputMethodHints: Qt.ImhDigitsOnly }
      }
      Column {
        width: (parent.width - parent.spacing) / 2
        spacing: Style.spacing.sm
        Label { text: root.draft.quotaMode === "Remaining" ? "Critical at or below (% left)" : "Critical at or above (% used)" }
        Field { id: criticalField; objectName: "criticalThresholdField"; settingKey: "criticalThreshold"; Accessible.name: "Critical threshold " + root.thresholdUnit; inputMethodHints: Qt.ImhDigitsOnly }
      }
    }
    Label {
      visible: root.openrouterMonitored
      text: "Low balance (OpenRouter)"
      font.bold: true
    }
    Row {
      visible: root.openrouterMonitored
      width: parent.width
      spacing: Style.spacing.lg
      Column {
        width: (parent.width - parent.spacing) / 2
        spacing: Style.spacing.sm
        Label { text: "Warn at or below ($)" }
        Field { id: moneyWarningField; objectName: "creditWarningUsdField"; settingKey: "creditWarningUsd"; Accessible.name: "Low balance warning in dollars"; inputMethodHints: Qt.ImhFormattedNumbersOnly }
      }
      Column {
        width: (parent.width - parent.spacing) / 2
        spacing: Style.spacing.sm
        Label { text: "Critical at or below ($)" }
        Field { id: moneyCriticalField; objectName: "creditCriticalUsdField"; settingKey: "creditCriticalUsd"; Accessible.name: "Low balance critical in dollars"; inputMethodHints: Qt.ImhFormattedNumbersOnly }
      }
    }
  }

  Section {
    id: refreshSection
    objectName: "refreshSection"
    title: "Refresh"
    summary: "Every " + (root.refreshMinutes || "—") + " min"
    Label { text: "Refresh interval (minutes)" }
    SettingsField {
      id: refreshField
      objectName: "refreshMinutesField"
      width: parent.width
      text: root.refreshMinutes
      foreground: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      inputMethodHints: Qt.ImhFormattedNumbersOnly
      Accessible.name: "Refresh interval in minutes"
      onTextEdited: { root.refreshMinutes = text; root.errorText = "" }
      onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
    }
  }

  Section {
    id: privacySection
    objectName: "privacySection"
    title: "Privacy"
    summary: root.draft.hideAccountEmails !== false ? "Emails hidden" : "Emails shown"
    Row {
      width: parent.width
      Label { width: parent.width - hideEmailSwitch.width; text: "Hide account emails"; anchors.verticalCenter: parent.verticalCenter }
      ProviderToggle {
        id: hideEmailSwitch
        objectName: "hideAccountEmailsToggle"
        width: Style.space(82)
        checked: root.draft.hideAccountEmails !== false
        Accessible.name: "Hide account emails"
        onToggled: root.setValue("hideAccountEmails", !checked)
      }
    }
    Hint { text: "Shows Account 1, Account 2, … instead of account identities, on screen and in exports." }
  }

  Section {
    id: diagnosticsSection
    title: "Diagnostics"
    Hint { text: root.draft.hideAccountEmails !== false ? root.accountDetails.replace(/^Account:.*(?:\n|$)/m, "") : root.accountDetails }
  }

  component Section: SettingsSection {
    width: parent.width
    foreground: root.foreground
    fontFamily: root.fontFamily
    onRevealRequested: function(item) { root.revealRequested(item) }
  }

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

  component Field: SettingsField {
    required property string settingKey
    width: parent.width
    text: String(root.draft[settingKey] === undefined ? "" : root.draft[settingKey])
    foreground: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    selectByMouse: true
    onTextEdited: root.setValue(settingKey, text)
    onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
  }

  component ProviderToggle: Ui.ToggleSwitch {
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
}
