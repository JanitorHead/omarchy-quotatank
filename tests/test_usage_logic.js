const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "UsageLogic.js"), "utf8")
  .replace(/^\.pragma library\s*/m, "");
const context = { Array, Math, Number, String, isFinite };
vm.createContext(context);
vm.runInContext(source, context, { filename: "UsageLogic.js" });

const provider = (id, remaining, status = "ok") => ({
  id,
  name: id,
  status,
  windows: remaining === null ? [] : [{ remaining }],
});

assert.equal(context.minRemaining(provider("claude", 72)), 72);
assert.equal(context.minRemaining({ ...provider("codex", 44), windows: [{ remaining: 91 }, { remaining: 44 }] }), 44);
assert.equal(context.minRemaining({ ...provider("codex", 44), windows: { 0: { remaining: 62 }, length: 1 } }), 62);
assert.equal(context.minRemaining(provider("claude", null)), null);
assert.equal(context.minRemaining({ ...provider("codex", 44), windows: [{ remaining: null }] }), null);
assert.equal(context.severity(provider("kimi", 9), 25, 10), "critical");
assert.equal(context.severity(provider("kimi", 20), 25, 10), "warning");
assert.equal(context.severity(provider("kimi", 80), 25, 10), "ok");
assert.equal(context.severity(provider("kimi", null, "error"), 25, 10), "error");
const listLike = { 0: "first", 1: "second", length: 2 };
assert.equal(context.isListLike(listLike), true);
assert.equal(context.isListLike("not a list"), false);
assert.equal(context.isListLike({ length: 1.5 }), false);
assert.equal(context.contains(listLike, "second"), true);
assert.equal(context.contains(listLike, "missing"), false);
assert.equal(JSON.stringify(context.firstItems(listLike, 1)), '["first"]');
assert.equal(JSON.stringify(context.listOrEmpty(null)), "[]");
assert.equal(context.errorTitle({ id: "claude", name: "Claude Code", errorKind: "expired" }), "Claude Code sign-in expired");

const providers = [provider("claude", 72), provider("codex", 44), provider("kimi", null, "error")];
const selected = context.selectedProviders(providers, { 0: "codex", 1: "kimi", length: 2 });
assert.equal(selected.length, 2);
assert.equal(selected[0].id, "codex");
assert.equal(context.barProviders(selected).length, 2);
assert.equal(context.selectedProviders(providers, []).length, 0);
assert.equal(providers.length, 3);

// Per-provider bar limits: a valid override wins, a missing or invalid slot inherits the global value.
const barLimitsText = JSON.stringify({ opencode: { top: "monthly", bottom: "weekly" }, codex: { top: "bogus" } });
assert.equal(JSON.stringify(context.barLimitsFor(barLimitsText, "opencode", "session", "none")), '{"top":"monthly","bottom":"weekly"}');
assert.equal(JSON.stringify(context.barLimitsFor(barLimitsText, "codex", "weekly", "none")), '{"top":"weekly","bottom":"none"}');
assert.equal(JSON.stringify(context.barLimitsFor(barLimitsText, "claude", "session", "monthly")), '{"top":"session","bottom":"monthly"}');
assert.equal(JSON.stringify(context.barLimitsFor("not json", "opencode", "auto", "none")), '{"top":"auto","bottom":"none"}');
assert.equal(JSON.stringify(context.parseBarLimits('{"x":{"top":"daily","bottom":"weekly"}}')), '{"x":{"bottom":"weekly"}}');
assert.equal(context.serializeBarLimits(context.parseBarLimits('{"x":{}}')), "{}");
assert.equal(context.setBarLimit('{"opencode":{"top":"monthly"}}', "opencode", "top", "default"), "{}");
const edited = JSON.parse(context.setBarLimit('{"opencode":{"bottom":"weekly"}}', "opencode", "top", "monthly"));
assert.equal(edited.opencode.top, "monthly");
assert.equal(edited.opencode.bottom, "weekly");
assert.equal(context.setBarLimit('{"opencode":{"top":"monthly"}}', "opencode", "top", "daily"), '{"opencode":{"top":"monthly"}}');

// Window rows: an exact window never borrows another window's remaining; the chip fallback does.
const opencode = {
  id: "opencode",
  status: "ok",
  windows: [
    { id: "weekly", label: "Weekly", windowSeconds: 604800, remaining: 40, resetsAt: 1791763200 },
    { id: "monthly", label: "Monthly", windowSeconds: 2592000, remaining: 0, resetsAt: 1792352671 },
  ],
};
assert.equal(context.exactRemainingForWindow(opencode, "weekly"), 40);
assert.equal(context.exactRemainingForWindow(opencode, "session"), null);
assert.equal(context.remainingForWindow(opencode, "session"), 0);
assert.equal(context.windowRowFor(opencode, "weekly", false).resetsAt, 1791763200);
assert.equal(context.windowRowFor(opencode, "auto", false).resetsAt, 1792352671);
assert.equal(context.barProviders([opencode, provider("claude", null)], (p) => (p.id === "opencode" ? "session" : "weekly")).length, 1);

const discovered = [
  { id: "claude", status: "ok", accounts: [{ status: "disabled" }, { status: "ok" }] },
  { id: "codex", status: "error", accounts: { 0: { status: "error", errorKind: "timeout" }, length: 1 } },
  { id: "xai", status: "disabled", accounts: [{ status: "disabled" }] },
  { id: "kimi", status: "error", errorKind: "no_credentials" },
  { id: "gemini", status: "unsupported", accounts: [{ status: "unsupported" }] },
];
assert.equal(JSON.stringify(context.availableProviders(discovered).map(row => row.id)),
  '["claude","codex","gemini"]', "hide unconnected or paused providers, retain active accounts even when quota checks fail");
assert.equal(context.availableProviders([{ id: "cliproxy", status: "error", errorKind: "no_credentials" }]).length,
  1, "proxy setup errors must remain visible");
assert.equal(context.availableProviders(null).length, 0);
assert.equal(discovered.length, 5, "filtering does not change backend discovery");

const priorAccount = { ...provider("antigravity", 75), accountId: "a", plan: "Pro", fetchedAt: "then" };
const oldProxy = { source: "cliproxy", providers: [{ ...priorAccount, accounts: [priorAccount] }] };
const failedAccount = { ...priorAccount, status: "error", windows: [], message: "Timeout" };
const stale = context.preserveProxyReadings(oldProxy, { source: "cliproxy",
  providers: [{ ...failedAccount, accounts: [failedAccount] }] });
assert.equal(stale.providers[0].accounts[0].windows[0].remaining, 75);
assert.equal(stale.providers[0].accounts[0].stale, true);
assert.equal(stale.providers[0].fetchedAt, "then");
const outage = context.preserveProxyReadings(oldProxy, { providers: [{ id: "cliproxy", status: "error", message: "Offline" }] });
assert.equal(outage.providers[0].id, "antigravity");
assert.equal(outage.providers[0].stale, true);
const paused = context.preserveProxyReadings(oldProxy, { providers: [{ ...priorAccount, status: "disabled", windows: [] }] });
assert.equal(paused.providers[0].status, "disabled");
assert.equal(paused.providers[0].windows.length, 0);

const accountPool = { ...provider("codex", 90), accounts: [
  { ...provider("codex", 90), accountId: "one", account: "one@example.invalid" },
  { ...provider("codex", 23), accountId: "two", account: "two@example.invalid" },
] };
const recent = [{ id: "codex", status: "ok", accountId: "two", lastUsedAt: 123 }];
let lastAccount = context.lastUsedAccount(accountPool, recent, true);
assert.equal(lastAccount.label, "Account 2");
assert.equal(context.minRemaining(lastAccount.reading), 23, "quota must belong to the last account, not the best account");
assert.equal(lastAccount.lastUsedAt, 123);
assert.equal(context.lastUsedAccount(accountPool, recent, false).label, "two@example.invalid");
assert.equal(context.lastUsedAccount(accountPool, [{ ...recent[0], accountId: "one" }], true).label, "Account 1");
assert.equal(context.lastUsedAccount(accountPool, [], true).reading, null);
assert.equal(context.lastUsedAccount(accountPool, [{ ...recent[0], accountId: "removed" }], true).reading, null);
assert.equal(context.lastUsedAccount(accountPool, [{ ...recent[0], status: "ambiguous" }], true).label, "Multiple accounts");
assert.equal(context.lastUsedAccount({ ...accountPool, accounts: { 0: accountPool.accounts[1], length: 1 } }, recent, true).label, "Account 1");
assert.equal(context.minRemaining(context.lastUsedAccount({ ...accountPool, accounts: [
  { ...accountPool.accounts[1], status: "disabled", windows: [] }
] }, recent, true).reading), null);
console.log("UsageLogic.js: all assertions passed");

const codexWindows = [
  {id: "additional-secondary", label: "Code review · Weekly limit", windowSeconds: 604800},
  {id: "codex-primary", label: "5 hour limit", windowSeconds: 18000},
  {id: "codex-secondary", label: "Weekly limit", windowSeconds: 604800}
];
assert.equal(context.accountWindows({windows: codexWindows}, false).length, 1);
assert.equal(context.accountWindows({windows: codexWindows}, false)[0].id, "codex-secondary");
assert.equal(context.accountWindows({windows: codexWindows}, true).length, 3);
assert.equal(context.accountWindows({windows: [{label: "Monthly limit"}]}, false)[0].label, "Monthly limit");
assert.equal(context.accountWindows({windows: []}, false).length, 0);
assert.equal(context.accountPlanLabel({id: "codex", planType: "pro"}), "Codex Pro · 20×");
assert.equal(context.accountPlanLabel({id: "codex", planType: "prolite"}), "Codex Pro · 5×");
assert.equal(context.accountPlanLabel({id: "codex", plan: "ChatGPT Pro"}), "Codex Pro · 20×");

const resetAccount = { ...provider("codex", 55), accountId: "reset-account", credits: { resetCreditsAvailable: 2 } };
assert.equal(context.accountResetLabel(resetAccount), "2 banked resets");
assert.equal(context.accountResetLabel({ ...resetAccount, credits: { resetCreditsAvailable: 1 } }), "1 banked reset");
assert.equal(context.accountResetLabel({ ...resetAccount, credits: { resetCreditsAvailable: 0 } }), "0 banked resets");
for (const count of [undefined, null, -1, 1.5, true, "2", NaN, Infinity])
  assert.equal(context.accountResetLabel({ ...resetAccount, credits: { resetCreditsAvailable: count } }), "");
assert.equal(context.accountResetLabel({ ...resetAccount, credits: null }), "");
assert.equal(context.accountResetLabel({ ...resetAccount, id: "claude" }), "");
assert.equal(context.accountResetLabel({ ...resetAccount, status: "disabled" }), "");
const resetFailure = { ...resetAccount, status: "error", credits: null, message: "Timeout" };
const resetStale = context.preserveProxyReadings({ source: "cliproxy", providers: [{ ...resetAccount, accounts: [resetAccount] }] },
  { source: "cliproxy", providers: [{ ...resetFailure, accounts: [resetFailure] }] });
assert.equal(context.accountResetLabel(resetStale.providers[0].accounts[0]), "2 banked resets");
assert.equal(resetStale.providers[0].accounts[0].stale, true);
const goSnapshot = { source: "cliproxy", proxyImplementation: "go",
  providers: [{ ...resetAccount, proxyImplementation: "go", accounts: [{ ...resetAccount, proxyImplementation: "go" }] }] };
const nativeFailure = { ...resetFailure, windows: [], proxyImplementation: "rust", supportsBankedReset: false };
const rustSnapshot = context.preserveProxyReadings(goSnapshot,
  { source: "cliproxy", proxyImplementation: "rust", providers: [{ ...nativeFailure, accounts: [nativeFailure] }] });
assert.equal(rustSnapshot.providers[0].accounts[0].credits, null, "implementation changes never restore Go reset credits");
assert.equal(rustSnapshot.providers[0].accounts[0].windows.length, 0);
const malformedNative = context.preserveProxyReadings(
  { source: "cliproxy", providers: [{ ...priorAccount, proxyImplementation: "rust" }] },
  { source: "cliproxy", providers: [{ ...failedAccount, proxyImplementation: "rust", errorKind: "malformed" }] });
assert.equal(malformedNative.providers[0].status, "error", "invalid native data cannot become a successful retained reading");

const customRows = [{model: " vendor/Model[1m] ", inputCostPerMillionTokens: "2",
  outputCostPerMillionTokens: "8", cacheReadCostPerMillionTokens: "0", cacheWriteCostPerMillionTokens: ""}];
const customJson = context.encodeCostPrices(customRows);
assert.deepEqual(JSON.parse(customJson), {"vendor/Model[1m]": {
  inputCostPerMillionTokens: 2, outputCostPerMillionTokens: 8, cacheReadCostPerMillionTokens: 0}});
assert.equal(context.encodeCostPrices(context.decodeCostPrices(customJson)), customJson);
assert.equal(context.encodeCostPrices([]), "{}");
for (const value of ["", "-1", "Infinity", "NaN", "0x10", "true", "1e10"])
  assert.throws(() => context.encodeCostPrices([{...customRows[0], inputCostPerMillionTokens: value}]));
assert.throws(() => context.encodeCostPrices([customRows[0], customRows[0]]));
assert.throws(() => context.encodeCostPrices([{...customRows[0], model: "<unattributed>"}]));
for (const raw of ["null", "[]", "{", '{"x":{"inputCostPerMillionTokens":true,"outputCostPerMillionTokens":2}}',
  '{"x":{"inputCostPerMillionTokens":2}}', '{"x":{"inputCostPerMillionTokens":2,"outputCostPerMillionTokens":2,"extra":2}}'])
  assert.throws(() => context.decodeCostPrices(raw));
const specialId = context.encodeCostPrices([{...customRows[0], model: "__proto__"}]);
assert.ok(Object.prototype.hasOwnProperty.call(JSON.parse(specialId), "__proto__"));
console.log("Custom cost price validation: passed");

const a = { id: 'codex', accountId: '0123456789abcdef' };
const b = { id: 'codex', accountId: 'fedcba9876543210' };
const activity = { liveState: 'live', liveAccounts: [
  { provider: 'codex', accountId: a.accountId, inFlight: 3, sessions: 5 },
  { provider: 'codex', accountId: b.accountId, inFlight: 1, sessions: 1 }
] };
activity.liveState = 'reconnecting';
assert.equal(context.accountLoad(a, activity), null);
assert.equal(context.sessionBadgeText(null), 'Sessions unknown');
assert.equal(context.sessionBadgeText({sessions: 0}), '0 sessions');
assert.equal(context.sessionBadgeText({sessions: 1, inFlight: 3}), '1 session');
assert.equal(context.sessionBadgeText({sessions: 5, inFlight: 0}), '5 sessions');
assert.match(context.sessionDetails({sessions: 5}), /may remain assigned after a request finishes/);
const payload = { schemaVersion: 1, state: 'live', message: 'Live', providers: [], accounts: activity.liveAccounts };
assert.equal(context.validLivePayload(payload), true);
assert.equal(context.validLivePayload({ ...payload, state: 'reconnecting' }), false);
assert.equal(context.validLivePayload({ ...payload, accounts: [{...activity.liveAccounts[0], inFlight: NaN}] }), false);
assert.equal(context.validLivePayload({ ...payload, accounts: [{...activity.liveAccounts[0], inFlight: true}] }), false);
let created = 0, stopped = 0, destroyed = 0;
const factory = { createObject(parent) { assert.equal(parent,null); created++; return {
  stop() { stopped++; }, destroy() { destroyed++; }
}; } };
assert.equal(context.acquireLive('test', factory, {}), context.acquireLive('test', factory, {}));
assert.equal(created,1);
context.releaseLive('test'); assert.equal(stopped,0);
context.releaseLive('test'); assert.equal(stopped,1);
// The menu bar limit setting: which window supplies the percentage, the
// fallbacks, and the spellings shared with the AI usage widget.
const windowed = (windows) => ({ id: "opencode", name: "OpenCode Go", status: "ok", windows });
const opencodeWindows = windowed([
  { id: "session", label: "5 hour limit", remaining: 100, windowSeconds: 18000 },
  { id: "weekly", label: "Weekly limit", remaining: 60, windowSeconds: 604800 },
  { id: "monthly", label: "Monthly limit", remaining: 80, windowSeconds: 2592000 },
]);
assert.equal(context.remainingForWindow(opencodeWindows, "auto"), 60, "auto keeps the most restrictive window");
assert.equal(context.remainingForWindow(opencodeWindows, "session"), 100);
assert.equal(context.remainingForWindow(opencodeWindows, "5h"), 100, "the AI usage widget spellings resolve");
assert.equal(context.remainingForWindow(opencodeWindows, "7D"), 60);
assert.equal(context.remainingForWindow(opencodeWindows, "30d"), 80);
assert.equal(context.remainingForWindow(opencodeWindows, "nonsense"), 60, "an unknown value falls back to the most restrictive window");
const weeklyOnly = windowed([{ id: "weekly", label: "Weekly limit", remaining: 42, windowSeconds: 604800 }]);
assert.equal(context.remainingForWindow(weeklyOnly, "monthly"), 42, "a missing window keeps a bar percentage");
const undated = windowed([{ id: "monthly", label: "Monthly", remaining: 25 }]);
assert.equal(context.remainingForWindow(undated, "monthly"), 25, "windows without a duration match by id or label");
assert.equal(context.remainingForWindow({ ...opencodeWindows, status: "error" }, "weekly"), null);
assert.equal(context.severity(opencodeWindows, 25, 10, 80), "ok");
assert.equal(context.severity(opencodeWindows, 25, 10, 9), "critical");
assert.equal(context.barProviders([opencodeWindows, weeklyOnly], "weekly").length, 2);
assert.equal(context.barProviders([{ ...opencodeWindows, status: "error" }], "weekly").length, 1);
assert.equal(context.windowShortLabel("session"), "5h");
assert.equal(context.windowShortLabel("7D"), "7d");
assert.equal(context.windowShortLabel("monthly"), "30d");
const failedNoWindows = { id: "codex", status: "error", errorKind: "rate_limited", windows: [] };
const failedBar = context.barProviders([failedNoWindows, provider("claude", null)], "weekly");
assert.equal(failedBar.length, 1);
assert.equal(failedBar[0].id, "codex");
assert.equal(context.errorReasonLabel("rate_limited"), "rate limited");
assert.equal(context.errorReasonLabel("expired"), "sign in");
assert.equal(context.errorReasonLabel("no_credentials"), "sign in");
assert.equal(context.errorReasonLabel("timeout"), "timeout");
assert.equal(context.errorReasonLabel("network"), "offline");
assert.equal(context.errorReasonLabel("malformed"), "bad data");
assert.equal(context.errorReasonLabel("http"), "error");
assert.equal(context.errorReasonLabel("constructor"), "error");
assert.equal(context.errorReasonLabel(undefined), "error");
assert.equal(context.errorNeedsSignIn("expired"), true);
assert.equal(context.errorNeedsSignIn("no_credentials"), true);
assert.equal(context.errorNeedsSignIn("rate_limited"), false);
assert.equal(context.windowShortLabel("auto"), "", "auto has no single period to tag");
assert.equal(context.inheritedBarLimitLabel("top", "session"), "Global: 5-hour (session)");
assert.equal(context.inheritedBarLimitLabel("bottom", "none"), "Global: None", "a disabled global bottom limit is not shown as auto");
assert.equal(context.inheritedBarLimitLabel("bottom", "weekly"), "Global: 7-day (weekly)");
assert.equal(context.inheritedBarLimitLabel("top", "auto"), "Global: Lowest left (auto)");

// Second stacked bar limit: strict lookup, no fallback to the most restrictive window.
assert.equal(context.normalizeSecondaryBarWindow(""), "none");
assert.equal(context.normalizeSecondaryBarWindow("none"), "none");
assert.equal(context.normalizeSecondaryBarWindow("auto"), "none", "auto is not a valid second limit");
assert.equal(context.normalizeSecondaryBarWindow("7D"), "weekly");
assert.equal(context.normalizeSecondaryBarWindow("nonsense"), "none");
assert.equal(context.exactRemainingForWindow(weeklyOnly, "weekly"), 42);
assert.equal(context.exactRemainingForWindow(weeklyOnly, "monthly"), null, "an unreported window gets no fallback");
assert.equal(context.exactRemainingForWindow(weeklyOnly, "auto"), null);
assert.equal(context.exactRemainingForWindow({ ...weeklyOnly, status: "error" }, "weekly"), null);
assert.equal(context.exactRemainingForWindow(opencodeWindows, "monthly"), 80);
assert.equal(context.remainingForWindow(weeklyOnly, "monthly"), 42, "the primary bar keeps its fallback");
assert.equal(context.usedFromRemaining(30), 70);
assert.equal(context.usedFromRemaining(null), null);

// Shared number formatting and the Limits view's per-model rows.
assert.equal(context.formatTokens(8166), "8.17K");
assert.equal(context.formatTokens(0), "0");
assert.equal(context.formatTokens(null), "0");
assert.equal(context.formatTokens(2_500_000), "2.50M");
assert.equal(context.formatUsd(0.00122625), "$0.0012");
assert.equal(context.formatUsd(12.345), "$12.35");
assert.equal(context.formatUsd(null), "—");
const modelRows = [
  { provider: "opencode", model: "small", totalTokens: 10, costUsd: 0.01 },
  { provider: "claude", model: "other", totalTokens: 999, costUsd: 1 },
  { provider: "opencode", model: "heavy", totalTokens: 5000, costUsd: null },
];
assert.equal(JSON.stringify(context.providerModels(modelRows, "opencode").map(row => row.model)),
  '["heavy","small"]', "one provider, heaviest first, unknown cost kept in the list");
assert.equal(context.providerModels(modelRows, "kimi").length, 0);
assert.equal(context.providerModels(null, "opencode").length, 0);

// Used versus remaining: both sides of one allowance, and the label that goes
// with each. Provider dashboards show usage, so that is the default.
const halfUsed = { id: "opencode", name: "OpenCode Go", status: "ok",
  windows: [{ id: "weekly", label: "Weekly limit", used: 41.6, remaining: 58.4, windowSeconds: 604800 }] };
assert.equal(context.windowUsed(halfUsed.windows[0]), 41.6);
assert.equal(context.windowRemaining(halfUsed.windows[0]), 58.4);
assert.equal(context.usedForWindow(halfUsed, "weekly"), 41.6);
assert.equal(context.usedForWindow(halfUsed, "auto"), 41.6, "auto still resolves to the most restrictive window");
assert.equal(context.quotaText(41.6, "Used"), "41.6% used");
assert.equal(context.quotaText(58.4, "Remaining"), "58.4% left");
assert.equal(context.quotaText(null, "Used"), "");
const onlyRemaining = { id: "x", status: "ok", windows: [{ id: "w", label: "Weekly", remaining: 30 }] };
assert.equal(context.windowUsed(onlyRemaining.windows[0]), 70, "a window reporting one side still yields the other");
assert.equal(context.windowRemaining({ used: 12.5 }), 87.5);
assert.equal(context.windowUsed(null), null);

assert.equal(context.formatPercent(41.6), "41.6", "one decimal survives");
assert.equal(context.formatPercent(4), "4", "an integer keeps no invented decimal");
assert.equal(context.formatPercent(20.75), "20.8", "rounds to one decimal");
assert.equal(context.formatPercent(null), "");
assert.equal(context.quotaText(41.6, "Used"), "41.6% used");
assert.equal(context.quotaText(58.4, "Remaining"), "58.4% left");

// Pace: the projection rests on each window's own recent samples, not on its average since reset.
// `NOW` is injected so results are fixed. Samples are [epoch, used] pairs, each holding until the next.
const NOW = 1000000;
const HOUR = 3600;
const DAY = 24 * HOUR;
const WEEK = 604800;
const weekStart = NOW - WEEK / 2; // a weekly window, half elapsed
const weekly = (used, samples, untilReset = WEEK / 2) =>
  ({ used, windowSeconds: WEEK, resetsAt: NOW + untilReset, samples });
// Samples every `step` seconds from `from` through `to`, all holding `used`.
const holding = (from, to, used, step = 900) => {
  const rows = [];
  for (let t = from; t <= to; t += step) rows.push([t, used]);
  return rows;
};
// Samples rising linearly from 0 at `from` to `endUsed` at `to`.
const linear = (from, to, endUsed, step = 900) => {
  const rows = [];
  for (let t = from; t <= to; t += step) rows.push([t, endUsed * (t - from) / (to - from)]);
  return rows;
};

assert.equal(context.paceForWindow(null, NOW), null);
assert.equal(context.paceForWindow({ used: 10, resetsAt: NOW + 500, samples: [] }, NOW), null, "no windowSeconds, no projection");
assert.equal(context.paceForWindow({ used: 10, windowSeconds: WEEK, resetsAt: null, samples: [] }, NOW), null, "null resetsAt is not zero");
assert.equal(context.paceForWindow({ windowSeconds: WEEK, resetsAt: NOW + 500, samples: [] }, NOW), null, "no usage figure, no projection");
assert.equal(context.paceForWindow(weekly(10, []), null), null, "no clock, no projection");

const remainingOnly = context.paceForWindow({ remaining: 40, windowSeconds: WEEK, resetsAt: NOW + WEEK / 2, samples: [] }, NOW);
assert.equal(remainingOnly.used, 60, "a remaining-only row reads used through windowUsed");

const early = context.paceForWindow(weekly(30, [[NOW - 60, 30]], WEEK - 1000), NOW);
assert.equal(early.known, false, "under 2% elapsed there is no projection");
assert.equal(context.paceStatusText(early), "starts after 2% of the window");

const unused = context.paceForWindow(weekly(0, holding(weekStart, NOW, 0)), NOW);
assert.equal(unused.state, "no-usage");
assert.equal(unused.runsOut, false);
assert.equal(context.paceText(unused), "");
assert.equal(context.paceTickText(unused), "", "no tick, no tooltip");
assert.equal(context.paceStatusText(unused), "no usage yet");

const noSamples = context.paceForWindow({ used: 60, windowSeconds: WEEK, resetsAt: NOW + WEEK / 2 }, NOW);
assert.equal(noSamples.state, "stale", "a row without samples is never projected from an average");

// The bug this guards: used early, then quiet for days. The since-reset average (60% in half a week)
// would say it runs out before reset; the recent burn is zero, so there is no projection.
const quietSince = NOW - 3 * DAY;
const dormant = context.paceForWindow(weekly(60, [
  ...holding(weekStart, quietSince, 0),
  ...holding(quietSince + 900, NOW, 60),
]), NOW);
assert.equal(dormant.state, "idle");
assert.equal(dormant.runsOut, false);
assert.equal(dormant.etaSeconds, null);
assert.ok(dormant.idleSeconds >= 3 * DAY - 900, "idle time runs from the last increase");
assert.equal(context.paceShowsMark(dormant), true, "an idle window keeps its tick: used against expected");
assert.equal(context.paceText(dormant), "Idle 2d 23h · expected 50%");
assert.equal(context.paceTickText(dormant), "Used 60% · expected 50%\nAhead by 10 pts\nNo increase for 2d 23h · no projection");

// A calm window with a burst in its last hour projects a run-out; its since-reset average (20% in half a week) does not.
const burst = context.paceForWindow(weekly(20, [
  ...holding(weekStart, NOW - HOUR, 10),
  [NOW - 2700, 12.5], [NOW - 1800, 15], [NOW - 900, 17.5], [NOW, 20],
]), NOW);
assert.equal(burst.state, "projecting");
assert.equal(burst.runsOut, true, "the recent rate decides the run-out, not the calm average");
assert.ok(burst.etaSeconds > 0 && burst.etaSeconds < WEEK / 2);
assert.ok(context.paceText(burst).startsWith("Runs out in "));
assert.ok(context.paceText(burst).endsWith("· expected 50%"));
assert.ok(context.paceTickText(burst).split("\n")[2].startsWith("At this pace: runs out in "));
assert.equal(context.paceStatusText(burst), context.paceText(burst), "a drawn tick reports the same line as paceText");

// A steady burn that empties the window exactly at reset is not a run-out (40% used, 60% left at 40%/half week).
const steady = context.paceForWindow(weekly(40, linear(weekStart, NOW, 40)), NOW);
assert.equal(steady.state, "projecting");
assert.equal(steady.runsOut, false, "a steady burn that lasts until reset is not a run-out");
assert.equal(context.paceText(steady), "Lasts until reset · expected 50%");
assert.equal(context.paceTickText(steady), "Used 40% · expected 50%\nBehind by 10 pts\nAt this pace: lasts until reset");

// Too little observed time is no basis for a projection.
const fresh = context.paceForWindow(weekly(20, [[NOW - 300, 20], [NOW, 20]]), NOW);
assert.equal(fresh.state, "collecting");
assert.equal(context.paceShowsMark(fresh), false, "no rate yet, so no tick and no Ahead/Behind");
assert.equal(context.paceTickText(fresh), "");
assert.equal(context.paceStatusText(fresh), "Collecting data");

// A gap longer than an hour is unobserved: the rise across it is neither a rate nor idle time.
const gapped = context.paceForWindow(weekly(20, [[NOW - 4000, 10], [NOW - 100, 20]]), NOW);
assert.equal(gapped.state, "collecting");
assert.equal(gapped.observedSeconds, 100);

// Newest sample older than an hour: the data is stale, not idle. No rate is trusted, so no tick and no Ahead/Behind.
const silent = context.paceForWindow(weekly(60, holding(weekStart, NOW - 2 * HOUR, 60)), NOW);
assert.equal(silent.state, "stale");
assert.equal(context.paceShowsMark(silent), false, "stale data draws no tick");
assert.equal(context.paceTickText(silent), "");
assert.equal(context.paceStatusText(silent), "No recent data");

// Usage recorded before the window started is not a rise inside it.
const previous = context.paceForWindow(weekly(5, [[weekStart - HOUR, 90], ...holding(weekStart, NOW, 5)]), NOW);
assert.equal(previous.state, "idle", "the earlier window's 90% does not start a burn");
assert.equal(previous.runsOut, false);

const exhausted = context.paceForWindow(weekly(140, holding(weekStart, NOW, 100)), NOW);
assert.equal(exhausted.used, 100, "used clamps before projecting");
assert.equal(exhausted.state, "exhausted");
assert.equal(context.paceText(exhausted), "Limit reached");
assert.equal(context.paceShowsMark(exhausted), false, "an exhausted window has no tick");

assert.equal(context.paceText(null), "");
assert.equal(context.paceStatusText(null), "not reported");
assert.equal(context.paceShowsMark(unused), false);

assert.equal(context.formatDuration(0), "0m");
assert.equal(context.formatDuration(41 * 60), "41m");
assert.equal(context.formatDuration(2 * 3600 + 5 * 60), "2h 5m");
assert.equal(context.formatDuration(3 * 86400 + 4 * 3600), "3d 4h");
assert.equal(context.formatDuration(null), "");

// Threshold crossings: notify only on a move to a worse severity, seed silently on first sight.
const reading = (key, severity) => ({ key, severity });
const step = (previous, readings) => context.severityCrossings(previous, readings);

const seeded = step({}, [reading("codex|weekly", "ok")]);
assert.equal(seeded.crossings.length, 0, "first sighting seeds silently");
assert.equal(seeded.state["codex|weekly"], "ok");

const warned = step(seeded.state, [reading("codex|weekly", "warning")]);
assert.equal(warned.crossings.length, 1, "ok to warning notifies");
assert.equal(warned.crossings[0].severity, "warning");

const stillWarned = step(warned.state, [reading("codex|weekly", "warning")]);
assert.equal(stillWarned.crossings.length, 0, "staying at warning does not repeat");

const critical = step(stillWarned.state, [reading("codex|weekly", "critical")]);
assert.equal(critical.crossings.length, 1, "warning to critical notifies");

const recovered = step(critical.state, [reading("codex|weekly", "ok")]);
assert.equal(recovered.crossings.length, 0, "recovery never notifies");
assert.equal(recovered.state["codex|weekly"], "ok");

const rearmed = step(recovered.state, [reading("codex|weekly", "warning")]);
assert.equal(rearmed.crossings.length, 1, "a reset re-arms the next crossing");

const jumped = step({ "codex|weekly": "ok" }, [reading("codex|weekly", "critical")]);
assert.equal(jumped.crossings.length, 1, "a jump straight to critical notifies once");

const unknown = step(rearmed.state, [reading("codex|weekly", "none")]);
assert.equal(unknown.crossings.length, 0, "no reading is not a crossing");
assert.equal(unknown.state["codex|weekly"], "warning", "no reading keeps the last known severity");

const dropped = step({ "codex|weekly": "critical" }, []);
assert.equal(Object.keys(dropped.state).length, 0, "a window that disappears is forgotten");
assert.equal(step(dropped.state, [reading("codex|weekly", "critical")]).crossings.length, 0, "a returning window seeds again");

const batch = step({ "codex|weekly": "ok", "claude|session": "ok" },
  [reading("codex|weekly", "warning"), reading("claude|session", "critical")]);
assert.equal(batch.crossings.length, 2, "each window crosses independently in one refresh");

const exported = (hideEmails) => JSON.parse(context.exportSnapshot([{
  id: "codex", name: "Codex", status: "ok",
  windows: [{ label: "weekly", used: 60, remaining: 40, resetsAt: 1080, windowSeconds: 100 }],
  accounts: [{ account: "alice@example.com", windows: [{ label: "weekly", remaining: 40, resetsAt: 1080, windowSeconds: 100 }] }],
}], 1050, hideEmails));
const hidden = exported(true);
assert.equal(hidden.generatedAt, 1050);
assert.equal(hidden.providers[0].accounts[0].label, "Account 1");
assert.equal(exported(undefined).providers[0].accounts[0].label, "Account 1");
assert.equal(exported(false).providers[0].accounts[0].label, "alice@example.com");
const exportedWindow = hidden.providers[0].windows[0];
assert.equal(exportedWindow.used, 60);
assert.equal(exportedWindow.remaining, 40);
assert.equal(exportedWindow.resetsAt, 1080);
assert.equal(exportedWindow.pace.expected, 70);
assert.equal(exportedWindow.pace.state, "stale", "no samples in the export: no projection from the average");
assert.equal(exportedWindow.pace.runsOut, false);

// Bar reset text: a window of at most a day shows a time; longer windows show a date.
assert.equal(context.barResetKind({ id: "session", windowSeconds: 18000 }), "time")
assert.equal(context.barResetKind({ id: "x", windowSeconds: 86400 }), "time")
assert.equal(context.barResetKind({ id: "x", windowSeconds: 86401 }), "date")
assert.equal(context.barResetKind({ id: "weekly", windowSeconds: 604800 }), "date")
assert.equal(context.barResetKind({ id: "monthly", windowSeconds: 2592000 }), "date")
assert.equal(context.barResetKind({ id: "session" }), "time")
assert.equal(context.barResetKind({ id: "weekly" }), "date")
// The chosen format applies only to its kind; unknown stored values fall back to the default.
assert.equal(context.barResetFormat("time", "24h", "DD/MM"), "HH:mm")
assert.equal(context.barResetFormat("time", "12h", "MM/DD"), "h:mm AP")
assert.equal(context.barResetFormat("time", "bogus", "DD/MM"), "HH:mm")
assert.equal(context.barResetFormat("date", "12h", "DD/MM"), "dd/MM")
assert.equal(context.barResetFormat("date", "24h", "MM/DD"), "MM/dd")
assert.equal(context.barResetFormat("date", "24h", "D MMM"), "d MMM")
assert.equal(context.barResetFormat("date", "24h", "constructor"), "dd/MM")
assert.equal(context.normalizeBarResetChoice("date", "12h"), "DD/MM")
assert.equal(context.normalizeBarResetChoice("time", "12h"), "12h")
assert.equal(context.normalizeBarResetChoice("time", undefined), "24h")
