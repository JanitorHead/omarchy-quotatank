pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons

// Meter style "Waveform", a voice note recording. Each bar is 1/N of the limit; a spent bar's height says
// how fast that share went (peaks are bursts, from the window's samples), the bars brightening toward the
// newest. Past the fill, small dashes run as far as this pace takes the limit by its reset (red when it runs
// out first) and dots mark the rest. While the account spends, the bar being filled and the two before it
// oscillate, wider under more pressure, with a peak on each request. The pace tick is a pair of short
// marks above and below the strip. Under Remaining, the fill is what is left: calm even bars from the
// left, the share this pace would spend by the reset dimmed at their end, and the spent bars recorded
// dimly on the right, newest at the edge, where the live bars eat leftward. Row: the same strip, finer.
//
// The strip is one Repeater whose bars change only when the samples, the use, the size or the side do;
// only the three live bars follow the shared clock.
Item {
  id: root

  property var host: null
  property string variant: "card"
  readonly property var model: host ? host.model : null
  readonly property bool remaining: !!model && model.quotaMode === "Remaining"
  readonly property bool small: variant === "row"
  readonly property real used: model ? Math.max(0, Math.min(100, model.used)) : 0
  // The pace tick on the chosen side (0-1), drawn only while the host asks for it.
  readonly property real markValue: model ? model.markValue : -1
  readonly property bool markShown: !!host && host.markShown && markValue >= 0 && !model.exhausted

  // Geometry: bars of `barWidth` every `pitch` pixels, as many as fit.
  readonly property int pitch: small ? Math.max(2, Style.space(3)) : Math.max(3, Style.space(4))
  readonly property int barWidth: Math.max(1, Math.round(pitch * (small ? 0.55 : 0.6)))
  readonly property int count: Math.max(0, Math.floor((width + pitch - barWidth) / pitch))
  readonly property real maxHeight: Math.max(2, height - (small ? Style.space(1) : Style.space(4)))
  readonly property real mid: height / 2

  // Chunks of the limit, counted from the first spent (0): how many are spent, the one being spent now and
  // how much of it, and the last one this pace reaches by the reset (-1 when there is no forecast).
  readonly property real spent: used / 100 * count
  readonly property int edge: Math.ceil(spent - 1e-9) - 1
  readonly property real edgeFill: edge >= 0 ? spent - edge : 0
  readonly property int forecastEdge: {
    if (!model || !model.forecastShown) return -1
    var projected = model.runsOut ? 100 : remaining ? 100 - model.forecastFrom * 100 : model.forecastTo * 100
    return Math.min(count - 1, Math.ceil(projected / 100 * count - 1e-9) - 1)
  }
  readonly property var levels: levelsOf(count)

  // Motion only while the account spends, on the shared clock.
  readonly property bool running: visible && !!model && model.moving && model.hasMeter
    && !!host && !!host.motion && !host.motion.reduced
  readonly property real liveSeconds: running ? host.motion.liveSeconds : 0
  // The pace's tempo (pressure in steps, 1 = it runs out at the reset), capped so bursts stay readable.
  readonly property real pressure: model ? Math.max(0, Math.min(1.5, model.tempo)) : 0
  // The card's edge bar jumps on each omp request and settles over half a second.
  readonly property real kick: {
    if (!running || small || !(model.requestAt > 0)) return 0
    var age = liveSeconds - model.requestAt
    return age >= 0 && age < 0.5 ? 1 - age / 0.5 : 0
  }
  // The live chunks: the one being spent and the two before it (under Remaining, the next two to go).
  readonly property int liveFrom: remaining ? edge : edge - 2
  readonly property int liveTo: remaining ? Math.min(count - 1, edge + 2) : edge

  function alpha(color, opacity) { return Qt.rgba(color.r, color.g, color.b, opacity) }
  function chunkAt(position) { return remaining ? count - 1 - position : position }
  function isLive(chunk) { return running && edge >= 0 && chunk >= Math.max(0, liveFrom) && chunk <= liveTo }

  // The window's use as [[epoch seconds, used %], …] from its start (at 0, the reset) to the latest use.
  // With no readings the line runs straight from 0 to the current use, so every bar gets the same level.
  function historyPoints() {
    var start = model.windowSeconds > 0 && model.resetsAt > 0 ? model.resetsAt - model.windowSeconds : -1
    var list = model.samples || []
    var points = []
    for (var i = 0; i < list.length; i++) {
      var stamp = Number(list[i][0])
      var value = Number(list[i][1])
      if (!isFinite(stamp) || !isFinite(value) || (start >= 0 && stamp < start)) continue
      points.push([stamp, Math.max(0, Math.min(100, value))])
    }
    if (points.length === 0) return [[0, 0], [1, used]]
    if (points[0][1] > 0) points.unshift([start >= 0 ? Math.min(start, points[0][0]) : points[0][0] - 1, 0])
    // A reading newer than the samples: now is only read in that case, so the bars do not rebuild every second.
    if (points[points.length - 1][1] < used) points.push([Math.max(model.nowSeconds, points[points.length - 1][0] + 1), used])
    return points
  }

  // How fast each 1/N of the limit was spent, 0-1 (log-scaled against the fastest and slowest share),
  // null for shares not spent yet: the gallery's intensity(). The first moment each share's start and end
  // were reached is found in one forward sweep, since it only moves forward as the use grows.
  function levelsOf(chunks) {
    if (!model || chunks <= 0) return []
    var points = historyPoints()
    var hit = 1
    function timeAt(value) {
      while (hit < points.length && points[hit][1] < value) hit++
      if (hit >= points.length) return points[points.length - 1][0]
      var a = points[hit - 1]
      var b = points[hit]
      var share = b[1] > a[1] ? Math.max(0, Math.min(1, (value - a[1]) / (b[1] - a[1]))) : 0
      return a[0] + (b[0] - a[0]) * share
    }
    var step = 100 / chunks
    var rates = []
    for (var chunk = 0; chunk < chunks; chunk++) {
      var from = chunk * step
      var to = Math.min(used, (chunk + 1) * step)
      if (from >= used) { rates.push(null); continue }
      var hours = Math.max(1e-3, (timeAt(to) - timeAt(from)) / 3600)
      rates.push(Math.log(1 + (to - from) / hours))
    }
    // Readings come every few minutes, so neighbouring shares straddle them unevenly; a light 1-2-1
    // smoothing turns that comb into the bursts and lulls it stands for.
    var smooth = []
    var low = Infinity
    var high = -Infinity
    for (var s = 0; s < rates.length; s++) {
      if (rates[s] === null) { smooth.push(null); continue }
      var sum = 2 * rates[s]
      var weight = 2
      if (s > 0 && rates[s - 1] !== null) { sum += rates[s - 1]; weight += 1 }
      if (s + 1 < rates.length && rates[s + 1] !== null) { sum += rates[s + 1]; weight += 1 }
      smooth.push(sum / weight)
      low = Math.min(low, sum / weight)
      high = Math.max(high, sum / weight)
    }
    var result = []
    for (var r = 0; r < smooth.length; r++)
      result.push(smooth[r] === null ? null : high - low < 1e-6 ? 0.5 : (smooth[r] - low) / (high - low))
    return result
  }

  // A spent bar's height from its level; the shares still left under Remaining stand at an even height.
  function barHeight(level) { return Math.max(2, maxHeight * (0.12 + 0.88 * level)) }

  implicitHeight: small ? Style.space(10) : Style.space(30)

  LiveClaim {
    motion: root.host ? root.host.motion : null
    active: root.visible && !!root.model && root.model.moving && root.model.hasMeter
  }

  Item {
    id: strip
    objectName: root.small ? "waveRow" : "waveStrip"
    visible: !!root.model && root.model.hasMeter && (root.variant === "card" || root.variant === "row")
    anchors.fill: parent

    Repeater {
      model: strip.visible ? root.count : 0

      Rectangle {
        id: bar
        required property int index
        readonly property int chunk: root.chunkAt(index)
        readonly property bool isSpent: chunk < root.edge || (chunk === root.edge && (!root.remaining || root.edgeFill >= 1))
        readonly property bool inForecast: !isSpent && chunk <= root.forecastEdge
        readonly property bool runsOut: !!root.model && root.model.runsOut
        // Used: spent bars are the fill. Remaining: what is left is the fill, the spent bars a dim record.
        readonly property bool isFill: root.remaining ? !isSpent : isSpent
        readonly property real level: isSpent ? (root.levels[chunk] === null || root.levels[chunk] === undefined ? 0.5 : root.levels[chunk]) : 0

        visible: !root.isLive(chunk)
        x: index * root.pitch
        width: root.barWidth
        height: isSpent ? root.barHeight(level)
          : isFill ? root.maxHeight * 0.55
          : inForecast ? Math.max(2, Style.space(3)) : Math.max(1, Style.space(2))
        y: Math.round(root.mid - height / 2)
        radius: isSpent || isFill ? width / 2 : 0
        color: !root.host ? "transparent"
          : root.remaining && isSpent ? root.alpha(root.host.foreground, 0.24)
          : isFill && inForecast && runsOut ? root.host.urgent
          : isFill ? root.host.tone
          : inForecast ? (runsOut ? root.alpha(root.host.urgent, 0.8) : root.alpha(root.host.tone, 0.5))
          : root.alpha(root.host.foreground, 0.2)
        // Spent bars brighten toward the newest; the one being spent lights as a whole by how full it is.
        // Under Remaining the forecast's share of the fill is dimmed.
        opacity: !isFill ? 1
          : root.remaining ? (inForecast ? 0.45 : 1) * (chunk === root.edge ? 0.3 + 0.7 * (1 - root.edgeFill) : 1)
          : (0.5 + 0.5 * chunk / Math.max(1, root.edge)) * (chunk === root.edge ? 0.3 + 0.7 * root.edgeFill : 1)
      }
    }

    // The live bars: the share being spent and its neighbours oscillate on the shared clock.
    Repeater {
      model: strip.visible && root.running && root.edge >= 0 ? Math.max(0, root.liveTo - Math.max(0, root.liveFrom) + 1) : 0

      Rectangle {
        required property int index
        readonly property int chunk: Math.max(0, root.liveFrom) + index
        readonly property real swing: Math.abs(Math.sin(root.liveSeconds * (3 + 2 * root.pressure) + chunk * 1.7))
          * Math.max(0.4, Math.min(1, 0.4 + root.pressure * 0.5))
        objectName: chunk === root.edge ? "waveLiveEdge" : ""
        x: root.chunkAt(chunk) * root.pitch
        width: root.barWidth
        height: Math.max(2, root.maxHeight * Math.min(1, 0.25 + 0.75 * swing + (chunk === root.edge ? root.kick : 0)))
        y: Math.round(root.mid - height / 2)
        radius: width / 2
        color: root.host ? Qt.lighter(root.host.tone, 1.25) : "transparent"
      }
    }

    // The pace tick: where even use would be by now, as short marks above and below the strip.
    Repeater {
      model: strip.visible && root.markShown ? 2 : 0

      Rectangle {
        required property int index
        objectName: index === 0 ? "wavePaceTick" : ""
        x: Math.min(root.count - 1, Math.floor(root.markValue * root.count)) * root.pitch + Math.round(root.barWidth / 2) - Math.round(width / 2)
        y: index === 0 ? 0 : strip.height - height
        width: Style.spacing.hairline
        height: Style.space(3)
        color: root.host ? root.alpha(root.host.foreground, 0.85) : "transparent"
      }
    }
  }
}
