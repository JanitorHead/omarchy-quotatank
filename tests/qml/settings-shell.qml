import QtQuick
import Quickshell

// Settings for omp (Oh My Pi) and the 1.9 display options, end to end with synthetic processes: what the
// form shows for each omp state, the Test buttons' findings, the commands it copies, the flags the
// backends receive, and omp's live feed (one helper shared by every panel, requests named by account).
ShellRoot {
  id: root
  property var form: null
  property var usage: null
  property var costs: null
  property var activity: null
  property var twin: null
  property var broken: null
  property var saved: ({})
  property int formPhase: 0
  property int usagePhase: 0
  property int costPhase: 0
  property int livePhase: 0
  property double slowStartedAt: 0
  property string connection: ""
  property var events: []
  property int twinEvents: 0
  property int remoteActivities: 0
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
  readonly property var ompFound: ({ local: "ok", gateway: "off", version: "omp/18.10.3", localAccounts: 3, accounts: 3, installed: true })

  Component.onCompleted: {
    form = create("UsageSettings.qml", { width: 420, ompActivity: liveStub,
      settings: { enabledProviders: ["claude", "codex"], barProviders: ["claude", "codex"] } })
    form.changeRequested.connect(host)
    form.begin("providers")
    form.usagePayload = payload(ompFound)

    usage = create("UsageBackend.qml", { settings: { enabledProviders: ["claude"], ompLocal: false, refreshIntervalSec: 3600 } })
    costs = create("CostBackend.qml", { settings: { costLocalProviders: ["claude"] } })
    costs.ensureLoaded()

    activity = create("OmpActivity.qml", { scriptPath: fakeLive, settings: { ompStatsUrl: "http://devbox:3847" },
      status: { local: "ok" } })
    twin = create("OmpActivity.qml", { scriptPath: fakeLive, settings: { ompStatsUrl: "http://devbox:3847" },
      status: { local: "ok" } })
    broken = create("OmpActivity.qml", { scriptPath: fakeLive, settings: { ompLocal: false, ompStatsUrl: "http://broken:3847" } })
    check(activity.connection !== null && activity.connection === twin.connection, "panels following the same omp setup share one helper")
    check(broken.connection !== activity.connection, "another setup gets its own helper")
    check(JSON.stringify(activity.flags) === '["--local","--accounts","--stats-url","http://devbox:3847"]',
      "omp found here and omp stats elsewhere are both followed: " + JSON.stringify(activity.flags))
    activity.request.connect(function(event) { root.events = root.events.concat([event]) })
    activity.remoteActivity.connect(function() { root.remoteActivities++ })
    twin.request.connect(function() { root.twinEvents++ })
    var idle = create("OmpActivity.qml", { scriptPath: fakeLive, settings: {}, status: { local: "missing" } })
    check(idle.connection === null && idle.state === "off", "without omp here or elsewhere nothing runs")
    idle.destroy()
    var unused = create("OmpActivity.qml", { scriptPath: fakeLive, settings: {}, status: { local: "unused", installed: true } })
    check(unused.connection === null && unused.state === "off", "omp installed but not signed in: nothing to follow")
    unused.destroy()
    var proxied = create("OmpActivity.qml", { scriptPath: fakeLive, settings: { ompStatsUrl: "http://devbox:3847" },
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
      root.costStep()
      root.liveStep()
      if (root.formPhase === 99 && root.usagePhase === 99 && root.costPhase === 99 && root.livePhase === 99) {
        root.formPhase = 100
        root.activity.destroy()
        root.twin.destroy()
        root.broken.destroy()
        quit.start()
      }
    }
  }
  Timer { id: quit; interval: 600; onTriggered: { console.log("Settings QML contract: passed"); Qt.quit() } }
  Timer {
    interval: 25000
    running: true
    onTriggered: {
      root.check(false, "timed out: form " + root.formPhase + ", usage " + root.usagePhase + ", costs " + root.costPhase
        + ", live " + root.livePhase + ", events " + JSON.stringify(root.events) + ", live state " + (root.activity ? root.activity.state : "-"))
      Qt.quit()
    }
  }

  function formStep() {
    if (formPhase === 0) {
      check(form.page === "providers", "Settings opens on Providers")
      check(text("ompStatusText") === "omp 18.10 found · 3 accounts", "the omp status names the version and the accounts: " + text("ompStatusText"))
      check(shown("ompLocal").visible && shown("ompLocalSwitch").checked, "Read omp's accounts is on by default")
      shown("ompLocalSwitch").toggled()
      check(saved.ompLocal === false, "the switch saves ompLocal")
      check(text("ompStatusText") === "omp found · its accounts are not read", "a switched-off reader still says omp is here")
      host({ ompLocal: true })
      form.usagePayload = payload({ local: "missing", gateway: "off", accounts: 0 })
      check(!shown("ompLocal").visible && text("ompLocalHint").indexOf("Install omp") === 0, "without omp the switch gives way to what to do")
      form.usagePayload = payload({ local: "unused", installed: true, gateway: "off", message: "omp is installed but not set up on this computer." })
      check(text("ompStatusText") === "omp is installed but not signed in to anything yet", "omp without its own state: " + text("ompStatusText"))
      check(text("ompLocalHint").indexOf("Once you sign in to an account in omp") === 0, "and what changes that")
      form.usagePayload = payload({ local: "error", gateway: "off", message: "omp usage did not finish in time." })
      check(Qt.colorEqual(shown("ompStatusText").color, form.urgent) && text("ompLocalHint") === "omp usage did not finish in time.",
        "a failing omp is in the alert colour, with the backend's reason")
      form.usagePayload = payload(ompFound)

      var gateway = shown("ompGatewaySection")
      check(gateway.summary === "Not set up", "the gateway starts unset")
      gateway.expanded = true
      check(!shown("ompGatewayTestButton").enabled && text("ompGatewayTestBlocked") === "Enter the gateway URL and save its token to test it.",
        "Test waits for an address and a token, and says so")
      edit("ompGatewayUrlField", "http://example.com:4000", true)
      check(shown("ompGatewayUrl").error !== "" && saved.ompGatewayUrl === undefined, "plain HTTP to a public host is refused in place")
      edit("ompGatewayUrlField", "http://devbox:4000", true)
      check(saved.ompGatewayUrl === "http://devbox:4000" && gateway.summary === "devbox · token needed", "the URL saves; the token is asked for")
      check(!shown("ompGatewayTestButton").enabled, "Test still waits for the token")
      host({ ompGatewayKeyFile: "/private/management-keys/key-0123.key" })
      check(gateway.summary === "devbox" && shown("ompGatewayTestButton").enabled, "with a saved token the gateway can be tested")
      check(shown("ompGatewayToken").saved && !shown("ompGatewayTokenField").visible, "the token shows as saved, never as text")
      check(editableTextInputs(form) === 0, "no omp field is an editable TextInput")
      check(text("ompGatewayCommand-0Text") === 'omp auth-gateway serve \\\n  --bind="$(tailscale ip -4):4000"', "the gateway command is shown")
      shown("ompGatewayCommand-1Copy").clicked()
      shown("ompGatewayTestButton").clicked()
      check(text("ompGatewayTestButton") === "Testing…" && !shown("ompGatewayTestButton").enabled, "a running test cannot start twice")
      formPhase = 1
    } else if (formPhase === 1 && find(form, "ompGatewayTestLine-0") !== null && text("ompGatewayCommand-1Copy") !== "Copy") {
      check(text("ompGatewayTestLine-0Text") === "Gateway answers · 3 accounts: Claude 2, Codex 1",
        "the gateway's result names what it found: " + text("ompGatewayTestLine-0Text"))
      check(Qt.colorEqual(shown("ompGatewayTestLine-0Text").color, form.foreground), "a finding reads in the text colour")
      check(find(form, "ompGatewayTestLine-1") === null, "both providers are monitored, so there is no note")
      check(text("ompGatewayCommand-1Copy") === "Copied", "Copy confirms once wl-copy has the command")
      edit("ompGatewayUrlField", "http://refused:4000", true)
      check(find(form, "ompGatewayTestLine-0") === null, "a result about another address goes away")
      shown("ompGatewayTestButton").clicked()
      formPhase = 2
    } else if (formPhase === 2 && find(form, "ompGatewayTestLine-0") !== null) {
      check(text("ompGatewayTestLine-0Text") === "The gateway refused the token. Copy a fresh one with omp auth-gateway token on refused, then save it here.",
        "a refusal says what to do next")
      check(Qt.colorEqual(shown("ompGatewayTestLine-0Text").color, form.urgent), "errors are in the alert colour")
      edit("ompGatewayUrlField", "http://slow:4000", true)
      shown("ompGatewayTestButton").clicked()
      slowStartedAt = Date.now()
      formPhase = 3
    } else if (formPhase === 3 && Date.now() - slowStartedAt >= 420) {
      check(text("ompGatewayTestButton") === "Testing…", "the slow gateway is still being asked")
      check(shown("ompGatewayTestSpinner").visible && text("ompGatewayTestWaiting") === "Asking the gateway on slow…",
        "after 300 ms a spinner says what the test waits for")
      formPhase = 4
    } else if (formPhase === 4 && find(form, "ompGatewayTestLine-0") !== null) {
      check(!shown("ompGatewayTestSpinner").visible, "the spinner leaves with the answer")
      form.page = "costs"
      check(text("costLocalOmpState") === "Not yet read", "omp's local sessions wait for the first scan")
      form.costSources = [{ id: "local-claude", name: "Local Claude", status: "ok" }, { id: "local-omp", name: "Local Oh My Pi", status: "ok" },
        { id: "omp-remote", name: "Oh My Pi stats", status: "ok", host: "devbox" }]
      check(text("costLocalOmpState") === "Included", "omp's local sessions are counted with the providers above")
      check(text("costSource-local-omp") === "omp sessions on this computer · Included" && text("costSource-omp-remote") === "omp stats on devbox · Included",
        "the last scan names omp's sources")
      var stats = shown("ompStatsSection")
      check(stats.summary === "Not set up", "omp stats starts unset")
      stats.expanded = true
      check(text("ompStatsCommand-0Text") === 'omp stats --host "$(tailscale ip -4)" --port 3847', "Tailscale is the first way shown")
      shown("ompStatsVia").changed("ssh")
      check(form.ompStatsVia === "ssh" && text("ompStatsCommand-0Text") === "omp stats --host 127.0.0.1 --port 3847"
        && text("ompStatsCommand-1Text") === "ssh -N -L 3847:127.0.0.1:3847 other-computer", "an SSH tunnel has a command on each computer")
      shown("ompStatsUnitToggle").checked = true
      check(text("ompStatsUnit-1Text").indexOf("ExecStart=/usr/bin/ssh -N \\\n  -o ExitOnForwardFailure=yes") >= 0, "the tunnel's unit is offered")
      check(shown("ompStatsWarning").visible && text("ompStatsWarningText").indexOf("also serves your conversations") >= 0,
        "the dashboard's conversations are warned about")
      edit("ompStatsUrlField", "http://example.com:3847", true)
      check(shown("ompStatsUrl").error !== "" && saved.ompStatsUrl === undefined, "an exposed dashboard address is refused")
      edit("ompStatsUrlField", "http://devbox:3847", true)
      check(saved.ompStatsUrl === "http://devbox:3847" && stats.summary === "devbox · live", "the URL saves; the summary says the feed is live")
      check(editableTextInputs(form) === 0, "no Costs field is an editable TextInput")
      shown("ompStatsTestButton").clicked()
      formPhase = 5
    } else if (formPhase === 5 && find(form, "ompStatsTestLine-1") !== null) {
      check(text("ompStatsTestLine-0Text") === "omp stats on devbox answers", "the server is named")
      check(text("ompStatsTestLine-1Text") === "18,811 requests · $1,107.83 in the last 7 days", "the result says what the server counted")
      check(shown("ompStatsTestLive").visible && text("ompStatsTestLiveText") === "Live feed on · new activity shows within 10 s", "the live feed is reported")
      liveStub.state = "reconnecting"
      check(text("ompStatsTestLiveText") === "Live feed connecting…", "the live line follows the feed after the test")
      liveStub.state = "live"
      edit("ompStatsUrlField", "http://down:3847", true)
      shown("ompStatsTestButton").clicked()
      formPhase = 6
    } else if (formPhase === 6 && find(form, "ompStatsTestLine-0") !== null) {
      check(text("ompStatsTestLine-0Text") === "Nothing answers there. Is omp stats running on down?", "an unreachable server says what to check")
      check(Qt.colorEqual(shown("ompStatsTestLine-0Text").color, form.urgent) && !shown("ompStatsTestLive").visible, "no live line without an answer")

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
      check(hasPair(args, "--omp", "local") && args.indexOf("--omp-gateway-url") < 0, "omp here is read with --omp local")
      check(usage.ompStatus && usage.ompStatus.local === "ok", "the backend's omp status reaches Settings")
      connection = usage.connectionId
      usage.settings = Object.assign({}, usage.settings, { ompGatewayUrl: "http://devbox:4000" })
      check(usage.connectionId === connection, "a gateway without its token changes nothing")
      usage.settings = Object.assign({}, usage.settings, { ompGatewayKeyFile: "/private/gateway.key" })
      check(usage.connectionId !== connection, "a complete gateway is a new connection")
      usagePhase = 2
    } else if (usagePhase === 2 && args && args.indexOf("--omp-gateway-url") >= 0) {
      check(hasPair(args, "--omp-gateway-url", "http://devbox:4000") && hasPair(args, "--omp-gateway-key-file", "/private/gateway.key")
        && hasPair(args, "--omp", "local"), "the gateway's URL and token file reach the backend")
      usage.settings = Object.assign({}, usage.settings, { usageSource: "cliproxy", cliproxyUrl: "https://proxy.example" })
      usagePhase = 3
    } else if (usagePhase === 3 && args && args.indexOf("cliproxy") >= 0) {
      check(args.indexOf("--omp") < 0 && args.indexOf("--omp-gateway-url") < 0, "a proxy source reads no omp")
      usagePhase = 99
    }
  }

  function costStep() {
    var args = argv(costs)
    if (costPhase === 0 && args && !costs.loading) {
      check(args.indexOf("--omp-stats-url") < 0, "without omp stats the scan gets no omp flag")
      connection = costs.connectionId
      costs.settings = { costLocalProviders: ["claude"], ompStatsUrl: "http://devbox:3847" }
      check(costs.connectionId !== connection, "omp stats is a new cost source")
      costPhase = 1
    } else if (costPhase === 1 && args && args.indexOf("--omp-stats-url") >= 0 && !costs.loading) {
      check(hasPair(args, "--omp-stats-url", "http://devbox:3847"), "omp stats reaches the scan")
      costPhase = 99
    }
  }

  function liveStep() {
    if (livePhase === 0 && events.length >= 3 && activity.state === "live") {
      check(events[0].accountId === "omp-0123456789ab" && events[0].accountKey === "claude@omp-0123456789ab",
        "a request names the account behind a known credential: " + JSON.stringify(events[0]))
      check(events[1].accountId === undefined && events[1].provider === "codex", "an unknown credential stays unattributed")
      check(events[2].credentialId === null && events[2].costUsd === null, "background spend arrives without a credential")
      check(twinEvents === 3, "every panel hears each request once")
      check(remoteActivities === 1, "activity on omp stats is passed on")
      var recent = activity.recentByAccount
      check(Object.keys(recent).length === 1 && recent["claude@omp-0123456789ab"] > 0, "recentByAccount keys are provider@account")
      var log = activity.requestLog
      check(activity.requestRevision === 3 && log.length === 3, "every request lands in the log once: " + activity.requestRevision)
      check(Math.abs(log[0][2] + log[1][2] - 0.52) < 1e-9 && log[2][2] === null, "priced requests keep their cost; background spend has none")
      check(Math.abs(log[0][0] - Date.now() / 1000) < 30, "log times are epoch seconds")
      check(activity.requestLog === twin.requestLog, "panels share one log")
      livePhase = 1
    } else if (livePhase === 1 && broken.state === "reconnecting") {
      check(broken.message !== "", "a broken feed says it is trying again")
      activity.settings = { ompLocal: false }
      check(activity.connection === null && activity.state === "off" && twin.connection !== null,
        "a panel that stops following omp lets go; the other keeps the helper")
      livePhase = 99
    }
  }
}
