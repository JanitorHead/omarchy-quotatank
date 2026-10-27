import QtQuick
import Quickshell.Io
import qs.Commons

// Quotatank's motion tokens. Panel owns one instance (`motion`) and hands it to every component that
// animates, so durations and the reduced-motion choice live in one place. Omarchy 4.0.4's Style has no
// motion tokens; a Style that reports `reduceMotion` is followed, otherwise Hyprland's
// `animations:enabled` is read at start and whenever the panel opens. The Display setting `motion`
// ("system" | "reduced") can force reduced motion. Reduced motion zeroes every duration: changes still
// happen, they just do not move.
QtObject {
  id: root

  // Display → Motion: "system" follows Omarchy/Hyprland, "reduced" turns animation off.
  property string preference: "system"
  // Re-reads Hyprland's setting each time this turns true (Panel binds it to `opened`).
  property bool panelOpen: false
  // Hyprland's answer; only used when Style has no reduceMotion of its own.
  property bool systemReduced: false
  readonly property var styleReduceMotion: Style["reduceMotion"]
  property bool reduced: preference === "reduced"
    || (styleReduceMotion !== undefined ? styleReduceMotion === true : systemReduced)

  readonly property int micro: 160    // hover, colour, toggles
  readonly property int row: 260      // rows, bars, dots
  readonly property int morph: 420    // chart, lanes
  readonly property int digit: 350    // rolling digits
  readonly property int popIn: 180    // hover card in
  readonly property int popOut: 120   // hover card out
  readonly property int flash: 600    // one-shot alerts
  readonly property int ping: 700     // spend ring

  // Enter decelerates, a move eases both ways, an exit accelerates away.
  readonly property int easeEnter: Easing.OutCubic
  readonly property int easeMove: Easing.InOutCubic
  readonly property int easeExit: Easing.InCubic

  function duration(ms) {
    if (reduced) return 0
    var value = Math.round(Number(ms))
    return isFinite(value) && value > 0 ? value : 0
  }

  function refresh() {
    if (styleReduceMotion !== undefined || probeProcess.running) return
    probeProcess.body = ""
    probeProcess.running = true
  }

  function applyOption(text) {
    var parsed = null
    try { parsed = JSON.parse(String(text || "")) } catch (error) { parsed = null }
    if (!parsed || typeof parsed !== "object") return
    var enabled = Number(parsed.int)
    if (isFinite(enabled)) systemReduced = enabled === 0
  }

  onPanelOpenChanged: if (panelOpen) refresh()
  Component.onCompleted: refresh()

  // hyprctl answers with one short JSON object; anything past 4 KiB is not that answer.
  property Process probe: Process {
    id: probeProcess
    property string body: ""
    command: ["hyprctl", "-j", "getoption", "animations:enabled"]
    stdout: SplitParser {
      splitMarker: ""
      onRead: function(data) {
        if (probeProcess.body.length < 4096) probeProcess.body += String(data).slice(0, 4096 - probeProcess.body.length)
      }
    }
    onExited: function(exitCode) {
      if (exitCode === 0) root.applyOption(probeProcess.body)
      probeProcess.body = ""
    }
  }

  // A compositor that does not answer must not leave the probe running.
  property Timer probeTimeout: Timer {
    interval: 3000
    running: probeProcess.running
    onTriggered: probeProcess.running = false
  }
}
