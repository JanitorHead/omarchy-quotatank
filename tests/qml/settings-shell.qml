import QtQuick
import Quickshell

// Settings for omp (Oh My Pi) and the sources page end to end with synthetic processes: what the
// form shows for each omp state, the proxy source the form saves and the flags the backends receive
// for it, and omp's live feed (one helper shared by every panel, requests named by account).
ShellRoot {
  id: root
  property var form: null
  property var usage: null
  property var activity: null
  property var twin: null
  property var saved: ({})
  property int formPhase: 0
  property int usagePhase: 0
  property int livePhase: 0
  property string connection: ""
  property var events: []
  property int twinEvents: 0
  property int ticks: 0
  readonly property string fakeLive: Quickshell.env("QUOTATANK_FAKE_OMP_LIVE")

  QtObject {
    id: liveStub
    property string state: "live"
    property string message: ""
  }

  function check(condition, message) {
    if (!condition) throw new Error("SETTINGS TEST FAILED: " + message)
  }
  function create(name, values) {
    var component = Qt.createComponent(Quickshell.env("QUOTATANK_REPO_URL") + "/" + name)
    check(component.status === Component.Ready, component.errorString())
    var object = component.createObject(root, values || {})
    check(object !== null, component.errorString())
    return object
  }
  function find(item, name) {
    if (item.objectName === name) return item
    var children = item.children || []
    for (var i = 0; i < children.length; i++) {
      var child = find(children[i], name)
      if (child) return child
    }
    return null
  }
  function shown(name) {
    var item = find(form, name)
    check(item !== null, "exists: " + name)
    return item
  }
  // Word joiners keep hyphenated commands whole at a line break; they are not part of what is said.
  function text(name) { return String(shown(name).text).replace(/\u2060/g, "") }
  function edit(name, value, done) {
    var field = shown(name)
    field.text = value
    field.textEdited()
    if (done) field.editingFinished()
  }
  // Editable TextInputs (what TextField is built on) fetch the clipboard on every change in Qt 6.11
  // and 6.12.0; a TextEdit or a read-only TextInput does not.
  function editableTextInputs(item) {
    var count = item.echoMode !== undefined && item.readOnly === false ? 1 : 0
    var children = item.children || []
    for (var i = 0; i < children.length; i++) count += editableTextInputs(children[i])
    return count
  }
  function host(values) {
    saved = Object.assign({}, form.settings, values)
    form.settings = saved
    form.finishSave(true)
  }
  function argv(backend) {
    var request = backend.payload ? backend.payload.testRequest : null
    return request ? Array.prototype.slice.call(request.argv) : null
  }
  function hasPair(list, flag, value) {
    for (var i = 0; i + 1 < list.length; i++) if (list[i] === flag && list[i + 1] === value) return true
    return false
  }
  function payload(omp, providers) {
    return { generatedAt: "2030-01-15T12:00:00Z", detected: [], installed: ["claude", "codex"], omp: omp,
      providers: providers || [{ id: "claude", status: "ok", plan: "Max" }, { id: "codex", status: "ok" }] }
  }
  readonly property var ompFound: ({ local: "ok", version: "omp/18.10.3", localAccounts: 3, accounts: 3, installed: true })

  Component.onCompleted: {
    form = create("UsageSettings.qml", { width: 420, ompActivity: liveStub,
      settings: { enabledProviders: ["claude", "codex"], barProviders: ["claude", "codex"] } })
    form.changeRequested.connect(host)
    form.begin("sources")
    form.usagePayload = payload(ompFound)

    usage = create("UsageBackend.qml", { settings: { enabledProviders: ["claude"], ompLocal: false, refreshIntervalSec: 3600 } })

    activity = create("OmpActivity.qml", { scriptPath: fakeLive, settings: { ompLocal: true }, status: { local: "ok" } })
    twin = create("OmpActivity.qml", { scriptPath: fakeLive, settings: { ompLocal: true }, status: { local: "ok" } })
    check(activity.connection !== null && activity.connection === twin.connection, "panels following the same omp setup share one helper")
    check(JSON.stringify(activity.flags) === '["--local","--accounts"]', "omp found here is followed: " + JSON.stringify(activity.flags))
    activity.request.connect(function(event) { root.events = root.events.concat([event]) })
    twin.request.connect(function() { root.twinEvents++ })
    var idle = create("OmpActivity.qml", { scriptPath: fakeLive, settings: {}, status: { local: "missing" } })
    check(idle.connection === null && idle.state === "off", "without omp here nothing runs")
    idle.destroy()
    var unused = create("OmpActivity.qml", { scriptPath: fakeLive, settings: {}, status: { local: "unused", installed: true } })
    check(unused.connection === null && unused.state === "off", "omp installed but not signed in: nothing to follow")
    unused.destroy()
    var proxied = create("OmpActivity.qml", { scriptPath: fakeLive, settings: { ompLocal: true },
      status: { local: "ok" }, proxyMode: true })
    check(proxied.connection === null && proxied.state === "off", "a proxy source runs no omp helper")
    proxied.destroy()
  }

  Timer {
    interval: 50
    running: true
    repeat: true
    onTriggered: {
      root.ticks++
      root.formStep()
      root.usageStep()
      root.liveStep()
      if (root.formPhase === 99 && root.usagePhase === 99 && root.livePhase === 99) {
        root.formPhase = 100
        root.activity.destroy()
        root.twin.destroy()
        quit.start()
      }
    }
  }
  Timer { id: quit; interval: 600; onTriggered: { console.log("Settings QML contract: passed"); Qt.quit() } }
  Timer {
    interval: 25000
    running: true
    onTriggered: {
      root.check(false, "timed out: form " + root.formPhase + ", usage " + root.usagePhase
        + ", live " + root.livePhase + ", events " + JSON.stringify(root.events) + ", live state " + (root.activity ? root.activity.state : "-"))
      Qt.quit()
    }
  }

  function formStep() {
    if (formPhase === 0) {
      check(form.page === "sources", "Settings opens on Sources")
      form.page = "providers"
      check(text("ompStatusText") === "omp 18.10 found · 3 accounts", "the omp status names the version and the accounts: " + text("ompStatusText"))
      check(shown("ompLocal").visible && shown("ompLocalSwitch").checked, "Read omp's accounts is on by default")
      shown("ompLocalSwitch").toggled()
      check(saved.ompLocal === false, "the switch saves ompLocal")
      check(text("ompStatusText") === "omp found · its accounts are not read", "a switched-off reader still says omp is here")
      host({ ompLocal: true })
      form.usagePayload = payload({ local: "missing", accounts: 0 })
      check(!shown("ompLocal").visible && text("ompLocalHint").indexOf("Install omp") === 0, "without omp the switch gives way to what to do")
      form.usagePayload = payload({ local: "unused", installed: true, message: "omp is installed but not set up on this computer." })
      check(text("ompStatusText") === "omp is installed but not signed in to anything yet", "omp without its own state: " + text("ompStatusText"))
      check(text("ompLocalHint").indexOf("Once you sign in to an account in omp") === 0, "and what changes that")
      form.usagePayload = payload({ local: "error", message: "omp usage did not finish in time." })
      check(Qt.colorEqual(shown("ompStatusText").color, form.urgent) && text("ompLocalHint") === "omp usage did not finish in time.",
        "a failing omp is in the alert colour, with the backend's reason")
      form.usagePayload = payload(ompFound)
      formPhase = 1
    } else if (formPhase === 1) {
      form.page = "sources"
      shown("addProxy").clicked()
      var added = JSON.parse(saved.sources || "[]")
      check(added.length === 1 && added[0].kind === "proxy" && added[0].on === true, "Add proxy creates one switched-on proxy: " + saved.sources)
      edit("proxyUrlField", "https://proxy.example", true)
      check(JSON.parse(saved.sources)[0].url === "https://proxy.example", "the proxy URL saves on its entry")
      shown("proxyOn").toggled()
      check(JSON.parse(saved.sources)[0].on === false, "the switch turns the proxy off")
      shown("proxyOn").toggled()
      check(JSON.parse(saved.sources)[0].on === true, "and back on")
      check(editableTextInputs(form) === 0, "no source field is an editable TextInput")
      shown("removeProxy").clicked()
      check(JSON.parse(saved.sources).length === 0, "Remove proxy leaves no proxy source")
      formPhase = 2
    } else if (formPhase === 2) {
      form.page = "costs"
      check(text("costLocalOmpState") === "Not yet read", "omp's local sessions wait for the first scan")
      form.costSources = [{ id: "local-claude", name: "Local Claude", status: "ok" }, { id: "local-omp", name: "Local Oh My Pi", status: "ok" }]
      check(text("costLocalOmpState") === "Included", "omp's local sessions are counted with the providers above")
      check(text("costSource-local-omp") === "omp sessions on this computer · Included", "the last scan names omp's sources")
      formPhase = 3
    } else if (formPhase === 3) {
      form.page = "bar"
      shown("barAccountModeControl").changed("chips")
      check(saved.barAccountMode === "chips" && form.menuBarSummary().indexOf("a chip per account") >= 0, "Accounts: one chip per account")
      form.page = "display"
      shown("motionControl").changed("reduced")
      check(saved.motion === "reduced" && form.reducedMotion && form.rowMs === 0 && form.displaySummary().indexOf("Reduced motion") >= 0,
        "Motion: reduced turns the settings' own motion off")

      form.page = "providers"
      form.usagePayload = payload(ompFound, [
        { id: "claude", status: "ok", accounts: [{ accountId: "main", origin: "omarchy" }, { accountId: "omp-0123456789ab", origin: "omp" }] },
        { id: "codex", status: "ok" }])
      shown("providerList").forceLayout()
      shown("customize-claude").expanded = true
      shown("customize-codex").expanded = true
      check(shown("accountMode-claude").visible && !shown("accountMode-codex").visible, "the account mode is offered for a provider with several accounts")
      shown("accountMode-claude").changed("together")
      check(saved.accountModes === '{"claude":"together"}' && form.overrideSummary("claude") === "Together", "Accounts are used: Together")
      shown("accountMode-claude").changed("auto")
      check(saved.accountModes === "{}", "Automatically forgets the override")
      check(shown("showAccount-claude-1").label === "Account 2 · omp", "each account says where it is read from: " + shown("showAccount-claude-1").label)
      shown("showAccount-claude-1Switch").toggled()
      check(saved.hiddenAccounts === '{"claude":["omp-0123456789ab"]}' && form.overrideSummary("claude") === "1 hidden",
        "Accounts shown: turning one off hides it")
      check(!shown("showAccount-claude-0").enabled, "the last account shown cannot be hidden")
      shown("showAccount-claude-1Switch").toggled()
      check(saved.hiddenAccounts === "{}" && shown("showAccount-claude-0").enabled, "turning it back on forgets it")
      check(!find(form, "showAccount-codex-0"), "a provider with one account lists none")
      check(form.providersSummary().indexOf("· omp") > 0, "the index says omp adds accounts")
      formPhase = 7
    } else if (formPhase === 7) {
      form.page = "bar"
      check(shown("barShowPeriodsToggle").checked, "chips show their limit period by default")
      shown("barShowPeriodsToggleSwitch").toggled()
      check(saved.barShowPeriods === false && !shown("barShowPeriodsToggle").checked, "Show limit period turns the tag off")
      shown("barShowPeriodsToggleSwitch").toggled()
      check(saved.barShowPeriods === true, "and back on")
      form.page = "providers"
      formPhase = 99
    }
  }

  function usageStep() {
    var args = argv(usage)
    if (usagePhase === 0 && args) {
      check(args.indexOf("--omp") < 0, "with omp turned off the backend gets no omp flag: " + JSON.stringify(args))
      connection = usage.connectionId
      usage.settings = Object.assign({}, usage.settings, { ompLocal: true })
      check(usage.connectionId !== connection, "turning omp on is a new connection")
      usagePhase = 1
    } else if (usagePhase === 1 && args && args.indexOf("--omp") >= 0) {
      check(hasPair(args, "--omp", "local"), "omp here is read with --omp local")
      check(usage.ompStatus && usage.ompStatus.local === "ok", "the backend's omp status reaches Settings")
      connection = usage.connectionId
      usage.settings = Object.assign({}, usage.settings, { sources: JSON.stringify([{ id: "p-1a2b3c4d", kind: "proxy", url: "https://proxy.example",
        keyFile: "/private/cliproxy.key", keeperUrl: "", keeperPasswordFile: "", on: true }]) })
      check(usage.connectionId !== connection, "a switched-on proxy source is a new connection")
      usagePhase = 2
    } else if (usagePhase === 2 && args && args.indexOf("--cliproxy-url") >= 0) {
      check(hasPair(args, "--cliproxy-url", "https://proxy.example") && hasPair(args, "--cliproxy-key-file", "/private/cliproxy.key")
        && args.indexOf("--omp") < 0, "a proxy source is read instead of omp: " + JSON.stringify(args))
      usagePhase = 99
    }
  }

  function liveStep() {
    if (livePhase === 0 && events.length >= 3 && activity.state === "live") {
      check(events[0].accountId === "omp-0123456789ab" && events[0].accountKey === "claude@omp-0123456789ab",
        "a request names the account behind a known credential: " + JSON.stringify(events[0]))
      check(events[1].accountId === undefined && events[1].provider === "codex", "an unknown credential stays unattributed")
      check(events[2].credentialId === null && events[2].costUsd === null, "background spend arrives without a credential")
      check(twinEvents === 3, "every panel hears each request once")
      var recent = activity.recentByAccount
      check(Object.keys(recent).length === 1 && recent["claude@omp-0123456789ab"] > 0, "recentByAccount keys are provider@account")
      var log = activity.requestLog
      check(activity.requestRevision === 3 && log.length === 3, "every request lands in the log once: " + activity.requestRevision)
      check(Math.abs(log[0][2] + log[1][2] - 0.52) < 1e-9 && log[2][2] === null, "priced requests keep their cost; background spend has none")
      check(Math.abs(log[0][0] - Date.now() / 1000) < 30, "log times are epoch seconds")
      check(activity.requestLog === twin.requestLog, "panels share one log")
      livePhase = 1
    } else if (livePhase === 1) {
      activity.settings = { ompLocal: false }
      check(activity.connection === null && activity.state === "off" && twin.connection !== null,
        "a panel that stops following omp lets go; the other keeps the helper")
      livePhase = 99
    }
  }
}
