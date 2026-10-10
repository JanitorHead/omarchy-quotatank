.pragma library

// One observer per connection across bars, monitors and open panels. The
// shared object has no panel parent; the final consumer explicitly stops it.
var liveConnections = ({})

function acquireLive(key, factory, properties) {
  var entry = liveConnections[key]
  if (!entry) {
    // Create in this engine-wide library context, not a consumer's context.
    // A parentless object alone still loses its functions when its creator dies.
    if (!factory) factory = Qt.createComponent("UsageLiveConnection.qml")
    var object = factory.createObject(null, properties)
    if (!object) return null
    entry = { object: object, references: 0 }
    liveConnections[key] = entry
  }
  entry.references++
  return entry.object
}

function releaseLive(key) {
  var entry = liveConnections[key]
  if (!entry) return
  entry.references--
  if (entry.references <= 0) {
    delete liveConnections[key]
    entry.object.stop()
  }
}

function validLivePayload(payload) {
  if (!payload || payload.schemaVersion !== 1) return false
  if (payload.heartbeat === true) return true
  if (!contains(["live", "reconnecting", "unavailable"], payload.state)
      || typeof payload.message !== "string" || payload.message.length > 256
      || !isListLike(payload.providers) || payload.providers.length > 4096
      || !isListLike(payload.accounts) || payload.accounts.length > 4096) return false
  var seen = ({})
  for (var p = 0; p < payload.providers.length; p++) {
    var provider = payload.providers[p]
    if (!provider || !/^[a-z0-9][a-z0-9_-]{0,63}$/.test(provider.id)
        || !contains(["ok", "ambiguous"], provider.status)
        || (provider.status === "ok" && !/^[a-f0-9]{16}$/.test(provider.accountId))
        || typeof provider.lastUsedAt !== "number" || !isFinite(provider.lastUsedAt)
        || provider.lastUsedAt <= 0) return false
  }
  for (var i = 0; i < payload.accounts.length; i++) {
    var row = payload.accounts[i]
    if (!row || !/^[a-f0-9]{16}$/.test(row.accountId)
        || !/^[a-z0-9][a-z0-9_-]{0,63}$/.test(row.provider)) return false
    if (seen[row.accountId]) return false
    seen[row.accountId] = true
    var counts = [row.inFlight, row.sessions]
    for (var j = 0; j < counts.length; j++)
      if (typeof counts[j] !== "number" || !isFinite(counts[j])
          || Math.floor(counts[j]) !== counts[j] || counts[j] < 0 || counts[j] > 1000000) return false
  }
  return payload.state === "live" || payload.accounts.length === 0
}

function accountLoad(account, activity) {
  if (!account || !activity || activity.liveState !== "live") return null
  var rows = listOrEmpty(activity.liveAccounts)
  for (var i = 0; i < rows.length; i++)
    if (rows[i].accountId === account.accountId && rows[i].provider === account.id) return rows[i]
  return null
}

function sessionBadgeText(load) {
  if (!load) return "Sessions unknown"
  return load.sessions + (load.sessions === 1 ? " session" : " sessions")
}

function sessionDetails(load) {
  if (!load) return "Session counts are unknown until Fusebox reconnects."
  return sessionBadgeText(load) + " assigned to this account recently. Sessions may remain assigned after a request finishes."
}

function proxyName(implementation) {
  if (implementation === "rust") return "Fusebox"
  if (implementation === "go") return "CLIProxyAPI"
  return "Fusebox / CLIProxyAPI"
}

function clamp(value, minimum, maximum) {
  var number = Number(value)
  if (!isFinite(number)) return minimum
  return Math.max(minimum, Math.min(maximum, number))
}

function isListLike(value) {
  if (!value || typeof value !== "object" || value.length === undefined) return false
  var length = Number(value.length)
  return isFinite(length) && length >= 0 && Math.floor(length) === length
}

function listOrEmpty(value) {
  return isListLike(value) ? value : []
}

function firstItems(value, limit) {
  var source = listOrEmpty(value)
  var count = Math.max(0, Math.min(Number(source.length), Math.floor(Number(limit) || 0)))
  var result = []
  for (var i = 0; i < count; i++) result.push(source[i])
  return result
}

function contains(value, needle) {
  var source = listOrEmpty(value)
  for (var i = 0; i < source.length; i++) {
    if (source[i] === needle) return true
  }
  return false
}

function trimNumber(value) {
  var absolute = Math.abs(value)
  var digits = absolute >= 100 ? 0 : (absolute >= 10 ? 1 : 2)
  return value.toFixed(digits).replace(/\.0+$/, "")
}

function formatTokens(value) {
  var amount = Number(value)
  if (!isFinite(amount)) return "—"
  var absolute = Math.abs(amount)
  if (absolute >= 1000000000000) return trimNumber(amount / 1000000000000) + "T"
  if (absolute >= 1000000000) return trimNumber(amount / 1000000000) + "B"
  if (absolute >= 1000000) return trimNumber(amount / 1000000) + "M"
  if (absolute >= 1000) return trimNumber(amount / 1000) + "K"
  return Math.round(amount).toString()
}

function formatUsd(value) {
  if (value === null || value === undefined || !isFinite(Number(value))) return "—"
  var amount = Number(value)
  if (Math.abs(amount) > 0 && Math.abs(amount) < 0.01) return "$" + amount.toFixed(4)
  // Grouped the same way Qt.locale("en_US") does, without depending on the QML
  // engine, so the formatter stays a pure function.
  var parts = Math.abs(amount).toFixed(2).split(".")
  var whole = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  return (amount < 0 ? "-$" : "$") + whole + "." + parts[1]
}

// Models of one provider, heaviest first, for the Limits view's token list.
function providerModels(models, providerId) {
  var rows = []
  var list = listOrEmpty(models)
  for (var i = 0; i < list.length; i++) {
    if (String(list[i] && list[i].provider || "") !== providerId) continue
    rows.push(list[i])
  }
  rows.sort(function(left, right) {
    return Number(right.totalTokens || 0) - Number(left.totalTokens || 0)
  })
  return rows
}

function minRemaining(provider) {
  if (!provider || provider.status !== "ok") return null
  // Repeater delegates expose nested JSON arrays as QML list-like objects on
  // some Quickshell builds. They still have length/index access, but fail
  // Array.isArray(), so do not reject them solely on that basis.
  var windows = provider.windows
  if (!isListLike(windows) || Number(windows.length) <= 0) return null
  var remaining = 101
  for (var i = 0; i < Number(windows.length); i++) {
    var row = windows[i]
    var raw = row ? row.remaining : null
    if (raw === null || raw === undefined || raw === "") continue
    var value = Number(raw)
    if (isFinite(value)) remaining = Math.min(remaining, value)
  }
  return remaining <= 100 ? clamp(remaining, 0, 100) : null
}

function severity(provider, warningThreshold, criticalThreshold, remaining) {
  var value = (remaining === undefined || remaining === null)
    ? minRemaining(provider) : Number(remaining)
  if (value === null || !isFinite(value)) return provider && provider.status === "error" ? "error" : "none"
  var critical = clamp(criticalThreshold, 0, 100)
  var warning = Math.max(critical, clamp(warningThreshold, 0, 100))
  if (value <= critical) return "critical"
  if (value <= warning) return "warning"
  return "ok"
}

// The menu bar can report one chosen limit instead of the most restrictive one.
// A window is matched by its reported duration first and by its id/label text
// second, so one choice works across providers that name windows differently
// (`session` vs `5 hour limit`, `Weekly limit`, and so on). The accepted
// spellings match the AI usage widget's `barWindow` setting, so the same value
// works for either plugin on the command line.
var WINDOW_SELECTORS = {
  session: { seconds: 18000, keywords: ["session", "5 hour", "5-hour", "hourly"] },
  weekly: { seconds: 604800, keywords: ["week"] },
  monthly: { seconds: 2592000, keywords: ["month"] }
}

function normalizeBarWindow(value) {
  var text = String(value === undefined || value === null ? "" : value).trim().toLowerCase()
  if (text === "" || text === "auto" || text === "highest" || text === "max" || text === "lowest") return "auto"
  if (text === "session" || text === "5h" || text === "5-hour" || text === "5hour"
      || text === "5hr" || text === "five-hour" || text === "rolling" || text === "session-5h") return "session"
  if (text === "weekly" || text === "week" || text === "7d" || text === "7-day" || text === "weekly-7d") return "weekly"
  if (text === "monthly" || text === "month" || text === "30d" || text === "monthly-cycle") return "monthly"
  return "auto"
}

// The second bar limit stacks under the first. `none` keeps the single-line chip.
function normalizeSecondaryBarWindow(value) {
  var text = String(value === undefined || value === null ? "" : value).trim().toLowerCase()
  if (text === "" || text === "none" || text === "off") return "none"
  var normalized = normalizeBarWindow(text)
  return normalized === "auto" ? "none" : normalized
}

// Per-provider menu bar limits, stored as JSON in `barProviderLimits`:
// {"opencode": {"top": "monthly", "bottom": "weekly"}}. A missing slot inherits the
// global `barWindow` / `barWindowSecondary`. Only canonical values are kept.
var BAR_LIMIT_CHOICES = {
  top: ["auto", "session", "weekly", "monthly"],
  bottom: ["none", "session", "weekly", "monthly"]
}

function parseBarLimits(text) {
  var parsed
  try { parsed = JSON.parse(String(text === undefined || text === null ? "{}" : text)) }
  catch (error) { return {} }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {}
  var result = {}
  var ids = Object.keys(parsed)
  for (var i = 0; i < ids.length; i++) {
    var entry = parsed[ids[i]]
    if (!entry || typeof entry !== "object") continue
    var limits = {}
    if (BAR_LIMIT_CHOICES.top.indexOf(entry.top) !== -1) limits.top = entry.top
    if (BAR_LIMIT_CHOICES.bottom.indexOf(entry.bottom) !== -1) limits.bottom = entry.bottom
    if (Object.keys(limits).length > 0) result[ids[i]] = limits
  }
  return result
}

function serializeBarLimits(limits) {
  var result = {}
  var ids = Object.keys(limits)
  for (var i = 0; i < ids.length; i++) {
    if (Object.keys(limits[ids[i]]).length > 0) result[ids[i]] = limits[ids[i]]
  }
  return JSON.stringify(result)
}

// `value` is "default" to inherit the global limit for that slot.
function setBarLimit(text, providerId, slot, value) {
  var limits = parseBarLimits(text)
  var entry = Object.assign({}, limits[providerId] || {})
  if (value === "default") delete entry[slot]
  else if (BAR_LIMIT_CHOICES[slot].indexOf(value) !== -1) entry[slot] = value
  else return serializeBarLimits(limits)
  if (Object.keys(entry).length > 0) limits[providerId] = entry
  else delete limits[providerId]
  return serializeBarLimits(limits)
}

// The top and bottom selectors one provider's chip uses: its override, else the global value.
function barLimitsFor(text, providerId, globalTop, globalBottom) {
  var entry = parseBarLimits(text)[providerId] || {}
  return {
    top: normalizeBarWindow(entry.top !== undefined ? entry.top : globalTop),
    bottom: normalizeSecondaryBarWindow(entry.bottom !== undefined ? entry.bottom : globalBottom)
  }
}

function windowSelectorLabel(selector) {
  var normalized = normalizeBarWindow(selector)
  if (normalized === "session") return "5-hour (session)"
  if (normalized === "weekly") return "7-day (weekly)"
  if (normalized === "monthly") return "Monthly"
  return "Lowest left (auto)"
}

// Label for the "Default" choice of one provider slot: names the global value it inherits.
function inheritedBarLimitLabel(slot, globalSelector) {
  var normalized = slot === "bottom" ? normalizeSecondaryBarWindow(globalSelector) : normalizeBarWindow(globalSelector)
  return "Global: " + (normalized === "none" ? "None" : windowSelectorLabel(normalized))
}

// Short period tag for stacked chips. Auto has no single period, so it has no tag.
function windowShortLabel(selector) {
  var normalized = normalizeBarWindow(selector)
  if (normalized === "session") return "5h"
  if (normalized === "weekly") return "7d"
  if (normalized === "monthly") return "30d"
  return ""
}

// Reset-day formats for the bar. Keys are the values stored in shell.json; values are Qt formats.
var BAR_RESET_TIME_FORMATS = { "24h": "HH:mm", "12h": "h:mm AP" }
var BAR_RESET_DATE_FORMATS = { "DD/MM": "dd/MM", "MM/DD": "MM/dd", "D MMM": "d MMM" }
var BAR_RESET_CHOICES = {
  time: ["24h", "12h"],
  date: ["DD/MM", "MM/DD", "D MMM"]
}

// "time" for a limit whose window is at most a day (5-hour), otherwise "date" (weekly, monthly).
function barResetKind(row) {
  var seconds = Number(row && row.windowSeconds)
  if (isFinite(seconds) && seconds > 0) return seconds <= 86400 ? "time" : "date"
  return row && String(row.id) === "session" ? "time" : "date"
}

function normalizeBarResetChoice(kind, value) {
  var choices = kind === "time" ? BAR_RESET_CHOICES.time : BAR_RESET_CHOICES.date
  var fallback = choices[0]
  return choices.indexOf(value) !== -1 ? value : fallback
}

// Qt format for one reset. The chosen format for the window's kind wins; unknown values fall back to the default.
function barResetFormat(kind, timeChoice, dateChoice) {
  if (kind === "time") {
    var timeKey = normalizeBarResetChoice("time", timeChoice)
    return BAR_RESET_TIME_FORMATS[timeKey]
  }
  var dateKey = normalizeBarResetChoice("date", dateChoice)
  return BAR_RESET_DATE_FORMATS[dateKey]
}

function windowMatches(row, selector) {
  var spec = WINDOW_SELECTORS[selector]
  if (!spec || !row) return false
  var seconds = Number(row.windowSeconds)
  if (isFinite(seconds) && seconds > 0) return seconds === spec.seconds
  var text = (String(row.id || "") + " " + String(row.label || "")).toLowerCase()
  for (var i = 0; i < spec.keywords.length; i++) {
    if (text.indexOf(spec.keywords[i]) !== -1) return true
  }
  return false
}

function exactRemainingForWindow(provider, selector) {
  if (normalizeBarWindow(selector) === "auto") return null
  var row = windowRowFor(provider, selector, false)
  return row === null ? null : clamp(remainingOf(row), 0, 100)
}

// The row that supplies a chip's number. With `allowFallback`, a window the provider
// does not report falls back to its most restrictive row, as remainingForWindow does.
function windowRowFor(provider, selector, allowFallback) {
  if (!provider || provider.status !== "ok") return null
  var want = normalizeBarWindow(selector)
  var windows = listOrEmpty(provider.windows)
  if (want !== "auto") {
    var matched = []
    for (var i = 0; i < windows.length; i++) {
      if (windowMatches(windows[i], want)) matched.push(windows[i])
    }
    var exact = lowestRow(matched)
    if (exact !== null || !allowFallback) return exact
  }
  return lowestRow(windows)
}

function lowestRow(rows) {
  var best = null
  var low = 101
  for (var i = 0; i < rows.length; i++) {
    var value = remainingOf(rows[i])
    if (value !== null && value < low) { low = value; best = rows[i] }
  }
  return best
}

function remainingOf(row) {
  if (!row || row.remaining === null || row.remaining === undefined || row.remaining === "") return null
  var value = Number(row.remaining)
  return isFinite(value) ? value : null
}

// A provider that does not report the chosen window keeps a bar percentage
// instead of losing its chip.
function remainingForWindow(provider, selector) {
  var remaining = exactRemainingForWindow(provider, selector)
  return remaining === null ? minRemaining(provider) : remaining
}

// Cards and chips can report either side of the same allowance. `used` is what
// provider dashboards show; `remaining` is what the warning thresholds gate on.
// A window that reports only one side still yields the other.
function windowUsed(row) {
  if (!row) return null
  var used = Number(row.used)
  if (isFinite(used)) return clamp(used, 0, 100)
  var remaining = Number(row.remaining)
  return isFinite(remaining) ? clamp(100 - remaining, 0, 100) : null
}

function windowRemaining(row) {
  if (!row) return null
  var remaining = Number(row.remaining)
  if (isFinite(remaining)) return clamp(remaining, 0, 100)
  var used = Number(row.used)
  return isFinite(used) ? clamp(100 - used, 0, 100) : null
}

function usedFromRemaining(remaining) {
  return remaining === null || remaining === undefined ? null : clamp(100 - Number(remaining), 0, 100)
}

function usedForWindow(provider, selector) {
  return usedFromRemaining(remainingForWindow(provider, selector))
}

// Pace projects a window's run-out from its own recent samples, not from its average since reset.
// `samples` is the window's [epoch, used] series; each value holds until the next sample.
// `expected` is the percent of the window already elapsed: the mark for an even burn.
// A projection needs an observed, recent burn; otherwise `state` says why there is none.
var PACE_MIN_ELAPSED_FRACTION = 0.02
var PACE_HALF_LIFE_SECONDS = 2 * 60 * 60  // newest samples weigh most; weight halves every this long
var PACE_MAX_GAP_SECONDS = 60 * 60        // a longer gap is unobserved (neither use nor idle); newest sample older than this is stale
var PACE_IDLE_SECONDS = 60 * 60           // no increase for this long: idle, no projection
var PACE_MIN_OBSERVED_SECONDS = 10 * 60   // less observed time than this: still collecting

function finiteOrNull(value) {
  if (value === null || value === undefined || value === "") return null
  var number = Number(value)
  return isFinite(number) ? number : null
}

// Burn of one window over its own samples, weighted toward the newest. Returns null when the
// newest sample is too old to judge. Otherwise: `percentPerSecond` is the weighted mean rate of
// the observed intervals, `observedSeconds` the time they cover, and `idleSeconds` the time since
// the last increase (or since observation began, when no increase was seen).
function recentBurn(samples, used, nowSeconds, windowStart) {
  var points = []
  var list = Array.isArray(samples) ? samples : []
  list.forEach(function (row) {
    var stamp = Array.isArray(row) ? finiteOrNull(row[0]) : null
    var value = Array.isArray(row) ? finiteOrNull(row[1]) : null
    if (stamp === null || value === null || stamp > nowSeconds) return
    points.push([stamp, clamp(value, 0, 100)])
  })
  points.sort(function (a, b) { return a[0] - b[0] })
  if (points.length === 0 || nowSeconds - points[points.length - 1][0] > PACE_MAX_GAP_SECONDS) return null

  // Samples from before this window began belong to the previous window; a reset is not a burn,
  // so the first in-window sample is the baseline and nothing before it counts.
  var inside = points.filter(function (point) { return point[0] >= windowStart })
  inside.push([nowSeconds, used])

  var weighted = 0
  var weight = 0
  var observed = 0
  var firstObserved = null
  var lastIncrease = null
  for (var i = 0; i + 1 < inside.length; i++) {
    var from = inside[i]
    var to = inside[i + 1]
    var seconds = to[0] - from[0]
    if (seconds <= 0 || seconds > PACE_MAX_GAP_SECONDS) continue
    var decay = Math.pow(0.5, (nowSeconds - to[0]) / PACE_HALF_LIFE_SECONDS)
    var rise = Math.max(0, to[1] - from[1])
    weighted += rise * decay
    weight += seconds * decay
    observed += seconds
    if (firstObserved === null) firstObserved = from[0]
    if (rise > 0) lastIncrease = to[0]
  }
  var idleFrom = lastIncrease !== null ? lastIncrease : firstObserved
  return {
    percentPerSecond: weight > 0 ? weighted / weight : 0,
    observedSeconds: observed,
    idleSeconds: idleFrom === null ? null : nowSeconds - idleFrom
  }
}

function paceForWindow(row, nowSeconds) {
  var windowSeconds = finiteOrNull(row ? row.windowSeconds : null)
  var resetsAt = finiteOrNull(row ? row.resetsAt : null)
  var now = finiteOrNull(nowSeconds)
  var used = windowUsed(row)
  if (windowSeconds === null || windowSeconds <= 0 || resetsAt === null || now === null || used === null) return null

  var untilReset = Math.max(0, resetsAt - now)
  var elapsed = clamp(windowSeconds - untilReset, 0, windowSeconds)
  var result = {
    used: used,
    expected: 100 * elapsed / windowSeconds,
    known: false,
    exhausted: false,
    state: "starting",
    runsOut: false,
    etaSeconds: null,
    observedSeconds: 0,
    idleSeconds: null
  }

  if (used >= 100) {
    result.known = true
    result.exhausted = true
    result.state = "exhausted"
    return result
  }
  if (elapsed < windowSeconds * PACE_MIN_ELAPSED_FRACTION) return result
  result.known = true
  if (used <= 0) {
    result.state = "no-usage"
    return result
  }

  var burn = recentBurn(row.samples, used, now, resetsAt - windowSeconds)
  if (burn === null) {
    result.state = "stale"
    return result
  }
  result.observedSeconds = burn.observedSeconds
  result.idleSeconds = burn.idleSeconds
  if (burn.observedSeconds < PACE_MIN_OBSERVED_SECONDS) {
    result.state = "collecting"
    return result
  }
  if (burn.percentPerSecond <= 0 || burn.idleSeconds >= PACE_IDLE_SECONDS) {
    result.state = "idle"
    return result
  }

  // Time from now until 100 % at the recent rate.
  var etaSeconds = (100 - used) / burn.percentPerSecond
  result.state = "projecting"
  if (etaSeconds < untilReset) {
    result.runsOut = true
    result.etaSeconds = etaSeconds
  }
  return result
}

// Compact countdown: "3d 4h", "2h 5m", "41m".
function formatDuration(seconds) {
  var value = finiteOrNull(seconds)
  if (value === null) return ""
  var minutes = Math.max(0, Math.round(value / 60))
  var days = Math.floor(minutes / 1440)
  var hours = Math.floor((minutes % 1440) / 60)
  var rest = minutes % 60
  if (days > 0) return days + "d " + hours + "h"
  if (hours > 0) return hours + "h " + rest + "m"
  return rest + "m"
}

// The pace tick is drawn only when there is usage to compare with it.
function paceShowsMark(pace) {
  return !!pace && pace.known && !pace.exhausted && pace.used > 0
}

// Hover text for the tick: usage against the expected share, then what the recent burn implies.
function paceTickText(pace) {
  if (!paceShowsMark(pace)) return ""
  var delta = Math.round(pace.used - pace.expected)
  var lines = ["Used " + Math.round(pace.used) + "% · expected " + Math.round(pace.expected) + "%"]
  if (delta > 0) lines.push("Ahead by " + delta + " pts")
  else if (delta < 0) lines.push("Behind by " + (-delta) + " pts")
  else lines.push("On pace")
  lines.push(projectionLine(pace))
  return lines.join("\n")
}

// What the recent burn says about the rest of the window, for the tooltip.
function projectionLine(pace) {
  if (pace.state === "projecting") {
    return pace.runsOut
      ? "At this pace: runs out in " + formatDuration(pace.etaSeconds)
      : "At this pace: lasts until reset"
  }
  if (pace.state === "idle") return "No increase for " + formatDuration(pace.idleSeconds) + " · no projection"
  if (pace.state === "stale") return "No samples in the last hour · no projection"
  return "Collecting samples · no projection"
}

// One status line for a window card; empty when there is nothing to say.
// Whenever the tick is drawn, its expected share is printed beside it.
function paceText(pace) {
  if (!pace || !pace.known) return ""
  if (pace.exhausted) return "Limit reached"
  if (!paceShowsMark(pace)) return ""
  var expected = "expected " + Math.round(pace.expected) + "%"
  if (pace.state === "idle") return "Idle " + formatDuration(pace.idleSeconds) + " · " + expected
  if (pace.state === "stale") return "No recent data · " + expected
  if (pace.state === "collecting") return "Collecting data · " + expected
  if (pace.runsOut) return "Runs out in " + formatDuration(pace.etaSeconds) + " · " + expected
  return "Lasts until reset · " + expected
}

// What the Pacing row says when no tick is drawn yet: the reason, not a blank.
function paceStatusText(pace) {
  var text = paceText(pace)
  if (text !== "") return text
  if (!pace) return "not reported"
  if (!pace.known) return "starts after 2% of the window"
  return "no usage yet"
}

// One legend for all limit cards of a provider, shown once under them. Each card's line gives its figures.
var PACING_LEGEND = [
  "Pacing compares usage with a steady burn across each limit's window.",
  "The tick on a meter marks the share of the window already passed; usage past it is ahead of pace.",
  "The line under each limit projects from recent use; the newest samples weigh most (half-life " + Math.round(PACE_HALF_LIFE_SECONDS / 3600) + "h).",
  "No run-out is projected while a limit is idle, has no recent samples, or is still collecting them.",
  "Pace starts after " + Math.round(PACE_MIN_ELAPSED_FRACTION * 100) + "% of a window has passed.",
  "Assumes the recent rate continues; bursts are not predicted."
].join("\n")

// Severity order for threshold crossings. "none" means no reading and never counts as one.
var SEVERITY_RANK = { none: 0, ok: 1, warning: 2, critical: 3 }

// Compares this refresh's per-window severities with the previous ones. Only a move to a
// worse severity is a crossing; recovering silently re-arms the next one. A window seen for
// the first time seeds state without notifying, so startup does not announce existing limits.
// A window missing from `readings` is dropped, so its next sighting seeds again.
// `readings` items: { key, severity, ... }. Returns { state, crossings }.
function severityCrossings(previous, readings) {
  var state = {}
  var crossings = []
  for (var i = 0; i < readings.length; i++) {
    var reading = readings[i]
    if (SEVERITY_RANK[reading.severity] === undefined || reading.severity === "none") {
      if (previous[reading.key] !== undefined) state[reading.key] = previous[reading.key]
      continue
    }
    var before = previous[reading.key]
    state[reading.key] = reading.severity
    if (before !== undefined && SEVERITY_RANK[reading.severity] > SEVERITY_RANK[before]) crossings.push(reading)
  }
  return { state: state, crossings: crossings }
}

function exportWindows(rows, nowSeconds) {
  var result = []
  var list = listOrEmpty(rows)
  for (var i = 0; i < list.length; i++) {
    var row = list[i]
    if (!row) continue
    result.push({
      label: row.label === undefined || row.label === null ? null : String(row.label),
      used: windowUsed(row),
      remaining: windowRemaining(row),
      resetsAt: finiteOrNull(row.resetsAt),
      windowSeconds: finiteOrNull(row.windowSeconds),
      pace: paceForWindow(row, nowSeconds)
    })
  }
  return result
}

// Account identities become "Account N" unless the caller explicitly disables hiding.
function exportProviders(providers, nowSeconds, hideEmails) {
  var result = []
  var list = listOrEmpty(providers)
  for (var i = 0; i < list.length; i++) {
    var provider = list[i]
    var accounts = listOrEmpty(provider.accounts)
    var accountRows = []
    for (var j = 0; j < accounts.length; j++) {
      accountRows.push({
        label: hideEmails ? "Account " + (j + 1) : String(accounts[j].account || "Account " + (j + 1)),
        windows: exportWindows(accounts[j].windows, nowSeconds)
      })
    }
    result.push({
      id: String(provider.id || ""),
      name: String(provider.name || provider.id || ""),
      status: String(provider.status || ""),
      windows: exportWindows(provider.windows, nowSeconds),
      accounts: accountRows
    })
  }
  return result
}

// JSON text for the IPC export. Redaction fails closed: only an explicit `false` shows emails.
function exportSnapshot(providers, nowSeconds, hideEmails) {
  return JSON.stringify({
    generatedAt: finiteOrNull(nowSeconds),
    providers: exportProviders(providers, nowSeconds, hideEmails !== false)
  }, null, 2)
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "") return ""
  var amount = Number(value)
  if (!isFinite(amount)) return ""
  // Provider dashboards report one decimal; keep it, but do not invent one.
  var rounded = Math.round(amount * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

function quotaText(value, mode) {
  var text = formatPercent(value)
  if (text === "") return ""
  return text + (String(mode) === "Used" ? "% used" : "% left")
}

// Providers that get a bar chip: a reading for the chosen window, or a failure the user must see.
function barProviders(providers, selector) {
  var result = []
  var list = listOrEmpty(providers)
  for (var i = 0; i < list.length; i++) {
    var chosen = typeof selector === "function" ? selector(list[i]) : selector
    if (String(list[i].status) === "error" || remainingForWindow(list[i], chosen) !== null)
      result.push(list[i])
  }
  return result
}

var ERROR_REASON_LABELS = {
  rate_limited: "rate limited",
  expired: "sign in",
  no_credentials: "sign in",
  timeout: "timeout",
  network: "offline",
  malformed: "bad data",
  http: "error"
}

// Short bar label for a failed provider; unknown kinds read "error".
function errorReasonLabel(kind) {
  var key = String(kind || "")
  return Object.prototype.hasOwnProperty.call(ERROR_REASON_LABELS, key) ? ERROR_REASON_LABELS[key] : "error"
}

// Sign-in failures persist until the user re-authenticates; the rest clear on their own.
function errorNeedsSignIn(kind) {
  var key = String(kind || "")
  return key === "expired" || key === "no_credentials"
}

function availableProviders(providers) {
  function available(reading) {
    return reading && reading.status !== "disabled" && reading.errorKind !== "no_credentials"
  }
  var result = []
  var list = listOrEmpty(providers)
  for (var i = 0; i < list.length; i++) {
    var provider = list[i]
    // Keep connection-level errors visible so the user can fix proxy setup.
    if (provider && provider.id === "cliproxy") {
      result.push(provider)
      continue
    }
    var accounts = listOrEmpty(provider && provider.accounts)
    if (accounts.length > 0) {
      for (var j = 0; j < accounts.length; j++) {
        if (available(accounts[j])) {
          result.push(provider)
          break
        }
      }
    } else if (available(provider)) {
      result.push(provider)
    }
  }
  return result
}

function selectedProviders(providers, ids) {
  var result = []
  var list = listOrEmpty(providers)
  for (var i = 0; i < list.length; i++) {
    if (list[i] && contains(ids, list[i].id)) result.push(list[i])
  }
  return result
}

function lastUsedAccount(provider, activityProviders, hideEmails) {
  var activity = listOrEmpty(activityProviders)
  var last = null
  for (var i = 0; i < activity.length; i++)
    if (provider && activity[i].id === provider.id) last = activity[i]
  if (!last) return { label: "Unknown", reading: null, lastUsedAt: 0 }
  if (last.status === "ambiguous")
    return { label: "Multiple accounts", reading: null, lastUsedAt: last.lastUsedAt }
  var accounts = listOrEmpty(provider && provider.accounts)
  for (var j = 0; j < accounts.length; j++) {
    if (last.status === "ok" && accounts[j].accountId === last.accountId)
      return { label: hideEmails ? "Account " + (j + 1) : String(accounts[j].account || "Account " + (j + 1)),
        reading: accounts[j], lastUsedAt: last.lastUsedAt }
  }
  // Account inventory and activity refresh independently. Never substitute the
  // pool's best-quota account when a new/deleted account cannot be matched.
  return { label: "Unknown", reading: null, lastUsedAt: last.lastUsedAt }
}

function providerMark(providerId) {
  if (providerId === "claude") return "C"
  if (providerId === "codex") return "O"
  if (providerId === "kimi") return "K"
  return String(providerId || "?").charAt(0).toUpperCase()
}

function accountPlanLabel(account) {
  if (!account) return ""
  var plan = String(account.planType || account.plan || "")
  var normalized = plan.toLowerCase().replace(/^chatgpt\s+/, "").replace(/[-_ ]/g, "")
  if (account.id === "codex") {
    if (normalized === "pro" || normalized === "pro20x") return "Codex Pro · 20×"
    if (normalized === "prolite" || normalized === "pro5x") return "Codex Pro · 5×"
  }
  return String(account.plan || account.name || account.id || "Account")
}

function accountResetLabel(account) {
  if (!account || account.id !== "codex" || account.status !== "ok") return ""
  var count = account.credits && account.credits.resetCreditsAvailable
  if (typeof count !== "number" || !isFinite(count) || count < 0 || Math.floor(count) !== count) return ""
  return count + " banked reset" + (count === 1 ? "" : "s")
}

function accountWindows(account, expanded) {
  var rows = listOrEmpty(account && account.windows)
  if (expanded) return rows
  var overall = [], weekly = [], monthly = []
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i]
    var label = String(row.label || "")
    var seconds = Number(row.windowSeconds)
    if (/^weekly(?: limit)?$/i.test(label)) overall.push(row)
    if (seconds === 604800 || /weekly/i.test(label)) weekly.push(row)
    if (/^monthly(?: limit)?$/i.test(label)) monthly.push(row)
  }
  if (overall.length) return overall
  if (weekly.length) return weekly
  if (monthly.length) return monthly
  // Plans without a weekly/monthly allowance still show their real main window.
  return firstItems(rows, 1)
}

function errorTitle(provider) {
  if (!provider) return "Provider unavailable"
  var name = String(provider.name || provider.id || "Provider")
  switch (provider.errorKind) {
  case "config": return proxyName(provider.proxyImplementation) + " configuration required"
  case "no_credentials": return name + " sign-in required"
  case "expired": return name + " sign-in expired"
  case "rate_limited": return name + " is rate limited"
  case "timeout": return name + " timed out"
  case "cli_unavailable": return name + " CLI unavailable"
  default: return name + " usage unavailable"
  }
}

function preserveProxyReadings(previous, next) {
  if (!previous || previous.source !== "cliproxy") return next
  if (previous.proxyImplementation && next.proxyImplementation
      && previous.proxyImplementation !== next.proxyImplementation) return next
  if (!next.proxyImplementation && previous.proxyImplementation)
    next.proxyImplementation = previous.proxyImplementation
  function retain(old, fresh) {
    if (!old || !fresh || fresh.status !== "error" || old.status !== "ok") return fresh
    if (old.proxyImplementation && fresh.proxyImplementation
        && old.proxyImplementation !== fresh.proxyImplementation) return fresh
    if (fresh.errorKind === "malformed" || fresh.supportsBankedReset === false
        && fresh.proxyImplementation !== old.proxyImplementation) return fresh
    if (fresh.proxyImplementation === "rust" && fresh.errorKind === "quota_unavailable") return fresh
    return Object.assign({}, fresh, {
      status: "ok", stale: true, windows: old.windows, credits: old.credits,
      plan: old.plan, account: old.account, fetchedAt: old.fetchedAt,
      notice: "Last known reading · " + String(fresh.message || "Refresh failed.")
    })
  }
  var oldProviders = listOrEmpty(previous.providers)
  if (next.providers.length === 1 && next.providers[0].id === "cliproxy" && next.providers[0].status === "error"
      && oldProviders.length > 0 && oldProviders[0].id !== "cliproxy") {
    var failure = next.providers[0]
    next.providers = Array.prototype.map.call(oldProviders, function(old) {
      var fresh = Object.assign({}, old, { status: "error", message: failure.message, errorKind: failure.errorKind })
      fresh.accounts = Array.prototype.map.call(listOrEmpty(old.accounts), function(account) {
        return retain(account, Object.assign({}, account, { status: "error", message: failure.message }))
      })
      return retain(old, fresh)
    })
  }
  next.providers = listOrEmpty(next.providers).map(function(fresh) {
    var old = null
    for (var i = 0; i < oldProviders.length; i++)
      if (oldProviders[i].id === fresh.id) old = oldProviders[i]
    var accounts = listOrEmpty(fresh.accounts).map(function(account) {
      var prior = listOrEmpty(old && old.accounts)
      for (var j = 0; j < prior.length; j++)
        if (prior[j].accountId === account.accountId) return retain(prior[j], account)
      return account
    })
    var result = old && old.accountId === fresh.accountId ? retain(old, fresh) : fresh
    if (fresh.accounts) result.accounts = accounts
    return result
  })
  return next
}

// Custom cost rates are stored as JSON for the manifest's string setting, but
// edited as ordinary fields. Model IDs deliberately keep case and prefixes.
function costPriceError(message, rowIndex, fieldKey) {
  var error = new Error(message)
  error.rowIndex = rowIndex
  error.fieldKey = fieldKey
  return error
}

function encodeCostPrices(rows) {
  var fields = ["inputCostPerMillionTokens", "outputCostPerMillionTokens",
    "cacheReadCostPerMillionTokens", "cacheWriteCostPerMillionTokens"]
  var result = Object.create(null)
  if (rows.length > 128) throw new Error("Custom prices support at most 128 models.")
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i]
    var model = String(row.model || "").trim()
    if (!model || model.length > 256 || /[\x00-\x1f]/.test(model))
      throw costPriceError("Enter a model ID of 1–256 characters for custom price " + (i + 1) + ".", i, "modelId")
    if (Object.prototype.hasOwnProperty.call(result, model))
      throw costPriceError("Each custom price must use a different model ID.", i, "modelId")
    var bare = model.toLowerCase().split("/").pop().split("[")[0]
    if (["<unattributed>", "<synthetic>", "synthetic"].indexOf(bare) >= 0)
      throw costPriceError("Custom prices require an attributable model ID.", i, "modelId")
    var prices = {}
    for (var j = 0; j < fields.length; j++) {
      var raw = row[fields[j]]
      var value = raw === undefined ? "" : String(raw).trim()
      if (j >= 2 && value === "") continue
      if (value === "" || !/^(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value)
          || !isFinite(Number(value)) || Number(value) > 1000000000)
        throw costPriceError("Enter input/output prices from 0 to 1,000,000,000 USD per million tokens; cache prices may be blank.", i, fields[j])
      prices[fields[j]] = Number(value)
    }
    result[model] = prices
  }
  var json = JSON.stringify(result)
  if (encodeURIComponent(json).replace(/%[0-9A-F]{2}/gi, "x").length > 65536)
    throw new Error("Custom prices exceed the 64 KiB limit.")
  return json
}

function decodeCostPrices(raw) {
  if (typeof raw !== "string" || raw.length > 65536)
    throw new Error("Saved custom prices are invalid. Remove them to restore automatic pricing.")
  var document = JSON.parse(raw)
  if (!document || typeof document !== "object" || Array.isArray(document))
    throw new Error("Saved custom prices must be an object.")
  var fields = ["inputCostPerMillionTokens", "outputCostPerMillionTokens",
    "cacheReadCostPerMillionTokens", "cacheWriteCostPerMillionTokens"]
  var rows = Object.keys(document).map(function(model) {
    var prices = document[model]
    if (!prices || typeof prices !== "object" || Array.isArray(prices)
        || Object.keys(prices).some(function(key) { return fields.indexOf(key) < 0 }))
      throw new Error("Saved custom prices contain unsupported fields.")
    var row = { model: model }
    for (var i = 0; i < fields.length; i++) {
      var value = prices[fields[i]]
      if (value !== undefined && (typeof value !== "number" || !isFinite(value)))
        throw new Error("Saved custom prices must be numeric.")
      row[fields[i]] = value === undefined ? "" : String(value)
    }
    return row
  })
  encodeCostPrices(rows)
  return rows
}
