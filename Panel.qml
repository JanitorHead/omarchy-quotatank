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

  // The saved order drives tiles, chips, and provider cycling alike.
  readonly property string providerOrder: String(setting("providerOrder", "[]"))
  readonly property var providers: UsageLogic.orderProviders(UsageLogic.availableProviders(
    UsageLogic.selectedProviders(backend.providers, backend.enabledProviderIds)), providerOrder)
  // Providers set up on this computer that are neither monitored nor dismissed. Limits points to
  // them in one quiet line until each is monitored or ignored under Settings → Providers.
  readonly property var foundProviders: UsageLogic.foundProviders(backend.detected,
    backend.enabledProviderIds, UsageLogic.listOrEmpty(setting("dismissedProviders", UsageLogic.DEFAULT_SETTINGS.dismissedProviders)))
  property string selectedProviderId: ""
  property string viewMode: "limits"
  property string settingsReturnView: "limits"
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
  readonly property bool barShowPeriods: setting("barShowPeriods", true) !== false
  // Clock format for the pace tick's "Now" time: the same reset time setting as the bar.
  readonly property string tickTimeFormat: UsageLogic.barResetFormat("time", setting("barResetTimeFormat", "24h"), setting("barResetDateFormat", "DD/MM"))
  // Optionally drop accounts whose weekly or monthly limit is used up, and a provider once all of them
  // are: they cannot be used until it resets. Limits still shows them, marked used up, with the reset time.
  readonly property bool hideUsedUpProviders: setting("hideExhaustedProviders", false) === true
  readonly property var barCandidates: UsageLogic.barProviders(
    UsageLogic.selectedProviders(providers, setting("barProviders", UsageLogic.DEFAULT_SETTINGS.barProviders)),
    function (provider) { return barLimitsFor(provider.id).top })
    .map(function (provider) { return hideUsedUpProviders ? UsageLogic.withoutUsedUpAccounts(provider) : provider })
    .filter(function (provider) { return provider !== null })
  // With many providers the bar keeps the ones closest to a limit (failures first) and folds the
  // rest into one "+N" chip, so the bar never pushes into the clock. The cap counts chips: under "One
  // chip per account" a provider takes one chip per account it shows.
  readonly property int barMaxChips: Number(setting("barMaxChips", UsageLogic.DEFAULT_SETTINGS.barMaxChips))
  readonly property var chipSelection: UsageLogic.limitChips(barCandidates, barMaxChips, chipPressure,
    function (provider) { return UsageLogic.barChipCount(provider, root.barAccountMode, root.barMaxChips) })
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
  property alias usageBackend: backend
  readonly property alias providerTiles: navigation.tiles
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
  readonly property var proxyAccounts: UsageLogic.listOrEmpty(providerSummary && providerSummary.accounts)
  // A provider read only through a proxy always shows its accounts; otherwise it lists them once it has more
  // than one (Omarchy subscription accounts, extra API keys, accounts omp, other computers or a proxy read).
  readonly property bool accountOverview: proxyAccounts.length > (UsageLogic.proxyPool(providerSummary) ? 0 : 1)
  property alias accountList: accountListView
  property alias limitCards: limitCards
  readonly property var providerOptions: {
    var result = []
    for (var i = 0; i < providers.length; i++) result.push(providerTile(providers[i]))
    return result
  }

  // ---- Accounts: one state per provider (UsageLogic.accountState), read by the chip, its dots and
  // hover card, the tile, the Limits rows, the detail and the runway, so they all count, order and ring
  // the same accounts. It follows the panel's one clock (`nowMs`: every second while the panel is
  // open, every 30 s for the bar while it is closed) and one map of recent use.
  readonly property real nowSeconds: nowMs / 1000
  // omp's live feed (OmpActivity.qml): requests as they happen, with their accounts. Tests put a
  // stand-in with the same signals and properties here.
  property QtObject ompActivity: ompActivityHelper
  // The latest sign of use per account: live omp requests and, through a proxy's Keeper, each account's last
  // request; the newest wins (UsageLogic.mergeRecentActivity).
  readonly property var recentByAccount: UsageLogic.mergeRecentActivity(
    ompActivity && ompActivity.recentByAccount ? ompActivity.recentByAccount : null, activityBackend.providers)
  readonly property var accountModeChoices: UsageLogic.parseAccountModes(setting("accountModes", "{}"))
  readonly property var accountStateOptions: ({ modes: accountModeChoices, nowSeconds: nowSeconds,
    recentByAccount: recentByAccount, warningThreshold: warningThreshold, criticalThreshold: criticalThreshold })
  readonly property var accountStates: {
    var states = {}
    for (var i = 0; i < providers.length; i++)
      states[String(providers[i].id)] = UsageLogic.accountState(providers[i], accountStateOptions)
    return states
  }
  function accountStateOf(reading) {
    return reading ? accountStates[String(reading.id)] || null : null
  }
  // The bar's chips index the accounts the bar shows. A reading trimmed of its used-up accounts has
  // fewer accounts than the state worked out for the full reading, so it gets a state of its own,
  // from the reading itself: its counted account, dots and chips per account then point at accounts
  // that are still there, even while the trim and the shared states update one after the other.
  function barAccountStateOf(reading) {
    var state = accountStateOf(reading)
    if (!state || UsageLogic.providerAccounts(reading).length === state.rings.length) return state
    return UsageLogic.accountState(reading, accountStateOptions)
  }
  // The provider on screen: one at a time ("single") or used together, the counted accounts, row order.
  readonly property var providerState: accountStateOf(providerSummary)
  readonly property string accountMode: providerState ? providerState.mode : "single"
  readonly property var countedIndexes: providerState ? providerState.counted : []
  readonly property var accountOrderIndexes: providerState ? providerState.order : []
  readonly property var accountNames: {
    var names = []
    for (var i = 0; i < proxyAccounts.length; i++) names.push(accountRowName(proxyAccounts[i], i + 1))
    return names
  }
  // The account the detail shows: the one the user picked; without a pick, the counted account as it
  // was when the panel opened or the provider was chosen (`defaultAccountId`). Counted accounts change
  // with every request, so the detail never follows them while it is on screen.
  property string selectedAccountId: ""
  property string defaultAccountId: ""
  function accountIndexOf(accountId) {
    if (accountId === "") return -1
    for (var i = 0; i < proxyAccounts.length; i++)
      if (String(proxyAccounts[i].accountId) === accountId) return i
    return -1
  }
  function countedAccountIndex() {
    var index = providerState ? providerState.value : -1
    return index >= 0 ? index : (proxyAccounts.length > 0 ? 0 : -1)
  }
  function latchDefaultAccount() {
    var index = countedAccountIndex()
    defaultAccountId = index >= 0 ? String(proxyAccounts[index].accountId) : ""
  }
  readonly property int selectedAccountIndex: {
    var picked = accountIndexOf(selectedAccountId)
    if (picked >= 0) return picked
    var latched = accountIndexOf(defaultAccountId)
    return latched >= 0 ? latched : countedAccountIndex()
  }
  // New accounts, or the latched one gone: latch again once the reading has settled.
  onProxyAccountsChanged: Qt.callLater(function() { if (root.accountIndexOf(root.defaultAccountId) < 0) root.latchDefaultAccount() })
  readonly property var selectedAccount: accountOverview && selectedAccountIndex >= 0 ? proxyAccounts[selectedAccountIndex] : null
  // The reading the detail shows: the selected account, or the provider itself.
  readonly property var detail: accountOverview ? selectedAccount : provider
  readonly property string detailKey: (provider ? String(provider.id) : "") + "@"
    + (selectedAccount ? String(selectedAccount.accountId) : "")
  readonly property var runway: provider && provider.status === "ok"
    ? UsageLogic.accountRunway(providerSummary, accountOverview ? accountMode : "single",
      accountOverview ? countedIndexes : [0], nowSeconds, accountOverview ? accountOrderIndexes : [0])
    : null
  // With several accounts while something is spent; for any provider once the limit runs out before it resets.
  readonly property bool runwayVisible: viewMode === "limits" && runway !== null
    && ((accountOverview && proxyAccounts.length > 1 && runway.spending) || runway.gap > 0
      || (runway.lanes.length > 0 && runway.lanes[0].kind === "runs"))
  readonly property var runwayNames: accountOverview ? accountNames
    : [provider ? UsageLogic.providerShortName(provider) : ""]

  // Account names for rows and notices: the email privacy setting applies, and "in use" is a tag of its
  // own in the row, not part of the name.
  function accountRowName(account, number) {
    return accountDisplayName(Object.assign({}, account, { active: false }), number)
  }

  function selectAccount(accountId) {
    var before = selectedAccountIndex
    selectedAccountId = String(accountId)
    if (selectedAccountIndex !== before && before >= 0)
      slideDetail(accountOrderIndexes.indexOf(selectedAccountIndex) < accountOrderIndexes.indexOf(before) ? -1 : 1)
  }

  // The detail of a newly chosen account fades in from the side of its row: from the left for a row
  // above the previous one, from the right for one below.
  property real detailSlideFrom: 0
  function slideDetail(direction) {
    detailSwapAnimation.stop()
    detailSlideFrom = direction * Style.space(12)
    detailSwapAnimation.start()
  }

  // A proxy account's banked reset: the confirmation takes over the panel, as before.
  function resetAccount(accountId) {
    for (var i = 0; i < proxyAccounts.length; i++) {
      if (String(proxyAccounts[i].accountId) !== String(accountId)) continue
      return resetBackend.begin(proxyAccounts[i], accountDisplayName(proxyAccounts[i], i + 1))
    }
    return false
  }

  // The detail's banked reset (the provider, or the selected account): the same confirmation.
  function resetDetail() {
    if (!detail) return false
    if (accountOverview) return resetAccount(detail.accountId)
    return resetBackend.begin(detail, String(detail.name || detail.id || ""))
  }

  // Under the banked-reset count: when the next one expires, and why it cannot be applied from here, if so.
  function bankedResetDetail(reading) {
    var parts = []
    var expires = reading && reading.credits ? Number(reading.credits.resetCreditsExpiresAt) : NaN
    if (isFinite(expires) && expires > 0) parts.push("Expires " + clockText(expires))
    var note = UsageLogic.accountResetNote(reading)
    if (note !== "") parts.push(note)
    return parts.join(" · ")
  }

  // Up/down walks the rows in their shown order; past either end the panel scrolls instead.
  function moveAccountSelection(step) {
    var order = accountOrderIndexes
    var at = order.indexOf(selectedAccountIndex)
    var next = at + step
    if (at < 0 || next < 0 || next >= order.length) return false
    selectAccount(proxyAccounts[order[next]].accountId)
    return true
  }

  // Use: Omarchy starts new sessions with that login (AccountEvents runs the command and watches for it).
  function useAccount(accountId) {
    if (!provider) return false
    for (var i = 0; i < proxyAccounts.length; i++)
      if (String(proxyAccounts[i].accountId) === String(accountId))
        return accountEventsTracker.use(provider.id, proxyAccounts[i], accountMode)
    return false
  }

  property alias accountEvents: accountEventsTracker
  readonly property var noticeEvent: accountEventsTracker.notice
  readonly property string noticeText: noticeEvent ? UsageLogic.eventNoticeText(noticeEvent,
    UsageLogic.readingFor(providers, noticeEvent.provider), noticeNames(noticeEvent.provider), clockText,
    noticeEvent.manual === true) : ""

  function noticeNames(providerId) {
    var reading = UsageLogic.readingFor(providers, providerId)
    var accounts = UsageLogic.providerAccounts(reading)
    var names = {}
    for (var i = 0; i < accounts.length; i++) names[String(accounts[i].accountId)] = accountRowName(accounts[i], i + 1)
    return names
  }

  AccountEvents {
    id: accountEventsTracker
    providers: backend.providers
    warningThreshold: root.warningThreshold
    panelOpen: root.opened
    onRefreshRequested: backend.refresh()
  }

  // Every clock time the panel and the bar show, in the user's clock format: the time alone today, with
  // the weekday within the week, with the date further out (UsageLogic.clockPattern).
  function clockText(epochSeconds) {
    var seconds = Number(epochSeconds)
    if (!isFinite(seconds) || seconds <= 0) return ""
    return Qt.formatDateTime(new Date(seconds * 1000), UsageLogic.clockPattern(seconds, nowSeconds, tickTimeFormat))
  }

  // Limit cards keep their delegates across readings (keyed by account and window), so a new reading
  // moves bars and digits instead of rebuilding the cards.
  function detailWindowKey(row, index) {
    return detailKey + "|" + String(row && (row.id || row.label) || index)
  }

  // The rows of the cards, by key, rebuilt once per reading so each card finds its row without a scan.
  property var detailWindowRows: ({})

  function detailWindowFor(key) {
    return detailWindowRows[key] || null
  }

  function syncLimitCards() {
    var all = detail ? UsageLogic.listOrEmpty(detail.windows) : []
    var byRow = new Map()
    for (var i = 0; i < all.length; i++) if (!byRow.has(all[i])) byRow.set(all[i], i)
    var rows = detail && detail.status === "ok" ? UsageLogic.orderedWindows(all) : []
    var keyed = {}
    var keys = []
    for (var j = 0; j < rows.length; j++) {
      var key = detailWindowKey(rows[j], byRow.get(rows[j]))
      if (Object.prototype.hasOwnProperty.call(keyed, key)) continue
      keyed[key] = rows[j]
      keys.push(key)
    }
    detailWindowRows = keyed
    UsageLogic.syncKeyedOrder({
      count: function() { return limitCardModel.count },
      keyAt: function(index) { return limitCardModel.get(index).cardKey },
      move: function(from, to) { limitCardModel.move(from, to, 1) },
      insert: function(index, value) { limitCardModel.insert(index, { cardKey: value }) }
    }, keys)
    while (limitCardModel.count > keys.length) limitCardModel.remove(limitCardModel.count - 1)
  }

  onDetailChanged: Qt.callLater(syncLimitCards)

  ListModel { id: limitCardModel }

  // Low-balance thresholds for providers measured in money (OpenRouter, DeepSeek), compared in the
  // balance's own currency.
  readonly property real creditCriticalUsd: Math.max(0, Number(setting("creditCriticalUsd", 1)) || 0)
  readonly property real creditWarningUsd: Math.max(creditCriticalUsd, Number(setting("creditWarningUsd", 5)) || 0)

  function moneySeverityOf(provider) {
    return UsageLogic.moneySeverity(UsageLogic.spendable(provider), creditWarningUsd, creditCriticalUsd)
  }

  // One overview tile: logo, short name, the most pressing figure on the chosen side, and a mini
  // meter. Money providers show dollars on that side too. A failed refresh shows its short reason.
  // A provider with several accounts shows the counted account with the least headroom and the dots
  // of its account state, like its chip.
  function providerTile(provider) {
    var id = String(provider.id)
    var failed = String(provider.status) === "error"
    var mode = quotaModeFor(id)
    var accounts = UsageLogic.providerAccounts(provider)
    var state = accounts.length > 1 ? accountStateOf(provider) : null
    var reading = !failed && state && state.value >= 0 ? accounts[state.value] : provider
    var money = failed ? null : UsageLogic.moneyView(reading, mode)
    var remaining = failed ? null : UsageLogic.minRemaining(reading)
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
      failed: failed,
      dots: state ? state.dots : null
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
  // With several accounts the same line heads the selected account's detail instead.
  readonly property var headline: accountOverview ? ({ text: "", urgent: false }) : headlineFor(provider)
  readonly property var accountHeadline: accountOverview ? headlineFor(selectedAccount) : ({ text: "", urgent: false })
  // A provider read with one account that has limits: that account, whose 24-hour trend and "spending now"
  // sit beside the headline. Providers with several accounts show both in their account rows instead.
  readonly property var singleAccount: {
    if (viewMode !== "limits" || accountOverview || !provider || provider.status !== "ok") return null
    var accounts = UsageLogic.listOrEmpty(provider.accounts)
    if (accounts.length > 1) return null
    var account = accounts.length ? accounts[0] : provider
    var trend = account.history ? UsageLogic.listOrEmpty(account.history.h24) : []
    return UsageLogic.listOrEmpty(account.windows).length > 0 && trend.length > 1 ? account : null
  }
  readonly property bool singleSpending: !!singleAccount && UsageLogic.spendingNow(singleAccount, nowSeconds, recentByAccount)

  // First-run setup (UsageLogic.setupWanted): the panel opens on Settings, which walks Sources, Providers
  // and Menu bar, then lands on Limits.
  readonly property bool setupWanted: UsageLogic.setupWanted(settings)
  onSetupWantedChanged: beginSetupIfWanted()
  function beginSetupIfWanted() {
    if (!setupWanted) return
    if (configForm.setupStep === 0) configForm.beginSetup()
    settingsReturnView = "limits"
    viewMode = "settings"
  }
  function hintShown(hintId) { return UsageLogic.hintShown(settings, hintId) }
  function dismissHint(hintId) { saveSettings({ hintsDismissed: UsageLogic.hintsDismissing(settings, hintId) }) }
  // Limits explains one part at a time, top to bottom: the next shows once the one above is dismissed.
  readonly property string limitsHint: {
    if (viewMode !== "limits") return ""
    var parts = [["accounts", accountOverview], ["forecast", forecastVisible], ["runway", runwayVisible]]
    for (var i = 0; i < parts.length; i++) if (parts[i][1] && hintShown(parts[i][0])) return parts[i][0]
    return ""
  }
  // Any limit card of the detail draws forecast dashes.
  readonly property bool forecastVisible: {
    for (var i = 0; i < limitCards.count; i++) {
      var card = limitCards.itemAt(i)
      if (card && card.forecastShown) return true
    }
    return false
  }

  function headlineFor(reading) {
    var empty = { text: "", urgent: false }
    var provider = reading
    if (!provider || String(provider.status) !== "ok") return empty
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
    open()
  }

  function showCosts() {
    viewMode = "costs"
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

  // Only Costs, and Settings → Costs with the sources the last scan found, read transcripts; Limits never
  // waits on a scan.
  readonly property bool costsShown: opened && (viewMode === "costs"
    || (configuring && (configForm.page === "costs" || configForm.page === "sources")))
  onCostsShownChanged: if (costsShown) costBackend.ensureLoaded()

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

  // Saved 1.x key paths follow the private folder to omarchy/quotatank (UsageLogic.legacyPathSettings), and the
  // source settings of 2.3 and older move to Settings → Sources (UsageLogic.migrateSources), in one save.
  // This runs as settings arrive, before the backends' first refresh starts.
  function moveLegacyPaths() {
    var entry = Object.assign({}, settings, UsageLogic.legacyPathSettings(settings))
    var migration = UsageLogic.migrateSources(entry)
    if (migration) {
      for (var key in migration.changes) {
        if (migration.changes[key] === null) delete entry[key]
        else entry[key] = migration.changes[key]
      }
    }
    if (JSON.stringify(entry) === JSON.stringify(settings)) return
    if (bar && bar.shell && typeof bar.shell.updateEntryInline === "function") bar.shell.updateEntryInline(moduleName, entry)
    settings = entry
  }
  onSettingsChanged: moveLegacyPaths()
  Component.onCompleted: { moveLegacyPaths(); beginSetupIfWanted() }

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

  // Runs after each successful refresh: a desktop notification per window that moved to a worse severity, at most
  // UsageLogic.MAX_LIMIT_NOTIFICATIONS of them and one that counts the rest.
  function checkLimitCrossings() {
    var readings = []
    for (var i = 0; i < root.providers.length; i++) {
      var provider = root.providers[i]
      // A stale reading repeats what another computer said before it stopped answering: "none" leaves it out,
      // so the level noted before stays and nothing crosses a threshold again when it answers.
      var stale = provider.stale === true
      var rows = UsageLogic.listOrEmpty(provider.windows)
      for (var j = 0; j < rows.length; j++) {
        var row = rows[j]
        readings.push({
          key: String(provider.id) + "|" + String(row.label || j),
          severity: stale ? "none" : windowSeverity(row),
          title: String(provider.name || provider.id) + " · " + String(row.label || "Usage limit"),
          remaining: UsageLogic.windowRemaining(row),
          mode: quotaModeFor(provider.id)
        })
      }
      var money = UsageLogic.spendable(provider)
      if (money !== null) {
        var level = stale ? "none" : moneySeverityOf(provider)
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
    var notifications = UsageLogic.limitNotifications(result.crossings)
    for (var k = 0; k < notifications.length; k++)
      Util.execArgv(["notify-send", "--app-name=Quotatank", "--urgency=" + (notifications[k].critical ? "critical" : "normal"),
        notifications[k].title, notifications[k].body])
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
    var absolute = clockText(window.resetsAt)
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

  // `showResets` false leaves the banked-reset count out, when the banked-reset card shows it.
  function creditsPrimary(credits, showResets) {
    if (!credits) return ""
    if (credits.remaining !== null && credits.remaining !== undefined)
      return UsageLogic.formatMoney(credits.remaining, credits.currency) + " remaining"
    if (credits.unlimited) return "Unlimited"
    if (credits.used !== null && credits.used !== undefined)
      return UsageLogic.formatMoney(credits.used, credits.currency) + " used"
    if (showResets !== false && credits.resetCreditsAvailable !== null && credits.resetCreditsAvailable !== undefined)
      return credits.resetCreditsAvailable + " reset credit" + (credits.resetCreditsAvailable === 1 ? "" : "s")
    return "Available"
  }

  function creditsDetail(credits, showResets) {
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
    if (showResets !== false && credits.resetCreditsAvailable !== null && credits.resetCreditsAvailable !== undefined)
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

  // A reading is stale once two refresh intervals pass without a new one, or the last refresh failed;
  // the chips fade by the same rule on the same clock.
  readonly property bool usageStale: UsageLogic.readingStale(nowMs, backend.lastSuccessAt, backend.refreshIntervalSec,
    backend.fetchError !== "", null)
  // Share of the time left until the next reading: 1 just after one, 0 when the next is due.
  readonly property real readingDrain: backend.nextRefreshAt <= 0 || backend.loading ? 0
    : clamp((backend.nextRefreshAt - nowMs) / (backend.refreshIntervalSec * 1000), 0, 1)

  function footerLeft() {
    if (viewMode === "costs") {
      if (costBackend.fetchError !== "") return costBackend.fetchError
      if (costBackend.lastSuccessAt > 0)
        return "Updated " + Qt.formatTime(new Date(costBackend.lastSuccessAt), "HH:mm")
      return costBackend.loading ? "Loading session history…" : "Open Costs to load session history"
    }
    if (backend.lastSuccessAt > 0 && usageStale) {
      var minutes = Math.max(1, Math.round((nowMs - backend.lastSuccessAt) / 60000))
      return "Last reading " + (minutes < 60 ? minutes + " min" : UsageLogic.formatDuration(minutes * 60)) + " ago · retrying"
    }
    if (backend.fetchError !== "") return backend.fetchError
    if (backend.lastSuccessAt > 0) return "Updated " + Qt.formatTime(new Date(backend.lastSuccessAt), tickTimeFormat)
    return backend.loading ? "Refreshing…" : "Waiting for first refresh"
  }

  // A countdown, written so it cannot be read as a clock time beside "Updated 14:56". Costs names its
  // sources there instead.
  function footerRight() {
    if (viewMode === "costs") return costsView.sourceSummary
    if (backend.loading || backend.nextRefreshAt <= 0) return ""
    var seconds = Math.max(0, Math.floor((backend.nextRefreshAt - nowMs) / 1000))
    if (seconds < 60) return "Next reading in " + Math.max(1, seconds) + " s"
    return "Next reading in " + Math.ceil(seconds / 60) + " min"
  }

  visible: UsageLogic.onScreen(setting("barScreens", "[]"), QsWindow.window ? QsWindow.window.screen : null)
  implicitWidth: percentageMode ? percentageGroup.implicitWidth : iconButton.implicitWidth
  implicitHeight: percentageMode ? percentageGroup.implicitHeight : iconButton.implicitHeight
  // Bar draws the open-panel mark at this width (otherwise it falls back to
  // 55% of the slot, which leaves the chips' outer ends unmarked).
  readonly property real openPanelIndicatorWidth: implicitWidth

  onProvidersChanged: ensureSelection()
  onSelectedProviderIdChanged: {
    selectedAccountId = ""
    Qt.callLater(latchDefaultAccount)
  }
  onOpenedChanged: if (opened) {
    nowMs = Date.now()
    // Until setup is done or skipped, opening the panel goes back to it, at the step it was left on.
    beginSetupIfWanted()
    latchDefaultAccount()
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
    if (panelFlick) panelFlick.contentY = 0
  }

  UsageBackend {
    id: backend
    settings: root.settings
    onRefreshed: {
      root.nowMs = Date.now()
      activityBackend.refresh()
      root.checkLimitCrossings()
      accountEventsTracker.track(Date.now() / 1000)
    }
  }

  UsageActivityBackend {
    id: activityBackend
    usageBackend: backend
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

  // omp's live feed: requests as they happen, with their accounts (OmpActivity.qml). Through a proxy
  // there is nothing of omp's to follow.
  OmpActivity {
    id: ompActivityHelper
    settings: root.settings
    status: backend.ompStatus
    computers: backend.computers
  }

  // A first open with nothing read yet shows placeholder blocks, but only once reading takes over a
  // second; a quick first reading never flashes them.
  property bool skeletonDue: false
  readonly property bool waitingForFirstReading: providers.length === 0 && backend.loading && backend.lastSuccessAt <= 0
  onWaitingForFirstReadingChanged: {
    skeletonDue = false
    if (waitingForFirstReading) skeletonTimer.restart()
    else skeletonTimer.stop()
  }
  Timer {
    id: skeletonTimer
    interval: 1000
    onTriggered: root.skeletonDue = root.waitingForFirstReading
  }

  // The panel's one clock: every second while the panel is open, and every 30 s while it is closed for
  // the chips (fading old readings, the reset countdown); a new reading sets it too.
  Timer {
    interval: 1000
    running: root.opened
    repeat: true
    triggeredOnStart: true
    onTriggered: root.nowMs = Date.now()
  }
  Timer {
    interval: 30000
    running: !root.opened && root.percentageMode
    repeat: true
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

  // ---- Menu bar chips ----
  Motion {
    id: motionTokens
    preference: String(root.setting("motion", "system"))
    panelOpen: root.opened
  }
  // The panel's Motion, as the UI contract names it. Children take `motion: root.motion` (qualified:
  // inside a child, a bare `motion` names its own property).
  readonly property alias motion: motionTokens

  // Several accounts in the bar: "dots" keeps one chip per provider with a dot per account, "chips"
  // gives each account its own chip (at most four per provider, within the bar's chip cap).
  readonly property string barAccountMode: String(setting("barAccountMode", "dots")) === "chips" ? "chips" : "dots"
  signal barLivePing(string providerId, string accountId)

  readonly property var barProviderMap: {
    var map = {}
    for (var i = 0; i < percentageProviders.length; i++) map[String(percentageProviders[i].id)] = percentageProviders[i]
    return map
  }
  readonly property var barChipEntries: UsageLogic.barChipEntries(root.percentageProviders, barAccountMode,
    function (provider) { return root.barAccountStateOf(provider) }, setting("extraKeys", "{}"), barMaxChips)
  onBarChipEntriesChanged: syncBarChips()

  // Keeps one row per chip key, moved and updated in place, so chips survive readings.
  function syncBarChips() {
    var wanted = barChipEntries
    var keys = wanted.map(function (entry) { return entry.key })
    UsageLogic.syncKeyedOrder({
      count: function() { return barChipModel.count },
      keyAt: function(index) { return barChipModel.get(index).chipKey },
      move: function(from, to) { barChipModel.move(from, to, 1) },
      insert: function(index, key) {
        var entry = wanted[keys.indexOf(key)]
        barChipModel.insert(index, { chipKey: key, providerId: entry.providerId, accountIndex: entry.accountIndex, initial: entry.initial })
      }
    }, keys)
    while (barChipModel.count > keys.length) barChipModel.remove(barChipModel.count - 1)
    for (var i = 0; i < wanted.length; i++) {
      var current = barChipModel.get(i)
      if (current.accountIndex !== wanted[i].accountIndex) barChipModel.setProperty(i, "accountIndex", wanted[i].accountIndex)
      if (current.initial !== wanted[i].initial) barChipModel.setProperty(i, "initial", wanted[i].initial)
    }
  }

  ListModel {
    id: barChipModel
    Component.onCompleted: root.syncBarChips()
  }

  // When a provider's reading was taken, for the hover card.
  function readingSeconds(provider) {
    var fetched = new Date(String(provider && provider.fetchedAt || "")).getTime()
    return isFinite(fetched) && fetched > 0 ? fetched / 1000 : backend.lastSuccessAt / 1000
  }

  Connections {
    target: root.ompActivity
    ignoreUnknownSignals: true
    function onRequest(event) {
      if (event) root.barLivePing(String(event.provider || ""), String(event.accountId || ""))
    }
  }

  // Hover card: opens 350 ms after the pointer settles on a chip with several accounts, closes 150 ms
  // after it leaves both the chip and the card, and stays out of the way while the panel is open. Only
  // the hovered chip builds the card's model, and only while the card shows; once it has faded out the
  // chip is let go.
  property Item hoverChip: null
  property Item hoverCandidate: null
  property bool hoverCardOpen: false
  property alias hoverCard: hoverCardSurface
  readonly property bool hoverCardShown: hoverCardSurface.open || hoverCardSurface.opacity > 0

  function chipHoverChanged(chip, hovered) {
    if (hovered && !opened) {
      hoverCandidate = chip
      hoverCloseTimer.stop()
      if (hoverCardOpen) hoverChip = chip
      else hoverOpenTimer.restart()
    } else if (hoverCandidate === chip) {
      hoverCandidate = null
      hoverOpenTimer.stop()
      if (hoverCardOpen) hoverCloseTimer.restart()
    }
  }

  function closeHoverCard() {
    hoverOpenTimer.stop()
    hoverCandidate = null
    hoverCardOpen = false
  }

  Timer {
    id: hoverOpenTimer
    interval: 350
    onTriggered: if (root.hoverCandidate && !root.opened) {
      root.hoverChip = root.hoverCandidate
      root.hoverCardOpen = true
    }
  }

  Timer {
    id: hoverCloseTimer
    interval: 150
    onTriggered: if (!root.hoverCandidate && !hoverCardHover.hovered) root.hoverCardOpen = false
  }

  PopupWindow {
    id: hoverCardWindow
    readonly property Item chip: root.hoverChip
    readonly property var chipWindow: chip ? chip.QsWindow.window : null
    property real anchorX: 0
    property real anchorY: 0
    visible: !!chip && !!chipWindow && (hoverCardSurface.open || hoverCardSurface.opacity > 0)
    color: "transparent"
    implicitWidth: Math.ceil(hoverCardSurface.implicitWidth)
    implicitHeight: Math.ceil(hoverCardSurface.implicitHeight)

    // Centred under the chip (over it on a bottom bar) and kept inside the bar's window, like Omarchy's
    // popup cards; the anchor's defaults slide it back on screen.
    function place() {
      if (!chip || !chipWindow) return
      var margin = Style.gapsOut
      var localX = chip.width / 2 - implicitWidth / 2
      var localY = root.bar && root.bar.position === "bottom" ? -implicitHeight - margin : chip.height + margin
      var point = chipWindow.contentItem.mapFromItem(chip, localX, localY)
      anchorX = Math.round(Math.max(margin, Math.min(point.x, chipWindow.width - implicitWidth - margin)))
      anchorY = Math.round(point.y)
    }

    anchor {
      window: hoverCardWindow.chipWindow
      rect.x: hoverCardWindow.anchorX
      rect.y: hoverCardWindow.anchorY
      rect.width: 1
      rect.height: 1
      onAnchoring: hoverCardWindow.place()
    }

    AccountHoverCard {
      id: hoverCardSurface
      objectName: "accountHoverCard"
      anchors.fill: parent
      open: root.hoverCardOpen && !root.opened && !!hoverCardWindow.chip
      model: hoverCardWindow.chip ? hoverCardWindow.chip.hoverModel : null
      motion: root.motion
      onOpacityChanged: if (opacity === 0 && !open) root.hoverChip = null
      quotaMode: hoverCardWindow.chip ? hoverCardWindow.chip.quotaMode : root.quotaMode
      warningThreshold: root.warningThreshold
      criticalThreshold: root.criticalThreshold
      fontFamily: root.fontFamily
      clockFormat: root.tickTimeFormat
      endSeconds: hoverCardWindow.chip ? root.readingSeconds(hoverCardWindow.chip.modelData) : 0
      barPosition: root.bar ? String(root.bar.position) : "top"

      HoverHandler {
        id: hoverCardHover
        onHoveredChanged: {
          if (hovered) hoverCloseTimer.stop()
          else if (!root.hoverCandidate && root.hoverCardOpen) hoverCloseTimer.restart()
        }
      }
    }
  }

  // One line of a chip: period tag, the value (its digits roll) and the reset time, spaced as one text.
  component ChipLine: Row {
    id: chipLine
    property string tag: ""
    property string value: ""
    property string suffix: ""
    property string valueName: ""
    property color color: root.foreground
    property int pixelSize: Style.font.bodySmall
    readonly property real spaceWidth: Math.round(lineMetrics.advanceWidth(" "))
    spacing: 0

    FontMetrics {
      id: lineMetrics
      font.family: root.fontFamily
      font.pixelSize: chipLine.pixelSize
      font.weight: Font.Medium
    }

    PlainText {
      objectName: chipLine.valueName + "Tag"
      visible: chipLine.tag !== ""
      anchors.baseline: chipValue.baseline
      rightPadding: chipLine.spaceWidth
      text: chipLine.tag
      color: chipLine.color
      font.family: root.fontFamily
      font.pixelSize: chipLine.pixelSize
      font.weight: Font.Medium
    }

    RollingNumber {
      id: chipValue
      objectName: chipLine.valueName
      text: chipLine.value
      color: chipLine.color
      font.family: root.fontFamily
      font.pixelSize: chipLine.pixelSize
      font.weight: Font.Medium
      motion: root.motion
    }

    PlainText {
      visible: chipLine.suffix !== ""
      anchors.baseline: chipValue.baseline
      text: " · " + chipLine.suffix
      color: chipLine.color
      font.family: root.fontFamily
      font.pixelSize: chipLine.pixelSize
      font.weight: Font.Medium
    }
  }

  Ui.BarIconButton {
    id: iconButton
    anchors.fill: parent
    visible: !root.percentageMode
    bar: root.bar
    text: "󱚣"
    active: root.alarming
    tooltipText: root.provider ? "Quotatank · " + root.provider.name
      + (UsageLogic.proxyPool(root.provider) ? "\n" + root.lastAccountTooltip(root.lastAccount(root.provider)) : "") : "Quotatank"
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
        id: chipRepeater
        // Rows come from UsageLogic.barChipEntries(root.percentageProviders, …), kept by syncBarChips().
        model: barChipModel

        delegate: Ui.WidgetButton {
          id: providerChip
          objectName: "barChip-" + chipKey
          required property string chipKey
          required property string providerId
          required property int accountIndex
          required property string initial
          // A chip outlives readings, so digits can roll and flashes fire once; its data follows the
          // latest reading of its provider.
          readonly property var modelData: root.barProviderMap[providerId]
            || ({ id: providerId, name: providerId, status: "none", windows: [] })
          readonly property var accounts: UsageLogic.listOrEmpty(modelData.accounts)
          readonly property bool multiAccount: accounts.length >= 2
          // Chips per account: this chip is one account of its provider.
          readonly property bool accountChip: accountIndex >= 0 && accountIndex < accounts.length
          // The provider's account state, shared with its tile, the Limits rows and the runway; with
          // used-up accounts hidden, that of the accounts the bar still shows.
          readonly property var accountState: multiAccount ? root.barAccountStateOf(modelData) : null
          readonly property string accountMode: accountState ? accountState.mode : "single"
          readonly property var counted: accountState ? accountState.counted : []
          readonly property bool countedAccount: accountChip && counted.indexOf(accountIndex) !== -1

          readonly property var lastAccount: root.lastAccount(modelData)
          // Every account read through a proxy, which rotates them.
          readonly property bool throughProxy: UsageLogic.proxyPool(modelData)
          // A proxy provider with one account shows the pool's summary when its last request is unknown.
          readonly property bool usingPoolQuota: throughProxy && !multiAccount && !lastAccount.reading
          // The account whose figure the chip shows: its own on a per-account chip, else the counted
          // account with the least headroom on the chip's window; -1 shows the provider's own reading.
          readonly property int valueIndex: accountChip ? accountIndex
            : !multiAccount ? -1
            : UsageLogic.barValueIndex(modelData, counted, limits.top)
          readonly property var reading: valueIndex >= 0 ? accounts[valueIndex]
            : throughProxy && lastAccount.reading ? lastAccount.reading : modelData
          readonly property var limits: root.barLimitsFor(modelData.id)
          readonly property string quotaMode: root.quotaModeFor(modelData.id)
          readonly property var failure: accountChip ? reading : modelData
          readonly property bool failed: String(failure.status) === "error"
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
            ? (throughProxy ? "—" : "") : UsageLogic.formatPercent(shownValue) + "%"
          readonly property string severity: UsageLogic.severity(
            reading, root.warningThreshold, root.criticalThreshold, remainingValue)
          readonly property string moneySeverity: moneyChip ? root.moneySeverityOf(reading) : "none"
          readonly property var secondaryRemaining: windowStacked
            ? UsageLogic.exactRemainingForWindow(reading, secondaryWindow) : null
          readonly property string secondaryText: secondaryRemaining === null ? "—"
            : UsageLogic.formatPercent(providerChip.quotaMode === "Remaining"
              ? secondaryRemaining : UsageLogic.usedFromRemaining(secondaryRemaining)) + "%"
          readonly property string topTag: root.barShowPeriods ? UsageLogic.barTagFor(reading, topWindow, true) : ""
          readonly property string bottomTag: root.barShowPeriods ? UsageLogic.windowShortLabel(secondaryWindow) : ""
          readonly property string topReset: root.barShowResets
            ? root.barResetText(UsageLogic.windowRowFor(reading, topWindow, true)) : ""
          readonly property string bottomReset: root.barShowResets && windowStacked
            ? root.barResetText(UsageLogic.windowRowFor(reading, secondaryWindow, false)) : ""
          readonly property string percentTag: topTag !== "" || !moneyChip || !root.barShowPeriods ? topTag
            : UsageLogic.rowPeriodTag(UsageLogic.windowRowFor(reading, topWindow, true))
          readonly property string percentLine: (percentTag ? percentTag + " " : "") + shownText + (topReset ? " · " + topReset : "")
          readonly property string topText: failed ? UsageLogic.errorReasonLabel(failure.errorKind)
            : moneyChip ? moneyShown.text : percentLine
          readonly property string bottomText: moneyChip ? percentLine
            : (bottomTag ? bottomTag + " " : "") + secondaryText + (bottomReset ? " · " + bottomReset : "")
          // The same lines in parts: the value rolls, the tag and reset time stay put.
          readonly property var topParts: failed ? { tag: "", value: topText, suffix: "" }
            : moneyChip ? { tag: "", value: moneyShown.text, suffix: "" }
            : { tag: percentTag, value: shownText, suffix: topReset }
          readonly property var bottomParts: moneyChip ? { tag: percentTag, value: shownText, suffix: topReset }
            : { tag: bottomTag, value: secondaryText, suffix: bottomReset }
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

          // An old reading fades the chip: the last refresh failed, or it is two intervals old.
          readonly property bool stale: UsageLogic.readingStale(root.nowMs, backend.lastSuccessAt,
            backend.refreshIntervalSec, backend.fetchError !== "", reading)
          readonly property var strip: multiAccount && !accountChip ? UsageLogic.barAccountStrip(modelData, accountState, {
            selector: topWindow, nowSeconds: root.nowSeconds, stale: stale, extraKeys: root.setting("extraKeys", "{}") }) : null
          // A provider with several accounts gets the hover card instead of the plain tooltip; its model is
          // built only while this chip's card shows.
          readonly property bool hoverCardEligible: multiAccount
          readonly property var hoverModel: root.hoverChip === providerChip && multiAccount && root.hoverCardShown
            ? UsageLogic.barHoverModel(modelData, accountState, { nowSeconds: root.nowSeconds,
              extraKeys: root.setting("extraKeys", "{}"), readAtSeconds: root.readingSeconds(modelData), stale: stale,
              formatClock: root.clockText })
            : null
          readonly property string plainTooltip: failed
            ? String(modelData.name || modelData.id) + " · " + root.errorBody(failure)
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
            + (throughProxy ? "\n" + root.lastAccountTooltip(lastAccount) : "")
            + (usingPoolQuota ? "\nQuota shown: account with the most remaining capacity." : "")

          // One-shot flash: the same account's window moved to a worse severity, or it reset (the rule
          // Limits notices use). Seeded at creation, so existing limits never flash on startup; a chip that
          // moves to another account or window only seeds again. Reduced motion skips it: the colour
          // already says it.
          property var flashSeed: null
          readonly property var topRow: failed || moneyChip ? null : UsageLogic.windowRowFor(reading, topWindow, true)
          readonly property var flashReading: ({ key: String(reading && reading.accountId || "") + "|" + topWindow,
            severity: topSeverity, used: topRow ? UsageLogic.usedForWindow(reading, topWindow) : null,
            resetsAt: topRow ? topRow.resetsAt : null })
          onFlashReadingChanged: {
            var kind = UsageLogic.barFlashKind(flashSeed, flashReading, Date.now() / 1000)
            flashSeed = flashReading
            if (kind !== "" && !root.motion.reduced) flash(kind)
          }
          Component.onCompleted: flashSeed = flashReading

          // Flashes so far and the last kind, for the contract tests.
          property int flashes: 0
          property string lastFlash: ""
          function flash(kind) {
            flashes++
            lastFlash = kind
            flashFill.tint = kind === "reset" ? Commons.Color.accent : root.urgent
            flashAnimation.restart()
          }

          bar: root.bar
          text: ""
          labelVisible: false
          hasVisualContent: true
          fixedWidth: providerChipContent.implicitWidth + Style.space(10)
          active: stressed || failed
          horizontalMargin: 0
          tooltipText: hoverCardEligible ? "" : plainTooltip
          Accessible.role: Accessible.Button
          Accessible.name: multiAccount
            ? UsageLogic.barAccessibleName(modelData, accountState, { selector: topWindow, quotaMode: quotaMode,
              extraKeys: root.setting("extraKeys", "{}"), accountIndex: accountChip ? accountIndex : -1, strip: strip })
            : plainTooltip.split("\n").join(", ")
          onPressed: function(buttonCode) {
            root.closeHoverCard()
            root.handleProviderChipPress(String(providerChip.modelData.id), buttonCode)
          }
          onTooltipHoveredChanged: root.chipHoverChanged(providerChip, tooltipHovered && hoverCardEligible)

          // One ring per live request from the dot of the account that served it: omp names a native
          // login by its own id, so either id finds the account.
          Connections {
            target: root
            function onBarLivePing(pingProvider, pingAccount) {
              if (pingProvider !== String(providerChip.modelData.id) || providerChip.strip === null) return
              var index = -1
              for (var i = 0; i < providerChip.accounts.length; i++)
                if (UsageLogic.accountAnswersTo(providerChip.accounts[i], pingAccount)) index = i
              accountDots.ping(index)
            }
          }

          // Background of the one-shot flash; the bar shows through between flashes.
          Rectangle {
            id: flashFill
            property color tint: root.urgent
            anchors.fill: parent
            anchors.topMargin: Style.space(3)
            anchors.bottomMargin: Style.space(3)
            radius: Style.cornerRadius
            color: Qt.rgba(tint.r, tint.g, tint.b, 0.32)
            opacity: 0
            visible: flashAnimation.running

            OpacityAnimator {
              id: flashAnimation
              target: flashFill
              from: 1
              to: 0
              duration: root.motion.duration(root.motion.flash)
              easing.type: Easing.OutCubic
            }
          }

          Row {
            id: providerChipContent
            x: Math.round((parent.width - width) / 2)
            y: Math.round((parent.height - height) / 2)
            spacing: Style.spacing.sm
            opacity: providerChip.stale ? 0.5 : 1

            Behavior on opacity {
              OpacityAnimator { duration: root.motion.duration(root.motion.row); easing.type: Easing.InOutCubic }
            }

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

              PlainText {
                anchors.centerIn: parent
                visible: providerMarkImage.status !== Image.Ready
                text: UsageLogic.providerMark(String(providerChip.modelData.id))
                color: providerChip.contentColor
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            // Chips per account: the account's initial, underlined on the account the chip counts.
            Item {
              id: accountInitial
              objectName: "barAccountInitial"
              readonly property bool counted: providerChip.countedAccount
              visible: providerChip.accountChip
              y: Math.round((parent.height - height) / 2)
              width: Math.ceil(initialLabel.implicitWidth)
              height: Math.ceil(initialLabel.implicitHeight)

              PlainText {
                id: initialLabel
                text: providerChip.initial
                color: providerChip.topColor
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.weight: Font.DemiBold
              }

              Rectangle {
                objectName: "barAccountUnderline"
                visible: accountInitial.counted
                y: Math.round(initialLabel.baselineOffset + Style.space(2))
                width: parent.width
                height: Math.max(1, Style.spacing.hairline)
                color: providerChip.topColor
              }
            }

            ChipLine {
              visible: !providerChip.stacked
              y: Math.round((parent.height - height) / 2)
              valueName: "barAccountRemaining"
              tag: providerChip.topParts.tag
              value: providerChip.topParts.value
              suffix: providerChip.topParts.suffix
              color: providerChip.topColor
              pixelSize: Style.font.bodySmall
            }

            // Two caption lines, twelve pixels apart, so the pair fits the bar.
            Column {
              visible: providerChip.stacked
              y: Math.round((parent.height - height) / 2)
              spacing: 12 - topLine.height

              ChipLine {
                id: topLine
                valueName: "barAccountRemainingTop"
                tag: providerChip.topParts.tag
                value: providerChip.topParts.value
                suffix: providerChip.topParts.suffix
                color: providerChip.topColor
                pixelSize: Style.font.caption
              }

              ChipLine {
                valueName: "barAccountRemainingBottom"
                tag: providerChip.bottomParts.tag
                value: providerChip.bottomParts.value
                suffix: providerChip.bottomParts.suffix
                color: providerChip.bottomColor
                pixelSize: Style.font.caption
              }
            }

            AccountDots {
              id: accountDots
              objectName: "barAccountDots"
              visible: providerChip.strip !== null
              y: Math.round((parent.height - height) / 2)
              strip: providerChip.strip
              mode: providerChip.accountMode
              stale: providerChip.stale
              motion: root.motion
              foreground: root.foreground
              urgent: root.urgent
              accent: Commons.Color.accent
              dim: root.dim
              fontFamily: root.fontFamily
              fontSize: providerChip.stacked ? Style.font.caption : Style.font.bodySmall
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
        // Up/down walks the account rows while there are some; past either end it scrolls.
        if (dy !== 0 && !(root.viewMode === "limits" && root.accountOverview && root.moveAccountSelection(dy))) {
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

              PlainText {
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
              motion: root.motion
              onViewRequested: function(value) { root.viewMode = value }
              onProviderRequested: function(value) { root.selectProviderId(value) }
            }

            PlainText {
              width: parent.width
              text: {
                if (root.viewMode === "costs")
                  return costBackend.loading ? "Loading session history…" : ""
                var context = root.accountOverview ? "" : root.heroMeta(root.provider)
                if (root.providers.length === 1 && root.provider)
                  context = root.provider.name + (context ? " · " + context : "")
                return context + (backend.loading ? (context ? " · " : "") + "Refreshing…" : "")
              }
              visible: text !== ""
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            Item {
              width: parent.width
              visible: root.viewMode === "limits" && root.headline.text !== ""
              implicitHeight: Math.max(headlineText.implicitHeight, singleTrend.visible ? singleTrend.implicitHeight : 0)

              PlainText {
                id: headlineText
                objectName: "limitsHeadline"
                anchors.left: parent.left
                anchors.right: singleTrend.visible ? singleTrend.left : parent.right
                anchors.rightMargin: singleTrend.visible ? Style.spacing.lg : 0
                anchors.verticalCenter: parent.verticalCenter
                text: root.headline.text
                color: root.headline.urgent ? root.urgent : root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.heading
                font.bold: true
                wrapMode: Text.WordWrap
              }

              Row {
                id: singleTrend
                objectName: "singleTrend"
                visible: !!root.singleAccount
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.spacing.md

                PlainText {
                  objectName: "singleSpending"
                  visible: root.singleSpending
                  anchors.verticalCenter: parent.verticalCenter
                  text: "spending now"
                  color: Commons.Color.accent
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                Sparkline {
                  objectName: "singleSparkline"
                  anchors.verticalCenter: parent.verticalCenter
                  width: Style.space(52)
                  height: Style.space(18)
                  values: root.singleAccount && root.singleAccount.history ? UsageLogic.listOrEmpty(root.singleAccount.history.h24) : []
                  endSeconds: root.readingSeconds(root.provider)
                  lineColor: root.singleSpending ? Commons.Color.accent : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.5)
                  dotColor: root.singleSpending ? Commons.Color.accent : root.foreground
                  guideColor: root.foreground
                  fontFamily: root.fontFamily
                  clockFormat: root.tickTimeFormat
                  motion: root.motion
                }
              }
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
            usagePayload: backend.payload
            usageLoading: backend.loading
            costSources: costBackend.payload ? UsageLogic.listOrEmpty(costBackend.payload.sources) : []
            costModels: costBackend.payload ? UsageLogic.listOrEmpty(costBackend.payload.models) : []
            motion: root.motion
            onSetupRequested: function(entry, action) { root.startSetup(entry, action) }
            onSetupFinished: root.viewMode = "limits"
            onChangeRequested: function(values) { root.saveSettings(values) }
            onCloseRequested: root.leaveSettings()
            onRevealRequested: function(item) {
              settingsRevealTimer.item = item
              settingsRevealTimer.restart()
            }
          }

          EventNotice {
            id: eventNotice
            objectName: "eventNotice"
            width: parent.width
            shown: root.viewMode === "limits" && root.noticeText !== ""
            text: root.noticeText
            foreground: root.foreground
            accent: Commons.Color.accent
            fontFamily: root.fontFamily
            cardRadius: root.usageCardRadius
            motion: root.motion
            onDismissed: root.accountEvents.dismiss()
          }

          // Once, after updating from 2.3 or older with omp read from another computer's dashboard.
          EventNotice {
            objectName: "sourcesNotice"
            width: parent.width
            shown: root.viewMode === "limits" && root.settings && root.settings.sourcesNotice === "ompRemote"
            text: "omp on another computer now uses SSH. Add that computer under Settings → Sources."
            actionText: "Open Sources"
            foreground: root.foreground
            accent: Commons.Color.accent
            fontFamily: root.fontFamily
            cardRadius: root.usageCardRadius
            motion: root.motion
            onDismissed: root.saveSettings({ sourcesNotice: "" })
            onActionRequested: {
              root.saveSettings({ sourcesNotice: "" })
              root.showSettings("sources")
            }
          }

          Column {
            id: accountOverviewSection
            visible: root.viewMode === "limits" && root.accountOverview
            width: parent.width
            spacing: Style.spacing.lg

            HintLine {
              objectName: "hint-accounts"
              width: parent.width
              hintId: "accounts"
              shown: root.limitsHint === "accounts"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onDismissed: function(hintId) { root.dismissHint(hintId) }
            }

            AccountList {
              id: accountListView
              objectName: "accountList"
              width: parent.width
              providerId: root.provider ? String(root.provider.id) : ""
              accounts: root.proxyAccounts
              names: root.accountNames
              accountState: root.providerState
              selectedId: root.selectedAccount ? String(root.selectedAccount.accountId) : ""
              nowSeconds: root.nowSeconds
              events: root.accountEvents.eventLog
              resetsActionable: !resetBackend.active && !resetBackend.busy
              useBusyId: root.accountEvents.useBusyId
              headerText: UsageLogic.accountModeText(root.provider, root.accountMode)
              quotaMode: root.selectedQuotaMode
              warningThreshold: root.warningThreshold
              criticalThreshold: root.criticalThreshold
              foreground: root.foreground
              urgent: root.urgent
              fontFamily: root.fontFamily
              clockFormat: root.tickTimeFormat
              cardRadius: root.usageCardRadius
              motion: root.motion
              onAccountSelected: function(accountId) { root.selectAccount(accountId) }
              onUseRequested: function(accountId) { root.useAccount(accountId) }
              onResetRequested: function(accountId) { root.resetAccount(accountId) }
            }
          }

          // A slow first reading: placeholder blocks where the tiles and cards will be.
          Column {
            objectName: "limitsSkeleton"
            visible: root.viewMode === "limits" && root.skeletonDue && root.providers.length === 0
            width: parent.width
            spacing: Style.spacing.lg

            Repeater {
              model: [{ width: 1, height: 40 }, { width: 0.55, height: 14 }, { width: 1, height: 74 }, { width: 1, height: 74 }]

              Rectangle {
                required property var modelData
                width: Math.round(parent.width * modelData.width)
                height: Style.space(modelData.height)
                radius: root.usageCardRadius
                color: root.alpha(root.foreground, 0.06)
              }
            }
          }

          PlainText {
            visible: root.viewMode === "limits" && root.providers.length === 0 && (!backend.loading || root.skeletonDue)
            width: parent.width
            topPadding: root.skeletonDue ? 0 : Style.spacing.huge
            bottomPadding: root.skeletonDue ? 0 : Style.spacing.huge
            text: backend.loading
              ? "Reading your limits…"
              : "Nothing to show yet. Sign in to a provider's CLI or app, or turn one on under Settings → Providers."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: root.skeletonDue ? Style.font.caption : Style.font.body
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
          }

          // What the selected account (or the provider itself) says: header, hero line, limits, runway,
          // history and tokens. Choosing another account cross-fades it in from the side of that row.
          Column {
            id: detailColumn
            objectName: "accountDetail"
            visible: root.viewMode === "limits" && !!root.detail
            width: parent.width
            spacing: Style.spacing.xxl

            ParallelAnimation {
              id: detailSwapAnimation
              OpacityAnimator {
                target: detailColumn
                from: 0
                to: 1
                duration: root.motion.duration(root.motion.row)
                easing.type: Easing.OutCubic
              }
              XAnimator {
                target: detailColumn
                from: root.detailSlideFrom
                to: 0
                duration: root.motion.duration(root.motion.row)
                easing.type: Easing.OutCubic
              }
            }

            Ui.PanelSeparator {
              visible: root.accountOverview && !!root.selectedAccount
              foreground: root.foreground
            }

            Column {
              visible: root.accountOverview && !!root.selectedAccount
              width: parent.width
              spacing: Style.spacing.md

              Row {
                objectName: "accountDetailHeader"
                width: parent.width

                PlainText {
                  id: detailName
                  objectName: "accountDetailName"
                  width: Math.min(implicitWidth, parent.width * 0.6)
                  text: root.selectedAccount ? root.accountNames[root.selectedAccountIndex] || "" : ""
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                  elide: Text.ElideRight
                }

                PlainText {
                  objectName: "accountDetailMeta"
                  width: Math.max(0, parent.width - detailName.width)
                  anchors.baseline: detailName.baseline
                  text: {
                    var account = root.selectedAccount
                    if (!account) return ""
                    var parts = []
                    var plan = account.plan || account.planType ? UsageLogic.accountPlanLabel(account) : ""
                    if (plan !== "" && plan !== detailName.text) parts.push(plan)
                    if (root.providerState && root.providerState.inUse[root.selectedAccountIndex] === true) parts.push("in use")
                    var kind = UsageLogic.accountSourceKind(account)
                    if (kind === "omp") parts.push("from omp")
                    else if (kind === "computer") parts.push("on " + String(account.computer.name || ""))
                    else if (kind === "proxy") parts.push("through " + String(account.proxy.name || "CLIProxyAPI"))
                    else if (account.standIn && account.standIn.name)
                      parts.push((UsageLogic.readingProxy(account) ? "read through " : "read on ") + String(account.standIn.name))
                    return parts.length > 0 ? " · " + parts.join(" · ") : ""
                  }
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  elide: Text.ElideRight
                }
              }

              PlainText {
                objectName: "accountHeadline"
                width: parent.width
                visible: text !== ""
                text: root.accountHeadline.text
                color: root.accountHeadline.urgent ? root.urgent : root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.heading
                font.bold: true
                wrapMode: Text.WordWrap
              }
            }

            Ui.BorderSurface {
              id: errorCard
              visible: !!root.detail && root.detail.status === "error"
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

                PlainText {
                  width: parent.width
                  text: UsageLogic.errorTitle(root.detail)
                  color: root.urgent
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                  wrapMode: Text.WordWrap
                }

                PlainText {
                  width: parent.width
                  text: root.errorBody(root.detail)
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  wrapMode: Text.WordWrap
                }

                // The same one-click fix Settings offers, right where the failure is reported. An account
                // of several signs in from its own folder, so only the provider's own failure offers it.
                Ui.Button {
                  id: errorSetupButton
                  objectName: "errorSetupButton"
                  readonly property var entry: root.accountOverview || !root.provider ? null : UsageLogic.localProvider(root.provider.id)
                  readonly property var action: UsageLogic.setupActionFor(entry, root.provider, backend.payload, backend.mainComputer)
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

            PlainText {
              objectName: "detailNotice"
              visible: text !== ""
              width: parent.width
              text: {
                var reading = root.detail
                if (!reading || reading.status === "error") return ""
                var notice = String(reading.notice || "")
                if (notice !== "") return notice
                if (!root.accountOverview) return ""
                if (reading.status === "disabled") return "This account is paused in CLIProxyAPI."
                if (reading.status !== "ok") return "Quota unavailable"
                if (UsageLogic.listOrEmpty(reading.windows).length === 0 && UsageLogic.spendable(reading) === null)
                  return "No subscription limits reported."
                return ""
              }
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
            }

            Ui.PanelSeparator {
              visible: !root.accountOverview && (balanceCard.visible || limitsSection.visible || creditsSection.visible)
              foreground: root.foreground
            }

            BalanceCard {
              id: balanceCard
              visible: !!root.detail && root.detail.status === "ok" && UsageLogic.spendable(root.detail) !== null
              width: parent.width
              provider: visible ? root.detail : null
            }

            Column {
              id: limitsSection
              objectName: "limitsSection"
              visible: !!root.detail && root.detail.status === "ok" && limitCardModel.count > 0
              width: parent.width
              spacing: Style.spacing.lg

              HintLine {
                objectName: "hint-forecast"
                width: parent.width
                hintId: "forecast"
                shown: root.limitsHint === "forecast"
                foreground: root.foreground
                fontFamily: root.fontFamily
                onDismissed: function(hintId) { root.dismissHint(hintId) }
              }

              Repeater {
                id: limitCards
                model: limitCardModel

                LimitCard {
                  required property string cardKey
                  readonly property var row: root.detailWindowFor(cardKey)
                  objectName: "limitCard-" + (row ? String(row.id || row.label || "") : "")
                  width: limitsSection.width
                  window: row
                  severity: root.windowSeverity(row)
                  resetLabel: root.resetText(row)
                  quotaMode: root.selectedQuotaMode
                  foreground: root.foreground
                  urgent: root.urgent
                  providerColor: root.providerColors ? UsageLogic.providerAccent(String(root.provider ? root.provider.id : ""), root.foreground) : root.foreground
                  dim: root.dim
                  fontFamily: root.fontFamily
                  cardRadius: root.usageCardRadius
                  nowSeconds: root.nowSeconds
                  clockFormat: root.tickTimeFormat
                  warningThreshold: root.warningThreshold
                  criticalThreshold: root.criticalThreshold
                  motion: root.motion
                }
              }
            }

            HintLine {
              objectName: "hint-runway"
              width: parent.width
              hintId: "runway"
              shown: root.limitsHint === "runway"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onDismissed: function(hintId) { root.dismissHint(hintId) }
            }

            RunwayCard {
              id: runwayCard
              objectName: "runwayCard"
              visible: root.runwayVisible
              width: parent.width
              runway: root.runway
              names: root.runwayNames
              counted: root.accountOverview ? root.countedIndexes : [0]
              poolText: root.runway && root.provider ? UsageLogic.poolLine(root.provider.pool, root.runway.window) : ""
              nowSeconds: root.nowSeconds
              clockFormat: root.tickTimeFormat
              foreground: root.foreground
              urgent: root.urgent
              fontFamily: root.fontFamily
              cardRadius: root.usageCardRadius
              motion: root.motion
            }

            // The detail's banked resets when no account row carries them: what is left, when the next one
            // expires, and the button that opens the confirmation.
            Ui.BorderSurface {
              id: resetCard
              objectName: "bankedResetCard"
              readonly property var reading: root.detail
              readonly property bool actionable: UsageLogic.accountResetActionable(reading)
              // With account rows, a reading through a proxy carries its resets on its row; a single reading
              // standing in through a proxy has no row, so they show here.
              visible: !!reading && !(root.accountOverview && UsageLogic.readingProxy(reading))
                && UsageLogic.accountResetShown(reading) && UsageLogic.accountResetCount(reading) > 0
              width: parent.width
              implicitHeight: resetCardContent.implicitHeight + contentTopInset + contentBottomInset
              color: Style.normalFillFor(root.foreground, Commons.Color.accent, root.urgent)
              borderSpec: Border.controlSpec("normal", root.foreground, Commons.Color.accent, root.urgent)
              padding: Style.spacing.xxl
              radius: root.usageCardRadius

              Item {
                id: resetCardContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: resetCard.contentLeftInset
                anchors.rightMargin: resetCard.contentRightInset
                anchors.topMargin: resetCard.contentTopInset
                implicitHeight: Math.max(resetCardText.implicitHeight, resetApply.visible ? resetApply.implicitHeight : 0)

                Column {
                  id: resetCardText
                  anchors.left: parent.left
                  anchors.right: resetApply.visible ? resetApply.left : parent.right
                  anchors.rightMargin: resetApply.visible ? Style.spacing.lg : 0
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.spacing.xs

                  PlainText {
                    objectName: "bankedResetLabel"
                    width: parent.width
                    text: UsageLogic.accountResetLabel(resetCard.reading)
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                    elide: Text.ElideRight
                  }

                  PlainText {
                    objectName: "bankedResetDetail"
                    visible: text !== ""
                    width: parent.width
                    text: root.bankedResetDetail(resetCard.reading)
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }
                }

                Ui.Button {
                  id: resetApply
                  objectName: "bankedResetApply"
                  visible: resetCard.actionable
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  text: "Apply…"
                  bordered: true
                  focusable: true
                  enabled: !resetBackend.active && !resetBackend.busy
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  tooltipText: "Review the reset before it is spent"
                  onClicked: root.resetDetail()
                }
              }
            }

            Column {
              id: creditsSection
              visible: !!root.detail && root.detail.status === "ok" && !!root.detail.credits && !balanceCard.visible
                && (UsageLogic.creditsHaveFunds(root.detail.credits) || !resetCard.visible)
              width: parent.width
              spacing: Style.spacing.lg

              UsageDisclosure {
                id: creditsToggle
                width: parent.width
                foreground: root.foreground
                fontFamily: root.fontFamily
                text: root.detail && root.detail.credits
                  ? String(root.detail.credits.label || "Credits") : "Credits"
              }

              CreditsCard {
                width: parent.width
                credits: root.detail ? root.detail.credits : null
                showResets: !resetCard.visible
                visible: creditsToggle.checked
              }
            }
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
            motion: root.motion
            ompActivity: root.ompActivity
            heatmapHintShown: root.hintShown("heatmap")
            onHintDismissed: function(hintId) { root.dismissHint(hintId) }
            onPeriodRequested: function(days) { costBackend.selectPeriod(days) }
            onMenuClosed: Qt.callLater(function() {
              if (root.opened && !root.configuring && !resetBackend.active)
                keyCatcher.forceActiveFocus()
            })
          }

          // One quiet pointer to providers set up here but not monitored; it goes away once each is
          // monitored or ignored under Settings → Providers.
          PlainText {
            objectName: "foundProvidersLine"
            visible: root.viewMode === "limits" && root.foundProviders.length > 0
            width: parent.width
            text: UsageLogic.foundSummary(root.foundProviders) + " · Set up"
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

          // The rule above the footer drains, in accent, until the next reading is due.
          Ui.PanelSeparator {
            visible: !root.configuring
            foreground: root.foreground

            Rectangle {
              objectName: "readingDrain"
              visible: root.viewMode === "limits" && root.readingDrain > 0 && !root.usageStale
              height: parent.height
              width: Math.round(parent.width * root.readingDrain)
              color: Commons.Color.accent
            }
          }

          Item {
            visible: !root.configuring
            width: parent.width
            implicitHeight: Math.max(footerLeft.implicitHeight, footerRight.implicitHeight)

            PlainText {
              id: footerLeft
              objectName: "footerLeft"
              HoverHandler { id: footerHover }
              Ui.PanelToolTip {
                visible: footerHover.hovered && (root.viewMode === "costs" ? costBackend.lastSuccessAt > 0
                  : root.usageStale && backend.fetchError !== "" && backend.lastSuccessAt > 0)
                text: root.viewMode === "costs"
                  ? "Updated " + Qt.formatDateTime(new Date(costBackend.lastSuccessAt), "MMM d, HH:mm:ss")
                    + (costBackend.payload && Number(costBackend.payload.scanDurationMs) > 0
                      ? " · Scan " + costBackend.payload.scanDurationMs + "ms" : "")
                  : backend.fetchError
                fontFamily: root.fontFamily
              }
              anchors.left: parent.left
              anchors.right: footerRight.left
              anchors.rightMargin: Style.spacing.controlGap
              text: root.footerLeft()
              color: (root.viewMode === "costs" ? costBackend.fetchError !== "" : root.usageStale)
                ? root.urgent : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }

            PlainText {
              id: footerRight
              objectName: "footerRight"
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

        PlainText {
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

        PlainText {
          id: moneyFigure
          anchors.right: moneyUnit.left
          anchors.rightMargin: Style.spacing.sm
          text: moneyCard.view ? moneyCard.view.text : moneyCard.money(moneyCard.amount)
          color: moneyCard.stressed ? root.urgent : root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.heading
          font.bold: true
        }

        PlainText {
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
        objectName: "moneyMeter"
        visible: moneyCard.share !== null
        width: parent.width
        height: Style.space(12)
        value: moneyCard.share === null ? 0 : moneyCard.share / 100
        fillColor: moneyCard.stressed ? root.urgent
          : root.providerColors ? UsageLogic.providerAccent(String(moneyCard.provider ? moneyCard.provider.id : ""), root.foreground) : root.foreground
        trackColor: root.alpha(root.foreground, 0.14)
        motion: root.motion
      }

      PlainText {
        width: parent.width
        text: moneyCard.sourceLine()
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      PlainText {
        visible: text !== ""
        width: parent.width
        text: moneyCard.spendLine()
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      PlainText {
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
    property bool showResets: true
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

      PlainText {
        width: parent.width
        text: root.creditsPrimary(creditsCard.credits, creditsCard.showResets)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
        elide: Text.ElideRight
      }

      PlainText {
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
        objectName: "creditsMeter"
        visible: creditsCard.hasMeter
        width: parent.width
        value: creditsCard.hasMeter
          ? UsageLogic.sideOfUsed(Number(creditsCard.credits.used) / Number(creditsCard.credits.limit) * 100, root.selectedQuotaMode) / 100 : 0
        fillColor: root.foreground
        trackColor: root.alpha(root.foreground, 0.14)
        motion: root.motion
      }

      PlainText {
        visible: text !== ""
        width: parent.width
        text: root.creditsDetail(creditsCard.credits, creditsCard.showResets)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }
}
