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
  property bool twinRefreshed: false
  property var dueEvents: []
  property bool otherFetched: false
  property string otherFirst: ""
  property int phase: 0
  readonly property var shared: ({ enabledProviders: ["codex"], refreshIntervalSec: 3600 })

  function check(condition, message) {
    if (!condition) { console.error("RESTART TEST FAILED: " + message); Qt.exit(1) }
  }
  function create(settings) {
    var backend = component.createObject(root, { settings: settings })
    check(backend !== null, component.errorString())
    return backend
  }
  function next() { phase++ }

  FileView {
    id: stateFile
    path: Quickshell.env("XDG_STATE_HOME") + "/omarchy/quotatank/refresh.json"
    blockAllReads: true
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
      if (root.phase === 0 && root.first.lastSuccessAt > 0 && !root.first.loading) {
        check(root.first.payload.testRequest, "with no saved state the first panel checks at once")
        stateFile.reload()
        var saved = JSON.parse(stateFile.text())
        check(saved.reading && saved.reading.payload.testRequest && saved.lastAttemptAt > 0, "the reading is saved with its check time")
        root.twin = create(shared)
        root.twin.loadingChanged.connect(function() { if (root.twin.loading) root.twinFetched = true })
        root.twin.refreshed.connect(function() { root.twinRefreshed = true })
        next()
      } else if (root.phase === 1 && root.twin.stateLoaded) {
        check(!root.twinFetched, "a panel started within the interval waits instead of checking")
        check(!root.twinRefreshed, "a restored reading sends no refreshed(): notices start from a live reading")
        check(root.twin.providers.length === 1 && root.twin.payload.testRequest, "it shows the saved reading meanwhile")
        check(root.twin.lastSuccessAt === root.first.lastSuccessAt, "with the saved reading's time")
        check(root.twin.nextRefreshAt > Date.now() + 3000 * 1000, "and checks when the interval ends")
        stateFile.reload()
        var aged = JSON.parse(stateFile.text())
        aged.lastAttemptAt = Date.now() - 2 * 3600 * 1000
        stateFile.setText(JSON.stringify(aged))
        root.due = create(shared)
        root.due.payloadChanged.connect(function() {
          root.dueEvents.push({ payload: true, loading: root.due.loading, request: !!root.due.payload.testRequest })
        })
        root.due.refreshed.connect(function() { root.dueEvents.push({ refreshed: true }) })
        root.due.loadingChanged.connect(function() { if (root.due.loading) root.dueEvents.push({ fetch: true }) })
        next()
      } else if (root.phase === 2 && root.dueEvents.length >= 4 && !root.due.loading) {
        var events = JSON.stringify(root.dueEvents)
        check(root.dueEvents[0].payload && root.dueEvents[0].request && !root.dueEvents[0].loading,
          "a due panel shows the saved reading first: " + events)
        check(root.dueEvents[1].fetch, "then checks at once: " + events)
        check(root.dueEvents.filter(function(event) { return event.refreshed }).length === 1
          && root.dueEvents[root.dueEvents.length - 1].refreshed, "and only the live reading is refreshed(): " + events)
        root.other = create({ enabledProviders: ["claude", "codex"], refreshIntervalSec: 3600 })
        root.other.loadingChanged.connect(function() { if (root.other.loading) root.otherFetched = true })
        root.other.payloadChanged.connect(function() {
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
