import QtQuick
import Quickshell

// Menu bar chip contract (DESIGN §1–2). The "components" phase runs offscreen in a window of its own, so
// animations really run: motion tokens and reduced motion, rolling digits, account dots, hints, the
// clock pie and the hover card, each driven from UsageLogic's helpers by synthetic accounts. The "panel"
// phase needs a Wayland session (Panel.qml creates a layer-shell panel): it loads Panel.qml with the
// synthetic multi-account backend and counts the chips it renders in both account modes.
ShellRoot {
  id: root

  readonly property string repoUrl: Quickshell.env("QUOTATANK_REPO_URL")
  readonly property string phaseName: Quickshell.env("QUOTATANK_BAR_PHASE") || "components"
  readonly property real now: Math.floor(Date.now() / 1000)
  readonly property var thresholds: ({ warningThreshold: 25, criticalThreshold: 10 })
  property var logic: null
  property var stage: null
  property var motion: null
  property var number: null
  property var dots: null
  property var cardWindow: null
  property var card: null
  property var widget: null
  property var live: null
  property int step: 0
  property int ticks: 0
  property int waited: 0
  property var savedPayload: null

  Item {
    id: panelHost
    width: 800
    height: 26
  }

  function check(condition, message) {
    if (condition) return
    console.error("BAR TEST FAILED: " + message)
    Qt.exit(1)
    throw new Error("bar contract stopped")
  }

  function create(name, parent, props) {
    var component = Qt.createComponent(repoUrl + "/" + name)
    check(component.status === Component.Ready, name + ": " + component.errorString())
    var object = component.createObject(parent, props || {})
    check(object !== null, "create " + name)
    return object
  }

  function namedChild(item, name) {
    if (!item) return null
    if (item.objectName === name) return item
    var children = item.children || []
    for (var i = 0; i < children.length; i++) {
      var found = namedChild(children[i], name)
      if (found) return found
    }
    return null
  }

  function namedChildren(item, prefix, out) {
    if (!item) return out
    if (String(item.objectName).indexOf(prefix) === 0) out.push(item)
    var children = item.children || []
    for (var i = 0; i < children.length; i++) namedChildren(children[i], prefix, out)
    return out
  }

  function win(id, label, used, resetIn, seconds) {
    return { id: id, label: label, used: used, remaining: 100 - used, resetsAt: now + resetIn, windowSeconds: seconds }
  }

  function account(id, label, used, extra) {
    return Object.assign({ id: "claude", accountId: id, label: label, status: "ok", origin: "omarchy",
      windows: [win("session", "5-hour limit", used, 7200, 18000), win("weekly", "Weekly limit", 30, 300000, 604800)],
      activity: {}, history: { h24: [10, 20, 30, 40, 50, used] } }, extra || {})
  }

  function provider(accounts, extra) {
    return Object.assign({ id: "claude", name: "Claude Code", status: "ok", windows: accounts[0].windows,
      accounts: accounts }, extra || {})
  }

  // The chip's strip, from the provider's account state (UsageLogic.accountState) in `mode`; `counted`
  // documents the account the state counts there.
  function strip(data, counted, mode, extra) {
    var state = logic.state(data, Object.assign({ modes: '{"claude":"' + mode + '"}', nowSeconds: now }, thresholds))
    check(JSON.stringify(Array.prototype.slice.call(state.counted)) === JSON.stringify(counted) || mode === "together",
      "the state counts " + JSON.stringify(counted))
    return logic.strip(data, state, Object.assign({ selector: "auto", nowSeconds: now }, extra || {}))
  }

  // Runs one step per tick; a step returns false to wait for animations or processes.
  readonly property var componentSteps: [
    function () {
      root.stage = Qt.createQmlObject('import QtQuick; import Quickshell; FloatingWindow { visible: true; implicitWidth: 520; '
        + 'implicitHeight: 360; color: "transparent"; property alias host: host; Item { id: host; anchors.fill: parent } }',
        root, "barStage")
      root.logic = Qt.createQmlObject('import QtQuick; import "' + repoUrl + '/UsageLogic.js" as UsageLogic; QtObject { '
        + 'function state(p, o) { return UsageLogic.accountState(p, o) } '
        + 'function strip(p, s, o) { return UsageLogic.barAccountStrip(p, s, o) } '
        + 'function hover(p, s, o) { return UsageLogic.barHoverModel(p, s, o) } }', root, "barLogic")
      root.motion = create("Motion.qml", root, {})
      return true
    },
    function () {
      if (motion.probe.running || waited < 2) return false
      check(!motion.systemReduced && !motion.reduced, "Hyprland with animations on keeps motion")
      check(motion.duration(motion.row) === 260 && motion.duration(motion.ping) === 700, "tokens pass through")
      var styleMotion = motion.styleReduceMotion !== undefined
      var animations = styleMotion ? Qt.createQmlObject('import QtQuick; import qs.Commons; QtObject { '
        + 'function set(on) { Style.reduceMotion = !on } }', root, "styleMotion")
        : { set: function (on) { motion.applyOption('{"option":"animations:enabled","int":' + (on ? 1 : 0) + ',"set":true}') } }
      animations.set(false)
      check(motion.reduced && motion.duration(motion.digit) === 0,
        styleMotion ? "Omarchy's reduced motion reduces motion" : "Hyprland animations off reduce motion")
      animations.set(true)
      check(!motion.reduced, "motion comes back with the animations")
      motion.preference = "reduced"
      var tokens = [motion.micro, motion.row, motion.morph, motion.digit, motion.popIn, motion.popOut, motion.flash, motion.ping]
      for (var i = 0; i < tokens.length; i++) check(motion.duration(tokens[i]) === 0, "reduced motion zeroes token " + tokens[i])
      motion.preference = "system"
      check(!motion.reduced && motion.duration(motion.micro) === 160, "the setting follows Hyprland again")
      root.number = create("RollingNumber.qml", stage.host, { text: "72%", motion: motion })
      number.font.pixelSize = 11
      return true
    },
    function () {
      check(number.renderedText() === "72%" && number.implicitWidth > 0, "first value shows without rolling")
      check(number.directionOf("72%", "75%") === 1 && number.directionOf("75%", "72%") === -1, "direction follows the value")
      check(number.directionOf("$1,234.50", "$1,234.00") === -1 && number.directionOf("—", "5%") === 0, "money and dashes")
      number.text = "75%"
      check(number.rolling, "a changed digit rolls")
      return true
    },
    function () {
      if (number.rolling) return false
      check(number.renderedText() === "75%", "rolled digits settle on the new value, got " + number.renderedText())
      number.text = "100%"
      return true
    },
    function () {
      if (number.rolling) return false
      check(number.renderedText() === "100%", "a longer value slides in whole, got " + number.renderedText())
      number.text = "9%"
      return true
    },
    function () {
      if (number.rolling) return false
      check(number.renderedText() === "9%", "a shorter value slides in whole, got " + number.renderedText())
      motion.preference = "reduced"
      number.text = "42%"
      check(!number.rolling && number.renderedText() === "42%", "reduced motion changes digits at once")
      motion.preference = "system"
      var two = provider([account("main", "Work", 72, { active: true }), account("personal", "Personal", 3)],
        { accountSwitch: { mode: "manual", threshold: 95 } })
      root.dots = create("AccountDots.qml", stage.host, { y: 40, motion: motion, strip: strip(two, [0], "single") })
      return true
    },
    function () {
      check(dots.dotCount === 2, "two accounts, two dots")
      var first = namedChild(dots, "accountDot-0")
      var second = namedChild(dots, "accountDot-1")
      check(first.counted && !first.dashed, "the account in use is counted")
      check(!second.counted && !second.dashed && second.dotState === "ok", "the other account is a hollow ok ring")
      check(namedChild(dots, "accountDotsFill").shown && namedChild(dots, "accountDotsFill").x === 0, "filled dot on the first slot")
      check(!namedChild(dots, "accountDotsMore").visible, "no +N with two accounts")
      check(!namedChild(dots, "accountDotsHint").shown, "no hint while the account in use has room")
      check(!namedChild(dots, "accountDotsPie").shown, "no pie while accounts have room")
      var switched = provider([account("main", "Work", 72), account("personal", "Personal", 3, { active: true })])
      dots.strip = strip(switched, [1], "single")
      return true
    },
    function () {
      var fill = namedChild(dots, "accountDotsFill")
      if (fill.x !== dots.pitch) return waited < 40 ? false : check(false, "filled dot slides to the new account")
      var five = provider([0, 1, 2, 3, 4].map(function (i) { return account("a" + i, "Account " + (i + 1), 10 + i * 10, { active: i === 4 }) }))
      dots.strip = strip(five, [4], "single")
      return true
    },
    function () {
      check(dots.dotCount === 3, "five accounts show three dots")
      check(namedChild(dots, "accountDot-2").counted && namedChild(dots, "accountDot-2").info.index === 4,
        "the counted fifth account keeps a dot")
      var more = namedChild(dots, "accountDotsMore")
      check(more.visible && more.text === "+2", "and +2 for the rest")
      var failing = provider([account("main", "Work", 40, { active: true }),
        account("broken", "Lab", 0, { status: "error", errorKind: "expired", windows: [] })])
      dots.strip = strip(failing, [0], "single")
      return true
    },
    function () {
      check(namedChild(dots, "accountDot-1").dashed && namedChild(dots, "accountDot-1").dotState === "error",
        "a failed account is a dashed ring")
      check(!namedChild(dots, "accountDot-0").dashed, "a healthy account keeps a solid ring")
      dots.stale = true
      check(namedChild(dots, "accountDot-0").dashed && !namedChild(dots, "accountDotsFill").shown,
        "a stale reading dashes every ring and drops the fill")
      dots.stale = false
      // Hint rules: the counted Omarchy login is critical and another login is below warning.
      var busy = [account("main", "Work", 92, { active: true }), account("personal", "Personal", 3)]
      dots.strip = strip(provider(busy, { accountSwitch: { mode: "manual", threshold: 95 } }), [0], "single")
      var hint = namedChild(dots, "accountDotsHint")
      check(hint.shown && hint.text === "→ Personal", "manual switching suggests the login with room")
      dots.strip = strip(provider(busy, { accountSwitch: { mode: "auto", threshold: 95 } }), [0], "single")
      check(!hint.shown, "no hint when Omarchy switches by itself")
      dots.strip = strip(provider(busy), [0], "single")
      check(!hint.shown, "no hint without Omarchy switching")
      var warm = [account("main", "Work", 92, { active: true }), account("personal", "Personal", 80)]
      dots.strip = strip(provider(warm, { accountSwitch: { mode: "manual", threshold: 95 } }), [0], "single")
      check(!hint.shown, "no hint when the other login is at warning too")
      dots.strip = strip(provider(busy, { accountSwitch: { mode: "manual", threshold: 95 } }), [0, 1], "together")
      check(!hint.shown, "no hint when accounts are used together")
      dots.strip = strip(provider(busy, { accountSwitch: { mode: "manual", threshold: 95 } }), [0], "single", { stale: true })
      check(!hint.shown, "no hint from a stale reading")
      // Every account used up: one clock pie towards the earliest reset, and the time left beside it.
      var spent = [account("main", "Work", 100, { active: true }),
        account("personal", "Personal", 100, { windows: [win("session", "5-hour limit", 100, 3600, 18000)] })]
      dots.strip = strip(provider(spent), [0], "single")
      check(dots.allUsedUp && namedChild(dots, "accountDotsPie").shown, "all used up shows the pie")
      check(Math.abs(namedChild(dots, "accountDotsPie").fraction - 0.8) < 0.01, "pie fills towards the earliest reset")
      check(hint.shown && hint.text === "1h 0m", "the hint names the time to that reset, got " + hint.text)
      return true
    },
    function () {
      if (namedChild(dots, "accountDotsPie").opacity !== 1) return waited < 40 ? false : check(false, "pie fades in")
      var spending = account("main", "Work", 64, { active: true, activity: { lastIncreaseAt: now - 60, lastDelta: 4, lastReadingAt: now - 60 } })
      var data = provider([spending, account("personal", "Personal", 100, { windows: [win("session", "5-hour limit", 100, 3600, 18000)] })],
        { accountSwitch: { mode: "auto", threshold: 95 } })
      var model = logic.hover(data, logic.state(data, Object.assign({ modes: "{}", nowSeconds: now }, thresholds)), { nowSeconds: now,
        readAtSeconds: now - 120, formatClock: function (seconds) { return Qt.formatTime(new Date(seconds * 1000), "HH:mm") } })
      // Hosted like Panel.qml's: a popup that shows while the card is open or fading, and lets go of its
      // anchor once the fade-out ends, so the card leaves its window from inside that last frame.
      root.cardWindow = Qt.createQmlObject('import QtQuick; import Quickshell; PopupWindow { property var stageWindow: null; '
        + 'property bool held: true; property Item card: null; visible: held && !!card && (card.open || card.opacity > 0); '
        + 'color: "transparent"; implicitWidth: 400; implicitHeight: 300; anchor.window: held ? stageWindow : null; '
        + 'anchor.rect.x: 10; anchor.rect.y: 70; anchor.rect.width: 1; anchor.rect.height: 1 }', root, "cardWindow")
      cardWindow.stageWindow = stage
      root.card = create("AccountHoverCard.qml", cardWindow.contentItem, { model: model, motion: motion, open: true })
      card.opacityChanged.connect(function () { if (card.opacity === 0 && !card.open) cardWindow.held = false })
      cardWindow.card = card
      return true
    },
    function () {
      if (card.opacity !== 1) return waited < 40 ? false : check(false, "hover card fades in")
      check(namedChild(card, "hoverCardTitle").text === "Claude · 2 accounts", "card names the provider and count")
      check(namedChild(card, "hoverCardMode").text === "Omarchy · switches at 95%", "card says how Omarchy switches")
      check(namedChild(card, "hoverCardStatus-0").text === "spending now", "spending account says so")
      check(namedChild(card, "hoverCardStatus-1").text.indexOf("used up · back ") === 0, "used-up account says when it is back")
      check(namedChild(card, "hoverCardRead").text.indexOf("Read at ") === 0, "footer says when the reading was taken")
      check(namedChildren(card, "hoverCardRow-", []).length === 2, "one row per account")
      check(namedChild(card, "hoverCardMore").text === "Click for details", "nothing more to list")
      var firstRow = namedChild(card, "hoverCardRow-0")
      var data = provider([account("main", "Work", 65, { active: true }), account("personal", "Personal", 100,
        { windows: [win("session", "5-hour limit", 100, 3600, 18000)] })], { accountSwitch: { mode: "auto", threshold: 95 } })
      card.model = logic.hover(data, logic.state(data, Object.assign({ modes: "{}", nowSeconds: now + 30 }, thresholds)),
        { nowSeconds: now + 30, readAtSeconds: now - 90, formatClock: function (seconds) { return "T" } })
      check(namedChild(card, "hoverCardRow-0") === firstRow, "a new reading updates the rows in place")
      // Many accounts: six rows at most, then "+N more".
      var crowd = provider([0, 1, 2, 3, 4, 5, 6, 7, 8].map(function (i) { return account("c" + i, "Account " + (i + 1), 10 + i * 9) }),
        { pool: { source: "omp", windows: [] } })
      card.model = logic.hover(crowd, logic.state(crowd, Object.assign({ modes: "{}", nowSeconds: now }, thresholds)), { nowSeconds: now })
      check(namedChildren(card, "hoverCardRow-", []).length === 6, "the card lists six accounts at most")
      check(namedChild(card, "hoverCardMore").text === "+3 more · Click for details", "and says how many more: " + namedChild(card, "hoverCardMore").text)
      // Provider tiles keep their delegates across readings: a tick changes figures, not tiles.
      var tileOptions = function (figure) {
        return ["claude", "codex"].map(function (id) { return { value: id, label: id, name: id, iconUrl: "", mark: "C", figure: figure,
          unit: "used", fill: 0.4, alert: false, failed: false, dots: null } })
      }
      root.widget = create("ProviderTiles.qml", stage.host, { y: 300, width: 400, options: tileOptions("40%"), motion: motion })
      card.open = false
      return true
    },
    function () {
      var tile = namedChild(widget, "providerTile-claude")
      check(tile !== null, "a tile per provider")
      var focused = tile.activeFocus
      widget.options = widget.options.map(function (option) { return Object.assign({}, option, { figure: "41%" }) })
      check(namedChild(widget, "providerTile-claude") === tile && tile.modelData.figure === "41%", "the tile survives a new reading")
      check(tile.activeFocus === focused, "and keeps keyboard focus")
      widget.options = [widget.options[1], widget.options[0]]
      check(namedChild(widget, "providerTile-claude") === tile, "a new order moves tiles instead of rebuilding them")
      widget.destroy()
      root.widget = null
      return true
    },
    function () {
      if (card.opacity !== 0) return waited < 40 ? false : check(false, "hover card fades out")
      check(!cardWindow.held && !cardWindow.visible, "the faded card's window closes")
      console.log("Bar QML contract: passed (components)")
      Qt.quit()
      return false
    }
  ]

  // The counted accounts as the chip's dots, the provider's tile and the Limits rows show them.
  function countedEverywhere(providerId) {
    var chip = namedChild(widget, "barChip-" + providerId)
    var chipDots = chip && chip.strip ? chip.strip.dots.filter(function (dot) { return dot.counted }).map(function (dot) { return dot.index }) : []
    var tile = widget.providerOptions.filter(function (option) { return option.value === providerId })[0]
    var tileDots = tile && tile.dots ? tile.dots.dots.filter(function (dot) { return dot.counted }).map(function (dot) { return dot.index }) : []
    var rows = []
    for (var i = 0; i < widget.proxyAccounts.length; i++) {
      var row = widget.accountList.rowFor(String(widget.proxyAccounts[i].accountId))
      if (row && row.counted) rows.push(i)
    }
    return JSON.stringify(chipDots) + " | " + JSON.stringify(tileDots) + " | " + JSON.stringify(rows)
  }
  // A copy of the backend's payload with Claude's first account's 5-hour window changed.
  function changeWork(change) {
    var copy = JSON.parse(JSON.stringify(widget.usageBackend.payload))
    change(copy.providers.filter(function (provider) { return provider.id === "claude" })[0].accounts[0].windows[0])
    widget.usageBackend.payload = copy
  }

  readonly property var panelSteps: [
    function () {
      root.live = Qt.createQmlObject('import QtQuick; QtObject { signal request(var event); '
        + 'property var recentByAccount: ({}); property var requestLog: []; property int requestRevision: 0; '
        + 'property string state: "live"; property string message: "" }', root, "live")
      root.widget = create("Panel.qml", panelHost, { moduleName: "test.bar", ipcTarget: "test.bar",
        settings: { enabledProviders: ["claude", "codex"], barProviders: ["claude", "codex"], barAccountMode: "chips",
          refreshIntervalSec: 3600 } })
      widget.ompActivity = live
      return true
    },
    function () {
      if (widget.providers.length < 2) return waited < 150 ? false : check(false, "synthetic accounts load")
      var chips = namedChildren(widget, "barChip-", [])
      check(chips.length > 0 && chips.length <= 4, "chips per account stay within the four-chip cap, got " + chips.length)
      check(namedChild(widget, "barOverflowChip").visible, "the provider that does not fit folds into +N")
      widget.settings = Object.assign({}, widget.settings, { barMaxChips: 0 })
      return true
    },
    function () {
      // One chip per account with used-up accounts hidden: a used-up Claude login between Personal and
      // the login in use leaves, and the chips left must point at the two logins the bar still has.
      root.savedPayload = widget.usageBackend.payload
      var copy = JSON.parse(JSON.stringify(savedPayload))
      var claude = copy.providers.filter(function (provider) { return provider.id === "claude" })[0]
      var inUse = claude.accounts[0]
      var personal = claude.accounts[1]
      var spent = JSON.parse(JSON.stringify(personal))
      spent.accountId = "spent"
      spent.label = "Spent"
      spent.windows[1].used = 100
      spent.windows[1].remaining = 0
      claude.accounts = [personal, spent, inUse]
      widget.usageBackend.payload = copy
      widget.settings = Object.assign({}, widget.settings, { hideExhaustedProviders: true })
      return true
    },
    function () {
      var chips = namedChildren(widget, "barChip-claude@", [])
      var keys = chips.map(function (chip) { return chip.objectName }).sort()
      check(JSON.stringify(keys) === JSON.stringify(["barChip-claude@main", "barChip-claude@personal"]),
        "hiding a used-up login keeps a chip for each of the others: " + JSON.stringify(keys))
      var underlined = chips.filter(function (chip) {
        var line = namedChild(chip, "barAccountUnderline")
        return line && line.visible
      })
      check(underlined.length === 1 && underlined[0].objectName === "barChip-claude@main",
        "and the login in use is still the one underlined")
      widget.usageBackend.payload = savedPayload
      widget.settings = Object.assign({}, widget.settings, { hideExhaustedProviders: false })
      return true
    },
    function () {
      var chips = namedChildren(widget, "barChip-", [])
      check(chips.length === 6, "without a cap: 2 Claude logins and 4 of 5 Codex accounts, got " + chips.length)
      var underlined = chips.filter(function (chip) {
        var line = namedChild(chip, "barAccountUnderline")
        return chip.objectName.indexOf("barChip-claude@") === 0 && line && line.visible
      })
      check(underlined.length === 1 && underlined[0].objectName === "barChip-claude@main", "the login in use is underlined")
      check(namedChild(chips[0], "barAccountInitial").visible, "account chips carry the account's initial")
      widget.settings = Object.assign({}, widget.settings, { barAccountMode: "dots" })
      widget.selectProviderId("claude")
      return true
    },
    function () {
      var chips = namedChildren(widget, "barChip-", [])
      check(chips.length === 2, "one chip per provider with dots, got " + chips.length)
      var claudeDots = namedChild(namedChild(widget, "barChip-claude"), "barAccountDots")
      var codexDots = namedChild(namedChild(widget, "barChip-codex"), "barAccountDots")
      check(claudeDots.visible && claudeDots.dotCount === 2, "Claude shows two dots")
      check(codexDots.visible && codexDots.dotCount === 3 && codexDots.extra === 2, "Codex shows three dots and +2")
      check(namedChild(namedChild(widget, "barChip-claude"), "barAccountRemaining").text === "72%", "value of the login in use")
      check(namedChild(widget, "barChip-claude").tooltipText === "", "the hover card replaces the tooltip")
      live.request({ type: "request", provider: "claude", accountId: "main", at: now })
      check(claudeDots.lastPingAt["0"] !== undefined, "a live request rings from the account's dot")
      // Tiles survive the clock and live requests (M1).
      var tile = namedChild(widget.providerTiles, "providerTile-claude")
      widget.nowMs = Date.now() + 1500
      live.recentByAccount = { "codex@omp-000000000001": Date.now() / 1000 }
      check(tile !== null && namedChild(widget.providerTiles, "providerTile-claude") === tile, "a tick and a live request keep the tile")
      // omp names Personal by its own id: the request reaches the native login (M2).
      live.recentByAccount = { "claude@omp-0123456789ab": Date.now() / 1000 }
      check(widget.accountStateOf(widget.providers[0]).spending[1] === true, "omp's request makes Personal spend now")
      live.request({ type: "request", provider: "claude", accountId: "omp-0123456789ab", at: Date.now() / 1000 })
      check(claudeDots.lastPingAt["1"] !== undefined, "and rings from Personal's dot")
      return true
    },
    function () {
      var chip = namedChild(widget, "barChip-claude")
      check(chip.topParts.tag !== "" && namedChild(chip, "barAccountRemainingTag").visible,
        "a chip line carries its limit period by default: " + JSON.stringify(chip.topParts))
      widget.settings = Object.assign({}, widget.settings, { barShowPeriods: false })
      return true
    },
    function () {
      var chip = namedChild(widget, "barChip-claude")
      check(chip.topParts.tag === "" && chip.bottomParts.tag === "", "Show limit period off drops the tags")
      check(!namedChild(chip, "barAccountRemainingTag").visible && !namedChild(chip, "barAccountRemainingTopTag").visible
        && !namedChild(chip, "barAccountRemainingBottomTag").visible, "and hides them, so the chip line keeps no room for one")
      widget.settings = Object.assign({}, widget.settings, { barShowPeriods: true })
      return true
    },
    function () {
      check(countedEverywhere("claude") === "[0] | [0] | [0]", "one at a time, chip, tile and rows count Work: " + countedEverywhere("claude"))
      check(widget.selectedAccount && widget.selectedAccount.accountId === "main", "the detail shows the counted login")
      // Flashes (M3): a rolling window shedding use stays quiet, a real reset flashes once.
      var chip = namedChild(widget, "barChip-claude")
      var flashes = chip.flashes
      changeWork(function (row) { row.used = 62; row.remaining = 38 })
      check(chip.flashes === flashes, "use falling while the reset is far off is no reset")
      changeWork(function (row) { row.resetsAt = Math.floor(Date.now() / 1000) - 30 })
      changeWork(function (row) { row.used = 2; row.remaining = 98; row.resetsAt = Math.floor(Date.now() / 1000) + 18000 })
      check(chip.flashes === flashes + 1 && chip.lastFlash === "reset", "a window that reset flashes once: " + chip.lastFlash)
      widget.settings = Object.assign({}, widget.settings, { accountModes: '{"claude":"together"}' })
      return true
    },
    function () {
      check(widget.accountMode === "together", "Claude is used together")
      check(countedEverywhere("claude") === "[1] | [1] | [1]", "together, chip, tile and rows count Personal: " + countedEverywhere("claude"))
      // The detail stays on the account it showed (M6), across readings too.
      check(widget.selectedAccount.accountId === "main", "the detail does not follow the counted account mid-view")
      widget.usageBackend.payload = JSON.parse(JSON.stringify(widget.usageBackend.payload))
      check(widget.selectedAccount.accountId === "main", "a new reading keeps the detail")
      widget.selectProviderId("codex")
      widget.selectProviderId("claude")
      return true
    },
    function () {
      check(widget.selectedAccount.accountId === "personal", "choosing the provider again shows the counted account")
      widget.settings = Object.assign({}, widget.settings, { sources: JSON.stringify([{ id: "p-1a2b3c4d", kind: "proxy",
        url: "https://proxy.test/prefix", keyFile: "/private/proxy key" }]) })
      return true
    },
    function () {
      if (!widget.proxyMode || widget.providers.length < 2 || accountCount(widget, "codex") < 3)
        return waited < 150 ? false : check(false, "the proxy's accounts load")
      widget.selectProviderId("codex")
      return true
    },
    function () {
      check(countedEverywhere("codex") === "[0] | [0] | [0]", "through a proxy, chip, tile and rows count the same account: "
        + countedEverywhere("codex"))
      console.log("Bar QML contract: passed (panel chips)")
      Qt.quit()
      return false
    }
  ]

  function accountCount(panel, providerId) {
    var reading = panel.providers.filter(function (provider) { return provider.id === providerId })[0]
    return reading && reading.accounts ? reading.accounts.length : 0
  }

  Timer {
    interval: 40
    running: true
    repeat: true
    onTriggered: {
      root.ticks++
      root.check(root.ticks < 400, "timed out at step " + root.step + " of " + root.phaseName)
      var steps = root.phaseName === "panel" ? root.panelSteps : root.componentSteps
      if (root.step >= steps.length) return
      if (steps[root.step]()) {
        root.step++
        root.waited = 0
      } else {
        root.waited++
      }
    }
  }
}
