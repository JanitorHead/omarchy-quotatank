import QtQuick
import "UsageLogic.js" as UsageLogic

// omp's live activity for one panel: each request as it happens, with the account behind it once omp's
// credential map names it, and the log of recent requests that Costs adds to its last scan. It follows omp
// only while omp is set up here (found and signed in), and omp on each other
// computer under Settings → Sources where the last refresh found it set up; the panels on every monitor share
// one helper process per computer (OmpLiveConnection.qml).
QtObject {
  id: root

  property var settings: ({})
  // The usage backend's `omp` status. The last one is kept while a settings change clears the backend's
  // payload, so an unrelated change does not restart the feed.
  property var status: null
  // The usage backend's `computers`: the other computers and what was found of omp there.
  property var computers: []
  property string scriptPath: decodeURIComponent(String(Qt.resolvedUrl("scripts/omp-live.py")).replace(/^file:\/\//, ""))
  property string checkPath: decodeURIComponent(String(Qt.resolvedUrl("scripts/computer-check.py")).replace(/^file:\/\//, ""))

  property var knownStatus: null
  property var knownComputers: []
  readonly property var flags: UsageLogic.ompLiveArguments(settings, knownStatus)
  readonly property string wantedKey: flags.length > 0 ? "omp-live:" + JSON.stringify([scriptPath, flags]) : ""
  // [{ key, host, prefix }] for each computer to follow.
  readonly property var wantedComputers: UsageLogic.ompLiveComputers(settings, knownComputers).map(function(entry) {
    return { key: "omp-live:" + JSON.stringify([checkPath, entry.id, entry.host]), host: entry.host, prefix: entry.id + "/" }
  })
  property var connection: null
  property string connectionKey: ""
  property var computerConnections: []
  property var computerKeys: []
  property bool ready: false

  // "off" while nothing is followed here; otherwise "connecting", "live", "reconnecting" or "unavailable".
  readonly property string state: connection ? connection.feedState : "off"
  readonly property string message: connection ? connection.message : ""
  // {"<provider>@<accountId>": epochSeconds} for the accounts that served a request in the last hour, here
  // and on the other computers.
  readonly property var recentByAccount: {
    var merged = UsageLogic.mergeRecentActivity(connection ? connection.recentByAccount : ({}), [])
    for (var i = 0; i < computerConnections.length; i++) {
      var recent = computerConnections[i].recentByAccount
      for (var key in recent) if (!(merged[key] >= recent[key])) merged[key] = recent[key]
    }
    return merged
  }
  // Recent requests, [at, provider, costUsd | null, tokens, source] each (UsageLogic.noteOmpLog). The logs
  // grow in place; `requestRevision` counts their changes, so bindings that read them run again.
  readonly property int requestRevision: {
    var total = connection ? connection.requestRevision : 0
    for (var i = 0; i < computerConnections.length; i++) total += computerConnections[i].requestRevision
    return total
  }
  readonly property var requestLog: {
    var revision = requestRevision
    var log = connection ? connection.requestLog : []
    if (computerConnections.length === 0) return log
    var all = log.slice()
    for (var i = 0; i < computerConnections.length; i++) all = all.concat(computerConnections[i].requestLog)
    return all
  }

  // `event`: the request line from omp-live.py, plus `accountId` and `accountKey` when omp's credential
  // map knows the credential that served it.
  signal request(var event)

  function sync() {
    if (!ready) return
    if (wantedKey !== connectionKey) {
      var previous = connectionKey
      if (connection) connection.request.disconnect(root.request)
      connection = null
      connectionKey = wantedKey
      if (previous !== "") UsageLogic.releaseLive(previous)
      if (connectionKey !== "") {
        connection = UsageLogic.acquireOmpLive(connectionKey, { scriptPath: scriptPath, flags: flags })
        connection.request.connect(root.request)
      }
    }
    var keys = wantedComputers.map(function(entry) { return entry.key })
    if (JSON.stringify(keys) === JSON.stringify(computerKeys)) return
    var kept = []
    for (var i = 0; i < computerKeys.length; i++) {
      if (keys.indexOf(computerKeys[i]) >= 0) continue
      computerConnections[i].request.disconnect(root.request)
      UsageLogic.releaseLive(computerKeys[i])
    }
    for (var j = 0; j < wantedComputers.length; j++) {
      var wanted = wantedComputers[j]
      var known = computerKeys.indexOf(wanted.key)
      var live = known >= 0 ? computerConnections[known] : UsageLogic.acquireOmpLive(wanted.key,
        { scriptPath: checkPath, flags: ["--local", "--accounts"], host: wanted.host, accountPrefix: wanted.prefix })
      if (known < 0) live.request.connect(root.request)
      kept.push(live)
    }
    computerKeys = keys
    computerConnections = kept
  }

  function release() {
    if (connection) connection.request.disconnect(root.request)
    connection = null
    if (connectionKey !== "") UsageLogic.releaseLive(connectionKey)
    connectionKey = ""
    for (var i = 0; i < computerKeys.length; i++) {
      computerConnections[i].request.disconnect(root.request)
      UsageLogic.releaseLive(computerKeys[i])
    }
    computerConnections = []
    computerKeys = []
  }

  onStatusChanged: if (status && typeof status === "object") knownStatus = status
  // An empty list is a payload cleared by a settings change, not computers gone: they stay followed.
  onComputersChanged: if (UsageLogic.isListLike(computers) && (computers.length > 0 || UsageLogic.computerArguments(settings).length === 0))
    knownComputers = computers
  onWantedKeyChanged: sync()
  onWantedComputersChanged: sync()
  Component.onCompleted: {
    if (status && typeof status === "object") knownStatus = status
    if (UsageLogic.isListLike(computers) && computers.length > 0) knownComputers = computers
    ready = true
    sync()
  }
  Component.onDestruction: {
    ready = false
    release()
  }
}
