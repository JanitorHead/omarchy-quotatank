import QtQuick
import "UsageLogic.js" as UsageLogic

// omp's live activity for one panel: each request as it happens, with the account behind it once omp's
// credential map names it, the log of recent requests that Costs adds to its last scan, and activity on
// omp stats on another computer. It follows omp only while omp is set up (found here and signed in, or
// omp stats on another computer) and never through a proxy; the panels on every monitor share one
// helper process (OmpLiveConnection.qml).
QtObject {
  id: root

  property var settings: ({})
  // The usage backend's `omp` status. The last one is kept while a settings change clears the backend's
  // payload, so an unrelated change does not restart the feed.
  property var status: null
  // Limits read through a proxy: its accounts are the proxy's and omp is not read, so nothing runs.
  property bool proxyMode: false
  property string scriptPath: decodeURIComponent(String(Qt.resolvedUrl("scripts/omp-live.py")).replace(/^file:\/\//, ""))

  property var knownStatus: null
  readonly property var flags: UsageLogic.ompLiveArguments(settings, knownStatus, proxyMode)
  readonly property string wantedKey: flags.length > 0 ? "omp-live:" + JSON.stringify([scriptPath, flags]) : ""
  property var connection: null
  property string connectionKey: ""
  property bool ready: false

  // "off" while nothing is followed; otherwise "connecting", "live", "reconnecting" or "unavailable".
  readonly property string state: connection ? connection.feedState : "off"
  readonly property string message: connection ? connection.message : ""
  // {"<provider>@<accountId>": epochSeconds} for the accounts that served a request in the last hour.
  readonly property var recentByAccount: connection ? connection.recentByAccount : ({})
  // Recent requests, [at, provider, costUsd | null, tokens, source] each (UsageLogic.noteOmpLog). The log
  // grows in place; `requestRevision` counts its changes, so bindings that read it run again.
  readonly property var requestLog: connection ? connection.requestLog : []
  readonly property int requestRevision: connection ? connection.requestRevision : 0

  // `event`: the request line from omp-live.py, plus `accountId` and `accountKey` when omp's credential
  // map knows the credential that served it.
  signal request(var event)
  // omp stats on another computer indexed new requests.
  signal remoteActivity()

  function sync() {
    if (!ready || wantedKey === connectionKey) return
    var previous = connectionKey
    connection = null
    connectionKey = wantedKey
    if (previous !== "") UsageLogic.releaseLive(previous)
    if (connectionKey !== "") connection = UsageLogic.acquireOmpLive(connectionKey, { scriptPath: scriptPath, flags: flags })
  }

  onStatusChanged: if (status && typeof status === "object") knownStatus = status
  onWantedKeyChanged: sync()
  Component.onCompleted: {
    if (status && typeof status === "object") knownStatus = status
    ready = true
    sync()
  }
  Component.onDestruction: {
    ready = false
    connection = null
    if (connectionKey !== "") UsageLogic.releaseLive(connectionKey)
    connectionKey = ""
  }

  property Connections feed: Connections {
    target: root.connection
    function onRequest(event) { root.request(event) }
    function onRemoteActivity() { root.remoteActivity() }
  }
}
