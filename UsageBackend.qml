import QtQuick
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

  readonly property int refreshIntervalSec: Math.max(60, Math.min(3600,
    Math.round(Number(setting("refreshIntervalSec", 900)) || 900)))
  readonly property var enabledProviderIds: normalizedProviderIds(setting(
    "enabledProviders", UsageLogic.DEFAULT_SETTINGS.enabledProviders))
  readonly property string usageSource: String(setting("usageSource", "direct")) === "cliproxy" ? "cliproxy" : "direct"
  readonly property string cliproxyUrl: String(setting("cliproxyUrl", "http://127.0.0.1:8317"))
  readonly property string cliproxyKeyFile: String(setting("cliproxyKeyFile", ""))
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
  // omp (Oh My Pi) on this computer and through its auth gateway (Settings → Providers → omp). A proxy
  // source reads every account from the proxy instead.
  readonly property var ompArguments: usageSource === "cliproxy" ? [] : UsageLogic.ompUsageArguments(settings)
  // What the backend found of omp: { local, gateway, message, accounts, ... }, or null before it says.
  readonly property var ompStatus: payload && payload.omp && typeof payload.omp === "object" ? payload.omp : null
  readonly property var providers: payload ? UsageLogic.listOrEmpty(payload.providers) : []
  // Providers set up on this computer, monitored or not; Settings offers the ones not monitored yet.
  readonly property var detected: payload ? UsageLogic.listOrEmpty(payload.detected) : []
  // Providers whose CLI is on PATH, or null before a payload says: Settings offers Sign in for these
  // and Install for the rest.
  readonly property var installed: payload && payload.installed !== undefined ? UsageLogic.listOrEmpty(payload.installed) : null
  readonly property string connectionId: JSON.stringify([usageSource, cliproxyUrl, cliproxyKeyFile, keyFiles, extraKeyArguments, ompArguments])
  readonly property string scriptPath: localPath(Qt.resolvedUrl("scripts/usage-fetch.py"))
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

  function requestRefresh(manual) {
    if (manual) refreshTimer.restart()
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
    var command = [
      "python3", scriptPath,
      "--providers", enabledProviderIds.join(","),
      "--source", usageSource,
      "--timeout", "12"
    ]
    if (usageSource === "cliproxy") {
      if (cliproxyUrl.trim() !== "") command.push("--cliproxy-url", cliproxyUrl.trim())
      if (cliproxyKeyFile.trim() !== "") command.push("--cliproxy-key-file", cliproxyKeyFile.trim())
    }
    if (usageSource !== "cliproxy") {
      for (var i = 0; i < keyFiles.length; i++) command.push("--key-file", keyFiles[i][0] + "=" + keyFiles[i][1])
      command = command.concat(extraKeyArguments).concat(ompArguments)
    }
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
          payload = usageSource === "cliproxy" ? UsageLogic.preserveProxyReadings(payload, parsed) : parsed
          fetchError = ""
          var generated = new Date(String(parsed.generatedAt || "")).getTime()
          lastSuccessAt = isFinite(generated) ? generated : Date.now()
          // The first check of a session often runs before the network is up; try once more soon
          // instead of leaving the cards on a connection error until the next interval.
          var unreachable = UsageLogic.listOrEmpty(parsed.providers).some(function(provider) {
            return provider && (provider.errorKind === "network" || provider.errorKind === "timeout")
          })
          if (!unreachable) networkRetry.stop()
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
  onEnabledProviderIdsChanged: Qt.callLater(refreshForSettings)
  onConnectionIdChanged: {
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
    // `omp usage` may take up to 45 s, so the collector gets longer when it runs omp.
    interval: root.ompArguments.indexOf("local") >= 0 ? 60000 : 35000
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

  Timer {
    id: refreshTimer
    interval: root.refreshIntervalSec * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.requestRefresh(false)
  }
}
