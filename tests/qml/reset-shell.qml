import QtQuick
import Quickshell

ShellRoot {
  id: root
  property var backend: null
  property var form: null
  property var widget: null
  property int phase: 0
  property int ticks: 0
  property int finishes: 0
  readonly property var proxy: ({ id: "p-1a2b3c4d", name: "CLIProxyAPI" })
  // A Codex account read through the proxy: its resets are applied there.
  readonly property var account: ({ id: "codex", accountId: "account", status: "ok",
    credits: { resetCreditsAvailable: 2 }, planType: "pro", origin: "proxy", proxy: proxy })
  // A single Claude Code sign-in (no accountId) holding one reset Claude lets it spend now.
  readonly property var claude: ({ id: "claude", name: "Claude Code", status: "ok", plan: "Max",
    credits: { label: "Banked resets", resetCreditsAvailable: 1, resetCreditsUsable: true, resetCreditsReason: "" } })

  QtObject {
    id: usage
    property string connectionId: "first-server"
    property var settings: ({ sources: JSON.stringify([{ id: "p-1a2b3c4d", kind: "proxy", on: true,
      url: "http://synthetic.invalid", keyFile: "" }]) })
    function localPath(url) { return String(url).replace("file://", "") }
  }
  Item { id: host; width: 420; height: 800 }

  function check(condition, message) {
    if (!condition) { console.error("RESET TEST FAILED: " + message); Qt.exit(1) }
  }
  function create(name, props) {
    var component = Qt.createComponent(Quickshell.env("QUOTATANK_REPO_URL") + "/" + name)
    check(component.status === Component.Ready, component.errorString())
    var object = component.createObject(host, props)
    check(object !== null, "create " + name)
    return object
  }
  function namedChild(item, name) {
    if (item.objectName === name) return item
    var children = item.children || []
    for (var i = 0; i < children.length; i++) {
      var found = namedChild(children[i], name)
      if (found) return found
    }
    return null
  }
  Component.onCompleted: {
    backend = create("ResetBackend.qml", { usageBackend: usage, scriptPath: Quickshell.env("QUOTATANK_FAKE_RESET") })
    form = create("ResetConfirmation.qml", { backend: backend, width: 420 })
    backend.finished.connect(function() { root.finishes++ })
    var own = Object.assign({}, account, { origin: "omarchy" })
    delete own.proxy
    check(!backend.begin(own, "Account 1"), "a Codex account read here is not actionable")
    check(!backend.begin(Object.assign({}, claude, { credits: Object.assign({}, claude.credits,
      { resetCreditsUsable: false, resetCreditsReason: "limit" }) }), "Claude Code"), "a reset Claude holds back is not actionable")
    check(!backend.begin(Object.assign({}, claude, { origin: "omp" }), "Claude Code"), "omp keeps that sign-in")
    check(!backend.begin(Object.assign({}, account, { proxy: { id: "p-00000000", name: "CLIProxyAPI" } }), "Account 1"),
      "a proxy that is no longer under Sources cannot apply it")
    check(!backend.begin(Object.assign({}, account, { credits: {} }), "Account 1"), "unknown count is not actionable")
    check(backend.begin(account, "Account 1"), "begin fresh lookup")
    check(backend.proxy && backend.proxy.url === "http://synthetic.invalid", "the reset goes through the reading's proxy")
    check(!backend.begin(account, "Account 2"), "duplicate click is ignored")
  }
  Timer {
    interval: 30
    running: true
    repeat: true
    onTriggered: {
      root.ticks++
      root.check(root.ticks < 250, "state machine timed out at " + root.phase + ": " + root.backend.state)
      var b = root.backend
      if (root.phase === 0 && b.state === "ready") {
        root.check(b.selectedCredit.id === "first", "earliest reset is preselected")
        root.check(b.accountLabel === "Account 1", "confirmation preserves account privacy label")
        root.check(root.form.implicitHeight > 0, "confirmation has a visible layout")
        var option = root.namedChild(root.form, "resetCreditOption")
        root.check(option !== null, "reset option button exists")
        option.clicked()
        root.check(b.state === "ready" && !b.busy, "clicking a reset option only selects it")
        b.selectedIndex = 1
        b.apply()
        b.apply()
        root.check(b.state === "sending", "double apply starts only one request")
        root.phase++
      } else if (root.phase === 1 && b.state === "uncertain") {
        b.cancel()
        root.check(b.state === "uncertain", "uncertain request retains retry context")
        root.check(b.selectedCredit.id === "second", "retry retains selected credit")
        b.apply()
        root.phase++
      } else if (root.phase === 2 && b.state === "result") {
        root.check(root.finishes === 2, "refresh follows both ambiguous and confirmed outcomes")
        root.check(b.message.indexOf("already redeemed") >= 0, "idempotent replay gets accurate feedback")
        b.cancel()
        b.begin(root.account, "Account 1")
        b.cancel()
        root.phase++
      } else if (root.phase === 3 && !b.busy) {
        root.check(b.state === "idle", "cancelled lookup cannot reopen confirmation")
        b.begin(root.account, "Account 1")
        root.phase++
      } else if (root.phase === 4 && b.state === "ready") {
        usage.connectionId = "second-server"
        root.check(b.state === "idle", "server change invalidates confirmation")
        b.apply()
        root.check(!b.busy, "old confirmation cannot submit")
        b.begin(root.account, "Account 1")
        root.phase++
      } else if (root.phase === 5 && b.state === "ready") {
        b.preparedAt = Date.now() - 180000
        b.apply()
        root.check(b.state === "error" && !b.busy, "stale confirmation cannot submit")
        b.cancel()
        root.check(b.begin(root.claude, "Claude Code"), "a Claude Code sign-in applies its own reset")
        root.check(b.providerId === "claude" && b.accountId === "main" && b.proxy === null,
          "the single sign-in is main, reset with its own sign-in")
        root.phase++
      } else if (root.phase === 6 && b.state === "ready") {
        root.check(b.selectedCredit.id === "launch-reset", "Claude's offered reset is selected")
        root.check(b.details.availableCount === 1, "Claude's count reaches the confirmation")
        b.apply()
        root.phase++
      } else if (root.phase === 7 && b.state === "result") {
        root.check(root.finishes === 3, "a Claude reset refreshes usage")
        b.cancel()
        if (Quickshell.env("QT_QPA_PLATFORM") === "offscreen") {
          console.log("Reset QML contract: passed")
          Qt.quit()
          return
        }
        root.widget = root.create("Panel.qml", { moduleName: "test.reset", ipcTarget: "test.reset",
          settings: { sources: JSON.stringify([{ id: "p-1a2b3c4d", kind: "proxy", url: "https://proxy.test/prefix",
            keyFile: "/private/proxy key", on: true }]), enabledProviders: ["codex"], refreshIntervalSec: 3600 } })
        root.widget.resetAction.scriptPath = Quickshell.env("QUOTATANK_FAKE_RESET")
        root.phase++
      } else if (root.phase === 8 && root.widget.providers.length > 0) {
        root.widget.selectProviderId("codex")
        root.phase++
      } else if (root.phase === 9 && root.widget.accountList.view.count > 0) {
        // Rows follow the accounts once the list has synced its model.
        root.check(root.widget.accountList.view.count === 3, "account badge integration fixture loaded")
        var zero = root.namedChild(root.widget.accountList.rowFor("0"), "accountResetAction")
        var action = root.namedChild(root.widget.accountList.rowFor("1"), "accountResetAction")
        root.check(zero && !zero.enabled, "zero resets badge is disabled")
        root.check(action && action.enabled, "nonzero resets badge is actionable")
        action.activate()
        root.check(root.widget.resetAction.accountId === "1", "badge targets the clicked account")
        root.check(root.widget.resetAction.accountLabel === "Account 2", "badge preserves email privacy")
        root.phase++
      } else if (root.phase === 10 && root.widget.resetAction.state === "ready") {
        root.check(!root.widget.resetAction.busy, "badge click only prepares confirmation")
        root.widget.resetAction.cancel()
        root.check(!root.widget.resetAction.active, "panel confirmation cancels without consuming")
        console.log("Reset QML contract: passed")
        Qt.quit()
      }
    }
  }
}
