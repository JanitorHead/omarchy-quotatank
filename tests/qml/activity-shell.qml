import QtQuick
import Quickshell

ShellRoot {
  id: root
  property var backend: null
  property int phase: 0
  property int ticks: 0
  property var startupProbe: null
  property bool startupVerified: false
  function proxyWith(keeperUrl, passwordFile) {
    return { id: "p-1a2b3c4d", kind: "proxy", on: true, url: "http://synthetic.invalid", keyFile: "",
      keeperUrl: keeperUrl, keeperPasswordFile: passwordFile || "" }
  }
  QtObject {
    id: usage
    property var proxy: root.proxyWith("http://synthetic.invalid/old")
    readonly property string usageSource: proxy ? "cliproxy" : "direct"
    readonly property string cliproxyUrl: proxy ? proxy.url : ""
    readonly property string cliproxyKeyFile: proxy ? proxy.keyFile : ""
    readonly property string connectionId: JSON.stringify([usageSource, cliproxyUrl])
    function localPath(url) { return String(url).replace("file://", "") }
  }
  QtObject {
    id: probeUsage
    property var proxy: root.proxyWith("http://synthetic.invalid/old")
    readonly property string usageSource: "cliproxy"
    readonly property string cliproxyUrl: "http://synthetic.invalid"
    readonly property string cliproxyKeyFile: ""
    readonly property string connectionId: JSON.stringify([usageSource, cliproxyUrl])
    function localPath(url) { return String(url).replace("file://", "") }
  }
  Item { id: host }
  function check(condition, message) {
    if (!condition) { console.error("ACTIVITY TEST FAILED: " + message); Qt.exit(1) }
  }
  Component.onCompleted: {
    var component = Qt.createComponent(Quickshell.env("QUOTATANK_REPO_URL") + "/UsageActivityBackend.qml")
    check(component.status === Component.Ready, component.errorString())
    backend = component.createObject(host, { usageBackend: usage,
      scriptPath: Quickshell.env("QUOTATANK_FAKE_ACTIVITY") })
    check(backend !== null, "create activity backend")
    startupProbe = component.createObject(host, { usageBackend: probeUsage,
      scriptPath: Quickshell.env("QUOTATANK_FAKE_ACTIVITY") })
    startupProbe.providersChanged.connect(function() {
      if (!startupProbe.providers.length) return
      root.check(startupProbe.providers[0].accountId === "new", "startup response uses its original connection")
      root.startupVerified = true
    })
    startupProbe.refresh()
    probeUsage.proxy = proxyWith("http://synthetic.invalid/new")
    startupProbe.refresh()
    startupProbe.refresh()
  }
  Timer {
    interval: 40
    running: true
    repeat: true
    onTriggered: {
      root.ticks++
      root.check(root.ticks < 150, "state machine timed out at " + root.phase)
      var b = root.backend
      if (root.phase === 0 && root.ticks >= 2) {
        usage.proxy = root.proxyWith("http://synthetic.invalid/new", Quickshell.env("QUOTATANK_ACTIVITY_MARKER"))
        root.check(b.providers.length === 0, "changing Keeper clears activity immediately")
        root.phase++
      } else if (root.phase === 1 && b.providers.length > 0) {
        root.check(b.providers[0].accountId === "new", "old process cannot overwrite changed connection")
        root.check(b.lastSuccessAt > 0, "success records freshness")
        b.refresh()
        root.phase++
      } else if (root.phase === 2 && b.fetchError !== "") {
        root.check(b.providers[0].accountId === "new", "outage preserves last-known activity")
        root.check(b.notice === "Synthetic outage", "outage is explained")
        usage.proxy = null
        root.check(!b.trackingEnabled && b.providers.length === 0, "direct mode disables and clears tracking")
        usage.proxy = root.proxyWith("http://synthetic.invalid/oversized")
        root.phase++
      } else if (root.phase === 3 && b.fetchError !== "") {
        root.check(b.providers.length === 0, "oversized output cannot supply account activity")
        usage.proxy = root.proxyWith("")
        root.check(!b.trackingEnabled && b.notice.indexOf("Configure") >= 0, "missing Keeper gives setup guidance")
        root.check(root.startupVerified, "activity startup probe completed")
        console.log("Activity QML contract: passed")
        Qt.quit()
      }
    }
  }
}
