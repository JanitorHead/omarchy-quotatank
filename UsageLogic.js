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
  return formatMoney(value, "USD")
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

// The weekly or monthly limit a provider has used up, if any: such a provider cannot be used until
// that window resets, so its chip may be hidden. A limit of a week or longer counts; a 5-hour or
// daily limit refills soon and does not. Returns the soonest-resetting such row, or null.
function usedUpLongWindow(provider) {
  if (!provider || provider.status !== "ok") return null
  var rows = listOrEmpty(provider.windows)
  var found = null
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i]
    var remaining = remainingOf(row)
    if (remaining === null || remaining > 0) continue
    var seconds = Number(row.windowSeconds)
    var long = isFinite(seconds) && seconds > 0
      ? seconds >= 604800
      : windowMatches(row, "weekly") || windowMatches(row, "monthly")
    if (!long) continue
    if (!found || Number(row.resetsAt || Infinity) < Number(found.resetsAt || Infinity)) found = row
  }
  return found
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
// (`session` vs `5-hour limit`, `Weekly limit`, and so on). The accepted
// spellings match the AI usage widget's `barWindow` setting, so the same value
// works for either plugin on the command line. A monthly window that reports
// its real calendar period runs 28 to 31 days, so any of those lengths counts.
var WINDOW_SELECTORS = {
  session: { seconds: 18000, keywords: ["session", "5 hour", "5-hour", "hourly"] },
  weekly: { seconds: 604800, keywords: ["week"] },
  monthly: { seconds: 2592000, minSeconds: 2419200, maxSeconds: 2678400, keywords: ["month"] }
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
  if (normalized === "session") return "5-hour"
  if (normalized === "weekly") return "7-day"
  if (normalized === "monthly") return "Monthly"
  return "Most constrained"
}

// Label for the "Default" choice of one provider slot: names the global value it inherits.
function inheritedBarLimitLabel(slot, globalSelector) {
  var normalized = slot === "bottom" ? normalizeSecondaryBarWindow(globalSelector) : normalizeBarWindow(globalSelector)
  return "Default (" + (normalized === "none" ? "None" : windowSelectorLabel(normalized)) + ")"
}

// Per-provider "Show limits as" overrides (`providerQuotaModes`, a JSON object of provider id →
// "Used" | "Remaining"); a provider without one follows the global `quotaMode`.
function parseQuotaModes(text) {
  var parsed
  try { parsed = JSON.parse(String(text === undefined || text === null ? "{}" : text)) }
  catch (error) { return {} }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {}
  var result = {}
  var ids = Object.keys(parsed)
  for (var i = 0; i < ids.length; i++)
    if (parsed[ids[i]] === "Used" || parsed[ids[i]] === "Remaining") result[ids[i]] = parsed[ids[i]]
  return result
}

// `value` is "default" to follow the global choice again.
function setQuotaMode(text, providerId, value) {
  var modes = parseQuotaModes(text)
  if (value === "default") delete modes[providerId]
  else if (value === "Used" || value === "Remaining") modes[providerId] = value
  return JSON.stringify(modes)
}

function quotaModeFor(text, providerId, globalMode) {
  var mode = parseQuotaModes(text)[String(providerId)]
  return mode || (String(globalMode) === "Remaining" ? "Remaining" : "Used")
}

function quotaModeLabel(mode) {
  return String(mode) === "Remaining" ? "Left (%)" : "Used (%)"
}

// Provider order (`providerOrder`, a JSON array of provider ids). Listed providers come first in that
// order; the rest keep their natural order after them, so a saved order survives new providers.
function parseProviderOrder(text) {
  var parsed
  try { parsed = JSON.parse(String(text === undefined || text === null ? "[]" : text)) }
  catch (error) { return [] }
  if (!Array.isArray(parsed)) return []
  var result = []
  for (var i = 0; i < parsed.length; i++) {
    var id = parsed[i]
    if (typeof id === "string" && /^[a-z0-9][a-z0-9_-]{0,63}$/.test(id) && result.indexOf(id) === -1) result.push(id)
  }
  return result
}

function orderProviders(list, text) {
  var order = parseProviderOrder(text)
  var rows = listOrEmpty(list)
  var ranked = []
  for (var i = 0; i < rows.length; i++) {
    var index = order.indexOf(String(rows[i] && rows[i].id))
    ranked.push({ row: rows[i], rank: index === -1 ? order.length + i : index, index: i })
  }
  ranked.sort(function (a, b) { return a.rank - b.rank || a.index - b.index })
  return ranked.map(function (entry) { return entry.row })
}

// Short period tag for stacked chips. Auto has no single period, so it has no tag.
function windowShortLabel(selector) {
  var normalized = normalizeBarWindow(selector)
  if (normalized === "session") return "5h"
  if (normalized === "weekly") return "7d"
  if (normalized === "monthly") return "30d"
  return ""
}

// Period tag for the row a chip actually shows. Most constrained names the period of the
// limit it picked (so "7d 91%" says the weekly limit is the tight one). A provider without the
// chosen window falls back to its most restrictive row; the tag then names that row's period,
// or nothing when the period cannot be told, so a figure is never tagged wrong.
function barTagFor(provider, selector, allowFallback) {
  var want = normalizeBarWindow(selector)
  if (want === "auto") return rowPeriodTag(windowRowFor(provider, "auto", true))
  var row = windowRowFor(provider, want, allowFallback)
  if (row === null || windowMatches(row, want)) return windowShortLabel(want)
  return rowPeriodTag(row)
}

// Short period of one reported row: 5h, 7d, 30d, or 1d for a daily limit; empty when unknown.
function rowPeriodTag(row) {
  if (!row) return ""
  var selectors = Object.keys(WINDOW_SELECTORS)
  for (var i = 0; i < selectors.length; i++) {
    if (windowMatches(row, selectors[i])) return windowShortLabel(selectors[i])
  }
  return Number(row.windowSeconds) === 86400 ? "1d" : ""
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
  if (isFinite(seconds) && seconds > 0)
    return spec.minSeconds !== undefined ? seconds >= spec.minSeconds && seconds <= spec.maxSeconds : seconds === spec.seconds
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

// The longer of a chip's two windows, once exhausted, is the limit that decides
// whether the provider can be used. Returns that window, or "" when there is no
// such limit: a window is `auto`/`none`, both windows are the same, or the longer
// one still has allowance.
function blockingWindow(topWindow, topRemaining, bottomWindow, bottomRemaining) {
  var top = normalizeBarWindow(topWindow)
  var bottom = normalizeSecondaryBarWindow(bottomWindow)
  if (!WINDOW_SELECTORS[top] || !WINDOW_SELECTORS[bottom] || top === bottom) return ""
  var longer = WINDOW_SELECTORS[top].seconds >= WINDOW_SELECTORS[bottom].seconds ? top : bottom
  var remaining = longer === top ? topRemaining : bottomRemaining
  if (remaining === null || remaining === undefined || !isFinite(Number(remaining))) return ""
  return Number(remaining) <= 0 ? longer : ""
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

// Limit cards in one order for every provider: shortest window first, so a 5-hour
// limit always sits above weekly and monthly ones. Rows without a window length keep
// their reported order after the timed ones.
function orderedWindows(windows) {
  var rows = listOrEmpty(windows)
  var indexed = []
  for (var i = 0; i < rows.length; i++) {
    var seconds = Number(rows[i] && rows[i].windowSeconds)
    indexed.push({ row: rows[i], index: i, seconds: isFinite(seconds) && seconds > 0 ? seconds : Infinity })
  }
  indexed.sort(function(a, b) {
    if (a.seconds !== b.seconds) return a.seconds < b.seconds ? -1 : 1
    return a.index - b.index
  })
  return indexed.map(function(entry) { return entry.row })
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
// A window that reports only one side still yields the other. A window whose usage
// is unknown (null on both sides, e.g. a quota pool without a reported fraction)
// stays unknown: Number(null) is 0, so it must never pass through Number() alone.
function windowUsed(row) {
  if (!row) return null
  var used = finiteOrNull(row.used)
  if (used !== null) return clamp(used, 0, 100)
  var remaining = finiteOrNull(row.remaining)
  return remaining === null ? null : clamp(100 - remaining, 0, 100)
}

function windowRemaining(row) {
  if (!row) return null
  var remaining = finiteOrNull(row.remaining)
  if (remaining !== null) return clamp(remaining, 0, 100)
  var used = finiteOrNull(row.used)
  return used === null ? null : clamp(100 - used, 0, 100)
}

function usedFromRemaining(remaining) {
  return remaining === null || remaining === undefined ? null : clamp(100 - Number(remaining), 0, 100)
}

function usedForWindow(provider, selector) {
  return usedFromRemaining(remainingForWindow(provider, selector))
}

// Pace has two parts. The tick (`expected`) is the share of the window already elapsed: where an
// even burn would be by now. It needs only the clock, so it shows whenever the limit has usage.
// The projection says when the limit would run out, and how depends on the window's length:
// - Limits of a day or less (the 5-hour session) follow the recent rate of their own samples,
//   newest weighing most, because a session is used in one sitting.
// - Longer limits (weekly, monthly) follow the average so far this window blended with the last
//   24 hours. The average already counts nights and days off, so one busy hour does not predict a
//   weekly run-out and a quiet weekend does not hide a heavy week.
// `samples` is the window's [epoch, used] series; each value holds until the next.
var PACE_MIN_ELAPSED_FRACTION = 0.02
var PACE_SHORT_WINDOW_SECONDS = 24 * 60 * 60  // at most this long: projected from the recent rate
var PACE_MAX_GAP_SECONDS = 60 * 60        // a longer gap is unobserved (neither use nor idle); newest sample older than this is stale
var PACE_IDLE_SECONDS = 60 * 60           // no increase for this long: idle, no projection
var PACE_MIN_OBSERVED_SECONDS = 10 * 60   // less observed time than this: still collecting
var PACE_DAY_SECONDS = 24 * 60 * 60

// Half-life of the recent rate for a short window: an eighth of the window, 15 minutes to 2 hours
// (about 40 minutes for a 5-hour session).
function paceHalfLife(windowSeconds) {
  return clamp(windowSeconds / 8, 15 * 60, 2 * 60 * 60)
}

function finiteOrNull(value) {
  if (value === null || value === undefined || value === "") return null
  var number = Number(value)
  return isFinite(number) ? number : null
}

// Burn of one window over its own samples, weighted toward the newest. Returns null when the
// newest sample is too old to judge. Otherwise: `percentPerSecond` is the weighted mean rate of
// the observed intervals, `observedSeconds` the time they cover, and `idleSeconds` the time since
// the last increase (or since observation began, when no increase was seen).
function recentBurn(samples, used, nowSeconds, windowStart, halfLifeSeconds) {
  var halfLife = halfLifeSeconds || paceHalfLife(5 * 60 * 60)
  var points = []
  var list = listOrEmpty(samples)
  // Index loop, not forEach: Quickshell lists may lack forEach but keep length and indexing.
  for (var r = 0; r < list.length; r++) {
    var row = list[r]
    var stamp = isListLike(row) ? finiteOrNull(row[0]) : null
    var value = isListLike(row) ? finiteOrNull(row[1]) : null
    if (stamp === null || value === null || stamp > nowSeconds) continue
    points.push([stamp, clamp(value, 0, 100)])
  }
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
    var decay = Math.pow(0.5, (nowSeconds - to[0]) / halfLife)
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

// Rise over the last day, as percent per second, for a long window; null when the window began less
// than a day ago or the history does not reach back a day. A rolling window can fall: never negative.
function lastDayRate(samples, used, nowSeconds, windowStart) {
  var since = nowSeconds - PACE_DAY_SECONDS
  if (windowStart > since) return null
  var base = null
  var list = listOrEmpty(samples)
  for (var r = 0; r < list.length; r++) {
    var row = list[r]
    var stamp = isListLike(row) ? finiteOrNull(row[0]) : null
    var value = isListLike(row) ? finiteOrNull(row[1]) : null
    if (stamp === null || value === null || stamp < windowStart || stamp > since) continue
    if (base === null || stamp > base[0]) base = [stamp, clamp(value, 0, 100)]
  }
  return base === null ? null : Math.max(0, used - base[1]) / PACE_DAY_SECONDS
}

function paceForWindow(row, nowSeconds) {
  var windowSeconds = finiteOrNull(row ? row.windowSeconds : null)
  var resetsAt = finiteOrNull(row ? row.resetsAt : null)
  var now = finiteOrNull(nowSeconds)
  var used = windowUsed(row)
  if (windowSeconds === null || windowSeconds <= 0 || resetsAt === null || now === null || used === null) return null

  var untilReset = Math.max(0, resetsAt - now)
  var elapsed = clamp(windowSeconds - untilReset, 0, windowSeconds)
  var windowStart = resetsAt - windowSeconds
  var result = {
    used: used,
    expected: 100 * elapsed / windowSeconds,
    known: false,
    exhausted: false,
    method: windowSeconds > PACE_SHORT_WINDOW_SECONDS ? "average" : "recent",
    state: "starting",
    runsOut: false,
    etaSeconds: null,
    observedSeconds: 0,
    idleSeconds: null,
    // Percent per second the projection uses; 0 while there is none.
    rate: 0
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

  var rate
  if (result.method === "average") {
    // The window's own average (over at least a day, so the first hours of a week do not alarm),
    // blended evenly with the last day when the history reaches that far.
    var average = used / Math.max(elapsed, PACE_DAY_SECONDS)
    var lastDay = lastDayRate(row.samples, used, now, windowStart)
    rate = lastDay === null ? average : (average + lastDay) / 2
    result.observedSeconds = elapsed
  } else {
    var burn = recentBurn(row.samples, used, now, windowStart, paceHalfLife(windowSeconds))
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
    rate = burn.percentPerSecond
  }

  // Time from now until 100 % at that rate.
  var etaSeconds = (100 - used) / rate
  result.state = "projecting"
  result.rate = rate
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

// The meter, tick, and pace figures show the side the user chose. Pace maths stay in usage.
function sideOfUsed(usedPercent, mode) {
  return mode === "Remaining" ? 100 - usedPercent : usedPercent
}

// Fill of a window's meter on the chosen side, 0-1; null when no window reports usage.
function meterFill(row, mode) {
  var used = windowUsed(row)
  return used === null ? null : sideOfUsed(used, mode) / 100
}

// Position of the pace tick on the chosen side, 0-1; -1 when no tick is drawn.
function meterMark(pace, mode) {
  return paceShowsMark(pace) ? sideOfUsed(pace.expected, mode) / 100 : -1
}

// The pace share as the chosen side reads it: "pace 50%" under Used, "pace 50% left" under Remaining.
// "Pace" is where steady use would be by now, the same point the meter's tick marks.
function expectedText(pace, mode) {
  return "pace " + Math.round(sideOfUsed(pace.expected, mode)) + "%" + (mode === "Remaining" ? " left" : "")
}

// The tick needs only the clock, so it is drawn whenever the limit has usage to compare with it:
// a short limit that is still collecting samples, or whose data is stale, keeps its tick and its
// ahead/behind badge, and only the projection waits.
function paceShowsMark(pace) {
  return !!pace && pace.known && !pace.exhausted && pace.used > 0
}

// Hover text for the tick: usage against the expected share, then what the projection says.
function paceTickText(pace, mode) {
  if (!paceShowsMark(pace)) return ""
  var delta = Math.round(pace.used - pace.expected)
  var side = mode === "Remaining" ? "Left " : "Used "
  var lines = [side + Math.round(sideOfUsed(pace.used, mode)) + "% · " + expectedText(pace, mode)]
  if (delta > 0) lines.push("Ahead by " + delta + " pts")
  else if (delta < 0) lines.push("Behind by " + (-delta) + " pts")
  else lines.push("On pace")
  lines.push(projectionLine(pace))
  return lines.join("\n")
}

// What the projection says about the rest of the window, for the tooltip.
function projectionLine(pace) {
  var basis = pace.method === "average" ? "At this window's pace: " : "At your recent rate: "
  if (pace.state === "projecting")
    return basis + (pace.runsOut ? "runs out in " + formatDuration(pace.etaSeconds) : "lasts until reset")
  if (pace.state === "idle") return "No increase for " + formatDuration(pace.idleSeconds) + " · no projection"
  if (pace.state === "collecting") return "Collecting samples for a projection"
  if (pace.state === "stale") return "No recent data · no projection"
  return ""
}

// One status line for a window card; empty when there is nothing to say.
// Whenever the tick is drawn, its expected share is printed beside it.
function paceText(pace, mode) {
  if (!pace || !pace.known) return ""
  if (pace.exhausted) return "Limit reached"
  if (!paceShowsMark(pace)) return ""
  var expected = expectedText(pace, mode)
  if (pace.state === "idle") return "Idle " + formatDuration(pace.idleSeconds) + " · " + expected
  if (pace.state === "collecting") return "Collecting data · " + expected
  if (pace.state === "stale") return "No recent data · " + expected
  if (pace.runsOut) return "Runs out in " + formatDuration(pace.etaSeconds) + " · " + expected
  return "Lasts until reset · " + expected
}

// Short ahead/behind badge for a card: points of use past or short of pace. Empty without a tick.
function paceBadgeText(pace) {
  if (!paceShowsMark(pace)) return ""
  var delta = Math.round(pace.used - pace.expected)
  if (delta > 0) return delta + " pts ahead"
  if (delta < 0) return (-delta) + " pts behind"
  return "On pace"
}

// What the card says when no tick is drawn yet: the reason, not a blank.
function paceStatusText(pace, mode) {
  var text = paceText(pace, mode)
  if (text !== "") return text
  if (!pace) return "No pace for this limit"
  if (!pace.known) return "Pace starts after " + Math.round(PACE_MIN_ELAPSED_FRACTION * 100) + "% of the window"
  return "No usage yet"
}

// One legend for all limit cards of a provider, shown once under them. Each card's line gives its figures.
// Lines are wrapped by hand: the shell tooltip does not wrap text.
var PACING_LEGEND = [
  "The tick on each meter is the pace: where usage",
  "would be by now if the limit were spread evenly",
  "over its window. Blocks past the tick are use",
  "ahead of pace.",
  "",
  "The line under each limit says when it would run",
  "out: \"Runs out in …\" before it resets, \"Lasts",
  "until reset\" if not.",
  "",
  "Limits of a day or less follow your recent rate",
  "(newest use counts most). Weekly and monthly",
  "limits follow this window's average blended with",
  "the last 24 hours, so one busy hour or a quiet",
  "weekend does not swing them.",
  "",
  "A short limit makes no projection while idle or",
  "collecting samples; no pace in the first " + Math.round(PACE_MIN_ELAPSED_FRACTION * 100) + "%",
  "of a window."
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

// Thresholds are stored as % left, so existing settings keep their meaning. Used mode shows and
// accepts the same boundary as % used (25 left is 75 used). Severity still gates on what is left.
function thresholdInMode(left, mode) {
  var value = clamp(left, 0, 100)
  return String(mode) === "Used" ? 100 - value : value
}

function thresholdToLeft(entered, mode) {
  var value = clamp(entered, 0, 100)
  return String(mode) === "Used" ? 100 - value : value
}

// Entry bounds for a stored % left range, expressed in the unit the mode shows.
function thresholdBounds(minLeft, maxLeft, mode) {
  return String(mode) === "Used" ? [100 - maxLeft, 100 - minLeft] : [minLeft, maxLeft]
}

// The figure an alert names: % used in Used mode, % left in Remaining mode.
function alertFigure(remaining, mode) {
  if (remaining === null || remaining === undefined) return null
  return String(mode) === "Used" ? usedFromRemaining(remaining) : clamp(remaining, 0, 100)
}

// Remaining alerts report a limit running low; Used alerts report high usage. Same boundaries, different wording.
function alertText(level, remaining, mode) {
  var figure = alertFigure(remaining, mode)
  if (figure === null) return ""
  var used = String(mode) === "Used"
  var title = level === "critical"
    ? (used ? "Near the limit" : "Almost out")
    : (used ? "High usage" : "Running low")
  return title + ": " + quotaText(figure, mode)
}

// A desktop notification body as literal text. Omarchy's notification server advertises body markup, so
// a provider's currency or label carrying `<img …>` or `<b>` would be read as markup; spec escaping keeps
// it text. The summary is plain text by the spec and is passed as is.
function notificationBody(text) {
  return String(text === null || text === undefined ? "" : text)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
}

// Providers that get a bar chip: a reading for the chosen window, money left to spend, or a failure the user must see.
function barProviders(providers, selector) {
  var result = []
  var list = listOrEmpty(providers)
  for (var i = 0; i < list.length; i++) {
    var chosen = typeof selector === "function" ? selector(list[i]) : selector
    if (String(list[i].status) === "error" || remainingForWindow(list[i], chosen) !== null || spendable(list[i]) !== null)
      result.push(list[i])
  }
  return result
}

// At most `max` chips (0 = no cap): the providers under the most pressure, kept in their usual
// order so chips do not jump around as figures change. `pressure(provider)` is lower when the
// provider is closer to a limit; ties keep the earlier provider. `size(provider)` is how many chips
// a provider takes (default one; one per account under "One chip per account"), so the cap counts
// chips: a provider that no longer fits leaves its room to a later, smaller one. The rest are
// returned as `hidden` for the overflow chip.
function limitChips(providers, max, pressure, size) {
  var list = listOrEmpty(providers)
  var cap = Math.floor(Number(max))
  var sizes = []
  var total = 0
  for (var s = 0; s < list.length; s++) {
    var chips = typeof size === "function" ? Math.max(1, Math.floor(Number(size(list[s])) || 1)) : 1
    sizes.push(chips)
    total += chips
  }
  if (!isFinite(cap) || cap <= 0 || total <= cap) return { shown: list.slice(), hidden: [] }
  var ranked = list.map(function (provider, index) { return { index: index, pressure: Number(pressure(provider)) } })
  ranked.sort(function (a, b) {
    var pa = isFinite(a.pressure) ? a.pressure : 100
    var pb = isFinite(b.pressure) ? b.pressure : 100
    return pa - pb || a.index - b.index
  })
  var keep = {}
  var room = cap
  for (var i = 0; i < ranked.length && room > 0; i++) {
    if (sizes[ranked[i].index] > room) continue
    keep[ranked[i].index] = true
    room -= sizes[ranked[i].index]
  }
  var result = { shown: [], hidden: [] }
  for (var j = 0; j < list.length; j++) result[keep[j] ? "shown" : "hidden"].push(list[j])
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

// How Settings sets up a sign-in provider: `login` runs in a floating Omarchy terminal; `mise` is
// the package Omarchy's mise installs the CLI from (the names `omarchy default agent` uses), so a
// missing CLI can be installed and signed in to in one go; `installUrl` is where to get a tool
// that neither covers, such as an app or IDE.
var PROVIDER_SETUP = {
  claude: { login: "claude auth login", mise: "claude", installUrl: "https://claude.com/product/claude-code" },
  codex: { login: "codex login", mise: "codex", installUrl: "https://developers.openai.com/codex/cli" },
  kimi: { login: "kimi login", installUrl: "https://github.com/MoonshotAI/kimi-cli" },
  opencode: { login: "opencode auth login", mise: "opencode", installUrl: "https://opencode.ai" },
  antigravity: { login: "agy", installUrl: "https://antigravity.google" },
  gemini: { login: "gemini", mise: "gemini", installUrl: "https://github.com/google-gemini/gemini-cli" },
  copilot: { login: "gh auth login", mise: "gh", installUrl: "https://cli.github.com" },
  cursor: { login: "cursor-agent login", mise: "cursor-agent", installUrl: "https://cursor.com/cli" },
  grok: { login: "grok login", mise: "npm:@xai-official/grok", installUrl: "https://www.npmjs.com/package/@xai-official/grok" },
  kiro: { login: "kiro-cli login", installUrl: "https://kiro.dev/cli" },
  jetbrains: { installUrl: "https://www.jetbrains.com/ai/" },
  factory: { login: "droid", installUrl: "https://factory.ai" },
  amp: { login: "amp login", mise: "npm:@sourcegraph/amp", installUrl: "https://ampcode.com" },
  kilo: { login: "kilo auth login", mise: "npm:@kilocode/cli", installUrl: "https://kilo.ai/cli" },
  codebuff: { login: "codebuff login", mise: "npm:codebuff", installUrl: "https://www.codebuff.com" },
  huggingface: { login: "hf auth login", installUrl: "https://huggingface.co/docs/huggingface_hub/installation" },
  nous: { login: "hermes portal", installUrl: "https://github.com/NousResearch/hermes-agent" },
  muse: { login: "muse login", installUrl: "https://developer.meta.ai/docs/muse-code" }
}

// Providers the widget reads on this computer, in scripts/usage-fetch.py's PROVIDER_ORDER, which is
// also their default order everywhere. `short` is the tile and chip name. `auth` says how one is set
// up: "signin" (a CLI, app, or IDE sign-in the provider owns), "key" (an API key saved here or set in
// `keyEnv`, the first environment variable the backend reads), or "both". `keysUrl` is where a key is
// created, `keysLinkText` the link to it, `keyLabel` what the saved secret is called (TypeSafe's is a
// console Cookie header, not an API key), and `keyHelp` how to get it; `signIn` is the one-line hint
// shown while a provider is not set up. `money` marks providers that lead with a prepaid balance rather
// than percentages; `lightIcon` marks dark marks that ship an `assets/<id>-light.svg` for light surfaces.
var LOCAL_PROVIDERS = [
  { id: "claude", name: "Claude Code", short: "Claude", auth: "signin", signIn: "Run claude auth login" },
  { id: "codex", name: "OpenAI Codex", short: "Codex", auth: "signin", signIn: "Run codex login", lightIcon: true },
  { id: "kimi", name: "Kimi Code", short: "Kimi", auth: "signin", signIn: "Run kimi login" },
  { id: "opencode", name: "OpenCode Go", short: "OpenCode", auth: "signin", keyEnv: "OPENCODE_GO_API_KEY", signIn: "Run opencode auth login" },
  { id: "antigravity", name: "Antigravity", short: "Antigravity", auth: "signin", signIn: "Open Antigravity, or run agy and sign in", lightIcon: true },
  { id: "gemini", name: "Gemini CLI", short: "Gemini", auth: "signin", signIn: "Run gemini and sign in with Google" },
  { id: "copilot", name: "GitHub Copilot", short: "Copilot", auth: "signin", keyEnv: "COPILOT_API_TOKEN", signIn: "Run gh auth login", lightIcon: true },
  { id: "cursor", name: "Cursor", short: "Cursor", auth: "signin", signIn: "Sign in to Cursor, or run cursor-agent login", lightIcon: true },
  { id: "grok", name: "Grok CLI", short: "Grok", auth: "signin", signIn: "Run grok login", lightIcon: true },
  { id: "kiro", name: "Kiro", short: "Kiro", auth: "signin", signIn: "Run kiro-cli login" },
  { id: "jetbrains", name: "JetBrains AI", short: "JetBrains", auth: "signin", signIn: "Use AI Assistant in a JetBrains IDE", lightIcon: true },
  { id: "nous", name: "Nous Portal", short: "Nous", auth: "signin", signIn: "Run hermes portal and sign in", lightIcon: true },
  { id: "muse", name: "Muse Code", short: "Muse", auth: "signin", signIn: "Run muse login and sign in" },
  { id: "factory", name: "Droid", short: "Droid", auth: "both", keyEnv: "FACTORY_API_KEY", keysUrl: "https://app.factory.ai/settings/api-keys", signIn: "Save a Factory API key", lightIcon: true },
  { id: "amp", name: "Amp", short: "Amp", auth: "both", keyEnv: "AMP_API_KEY", keysUrl: "https://ampcode.com/settings", signIn: "Run amp login, or save a key" },
  { id: "kilo", name: "Kilo Code", short: "Kilo", auth: "both", keyEnv: "KILO_API_KEY", keysUrl: "https://app.kilo.ai/profile", signIn: "Run kilo auth login, or save a key", lightIcon: true },
  { id: "codebuff", name: "Codebuff", short: "Codebuff", auth: "both", keyEnv: "CODEBUFF_API_KEY", keysUrl: "https://www.codebuff.com/profile", signIn: "Run codebuff login, or save a key", lightIcon: true },
  { id: "huggingface", name: "Hugging Face", short: "Hugging Face", auth: "both", keyEnv: "HF_TOKEN", keysUrl: "https://huggingface.co/settings/tokens", signIn: "Run hf auth login, or save a token" },
  { id: "zai", name: "Z.ai Coding Plan", short: "Z.ai", auth: "key", keyEnv: "Z_AI_API_KEY", keysUrl: "https://z.ai/manage-apikey/apikey-list", signIn: "Save a Z.ai API key", lightIcon: true },
  { id: "minimax", name: "MiniMax Coding Plan", short: "MiniMax", auth: "key", keyEnv: "MINIMAX_CODING_API_KEY", keysUrl: "https://platform.minimax.io/console/plan", signIn: "Save a MiniMax Subscription Key (it starts with sk-cp-)" },
  { id: "synthetic", name: "Synthetic", short: "Synthetic", auth: "key", keyEnv: "SYNTHETIC_API_KEY", keysUrl: "https://synthetic.new/user-settings/api", signIn: "Save a Synthetic API key", lightIcon: true },
  { id: "chutes", name: "Chutes", short: "Chutes", auth: "key", keyEnv: "CHUTES_API_KEY", keysUrl: "https://chutes.ai/app/settings/api-keys", signIn: "Save a Chutes API key", lightIcon: true },
  { id: "ollama", name: "Ollama Cloud", short: "Ollama", auth: "key", keyEnv: "OLLAMA_API_KEY", keysUrl: "https://ollama.com/settings/keys", signIn: "Save an Ollama API key", lightIcon: true },
  { id: "warp", name: "Warp", short: "Warp", auth: "key", keyEnv: "WARP_API_KEY", keysUrl: "https://oz.warp.dev/settings", signIn: "Save a personal Warp API key (Warp → Settings → Cloud platform → API keys)" },
  { id: "zenmux", name: "ZenMux", short: "ZenMux", auth: "key", keyEnv: "ZENMUX_MANAGEMENT_API_KEY", keysUrl: "https://zenmux.ai/platform/management", signIn: "Save a ZenMux management key", lightIcon: true },
  { id: "clinepass", name: "Cline", short: "Cline", auth: "key", keyEnv: "CLINE_API_KEY", keysUrl: "https://app.cline.bot/dashboard/account?tab=api-keys", signIn: "Save a Cline API key", lightIcon: true },
  { id: "alibaba", name: "Alibaba Coding Plan", short: "Alibaba", auth: "key", keyEnv: "ALIBABA_CODING_PLAN_API_KEY", keysUrl: "https://modelstudio.console.alibabacloud.com/ap-southeast-1/?tab=coding-plan#/efm/coding_plan", signIn: "Save an Alibaba Coding Plan API key" },
  { id: "commandcode", name: "Command Code", short: "Command Code", auth: "key", keyEnv: "COMMAND_CODE_API_KEY", keysUrl: "https://commandcode.ai/studio", signIn: "Save a Command Code API key", lightIcon: true },
  { id: "devpass", name: "DevPass", short: "DevPass", auth: "key", keyEnv: "DEVPASS_API_KEY", signIn: "Save a DevPass API key", lightIcon: true },
  { id: "xkiro", name: "xKiro", short: "xKiro", auth: "key", keyEnv: "XKIRO_API_KEY", signIn: "Save an xKiro API key" },
  { id: "ibmbob", name: "IBM Bob", short: "IBM Bob", auth: "key", keyEnv: "BOBSHELL_API_KEY", keysUrl: "https://bob.ibm.com", signIn: "Save an IBM Bob API key" },
  { id: "umans", name: "Umans", short: "Umans", auth: "key", keyEnv: "UMANS_AI_CODING_PLAN_API_KEY", keysUrl: "https://app.umans.ai/billing", signIn: "Save an Umans API key", lightIcon: true },
  { id: "neuralwatt", name: "Neuralwatt", short: "Neuralwatt", auth: "key", keyEnv: "NEURALWATT_API_KEY", signIn: "Save a Neuralwatt API key" },
  { id: "aixy", name: "Aixy", short: "Aixy", auth: "key", keyEnv: "AIXY_API_KEY", signIn: "Save an Aixy API key", lightIcon: true },
  { id: "clawrouter", name: "ClawRouter", short: "ClawRouter", auth: "key", keyEnv: "CLAWROUTER_API_KEY", signIn: "Save a ClawRouter API key" },
  { id: "openrouter", name: "OpenRouter", short: "OpenRouter", auth: "key", money: true, keyEnv: "OPENROUTER_API_KEY", keysUrl: "https://openrouter.ai/settings/keys", signIn: "Save an OpenRouter key" },
  { id: "deepseek", name: "DeepSeek", short: "DeepSeek", auth: "key", money: true, keyEnv: "DEEPSEEK_API_KEY", keysUrl: "https://platform.deepseek.com/api_keys", signIn: "Save a DeepSeek key" },
  { id: "moonshot", name: "Moonshot", short: "Moonshot", auth: "key", money: true, keyEnv: "MOONSHOT_API_KEY", keysUrl: "https://platform.kimi.ai/console/api-keys", signIn: "Save a Moonshot key", lightIcon: true },
  { id: "venice", name: "Venice", short: "Venice", auth: "key", money: true, keyEnv: "VENICE_API_KEY", keysUrl: "https://venice.ai/settings/api", signIn: "Save a Venice Admin API key (inference keys cannot read the balance)", lightIcon: true },
  { id: "deepinfra", name: "DeepInfra", short: "DeepInfra", auth: "key", money: true, keyEnv: "DEEPINFRA_API_KEY", keysUrl: "https://deepinfra.com/dash/api_keys", signIn: "Save a DeepInfra key", lightIcon: true },
  { id: "vercel", name: "Vercel AI Gateway", short: "Vercel", auth: "key", money: true, keyEnv: "AI_GATEWAY_API_KEY", keysUrl: "https://vercel.com/d?to=%2F%5Bteam%5D%2F%7E%2Fai-gateway%2Fapi-keys&title=AI+Gateway+API+Keys", signIn: "Save an AI Gateway key", lightIcon: true },
  { id: "poe", name: "Poe", short: "Poe", auth: "key", money: true, keyEnv: "POE_API_KEY", keysUrl: "https://poe.com/api/keys", signIn: "Save a Poe API key" },
  { id: "atlascloud", name: "Atlas Cloud", short: "Atlas", auth: "key", money: true, keyEnv: "ATLASCLOUD_API_KEY", keysUrl: "https://www.atlascloud.ai/console", signIn: "Save an Atlas Cloud API key with balance access", lightIcon: true },
  { id: "hyper", name: "Charm Hyper", short: "Hyper", auth: "key", money: true, keyEnv: "HYPER_API_KEY", keysUrl: "https://hyper.charm.land", signIn: "Save a Hyper API key" },
  { id: "sailresearch", name: "Sail Research", short: "Sail", auth: "key", money: true, keyEnv: "SAIL_API_KEY", keysUrl: "https://app.sailresearch.com", signIn: "Save a Sail Research API key", lightIcon: true },
  { id: "sofya", name: "Sofya", short: "Sofya", auth: "key", money: true, keyEnv: "SOFYA_API_KEY", keysUrl: "https://sofya.co/dashboard", signIn: "Save a Sofya API key" },
  { id: "v0", name: "v0", short: "v0", auth: "key", money: true, keyEnv: "V0_API_KEY", keysUrl: "https://v0.app/settings/keys", signIn: "Save a v0 API key", lightIcon: true },
  { id: "manus", name: "Manus", short: "Manus", auth: "key", money: true, keyEnv: "MANUS_API_KEY", keysUrl: "https://manus.im/app#settings/developers", signIn: "Save a Manus API key", lightIcon: true },
  { id: "typesafe", name: "TypeSafe", short: "TypeSafe", auth: "key", money: true, keyEnv: "TYPESAFE_COOKIE", keysUrl: "https://console.typesafe.ai/settings/billing", keyLabel: "Cookie header", keysLinkText: "Open billing ↗", keyHelp: "Open billing signed in, then copy the request's Cookie header from the browser's developer tools (Network). It lasts as long as that console session.", signIn: "Paste the Cookie header from console.typesafe.ai/settings/billing (an inference API key cannot replace it)", lightIcon: true }
].map(function (entry) {
  // Every entry carries every field, so QML bindings never read `undefined` as text.
  return Object.assign({ money: false, keyEnv: "", keysUrl: "", keyLabel: "API key", keysLinkText: "Get a key ↗", keyHelp: "",
    lightIcon: false, login: "", mise: "", installUrl: "" },
    entry, PROVIDER_SETUP[entry.id] || {})
})
var LOCAL_PROVIDER_IDS = LOCAL_PROVIDERS.map(function (entry) { return entry.id })
// Providers whose key can be saved in settings, as the `<id>KeyFile` setting.
var KEY_PROVIDER_IDS = providerIds(function (entry) { return entry.auth !== "signin" })

function providerIds(keep) {
  var result = []
  for (var i = 0; i < LOCAL_PROVIDERS.length; i++)
    if (keep(LOCAL_PROVIDERS[i])) result.push(LOCAL_PROVIDERS[i].id)
  return result
}

// Preferences Settings → Advanced → Reset restores, with their defaults (the same values as
// manifest.json). Connections and secrets are not here, so a reset never disconnects anything:
// the source, server URLs, saved keys and tokens, T3 servers, and custom model prices are kept.
// Every provider with a sign-in of its own is monitored by default; one that is not signed in
// simply does not appear. API-key-only providers stay off until turned on, and every monitored
// provider gets a chip. `dismissedProviders` lists providers the user chose not to monitor, so
// one found on this computer is not suggested again.
var DEFAULT_SETTINGS = {
  enabledProviders: providerIds(function (entry) { return entry.auth !== "key" }),
  barProviders: LOCAL_PROVIDER_IDS.slice(),
  dismissedProviders: [],
  providerOrder: "[]",
  providerQuotaModes: "{}",
  barProviderLimits: "{}",
  barDisplayMode: "Percentages",
  barWindow: "auto",
  barWindowSecondary: "none",
  barShowResets: false,
  barResetTimeFormat: "24h",
  barResetDateFormat: "DD/MM",
  hideExhaustedProviders: false,
  barMaxChips: 4,
  quotaMode: "Used",
  providerColors: false,
  squareUsageCards: true,
  hideAccountEmails: true,
  notifyLimitThresholds: true,
  warningThreshold: 25,
  criticalThreshold: 10,
  creditWarningUsd: 5,
  creditCriticalUsd: 1,
  refreshIntervalSec: 900,
  costLocalProviders: ["claude", "codex", "opencode"],
  liveAccountActivity: true,
  ompLocal: true,
  barAccountMode: "dots",
  motion: "system",
  accountModes: "{}"
}

// The keys of `settings` that differ from their default; what Reset would change.
function changedFromDefaults(settings) {
  var changed = []
  for (var key in DEFAULT_SETTINGS) {
    var current = settings ? settings[key] : undefined
    if (current !== undefined && current !== null && JSON.stringify(current) !== JSON.stringify(DEFAULT_SETTINGS[key]))
      changed.push(key)
  }
  return changed
}

function localProvider(providerId) {
  for (var i = 0; i < LOCAL_PROVIDERS.length; i++)
    if (LOCAL_PROVIDERS[i].id === String(providerId)) return LOCAL_PROVIDERS[i]
  return null
}

function providerShortName(provider) {
  var entry = localProvider(provider && provider.id)
  return entry ? entry.short : String(provider && (provider.name || provider.id) || "")
}

// Brand colour per provider. The cost chart always uses these; the bar and Limits use them when
// providerColors is on. They are mid-tones, so a chip stays readable on dark and light bars, and they
// stay apart from one another; providers whose mark is plain black or white get a hue of their own.
var PROVIDER_COLORS = {
  claude: "#d97757",
  codex: "#10a37f",
  kimi: "#eab308",
  opencode: "#a78bfa",
  antigravity: "#708fe6",
  gemini: "#8e75b2",
  copilot: "#3fb950",
  cursor: "#94a3b8",
  grok: "#a8a29e",
  kiro: "#9046ff",
  jetbrains: "#d8188b",
  factory: "#cb720b",
  amp: "#d5818c",
  kilo: "#b8a01c",
  codebuff: "#8eb620",
  huggingface: "#fb923c",
  zai: "#157cc1",
  minimax: "#e73562",
  synthetic: "#e25ff7",
  chutes: "#20b6b6",
  ollama: "#cfa16e",
  warp: "#01a4ff",
  zenmux: "#e670b7",
  clinepass: "#0cb9e4",
  openrouter: "#6467f2",
  deepseek: "#4d6bfe",
  moonshot: "#64759a",
  venice: "#e5322d",
  deepinfra: "#3692a1",
  vercel: "#787878",
  poe: "#c026d3",
  nous: "#c99a52",
  muse: "#3b82f6",
  alibaba: "#ff6a00",
  commandcode: "#8c4edd",
  devpass: "#2563eb",
  xkiro: "#22c55e",
  ibmbob: "#5b6cf0",
  umans: "#f472b6",
  neuralwatt: "#d55934",
  aixy: "#ec744a",
  clawrouter: "#e0622b",
  atlascloud: "#5975f5",
  hyper: "#9cb83a",
  sailresearch: "#4a6fb5",
  sofya: "#a3ab1e",
  v0: "#8b8b9e",
  manus: "#7b6ff0",
  typesafe: "#0ea5a4"
}

// ---- Settings → Providers (local mode)

// The latest reading of one provider in a backend payload's `providers`, or null.
function readingFor(readings, providerId) {
  var list = listOrEmpty(readings)
  for (var i = 0; i < list.length; i++)
    if (list[i] && list[i].id === providerId) return list[i]
  return null
}

// Whether a private key file is saved for a provider (its `<id>KeyFile` setting).
function keySaved(settings, providerId) {
  var path = settings ? settings[String(providerId) + "KeyFile"] : ""
  return path !== undefined && path !== null && String(path).trim() !== ""
}

// Every private file the settings point at: `<id>KeyFile`, the proxy and Keeper secrets, extra keys,
// and T3 tokens. A restore deletes the ones the new settings no longer use.
function secretPaths(settings) {
  var paths = []
  function add(path) { if (typeof path === "string" && path.trim() !== "" && paths.indexOf(path) < 0) paths.push(path) }
  if (!settings) return paths
  for (var key in settings) if (/KeyFile$/.test(key) || key === "costKeeperPasswordFile") add(settings[key])
  var extra = parseExtraKeys(settings.extraKeys)
  for (var id in extra) for (var i = 0; i < extra[id].keys.length; i++) add(extra[id].keys[i].file)
  var servers = []
  try { servers = JSON.parse(String(settings.costT3Servers || "[]")) } catch (e) { servers = [] }
  if (Array.isArray(servers)) for (var j = 0; j < servers.length; j++) if (servers[j]) add(servers[j].tokenFile)
  return paths
}

// ---- Several keys for one provider. The `extraKeys` setting is a JSON string:
// {"<provider>": {"primary": "<name of the <id>KeyFile key>", "keys": [{"id": "k-1a2b3c4d", "label": "Work",
// "file": "/private/key-….key"}]}}. The usual key stays where it was, so nothing needs migrating; the
// backend reads each extra key with `--extra-key PROVIDER=ID=PATH`, and names never leave the widget.
var EXTRA_KEY_LIMIT = 8
var EXTRA_KEY_LABEL_LIMIT = 40

function parseExtraKeys(raw) {
  var parsed = null
  try { parsed = JSON.parse(String(raw || "{}")) } catch (e) { parsed = null }
  var result = {}
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return result
  for (var i = 0; i < KEY_PROVIDER_IDS.length; i++) {
    var id = KEY_PROVIDER_IDS[i]
    var entry = parsed[id]
    if (!entry || typeof entry !== "object") continue
    var keys = []
    var rows = Array.isArray(entry.keys) ? entry.keys : []
    for (var j = 0; j < rows.length && keys.length < EXTRA_KEY_LIMIT; j++) {
      var row = rows[j]
      if (!row || !/^k-[0-9a-f]{8}$/.test(String(row.id)) || typeof row.file !== "string" || row.file.trim() === "") continue
      keys.push({ id: String(row.id), label: String(row.label || "").slice(0, EXTRA_KEY_LABEL_LIMIT), file: row.file })
    }
    var primary = String(entry.primary || "").slice(0, EXTRA_KEY_LABEL_LIMIT)
    if (keys.length || primary) result[id] = { primary: primary, keys: keys }
  }
  return result
}

function extraKeysFor(raw, providerId) {
  return parseExtraKeys(raw)[String(providerId)] || { primary: "", keys: [] }
}

function withExtraKeys(raw, providerId, entry) {
  var all = parseExtraKeys(raw)
  if (entry.keys.length || entry.primary) all[String(providerId)] = entry
  else delete all[String(providerId)]
  return JSON.stringify(all)
}

function addExtraKey(raw, providerId, key) {
  var entry = extraKeysFor(raw, providerId)
  if (entry.keys.length >= EXTRA_KEY_LIMIT) return String(raw || "{}")
  entry.keys.push({ id: key.id, label: String(key.label || "").trim().slice(0, EXTRA_KEY_LABEL_LIMIT), file: key.file })
  return withExtraKeys(raw, providerId, entry)
}

function removeExtraKey(raw, providerId, keyId) {
  var entry = extraKeysFor(raw, providerId)
  entry.keys = entry.keys.filter(function (key) { return key.id !== keyId })
  return withExtraKeys(raw, providerId, entry)
}

function renamePrimaryKey(raw, providerId, label) {
  var entry = extraKeysFor(raw, providerId)
  entry.primary = String(label || "").trim().slice(0, EXTRA_KEY_LABEL_LIMIT)
  return withExtraKeys(raw, providerId, entry)
}

function newExtraKeyId() {
  var hex = ""
  for (var i = 0; i < 8; i++) hex += Math.floor(Math.random() * 16).toString(16)
  return "k-" + hex
}

// `--extra-key PROVIDER=ID=PATH` for every extra key of a monitored provider.
function extraKeyArguments(raw, providerIds) {
  var all = parseExtraKeys(raw)
  var args = []
  for (var id in all) {
    if (!contains(providerIds, id)) continue
    for (var i = 0; i < all[id].keys.length; i++) args.push("--extra-key", id + "=" + all[id].keys[i].id + "=" + all[id].keys[i].file)
  }
  return args
}

// The name on an account card. Omarchy subscription accounts carry the name chosen when they were
// added (`label`); a provider's extra keys use the names saved in Settings; proxy and unnamed accounts
// fall back to the email, or "Account N" while account emails are hidden.
function accountName(account, extraRaw, hideEmails, index) {
  if (!account) return ""
  var named = String(account.label || "")
  if (!named && (account.accountId === "primary" || /^k-[0-9a-f]{8}$/.test(String(account.accountId)))) {
    var entry = extraKeysFor(extraRaw, account.id)
    if (account.accountId === "primary") named = entry.primary || "Main key"
    for (var i = 0; i < entry.keys.length && !named; i++)
      if (entry.keys[i].id === account.accountId) named = entry.keys[i].label || "Key " + (i + 2)
  }
  var email = String(account.account || "")
  if (named) return named + (account.label && account.active ? " · in use" : "") + (!hideEmails && email ? " · " + email : "")
  return hideEmails || !email ? "Account " + index : email
}

// `list` with `id` present or absent, in `order`; ids that `order` does not know are dropped.
function withMember(list, id, present, order) {
  var result = []
  var ids = listOrEmpty(order)
  for (var i = 0; i < ids.length; i++)
    if (ids[i] === id ? present : contains(list, ids[i])) result.push(ids[i])
  return result
}

// Providers set up on this computer (the backend's `detected`) that are neither monitored nor
// dismissed, in registry order: what Settings and Limits suggest.
function foundProviders(detected, enabled, dismissed) {
  var result = []
  for (var i = 0; i < LOCAL_PROVIDERS.length; i++) {
    var id = LOCAL_PROVIDERS[i].id
    if (contains(detected, id) && !contains(enabled, id) && !contains(dismissed, id)) result.push(LOCAL_PROVIDERS[i])
  }
  return result
}

// Settings → Providers places every provider once, so 31 of them never read as one long list:
// - listed: monitored and in use (connected, failing, keyed, found here, or not checked yet), as the
//   draggable rows, in `ordered` (the registry in the saved order);
// - waiting: monitored, but the last check found no sign-in; folded away until one appears, which
//   is how every default sign-in provider a user does not have stays out of sight;
// - found: set up on this computer but not monitored, offered with one click;
// - moreSignIns / moreKeys: everything else, in registry order.
function providerSections(ordered, enabled, dismissed, readings, detected, settings) {
  var sections = { listed: [], waiting: [], found: foundProviders(detected, enabled, dismissed), moreSignIns: [], moreKeys: [] }
  var rows = listOrEmpty(ordered)
  for (var i = 0; i < rows.length; i++) {
    var entry = rows[i]
    if (!contains(enabled, entry.id)) continue
    var reading = readingFor(readings, entry.id)
    var inUse = entry.auth === "key" || keySaved(settings, entry.id) || contains(detected, entry.id)
      || !reading || reading.errorKind !== "no_credentials"
    sections[inUse ? "listed" : "waiting"].push(entry)
  }
  for (var j = 0; j < LOCAL_PROVIDERS.length; j++) {
    var other = LOCAL_PROVIDERS[j]
    if (contains(enabled, other.id) || sections.found.indexOf(other) !== -1) continue
    sections[other.auth === "key" ? "moreKeys" : "moreSignIns"].push(other)
  }
  return sections
}

var STATUS_FALLBACKS = {
  rate_limited: "Rate limited",
  timeout: "Timed out",
  network: "Offline",
  malformed: "Unreadable usage data",
  http: "Provider error",
  config: "Setup problem",
  cli_unavailable: "CLI not found"
}

// The line under a monitored provider in Settings: what the last check found and, when something is
// missing, what to do. `tone` is "ok", "muted", or "error". A saved key never reports a missing
// sign-in, so such a reading predates the key and the provider reads as still being checked. With
// `withButton` the row also shows a Sign in or Install button, so the hint is left out.
function providerStatus(entry, reading, hasKey, checking, withButton) {
  var pending = { text: checking ? "Checking…" : "Not checked yet", tone: "muted" }
  if (!reading) return pending
  if (reading.status === "ok") {
    var plan = String(reading.plan || "")
    return { text: "Connected" + (plan !== "" ? " · " + plan : ""), tone: "ok" }
  }
  if (reading.status !== "error") return { text: "", tone: "muted" }
  var kind = String(reading.errorKind || "")
  var hint = withButton ? "" : " — " + entry.signIn
  if (kind === "no_credentials") {
    if (hasKey) return pending
    return entry.auth === "key" ? { text: "No key saved", tone: "muted" }
      : { text: "Not signed in" + hint, tone: "muted" }
  }
  if (kind === "expired")
    return entry.auth === "key" || hasKey ? { text: "Key rejected", tone: "error" }
      : { text: "Sign-in expired" + hint, tone: "error" }
  var message = String(reading.message || "")
  if (message !== "") return { text: message, tone: "error" }
  return { text: Object.prototype.hasOwnProperty.call(STATUS_FALLBACKS, kind) ? STATUS_FALLBACKS[kind] : "Error", tone: "error" }
}

// What the key editor says: the environment always wins, and for a provider with a sign-in of its
// own a saved key replaces that sign-in.
function keyHint(entry) {
  return (entry.keyHelp ? entry.keyHelp + " " : "")
    + (entry.auth === "both" ? "Optional: used instead of the sign-in. " : "")
    + (entry.keyEnv ? entry.keyEnv + " in the environment takes precedence." : "")
}

// The one-click way to fix a provider that is not signed in, or `kind: ""` when there is nothing to
// offer. `installed` is the backend's list of providers whose CLI is on PATH; when it is unknown the
// CLI is assumed present. Order of preference: sign in with the CLI that is there; install it with
// mise and sign in, in one terminal; or link to where the tool comes from.
function setupAction(entry, reading, installed) {
  var none = { kind: "", label: "", command: "", url: "" }
  if (!entry || entry.auth === "key") return none
  if (reading && (reading.status === "ok" || !errorNeedsSignIn(reading.errorKind))) return none
  var present = installed === null || installed === undefined || contains(installed, entry.id)
  if (present && entry.login !== "")
    return { kind: "signin", label: "Sign in", command: entry.login, url: "" }
  if (!present && entry.mise !== "" && entry.login !== "")
    return { kind: "install", label: "Install and sign in", command: "mise use -g " + entry.mise + " && " + entry.login, url: "" }
  if (!present && entry.installUrl !== "")
    return { kind: "link", label: "Get " + entry.short + " ↗", command: "", url: entry.installUrl }
  return none
}

// Providers whose name, short name, or id contains `text`, ignoring case; all of them when blank.
function filterProviders(entries, text) {
  var needle = String(text || "").trim().toLowerCase()
  var list = listOrEmpty(entries)
  var result = []
  for (var i = 0; i < list.length; i++) {
    var entry = list[i]
    var haystack = (String(entry.name) + " " + String(entry.short) + " " + String(entry.id)).toLowerCase()
    if (needle === "" || haystack.indexOf(needle) !== -1) result.push(entry)
  }
  return result
}

// "A", "A and B", "A, B and C".
function joinNames(names) {
  var list = listOrEmpty(names)
  if (list.length <= 1) return list.length ? String(list[0]) : ""
  return Array.prototype.slice.call(list, 0, -1).join(", ") + " and " + list[list.length - 1]
}

// The Limits view's pointer to Settings: "Gemini CLI and GitHub Copilot found on this computer";
// past three providers, "A, B and 2 more found on this computer". Empty when nothing is found.
function foundSummary(entries) {
  var list = listOrEmpty(entries)
  if (list.length === 0) return ""
  var names = []
  var shown = list.length > 3 ? 2 : list.length
  for (var i = 0; i < shown; i++) names.push(list[i].name)
  if (list.length > shown) names.push((list.length - shown) + " more")
  return joinNames(names) + " found on this computer"
}

var CURRENCY_PREFIX = { USD: "$", EUR: "€", GBP: "£", CNY: "¥" }

// "$1,234.56" / "¥12.00": grouped the same way Qt.locale("en_US") does, without depending on the
// QML engine, so the formatter stays a pure function. Tiny nonzero amounts keep four decimals.
// A code that is not a three-letter currency is a unit such as POINTS or CREDITS, whose balances
// run to millions; it reads "1.25M points", which keeps a chip short.
function formatMoney(value, currency) {
  if (value === null || value === undefined || !isFinite(Number(value))) return "—"
  var amount = Number(value)
  var code = String(currency || "USD").toUpperCase()
  if (!/^[A-Z]{3}$/.test(code)) {
    var size = Math.abs(amount)
    return (amount < 0 ? "-" : "") + (size >= 1000 ? formatTokens(size) : trimNumber(size)) + " " + code.toLowerCase()
  }
  var prefix = Object.prototype.hasOwnProperty.call(CURRENCY_PREFIX, code) ? CURRENCY_PREFIX[code] : code + " "
  if (Math.abs(amount) > 0 && Math.abs(amount) < 0.01) return (amount < 0 ? "-" : "") + prefix + Math.abs(amount).toFixed(4)
  var parts = Math.abs(amount).toFixed(2).split(".")
  var whole = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  return (amount < 0 ? "-" : "") + prefix + whole + "." + parts[1]
}

// Currency of a provider's balance; "USD" when it has none.
function moneyCurrency(provider) {
  var credits = provider && provider.credits
  return credits && credits.currency ? String(credits.currency).toUpperCase() : "USD"
}

// Money a provider can still spend now (OpenRouter, DeepSeek): the backend's `spendable`, the
// lowest of the balance and every spending limit's allowance. Null for providers measured only in
// percentages.
function spendable(provider) {
  var credits = provider && provider.credits
  if (!credits) return null
  var amount = Number(credits.spendable)
  if (credits.spendable === null || credits.spendable === undefined || !isFinite(amount)) return null
  return Math.max(0, amount)
}

// Money on the side "Show limits as" picks, like every percentage: under Used, what the binding
// allowance has spent ("$73.42 used" of a $75.00 balance, or of a key limit); under Remaining, what
// can still be spent ("$1.58 left"). The allowance that binds is the one `spendable` came from.
// `share` is the shown side as 0-100 of that allowance, null when its size is unknown.
// Returns { amount, total, share, unit, currency, text } or null for providers without money;
// `text` is the amount already formatted in the balance's currency.
function moneyView(provider, mode) {
  var left = spendable(provider)
  if (left === null) return null
  var credits = provider.credits
  var total = null
  var balance = Number(credits.remaining)
  if (credits.remaining !== null && credits.remaining !== undefined && Math.abs(balance - left) < 0.005
      && Number(credits.total) > 0) {
    total = Number(credits.total)
  } else {
    var rows = listOrEmpty(provider.windows)
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i]
      if (row && row.unit === "usd" && Number(row.limitAmount) > 0 && Math.abs(Number(row.remainingAmount) - left) < 0.005) {
        total = Number(row.limitAmount)
        break
      }
    }
  }
  var used = total === null ? null : Math.max(0, total - left)
  var currency = moneyCurrency(provider)
  if (String(mode) === "Used" && used !== null)
    return { amount: used, total: total, share: clamp(used / total * 100, 0, 100), unit: "used",
             currency: currency, text: formatMoney(used, currency) }
  return { amount: left, total: total, share: total === null ? null : clamp(left / total * 100, 0, 100), unit: "left",
           currency: currency, text: formatMoney(left, currency) }
}

// Low-balance severity from dollar thresholds: at or below `critical` is critical, at or below `warning` warns.
function moneySeverity(amount, warning, critical) {
  if (amount === null || amount === undefined || !isFinite(Number(amount))) return "none"
  var value = Number(amount)
  if (value <= Number(critical)) return "critical"
  if (value <= Number(warning)) return "warning"
  return "ok"
}

// How long the money lasts at this UTC week's average daily spend, e.g. "about 6 weeks".
// Empty when there is no spend yet this week or the week has barely started.
function moneyRunway(amount, weeklySpend, nowSeconds) {
  var spentWeek = Number(weeklySpend)
  if (amount === null || amount === undefined || !isFinite(spentWeek) || spentWeek <= 0) return ""
  var now = new Date(nowSeconds * 1000)
  var weekday = (now.getUTCDay() + 6) % 7
  var weekStart = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - weekday) / 1000
  var days = (nowSeconds - weekStart) / 86400
  if (days < 0.25) return ""
  var left = Number(amount) / (spentWeek / days)
  if (left < 1) return "less than a day"
  if (left < 14) return "about " + Math.round(left) + (Math.round(left) === 1 ? " day" : " days")
  if (left < 90) return "about " + Math.round(left / 7) + " weeks"
  return "more than 3 months"
}

// Brand colour for a provider id; ids without one (T3 servers, local-* sources) get the fallback.
function providerAccent(providerId, fallback) {
  var id = String(providerId || "")
  return Object.prototype.hasOwnProperty.call(PROVIDER_COLORS, id) ? PROVIDER_COLORS[id] : fallback
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

// ---- 1.9 QmlCosts ----

// Costs tab (DESIGN §4). Labels stay English like the rest of the panel; clock times are formatted by
// the QML caller in the user's clock format.
var COST_DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
var COST_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
var COST_AGENT_LABELS = {
  main: { name: "Main sessions", context: "what you type" },
  subagent: { name: "Subagents", context: "tasks and workpools" }
}

// Whole number with thousands separators: 1375 -> "1,375".
function costCount(value) {
  var amount = Math.round(Number(value) || 0)
  return (amount < 0 ? "-" : "") + String(Math.abs(amount)).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

function costRequestsText(count) {
  var amount = Math.max(0, Math.round(Number(count) || 0))
  return costCount(amount) + (amount === 1 ? " request" : " requests")
}

// A bucket start as a local Date. A day ("2030-01-09") is that calendar day where the user is, not
// UTC midnight; a timestamp keeps its instant. Null when unreadable.
function costBucketDate(start) {
  var text = String(start || "")
  var day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text)
  if (day) return new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]))
  if (!/^\d{4}-\d{2}-\d{2}T/.test(text)) return null
  var date = new Date(text)
  return isNaN(date.getTime()) ? null : date
}

// The chart keys a bar by its time, so it keeps its delegate across refreshes and period switches.
// Days key by date. The 24-hour window rolls with every scan, so an hour bucket keys by the clock
// hour it starts in: a rescan ten minutes later lands on the same bars. "" when unreadable.
function costBucketKey(start) {
  var text = String(start || "")
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return "d" + text
  var date = costBucketDate(text)
  return date ? "h" + Math.floor(date.getTime() / 3600000) : ""
}

function costDayName(date) {
  return date ? COST_DAY_NAMES[date.getDay()] : ""
}

function costMonthDay(date) {
  return date ? COST_MONTH_NAMES[date.getMonth()] + " " + date.getDate() : ""
}

// The span a total covers, for "vs previous …".
function costPeriodPhrase(days) {
  var count = Math.round(Number(days) || 0)
  return count === 1 ? "24 h" : count + " days"
}

// A row's figure for the chosen metric: tokens always count; cost is null when nothing was priced.
function costMetricValue(row, metric) {
  if (!row) return null
  if (metric === "tokens") return Math.max(0, Number(row.totalTokens) || 0)
  if (row.costUsd === null || row.costUsd === undefined) return null
  var amount = Number(row.costUsd)
  return isFinite(amount) ? Math.max(0, amount) : null
}

// Change against the equal window just before, in whole percent. Null when either side is missing
// or the earlier window was empty, where a ratio means nothing.
function costDelta(current, previous) {
  if (current === null || current === undefined || previous === null || previous === undefined) return null
  var now = Number(current)
  var before = Number(previous)
  if (!isFinite(now) || !isFinite(before) || now < 0 || before <= 0) return null
  var percent = Math.round((now / before - 1) * 100)
  return { percent: percent, direction: percent > 0 ? 1 : (percent < 0 ? -1 : 0) }
}

function costDeltaText(delta, days) {
  if (!delta) return ""
  var span = costPeriodPhrase(days)
  if (delta.direction === 0) return "Same as previous " + span
  return (delta.direction > 0 ? "▲ " : "▼ ") + costCount(Math.abs(delta.percent)) + "% vs previous " + span
}

// Breakdown dimensions the payload can fill: models always, projects and agents when present.
function costBreakdownModes(payload) {
  var modes = [{ value: "model", label: "Model" }]
  if (payload && listOrEmpty(payload.projects).length > 0) modes.push({ value: "project", label: "Project" })
  if (payload && listOrEmpty(payload.agents).length > 0) modes.push({ value: "agent", label: "Agent" })
  return modes
}

// The pricing note a model row has always carried.
function costModelNote(row) {
  if (!row) return ""
  if (row.costUsd === null || row.costUsd === undefined) return "pricing unavailable"
  if (Number(row.customPricedRecords || 0) > 0) return "custom prices"
  if (Number(row.basePricedRecords || 0) > 0) return "base rates"
  if (row.costSource === "providerReported") return "reported cost"
  return ""
}

// Rows for the breakdown in one dimension, largest first for the metric (unpriced rows last, the
// folded "Other" project always last), each with a unique key and its share of the largest row.
function costBreakdownRows(payload, mode, metric) {
  var source = mode === "project" ? listOrEmpty(payload && payload.projects)
    : mode === "agent" ? listOrEmpty(payload && payload.agents) : listOrEmpty(payload && payload.models)
  var rows = []
  var seen = {}
  for (var i = 0; i < source.length; i++) {
    var item = source[i]
    if (!item || typeof item !== "object") continue
    var row = { key: "", name: "", context: "", provider: "", value: costMetricValue(item, metric),
      tokens: Math.max(0, Number(item.totalTokens) || 0), last: false, fraction: 0 }
    if (mode === "project") {
      row.last = String(item.id) === "other"
      row.key = "p:" + String(item.id || item.name || i)
      row.name = row.last ? "Other" : String(item.name || "Unknown folder")
      row.context = costRequestsText(item.records)
    } else if (mode === "agent") {
      var label = Object.prototype.hasOwnProperty.call(COST_AGENT_LABELS, String(item.id))
        ? COST_AGENT_LABELS[String(item.id)] : null
      row.key = "a:" + String(item.id || i)
      row.name = label ? label.name : String(item.id || "Agent")
      row.context = label ? label.context : costRequestsText(item.records)
    } else {
      var note = costModelNote(item)
      var known = localProvider(item.provider)
      row.key = "m:" + String(item.provider || "") + "/" + String(item.model || "")
      row.name = String(item.model || "Unknown model")
      row.provider = String(item.provider || "")
      row.context = (known ? known.short : String(item.providerName || item.provider || "")) + (note ? " · " + note : "")
    }
    if (seen[row.key]) row.key += "#" + i
    seen[row.key] = true
    rows.push(row)
  }
  rows.sort(function(left, right) {
    if (left.last !== right.last) return left.last ? 1 : -1
    var a = left.value === null ? -1 : left.value
    var b = right.value === null ? -1 : right.value
    if (a !== b) return b - a
    if (left.tokens !== right.tokens) return right.tokens - left.tokens
    return left.name < right.name ? -1 : (left.name > right.name ? 1 : 0)
  })
  var peak = 0
  for (var j = 0; j < rows.length; j++) if (rows[j].value !== null) peak = Math.max(peak, rows[j].value)
  for (var k = 0; k < rows.length; k++)
    rows[k].fraction = peak > 0 && rows[k].value !== null ? rows[k].value / peak : 0
  return rows
}

// The "When" grid: 7 local days x 24 hours from the payload's `heatmap`, oldest day first. Cells keep
// their cost (null = only unpriced use) and requests; `level` (0-1, square-root scale so one busy hour
// does not wash out the rest) follows cost, or requests for the Tokens metric, which the grid lacks.
// Null when the payload has no well-formed grid.
function costHeatmapGrid(heatmap, metric) {
  if (!heatmap || typeof heatmap !== "object") return null
  var days = listOrEmpty(heatmap.days)
  var costs = listOrEmpty(heatmap.cost)
  var records = listOrEmpty(heatmap.records)
  if (days.length !== 7 || costs.length !== 7 || records.length !== 7) return null
  var cells = []
  var dayNames = []
  var peak = 0
  var busiest = -1
  for (var d = 0; d < 7; d++) {
    var costRow = listOrEmpty(costs[d])
    var recordRow = listOrEmpty(records[d])
    if (costRow.length !== 24 || recordRow.length !== 24) return null
    dayNames.push(costDayName(costBucketDate(days[d])))
    for (var h = 0; h < 24; h++) {
      var raw = costRow[h]
      var amount = raw === null || raw === undefined || !isFinite(Number(raw)) ? null : Math.max(0, Number(raw))
      var count = Math.max(0, Math.round(Number(recordRow[h]) || 0))
      var weight = metric === "tokens" ? count : (amount === null ? 0 : amount)
      cells.push({ day: d, hour: h, dayName: dayNames[d], cost: amount, records: count, weight: weight,
        unpriced: amount === null && count > 0, level: 0 })
      if (weight > peak) {
        peak = weight
        busiest = cells.length - 1
      }
    }
  }
  for (var i = 0; i < cells.length; i++)
    cells[i].level = peak > 0 && cells[i].weight > 0 ? Math.sqrt(cells[i].weight / peak) : 0
  return { cells: cells, dayNames: dayNames, busiest: busiest }
}

// "Tue 15:00 · $4.20 · 63 requests"; `hourLabel` comes formatted in the user's clock format.
function costHeatmapText(cell, hourLabel) {
  if (!cell) return ""
  var when = cell.dayName + " " + hourLabel
  if (cell.records === 0 && !(cell.cost > 0)) return when + " · no requests"
  return when + " · " + (cell.cost === null ? "not priced" : formatUsd(cell.cost)) + " · " + costRequestsText(cell.records)
}

// "92% read from cache · saved $3,412.00": the share of input tokens served from cache, from the
// totals any source reports, also split as `percent` and `label` for the panel's value column.
// Null without cached input.
function costCacheSummary(totals) {
  if (!totals) return null
  var cached = Number(totals.cachedInputTokens)
  if (!isFinite(cached) || cached <= 0) return null
  var input = cached + Math.max(0, Number(totals.uncachedInputTokens) || 0)
    + Math.max(0, Number(totals.cacheCreationTokens) || 0)
  var share = Math.min(1, cached / input)
  var percent = Math.round(share * 100)
  if (percent >= 100 && share < 1) percent = 99
  var label = "read from cache"
  var saved = Number(totals.cacheSavingsUsd)
  if (totals.cacheSavingsUsd !== null && totals.cacheSavingsUsd !== undefined && isFinite(saved) && saved > 0)
    label += " · saved " + formatUsd(saved)
  return { share: share, percent: percent + "%", label: label, text: percent + "% " + label }
}

// Whether the cost scan read the omp sessions on this computer. Live requests come only from those
// sessions (omp-live.py --local), so only then do the ones after the scan add to its totals; omp stats
// on another computer is never live here.
function costScanHasOmp(sources) {
  var list = listOrEmpty(sources)
  for (var i = 0; i < list.length; i++) {
    var source = list[i]
    if (source && (source.id === "local-omp" || source.provider === "omp") && source.included === true) return true
  }
  return false
}

// Footer line naming where the totals come from: "Local transcripts + omp on devbox · live", or "omp
// through a tunnel" when the server is reached through this computer.
function costSourceSummary(sources, live) {
  var list = listOrEmpty(sources)
  var local = false
  var servers = []
  var omp = ""
  for (var i = 0; i < list.length; i++) {
    var source = list[i]
    if (!source || typeof source !== "object") continue
    if (source.id === "omp-remote") {
      var place = ompPlace(source.host) || " on another computer"
      if (source.status === "ok") omp = "omp" + place
      else if (source.status === "error") omp = "omp" + place + " unavailable"
      continue
    }
    if (source.included !== true) continue
    if (source.kind === "local") local = true
    else if (source.kind === "t3") {
      var name = String(source.name || "").split(" · ")[0]
      if (name !== "" && servers.indexOf(name) < 0) servers.push(name)
    }
  }
  var parts = []
  if (local) parts.push("Local transcripts")
  for (var j = 0; j < servers.length; j++) parts.push("T3 on " + servers[j])
  if (omp !== "") parts.push(omp)
  if (parts.length > 3) parts = [parts[0], (parts.length - 1) + " more sources"]
  var text = parts.join(" + ")
  return text !== "" && live ? text + " · live" : text
}

// What the live omp requests after the scan add to it: cost and tokens per provider, the request count
// and the newest time. `log` is OmpActivity's request log ([at, provider, costUsd | null, tokens,
// source] per request); `scanSeconds` is the scan's `generatedAt`, the moment it started, so a request
// that arrived while the scan ran still counts until the next scan. Only requests from this computer's
// sessions count, and only for providers the scan charts, so live growth never shows spend the next
// scan will not.
function costLiveTotals(log, scanSeconds, providerIds) {
  var result = { cost: {}, tokens: {}, requests: 0, lastAt: 0 }
  var since = finiteOrNull(scanSeconds)
  if (since === null) return result
  var list = listOrEmpty(log)
  for (var i = 0; i < list.length; i++) {
    var entry = list[i]
    if (!entry || !(entry[0] > since) || entry[4] === "remote" || !contains(providerIds, entry[1])) continue
    var provider = entry[1]
    if (entry[2] !== null && entry[2] > 0) result.cost[provider] = (result.cost[provider] || 0) + entry[2]
    if (entry[3] > 0) result.tokens[provider] = (result.tokens[provider] || 0) + entry[3]
    result.requests++
    result.lastAt = Math.max(result.lastAt, entry[0])
  }
  return result
}

// Brings a keyed list to `keys` order with moves and inserts only, so the delegates of kept keys
// survive (object constancy in the cost chart, rows sliding to their new place in lists). `list`
// adapts a ListModel: count(), keyAt(index), move(from, to), insert(index, key). Entries `keys` no
// longer names end up after keys.length, in their previous relative order, for the caller to drop.
function syncKeyedOrder(list, keys) {
  keys = listOrEmpty(keys).map(String)
  for (var target = 0; target < keys.length; target++) {
    var found = -1
    for (var i = target; i < list.count(); i++) {
      if (String(list.keyAt(i)) === keys[target]) {
        found = i
        break
      }
    }
    if (found === target) continue
    if (found > target) list.move(found, target)
    else list.insert(target, keys[target])
  }
}

// ---- 1.9 QmlSettings ----
// omp (Oh My Pi) as a source of limits, costs and live activity: the flags each backend gets, what
// Settings says about omp, the Test results, and the lines of omp's live feed (scripts/omp-live.py).
// Then the per-provider account mode that Providers → Customize sets.

// Quotatank ids of the subscriptions omp signs in to (OMP_PROVIDERS in scripts/model_usage_common.py).
var OMP_PROVIDER_IDS = ["claude", "codex", "kimi", "opencode", "antigravity", "copilot", "cursor", "zai", "minimax"]
var OMP_STATS_PORT = 3847
var OMP_GATEWAY_PORT = 4000
var OMP_RECENT_SECONDS = 3600       // an account counts as recently used this long after a request
var OMP_RECENT_LIMIT = 256          // accounts kept in recentByAccount
var OMP_LOG_SECONDS = 6 * 3600      // live requests kept for the cost scans that do not hold them yet
var OMP_LOG_LIMIT = 4096            // entries in the live request log
var OMP_LINE_LIMIT = 65536          // characters in one live line
var OMP_URL_PROBLEM = "Enter an HTTP or HTTPS address with a host name and, if needed, a port: no path, user name, query, or fragment."
var OMP_HTTP_PROBLEM = "Use HTTPS, or plain HTTP only to this computer, a private network, or Tailscale."
// The gateway's token can spend model quota, so it never goes over plain HTTP outside this computer and
// Tailscale (the backend checks where a name leads before it sends anything).
var OMP_GATEWAY_HTTP_PROBLEM = "Use HTTPS, or plain HTTP only to this computer or over Tailscale (a 100.x.y.z address or the computer's Tailscale name)."

// The omp settings with their defaults. `local` reads omp on this computer unless turned off.
function ompSettings(settings) {
  var source = settings && typeof settings === "object" ? settings : {}
  function text(key) {
    var value = source[key]
    return value === undefined || value === null ? "" : String(value).trim()
  }
  return { local: source.ompLocal !== false, gatewayUrl: text("ompGatewayUrl"),
    gatewayKeyFile: text("ompGatewayKeyFile"), statsUrl: text("ompStatsUrl") }
}

// usage-fetch.py flags: omp on this computer (the backend reports when omp is missing), and omp's
// auth gateway once both its URL and its token are saved, since the gateway answers nothing without
// the token. The caller leaves them out for a proxy source.
function ompUsageArguments(settings) {
  var omp = ompSettings(settings)
  var args = []
  if (omp.local) args.push("--omp", "local")
  if (omp.gatewayUrl !== "" && omp.gatewayKeyFile !== "")
    args.push("--omp-gateway-url", omp.gatewayUrl, "--omp-gateway-key-file", omp.gatewayKeyFile)
  return args
}

// cost-fetch.py flags: omp stats on another computer.
function ompCostArguments(settings) {
  var url = ompSettings(settings).statsUrl
  return url === "" ? [] : ["--omp-stats-url", url]
}

// Whether omp is on this computer, from the usage backend's `omp` status: true, false, or null while
// nothing says. omp that is installed but not set up ("unused") is found, though there is nothing to read.
function ompFound(status) {
  if (!status || typeof status !== "object") return null
  if (status.installed === true || status.local === "ok" || status.local === "error" || status.local === "unused") return true
  if (status.installed === false || status.local === "missing") return false
  return null
}

// omp-live.py flags, or [] while there is nothing to follow: omp's sessions here once omp is found and
// set up (with --accounts, the map that names the account behind each request), and omp stats
// elsewhere. Nothing through a proxy: its accounts are the proxy's, and omp is not read then.
function ompLiveArguments(settings, status, proxyMode) {
  if (proxyMode === true) return []
  var omp = ompSettings(settings)
  var args = []
  if (omp.local && ompFound(status) === true && status.local !== "unused") args.push("--local", "--accounts")
  if (omp.statsUrl !== "") args.push("--stats-url", omp.statsUrl)
  return args
}

// "host", "host:port" or "[v6]:port" → { host (lower case, no brackets), port }, or null.
function ompSplitHost(text) {
  var host = String(text || "")
  var port = ""
  if (host.charAt(0) === "[") {
    var end = host.indexOf("]")
    if (end < 0) return null
    var rest = host.slice(end + 1)
    host = host.slice(1, end)
    if (rest !== "" && rest.charAt(0) !== ":") return null
    port = rest.slice(1)
    if (!/^[0-9a-f:.]+$/i.test(host)) return null
  } else {
    var colon = host.indexOf(":")
    if (colon >= 0) {
      port = host.slice(colon + 1)
      host = host.slice(0, colon)
    }
  }
  if (host === "" || (port !== "" && (!/^[0-9]{1,5}$/.test(port) || Number(port) > 65535))) return null
  return { host: host.toLowerCase(), port: port }
}

function ompLoopbackHost(host) {
  return host === "localhost" || host === "::1" || /^127\.[0-9]+\.[0-9]+\.[0-9]+$/.test(host)
}

// Plain HTTP stays on networks the user controls (plain_http_allowed in model_usage_common.py):
// loopback, private LANs, Tailscale addresses, MagicDNS names and single-label names.
function ompPlainHttpHost(host) {
  var octet = "(0|[1-9][0-9]{0,2})"
  var v4 = new RegExp("^" + octet + "\\." + octet + "\\." + octet + "\\." + octet + "$").exec(host)
  if (v4) {
    for (var i = 1; i <= 4; i++) if (Number(v4[i]) > 255) return false
    var a = Number(v4[1])
    var b = Number(v4[2])
    return a === 127 || a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
      || (a === 100 && b >= 64 && b <= 127)
  }
  if (host.indexOf(":") >= 0) return host === "::1" || /^(?:0{1,4}:){7}0{0,3}1$/.test(host) || /^f[cd][0-9a-f]{0,2}:/.test(host)
  return /^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(host)
    || /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+ts\.net$/.test(host)
}

// The gateway's plain-HTTP hosts: this computer, Tailscale addresses (100.64.0.0/10, fd7a:115c:a1e0::/48),
// and names that may lead there (single-label and MagicDNS names); the backend resolves a name and
// refuses it unless every address is on Tailscale.
function ompTailscaleHost(host) {
  if (ompLoopbackHost(host)) return true
  var v4 = /^(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})$/.exec(host)
  if (v4) return Number(v4[1]) === 100 && Number(v4[2]) >= 64 && Number(v4[2]) <= 127 && Number(v4[3]) <= 255 && Number(v4[4]) <= 255
  if (host.indexOf(":") >= 0) return /^fd7a:115c:a1e0(?::|$)/.test(host)
  return /^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(host)
    || /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+ts\.net$/.test(host)
}

// What is wrong with an omp server address, or "" when the backends take it (normalize_server_url
// in scripts/model_usage_common.py): a scheme, a host and an optional port, nothing after them but one
// "/"; HTTPS anywhere, plain HTTP only to this computer, a private network or Tailscale. With `gateway`
// (the token it sends can spend model quota) plain HTTP stays on this computer and Tailscale. Empty turns
// the server off.
function ompServerUrlProblem(text, gateway) {
  var value = String(text === undefined || text === null ? "" : text).trim()
  if (value === "") return ""
  var match = /^(https?):\/\/([^\s\/?#@\\]+)\/?$/i.exec(value)
  if (!match || /[\x00-\x1f\x7f]/.test(value)) return OMP_URL_PROBLEM
  var address = ompSplitHost(match[2])
  if (!address) return OMP_URL_PROBLEM
  if (match[1].toLowerCase() === "https") return ""
  if (gateway === true) return ompTailscaleHost(address.host) ? "" : OMP_GATEWAY_HTTP_PROBLEM
  return ompPlainHttpHost(address.host) ? "" : OMP_HTTP_PROBLEM
}

// The computer an omp server address names, for "omp stats on devbox": MagicDNS names drop the
// tailnet ("devbox.tail1234.ts.net" → "devbox"); "" when the address has no host.
function ompHost(url) {
  var match = /^https?:\/\/([^\s\/?#@]+)/i.exec(String(url || "").trim())
  var address = match ? ompSplitHost(match[1]) : null
  if (!address) return ""
  var tailnet = /^([a-z0-9-]+)\.[a-z0-9-]+\.ts\.net$/.exec(address.host)
  return tailnet ? tailnet[1] : address.host
}

// " on devbox" for a remote address; "" for this computer (an SSH tunnel's end) or no address.
function ompOnHost(url) {
  var host = ompHost(url)
  return host === "" || ompLoopbackHost(host) ? "" : " on " + host
}

// Where an omp server is, for the footer and the summaries: " on devbox", " through a tunnel" for an
// address on this computer (the near end of an SSH tunnel, never "127.0.0.1"), "" without an address.
// `address` is a URL, or a host with an optional port as cost-fetch.py reports it.
function ompPlace(address) {
  var text = String(address || "").trim()
  var url = /^https?:\/\//i.test(text) ? text : "http://" + text
  return ompOnHost(url) || (ompHost(url) !== "" ? " through a tunnel" : "")
}

// A section summary's name for an omp server: its host, "SSH tunnel" for this computer, "Set" without one.
function ompSummaryName(url) {
  var host = ompHost(url)
  return host === "" ? "Set" : ompLoopbackHost(host) ? "SSH tunnel" : host
}

function ompShortVersion(version) {
  var match = /([0-9]+)\.([0-9]+)/.exec(String(version || ""))
  return match ? match[1] + "." + match[2] : ""
}

// "1 account", "18,811 requests".
function ompCount(count, one, many) {
  var value = Math.max(0, Math.round(Number(count) || 0))
  return costCount(value) + " " + (value === 1 ? one : many)
}

function ompLine(tone, text) {
  return { tone: tone, text: text }
}

// Settings → Providers → omp: what the last refresh found on this computer, as { text, tone } with
// tone "ok", "off", "error" or "pending"; text "" while there is nothing to say.
function ompLocalStatus(status, localOn, loading) {
  var found = ompFound(status)
  if (!localOn)
    return ompLine("off", found === true ? "omp found · its accounts are not read" : "Reading omp's accounts is off")
  if (!status || typeof status !== "object" || status.local === undefined || status.local === "off")
    return ompLine("pending", loading ? "Looking for omp on this computer…" : "")
  if (status.local === "missing") return ompLine("off", "omp not found on this computer")
  if (status.local === "unused") return ompLine("off", "omp is installed but not signed in to anything yet")
  var version = ompShortVersion(status.version)
  var name = "omp " + (version !== "" ? version + " " : "") + "found"
  if (status.local === "error") return ompLine("error", name + " · its accounts could not be read")
  var count = typeof status.localAccounts === "number" ? status.localAccounts
    : (typeof status.accounts === "number" && (status.gateway === undefined || status.gateway === "off") ? status.accounts : null)
  if (count === null) return ompLine("ok", name)
  return ompLine("ok", name + " · " + (count === 0 ? "no accounts signed in" : ompCount(count, "account", "accounts")))
}

// The local part of omp's status message (the backend puts the local part first, then the gateway's).
function ompLocalMessage(status) {
  var sentences = String(status && status.message || "").split(/\.\s+/)
  var kept = []
  for (var i = 0; i < sentences.length; i++)
    if (sentences[i] !== "" && !/gateway/.test(sentences[i])) kept.push(sentences[i].replace(/\.$/, ""))
  return kept.length ? kept.join(". ") + "." : ""
}

// A gateway failure, from the backend's message, with what to do next: { summary, text }. The summary
// stays short; it follows the host in the section's title.
function ompGatewayProblem(message, url) {
  var text = String(message || "")
  var on = ompOnHost(url)
  var host = ompHost(url)
  if (/refused the token/.test(text))
    return { summary: "token refused", text: "The gateway refused the token. Copy a fresh one with omp auth-gateway token" + on + ", then save it here." }
  if (/asks for a token/.test(text))
    return { summary: "token needed", text: "The gateway asks for a token. Save the one omp auth-gateway token prints" + on + "." }
  if (/Could not reach the omp gateway/.test(text))
    return { summary: "not answering", text: "Nothing answers there. Is omp auth-gateway serve running" + (on || " on the other computer") + "?" }
  if (/gateway did not answer in time/.test(text))
    return { summary: "not answering", text: "The gateway did not answer in time. Check that " + (host !== "" && !ompLoopbackHost(host) ? host : "the other computer") + " is awake and on the network." }
  if (/rate limiting/.test(text))
    return { summary: "rate limited", text: "The gateway is rate limiting usage checks. Try again in a minute." }
  var http = /gateway answered HTTP ([0-9]{3})/.exec(text)
  if (http)
    return { summary: "HTTP " + http[1], text: "The gateway answered HTTP " + http[1] + ". Check that the URL points at omp auth-gateway (port " + OMP_GATEWAY_PORT + " unless you chose another)." }
  if (/unreadable usage data/.test(text))
    return { summary: "not a gateway", text: "That address did not answer like omp's auth gateway. Check the URL, and update omp there if it is older." }
  if (/plain HTTP only to this computer or over Tailscale/.test(text))
    return { summary: "needs HTTPS or Tailscale", text: "The token goes over plain HTTP only to this computer or over Tailscale. Use an https:// address, or check that Tailscale is connected on both computers and that the address is that computer's Tailscale name or address." }
  var sentences = text.split(/\.\s+/)
  var kept = []
  for (var i = 0; i < sentences.length; i++)
    if (/gateway/.test(sentences[i])) kept.push(sentences[i].replace(/\.$/, ""))
  return { summary: "not read", text: kept.length ? kept.join(". ") + "." : "The gateway could not be read." }
}

// The title summary of "omp on another computer (limits)".
function ompGatewaySummary(settings, status) {
  var omp = ompSettings(settings)
  if (omp.gatewayUrl === "") return "Not set up"
  var host = ompSummaryName(omp.gatewayUrl)
  if (omp.gatewayKeyFile === "") return host + " · token needed"
  if (!status || typeof status !== "object" || status.gateway === undefined || status.gateway === "off") return host
  if (status.gateway === "error") return host + " · " + ompGatewayProblem(status.message, omp.gatewayUrl).summary
  return host + (typeof status.gatewayAccounts === "number" ? " · " + ompCount(status.gatewayAccounts, "account", "accounts") : " · answers")
}

// The omp accounts a provider reading holds: entries whose kind (`origin`, or `origins` once merged
// with a native entry) is omp, or the provider itself when omp is all it has.
function ompFromOmp(entry) {
  return !!entry && (entry.origin === "omp" || contains(entry.origins, "omp"))
}

function ompAccountCount(provider) {
  if (!provider || typeof provider !== "object") return 0
  var accounts = listOrEmpty(provider.accounts)
  var count = 0
  for (var i = 0; i < accounts.length; i++) if (ompFromOmp(accounts[i])) count++
  return count === 0 && accounts.length === 0 && ompFromOmp(provider) ? 1 : count
}

// A Test that did not get an answer: { probeError: "timeout" | "tooLarge" }, or nothing at all.
function ompProbeLines(reply, seconds) {
  if (reply && reply.probeError === "timeout")
    return [ompLine("error", "No answer within " + seconds + " s. Check the URL, and that the other computer is awake.")]
  if (reply && reply.probeError === "tooLarge") return [ompLine("error", "The answer was too large to read.")]
  if (!reply || reply.schemaVersion !== 1)
    return [ompLine("error", "The test did not run. Check that Python 3 is installed, then try again.")]
  if (reply.backendError) return [ompLine("error", String(reply.backendError).slice(0, 300))]
  return null
}

// Settings → Providers → omp on another computer → Test, from usage-fetch.py --omp-only run with the
// gateway's flags: lines { tone: "ok" | "info" | "error", text } that name what the gateway has.
function ompGatewayTestLines(reply, url, monitored) {
  var failed = ompProbeLines(reply, 40)
  if (failed) return failed
  var omp = reply.omp && typeof reply.omp === "object" ? reply.omp : {}
  if (omp.gateway === "error") return [ompLine("error", ompGatewayProblem(omp.message, url).text)]
  if (omp.gateway !== "ok")
    return [ompLine("error", "This version of the backend cannot read an omp gateway. Update Quotatank, then try again.")]
  var parts = []
  var unmonitored = []
  var total = 0
  var providers = listOrEmpty(reply.providers)
  for (var i = 0; i < providers.length; i++) {
    var count = ompAccountCount(providers[i])
    if (count === 0) continue
    var name = providerShortName(providers[i])
    total += count
    parts.push(name + " " + count)
    if (monitored && !contains(monitored, providers[i].id)) unmonitored.push(name)
  }
  if (total === 0)
    return [ompLine("ok", "Gateway answers"), ompLine("info", "omp there has no signed-in accounts with limits that Quotatank reads.")]
  var lines = [ompLine("ok", "Gateway answers · " + ompCount(total, "account", "accounts") + ": " + parts.join(", "))]
  if (unmonitored.length > 0)
    lines.push(ompLine("info", "Not monitored here: " + joinNames(unmonitored) + ". Monitor " + (unmonitored.length === 1 ? "it" : "them")
      + " to see " + (unmonitored.length === 1 ? "its" : "their") + " accounts in Limits."))
  return lines
}

// An omp stats failure from cost-fetch.py's omp-remote source, with what to do next.
function ompStatsProblem(source, url) {
  var message = String(source && source.message || "")
  var kind = String(source && source.errorKind || "")
  var on = ompOnHost(url)
  if (kind === "network")
    return on !== "" ? "Nothing answers there. Is omp stats running" + on + "?"
      : "Nothing answers there. Is the SSH tunnel open, and omp stats running on the other computer?"
  if (kind === "http") return (message || "omp stats returned an error.") + " Check that the URL is the dashboard's address, without a path."
  return message || "omp stats could not be read."
}

// Settings → Costs → omp on another computer → Test, from cost-fetch.py --providers "" --days 7 run
// with only the omp stats flag: what the server reported for the last 7 days.
function ompStatsTestLines(reply, url) {
  var failed = ompProbeLines(reply, 75)
  if (failed) return failed
  var source = readingFor(reply.sources, "omp-remote")
  if (!source)
    return [ompLine("error", "This version of the backend cannot read omp stats. Update Quotatank, then try again.")]
  var on = ompOnHost(url)
  if (source.status === "error") return [ompLine("error", ompStatsProblem(source, url))]
  if (source.status === "duplicate")
    return [ompLine("ok", "omp stats" + on + " answers"), ompLine("info", "It runs on this computer, so its sessions are already counted here.")]
  if (source.status !== "ok") return [ompLine("error", "omp stats was not read. Check the URL, then try again.")]
  var totals = reply.totals && typeof reply.totals === "object" ? reply.totals : {}
  var records = Math.max(0, Math.round(Number(totals.records) || 0))
  var cost = typeof totals.costUsd === "number" && isFinite(totals.costUsd) ? totals.costUsd : null
  var lines = [ompLine("ok", "omp stats" + on + " answers")]
  if (records === 0) lines.push(ompLine("info", "No requests in the last 7 days."))
  else lines.push(ompLine("ok", ompCount(records, "request", "requests") + " · " + (cost === null ? "unpriced" : formatUsd(cost)) + " in the last 7 days"))
  return lines
}

// The Test's line about omp's live feed for that server, from OmpActivity; null when it is not
// following that server.
function ompLiveFeedLine(state, message) {
  if (state === "live") return ompLine("ok", "Live feed on · new activity shows within 10 s")
  if (state === "connecting" || state === "reconnecting") return ompLine("info", "Live feed connecting…")
  if (state === "unavailable")
    return ompLine("error", "Live feed unavailable." + (message ? " " + String(message).slice(0, 200) : ""))
  return null
}

// The title summary of Settings → Costs → "omp on another computer".
function ompStatsSummary(settings, source, liveState) {
  var url = ompSettings(settings).statsUrl
  if (url === "") return "Not set up"
  var host = ompSummaryName(url)
  if (source && source.status === "error") return host + " · not answering"
  if (source && source.status === "duplicate") return host + " · counted here"
  return host + (liveState === "live" ? " · live" : "")
}

// "omp sessions on this computer" in Settings → Costs → Local history: what the last scan did, in a
// word or two that fit under the switches.
function ompLocalCostState(sources, localProviders) {
  if (listOrEmpty(localProviders).length === 0) return "Off"
  var list = listOrEmpty(sources)
  if (list.length === 0) return "Not yet read"
  var source = readingFor(list, "local-omp")
  if (!source) return "None found"
  var labels = { ok: "Included", partial: "Partial", missing: "None found", failed: "Unavailable",
    unavailable: "Unavailable", duplicate: "Included" }
  return labels[source.status] || "Included"
}

// How to reach omp stats on another computer (Tailscale or an SSH tunnel): where each command runs
// ("other" or "here"), and the user units that start them at login. A unit's first line names its file;
// long lines use systemd's backslash continuation, and "$$" is systemd's literal dollar sign.
function ompStatsRecipe(via) {
  var port = String(OMP_STATS_PORT)
  function unit(name, description, execStart, restart) {
    return "# ~/.config/systemd/user/" + name + ".service\n[Unit]\nDescription=" + description
      + "\n\n[Service]\nExecStart=" + execStart + "\nRestart=" + restart + "\nRestartSec=10\n\n[Install]\nWantedBy=default.target\n"
  }
  function enable(name) {
    return "systemctl --user daemon-reload\nsystemctl --user enable --now " + name
  }
  if (via === "ssh") {
    return {
      url: "http://127.0.0.1:" + port,
      steps: [
        { where: "other", command: "omp stats --host 127.0.0.1 --port " + port },
        { where: "here", command: "ssh -N -L " + port + ":127.0.0.1:" + port + " other-computer" }
      ],
      units: [
        { where: "other", enable: enable("omp-stats"), text: unit("omp-stats", "omp stats for Quotatank",
          "/bin/sh -lc 'exec omp stats \\\n  --host 127.0.0.1 --port " + port + "'", "on-failure") },
        { where: "here", enable: enable("omp-stats-tunnel"), text: unit("omp-stats-tunnel", "SSH tunnel to omp stats for Quotatank",
          "/usr/bin/ssh -N \\\n  -o ExitOnForwardFailure=yes \\\n  -o ServerAliveInterval=30 \\\n  -L " + port + ":127.0.0.1:" + port + " other-computer", "always") }
      ]
    }
  }
  return {
    url: "http://other-computer:" + port,
    steps: [{ where: "other", command: "omp stats --host \"$(tailscale ip -4)\" --port " + port }],
    units: [
      { where: "other", enable: enable("omp-stats"), text: unit("omp-stats", "omp stats for Quotatank",
        "/bin/sh -lc 'exec omp stats \\\n  --host \"$$(tailscale ip -4)\" --port " + port + "'", "on-failure") }
    ]
  }
}

// The commands that start omp's auth gateway on the other computer and print its token.
function ompGatewayRecipe() {
  // The serve line breaks before its flag with a shell continuation: it reads in two lines and pastes as one.
  return [
    { where: "other", command: "omp auth-gateway serve \\\n  --bind=\"$(tailscale ip -4):" + OMP_GATEWAY_PORT + "\"" },
    { where: "other", command: "omp auth-gateway token" }
  ]
}

function ompLiveId(value) {
  return typeof value === "string" && /^[a-z0-9][a-z0-9._-]{0,63}$/.test(value)
}

function ompOptionalNumber(value, integer) {
  if (value === null || value === undefined) return { ok: true, value: null }
  if (typeof value !== "number" || !isFinite(value) || value < 0 || (integer && Math.floor(value) !== value)) return { ok: false }
  return { ok: true, value: value }
}

// One NDJSON line from scripts/omp-live.py, checked and reduced to what the widget uses; null when it
// is not JSON or breaks the shape of its type. A type this widget does not know comes back as
// { type: "other" }, so a newer helper does not stop an older widget.
function parseOmpLiveLine(line) {
  if (typeof line !== "string" || line.length > OMP_LINE_LIMIT) return null
  var raw
  try { raw = JSON.parse(line) } catch (error) { return null }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null
  if (raw.schemaVersion !== undefined && raw.schemaVersion !== 1) return null
  if (raw.heartbeat === true) return { type: "heartbeat" }
  if (raw.type === "request") {
    var credential = ompOptionalNumber(raw.credentialId, true)
    var cost = ompOptionalNumber(raw.costUsd, false)
    var tokens = ompOptionalNumber(raw.tokens, false)
    if (!ompLiveId(raw.provider) || typeof raw.at !== "number" || !isFinite(raw.at) || raw.at <= 0
        || !credential.ok || !cost.ok || !tokens.ok) return null
    return { type: "request", source: raw.source === "remote" ? "remote" : "local", provider: raw.provider,
      model: typeof raw.model === "string" ? raw.model.slice(0, 256) : "", credentialId: credential.value,
      costUsd: cost.value, tokens: tokens.value === null ? 0 : Math.floor(tokens.value), subagent: raw.subagent === true, at: raw.at }
  }
  if (raw.type === "activity") {
    if (typeof raw.at !== "number" || !isFinite(raw.at) || raw.at <= 0) return null
    return { type: "activity", source: "remote", version: typeof raw.version === "number" && isFinite(raw.version) ? raw.version : 0, at: raw.at }
  }
  if (raw.type === "accounts") {
    if (!raw.map || typeof raw.map !== "object" || Array.isArray(raw.map)) return null
    var keys = Object.keys(raw.map)
    if (keys.length > 512) return null
    var map = {}
    for (var i = 0; i < keys.length; i++) {
      var entry = raw.map[keys[i]]
      if (!/^[0-9]{1,12}$/.test(keys[i]) || !entry || typeof entry !== "object" || !ompLiveId(entry.provider)
          || typeof entry.accountId !== "string" || !/^omp-[0-9a-f]{12}(?:-[0-9]{1,3})?$/.test(entry.accountId)) continue
      map[keys[i]] = { provider: entry.provider, accountId: entry.accountId }
    }
    return { type: "accounts", map: map }
  }
  if (raw.type === "state") {
    if (["live", "reconnecting", "unavailable"].indexOf(raw.state) < 0) return null
    return { type: "state", state: raw.state, message: typeof raw.message === "string" ? raw.message.slice(0, 256) : "" }
  }
  return { type: "other" }
}

// A request with the account that served it, when omp's credential map names its credential:
// `accountId`, and `accountKey` ("<provider>@<accountId>", the key of recentByAccount). The parsed line
// is completed in place: it belongs to the feed, and copying it for every request buys nothing.
function resolveOmpRequest(event, map) {
  if (!event || typeof event !== "object") return event
  var entry = event.credentialId !== null && event.credentialId !== undefined && map
    ? map[String(event.credentialId)] : null
  if (entry && entry.provider === event.provider) {
    event.accountId = entry.accountId
    event.accountKey = event.provider + "@" + entry.accountId
  }
  return event
}

// recentByAccount after a request: the newest request time per account (never in the future), only
// the last hour, at most OMP_RECENT_LIMIT accounts. When nothing changes (a request omp's map cannot
// name, or an older one) the same object comes back, so nothing that reads the map is evaluated again.
function noteOmpRequest(recent, event, nowSeconds) {
  var current = recent && typeof recent === "object" ? recent : {}
  var cutoff = nowSeconds - OMP_RECENT_SECONDS
  var key = event && event.accountKey ? String(event.accountKey) : ""
  var at = key !== "" ? Math.min(Number(event.at), nowSeconds) : NaN
  var update = key !== "" && at >= cutoff && !(Number(current[key]) >= at)
  var keys = Object.keys(current)
  var expired = keys.length > OMP_RECENT_LIMIT
  for (var k = 0; k < keys.length && !expired; k++) expired = !(Number(current[keys[k]]) >= cutoff)
  if (!update && !expired) return current
  var next = {}
  for (var j = 0; j < keys.length; j++) if (Number(current[keys[j]]) >= cutoff) next[keys[j]] = Number(current[keys[j]])
  if (update) next[key] = at
  var kept = Object.keys(next)
  if (kept.length > OMP_RECENT_LIMIT) {
    kept.sort(function (a, b) { return next[a] - next[b] })
    for (var i = 0; i < kept.length - OMP_RECENT_LIMIT; i++) delete next[kept[i]]
  }
  return next
}

// The live request log after a request: [at, provider, costUsd | null, tokens, source] per request,
// in arrival order, only the last OMP_LOG_SECONDS and at most OMP_LOG_LIMIT entries. The log is
// changed in place and returned; its owner counts a revision so bindings read it again (costLiveTotals).
function noteOmpLog(log, event, nowSeconds) {
  var list = log && typeof log.push === "function" ? log : []
  if (event && typeof event === "object") {
    var at = Math.min(Number(event.at), nowSeconds)
    if (isFinite(at)) list.push([at, String(event.provider || ""), typeof event.costUsd === "number" && event.costUsd > 0 ? event.costUsd : null,
      Math.max(0, Math.floor(Number(event.tokens) || 0)), event.source === "remote" ? "remote" : "local"])
  }
  var cutoff = nowSeconds - OMP_LOG_SECONDS
  var drop = 0
  while (drop < list.length && (list.length - drop > OMP_LOG_LIMIT || !(list[drop][0] >= cutoff))) drop++
  if (drop > 0) list.splice(0, drop)
  return list
}

// One omp-live.py per omp setup, shared like the proxy's live connection (see acquireLive). The
// component is created here, in the library's context, so the shared object outlives its first panel.
function acquireOmpLive(key, properties) {
  if (liveConnections[key]) return acquireLive(key, null, properties)
  return acquireLive(key, Qt.createComponent("OmpLiveConnection.qml"), properties)
}

// Per-provider account mode (`accountModes`, a JSON object of provider id → "single" | "together", as
// text or already parsed); a provider without one follows the automatic rule. The one reading of the
// setting: Settings shows what the panel applies.
function parseAccountModes(raw) {
  var parsed = raw
  if (raw === undefined || raw === null) return {}
  if (typeof raw === "string") {
    if (raw.length > 65536) return {}
    try { parsed = JSON.parse(raw) } catch (error) { return {} }
  }
  if (!parsed || typeof parsed !== "object" || isListLike(parsed)) return {}
  var result = {}
  var ids = Object.keys(parsed)
  for (var i = 0; i < ids.length; i++)
    if (/^[a-z0-9][a-z0-9_-]{0,63}$/.test(ids[i]) && (parsed[ids[i]] === "single" || parsed[ids[i]] === "together"))
      result[ids[i]] = parsed[ids[i]]
  return result
}

// `mode` "auto" follows the automatic rule again.
function setAccountMode(raw, providerId, mode) {
  var modes = parseAccountModes(raw)
  if (mode === "single" || mode === "together") modes[providerId] = mode
  else delete modes[providerId]
  return JSON.stringify(modes)
}

function accountModeLabel(mode) {
  return mode === "single" ? "One at a time" : mode === "together" ? "Together" : "Automatic"
}

// ---- 1.9 QmlLimits ----
// Several accounts per provider (Omarchy logins, extra keys, omp accounts, proxy accounts): which ones
// the chip counts, the order of the Limits rows, what each row says, where each limit is heading at the
// current pace, how long the accounts last until the binding short window resets, and the changes
// between two readings that deserve one notice.

var ACCOUNT_TOGETHER_SECONDS = 3600     // two accounts rising within this time are used together
var ACCOUNT_SPENDING_SECONDS = 900      // a reading that rose this recently means "spending now"
var ACCOUNT_LIVE_SECONDS = 120          // a live request this recent means "spending now"
var ACCOUNT_EVENT_SECONDS = 3 * 60 * 60 // a row mentions a switch or a reset for this long
var ACCOUNT_SOURCE_RANK = { omarchy: 0, signin: 0, proxy: 0, key: 1, omp: 2 }
var ACCOUNT_ERROR_TEXT = {
  expired: "sign-in expired", no_credentials: "signed out", rate_limited: "rate limited",
  timeout: "timed out", network: "offline", config: "needs setup", cli_unavailable: "CLI missing"
}

function providerAccounts(provider) {
  return listOrEmpty(provider && provider.accounts)
}

// The mode chosen in Settings for one provider (`accountModes`, read by parseAccountModes), or "" for
// automatic. Settings owns writing it; anything parseAccountModes drops counts as automatic.
function accountModeChoice(raw, providerId) {
  var modes = parseAccountModes(raw)
  var id = String(providerId)
  return Object.prototype.hasOwnProperty.call(modes, id) ? modes[id] : ""
}

// The newest live request for an account in a "<provider>@<accountId>" map (live omp requests, a
// proxy's activity). A native login that omp also reads carries omp's id for it (`ompAccountId`), and
// omp's requests name it by that id, so both keys count.
function accountLiveAt(account, recentByAccount) {
  if (!account || !recentByAccount || typeof recentByAccount !== "object") return null
  var provider = String(account.id || "")
  var at = finiteOrNull(recentByAccount[provider + "@" + String(account.accountId || "")])
  var omp = typeof account.ompAccountId === "string" ? account.ompAccountId : ""
  var also = omp !== "" ? finiteOrNull(recentByAccount[provider + "@" + omp]) : null
  return also !== null && (at === null || also > at) ? also : at
}

// Whether a live request naming `accountId` (omp's or the proxy's id) was served by this account.
function accountAnswersTo(account, accountId) {
  var id = String(accountId || "")
  return !!account && id !== "" && (String(account.accountId || "") === id
    || (typeof account.ompAccountId === "string" && account.ompAccountId === id))
}

// The latest sign of use per account ("<provider>@<accountId>" → epoch seconds), one map for every
// surface: live omp requests (`ompRecent`, OmpActivity.recentByAccount) and, through a proxy, its own
// activity: `nowSeconds` for an account with a request in flight (`inFlight`, the live connection's
// accounts), else when its last request ended (`lastUsed`, UsageActivityBackend.providers). Where
// several say something about one account, the newest wins, so a request in flight always does.
function mergeRecentActivity(ompRecent, inFlight, lastUsed, nowSeconds) {
  var result = {}
  var key
  function note(name, at) {
    var value = finiteOrNull(at)
    if (value !== null && value > 0 && !(result[name] >= value)) result[name] = value
  }
  if (ompRecent && typeof ompRecent === "object") for (key in ompRecent) note(key, ompRecent[key])
  var used = listOrEmpty(lastUsed)
  for (var i = 0; i < used.length; i++)
    if (used[i] && used[i].status === "ok" && used[i].accountId) note(String(used[i].id) + "@" + String(used[i].accountId), used[i].lastUsedAt)
  var flying = listOrEmpty(inFlight)
  for (var j = 0; j < flying.length; j++)
    if (flying[j] && Number(flying[j].inFlight) > 0 && flying[j].accountId)
      note(String(flying[j].provider) + "@" + String(flying[j].accountId), nowSeconds)
  return result
}

function accountLastRise(account) {
  return finiteOrNull(account && account.activity ? account.activity.lastIncreaseAt : null)
}

// `at` lies within `seconds` before `now`; a minute of clock skew into the future still counts.
function withinSeconds(at, now, seconds) {
  return at !== null && now !== null && now - at <= seconds && at - now <= 60
}

// An account is spending now when its reading rose in the last 15 minutes or omp sent a request for
// it in the last two.
function spendingNow(account, nowSeconds, recentByAccount) {
  var now = finiteOrNull(nowSeconds)
  if (!account || now === null) return false
  return withinSeconds(accountLastRise(account), now, ACCOUNT_SPENDING_SECONDS)
    || withinSeconds(accountLiveAt(account, recentByAccount), now, ACCOUNT_LIVE_SECONDS)
}

// "single": new sessions use one account at a time (Omarchy's in-use login). "together": several
// accounts are spent at once (a proxy, omp's pool, or two accounts rising within the last hour).
// The Settings choice for the provider wins. A provider whose logins Omarchy switches between
// (`accountSwitch`) stays one at a time: right after a switch the old account still rises from the
// sessions left running on it, yet new sessions use only the new one.
function accountMode(provider, modesRaw, proxyMode, nowSeconds, recentByAccount) {
  var chosen = accountModeChoice(modesRaw, provider ? provider.id : "")
  if (chosen !== "") return chosen
  if (proxyMode) return "together"
  if (provider && provider.pool && typeof provider.pool === "object") return "together"
  if (provider && provider.accountSwitch && typeof provider.accountSwitch === "object") return "single"
  var now = finiteOrNull(nowSeconds)
  var accounts = providerAccounts(provider)
  var recent = 0
  for (var i = 0; i < accounts.length; i++) {
    if (withinSeconds(accountLastRise(accounts[i]), now, ACCOUNT_TOGETHER_SECONDS)
        || withinSeconds(accountLiveAt(accounts[i], recentByAccount), now, ACCOUNT_TOGETHER_SECONDS)) recent++
  }
  return recent >= 2 ? "together" : "single"
}

// The account the provider-level fields were read from: the active login or key, else the entry with
// the provider's accountId (a proxy's summary), else the first. -1 without accounts.
function summaryAccountIndex(provider) {
  var accounts = providerAccounts(provider)
  for (var i = 0; i < accounts.length; i++)
    if (accounts[i] && accounts[i].active === true) return i
  var id = provider ? provider.accountId : undefined
  if (id !== undefined && id !== null && id !== "")
    for (var j = 0; j < accounts.length; j++)
      if (accounts[j] && accounts[j].accountId === id) return j
  return accounts.length > 0 ? 0 : -1
}

// Of `indexes` (every account when null), the one closest to a limit that still has room. When none
// has room, the first used-up one; -1 when no account reports usage. A used-up account is skipped
// while another has room: together, new sessions spend from the ones that still can.
function leastHeadroomIndex(accounts, indexes) {
  var list = listOrEmpty(accounts)
  var all = indexes === null || indexes === undefined
  var count = all ? list.length : listOrEmpty(indexes).length
  var best = -1
  var low = Infinity
  var empty = -1
  for (var k = 0; k < count; k++) {
    var i = all ? k : indexes[k]
    var headroom = minRemaining(list[i])
    if (headroom === null) continue
    if (headroom <= 0) {
      if (empty < 0) empty = i
      continue
    }
    if (headroom < low) {
      low = headroom
      best = i
    }
  }
  return best >= 0 ? best : empty
}

// Indexes (ascending) of the accounts the chip counts. One at a time: the in-use account, else the
// summary's. Together: every account spending now, else the one with the least headroom.
function countedAccounts(provider, mode, nowSeconds, recentByAccount) {
  var accounts = providerAccounts(provider)
  if (accounts.length === 0) return []
  if (mode !== "together") return [summaryAccountIndex(provider)]
  var spending = []
  for (var i = 0; i < accounts.length; i++)
    if (spendingNow(accounts[i], nowSeconds, recentByAccount)) spending.push(i)
  if (spending.length > 0) return spending
  var least = leastHeadroomIndex(accounts, null)
  return [least >= 0 ? least : summaryAccountIndex(provider)]
}

// Where an account's reading comes from (its `origin`): "omarchy" (a login in Omarchy's registry),
// "signin" (the one native sign-in next to omp accounts), "key", "omp", or "proxy". Readings from a
// backend without `origin` are told apart by their ids. `source` is the API's description, not a kind.
// The one rule for every surface: rows, dots, hints and notices.
function accountSourceKind(account, proxyMode) {
  if (!account) return ""
  var origin = String(account.origin || "")
  if (origin === "omarchy" || origin === "signin" || origin === "key" || origin === "omp" || origin === "proxy") return origin
  if (proxyMode || account.proxyImplementation) return "proxy"
  var id = String(account.accountId || "")
  if (id === "primary" || /^k-[0-9a-f]{8}$/.test(id)) return "key"
  if (/^omp-/.test(id)) return "omp"
  return "omarchy"
}

function accountSourceLabel(kind) {
  if (kind === "omp") return "omp"
  if (kind === "key") return "key"
  if (kind === "omarchy") return "Omarchy"
  if (kind === "signin") return "sign-in"
  if (kind === "proxy") return "proxy"
  return ""
}

// Row order as account indexes. One at a time keeps the stable order (Omarchy's registry order, then
// keys, then omp). Together puts the account with the least headroom first; accounts without a reading
// go last. Ties keep the stable order, so rows only move when headroom really changes places.
function accountOrder(accounts, mode, proxyMode) {
  var list = listOrEmpty(accounts)
  var rows = []
  for (var i = 0; i < list.length; i++) {
    var headroom = minRemaining(list[i])
    var rank = ACCOUNT_SOURCE_RANK[accountSourceKind(list[i], proxyMode)]
    rows.push({ index: i, rank: rank === undefined ? 0 : rank, headroom: headroom === null ? Infinity : headroom })
  }
  rows.sort(function (a, b) {
    if (mode === "together" && a.headroom !== b.headroom) return a.headroom < b.headroom ? -1 : 1
    if (a.rank !== b.rank) return a.rank - b.rank
    return a.index - b.index
  })
  return rows.map(function (row) { return row.index })
}

// The two limits an account row shows: its short window (the 5-hour session, else the shortest of a
// day or less) and its main long window (the overall weekly, else another weekly, else monthly).
// Windows that report no usage are skipped; either side may be null.
function accountMeterRows(account) {
  var rows = listOrEmpty(account && account.windows)
  var short = null
  for (var i = 0; i < rows.length && short === null; i++)
    if (windowUsed(rows[i]) !== null && windowMatches(rows[i], "session")) short = rows[i]
  for (var j = 0; j < rows.length && short === null; j++) {
    var seconds = finiteOrNull(rows[j] && rows[j].windowSeconds)
    if (windowUsed(rows[j]) === null || seconds === null || seconds <= 0 || seconds > 86400) continue
    if (short === null || seconds < Number(short.windowSeconds)) short = rows[j]
  }
  var long = null
  var candidates = accountWindows(account, false)
  for (var k = 0; k < candidates.length && long === null; k++) {
    var row = candidates[k]
    var span = finiteOrNull(row && row.windowSeconds)
    if (row !== short && windowUsed(row) !== null && (span === null || span > 86400)) long = row
  }
  return { short: short, long: long }
}

// A whole percent for the compact account meters, on the side shown (`used` is % used): a window with
// some room left never reads as used up (100% used, 0% left) through rounding.
function compactPercent(used, mode) {
  var value = finiteOrNull(used)
  if (value === null) return null
  var shown = Math.round(sideOfUsed(clamp(value, 0, 100), mode))
  if (value < 100) shown = mode === "Remaining" ? Math.max(1, shown) : Math.min(99, shown)
  return shown
}

// The limit an account is blocked on and when it is usable again: of its used-up windows, the one that
// resets last ({ row, resetsAt }), since each must refill. `resetsAt` is null as soon as one used-up
// window reports no reset time: then nothing says when the account is back. Null while every window
// still has room. Rows and the hover card both read it, so they agree on "back 18:02".
function accountUsedUp(account) {
  if (!account || account.status !== "ok") return null
  var rows = listOrEmpty(account.windows)
  var found = null
  for (var i = 0; i < rows.length; i++) {
    var used = windowUsed(rows[i])
    if (used === null || used < 100) continue
    var at = finiteOrNull(rows[i].resetsAt)
    if (at === null) return { row: rows[i], resetsAt: null }
    if (!found || at > found.resetsAt) found = { row: rows[i], resetsAt: at }
  }
  return found
}

// One status line for an account row, most useful first: a failed or paused reading, a limit used up
// (with when it is back), a last-known reading, spending now (`spending`, from accountState), a recent
// switch or reset, the plan, the source. `event` is this account's newest {kind: "switch"|"reset", at},
// or null. Returns {kind, text, at, tone}; tone is "urgent", "accent" or "dim", and `at` is a time to
// append.
function accountStatusLine(account, spending, nowSeconds, event, proxyMode) {
  if (!account) return { kind: "", text: "", at: null, tone: "dim" }
  var status = String(account.status || "")
  if (status === "error") {
    var kind = String(account.errorKind || "")
    return { kind: "error", at: null, tone: "urgent",
      text: Object.prototype.hasOwnProperty.call(ACCOUNT_ERROR_TEXT, kind) ? ACCOUNT_ERROR_TEXT[kind] : "unavailable" }
  }
  if (status === "disabled") return { kind: "paused", text: "paused", at: null, tone: "dim" }
  var usedUp = accountUsedUp(account)
  if (usedUp !== null) return { kind: "usedup", text: "used up", at: usedUp.resetsAt, tone: "urgent" }
  if (account.stale === true) return { kind: "stale", text: "last known reading", at: null, tone: "dim" }
  if (spending === true) return { kind: "spending", text: "spending now", at: null, tone: "accent" }
  var now = finiteOrNull(nowSeconds)
  var eventAt = event ? finiteOrNull(event.at) : null
  if (event && (event.kind === "switch" || event.kind === "reset") && withinSeconds(eventAt, now, ACCOUNT_EVENT_SECONDS))
    return { kind: event.kind, text: event.kind === "switch" ? "switched" : "reset", at: eventAt, tone: "accent" }
  if (account.plan || account.planType) return { kind: "plan", text: accountPlanLabel(account), at: null, tone: "dim" }
  return { kind: "source", text: accountSourceLabel(accountSourceKind(account, proxyMode)), at: null, tone: "dim" }
}

// The command behind a row's Use button: Omarchy starts new sessions of the provider with that login.
// The built-in default login is named "primary", as in Omarchy's registry. Null for anything that is
// not a plain id, so nothing can be read as an option.
function accountUseArgv(providerId, account) {
  var provider = String(providerId || "")
  if (!account || !/^[a-z0-9][a-z0-9_-]{0,63}$/.test(provider)) return null
  var id = String(account.accountId || "")
  if (account.primary === true && (id === "main" || id === "primary")) id = "primary"
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(id)) return null
  return ["omarchy", "agent", "account", "use", provider, id]
}

// A row offers Use in one-at-a-time mode for an Omarchy login that is not in use and can be read.
function accountCanUse(account, mode, proxyMode) {
  return !!account && mode === "single" && account.active !== true && account.status === "ok"
    && accountSourceKind(account, proxyMode) === "omarchy"
}

// How new sessions pick among a provider's accounts, for the ACCOUNTS header and the hover card alike:
// "Used together · omp" (omp's pool, or an account omp reads), "Used together · Fusebox" (a proxy, named
// by `proxyLabel`), "Omarchy · switches at 95%" or "Omarchy · notifies at 95%"; "" otherwise.
function accountModeText(provider, mode, proxyMode, proxyLabel) {
  if (!provider) return ""
  if (mode === "together") {
    if (proxyMode) return "Used together · " + String(proxyLabel || "proxy")
    var accounts = providerAccounts(provider)
    var omp = !!provider.pool
    for (var i = 0; i < accounts.length && !omp; i++) {
      var origins = listOrEmpty(accounts[i] && accounts[i].origins)
      omp = accountSourceKind(accounts[i], false) === "omp" || contains(origins, "omp")
    }
    return "Used together" + (omp ? " · omp" : "")
  }
  var policy = provider.accountSwitch
  if (!policy || typeof policy !== "object") return ""
  var threshold = finiteOrNull(policy.threshold)
  var at = threshold === null ? "" : " at " + formatPercent(clamp(threshold, 0, 100)) + "%"
  if (policy.mode === "auto") return "Omarchy · switches" + at
  if (policy.mode === "manual") return "Omarchy · notifies" + at
  return ""
}

// An account's ring wherever it has a dot (chip, tile, hover card, row): "ok", "warning" or "critical"
// from its tightest limit, so an account blocked on a used-up weekly limit is critical whatever window a
// chip shows; "error" for a failed or paused reading, "unknown" without one.
function accountRingState(account, warningThreshold, criticalThreshold) {
  if (!account) return "unknown"
  if (account.status === "error" || account.status === "disabled") return "error"
  if (account.status !== "ok") return "unknown"
  var level = severity(account, warningThreshold, criticalThreshold)
  return level === "ok" || level === "warning" || level === "critical" ? level : "unknown"
}

// Up to `keep` of the account indexes in `order`, counted ones first so a counted account is never
// folded away, listed in `order`.
function pickAccounts(order, counted, keep) {
  var list = listOrEmpty(order)
  var chosen = []
  for (var c = 0; c < list.length && chosen.length < keep; c++)
    if (contains(counted, list[c])) chosen.push(list[c])
  for (var o = 0; o < list.length && chosen.length < keep; o++)
    if (!contains(chosen, list[o])) chosen.push(list[o])
  return Array.prototype.filter.call(list, function (index) { return contains(chosen, index) })
}

// What every surface says about a provider's accounts (DESIGN §2–3), worked out once per provider and
// clock tick so the chip, its dots and hover card, the tile, the Limits rows and the runway agree.
// `options`: modes (the accountModes setting, text or parsed), proxyMode, nowSeconds (the panel's one
// clock), recentByAccount (mergeRecentActivity), warningThreshold, criticalThreshold. Returns null
// without accounts, else:
// - mode: "single" | "together"; counted: indexes the chip counts (ascending); value: the counted
//   account with the least headroom, whose figure the tile shows;
// - spending, rings, inUse: one entry per account ("in use" only one at a time, never through a proxy);
// - order: the Limits rows' order; stable: the dots' order (Omarchy logins, keys, omp);
// - dots: { dots: [{ index, state, counted, spending }], extra }, at most four dots in stable order,
//   three and "+N" from five accounts on, counted accounts kept.
function accountState(provider, options) {
  var accounts = providerAccounts(provider)
  if (accounts.length === 0) return null
  var opts = options || {}
  var proxyMode = opts.proxyMode === true
  var mode = accountMode(provider, opts.modes, proxyMode, opts.nowSeconds, opts.recentByAccount)
  var counted = countedAccounts(provider, mode, opts.nowSeconds, opts.recentByAccount)
  var spending = []
  var rings = []
  var inUse = []
  for (var i = 0; i < accounts.length; i++) {
    spending.push(spendingNow(accounts[i], opts.nowSeconds, opts.recentByAccount))
    rings.push(accountRingState(accounts[i], opts.warningThreshold, opts.criticalThreshold))
    inUse.push(mode === "single" && !proxyMode && !!accounts[i] && accounts[i].active === true)
  }
  var stable = accountOrder(accounts, "single", proxyMode)
  var shown = stable.length <= 4 ? stable : pickAccounts(stable, counted, 3)
  var dots = []
  for (var d = 0; d < shown.length; d++) {
    var index = shown[d]
    var isCounted = contains(counted, index)
    dots.push({ index: index, state: rings[index], counted: isCounted, spending: isCounted && spending[index] })
  }
  var value = leastHeadroomIndex(accounts, counted)
  return {
    mode: mode,
    counted: counted,
    value: value >= 0 ? value : (counted.length > 0 ? counted[0] : -1),
    spending: spending,
    rings: rings,
    inUse: inUse,
    order: mode === "together" ? accountOrder(accounts, "together", proxyMode) : stable,
    stable: stable,
    dots: { dots: accounts.length > 1 ? dots : [], extra: accounts.length > 1 ? stable.length - shown.length : 0 }
  }
}

// Where a limit is heading at the current pace. `projected` is the use expected at reset (at most
// 100), `runsOutAt` when it reaches 100 before then. `rate` (percent per second) is 0 without a
// projection (idle, collecting, stale, starting). Null without a pace.
function windowForecast(row, nowSeconds) {
  var pace = paceForWindow(row, nowSeconds)
  if (!pace) return null
  var now = Number(nowSeconds)
  var resetsAt = Number(row.resetsAt)
  var rate = pace.state === "projecting" && pace.rate > 0 ? pace.rate : 0
  return {
    pace: pace,
    used: pace.used,
    rate: rate,
    resetsAt: resetsAt,
    untilReset: Math.max(0, resetsAt - now),
    projected: pace.exhausted ? 100 : rate > 0 ? Math.min(100, pace.used + rate * Math.max(0, resetsAt - now)) : null,
    runsOut: pace.runsOut === true,
    runsOutAt: pace.runsOut === true ? now + pace.etaSeconds : null
  }
}

// The dashed stretch a meter draws for the forecast, on the side the meter shows (fractions 0-1):
// past the fill under Used, the part of the fill that would be spent under Remaining. Null when there
// is no projection or it would not move the meter.
function forecastSegment(forecast, mode) {
  if (!forecast || forecast.rate <= 0 || forecast.projected === null) return null
  if (forecast.projected - forecast.used < 0.5) return null
  var from = sideOfUsed(forecast.used, mode) / 100
  var to = sideOfUsed(forecast.projected, mode) / 100
  return { from: Math.min(from, to), to: Math.max(from, to), runsOut: forecast.runsOut }
}

// The limit card's verdict beside the reset line. `clock(epochSeconds)` formats a time.
function forecastText(forecast, mode, clock) {
  if (!forecast) return { text: "", urgent: false }
  var pace = forecast.pace
  if (pace.exhausted) return { text: "used up", urgent: true }
  if (forecast.runsOut) return { text: "runs out " + clock(forecast.runsOutAt) + " · " + expectedText(pace, mode), urgent: true }
  if (pace.state === "projecting") return { text: "lasts until reset", urgent: false }
  if (pace.state === "idle") return { text: "idle " + formatDuration(pace.idleSeconds), urgent: false }
  if (pace.state === "collecting") return { text: "measuring pace", urgent: false }
  if (pace.state === "stale") return { text: "no recent data", urgent: false }
  if (pace.state === "no-usage") return { text: "not used yet", urgent: false }
  return { text: "", urgent: false }
}

// When a window's use first reached `used` in its current window, from its samples. Null when the
// samples do not show it: never reached, or already past it at the first sample of the window.
function firstCrossing(row, used) {
  var resetsAt = finiteOrNull(row && row.resetsAt)
  var seconds = finiteOrNull(row && row.windowSeconds)
  var start = resetsAt !== null && seconds !== null ? resetsAt - seconds : -Infinity
  var list = listOrEmpty(row && row.samples)
  var points = []
  for (var i = 0; i < list.length; i++) {
    var sample = list[i]
    var stamp = isListLike(sample) ? finiteOrNull(sample[0]) : null
    var value = isListLike(sample) ? finiteOrNull(sample[1]) : null
    if (stamp !== null && value !== null && stamp >= start) points.push([stamp, value])
  }
  points.sort(function (a, b) { return a[0] - b[0] })
  for (var j = 0; j < points.length; j++) {
    if (points[j][1] < used) continue
    return j === 0 && points[j][1] > used ? null : points[j][0]
  }
  return null
}

// What a point on a meter means, on the side the meter shows: at or below the fill, when use passed it
// (from the samples); above it, when this pace gets there. Returns {kind, percent, at}; kind is
// "passed", "earlier" (before the samples), "at", "after-reset" or "idle". Null without usage.
function meterScrub(row, percent, mode, nowSeconds) {
  var used = windowUsed(row)
  if (used === null) return null
  var shown = clamp(Math.round(Number(percent)), 0, 100)
  var target = sideOfUsed(shown, mode)
  if (target <= used) {
    var at = firstCrossing(row, target)
    return { kind: at === null ? "earlier" : "passed", percent: shown, at: at }
  }
  var forecast = windowForecast(row, nowSeconds)
  if (!forecast || forecast.rate <= 0) return { kind: "idle", percent: shown, at: null }
  var when = Number(nowSeconds) + (target - used) / forecast.rate
  return { kind: when > forecast.resetsAt ? "after-reset" : "at", percent: shown, at: when }
}

function scrubText(scrub, mode, clock) {
  if (!scrub) return ""
  var figure = scrub.percent + "%" + (mode === "Remaining" ? " left" : "")
  if (scrub.kind === "passed") return figure + " · passed " + clock(scrub.at)
  if (scrub.kind === "earlier") return figure + " · passed earlier"
  if (scrub.kind === "at") return figure + " · at " + clock(scrub.at) + " at this pace"
  if (scrub.kind === "after-reset") return figure + " · not before the reset at this pace"
  return figure + " · not being used now"
}

// "5-hour", "weekly", "monthly" or "daily" for a window; its label otherwise.
function windowPhrase(row) {
  var tag = rowPeriodTag(row)
  if (tag === "5h") return "5-hour"
  if (tag === "7d") return "weekly"
  if (tag === "30d") return "monthly"
  if (tag === "1d") return "daily"
  return String(row && row.label || "limit").toLowerCase()
}

// How long the accounts last until the counted account's short window resets.
// One at a time: the in-use account runs down at the current pace, then the next one (in `order`)
// takes over at that same pace, and so on. Together: every account runs down side by side at its own
// pace. Times are seconds from now, capped at the reset. A provider without accounts is its own single
// account. Null without a short window that resets in the future.
// Lane kinds: "runs" (empties before the reset), "lasts", "takesover", "notneeded", "usedup",
// "unavailable"; together, a lane not being spent is marked `idle`. `gap` is the time with nothing
// left before the reset.
function accountRunway(provider, mode, counted, nowSeconds, order) {
  var accounts = providerAccounts(provider)
  if (accounts.length === 0 && provider) accounts = [provider]
  var now = finiteOrNull(nowSeconds)
  if (accounts.length === 0 || now === null) return null
  var countedList = listOrEmpty(counted).length > 0 ? listOrEmpty(counted) : [0]
  var base = leastHeadroomIndex(accounts, countedList)
  if (base < 0) base = countedList[0]
  var baseRow = accountMeterRows(accounts[base]).short
  var resetsAt = finiteOrNull(baseRow && baseRow.resetsAt)
  if (!baseRow || resetsAt === null || resetsAt <= now) return null
  var horizon = resetsAt - now
  var sequence = []
  var source = listOrEmpty(order).length === accounts.length ? listOrEmpty(order) : accountOrder(accounts, mode, false)
  if (mode !== "together") sequence.push(base)
  for (var s = 0; s < source.length; s++)
    if (mode === "together" || source[s] !== base) sequence.push(source[s])

  function reading(index) {
    var account = accounts[index]
    var row = account && account.status === "ok" ? accountMeterRows(account).short : null
    if (!row) return null
    var forecast = windowForecast(row, now)
    return { used: windowUsed(row), rate: forecast ? forecast.rate : 0 }
  }
  var lanes = []
  var demand = 0
  var spending = false
  var end = 0
  if (mode === "together") {
    var lasting = false
    for (var t = 0; t < sequence.length; t++) {
      var own = reading(sequence[t])
      if (!own) {
        lanes.push({ index: sequence[t], kind: "unavailable", start: 0, end: 0 })
        continue
      }
      if (own.used >= 100) {
        lanes.push({ index: sequence[t], kind: "usedup", start: 0, end: 0 })
        continue
      }
      if (own.rate > 0) spending = true
      var span = own.rate > 0 ? (100 - own.used) / own.rate : Infinity
      if (span >= horizon) lasting = true
      lanes.push({ index: sequence[t], kind: span < horizon ? "runs" : "lasts", start: 0, end: Math.min(horizon, span),
        idle: own.rate <= 0 })
      end = Math.max(end, Math.min(horizon, span))
    }
    if (lasting) end = horizon
  } else {
    var first = reading(base)
    demand = first ? first.rate : 0
    spending = demand > 0
    var clockAt = 0
    for (var i = 0; i < sequence.length; i++) {
      var next = reading(sequence[i])
      if (!next) {
        lanes.push({ index: sequence[i], kind: "unavailable", start: clockAt, end: clockAt })
        continue
      }
      if (clockAt >= horizon) {
        lanes.push({ index: sequence[i], kind: "notneeded", start: horizon, end: horizon })
        continue
      }
      if (next.used >= 100) {
        lanes.push({ index: sequence[i], kind: "usedup", start: clockAt, end: clockAt })
        continue
      }
      var lasts = demand > 0 ? (100 - next.used) / demand : Infinity
      var stop = Math.min(horizon, clockAt + lasts)
      var kind = clockAt + lasts < horizon ? "runs" : clockAt > 0 ? "takesover" : "lasts"
      lanes.push({ index: sequence[i], kind: kind, start: clockAt, end: stop })
      clockAt = stop
    }
    end = clockAt
  }
  for (var l = 0; l < lanes.length; l++) {
    lanes[l].startAt = now + lanes[l].start
    lanes[l].endAt = now + lanes[l].end
  }
  var gap = lanes.some(function (lane) { return lane.kind === "runs" || lane.kind === "lasts" || lane.kind === "takesover" })
    ? Math.max(0, horizon - end) : horizon
  return {
    mode: mode === "together" ? "together" : "single",
    window: baseRow,
    windowSeconds: finiteOrNull(baseRow.windowSeconds),
    resetsAt: resetsAt,
    horizon: horizon,
    base: base,
    spending: spending,
    lanes: lanes,
    gap: gap > 0.5 ? gap : 0,
    gapStart: gap > 0.5 ? horizon - gap : horizon
  }
}

// "Pool: 1.57 of 2 accounts left this 5-hour window", from omp's capacity for the runway's window.
function poolLine(pool, row) {
  var rows = listOrEmpty(pool && pool.windows)
  var seconds = finiteOrNull(row && row.windowSeconds)
  for (var i = 0; i < rows.length; i++) {
    var entry = rows[i]
    var accounts = finiteOrNull(entry && entry.accounts)
    var left = finiteOrNull(entry && entry.remainingAccounts)
    if (seconds === null || finiteOrNull(entry && entry.windowSeconds) !== seconds) continue
    if (accounts === null || left === null || accounts <= 0) continue
    var shown = Math.round(clamp(left, 0, accounts) * 100) / 100
    return "Pool: " + shown + " of " + accounts + " account" + (accounts === 1 ? "" : "s")
      + " left this " + windowPhrase(row) + " window"
  }
  return ""
}

// Whether a window reset between two readings of it ({ used, resetsAt }, resetsAt in epoch seconds or
// null): its use fell, its old reset time was due (at most five minutes ahead of `nowSeconds`), and
// the new reset time lies past the old one, or there is none any more (an idle window whose provider
// reports no reset). A rolling window that sheds old use keeps a reset time that is not due yet, or
// never reports one, so it never counts. The one rule for Limits notices and chip flashes.
function windowWasReset(old, next, nowSeconds) {
  if (!old || !next) return false
  var before = finiteOrNull(old.used)
  var after = finiteOrNull(next.used)
  var was = finiteOrNull(old.resetsAt)
  var now = finiteOrNull(nowSeconds)
  if (before === null || after === null || was === null || now === null) return false
  if (!(after < before - 0.5) || was > now + 300) return false
  var is = finiteOrNull(next.resetsAt)
  return is === null || is > was + 60
}

// The Qt format of a clock time shown next to `nowSeconds`: the time alone today or within twelve hours,
// with the weekday within six days, with the date further out. The one rule behind every clock time the
// panel and the bar show (rows, limit cards, the runway, the hover card, notices); `timeFormat` is the
// user's clock format.
function clockPattern(epochSeconds, nowSeconds, timeFormat) {
  var format = String(timeFormat || "HH:mm")
  var at = finiteOrNull(epochSeconds)
  var now = finiteOrNull(nowSeconds)
  if (at === null || now === null) return format
  var distance = Math.abs(at - now)
  if (distance < 12 * 3600 || new Date(at * 1000).toDateString() === new Date(now * 1000).toDateString()) return format
  return (distance < 6 * 86400 ? "ddd " : "d MMM ") + format
}

// Changes between two readings worth one notice: Omarchy moving new sessions to another login, a
// limit that reset after it was nearly used up, and omp losing a sign-in it was renewing. The first
// reading of a provider only seeds `state`. Returns {state, events}; each event is
// {id, kind, provider, accountId, from, fromUsed, label, at}.
function accountEvents(previous, providers, nowSeconds, warningThreshold) {
  var state = {}
  var events = []
  var now = finiteOrNull(nowSeconds)
  var last = previous && typeof previous === "object" ? previous : {}
  var warning = clamp(warningThreshold === undefined ? 25 : warningThreshold, 0, 100)
  var list = listOrEmpty(providers)
  for (var p = 0; p < list.length; p++) {
    var provider = list[p]
    if (!provider || !provider.id) continue
    var id = String(provider.id)
    var before = last[id] || null
    var accounts = providerAccounts(provider)
    var readings = accounts.length > 0 ? accounts : [provider]
    var entry = { active: "", windows: {}, expired: {}, seen: {} }
    // Only Omarchy's registry names an account new sessions start with; a proxy's summary account
    // follows headroom and is no switch.
    var activeIndex = -1
    for (var x = 0; x < accounts.length; x++)
      if (accounts[x] && accounts[x].active === true) activeIndex = x
    var active = accounts.length > 1 && activeIndex >= 0
      && accountSourceKind(accounts[activeIndex], false) === "omarchy" ? accounts[activeIndex] : null
    entry.active = active ? String(active.accountId || "") : ""
    if (before && before.active && entry.active && before.active !== entry.active) {
      var from = null
      for (var f = 0; f < accounts.length; f++)
        if (String(accounts[f].accountId) === before.active) from = accounts[f]
      var fromLeft = from ? minRemaining(from) : null
      events.push({ id: "switch|" + id + "|" + entry.active + "|" + now, kind: "switch", provider: id,
        accountId: entry.active, from: before.active, fromUsed: fromLeft === null ? null : 100 - fromLeft,
        label: "", at: now })
    }
    for (var a = 0; a < readings.length; a++) {
      var account = readings[a]
      var accountId = accounts.length > 0 ? String(account.accountId || "") : ""
      entry.seen[accountId] = true
      if (account.status === "error" && account.errorKind === "expired" && accountSourceKind(account, false) === "omp") {
        entry.expired[accountId] = true
        if (before && before.seen && before.seen[accountId] === true && before.expired && before.expired[accountId] !== true)
          events.push({ id: "omp-expired|" + id + "|" + accountId + "|" + now, kind: "omp-expired", provider: id,
            accountId: accountId, from: "", fromUsed: null, label: "", at: now })
      }
      var rows = account.status === "ok" ? listOrEmpty(account.windows) : []
      for (var w = 0; w < rows.length; w++) {
        var row = rows[w]
        var used = windowUsed(row)
        if (!row || used === null) continue
        var key = accountId + "|" + String(row.id || row.label || w)
        var reading = { used: used, resetsAt: finiteOrNull(row.resetsAt) }
        entry.windows[key] = reading
        var old = before && before.windows ? before.windows[key] : null
        if (old && old.used >= 100 - warning && windowWasReset(old, reading, now))
          events.push({ id: "reset|" + id + "|" + key + "|" + old.resetsAt, kind: "reset", provider: id,
            accountId: accountId, from: "", fromUsed: old.used, label: String(row.label || "Usage limit"),
            at: Math.min(old.resetsAt, now) })
      }
    }
    state[id] = entry
  }
  return { state: state, events: events }
}

// The notice for one event. `names` maps accountId to the name the panel shows; `clock` formats a
// time; `manual` says the switch came from the panel's Use button.
function eventNoticeText(event, provider, names, clock, manual) {
  if (!event) return ""
  var who = function (accountId) { return names && names[accountId] ? String(names[accountId]) : "an account" }
  var service = providerShortName(provider || { id: event.provider })
  if (event.kind === "switch") {
    var policy = provider && provider.accountSwitch
    var running = " Running sessions stay on " + who(event.from) + "."
    if (manual || (policy && policy.mode === "manual"))
      return "New " + service + " sessions now use " + who(event.accountId) + "." + running
    var reached = event.fromUsed === null || event.fromUsed === undefined ? ""
      : ": " + who(event.from) + " reached " + formatPercent(Math.round(event.fromUsed)) + "%"
    return "Omarchy moved new " + service + " sessions to " + who(event.accountId) + " at " + clock(event.at)
      + reached + "." + running
  }
  if (event.kind === "reset") {
    var owner = event.accountId !== "" ? who(event.accountId) : service
    return owner + "'s " + String(event.label || "limit").replace(/^./, function (c) { return c.toLowerCase() })
      + " reset at " + clock(event.at) + "."
  }
  if (event.kind === "omp-expired")
    return "omp can no longer renew " + who(event.accountId) + "'s sign-in. Sign in again in omp."
  return ""
}

// ---- 1.9 QmlBar ----
// The menu bar chip of a provider with several accounts (DESIGN §2): its account strip (the dots of
// accountState, the hint, the clock pie once every account is used up), one chip per account, the
// hover card, and the one-shot flashes.

var BAR_HOVER_ROWS = 6  // accounts the hover card lists before "+N more"

// An account's name for the bar and the hover card: the name it was given, else "Account N". Never an
// email, whatever the privacy setting: the bar is on screen all day.
function barAccountName(account, index, extraRaw) {
  if (!account) return ""
  return String(accountName(account, extraRaw, true, index + 1)).replace(/ · in use$/, "")
}

// One short mark per account for chips per account: the first letter of each name, two letters where
// names share one, the account's number where even those match, and the number of an unnamed
// "Account N".
function barAccountInitials(names) {
  var list = listOrEmpty(names)
  var marks = "—–-·.,;:_()[]{}'\"/\\|!?*#@&%+=~^<>"
  function letters(name, count) {
    var numbered = /^Account (\d+)$/.exec(name)
    if (numbered) return numbered[1]
    var kept = ""
    for (var c = 0; c < name.length; c++) {
      var character = name.charAt(c)
      if (character.trim() !== "" && marks.indexOf(character) === -1) kept += character
    }
    if (kept === "") return "?"
    return kept.charAt(0).toUpperCase() + kept.substring(1, count).toLowerCase()
  }
  function clashes(marksSoFar, index) {
    for (var k = 0; k < marksSoFar.length; k++)
      if (k !== index && marksSoFar[k].toUpperCase() === marksSoFar[index].toUpperCase()) return true
    return false
  }
  var single = []
  for (var i = 0; i < list.length; i++) single.push(letters(String(list[i]), 1))
  var paired = []
  for (var j = 0; j < list.length; j++) paired.push(clashes(single, j) ? letters(String(list[j]), 2) : single[j])
  var result = []
  for (var m = 0; m < list.length; m++) result.push(clashes(paired, m) ? String(m + 1) : paired[m])
  return result
}

// The counted account whose figure the chip shows: the one with the least headroom on the chip's
// window, so a chip never claims more room than the busiest account has. A used-up account only wins
// when every counted account is used up: new sessions go where there is room. -1 without a counted
// reading.
function barValueIndex(provider, counted, selector) {
  var accounts = listOrEmpty(provider && provider.accounts)
  var wanted = listOrEmpty(counted)
  var best = -1
  var bestRank = Infinity
  for (var i = 0; i < wanted.length; i++) {
    var account = accounts[wanted[i]]
    if (!account || account.status !== "ok") continue
    var left = remainingForWindow(account, selector)
    var rank = (minRemaining(account) === 0 ? 1000 : 0) + (left === null ? 101 : left)
    if (best < 0 || rank < bestRank) {
      best = wanted[i]
      bestRank = rank
    }
  }
  return best
}

// Everything the chip's account strip shows (DESIGN §2.1): the provider's dots (accountState().dots),
// the switch hint, and the clock pie once every account is used up. `state` is accountState();
// `options`: selector (the chip's window), nowSeconds, stale, extraKeys. Returns { count, dots:
// [{ index, state, counted, spending }], extra, allUsedUp, resetAt, pieFraction, hint, hintKind ("" |
// "switch" | "reset") }. A switch hint only appears in single mode under Omarchy's manual switching,
// when the counted login is critical and another login is ok.
function barAccountStrip(provider, state, options) {
  var opts = options || {}
  var accounts = listOrEmpty(provider && provider.accounts)
  var now = Number(opts.nowSeconds) || 0
  var result = { count: accounts.length, dots: [], extra: 0, allUsedUp: false, resetAt: 0, pieFraction: -1,
                 hint: "", hintKind: "" }
  if (accounts.length < 2 || !state) return result
  var wanted = listOrEmpty(state.counted)
  var states = listOrEmpty(state.rings)
  result.dots = listOrEmpty(state.dots && state.dots.dots)
  result.extra = Number(state.dots && state.dots.extra) || 0

  var usedUp = 0
  var soonest = null
  for (var j = 0; j < accounts.length; j++) {
    if (states[j] === "error") continue
    var blocked = accountUsedUp(accounts[j])
    if (!blocked) return withSwitchHint(result)
    usedUp++
    if (blocked.resetsAt !== null && (!soonest || blocked.resetsAt < soonest.resetsAt)) soonest = blocked
  }
  if (usedUp === 0) return withSwitchHint(result)
  result.allUsedUp = true
  result.hintKind = "reset"
  if (!soonest) {
    result.hint = "used up"
    return result
  }
  result.resetAt = soonest.resetsAt
  var wait = soonest.resetsAt - now
  result.hint = wait <= 0 ? "now" : formatDuration(Math.max(60, wait))
  var span = finiteOrNull(soonest.row.windowSeconds)
  if (span !== null && span > 0) result.pieFraction = clamp(1 - wait / span, 0, 1)
  return result

  function withSwitchHint(strip) {
    var choice = provider.accountSwitch
    if (state.mode === "together" || opts.stale || wanted.length !== 1 || !choice || choice.mode !== "manual") return strip
    var current = wanted[0]
    if (states[current] !== "critical" || accountSourceKind(accounts[current], false) !== "omarchy") return strip
    var target = -1
    var targetLeft = -1
    for (var k = 0; k < accounts.length; k++) {
      if (k === current || states[k] !== "ok" || accountSourceKind(accounts[k], false) !== "omarchy") continue
      var left = remainingForWindow(accounts[k], opts.selector)
      if (left !== null && left > targetLeft) {
        target = k
        targetLeft = left
      }
    }
    if (target < 0) return strip
    strip.hint = "→ " + barAccountName(accounts[target], target, opts.extraKeys)
    strip.hintKind = "switch"
    return strip
  }
}

// How many chips a provider takes in the bar: one, or under "chips" one per account, at most four and
// never more than the bar's cap (`max`, 0 for none), so a provider always fits the cap on its own.
function barChipCount(provider, barAccountMode, max) {
  var accounts = listOrEmpty(provider && provider.accounts)
  if (barAccountMode !== "chips" || accounts.length < 2 || String(provider && provider.status) === "error") return 1
  var cap = Math.floor(Number(max))
  return Math.min(accounts.length, 4, isFinite(cap) && cap > 0 ? cap : 4)
}

// Chips in the bar. Under "chips", a provider with two or more accounts gets one chip per account
// (barChipCount of them, counted accounts first when some must stay out, in the dots' order), each with
// the account's initial; every other provider keeps one chip. `stateFor(provider)` gives its
// accountState(); `max` is the bar's chip cap. Keys are stable across readings so chips keep their state:
// "<provider>" or "<provider>@<account id>".
function barChipEntries(providers, barAccountMode, stateFor, extraRaw, max) {
  var list = listOrEmpty(providers)
  var result = []
  for (var i = 0; i < list.length; i++) {
    var provider = list[i]
    var id = String(provider && provider.id)
    var accounts = listOrEmpty(provider && provider.accounts)
    var count = barChipCount(provider, barAccountMode, max)
    var state = count > 1 && typeof stateFor === "function" ? stateFor(provider) : null
    if (!state) {
      result.push({ key: id, providerId: id, accountIndex: -1, initial: "", counted: false })
      continue
    }
    var counted = listOrEmpty(state.counted)
    var slots = pickAccounts(state.stable, counted, count)
    var names = []
    for (var n = 0; n < accounts.length; n++) names.push(barAccountName(accounts[n], n, extraRaw))
    var initials = barAccountInitials(names)
    for (var s = 0; s < slots.length; s++) {
      var index = slots[s]
      var accountId = accounts[index].accountId
      result.push({ key: id + "@" + (accountId !== undefined && accountId !== null && accountId !== "" ? String(accountId) : "#" + index),
                    providerId: id, accountIndex: index, initial: initials[index], counted: contains(counted, index) })
    }
  }
  return result
}

// One-shot chip flash (DESIGN §2.2) from two readings of a chip, { key, severity, used, resetsAt }
// with `key` naming the account and window shown: "reset" when that window reset (windowWasReset, the
// rule Limits notices use, so a rolling window shedding old use never flashes), "alert" when it moved to
// a worse severity, "" otherwise. Another key (the chip moved to another account or window) only seeds,
// and staying at a severity never flashes again.
function barFlashKind(previous, next, nowSeconds) {
  if (!previous || !next || previous.key !== next.key) return ""
  if (windowWasReset(previous, next, nowSeconds)) return "reset"
  var before = SEVERITY_RANK[previous.severity]
  var after = SEVERITY_RANK[next.severity]
  return before !== undefined && after !== undefined && before > 0 && after > before ? "alert" : ""
}

// A reading is old once the last refresh failed, it is a kept last-known one, or the last success is
// more than two refresh intervals ago: chips fade, Limits' footer says "retrying". One rule, one clock.
function readingStale(nowMs, lastSuccessMs, intervalSeconds, refreshFailed, reading) {
  if (refreshFailed || (reading && reading.stale === true)) return true
  var last = Number(lastSuccessMs)
  if (!isFinite(last) || last <= 0) return false
  return Number(nowMs) - last > 2 * Math.max(60, Number(intervalSeconds) || 900) * 1000
}

// How long ago a reading was taken, for "Read 42 min ago".
function barAgoText(seconds) {
  var value = Math.max(0, Math.floor(Number(seconds) || 0))
  if (value < 60) return "less than a minute"
  if (value < 3600) return Math.floor(value / 60) + " min"
  return formatDuration(value)
}

// The hover card of a chip with several accounts (DESIGN §2.4), as plain text and values, from the
// provider's accountState() so it says what the chip and Limits say. It lists every account up to
// BAR_HOVER_ROWS; past that the counted ones, then those closest to a limit, and `more` for the rest.
// Rows follow the dots' order and are keyed by account. `options`: proxyMode, proxyLabel, nowSeconds,
// extraKeys, readAtSeconds, stale, formatClock(epochSeconds) → "18:02".
function barHoverModel(provider, state, options) {
  var opts = options || {}
  var accounts = listOrEmpty(provider && provider.accounts)
  var now = Number(opts.nowSeconds) || 0
  var clock = typeof opts.formatClock === "function" ? opts.formatClock : function (seconds) { return String(seconds) }
  var counted = state ? listOrEmpty(state.counted) : []
  var stable = state ? listOrEmpty(state.stable) : []
  var shown = stable
  if (stable.length > BAR_HOVER_ROWS) {
    var ranked = Array.prototype.slice.call(stable)
    ranked.sort(function (a, b) {
      var first = (contains(counted, a) ? 0 : 1) - (contains(counted, b) ? 0 : 1)
      if (first !== 0) return first
      var left = minRemaining(accounts[a])
      var right = minRemaining(accounts[b])
      left = left === null ? Infinity : left
      right = right === null ? Infinity : right
      return left !== right ? (left < right ? -1 : 1) : stable.indexOf(a) - stable.indexOf(b)
    })
    var chosen = ranked.slice(0, BAR_HOVER_ROWS)
    shown = Array.prototype.filter.call(stable, function (index) { return contains(chosen, index) })
  }
  var rows = []
  for (var r = 0; r < shown.length; r++) {
    var i = shown[r]
    var account = accounts[i]
    var ring = state.rings[i]
    var blocked = accountUsedUp(account)
    var activity = account.activity || {}
    var delta = finiteOrNull(activity.lastDelta)
    var increased = finiteOrNull(activity.lastIncreaseAt)
    var readAt = finiteOrNull(activity.lastReadingAt)
    var status = "idle"
    var tone = "dim"
    if (ring === "error") {
      status = errorReasonLabel(account.errorKind)
      tone = "urgent"
    } else if (blocked) {
      status = "used up" + (blocked.resetsAt !== null ? " · back " + clock(blocked.resetsAt) : "")
      tone = "urgent"
    } else if (state.spending[i]) {
      status = "spending now"
      tone = "accent"
    } else if (delta !== null && delta > 0 && increased !== null && readAt !== null && increased >= readAt) {
      status = "+" + formatPercent(delta) + " last reading"
    }
    var history = account.history || {}
    var accountId = account.accountId
    rows.push({ key: accountId !== undefined && accountId !== null && accountId !== "" ? String(accountId) : "#" + i,
                index: i, name: barAccountName(account, i, opts.extraKeys), inUse: state.inUse[i] === true,
                counted: contains(counted, i), state: ring, status: status, tone: tone,
                spark: listOrEmpty(history.h24), account: account })
  }
  var readAtSeconds = Number(opts.readAtSeconds) || 0
  var readText = readAtSeconds <= 0 ? "" : opts.stale
    ? "Read " + barAgoText(now - readAtSeconds) + " ago" : "Read at " + clock(readAtSeconds)
  return { title: providerShortName(provider) + " · " + accounts.length + " accounts",
           modeText: accountModeText(provider, state ? state.mode : "single", opts.proxyMode === true, opts.proxyLabel),
           rows: rows, more: Math.max(0, accounts.length - rows.length), readText: readText, stale: !!opts.stale }
}

// What a screen reader hears for a chip: "Claude, Work in use, 72% used, Personal 3% used", then what
// its strip says (`strip`: barAccountStrip): "switch to Personal", or "all used up, back in 1h 0m". A
// chip per account names only its own account (`accountIndex`). `state` is accountState(); `options`:
// selector, quotaMode, extraKeys, accountIndex, strip.
function barAccessibleName(provider, state, options) {
  var opts = options || {}
  var parts = [providerShortName(provider)]
  var accounts = listOrEmpty(provider && provider.accounts)
  var only = typeof opts.accountIndex === "number" && opts.accountIndex >= 0 ? opts.accountIndex : -1
  for (var i = 0; i < accounts.length; i++) {
    if (only >= 0 && i !== only) continue
    var account = accounts[i]
    var left = remainingForWindow(account, opts.selector)
    var shown = left === null ? null : opts.quotaMode === "Remaining" ? left : usedFromRemaining(left)
    var figure = account.status === "error" ? errorReasonLabel(account.errorKind)
      : shown === null ? "no reading" : quotaText(shown, opts.quotaMode)
    var name = barAccountName(account, i, opts.extraKeys)
    parts.push(state && state.inUse[i] === true ? name + " in use, " + figure : name + " " + figure)
  }
  var strip = opts.strip
  if (strip && strip.hintKind === "switch" && strip.hint) parts.push("switch to " + String(strip.hint).replace(/^→ /, ""))
  else if (strip && strip.allUsedUp) parts.push(strip.resetAt > 0 ? "all used up, back in " + strip.hint : "all used up")
  return parts.join(", ")
}
