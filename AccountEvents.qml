import QtQuick
import qs.Commons
import "UsageLogic.js" as UsageLogic

// What changed for accounts between two readings, and the Use command. The newest change becomes a
// notice until it is dismissed, or until the panel closes after showing it; rows mention recent
// switches and resets. Use asks Omarchy to start new sessions with another login, then a refresh shows
// the change; the row's button spins until the reading says so, five seconds at most.
Item {
  id: root

  visible: false

  // The latest provider readings (UsageBackend.providers).
  property var providers: []
  property real warningThreshold: 25
  property bool panelOpen: false
  // Runs an argv without a shell. Tests swap in a recorder; nothing else replaces it.
  property var runArgv: function(argv) { Util.execArgv(argv) }

  property var eventState: ({})
  // Newest switch or reset per "<provider>@<accountId>": {kind, at}.
  property var eventLog: ({})
  property var notice: null
  property bool noticeSeen: false
  property var dismissed: []
  property string useBusyId: ""
  property var pendingUse: null

  signal refreshRequested()

  // Called after every successful reading.
  function track(nowSeconds) {
    var result = UsageLogic.accountEvents(eventState, providers, nowSeconds, warningThreshold)
    eventState = result.state
    if (pendingUse) {
      var accounts = UsageLogic.providerAccounts(UsageLogic.readingFor(providers, pendingUse.provider))
      for (var a = 0; a < accounts.length; a++)
        if (String(accounts[a].accountId) === pendingUse.accountId && accounts[a].active === true) useBusyId = ""
    }
    if (result.events.length === 0) return
    var log = Object.assign({}, eventLog)
    for (var i = 0; i < result.events.length; i++) {
      var event = result.events[i]
      if (event.accountId !== "" && (event.kind === "switch" || event.kind === "reset"))
        log[event.provider + "@" + event.accountId] = { kind: event.kind, at: event.at }
    }
    eventLog = log
    var newest = Object.assign({}, result.events[result.events.length - 1])
    if (dismissed.indexOf(newest.id) >= 0) return
    newest.manual = !!pendingUse && newest.kind === "switch" && pendingUse.provider === newest.provider
      && pendingUse.accountId === newest.accountId && newest.at - pendingUse.at < 120
    if (newest.manual) pendingUse = null
    notice = newest
    noticeSeen = panelOpen
  }

  function dismiss() {
    if (!notice) return
    dismissed = dismissed.concat([notice.id]).slice(-20)
    notice = null
    noticeSeen = false
  }

  // Starts new sessions of `providerId` with `account`; false when that is not possible now.
  function use(providerId, account, mode, proxyMode) {
    if (useBusyId !== "" || !UsageLogic.accountCanUse(account, mode, proxyMode)) return false
    var argv = UsageLogic.accountUseArgv(providerId, account)
    if (!argv) return false
    runArgv(argv)
    pendingUse = { provider: String(providerId), accountId: String(account.accountId), at: Date.now() / 1000 }
    useBusyId = String(account.accountId)
    useWatch.restart()
    useRefresh.restart()
    return true
  }

  onPanelOpenChanged: {
    if (panelOpen) {
      if (notice) noticeSeen = true
    } else if (noticeSeen) {
      // A notice that was on screen has been seen; closing the panel clears it.
      notice = null
      noticeSeen = false
    }
  }

  // Omarchy writes its registry first; the reading after that shows the account in use.
  Timer {
    id: useRefresh
    interval: 600
    onTriggered: root.refreshRequested()
  }

  Timer {
    id: useWatch
    interval: 5000
    onTriggered: root.useBusyId = ""
  }
}
