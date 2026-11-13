import QtQuick
import Quickshell
import Quickshell.Io

ShellRoot {
  id: root
  property var component: null
  property var first: null
  property var twin: null
  property var due: null
  property var other: null
  property bool twinFetched: false
  property var dueEvents: []
  property bool otherFetched: false
  property string otherFirst: ""
  property int phase: 0
  property double phaseAt: Date.now()
  readonly property var shared: ({ enabledProviders: ["codex"], refreshIntervalSec: 3600 })

  function check(condition, message) {
    if (!condition) { console.error("RESTART TEST FAILED: " + message); Qt.exit(1) }
  }
  function create(settings) {
    var backend = component.createObject(root, { settings: settings })
    check(backend !== null, component.errorString())
    return backend
  }
  function next() { phase++; phaseAt = Date.now() }

  FileView {
    id: stateFile
    path: Quickshell.env("XDG_STATE_HOME") + "/omarchy/quotatank/refresh.json"
    blockLoading: true
    blockWrites: true
    printErrors: false
  }

  Component.onCompleted: {
    component = Qt.createComponent(Quickshell.env("QUOTATANK_REPO_URL") + "/UsageBackend.qml")
    check(component.status === Component.Ready, component.errorString())
    first = create(shared)
  }

  Timer {
    interval: 50
    running: true
    repeat: true
    onTriggered: {
      var waited = Date.now() - root.phaseAt
      if (root.phase === 0 && root.first.savedReading && !root.first.loading && waited > 300) {
        check(root.first.payload.testRequest, "with no saved state the first panel checks at once")
        stateFile.reload()
        var saved = JSON.parse(stateFile.text())
        check(saved.reading && saved.reading.payload.testRequest && saved.lastAttemptAt > 0, "the reading is saved with its check time")
        root.twin = create(shared)
        root.twin.loadingChanged.connect(function() { if (root.twin.loading) root.twinFetched = true })
        next()
      } else if (root.phase === 1 && waited > 600) {
        check(!root.twinFetched, "a panel started within the interval waits instead of checking")
        check(root.twin.providers.length === 1 && root.twin.payload.testRequest, "it shows the saved reading meanwhile")
        check(root.twin.lastSuccessAt === root.first.lastSuccessAt, "with the saved reading's time")
        check(root.twin.nextRefreshAt > Date.now() + 3000 * 1000, "and checks when the interval ends")
        stateFile.reload()
        var aged = JSON.parse(stateFile.text())
        aged.lastAttemptAt = Date.now() - 2 * 3600 * 1000
        stateFile.setText(JSON.stringify(aged))
        root.due = create(shared)
        root.due.refreshed.connect(function() {
          root.dueEvents.push({ loading: root.due.loading, request: !!root.due.payload.testRequest })
        })
        root.due.loadingChanged.connect(function() { if (root.due.loading) root.dueEvents.push({ fetch: true }) })
        next()
      } else if (root.phase === 2 && root.dueEvents.length >= 3 && !root.due.loading) {
        check(root.dueEvents[0].request && !root.dueEvents[0].fetch, "a due panel shows the saved reading first: " + JSON.stringify(root.dueEvents))
        check(root.dueEvents[1].fetch, "then checks at once: " + JSON.stringify(root.dueEvents))
        root.other = create({ enabledProviders: ["claude", "codex"], refreshIntervalSec: 3600 })
        root.other.loadingChanged.connect(function() { if (root.other.loading) root.otherFetched = true })
        root.other.refreshed.connect(function() {
          if (root.otherFirst === "") root.otherFirst = root.other.payload.testRequest ? root.other.payload.testRequest.providers : "saved"
        })
        next()
      } else if (root.phase === 3 && root.otherFetched && !root.other.loading && root.other.payload.testRequest) {
        check(root.otherFirst === "claude,codex", "a reading saved for other providers is not shown; they check at once: " + root.otherFirst)
        console.log("Restart QML contract: passed")
        Qt.quit()
      }
    }
  }
  Timer { interval: 6000; running: true; onTriggered: root.check(false, "timed out in phase " + root.phase) }
}
