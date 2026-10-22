import QtQuick
import Quickshell
import "UsageLogic.js" as UsageLogic

// Limits with several accounts: rows and their status lines, reordering by model moves, the Use
// command, forecasts on limit cards, the runway and its gap, and the event notice. The components run
// offscreen; on Wayland the whole panel follows a synthetic backend through a Use and an Omarchy switch.
ShellRoot {
  id: root
  readonly property real now: Date.now() / 1000
  property var motion: null
  property var list: null
  property var rising: null
  property var quiet: null
  property var runwayCard: null
  property var notice: null
  property var markupNotice: null
  // Port 9 (discard) on loopback: were the tag ever read as rich text, nothing would answer.
  readonly property string markup: '<img src="http://127.0.0.1:9/quotatank-markup.png">Suspended'
  property var events: null
  property var widget: null
  property var argvs: []
  property var used: []
  property int refreshes: 0
  property int dismissals: 0
  property var workRow: null
  property int phase: 0
  property int ticks: 0
  property int waitTicks: 0
  readonly property string markers: Quickshell.env("QUOTATANK_ACCOUNTS_MARKERS")

  FloatingWindow {
    visible: true
    implicitWidth: 460
    implicitHeight: 1400
    color: "black"
    Item { id: host; anchors.fill: parent }
  }

  function check(condition, message) {
    if (!condition) {
      console.error("LIMITS TEST FAILED: " + message)
      Qt.exit(1)
      throw new Error(message)
    }
  }
  function create(name, props) {
    var component = Qt.createComponent(Quickshell.env("QUOTATANK_REPO_URL") + "/" + name)
    check(component.status === Component.Ready, component.errorString())
    var object = component.createObject(host, props || {})
    check(object !== null, "create " + name)
    return object
  }
  function find(item, name) {
    if (!item) return null
    if (item.objectName === name) return item
    var children = item.children || []
    for (var i = 0; i < children.length; i++) {
      var found = find(children[i], name)
      if (found) return found
    }
    return null
  }
  // Text items that would read markup: anything but PlainText. Provider text must stay text.
  function markupSinks(item, found) {
    found = found || []
    if (!item) return found
    if (item.textFormat !== undefined && item.textFormat !== Text.PlainText)
      found.push((item.objectName || String(item)) + " = " + item.textFormat)
    var children = item.children || []
    for (var i = 0; i < children.length; i++) markupSinks(children[i], found)
    return found
  }
  function textShowing(item, text) {
    if (!item) return null
    if (item.textFormat !== undefined && item.text === text) return item
    var children = item.children || []
    for (var i = 0; i < children.length; i++) {
      var found = textShowing(children[i], text)
      if (found) return found
    }
    return null
  }
  // A 5-hour window rising at `rate` %/s over its last 50 minutes, or holding still.
  function session(used, rate, resetsIn) {
    var samples = []
    for (var span = 3000; span >= 0; span -= 300)
      samples.push([now - span, rate ? Math.max(0, used - rate * span) : used])
    return { id: "session", label: "5-hour limit", used: used, remaining: 100 - used, windowSeconds: 18000,
      resetsAt: now + (resetsIn || 9000), samples: samples }
  }
  function weekly(used) {
    return { id: "weekly", label: "Weekly limit", used: used, remaining: 100 - used, windowSeconds: 604800,
      resetsAt: now + 3 * 86400, samples: [] }
  }
  function login(id, extra) {
    return Object.assign({ id: "claude", name: "Claude Code", status: "ok", accountId: id, label: id,
      origin: "omarchy", windows: [session(10, 0), weekly(20)] }, extra || {})
  }
  readonly property var accounts: [
    login("work", { active: true, plan: "Claude Max 5x", activity: { lastIncreaseAt: now - 60 },
      windows: [session(70, 0.01), weekly(31)] }),
    login("personal", { plan: "Claude Max 20x" }),
    login("spare", { plan: "Claude Pro", windows: [session(100, 0, 3600), weekly(50)] }),
    login("broken", { status: "error", errorKind: "expired", windows: [] })
  ]

  function stateOf(mode) {
    return UsageLogic.accountState({ id: "claude", status: "ok", accounts: accounts }, { modes: JSON.stringify({ claude: mode }),
      proxyMode: false, nowSeconds: now, recentByAccount: {}, warningThreshold: 25, criticalThreshold: 10 })
  }

  Component.onCompleted: {
    motion = create("Motion.qml", { preference: "reduced" })
    list = create("AccountList.qml", { width: 420, providerId: "claude", accounts: accounts,
      names: ["Work", "Personal", "Spare", "Broken"], accountState: stateOf("single"), nowSeconds: now, motion: motion })
    list.useRequested.connect(function(accountId) { root.used = root.used.concat([accountId]) })
    rising = create("LimitCard.qml", { width: 420, window: session(70, 0.01), nowSeconds: now, motion: motion })
    quiet = create("LimitCard.qml", { width: 420, window: Object.assign(session(31, 0), { label: markup }), nowSeconds: now, motion: motion })
    var provider = { id: "claude", status: "ok", accounts: [accounts[0], login("personal", { windows: [session(60, 0), weekly(10)] })] }
    runwayCard = create("RunwayCard.qml", { width: 420, motion: motion, nowSeconds: now, names: ["Work", "Personal"],
      counted: [0], runway: UsageLogic.accountRunway(provider, "single", [0], now, [0, 1]) })
    notice = create("EventNotice.qml", { width: 420, motion: motion, shown: true,
      text: "Omarchy moved new Claude sessions to Personal at 16:27: Work reached 95%. Running sessions stay on Work." })
    notice.dismissed.connect(function() { root.dismissals++ })
    markupNotice = create("EventNotice.qml", { width: 420, motion: motion, shown: true, text: markup })
    events = create("AccountEvents.qml", { providers: team("work", 90) })
    events.runArgv = function(argv) { root.argvs = root.argvs.concat([argv]) }
    events.refreshRequested.connect(function() { root.refreshes++ })
  }

  function team(active, workUsed) {
    return [{ id: "claude", name: "Claude Code", status: "ok", accountSwitch: { mode: "auto", threshold: 95 }, accounts: [
      login("work", { active: active === "work", windows: [session(workUsed, 0), weekly(31)] }),
      login("personal", { active: active === "personal", windows: [session(3, 0), weekly(39)] })
    ] }]
  }

  function rowText(accountId) {
    var row = list.rowFor(accountId)
    return row ? row.statusText : "(no row)"
  }

  function checkComponents() {
    // Rows: one per account, each with the most useful status line.
    check(list.view.count === 4, "a row per account")
    check(rowText("work") === "spending now", "spending now beats the plan: " + rowText("work"))
    check(rowText("personal") === "Claude Max 20x", "an idle account shows its plan: " + rowText("personal"))
    check(rowText("spare").indexOf("used up · back ") === 0, "used up says when it is back: " + rowText("spare"))
    check(rowText("broken") === "sign-in expired", "a failed reading says why: " + rowText("broken"))
    check(list.rowFor("work").inUse && !list.rowFor("work").canUse, "the account in use is tagged, not offered")
    check(list.rowFor("personal").useButton.visible, "another login offers Use")
    check(list.rowFor("work").counted && !list.rowFor("personal").counted, "the chip's account has the filled dot")
    list.rowFor("personal").useButton.clicked()
    check(root.used.length === 1 && root.used[0] === "personal", "Use asks for that account")
    list.events = ({ "claude@personal": { kind: "switch", at: now - 60 } })
    check(rowText("personal").indexOf("switched ") === 0, "a recent switch outranks the plan: " + rowText("personal"))

    // Together: least headroom first, by moves that keep each row's delegate.
    workRow = list.rowFor("work")
    check(list.view.itemAt(0) === workRow, "Work starts first")
    check(JSON.stringify(stateOf("together").order) === "[2,0,1,3]", "together: least headroom first")
    list.accountState = stateOf("together")

    // Limit cards: a dashed forecast where the pace runs out before the reset, none without a pace.
    check(rising.forecastSegment !== null && rising.meter.forecastActive, "a fast pace draws the forecast")
    check(rising.forecastSegment.runsOut === true, "the forecast runs out before the reset")
    check(rising.verdict.text.indexOf("runs out ") === 0 && rising.verdict.urgent, "the footer says when: " + rising.verdict.text)
    check(Math.abs(rising.meter.warningMark - 0.75) < 0.001 && Math.abs(rising.meter.criticalMark - 0.9) < 0.001,
      "threshold marks sit at 75% and 90% used")
    check(quiet.forecastSegment === null && !quiet.meter.forecastActive, "no pace, no forecast")
    rising.quotaMode = "Remaining"
    check(rising.meter.forecastActive && rising.forecastSegment.to <= 0.3001, "Remaining forecasts inside the fill")
    check(Math.abs(rising.meter.warningMark - 0.25) < 0.001, "Remaining marks the threshold on what is left")

    // Runway: both accounts run out before the reset, so a gap lane says how long nothing is left.
    check(runwayCard.runway.gap > 0, "the runway has a gap")
    check(find(runwayCard, "runwayLane-gap") !== null, "the gap lane is drawn")
    check(find(runwayCard, "runwayLane-account-1") !== null, "Personal takes over in its own lane")

    // Notice: open with its text, closed by its button.
    check(notice.height > 0 && notice.visible, "the notice opens")
    find(notice, "eventNoticeDismiss").clicked()
    check(root.dismissals === 1, "the notice can be dismissed")

    // Markup-shaped provider text is drawn as the characters it is, by no text item that reads markup.
    var shown = textShowing(markupNotice, markup)
    check(shown !== null && shown.textFormat === Text.PlainText, "a notice shows markup as text")
    shown = textShowing(quiet, markup)
    check(shown !== null && shown.textFormat === Text.PlainText, "a limit label shows markup as text")
    var sinks = markupSinks(host)
    check(sinks.length === 0, "text items that read markup: " + sinks.join(", "))

    // Use runs Omarchy's command and asks for a reading; the next readings make the notices.
    events.track(now)
    var personal = UsageLogic.providerAccounts(events.providers[0])[1]
    check(events.use("claude", personal, "single", false), "Use starts")
    check(root.argvs.length === 1 && JSON.stringify(root.argvs[0])
      === JSON.stringify(["omarchy", "agent", "account", "use", "claude", "personal"]), "Use runs omarchy agent account use: "
      + JSON.stringify(root.argvs))
    check(events.useBusyId === "personal", "the row waits for the switch")
    check(!events.use("claude", personal, "single", false), "a second click while waiting does nothing")
  }

  Timer {
    interval: 40
    running: true
    repeat: true
    onTriggered: {
      root.ticks++
      root.check(root.ticks < 400, "timed out in phase " + root.phase)
      if (root.phase === 0) {
        if (root.list.view.count < 4) return
        root.checkComponents()
        root.phase++
      } else if (root.phase === 1 && root.refreshes > 0) {
        root.check(root.list.rowModel.get(0).rowKey === "claude@spare", "the model moved Spare to the top")
        root.check(root.list.view.itemAt(1) === root.workRow, "Work's delegate survived the move")
        root.check(root.list.rowFor("work") === root.workRow, "no row was rebuilt")
        root.check(root.list.view.itemAt(0).y < root.workRow.y, "rows sit in the new order")
        root.events.providers = root.team("personal", 92)
        root.events.track(Date.now() / 1000)
        root.check(root.events.useBusyId === "", "the reading that shows the switch stops the spinner")
        root.check(root.events.notice && root.events.notice.manual === true, "the switch is the one Use asked for")
        root.check(UsageLogic.eventNoticeText(root.events.notice, root.events.providers[0], { work: "Work", personal: "Personal" },
          function() { return "16:27" }, root.events.notice.manual)
          === "New Claude sessions now use Personal. Running sessions stay on Work.", "the notice says what changed")
        root.events.providers = root.team("work", 92)
        root.events.track(Date.now() / 1000)
        root.check(root.events.notice.manual === false && root.events.notice.accountId === "work",
          "a switch Omarchy made on its own is its own notice")
        root.check(root.events.eventLog["claude@work"].kind === "switch", "the row of the new account mentions it")
        if (Quickshell.env("QT_QPA_PLATFORM") === "offscreen") {
          console.log("Limits QML contract: passed")
          Qt.quit()
          return
        }
        root.widget = Qt.createComponent(Quickshell.env("QUOTATANK_REPO_URL") + "/Panel.qml").createObject(host, {
          moduleName: "test.limits", ipcTarget: "test.limits",
          settings: { enabledProviders: ["claude", "kimi"], refreshIntervalSec: 3600, barDisplayMode: "Percentages" } })
        root.check(root.widget !== null, "panel loads")
        root.phase++
      } else if (root.phase === 2 && root.widget.providers.length === 2) {
        var w = root.widget
        w.selectProviderId("claude")
        root.check(w.accountOverview && w.accountMode === "single", "two Omarchy logins, one at a time")
        root.check(w.accountList.view.count === 2, "a row per login")
        root.check(w.providerOptions[0].dots && w.providerOptions[0].dots.dots.length === 2
          && w.providerOptions[0].dots.dots[0].counted, "the tile has a dot per login, the one in use filled")
        root.check(w.accountList.headerText === "Omarchy · switches at 95%", "the header says how logins switch")
        root.check(w.limitCards.count === 2, "the detail shows the selected login's limits")
        root.check(w.runwayVisible && w.runway.gap > 0, "both logins run out before the reset: a gap")
        w.selectProviderId("kimi")
        root.check(!w.accountOverview && w.detail === w.provider, "a single account keeps the provider layout")
        root.check(w.limitCards.count === 2 && w.headline.text !== "", "its cards and headline are as before")
        // The detail lives in the panel's popup: walk it from its content root.
        var content = w.accountList
        while (content.parent) content = content.parent
        var detailNotice = root.find(content, "detailNotice")
        root.check(detailNotice && detailNotice.text === root.markup && detailNotice.textFormat === Text.PlainText,
          "the provider's notice shows markup as text")
        var panelSinks = root.markupSinks(content).concat(root.markupSinks(w))
        root.check(panelSinks.length === 0, "panel text items that read markup: " + panelSinks.join(", "))
        w.selectProviderId("claude")
        // The recorder stands in for Omarchy: it notes the command and switches the synthetic registry.
        w.accountEvents.runArgv = function(argv) {
          root.argvs = root.argvs.concat([argv])
          Quickshell.execDetached(["touch", root.markers + "/used-personal"])
        }
        var row = w.accountList.rowFor("personal")
        root.check(row && row.useButton.visible, "Personal offers Use")
        row.useButton.clicked()
        root.check(JSON.stringify(root.argvs[root.argvs.length - 1])
          === JSON.stringify(["omarchy", "agent", "account", "use", "claude", "personal"]), "the panel's Use button runs the command")
        root.check(w.accountList.rowFor("personal").useBusy, "the button spins while it waits")
        root.phase++
      } else if (root.phase === 3 && root.widget.noticeText !== "") {
        var panel = root.widget
        root.check(panel.noticeText === "New Claude sessions now use Personal. Running sessions stay on Work.",
          "the panel's notice: " + panel.noticeText)
        root.check(panel.accountList.rowFor("personal").inUse && panel.accountEvents.useBusyId === "", "Personal is in use")
        Quickshell.execDetached(["touch", root.markers + "/omarchy-switched"])
        root.phase++
      } else if (root.phase === 4) {
        // Give the marker a moment to land, then read again.
        if (++root.waitTicks < 10) return
        root.widget.refreshNow()
        root.phase++
      } else if (root.phase === 5 && root.widget.noticeEvent && root.widget.noticeEvent.accountId === "work") {
        root.check(root.widget.noticeText.indexOf("Omarchy moved new Claude sessions to Work at ") === 0
          && root.widget.noticeText.indexOf("Personal reached 96%") > 0, "Omarchy's own switch: " + root.widget.noticeText)
        // One provider's answer with thousands of limits: the panel keeps a card's worth of them.
        Quickshell.execDetached(["touch", root.markers + "/flood"])
        root.waitTicks = 0
        root.phase++
      } else if (root.phase === 6) {
        if (++root.waitTicks < 10) return
        root.widget.refreshNow()
        root.phase++
      } else if (root.phase === 7) {
        var flooded = root.widget.providers.filter(function(row) { return row.id === "kimi" })[0]
        if (!flooded || UsageLogic.listOrEmpty(flooded.windows).length <= 2) return
        root.check(flooded.windows.length === UsageLogic.USAGE_LIST_LIMITS.windows,
          "the reading keeps " + UsageLogic.USAGE_LIST_LIMITS.windows + " of its 5000 limits: " + flooded.windows.length)
        root.widget.selectProviderId("kimi")
        root.phase++
      } else if (root.phase === 8) {
        root.check(root.widget.limitCards.count === UsageLogic.USAGE_LIST_LIMITS.windows,
          "a card per kept limit: " + root.widget.limitCards.count)
        console.log("Limits QML contract: passed")
        Qt.quit()
      }
    }
  }
}
