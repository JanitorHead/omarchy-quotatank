import QtQuick
import Quickshell.Io
import "UsageLogic.js" as UsageLogic

// One scripts/omp-live.py, shared by every panel that follows the same omp setup (UsageLogic.acquireOmpLive).
// It keeps omp's credential map, so each request names the account that served it, the accounts used in
// the last hour, and a bounded log of recent requests for Costs; it restarts the helper after a pause that
// grows with each failure when it exits, sends a malformed line, or misses its heartbeats. Output is
// bounded: a line past 64 KiB, or 1 MiB without a newline, restarts it.
Item {
  id: root
  visible: false
  required property string scriptPath
  required property var flags
  // "connecting" until the helper speaks, then "live"; "reconnecting" while the helper restarts,
  // "unavailable" once it has failed three times in a row.
  property string feedState: "connecting"
  property string message: ""
  property var accountMap: ({})
  property var recentByAccount: ({})
  // [at, provider, costUsd | null, tokens, source] per request (UsageLogic.noteOmpLog), changed in place;
  // `requestRevision` counts the changes.
  property var requestLog: []
  property int requestRevision: 0
  // Failures in a row; a helper that ran for a minute before failing starts the count again.
  property int failures: 0
  property double startedAt: 0
  property bool stopped: false

  signal request(var event)

  function start() {
    if (stopped || process.running) return
    process.command = ["python3", "-u", scriptPath].concat(flags)
    process.body = ""
    startedAt = Date.now()
    process.running = true
    watchdog.restart()
  }
  function stop() {
    stopped = true
    restart.stop()
    watchdog.stop()
    process.running = false
    // Let SIGTERM finish before disposing of the Process (its destructor kills it).
    dispose.restart()
  }
  function retry() {
    if (Date.now() - startedAt > 60000) failures = 0
    failures++
    feedState = failures >= 3 ? "unavailable" : "reconnecting"
    message = "It keeps trying on its own."
    watchdog.stop()
    restart.interval = Math.min(60000, 2000 * Math.pow(2, failures - 1))
    restart.restart()
  }
  // A helper that never started has no exit to wait for.
  function fail() {
    process.body = ""
    if (process.running) process.running = false
    else if (!stopped) retry()
  }
  // Splits complete lines off the buffer with one scan and one slice per chunk, however many lines it holds.
  function receive(data) {
    if (stopped) return
    var body = process.body + data
    if (body.length > 1048576) { fail(); return }
    var start = 0
    var newline
    while ((newline = body.indexOf("\n", start)) >= 0) {
      var line = body.slice(start, newline)
      start = newline + 1
      if (line.trim() === "") continue
      var parsed = UsageLogic.parseOmpLiveLine(line)
      if (!parsed) { fail(); return }
      watchdog.restart()
      handle(parsed)
      if (stopped) return
    }
    process.body = start > 0 ? body.slice(start) : body
  }
  function handle(line) {
    feedState = "live"
    message = ""
    var now = Date.now() / 1000
    if (line.type === "accounts") {
      accountMap = line.map
    } else if (line.type === "request") {
      var event = UsageLogic.resolveOmpRequest(line, accountMap)
      // The map is a new object only when an account's time changed.
      var recent = UsageLogic.noteOmpRequest(recentByAccount, event, now)
      if (recent !== recentByAccount) recentByAccount = recent
      UsageLogic.noteOmpLog(requestLog, event, now)
      requestRevision++
      request(event)
    }
  }
  Component.onCompleted: start()
  Component.onDestruction: stop()

  Process {
    id: process
    property string body: ""
    stdout: SplitParser { splitMarker: ""; onRead: function(data) { root.receive(data) } }
    // Drain diagnostics in arbitrary chunks without retaining them.
    stderr: SplitParser { splitMarker: "" }
    onExited: if (root.stopped) { dispose.stop(); Qt.callLater(function() { root.destroy() }) }
    onRunningChanged: if (!running && !root.stopped) root.retry()
  }
  // omp-live.py sends a heartbeat at least every 5 s.
  Timer { id: watchdog; interval: 20000; onTriggered: root.fail() }
  Timer { id: restart; interval: 2000; onTriggered: root.start() }
  Timer { id: dispose; interval: 1000; onTriggered: root.destroy() }
}
