pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

Ui.Panel {
  id: root
  moduleName: "janitorhead.quotatank"
  ipcTarget: "janitorhead.quotatank"
  manageIpc: false

  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground
  readonly property color urgent: bar ? bar.urgent : Commons.Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color surface: Commons.Color.popups.background
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property bool proxyMode: backend.usageSource === "cliproxy"
  // The saved order drives tiles, chips, and provider cycling alike.
  readonly property string providerOrder: String(setting("providerOrder", "[]"))
  readonly property var providers: UsageLogic.orderProviders(UsageLogic.availableProviders(proxyMode
    ? backend.providers : UsageLogic.selectedProviders(backend.providers, backend.enabledProviderIds)), providerOrder)
  // Providers set up on this computer that are neither monitored nor dismissed. Limits points to
  // them in one quiet line until each is monitored or ignored under Settings → Providers.
  readonly property var foundProviders: proxyMode ? [] : UsageLogic.foundProviders(backend.detected,
    backend.enabledProviderIds, UsageLogic.listOrEmpty(setting("dismissedProviders", UsageLogic.DEFAULT_SETTINGS.dismissedProviders)))
  property string selectedProviderId: ""
  property bool expandedAccountLimits: false
  property string historyMode: "h24"
  property string viewMode: "limits"
  property string settingsReturnView: "limits"
  readonly property bool historyAvailable: viewMode === "limits" && !accountOverview && !!provider
    && !!provider.history
    && ((UsageLogic.isListLike(provider.history.h24) && provider.history.h24.length > 0)
      || (UsageLogic.isListLike(provider.history.d7) && provider.history.d7.length > 0))
  readonly property bool tokensAvailable: viewMode === "limits" && !accountOverview && !!provider
    && provider.status !== "error" && providerModels.length > 0
  readonly property bool configuring: viewMode === "settings"
  property alias settingsForm: configForm
  property alias resetAction: resetBackend
  property double nowMs: Date.now()

  readonly property var viewOptions: [
    { value: "limits", label: "Limits" },
    { value: "costs", label: "Costs" }
  ]
  readonly property bool hideAccountEmails: setting("hideAccountEmails", true) !== false
  readonly property real usageCardRadius: setting("squareUsageCards", true) === true ? 0 : Style.cornerRadius
  readonly property bool notifyLimitThresholds: setting("notifyLimitThresholds", true) !== false
  readonly property bool providerColors: setting("providerColors", false) === true

  function accountDisplayName(account, index) {
    return UsageLogic.accountName(account, setting("extraKeys", "{}"), hideAccountEmails, index)
  }

  readonly property int criticalThreshold: UsageLogic.clamp(
    setting("criticalThreshold", 10), 0, 100)
  readonly property int warningThreshold: Math.max(criticalThreshold, UsageLogic.clamp(
    setting("warningThreshold", 25), 0, 100))
  readonly property string displayMode: String(setting("barDisplayMode", "Percentages"))
  // Which side of the allowance cards and chips report. Dashboards show usage;
  // the warning thresholds always gate on what is left. One provider can override the choice.
  readonly property string quotaMode: String(setting("quotaMode", "Used")) === "Remaining"
    ? "Remaining" : "Used"
  readonly property string providerQuotaModes: String(setting("providerQuotaModes", "{}"))
  function quotaModeFor(providerId) {
    return UsageLogic.quotaModeFor(providerQuotaModes, providerId, quotaMode)
  }
  // The side the selected provider's cards show.
  readonly property string selectedQuotaMode: quotaModeFor(provider ? provider.id : "")
  // Pins which reported limit supplies the bar percentage, its severity colour
  // and its echoes. Values match the AI usage widget's setting of the same name.
  readonly property string barWindow: UsageLogic.normalizeBarWindow(setting("barWindow", "auto"))
  readonly property string barWindowSecondary: UsageLogic.normalizeSecondaryBarWindow(setting("barWindowSecondary", "none"))
  readonly property string barProviderLimits: String(setting("barProviderLimits", "{}"))
  readonly property bool barShowResets: setting("barShowResets", false) === true
  // Clock format for the pace tick's "Now" time: the same reset time setting as the bar.
  readonly property string tickTimeFormat: UsageLogic.barResetFormat("time", setting("barResetTimeFormat", "24h"), setting("barResetDateFormat", "DD/MM"))
  // Optionally drop providers whose weekly or monthly limit is used up: they cannot be used until it
  // resets. Limits still shows them, marked used up, with the reset time.
  readonly property bool hideUsedUpProviders: setting("hideExhaustedProviders", false) === true
  readonly property var barCandidates: UsageLogic.barProviders(
    UsageLogic.selectedProviders(providers, setting("barProviders", UsageLogic.DEFAULT_SETTINGS.barProviders)),
    function (provider) { return barLimitsFor(provider.id).top })
    .filter(function (provider) { return !hideUsedUpProviders || UsageLogic.usedUpLongWindow(provider) === null })
  // With many providers the bar keeps the ones closest to a limit (failures first) and folds the
  // rest into one "+N" chip, so the bar never pushes into the clock.
  readonly property var chipSelection: UsageLogic.limitChips(barCandidates,
    Number(setting("barMaxChips", UsageLogic.DEFAULT_SETTINGS.barMaxChips)), chipPressure)
  readonly property var percentageProviders: chipSelection.shown
  readonly property var overflowProviders: chipSelection.hidden
  function chipPressure(provider) {
    if (String(provider.status) === "error") return -1
    var money = moneySeverityOf(provider)
    if (money === "critical") return 0
    if (money === "warning") return root.warningThreshold
    var remaining = UsageLogic.remainingForWindow(provider, barLimitsFor(provider.id).top)
    return remaining === null ? 100 : remaining
  }
  function barLimitsFor(providerId) {
    return UsageLogic.barLimitsFor(barProviderLimits, providerId, barWindow, barWindowSecondary)
  }
  property alias accountActivity: activityBackend
  readonly property bool percentageMode: displayMode === "Percentages"
    && !(bar && bar.vertical) && percentageProviders.length > 0
  readonly property bool alarming: anyProviderAlarming()
  readonly property int providerIndex: {
    for (var i = 0; i < providers.length; i++)
      if (providers[i].id === selectedProviderId) return i
    return 0
  }
  readonly property var providerSummary: providers.length > 0 ? providers[providerIndex] : null
  readonly property var provider: providerSummary
  // Per-model token activity for the provider on screen, taken from the same
  // estimated-cost scan the Costs tab uses so both views always agree.
  readonly property var providerModels: UsageLogic.providerModels(
    costBackend.payload ? costBackend.payload.models : [], provider ? provider.id : "")
  readonly property var proxyAccounts: UsageLogic.listOrEmpty(providerSummary && providerSummary.accounts)
  // A proxy always shows its accounts; locally a provider lists them once it has more than one
  // (Omarchy subscription accounts, or extra API keys).
  readonly property bool accountOverview: proxyAccounts.length > (proxyMode ? 0 : 1)
  property alias accountCards: accountRepeater
  readonly property var providerOptions: {
    var result = []
    for (var i = 0; i < providers.length; i++) result.push(providerTile(providers[i]))
    return result
  }

  // Low-balance thresholds for providers measured in money (OpenRouter, DeepSeek), compared in the
  // balance's own currency.
  readonly property real creditCriticalUsd: Math.max(0, Number(setting("creditCriticalUsd", 1)) || 0)
  readonly property real creditWarningUsd: Math.max(creditCriticalUsd, Number(setting("creditWarningUsd", 5)) || 0)

  function moneySeverityOf(provider) {
    return UsageLogic.moneySeverity(UsageLogic.spendable(provider), creditWarningUsd, creditCriticalUsd)
  }

  // One overview tile: logo, short name, the most pressing figure on the chosen side, and a mini
  // meter. Money providers show dollars on that side too. A failed refresh shows its short reason.
  function providerTile(provider) {
    var id = String(provider.id)
    var failed = String(provider.status) === "error"
    var mode = quotaModeFor(id)
    var money = failed ? null : UsageLogic.moneyView(provider, mode)
    var remaining = failed ? null : UsageLogic.minRemaining(provider)
    var shown = remaining === null ? null : (mode === "Remaining" ? remaining : UsageLogic.usedFromRemaining(remaining))
    return {
      value: id,
      label: UsageLogic.providerShortName(provider),
      name: String(provider.name || id),
      iconUrl: barIconUrl(provider),
      mark: UsageLogic.providerMark(id),
      figure: failed ? UsageLogic.errorReasonLabel(provider.errorKind)
        : money !== null ? money.text
        : (shown === null ? "—" : UsageLogic.formatPercent(shown) + "%"),
      unit: money !== null ? money.unit : shown === null ? "" : (mode === "Remaining" ? "left" : "used"),
      fill: money !== null ? (money.share === null ? 0 : money.share / 100) : shown === null ? 0 : shown / 100,
      alert: providerNeedsAttention(provider),
      failed: failed
    }
  }

  // A provider is flagged when its refresh failed, any limit is at warning or critical, or the
  // money it can still spend is at a low-balance threshold.
  function providerNeedsAttention(provider) {
    if (!provider) return false
    if (String(provider.status) === "error") return true
    var money = moneySeverityOf(provider)
    if (money === "warning" || money === "critical") return true
    var rows = UsageLogic.listOrEmpty(provider.windows)
    for (var i = 0; i < rows.length; i++) {
      var severity = windowSeverity(rows[i])
      if (severity === "warning" || severity === "critical") return true
    }
    return false
  }

  // The one-line answer at the top of Limits: a limit already reached, the money left and how long it
  // lasts, the soonest run-out, or that every limit lasts. `urgent` colors it; empty text hides it.
  readonly property var headline: {
    var empty = { text: "", urgent: false }
    if (!provider || String(provider.status) !== "ok" || accountOverview) return empty
    var rows = UsageLogic.listOrEmpty(provider.windows)
    var soonest = null
    var reached = null
    var projected = 0
    for (var i = 0; i < rows.length; i++) {
      var pace = UsageLogic.paceForWindow(rows[i], nowMs / 1000)
      if (!pace) continue
      if (pace.exhausted) { if (!reached) reached = rows[i]; continue }
      if (!UsageLogic.paceShowsMark(pace) || pace.state !== "projecting") continue
      projected++
      if (pace.runsOut && (!soonest || pace.etaSeconds < soonest.eta)) soonest = { row: rows[i], eta: pace.etaSeconds }
    }
    if (reached) {
      var back = durationUntil(reached.resetsAt)
      return { text: String(reached.label || "A limit") + " is used up" + (back && back !== "now" ? " · back in " + back : ""), urgent: true }
    }
    var money = UsageLogic.spendable(provider)
    var moneyLine = ""
    var moneyLow = false
    if (money !== null) {
      var spend = provider.credits && provider.credits.spend ? provider.credits.spend : {}
      var runway = UsageLogic.moneyRunway(money, spend.weekly, nowMs / 1000)
      var level = moneySeverityOf(provider)
      moneyLow = level === "warning" || level === "critical"
      var view = UsageLogic.moneyView(provider, quotaModeFor(provider.id))
      moneyLine = (view.unit === "used"
        ? view.text + " of " + UsageLogic.formatMoney(view.total, view.currency) + " used"
        : view.text + " left") + (runway ? " · lasts " + runway : "")
    }
    if (moneyLow) return { text: moneyLine, urgent: true }
    if (soonest) {
      // A projection from a short recent burst can sit far ahead of actual use; only alarm when the
      // limit is already at a threshold or would run out within a day.
      var pressing = soonest.eta <= 86400 || windowSeverity(soonest.row) === "warning" || windowSeverity(soonest.row) === "critical"
      return { text: String(soonest.row.label || "A limit") + " runs out in " + UsageLogic.formatDuration(soonest.eta)
        + (pressing ? "" : " at this rate"), urgent: pressing }
    }
    if (moneyLine !== "") return { text: moneyLine, urgent: false }
    if (projected > 0) return { text: projected === rows.length ? "Every limit lasts until it resets" : "No limit is on track to run out", urgent: false }
    return empty
  }

  // Name of the limit a chip line shows: the provider's own label, else the chosen window.
  function limitName(row, selector) {
    return row && row.label ? String(row.label) : UsageLogic.windowSelectorLabel(selector)
  }

  function alpha(color, opacity) {
    return Qt.rgba(color.r, color.g, color.b, opacity)
  }

  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)) }

  function anyProviderAlarming() {
    for (var i = 0; i < providers.length; i++) {
      var provider = providers[i]
      var money = moneySeverityOf(provider)
      if (money === "warning" || money === "critical") return true
      var severity = UsageLogic.severity(
        provider, warningThreshold, criticalThreshold,
        UsageLogic.remainingForWindow(provider, barLimitsFor(provider.id).top))
      if (severity === "warning" || severity === "critical") return true
      var secondary = barLimitsFor(provider.id).bottom
      var secondRemaining = secondary !== "none" ? UsageLogic.exactRemainingForWindow(provider, secondary) : null
      var secondSeverity = secondRemaining === null ? "none"
        : UsageLogic.severity(provider, warningThreshold, criticalThreshold, secondRemaining)
      if (secondSeverity === "warning" || secondSeverity === "critical") return true
    }
    return false
  }

  function ensureSelection() {
    if (providers.length === 0) {
      selectedProviderId = ""
      return
    }
    for (var i = 0; i < providers.length; i++)
      if (providers[i].id === selectedProviderId) return
    selectedProviderId = providers[0].id
  }

  function selectProvider(index) {
    if (providers.length === 0) return
    var wrapped = ((index % providers.length) + providers.length) % providers.length
    selectedProviderId = String(providers[wrapped].id)
    if (panelFlick) panelFlick.contentY = 0
  }

  function selectProviderId(providerId) {
    for (var i = 0; i < providers.length; i++) {
      if (providers[i].id === providerId) {
        selectProvider(i)
        return
      }
    }
  }

  function nextProvider() {
    selectProvider(providerIndex + 1)
  }

  function refreshNow() {
    if (viewMode === "costs") costBackend.refresh()
    else backend.refresh()
  }

  // Sign in to or install a provider in a floating Omarchy terminal, then refresh every few seconds
  // until its sign-in shows up (or three minutes pass), so the panel updates without a manual refresh.
  property string setupWatchId: ""
  property int setupWatchTicks: 0
  function startSetup(entry, action) {
    if (!entry || !action || action.command === "") return
    Quickshell.execDetached(["omarchy-launch-floating-terminal-with-presentation", action.command])
    setupWatchId = entry.id
    setupWatchTicks = 0
    setupWatch.restart()
  }
  Timer {
    id: setupWatch
    interval: 8000
    repeat: true
    onTriggered: {
      var reading = UsageLogic.readingFor(backend.providers, root.setupWatchId)
      root.setupWatchTicks++
      if ((reading && reading.status === "ok") || root.setupWatchTicks > 22) {
        stop()
        root.setupWatchId = ""
        return
      }
      backend.refresh()
    }
  }

  function showLimits() {
    viewMode = "limits"
    // Limits also renders per-model tokens, so it needs the same scan.
    costBackend.ensureLoaded()
    open()
  }

  function showCosts() {
    viewMode = "costs"
    costBackend.ensureLoaded()
    open()
  }

  // Settings open on the index, or straight on one page (the gear in Costs opens Costs).
  function showSettings(pageId) {
    if (!configuring) settingsReturnView = viewMode
    configForm.begin(pageId || "")
    viewMode = "settings"
    open()
    Qt.callLater(function() { configForm.focusFirst() })
  }

  function showCostSettings() {
    settingsReturnView = "costs"
    showSettings("costs")
  }

  function leaveSettings() {
    configForm.discardKey()
    viewMode = settingsReturnView
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  // Persists one batch of changed values; the form stays where it is so the result can be compared.
  function saveSettings(values) {
    var entry = Object.assign({}, settings, values)
    var changed = false
    for (var key in values) {
      if (JSON.stringify(settings[key]) !== JSON.stringify(values[key])) changed = true
    }
    if (changed) {
      if (!bar || !bar.shell || typeof bar.shell.updateEntryInline !== "function"
          || !bar.shell.updateEntryInline(moduleName, entry)) {
        configForm.errorText = "Could not save settings. Make sure Quotatank is enabled in the bar, then try again."
        configForm.finishSave(false)
        return false
      }
      settings = entry
    }
    configForm.finishSave(true)
    return true
  }

  function handleBarPress(buttonCode) {
    if (buttonCode === Qt.MiddleButton) nextProvider()
    else if (buttonCode === Qt.LeftButton) toggle()
  }

  function handleProviderChipPress(providerId, buttonCode) {
    if (buttonCode === Qt.MiddleButton) {
      nextProvider()
      return
    }
    if (buttonCode !== Qt.LeftButton) return
    var sameProvider = viewMode === "limits" && selectedProviderId === providerId
    viewMode = "limits"
    selectProviderId(providerId)
    if (opened && sameProvider) close()
    else open()
  }

  function windowSeverity(window) {
    if (!window || window.remaining === null || window.remaining === undefined) return "none"
    var remaining = Number(window.remaining)
    if (!isFinite(remaining)) return "none"
    if (remaining <= criticalThreshold) return "critical"
    if (remaining <= warningThreshold) return "warning"
    return "ok"
  }

  property var limitSeverityState: ({})

  // Runs after each successful refresh: one desktop notification per window that moved to a worse severity.
  function checkLimitCrossings() {
    var readings = []
    for (var i = 0; i < root.providers.length; i++) {
      var provider = root.providers[i]
      var rows = UsageLogic.listOrEmpty(provider.windows)
      for (var j = 0; j < rows.length; j++) {
        var row = rows[j]
        readings.push({
          key: String(provider.id) + "|" + String(row.label || j),
          severity: windowSeverity(row),
          title: String(provider.name || provider.id) + " · " + String(row.label || "Usage limit"),
          remaining: UsageLogic.windowRemaining(row),
          mode: quotaModeFor(provider.id)
        })
      }
      var money = UsageLogic.spendable(provider)
      if (money !== null) {
        var level = moneySeverityOf(provider)
        readings.push({
          key: String(provider.id) + "|money",
          severity: level,
          title: String(provider.name || provider.id) + " · Balance",
          body: (level === "critical" ? "Almost out: " : "Running low: ") + UsageLogic.formatMoney(money, UsageLogic.moneyCurrency(provider)) + " left"
        })
      }
    }
    var result = UsageLogic.severityCrossings(limitSeverityState, readings)
    limitSeverityState = result.state
    if (!notifyLimitThresholds) return
    for (var k = 0; k < result.crossings.length; k++) {
      var crossing = result.crossings[k]
      var critical = crossing.severity === "critical"
      Util.execArgv(["notify-send", "--app-name=Quotatank", "--urgency=" + (critical ? "critical" : "normal"),
        crossing.title, crossing.body || UsageLogic.alertText(crossing.severity, crossing.remaining, crossing.mode)])
    }
  }

  function durationUntil(epochSeconds) {
    var seconds = Number(epochSeconds)
    if (!isFinite(seconds) || seconds <= 0) return ""
    var remaining = Math.floor(seconds - nowMs / 1000)
    if (remaining <= 0) return "now"
    var days = Math.floor(remaining / 86400)
    var hours = Math.floor((remaining % 86400) / 3600)
    var minutes = Math.floor((remaining % 3600) / 60)
    var secs = remaining % 60
    if (days > 0) return days + "d " + hours + "h"
    if (hours > 0) return hours + "h " + minutes + "m"
    if (minutes > 0) return minutes + "m " + secs + "s"
    return Math.max(1, secs) + "s"
  }

  function absoluteReset(epochSeconds) {
    var seconds = Number(epochSeconds)
    if (!isFinite(seconds) || seconds <= 0) return ""
    var date = new Date(seconds * 1000)
    return seconds * 1000 - nowMs < 86400000
      ? Qt.formatTime(date, "HH:mm")
      : Qt.formatDateTime(date, "MMM d, HH:mm")
  }

  function barResetText(row) {
    if (!row) return ""
    var seconds = Number(row.resetsAt)
    if (!isFinite(seconds) || seconds <= 0) return ""
    var kind = UsageLogic.barResetKind(row)
    var format = UsageLogic.barResetFormat(kind,
      setting("barResetTimeFormat", "24h"), setting("barResetDateFormat", "DD/MM"))
    var date = new Date(seconds * 1000)
    return kind === "time" ? Qt.formatTime(date, format) : Qt.formatDate(date, format)
  }

  function resetText(window) {
    if (!window || !window.resetsAt) return ""
    var relative = durationUntil(window.resetsAt)
    var absolute = absoluteReset(window.resetsAt)
    if (relative === "") return ""
    return "Resets in " + relative + (absolute !== "" ? " · " + absolute : "")
  }

  function heroMeta(provider) {
    return provider && provider.plan ? String(provider.plan) : ""
  }

  function accountTooltip(provider) {
    if (!provider) return ""
    var lines = []
    if (!hideAccountEmails && provider.account) lines.push("Account: " + String(provider.account))
    if (provider.source) lines.push("Source: " + String(provider.source))
    return lines.join("\n")
  }

  function lastAccount(provider) {
    return UsageLogic.lastUsedAccount(provider, activityBackend.providers, hideAccountEmails)
  }

  function lastAccountTooltip(account) {
    var text = "Last used: " + account.label
    if (account.lastUsedAt > 0)
      text += " · " + Qt.formatDateTime(new Date(account.lastUsedAt * 1000), "MMM d, HH:mm:ss")
    if (activityBackend.notice !== "") text += "\n" + activityBackend.notice
    else if (!account.reading) text += "\nNo unique last-used account is available in recorded requests."
    if (account.reading && account.reading.status === "disabled") text += "\nThis account is now paused."
    if (account.reading && account.reading.stale) text += "\nQuota is a last-known reading."
    if (activityBackend.fetchError !== "" && account.reading) text += "\nShowing last-known account activity."
    if (activityBackend.rustProxy) text += "\nLatest completed request, including failures; activity resets when the proxy restarts."
    return text
  }

  // Dark marks ship an `-light` variant for light surfaces; the registry says which.
  function iconUrl(provider) {
    var entry = provider ? UsageLogic.localProvider(provider.id) : null
    if (!entry) return ""
    var light = entry.lightIcon && colorLuminance(surface) >= 0.5
    return Qt.resolvedUrl("assets/" + entry.id + (light ? "-light.svg" : ".svg"))
  }

  function barIconUrl(provider) {
    if (!provider) return ""
    if (!UsageLogic.localProvider(provider.id)) return ""
    return Qt.resolvedUrl("assets/" + provider.id + "-bar.svg")
  }

  function colorLuminance(color) {
    function channel(value) {
      return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4)
    }
    return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b)
  }

  function creditsPrimary(credits) {
    if (!credits) return ""
    if (credits.remaining !== null && credits.remaining !== undefined)
      return UsageLogic.formatMoney(credits.remaining, credits.currency) + " remaining"
    if (credits.unlimited) return "Unlimited"
    if (credits.used !== null && credits.used !== undefined)
      return UsageLogic.formatMoney(credits.used, credits.currency) + " used"
    if (credits.resetCreditsAvailable !== null && credits.resetCreditsAvailable !== undefined)
      return credits.resetCreditsAvailable + " reset credit" + (credits.resetCreditsAvailable === 1 ? "" : "s")
    return "Available"
  }

  function creditsDetail(credits) {
    if (!credits) return ""
    var parts = []
    if (credits.used !== null && credits.used !== undefined) {
      if (credits.limit !== null && credits.limit !== undefined)
        parts.push(UsageLogic.formatMoney(credits.used, credits.currency) + " used of " + UsageLogic.formatMoney(credits.limit, credits.currency))
      else parts.push(UsageLogic.formatMoney(credits.used, credits.currency) + " used this month")
    }
    if (credits.unlimited && credits.remaining !== null && credits.remaining !== undefined)
      parts.push("No monthly spending cap")
    if (credits.total !== null && credits.total !== undefined)
      parts.push(UsageLogic.formatMoney(credits.total, credits.currency) + " funded")
    if (credits.resetCreditsAvailable !== null && credits.resetCreditsAvailable !== undefined)
      parts.push(credits.resetCreditsAvailable + " rate-limit reset credit" + (credits.resetCreditsAvailable === 1 ? "" : "s"))
    return parts.join(" · ")
  }

  // What went wrong and what to do. The sign-in command is added once: a backend message that
  // already quotes it is left alone.
  function errorBody(provider) {
    if (!provider) return ""
    var message = String(provider.message || "Usage data is unavailable.")
    if (!UsageLogic.errorNeedsSignIn(provider.errorKind))
      return message + "\nRetries on the next automatic refresh."
    var command = String(provider.authCommand || "")
    return command !== "" && message.indexOf(command) === -1
      ? message + "\nTo fix it, run “" + command + "” in a terminal, then refresh."
      : message
  }

  function footerLeft() {
    if (viewMode === "costs") {
      if (costBackend.fetchError !== "") return costBackend.fetchError
      if (costBackend.lastSuccessAt > 0)
        return "Updated " + Qt.formatTime(new Date(costBackend.lastSuccessAt), "HH:mm")
      return costBackend.loading ? "Loading session history…" : "Open Costs to load session history"
    }
    if (backend.fetchError !== "") return backend.fetchError
    if (backend.lastSuccessAt > 0) return "Updated " + Qt.formatTime(new Date(backend.lastSuccessAt), "HH:mm:ss")
    return backend.loading ? "Refreshing…" : "Waiting for first refresh"
  }

  // A countdown, written so it cannot be read as a clock time beside "Updated 14:56". Costs names its
  // sources there instead.
  function footerRight() {
    if (viewMode === "costs") return costsView.sourceSummary
    if (backend.nextRefreshAt <= 0) return ""
    var seconds = Math.max(0, Math.floor((backend.nextRefreshAt - nowMs) / 1000))
    if (seconds < 60) return "Next refresh in " + Math.max(1, seconds) + " s"
    return "Next refresh in " + Math.ceil(seconds / 60) + " min"
  }

  visible: true
  implicitWidth: percentageMode ? percentageGroup.implicitWidth : iconButton.implicitWidth
  implicitHeight: percentageMode ? percentageGroup.implicitHeight : iconButton.implicitHeight
  // Bar draws the open-panel mark at this width (otherwise it falls back to
  // 55% of the slot, which leaves the chips' outer ends unmarked).
  readonly property real openPanelIndicatorWidth: implicitWidth

  onProvidersChanged: ensureSelection()
  onSelectedProviderIdChanged: expandedAccountLimits = false
  onOpenedChanged: if (opened) {
    nowMs = Date.now()
    costBackend.ensureLoaded()
    if (panelFlick) panelFlick.contentY = 0
    Qt.callLater(function() {
      if (resetBackend.active) resetForm.focusFirst()
      else if (root.configuring) configForm.focusFirst()
      else keyCatcher.forceActiveFocus()
    })
  } else {
    if (costsView) costsView.closeMenu()
    if (configuring) viewMode = settingsReturnView
  }

  onViewModeChanged: {
    if (costsView) costsView.closeMenu()
    if (viewMode !== "settings") configForm.discardKey()
    if (viewMode === "costs") costBackend.ensureLoaded()
    if (panelFlick) panelFlick.contentY = 0
  }

  UsageBackend {
    id: backend
    settings: root.settings
    onRefreshed: {
      activityBackend.refresh()
      root.checkLimitCrossings()
    }
  }

  UsageActivityBackend {
    id: activityBackend
    usageBackend: backend
    settings: root.settings
  }

  ResetBackend {
    id: resetBackend
    usageBackend: backend
    onFinished: backend.refresh()
    onStateChanged: {
      if (panelFlick) panelFlick.contentY = 0
      Qt.callLater(function() {
        if (resetBackend.active) resetForm.focusFirst()
        else keyCatcher.forceActiveFocus()
      })
    }
  }

  CostBackend {
    id: costBackend
    settings: root.settings
  }

  // omp's live feed: requests as they happen, with their accounts (OmpActivity.qml).
  OmpActivity {
    id: ompActivity
    settings: root.settings
    status: backend.ompStatus
    costBackend: costBackend
  }

  Timer {
    interval: 1000
    running: root.opened
    repeat: true
    triggeredOnStart: true
    onTriggered: root.nowMs = Date.now()
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { root.refreshNow(); return "ok" }
    function next(): string { root.nextProvider(); return "ok" }
    function limits(): string { root.showLimits(); return "ok" }
    function costs(): string { root.showCosts(); return "ok" }
    function configureCosts(): string { root.showCostSettings(); return "ok" }
    function configureProviders(): string { root.showSettings("providers"); return "ok" }
    function configure(): string { root.showSettings(); return "ok" }
    function exportJson(): string { return UsageLogic.exportSnapshot(root.providers, Date.now() / 1000, root.hideAccountEmails) }
  }

  Ui.BarIconButton {
    id: iconButton
    anchors.fill: parent
    visible: !root.percentageMode
    bar: root.bar
    text: "󱚣"
    active: root.alarming
    tooltipText: root.provider ? "Model usage · " + root.provider.name
      + (root.proxyMode ? "\n" + root.lastAccountTooltip(root.lastAccount(root.provider)) : "") : "Model usage"
    onPressed: function(buttonCode) { root.handleBarPress(buttonCode) }
  }

  Item {
    id: percentageGroup
    anchors.fill: parent
    visible: root.percentageMode
    implicitWidth: percentageRow.implicitWidth
    implicitHeight: percentageRow.implicitHeight

    Row {
      id: percentageRow
      anchors.centerIn: parent
      spacing: 0

      Repeater {
        model: root.percentageProviders

        delegate: Ui.WidgetButton {
          id: providerChip
          required property var modelData

          readonly property var lastAccount: root.lastAccount(modelData)
          readonly property bool usingPoolQuota: root.proxyMode && !lastAccount.reading
          readonly property var reading: root.proxyMode && lastAccount.reading ? lastAccount.reading : modelData
          readonly property var limits: root.barLimitsFor(modelData.id)
          readonly property string quotaMode: root.quotaModeFor(modelData.id)
          readonly property bool failed: String(modelData.status) === "error"
          readonly property string blocking: failed ? "" : UsageLogic.blockingWindow(
            limits.top, UsageLogic.exactRemainingForWindow(reading, limits.top),
            limits.bottom, UsageLogic.exactRemainingForWindow(reading, limits.bottom))
          readonly property string topWindow: blocking !== "" ? blocking : limits.top
          readonly property string secondaryWindow: blocking !== "" ? "none" : limits.bottom
          // Money providers (OpenRouter, DeepSeek) lead with the balance on the chosen side; their tightest limit, if any, sits below.
          readonly property var money: failed ? null : UsageLogic.spendable(reading)
          readonly property var moneyShown: money === null ? null : UsageLogic.moneyView(reading, providerChip.quotaMode)
          readonly property bool moneyChip: money !== null
          // A second line that would repeat the first (the most constrained limit is the weekly one
          // and the second line asks for weekly too) is left out.
          readonly property bool sameLimitTwice: secondaryWindow !== "none"
            && UsageLogic.windowRowFor(reading, topWindow, true) !== null
            && UsageLogic.windowRowFor(reading, topWindow, true) === UsageLogic.windowRowFor(reading, secondaryWindow, false)
          readonly property bool windowStacked: secondaryWindow !== "none" && !failed && !moneyChip && !sameLimitTwice
          readonly property var remainingValue: UsageLogic.remainingForWindow(reading, topWindow)
          readonly property var shownValue: providerChip.quotaMode === "Remaining"
            ? remainingValue : UsageLogic.usedForWindow(reading, topWindow)
          readonly property bool stacked: windowStacked || (moneyChip && shownValue !== null)
          readonly property string shownText: shownValue === null
            ? (root.proxyMode ? "—" : "") : UsageLogic.formatPercent(shownValue) + "%"
          readonly property string severity: UsageLogic.severity(
            reading, root.warningThreshold, root.criticalThreshold, remainingValue)
          readonly property string moneySeverity: moneyChip ? root.moneySeverityOf(reading) : "none"
          readonly property var secondaryRemaining: windowStacked
            ? UsageLogic.exactRemainingForWindow(reading, secondaryWindow) : null
          readonly property string secondaryText: secondaryRemaining === null ? "—"
            : UsageLogic.formatPercent(providerChip.quotaMode === "Remaining"
              ? secondaryRemaining : UsageLogic.usedFromRemaining(secondaryRemaining)) + "%"
          readonly property string topTag: UsageLogic.barTagFor(reading, topWindow, true)
          readonly property string bottomTag: UsageLogic.windowShortLabel(secondaryWindow)
          readonly property string topReset: root.barShowResets
            ? root.barResetText(UsageLogic.windowRowFor(reading, topWindow, true)) : ""
          readonly property string bottomReset: root.barShowResets && windowStacked
            ? root.barResetText(UsageLogic.windowRowFor(reading, secondaryWindow, false)) : ""
          readonly property string percentTag: topTag !== "" || !moneyChip ? topTag
            : UsageLogic.rowPeriodTag(UsageLogic.windowRowFor(reading, topWindow, true))
          readonly property string percentLine: (percentTag ? percentTag + " " : "") + shownText + (topReset ? " · " + topReset : "")
          readonly property string topText: failed ? UsageLogic.errorReasonLabel(modelData.errorKind)
            : moneyChip ? moneyShown.text : percentLine
          readonly property string bottomText: moneyChip ? percentLine
            : (bottomTag ? bottomTag + " " : "") + secondaryText + (bottomReset ? " · " + bottomReset : "")
          readonly property string topSeverity: moneyChip ? moneySeverity : severity
          readonly property string secondarySeverity: moneyChip ? (stacked ? severity : "none")
            : secondaryRemaining === null ? "none"
            : UsageLogic.severity(reading, root.warningThreshold, root.criticalThreshold, secondaryRemaining)
          readonly property bool topStressed: topSeverity === "warning" || topSeverity === "critical"
          readonly property bool bottomStressed: secondarySeverity === "warning" || secondarySeverity === "critical"
          readonly property bool stressed: topStressed || bottomStressed
          readonly property string brandColor: root.providerColors
            ? UsageLogic.providerAccent(String(modelData.id), "") : ""
          readonly property color contentColor: brandColor !== "" ? brandColor
            : (active && useActiveColor ? activeColor : foreground)
          readonly property color stressColor: active && useActiveColor ? activeColor : foreground
          readonly property color topColor: brandColor !== "" && !failed && topStressed ? stressColor : contentColor
          readonly property color bottomColor: brandColor !== "" && !failed && bottomStressed ? stressColor : contentColor

          bar: root.bar
          text: ""
          labelVisible: false
          hasVisualContent: true
          fixedWidth: providerChipContent.implicitWidth + Style.space(10)
          active: stressed || failed
          horizontalMargin: 0
          tooltipText: failed
            ? String(modelData.name || modelData.id) + " · " + root.errorBody(modelData)
            : String(modelData.name || modelData.id)
            + (moneyChip ? (moneyShown.unit === "used" ? "\nSpent: " + moneyShown.text + " of " + UsageLogic.formatMoney(moneyShown.total, moneyShown.currency) : "")
              + "\nCan spend now: " + UsageLogic.formatMoney(money, moneyShown.currency) : "")
            + (shownValue === null ? (moneyChip ? "" : " usage unavailable")
              : "\n" + root.limitName(UsageLogic.windowRowFor(reading, topWindow, true), topWindow)
                + ": " + UsageLogic.quotaText(shownValue, providerChip.quotaMode))
            + (windowStacked ? "\n" + root.limitName(UsageLogic.windowRowFor(reading, secondaryWindow, false), secondaryWindow)
              + (secondaryRemaining === null ? ": not reported"
                : ": " + UsageLogic.quotaText(providerChip.quotaMode === "Remaining"
                  ? secondaryRemaining : UsageLogic.usedFromRemaining(secondaryRemaining), providerChip.quotaMode)) : "")
            + (root.proxyMode ? "\n" + root.lastAccountTooltip(lastAccount) : "")
            + (usingPoolQuota ? "\nQuota shown: account with the most remaining capacity." : "")
          onPressed: function(buttonCode) {
            root.handleProviderChipPress(String(providerChip.modelData.id), buttonCode)
          }

          Row {
            id: providerChipContent
            anchors.centerIn: parent
            spacing: Style.spacing.sm

            Item {
              id: providerMark
              y: Math.round((parent.height - height) / 2)
              width: Style.space(12)
              height: width

              Image {
                id: providerMarkImage
                anchors.fill: parent
                source: root.barIconUrl(providerChip.modelData)
                sourceSize.width: providerMark.width * 2
                sourceSize.height: providerMark.height * 2
                fillMode: Image.PreserveAspectFit
                visible: false
                layer.enabled: true
              }

              MultiEffect {
                anchors.fill: providerMarkImage
                source: providerMarkImage
                visible: providerMarkImage.status === Image.Ready
                colorization: 1.0
                colorizationColor: providerChip.contentColor
              }

              Text {
                anchors.centerIn: parent
                visible: providerMarkImage.status !== Image.Ready
                text: UsageLogic.providerMark(String(providerChip.modelData.id))
                color: providerChip.contentColor
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            Text {
              objectName: "barAccountRemaining"
              visible: !providerChip.stacked
              y: Math.round((parent.height - height) / 2)
              text: providerChip.topText
              color: providerChip.topColor
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              font.weight: Font.Medium
            }

            Column {
              visible: providerChip.stacked
              y: Math.round((parent.height - height) / 2)
              spacing: 0

              Text {
                objectName: "barAccountRemainingTop"
                text: providerChip.topText
                color: providerChip.topColor
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.weight: Font.Medium
                height: 12
                verticalAlignment: Text.AlignVCenter
              }

              Text {
                objectName: "barAccountRemainingBottom"
                text: providerChip.bottomText
                color: providerChip.bottomColor
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.weight: Font.Medium
                height: 12
                verticalAlignment: Text.AlignVCenter
              }
            }
          }
        }
      }

      // The providers left out by "Chips in the bar": one chip that names them and opens the first.
      Ui.WidgetButton {
        id: overflowChip
        objectName: "barOverflowChip"
        visible: root.overflowProviders.length > 0
        bar: root.bar
        text: "+" + root.overflowProviders.length
        horizontalMargin: Style.space(5)
        active: root.overflowProviders.some(function (provider) { return String(provider.status) === "error" })
        tooltipText: root.overflowProviders.map(function (provider) { return String(provider.name || provider.id) }).join("\n")
        onPressed: function(buttonCode) {
          if (root.overflowProviders.length > 0)
            root.handleProviderChipPress(String(root.overflowProviders[0].id), buttonCode)
        }
      }
    }
  }

  Ui.KeyboardPanel {
    id: panel
    anchorItem: root.percentageMode ? percentageGroup : iconButton
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: resetBackend.active ? resetForm : root.configuring ? configForm : keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(resetBackend.active ? resetForm.implicitHeight : contentColumn.implicitHeight)

    Ui.PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: root.configuring || resetBackend.active || costsView.menuOpen

      onMoveRequested: function(dx, dy) {
        if (dx !== 0 && root.viewMode === "limits" && root.providers.length > 1) {
          root.selectProvider(root.providerIndex + dx)
        }
        if (dy !== 0) {
          var target = panelFlick.contentY + dy * Style.space(56)
          panelFlick.contentY = root.clamp(target, 0,
            Math.max(0, panelFlick.contentHeight - panelFlick.height))
        }
      }
      onActivateRequested: root.refreshNow()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        if (text === "r" || text === "R") root.refreshNow()
        else if (text === "c" || text === "C") root.showCosts()
        else if (text === "u" || text === "U") root.showLimits()
        else if ((text === "p" || text === "P") && root.viewMode === "limits" && root.providers.length > 1) root.nextProvider()
        else if (root.viewMode === "costs" && (text === "m" || text === "M")) costsView.openMetricMenu()
        else if (root.viewMode === "costs" && (text === "d" || text === "D")) costsView.tokenDetailsExpanded = !costsView.tokenDetailsExpanded
        else if (root.viewMode === "costs" && (text === "b" || text === "B")) costsView.modelsExpanded = !costsView.modelsExpanded
        else if (text === "s" || text === "S") root.showSettings()
      }

      // Expanded sections and new delegates must be laid out before their
      // coordinates can be used to scroll the focused field into view.
      Timer {
        id: settingsRevealTimer
        property var item: null
        interval: 0
        onTriggered: {
          if (!root.configuring || !root.opened || !item || !item.visible) return
          for (var ancestor = item.parent; ancestor && ancestor !== panelFlick; ancestor = ancestor.parent)
            if (ancestor.forceLayout) ancestor.forceLayout()
          var point = item.mapToItem(panelFlick.contentItem, 0, 0)
          var bottom = point.y + item.height + Style.spacing.md
          var target = panelFlick.contentY
          if (point.y < target) target = point.y
          else if (bottom > target + panelFlick.height) target = bottom - panelFlick.height
          panelFlick.contentY = root.clamp(target, 0, Math.max(0, panelFlick.contentHeight - panelFlick.height))
        }
      }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: resetBackend.active ? resetForm.implicitHeight : contentColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        // A fractional height difference from fitting must not paint a scrollbar over the content.
        interactive: contentHeight > height + 1
        ScrollBar.vertical: ScrollBar { policy: panelFlick.interactive ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }

        ResetConfirmation {
          id: resetForm
          width: panelFlick.width
          visible: resetBackend.active
          backend: resetBackend
          foreground: root.foreground
          background: root.surface
          fontFamily: root.fontFamily
          onCloseRequested: {
            if (resetBackend.state === "sending" || resetBackend.state === "uncertain") root.close()
            else resetBackend.cancel()
          }
        }

        Column {
          id: contentColumn
          visible: !resetBackend.active
          width: panelFlick.width
          spacing: Style.spacing.xxl

          Column {
            visible: !root.configuring
            width: parent.width
            spacing: Style.spacing.md

            Item {
              width: parent.width
              implicitHeight: Math.max(panelTitle.implicitHeight, headerActions.implicitHeight)

              Text {
                id: panelTitle
                anchors.left: parent.left
                anchors.right: headerActions.left
                anchors.rightMargin: Style.spacing.md
                anchors.verticalCenter: parent.verticalCenter
                text: "Quotatank"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
              }

              Row {
                id: headerActions
                anchors.right: parent.right
                spacing: Style.spacing.xs

                Ui.PanelActionButton {
                  objectName: root.viewMode === "costs" ? "costSettingsButton" : "usageSettingsButton"
                  iconText: "󰒓"
                  tooltipText: root.viewMode === "costs" ? "Settings · Costs" : "Settings"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  fontSize: Style.font.body
                  onClicked: root.viewMode === "costs" ? root.showCostSettings() : root.showSettings()
                }

                Ui.PanelActionButton {
                  iconText: "󰑐"
                  tooltipText: root.viewMode === "costs" ? "Refresh estimated costs" : "Refresh usage"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  fontSize: Style.font.body
                  enabled: !(root.viewMode === "costs" ? costBackend.loading : backend.loading)
                  onClicked: root.refreshNow()
                }
              }
            }

            UsageNavigation {
              id: navigation
              width: parent.width
              viewMode: root.viewMode
              viewOptions: root.viewOptions
              providerOptions: root.providerOptions
              providerId: root.selectedProviderId
              foreground: root.foreground
              urgent: root.urgent
              fontFamily: root.fontFamily
              cardRadius: root.usageCardRadius
              onViewRequested: function(value) { root.viewMode = value }
              onProviderRequested: function(value) { root.selectProviderId(value) }
            }

            Text {
              width: parent.width
              text: {
                if (root.viewMode === "costs")
                  return costBackend.loading ? "Loading session history…" : ""
                var context = root.accountOverview
                  ? root.proxyAccounts.length + " connected accounts" : root.heroMeta(root.provider)
                if (root.providers.length === 1 && root.provider)
                  context = root.provider.name + (context ? " · " + context : "")
                return context + (backend.loading ? (context ? " · " : "") + "Refreshing…" : "")
              }
              visible: text !== ""
              textFormat: Text.PlainText
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            Text {
              objectName: "limitsHeadline"
              width: parent.width
              visible: root.viewMode === "limits" && text !== ""
              text: root.headline.text
              textFormat: Text.PlainText
              color: root.headline.urgent ? root.urgent : root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.heading
              font.bold: true
              wrapMode: Text.WordWrap
            }
          }

          UsageSettings {
            id: configForm
            visible: root.viewMode === "settings"
            width: parent.width
            settings: root.settings
            foreground: root.foreground
            urgent: root.urgent
            surface: root.surface
            fontFamily: root.fontFamily
            accountDetails: root.accountTooltip(root.provider)
            proxyProviders: root.proxyMode ? backend.providers : []
            usagePayload: root.proxyMode ? null : backend.payload
            usageLoading: backend.loading
            proxyImplementation: backend.proxyImplementation
            costSources: costBackend.payload ? UsageLogic.listOrEmpty(costBackend.payload.sources) : []
            ompActivity: ompActivity
            onSetupRequested: function(entry, action) { root.startSetup(entry, action) }
            onChangeRequested: function(values) { root.saveSettings(values) }
            onCloseRequested: root.leaveSettings()
            onRevealRequested: function(item) {
              settingsRevealTimer.item = item
              settingsRevealTimer.restart()
            }
          }

          Column {
            id: accountOverviewSection
            visible: root.viewMode === "limits" && root.accountOverview
            width: parent.width
            spacing: Style.spacing.lg

            Text {
              objectName: "liveActivityStatus"
              width: parent.width
              visible: activityBackend.useLive
              text: activityBackend.liveNotice
              textFormat: Text.PlainText
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            Repeater {
              id: accountRepeater
              model: root.proxyAccounts
              ProxyAccountCard {
                required property var modelData
                required property int index
                width: accountOverviewSection.width
                account: modelData
                accountNumber: index + 1
              }
            }

            Ui.Button {
              text: "Additional limits " + (root.expandedAccountLimits ? "▴" : "▾")
              focusable: true
              horizontalPadding: Style.spacing.sm
              Accessible.name: root.expandedAccountLimits ? "Hide additional limits" : "Show additional limits"
              foreground: root.foreground
              fontFamily: root.fontFamily
              fontSize: Style.font.bodySmall
              onClicked: root.expandedAccountLimits = !root.expandedAccountLimits
            }
          }

          Text {
            visible: root.viewMode === "limits" && root.providers.length === 0
            width: parent.width
            topPadding: Style.spacing.huge
            bottomPadding: Style.spacing.huge
            text: backend.loading
              ? "Reading your limits…"
              : root.proxyMode ? "No enabled managed accounts found. Check the accounts configured in " + UsageLogic.proxyName(backend.proxyImplementation) + "."
              : "Nothing to show yet. Sign in to a provider's CLI or app, or turn one on under Settings → Providers."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
          }

          Ui.BorderSurface {
            id: errorCard
            visible: root.viewMode === "limits" && !root.accountOverview && !!root.provider && root.provider.status === "error"
            width: parent.width
            implicitHeight: errorColumn.implicitHeight + errorCard.contentTopInset + errorCard.contentBottomInset
            color: root.alpha(root.urgent, 0.09)
            borderSpec: Border.flat(root.alpha(root.urgent, 0.4), Style.spacing.hairline)
            padding: Style.spacing.xxl
            radius: root.usageCardRadius

            Column {
              id: errorColumn
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.top: parent.top
              anchors.leftMargin: errorCard.contentLeftInset
              anchors.rightMargin: errorCard.contentRightInset
              anchors.topMargin: errorCard.contentTopInset
              spacing: Style.spacing.labelGap

              Text {
                width: parent.width
                text: UsageLogic.errorTitle(root.provider)
                color: root.urgent
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
                wrapMode: Text.WordWrap
              }

              Text {
                width: parent.width
                text: root.errorBody(root.provider)
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
              }

              // The same one-click fix Settings offers, right where the failure is reported.
              Ui.Button {
                id: errorSetupButton
                objectName: "errorSetupButton"
                readonly property var entry: root.proxyMode || !root.provider ? null : UsageLogic.localProvider(root.provider.id)
                readonly property var action: UsageLogic.setupAction(entry, root.provider, backend.installed)
                visible: action.kind === "signin" || action.kind === "install"
                text: root.setupWatchId !== "" && entry && root.setupWatchId === entry.id ? "Waiting for the sign-in…" : action.label
                bordered: true
                foreground: root.foreground
                fontFamily: root.fontFamily
                fontSize: Style.font.bodySmall
                focusable: true
                tooltipText: action.command
                onClicked: root.startSetup(entry, action)
              }
            }
          }

          Text {
            visible: root.viewMode === "limits" && !root.accountOverview && !!root.provider && root.provider.status !== "error"
              && String(root.provider.notice || "") !== ""
            width: parent.width
            text: root.provider ? String(root.provider.notice || "") : ""
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          Ui.PanelSeparator {
            visible: root.viewMode === "limits" && (balanceCard.visible || limitsSection.visible || creditsSection.visible)
            foreground: root.foreground
          }

          BalanceCard {
            id: balanceCard
            visible: root.viewMode === "limits" && !root.accountOverview && !!root.provider
              && root.provider.status === "ok" && UsageLogic.spendable(root.provider) !== null
            width: parent.width
            provider: visible ? root.provider : null
          }

          Column {
            id: limitsSection
            visible: root.viewMode === "limits" && !root.accountOverview && !!root.provider && root.provider.status === "ok"
              && UsageLogic.isListLike(root.provider.windows) && root.provider.windows.length > 0
            width: parent.width
            spacing: Style.spacing.lg

            Repeater {
              model: root.provider ? UsageLogic.orderedWindows(root.provider.windows) : []

              LimitCard {
                required property var modelData
                width: limitsSection.width
                window: modelData
                severity: root.windowSeverity(modelData)
                resetLabel: root.resetText(modelData)
                quotaMode: root.selectedQuotaMode
                foreground: root.foreground
                urgent: root.urgent
                providerColor: root.providerColors ? UsageLogic.providerAccent(String(root.provider ? root.provider.id : ""), root.foreground) : root.foreground
                dim: root.dim
                fontFamily: root.fontFamily
                cardRadius: root.usageCardRadius
                nowSeconds: root.nowMs / 1000
                clockFormat: root.tickTimeFormat
              }
            }
            PacingLegend {
              foreground: root.foreground
              dim: root.dim
              fontFamily: root.fontFamily
            }
          }

          Column {
            id: creditsSection
            visible: root.viewMode === "limits" && !root.accountOverview && !!root.provider
              && root.provider.status === "ok" && !!root.provider.credits && !balanceCard.visible
            width: parent.width
            spacing: Style.spacing.lg

            UsageDisclosure {
              id: creditsToggle
              width: parent.width
              foreground: root.foreground
              fontFamily: root.fontFamily
              text: root.provider && root.provider.credits
                ? String(root.provider.credits.label || "Credits") : "Credits"
            }

            CreditsCard {
              width: parent.width
              credits: root.provider ? root.provider.credits : null
              visible: creditsToggle.checked
            }
          }

          Ui.PanelSeparator {
            visible: root.historyAvailable
            foreground: root.foreground
          }

          UsageDisclosure {
            id: historyToggle
            visible: root.historyAvailable
            width: parent.width
            foreground: root.foreground
            fontFamily: root.fontFamily
            text: "History"
          }

          UsageHistory {
            id: history
            visible: historyToggle.checked && root.historyAvailable
            width: parent.width
            history: root.provider ? root.provider.history : ({ h24: [], d7: [] })
            mode: root.historyMode
            foreground: root.foreground
            fontFamily: root.fontFamily
            onModeChanged: root.historyMode = mode
          }

          Ui.PanelSeparator {
            visible: root.tokensAvailable
            foreground: root.foreground
          }

          UsageDisclosure {
            id: tokensToggle
            visible: root.tokensAvailable
            width: parent.width
            foreground: root.foreground
            fontFamily: root.fontFamily
            text: "Tokens by model"
          }

          UsageTokenModels {
            id: tokensByModel
            visible: tokensToggle.checked && root.tokensAvailable
            width: parent.width
            models: root.providerModels
            periodLabel: costBackend.payload && costBackend.payload.period
              ? String(costBackend.payload.period.label || "") : ""
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          UsageCosts {
            id: costsView
            visible: root.viewMode === "costs"
            width: parent.width
            payload: costBackend.payload
            loading: costBackend.loading
            errorText: costBackend.fetchError
            periodDays: costBackend.periodDays
            foreground: root.foreground
            urgent: root.urgent
            surface: root.surface
            fontFamily: root.fontFamily
            clockFormat: root.tickTimeFormat
            onPeriodRequested: function(days) { costBackend.selectPeriod(days) }
            onMenuClosed: Qt.callLater(function() {
              if (root.opened && !root.configuring && !resetBackend.active)
                keyCatcher.forceActiveFocus()
            })
          }

          // One quiet pointer to providers set up here but not monitored; it goes away once each is
          // monitored or ignored under Settings → Providers.
          Text {
            objectName: "foundProvidersLine"
            visible: root.viewMode === "limits" && root.foundProviders.length > 0
            width: parent.width
            text: UsageLogic.foundSummary(root.foundProviders) + " · Set up"
            textFormat: Text.PlainText
            color: foundArea.containsMouse ? root.foreground : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.underline: foundArea.containsMouse
            wrapMode: Text.WordWrap
            Accessible.role: Accessible.Link
            Accessible.name: text

            MouseArea {
              id: foundArea
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.showSettings("providers")
            }
          }

          Ui.PanelSeparator { visible: !root.configuring; foreground: root.foreground }

          Item {
            visible: !root.configuring
            width: parent.width
            implicitHeight: Math.max(footerLeft.implicitHeight, footerRight.implicitHeight)

            Text {
              id: footerLeft
              HoverHandler { id: footerHover }
              Ui.PanelToolTip {
                visible: footerHover.hovered && root.viewMode === "costs" && costBackend.lastSuccessAt > 0
                text: "Updated " + Qt.formatDateTime(new Date(costBackend.lastSuccessAt), "MMM d, HH:mm:ss")
                  + (costBackend.payload && Number(costBackend.payload.scanDurationMs) > 0
                    ? " · Scan " + costBackend.payload.scanDurationMs + "ms" : "")
                fontFamily: root.fontFamily
              }
              anchors.left: parent.left
              anchors.right: footerRight.left
              anchors.rightMargin: Style.spacing.controlGap
              text: root.footerLeft()
              color: (root.viewMode === "costs" ? costBackend.fetchError : backend.fetchError) !== ""
                ? root.urgent : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }

            Text {
              id: footerRight
              anchors.right: parent.right
              text: root.footerRight()
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }
      }
    }
  }

  component ProxyAccountCard: Ui.BorderSurface {
    id: accountCard
    objectName: "proxyAccountCard"
    property var account: ({})
    property int accountNumber: 0
    property bool activityExpanded: false
    readonly property var load: UsageLogic.accountLoad(account, activityBackend)
    readonly property var windows: UsageLogic.accountWindows(account, root.expandedAccountLimits)
    readonly property bool healthy: account.status === "ok"
    implicitHeight: accountContent.implicitHeight + contentTopInset + contentBottomInset
    color: Style.normalFillFor(root.foreground, Commons.Color.accent, root.urgent)
    borderSpec: Border.flat(root.alpha(root.foreground, 0.22), Style.spacing.hairline)
    padding: Style.spacing.xxl
    radius: root.usageCardRadius

    Column {
      id: accountContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.leftMargin: accountCard.contentLeftInset
      anchors.rightMargin: accountCard.contentRightInset
      anchors.topMargin: accountCard.contentTopInset
      spacing: Style.spacing.md

      Item {
        width: parent.width
        implicitHeight: Math.max(accountLogo.height, accountPlan.implicitHeight,
          resetBadge.visible ? resetBadge.implicitHeight : 0,
          sessionBadge.visible ? sessionBadge.implicitHeight : 0)

        Item {
          id: accountLogo
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          width: Style.font.body * 1.2
          height: width

          Image {
            id: accountLogoImage
            anchors.fill: parent
            source: root.iconUrl(accountCard.account)
            sourceSize.width: accountLogo.width * 2
            sourceSize.height: accountLogo.height * 2
            fillMode: Image.PreserveAspectFit
          }

          Text {
            anchors.centerIn: parent
            visible: accountLogoImage.status !== Image.Ready
            text: UsageLogic.providerMark(accountCard.account.id)
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
          }
        }

        Text {
          id: accountPlan
          anchors.left: accountLogo.right
          anchors.leftMargin: Style.spacing.md
          anchors.verticalCenter: parent.verticalCenter
          width: Math.max(0, parent.width - accountLogo.width - Style.spacing.md
            - (resetBadge.visible ? resetBadge.width + Style.spacing.md : 0)
            - (sessionBadge.visible ? sessionBadge.width + Style.spacing.md : 0))
          text: UsageLogic.accountPlanLabel(accountCard.account)
          textFormat: Text.PlainText
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
          verticalAlignment: Text.AlignVCenter
          wrapMode: Text.WordWrap
        }

        Ui.Button {
          id: sessionBadge
          objectName: "accountSessionBadge"
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          visible: activityBackend.useLive
          text: UsageLogic.sessionBadgeText(accountCard.load)
          focusable: true
          bordered: true
          horizontalPadding: Style.spacing.sm
          verticalPadding: Style.spacing.xs
          foreground: accountCard.load !== null && accountCard.load.sessions > 0 ? root.foreground : root.dim
          fontFamily: root.fontFamily
          fontSize: Style.font.caption
          tooltipText: UsageLogic.sessionDetails(accountCard.load)
          Accessible.name: text + (accountCard.activityExpanded ? ", hide session details" : ", show session details")
          onClicked: accountCard.activityExpanded = !accountCard.activityExpanded
        }

        Rectangle {
          id: resetBadge
          objectName: "accountResetBadge"
          anchors.right: sessionBadge.visible ? sessionBadge.left : parent.right
          anchors.rightMargin: sessionBadge.visible ? Style.spacing.md : 0
          anchors.verticalCenter: parent.verticalCenter
          visible: resetLabel.text !== ""
          implicitWidth: resetLabel.implicitWidth + Style.spacing.lg * 2
          implicitHeight: resetLabel.implicitHeight + Style.spacing.sm * 2
          radius: height / 2
          color: resetClick.containsMouse && resetClick.enabled || activeFocus ? root.alpha(root.foreground, 0.08) : "transparent"
          border.color: root.alpha(root.foreground, activeFocus ? 0.6 : 0.18)
          activeFocusOnTab: resetClick.enabled
          Accessible.role: Accessible.Button
          Accessible.name: resetLabel.text + ": apply a reset"
          Keys.onReturnPressed: resetClick.activate()
          Keys.onSpacePressed: resetClick.activate()

          MouseArea {
            id: resetClick
            objectName: "accountResetAction"
            anchors.fill: parent
            enabled: root.proxyMode && accountCard.account.status === "ok"
              && accountCard.account.supportsBankedReset !== false
              && Number(accountCard.account.credits && accountCard.account.credits.resetCreditsAvailable) > 0
              && !resetBackend.active && !resetBackend.busy
            hoverEnabled: true
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            function activate() {
              if (enabled) resetBackend.begin(accountCard.account,
                root.accountDisplayName(accountCard.account, accountCard.accountNumber))
            }
            onClicked: activate()
          }

          ToolTip.visible: resetClick.containsMouse
          ToolTip.text: resetClick.enabled ? "Apply a banked reset to this account" : "No reset available"

          Text {
            id: resetLabel
            objectName: "accountResetLabel"
            anchors.centerIn: parent
            text: UsageLogic.accountResetLabel(accountCard.account)
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
      Text {
        objectName: "accountName"
        width: parent.width
        text: root.accountDisplayName(accountCard.account, accountCard.accountNumber)
        textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideMiddle
      }
      Text {
        objectName: "accountActivityDetails"
        width: parent.width
        visible: activityBackend.useLive && accountCard.activityExpanded
        text: UsageLogic.sessionDetails(accountCard.load)
        textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Repeater {
        model: accountCard.healthy ? accountCard.windows : []
        Column {
          id: accountWindow
          required property var modelData
          objectName: "proxyAccountWindow"
          readonly property bool known: modelData.remaining !== null && modelData.remaining !== undefined
            && isFinite(Number(modelData.remaining))
          readonly property bool stressed: root.windowSeverity(modelData) === "warning" || root.windowSeverity(modelData) === "critical"
          width: accountContent.width
          spacing: Style.spacing.sm
          Item {
            width: parent.width
            implicitHeight: accountFigure.implicitHeight
            readonly property var shown: root.selectedQuotaMode === "Remaining"
              ? UsageLogic.windowRemaining(accountWindow.modelData)
              : UsageLogic.windowUsed(accountWindow.modelData)
            Text {
              anchors.left: parent.left
              anchors.right: accountFigure.left
              anchors.rightMargin: Style.spacing.controlGap
              anchors.baseline: accountFigure.baseline
              text: String(accountWindow.modelData.label || "Usage limit")
              textFormat: Text.PlainText
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }
            Text {
              id: accountFigure
              anchors.right: accountUnit.left
              anchors.rightMargin: accountUnit.visible ? Style.spacing.sm : 0
              text: accountWindow.known ? UsageLogic.formatPercent(parent.shown) + "%" : "—"
              color: accountWindow.stressed ? root.urgent : root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
            }
            Text {
              id: accountUnit
              visible: accountWindow.known
              anchors.right: parent.right
              anchors.baseline: accountFigure.baseline
              text: !accountWindow.known ? "" : root.selectedQuotaMode === "Remaining" ? "left" : "used"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
          BlockMeter {
            visible: accountWindow.known
            width: parent.width
            height: Style.space(10)
            value: UsageLogic.meterFill(accountWindow.modelData, root.selectedQuotaMode) || 0
            fillColor: accountWindow.stressed ? root.urgent : root.foreground
            trackColor: root.alpha(root.foreground, 0.14)
          }
          Text {
            width: parent.width
            visible: text !== ""
            text: root.resetText(accountWindow.modelData)
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }

      Text {
        width: parent.width
        visible: text !== ""
        text: accountCard.account.status === "error" ? root.errorBody(accountCard.account)
          : accountCard.account.stale || !accountCard.healthy ? String(accountCard.account.notice || "Quota unavailable")
          : accountCard.windows.length === 0 && UsageLogic.spendable(accountCard.account) !== null
            ? UsageLogic.formatMoney(UsageLogic.spendable(accountCard.account), UsageLogic.moneyCurrency(accountCard.account)) + " left"
          : accountCard.windows.length === 0 ? "No subscription limits reported." : ""
        textFormat: Text.PlainText
        color: accountCard.account.status === "error" ? root.urgent : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }

  // Money a provider can still spend (OpenRouter, DeepSeek): the amount large, its share as a meter,
  // where it comes from, recent spend, and how long it lasts at this week's rate.
  component BalanceCard: Ui.BorderSurface {
    id: moneyCard
    property var provider: null
    readonly property var credits: provider ? provider.credits : null
    readonly property var amount: UsageLogic.spendable(provider)
    readonly property var view: UsageLogic.moneyView(provider, root.selectedQuotaMode)
    readonly property var share: view ? view.share : null
    readonly property string level: provider ? root.moneySeverityOf(provider) : "none"
    readonly property bool stressed: level === "warning" || level === "critical"
    readonly property bool hasBalance: !!credits && credits.remaining !== null && credits.remaining !== undefined
    readonly property var spend: credits && credits.spend ? credits.spend : ({})
    readonly property string runway: UsageLogic.moneyRunway(amount, spend.weekly, root.nowMs / 1000)
    readonly property string currency: UsageLogic.moneyCurrency(provider)

    function money(value) { return UsageLogic.formatMoney(value, currency) }

    function spendLine() {
      var parts = []
      if (spend.daily !== null && spend.daily !== undefined) parts.push("Today " + money(spend.daily))
      if (spend.weekly !== null && spend.weekly !== undefined) parts.push("Week " + money(spend.weekly))
      if (spend.monthly !== null && spend.monthly !== undefined) parts.push("Month " + money(spend.monthly))
      return parts.join(" · ")
    }

    // Where the balance comes from: purchased and used for OpenRouter; granted and topped up for
    // DeepSeek. A spending limit is named only when it holds back a noticeable part of the balance.
    function sourceLine() {
      if (!hasBalance) return "Save a management key to see the account balance too."
      var parts = []
      if (credits.total !== null && credits.total !== undefined) parts.push(money(credits.total) + " purchased")
      if (credits.used !== null && credits.used !== undefined) parts.push(money(credits.used) + " used")
      if (Number(credits.granted) > 0) parts.push(money(credits.granted) + " granted")
      if (Number(credits.toppedUp) > 0) parts.push(money(credits.toppedUp) + " topped up")
      var text = parts.join(" · ")
      if (amount !== null && Number(credits.remaining) - amount >= Math.max(1, Number(credits.remaining) * 0.05))
        text += (text ? "\n" : "") + "A spending limit allows " + money(amount) + " of the " + money(credits.remaining) + " balance now"
      return text
    }

    objectName: "moneyCard"
    implicitHeight: moneyContent.implicitHeight + contentTopInset + contentBottomInset
    color: level === "critical" ? root.alpha(root.urgent, 0.09) : Style.normalFillFor(root.foreground, Commons.Color.accent, root.urgent)
    borderSpec: stressed
      ? Border.flat(root.alpha(root.urgent, level === "critical" ? 0.45 : 0.28), Style.spacing.hairline)
      : Border.controlSpec("normal", root.foreground, Commons.Color.accent, root.urgent)
    padding: Style.spacing.xxl
    radius: root.usageCardRadius

    Column {
      id: moneyContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.leftMargin: moneyCard.contentLeftInset
      anchors.rightMargin: moneyCard.contentRightInset
      anchors.topMargin: moneyCard.contentTopInset
      spacing: Style.spacing.md

      Item {
        width: parent.width
        implicitHeight: moneyFigure.implicitHeight

        Text {
          anchors.left: parent.left
          anchors.right: moneyFigure.left
          anchors.rightMargin: Style.spacing.controlGap
          anchors.baseline: moneyFigure.baseline
          text: moneyCard.hasBalance ? "Balance" : "Can spend"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
          elide: Text.ElideRight
        }

        Text {
          id: moneyFigure
          anchors.right: moneyUnit.left
          anchors.rightMargin: Style.spacing.sm
          text: moneyCard.view ? moneyCard.view.text : moneyCard.money(moneyCard.amount)
          color: moneyCard.stressed ? root.urgent : root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.heading
          font.bold: true
        }

        Text {
          id: moneyUnit
          anchors.right: parent.right
          anchors.baseline: moneyFigure.baseline
          text: moneyCard.view ? moneyCard.view.unit : "left"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }

      BlockMeter {
        visible: moneyCard.share !== null
        width: parent.width
        height: Style.space(12)
        value: moneyCard.share === null ? 0 : moneyCard.share / 100
        fillColor: moneyCard.stressed ? root.urgent
          : root.providerColors ? UsageLogic.providerAccent(String(moneyCard.provider ? moneyCard.provider.id : ""), root.foreground) : root.foreground
        trackColor: root.alpha(root.foreground, 0.14)
      }

      Text {
        width: parent.width
        text: moneyCard.sourceLine()
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Text {
        visible: text !== ""
        width: parent.width
        text: moneyCard.spendLine()
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Text {
        visible: text !== ""
        width: parent.width
        text: (moneyCard.stressed ? moneyCard.money(moneyCard.amount) + " left, at or below your "
            + moneyCard.money(moneyCard.level === "critical" ? root.creditCriticalUsd : root.creditWarningUsd) + " alert"
            + (moneyCard.runway !== "" ? " · " : "") : "")
          + (moneyCard.runway !== "" ? (moneyCard.stressed ? "lasts " : "Lasts ") + moneyCard.runway + " at this week's rate" : "")
        color: moneyCard.stressed ? root.urgent : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }

  component CreditsCard: Ui.BorderSurface {
    id: creditsCard
    property var credits: null
    readonly property bool hasMeter: !!credits
      && credits.used !== null && credits.used !== undefined
      && credits.limit !== null && credits.limit !== undefined
      && Number(credits.limit) > 0

    implicitHeight: creditsContent.implicitHeight + contentTopInset + contentBottomInset
    color: Style.normalFillFor(root.foreground, Commons.Color.accent, root.urgent)
    borderSpec: Border.controlSpec("normal", root.foreground, Commons.Color.accent, root.urgent)
    padding: Style.spacing.xxl
    radius: root.usageCardRadius

    Column {
      id: creditsContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.leftMargin: creditsCard.contentLeftInset
      anchors.rightMargin: creditsCard.contentRightInset
      anchors.topMargin: creditsCard.contentTopInset
      spacing: Style.spacing.md

      Text {
        width: parent.width
        text: root.creditsPrimary(creditsCard.credits)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        visible: creditsCard.hasMeter
        width: parent.width
        text: creditsCard.hasMeter
          ? "Monthly allowance · " + Math.round(UsageLogic.sideOfUsed(Number(creditsCard.credits.used) / Number(creditsCard.credits.limit) * 100, root.selectedQuotaMode))
            + (root.selectedQuotaMode === "Remaining" ? "% left" : "% used")
          : ""
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }

      BlockMeter {
        visible: creditsCard.hasMeter
        width: parent.width
        value: creditsCard.hasMeter
          ? UsageLogic.sideOfUsed(Number(creditsCard.credits.used) / Number(creditsCard.credits.limit) * 100, root.selectedQuotaMode) / 100 : 0
        fillColor: root.foreground
        trackColor: root.alpha(root.foreground, 0.14)
      }

      Text {
        visible: text !== ""
        width: parent.width
        text: root.creditsDetail(creditsCard.credits)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }
}
