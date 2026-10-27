pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

// ACCOUNTS: one row per account of the selected provider. Rows live in a ListModel keyed by account,
// kept in step with move()/insert()/remove(), so a row keeps its delegate across readings and a new
// order slides rows to their places instead of rebuilding the list. What a row says about counting,
// spending, its ring and "in use" comes from the provider's UsageLogic.accountState, the same the chip,
// its hover card and the tile read.
Column {
  id: root

  property string providerId: ""
  property var accounts: []
  // Display names, by account index (the panel applies the email privacy setting).
  property var names: []
  // UsageLogic.accountState() of the provider: mode, counted, spending, rings, inUse and the row order.
  property var accountState: null
  readonly property string mode: accountState ? accountState.mode : "single"
  readonly property var counted: accountState ? accountState.counted : []
  // Display order as account indexes.
  readonly property var order: accountState ? accountState.order : []
  property string selectedId: ""
  property real nowSeconds: 0
  // Newest switch or reset per "<provider>@<accountId>".
  property var events: ({})
  property bool resetsActionable: false
  property string useBusyId: ""
  property string headerText: ""
  property string quotaMode: "Used"
  property real warningThreshold: 25
  property real criticalThreshold: 10
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family
  property string clockFormat: "HH:mm"
  property real cardRadius: 0
  property var motion: null
  // Order changes slide; a different provider's accounts simply replace the rows.
  property bool animated: false
  readonly property alias view: rowRepeater
  readonly property alias rowModel: rows

  signal accountSelected(string accountId)
  signal useRequested(string accountId)
  signal resetRequested(string accountId)

  function rowKey(index) {
    var account = accounts[index]
    return providerId + "@" + String(account && account.accountId || index)
  }

  function indexOfKey(key) {
    for (var i = 0; i < accounts.length; i++)
      if (rowKey(i) === key) return i
    return -1
  }

  // The row delegate showing an account, or null.
  function rowFor(accountId) {
    for (var i = 0; i < rowRepeater.count; i++) {
      var item = rowRepeater.itemAt(i)
      if (item && item.accountId === String(accountId)) return item
    }
    return null
  }

  function clock(epochSeconds) {
    var seconds = Number(epochSeconds)
    return Qt.formatDateTime(new Date(seconds * 1000), UsageLogic.clockPattern(seconds, nowSeconds, clockFormat))
  }

  // The newest point of an account's sparkline: when its reading was taken, where its 24 h buckets end.
  function readingEnd(account) {
    var at = account && account.activity ? Number(account.activity.lastReadingAt) : NaN
    if (isFinite(at) && at > 0) return at
    var fetched = new Date(String(account && account.fetchedAt || "")).getTime()
    return isFinite(fetched) && fetched > 0 ? fetched / 1000 : nowSeconds
  }

  function statusText(status) {
    if (!status || status.text === "") return ""
    if (status.at === null || status.at === undefined) return status.text
    return status.text + (status.kind === "usedup" ? " · back " : " ") + clock(status.at)
  }

  function sync() {
    var keys = []
    var wanted = UsageLogic.listOrEmpty(order)
    for (var i = 0; i < wanted.length; i++) {
      var key = rowKey(wanted[i])
      if (keys.indexOf(key) < 0) keys.push(key)
    }
    var overlap = false
    for (var j = 0; j < rows.count && !overlap; j++) overlap = keys.indexOf(rows.get(j).rowKey) >= 0
    animated = overlap
    UsageLogic.syncKeyedOrder({
      count: function() { return rows.count },
      keyAt: function(index) { return rows.get(index).rowKey },
      move: function(from, to) { rows.move(from, to, 1) },
      insert: function(index, value) { rows.insert(index, { rowKey: value }) }
    }, keys)
    while (rows.count > keys.length) rows.remove(rows.count - 1)
  }

  onAccountsChanged: Qt.callLater(sync)
  onOrderChanged: Qt.callLater(sync)
  onProviderIdChanged: Qt.callLater(sync)
  Component.onCompleted: sync()

  spacing: Style.spacing.md

  Item {
    width: parent.width
    implicitHeight: Math.max(sectionTitle.implicitHeight, modeText.implicitHeight)

    Ui.PanelSectionHeader {
      id: sectionTitle
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      text: "ACCOUNTS"
      foreground: root.foreground
      fontFamily: root.fontFamily
    }

    PlainText {
      id: modeText
      objectName: "accountsMode"
      anchors.right: parent.right
      anchors.left: sectionTitle.right
      anchors.leftMargin: Style.spacing.controlGap
      anchors.verticalCenter: parent.verticalCenter
      text: root.headerText
      color: Qt.darker(root.foreground, 1.55)
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      horizontalAlignment: Text.AlignRight
      elide: Text.ElideLeft
    }
  }

  ListModel { id: rows }

  // Rows sit in a Column, so every delegate exists even while the panel is closed. A ListModel move
  // restacks the same delegates, and the column slides the ones that change places.
  Column {
    id: list
    objectName: "accountRows"
    width: parent.width
    spacing: Style.spacing.md

    move: Transition {
      enabled: root.animated
      NumberAnimation { properties: "y"; duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.InOutCubic }
    }
    add: Transition {
      enabled: root.animated
      NumberAnimation { property: "opacity"; from: 0; to: 1; duration: root.motion ? root.motion.duration(root.motion.row) : 0; easing.type: Easing.OutCubic }
    }

    Repeater {
      id: rowRepeater
      model: rows

      delegate: AccountRow {
        id: row
        required property string rowKey
        required property int index
        readonly property int accountIndex: root.indexOfKey(rowKey)
        readonly property var accountData: accountIndex >= 0 ? root.accounts[accountIndex] : null
        readonly property string accountId: accountData ? String(accountData.accountId || "") : ""
        readonly property var status: UsageLogic.accountStatusLine(accountData, spending, root.nowSeconds,
          root.events[root.providerId + "@" + accountId] || null)

        objectName: "accountRow-" + accountId
        width: list.width
        account: accountData
        name: root.names[accountIndex] || ""
        selected: accountId !== "" && accountId === root.selectedId
        counted: UsageLogic.contains(root.counted, accountIndex)
        spending: !!root.accountState && root.accountState.spending[accountIndex] === true
        severity: root.accountState && accountIndex >= 0 ? String(root.accountState.rings[accountIndex]) : "unknown"
        statusText: root.statusText(status)
        statusTone: status.tone
        sparkValues: accountData && accountData.history ? UsageLogic.listOrEmpty(accountData.history.h24) : []
        sparkEnd: root.readingEnd(accountData)
        inUse: !!root.accountState && root.accountState.inUse[accountIndex] === true
        canUse: UsageLogic.accountCanUse(accountData, root.mode)
        useBusy: root.useBusyId !== "" && root.useBusyId === accountId
        // Rows read through a proxy carry their banked resets; elsewhere the selected account's detail does, beside Use.
        resetCount: UsageLogic.readingProxy(accountData) && UsageLogic.accountResetShown(accountData) ? UsageLogic.accountResetCount(accountData) : -1
        resetEnabled: root.resetsActionable && UsageLogic.accountResetActionable(accountData)
        quotaMode: root.quotaMode
        warningThreshold: root.warningThreshold
        criticalThreshold: root.criticalThreshold
        foreground: root.foreground
        urgent: root.urgent
        fontFamily: root.fontFamily
        clockFormat: root.clockFormat
        cardRadius: root.cardRadius
        motion: root.motion
        onSelectRequested: root.accountSelected(accountId)
        onUseRequested: root.useRequested(accountId)
        onResetRequested: root.resetRequested(accountId)
      }
    }
  }
}
