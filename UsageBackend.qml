import QtQuick
import Quickshell
import Quickshell.Io
import "UsageLogic.js" as UsageLogic

// Process boundary for all provider/network work. The QML side only consumes
// the versioned normalized contract emitted by scripts/usage-fetch.py.
Item {
  id: root
  visible: false

  property var settings: ({})
  property var payload: ({ schemaVersion: 1, generatedAt: "", providers: [] })
  property bool loading: false
  property string fetchError: ""
  property double lastSuccessAt: 0
  property double lastAttemptAt: 0
  property bool pendingRefresh: false
  property bool launchPending: false
  // refresh.json read (or found missing); until then it, not the settings, decides the first check.
  property bool stateLoaded: false

  readonly property int refreshIntervalSec: Math.max(60, Math.min(3600,
    Math.round(Number(setting("refreshIntervalSec", 900)) || 900)))
  readonly property var enabledProviderIds: normalizedProviderIds(setting(
    "enabledProviders", UsageLogic.DEFAULT_SETTINGS.enabledProviders))
  // Proxies under Settings → Sources: their accounts are read with this computer's and the other computers'.
  readonly property var proxyArguments: UsageLogic.proxyArguments(settings)
  // Private key files saved from settings, one `[id, path]` pair per API-key provider that has one.
  readonly property var keyFiles: {
    var result = []
    for (var i = 0; i < UsageLogic.KEY_PROVIDER_IDS.length; i++) {
      var id = UsageLogic.KEY_PROVIDER_IDS[i]
      var path = String(setting(id + "KeyFile", "")).trim()
      if (path !== "") result.push([id, path])
    }
    return result
  }
  // A provider's further keys, each read as its own account (Settings → Providers → Add another key).
  readonly property var extraKeyArguments: UsageLogic.extraKeyArguments(setting("extraKeys", "{}"), enabledProviderIds)
  // omp (Oh My Pi) on this computer (Settings → Sources → This computer).
  readonly property var ompArguments: UsageLogic.ompUsageArguments(settings)
  // What the backend found of omp: { local, message, accounts, ... }, or null before it says.
  readonly property var ompStatus: payload && payload.omp && typeof payload.omp === "object" ? payload.omp : null
  // Every reading as the backend gave it; Settings lists hidden accounts from these.
  readonly property var allProviders: payload ? UsageLogic.listOrEmpty(payload.providers) : []
  // What Limits, the menu bar and the notices show: the readings without the accounts hidden in Settings,
  // with the custom account names and the subscription end dates set in Settings applied.
  readonly property var providers: UsageLogic.withSubscriptionEnds(
    UsageLogic.withAccountNames(
      UsageLogic.withoutHiddenAccounts(allProviders, setting("hiddenAccounts", "{}")), setting("accountNames", "{}")),
    setting("subscriptionEnds", "{}"), Date.now() / 1000)
  // Providers set up on this computer, monitored or not; Settings offers the ones not monitored yet.
  readonly property var detected: payload ? UsageLogic.listOrEmpty(payload.detected) : []
  // Other computers under Settings → Sources, read over SSH with the same providers.
  readonly property var computerArguments: UsageLogic.computerArguments(settings)
  // What the backend says about each computer: { id, host, status, readAt, kind, message, fix, installed, omp }.
  readonly property var computers: payload ? UsageLogic.listOrEmpty(payload.computers) : []
  // Where Sign in and Install open a terminal (null: this computer).
  readonly property var mainComputer: UsageLogic.mainComputer(settings)
  readonly property string connectionId: JSON.stringify([keyFiles, extraKeyArguments, ompArguments, computerArguments,
    proxyArguments])
  // A saved reading stands in only for the same providers and connection.
  readonly property string readingKey: JSON.stringify([enabledProviderIds, connectionId])
  readonly property string scriptPath: localPath(Qt.resolvedUrl("scripts/usage-fetch.py"))
  readonly property string stateHome: Quickshell.env("XDG_STATE_HOME") || (Quickshell.env("HOME") + "/.local/state")
  readonly property string refreshStatePath: stateHome + "/omarchy/quotatank/refresh.json"
  readonly property double nextRefreshAt: lastAttemptAt > 0
    ? lastAttemptAt + refreshIntervalSec * 1000 : 0

  signal refreshed()

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function normalizedProviderIds(value) {
    var allowed = UsageLogic.LOCAL_PROVIDER_IDS
    var requested = UsageLogic.isListLike(value) ? value : allowed
    var result = []
    for (var i = 0; i < allowed.length; i++) {
      if (UsageLogic.contains(requested, allowed[i])) result.push(allowed[i])
    }
    return result
  }

  function localPath(url) {
    var value = String(url || "")
    if (value.indexOf("file://") === 0) value = value.substring(7)
    try { return decodeURIComponent(value) } catch (e) { return value }
  }

  // restart(), not start(): a running timer would keep its old deadline, and the automatic check would come
  // too soon after a manual one.
  function scheduleRefresh() {
    var delay = UsageLogic.refreshDelayMs(Date.now(), lastAttemptAt, refreshIntervalSec)
    refreshTimer.interval = Math.max(1, delay)
    refreshTimer.restart()
  }

  // A reading with a provider that could not be reached (no network yet, a timeout): worth a second try soon.
  function hasUnreachable(reading) {
    return UsageLogic.listOrEmpty(reading.providers).some(function(provider) {
      return provider && (provider.errorKind === "network" || provider.errorKind === "timeout")
    })
  }

  // The backend saves refresh.json (usage-fetch.py --refresh-key) as privately as its other state files; the
  // widget only reads it. A reading stands in only for the providers and sources it was read for.
  function restoreState(saved) {
    stateLoaded = true
    var attempted = saved ? Number(saved.lastAttemptAt) : NaN
    if (isFinite(attempted) && attempted > 0) lastAttemptAt = attempted
    var reading = saved && saved.reading && typeof saved.reading === "object" ? saved.reading : null
    var usable = reading && reading.key === readingKey && reading.payload
      && reading.payload.schemaVersion === 1 && UsageLogic.isListLike(reading.payload.providers)
    if (!usable) {
      requestRefresh(false)
      return
    }
    UsageLogic.boundUsagePayload(reading.payload)
    payload = reading.payload
    var generated = new Date(String(reading.payload.generatedAt || "")).getTime()
    lastSuccessAt = isFinite(generated) ? generated : 0
    // No refreshed(): threshold notices, account events and the trackers they compare with start from the first
    // live reading, as on a start without a saved one, never from a reading that may be hours old.
    scheduleRefresh()
    if (UsageLogic.refreshDelayMs(Date.now(), lastAttemptAt, refreshIntervalSec) > 0 && hasUnreachable(payload))
      networkRetry.start()
  }

  function requestRefresh(manual) {
    if (fetchProcess.running || launchPending || pendingRefresh) {
      pendingRefresh = true
      return
    }
    startFetch()
  }

  function refresh() { requestRefresh(true) }
  function refreshForSettings() { requestRefresh(false) }

  function startFetch() {
    if (fetchProcess.running || launchPending) return
    launchPending = true
    loading = true
    pendingRefresh = false
    lastAttemptAt = Date.now()
    scheduleRefresh()
    var command = [
      "python3", scriptPath,
      "--providers", enabledProviderIds.join(","),
      "--timeout", "12",
      "--refresh-key", readingKey
    ]
    for (var i = 0; i < keyFiles.length; i++) command.push("--key-file", keyFiles[i][0] + "=" + keyFiles[i][1])
    command = command.concat(extraKeyArguments).concat(ompArguments).concat(computerArguments).concat(proxyArguments)
    fetchProcess.command = command
    fetchProcess.connectionId = connectionId
    fetchProcess.running = true
  }

  function settle() {
    launchPending = false
    loading = false
    var wasRetry = networkRetry.retrying
    networkRetry.retrying = false
    if (fetchProcess.connectionId !== connectionId) {
      pendingRefresh = true
    } else if (fetchProcess.outputTooLarge) {
      fetchError = "Quotatank's limits reader returned too much data"
    } else if (fetchProcess.timedOut) {
      fetchError = "Quotatank's limits reader timed out"
    } else if (!fetchProcess.exitSeen) {
      fetchError = "Could not start python3 for Quotatank"
    } else if (fetchProcess.lastExit !== 0) {
      fetchError = "Quotatank's limits reader exited with status " + fetchProcess.lastExit
    } else {
      var parsed = null
      try { parsed = JSON.parse(fetchProcess.body) } catch (e) { parsed = null }
      if (!parsed || parsed.schemaVersion !== 1 || !UsageLogic.isListLike(parsed.providers)) {
        fetchError = "Quotatank's limits reader returned unreadable data"
      } else {
        var backendError = String(parsed.backendError || "")
        if (backendError !== "") {
          fetchError = backendError
        } else {
          UsageLogic.boundUsagePayload(parsed)
          payload = parsed
          fetchError = ""
          var generated = new Date(String(parsed.generatedAt || "")).getTime()
          lastSuccessAt = isFinite(generated) ? generated : Date.now()
          // The first check of a session often runs before the network is up; try once more soon
          // instead of leaving the cards on a connection error until the next interval.
          if (!hasUnreachable(parsed)) networkRetry.stop()
          else if (!wasRetry) networkRetry.start()
          refreshed()
        }
      }
    }
    if (pendingRefresh) Qt.callLater(function() {
      if (root.pendingRefresh) root.startFetch()
    })
  }

  // Let bindings consuming this list settle before changing loading state.
  onEnabledProviderIdsChanged: if (stateLoaded) Qt.callLater(refreshForSettings)
  onRefreshIntervalSecChanged: if (lastAttemptAt > 0) scheduleRefresh()
  onConnectionIdChanged: {
    if (!stateLoaded) return
    payload = ({ schemaVersion: 1, generatedAt: "", providers: [] })
    lastSuccessAt = 0
    fetchError = ""
    requestRefresh(false)
  }

  Process {
    id: fetchProcess
    running: false
    property string body: ""
    property bool exitSeen: false
    property int lastExit: 0
    property bool timedOut: false
    property bool outputTooLarge: false
    property string connectionId: ""
    readonly property int maxBodyChars: 2 * 1024 * 1024

    function appendBody(data) {
      if (outputTooLarge) return
      var chunk = String(data)
      if (body.length + chunk.length > maxBodyChars) {
        body = ""
        outputTooLarge = true
        running = false
        return
      }
      body += chunk
    }

    stdout: SplitParser {
      splitMarker: ""
      onRead: function(data) { fetchProcess.appendBody(data) }
    }
    // Drain diagnostics in arbitrary chunks without retaining them.
    stderr: SplitParser { splitMarker: "" }
    onExited: function(exitCode) {
      fetchProcess.exitSeen = true
      fetchProcess.lastExit = exitCode
    }
    onRunningChanged: {
      if (running) {
        root.launchPending = false
        body = ""
        exitSeen = false
        lastExit = 0
        timedOut = false
        outputTooLarge = false
        root.loading = true
        processTimeout.restart()
      } else {
        processTimeout.stop()
        root.settle()
      }
    }
  }

  Timer {
    id: processTimeout
    // `omp usage` may take up to 45 s, and another computer gets 55 s over SSH (scripts/usage-fetch.py), so
    // the collector gets longer when it runs either. A proxy is read after this computer's providers.
    interval: (root.computerArguments.length > 0 ? 75000 : root.ompArguments.indexOf("local") >= 0 ? 60000 : 35000)
      + (root.proxyArguments.length > 0 ? 15000 : 0)
    repeat: false
    onTriggered: {
      fetchProcess.timedOut = true
      fetchProcess.running = false
    }
  }

  Timer {
    id: networkRetry
    property bool retrying: false
    interval: 60000
    repeat: false
    onTriggered: {
      retrying = true
      root.requestRefresh(false)
    }
  }

  FileView {
    id: refreshState
    path: root.refreshStatePath
    printErrors: false
    onLoaded: {
      var saved = null
      try { saved = JSON.parse(text()) } catch (e) {}
      // Deferred so the settings given at creation are in readingKey.
      Qt.callLater(function() { if (!root.stateLoaded) root.restoreState(saved) })
    }
    onLoadFailed: Qt.callLater(function() { if (!root.stateLoaded) root.restoreState(null) })
  }

  Timer {
    id: refreshTimer
    interval: root.refreshIntervalSec * 1000
    repeat: false
    onTriggered: root.requestRefresh(false)
  }
}
