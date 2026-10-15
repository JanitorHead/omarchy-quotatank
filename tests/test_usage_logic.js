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
// A chip shows only its longer window when that window is exhausted; otherwise both stay.
assert.equal(context.blockingWindow("weekly", 40, "monthly", 0), "monthly");
assert.equal(context.blockingWindow("monthly", 0, "weekly", 40), "monthly");
assert.equal(context.blockingWindow("session", 0, "weekly", 0), "weekly");
assert.equal(context.blockingWindow("weekly", 0, "monthly", 40), "");
assert.equal(context.blockingWindow("monthly", 40, "weekly", 0), "");
assert.equal(context.blockingWindow("weekly", 40, "monthly", 0.4), "");
assert.equal(context.blockingWindow("weekly", 40, "monthly", null), "");
assert.equal(context.blockingWindow("auto", 0, "monthly", 0), "");
assert.equal(context.blockingWindow("weekly", 0, "none", null), "");
assert.equal(context.blockingWindow("weekly", 0, "weekly", 0), "");
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

const codexWindows = [
  {id: "additional-secondary", label: "Code review · Weekly limit", windowSeconds: 604800},
  {id: "codex-primary", label: "5-hour limit", windowSeconds: 18000},
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
  { id: "session", label: "5-hour limit", remaining: 100, windowSeconds: 18000 },
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
const noSession = windowed([
  { id: "weekly", label: "Weekly limit", remaining: 64, windowSeconds: 604800 },
  { id: "monthly", label: "Monthly limit", remaining: 58, windowSeconds: 2592000 },
]);
assert.equal(context.barTagFor(noSession, "session", true), "30d", "a fallback figure is tagged with its own period, not the chosen one");
assert.equal(context.barTagFor(noSession, "weekly", true), "7d");
assert.equal(context.barTagFor(noSession, "auto", true), "30d", "most constrained names the period of the limit it picked");
assert.equal(context.barTagFor(windowed([{ id: "quota", label: "Quota", remaining: 30 }]), "auto", true), "", "an unknown period gets no tag");
assert.equal(context.barTagFor(windowed([{ id: "quota", label: "Quota", remaining: 30 }]), "session", true), "", "an unknown fallback period gets no tag");
assert.equal(context.barTagFor({ ...noSession, status: "error" }, "weekly", false), "7d");
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
assert.equal(context.quotaText(null, "Used"), "");
const onlyRemaining = { id: "x", status: "ok", windows: [{ id: "w", label: "Weekly", remaining: 30 }] };
assert.equal(context.windowUsed(onlyRemaining.windows[0]), 70, "a window reporting one side still yields the other");
assert.equal(context.windowRemaining({ used: 12.5 }), 87.5);
assert.equal(context.windowUsed(null), null);

assert.equal(context.formatPercent(41.6), "41.6", "one decimal survives");
assert.equal(context.formatPercent(4), "4", "an integer keeps no invented decimal");
assert.equal(context.formatPercent(20.75), "20.8", "rounds to one decimal");
assert.equal(context.formatPercent(null), "");

// Alert thresholds are stored as % left. Used mode shows and enters them as % used, so 25 left is 75 used.
assert.equal(context.thresholdInMode(25, "Remaining"), 25);
assert.equal(context.thresholdInMode(25, "Used"), 75);
assert.equal(context.thresholdToLeft(75, "Used"), 25);
assert.equal(context.thresholdToLeft(25, "Remaining"), 25);
assert.equal(context.thresholdInMode(context.thresholdToLeft(37, "Used"), "Used"), 37, "a value entered in Used mode round-trips");
assert.equal(context.thresholdToLeft(150, "Remaining"), 100, "entries clamp to the 0-100 scale");
// Entry bounds in the shown unit: stored 1-100 left is 0-99 used.
assert.equal(JSON.stringify(context.thresholdBounds(1, 100, "Used")), "[0,99]");
assert.equal(JSON.stringify(context.thresholdBounds(1, 100, "Remaining")), "[1,100]");
assert.equal(JSON.stringify(context.thresholdBounds(0, 100, "Used")), "[0,100]");
// Alerts report the figure in the chosen mode; severity still gates on what is left.
assert.equal(context.alertFigure(20, "Remaining"), 20);
assert.equal(context.alertFigure(20, "Used"), 80);
assert.equal(context.alertFigure(null, "Used"), null);
assert.ok(context.alertText("warning", 20, "Used").includes("80"), "a Used alert names usage");
assert.ok(!context.alertText("warning", 20, "Used").includes("20"), "a Used alert never names the left figure");
assert.ok(context.alertText("critical", 5, "Remaining").includes("5"), "a Remaining alert names what is left");

// Pace: the tick is elapsed time; the projection follows the recent rate for short limits and the
// window's average blended with the last day for weekly and monthly ones.
// `NOW` is injected so results are fixed. Samples are [epoch, used] pairs, each holding until the next.
const NOW = 1000000;
const HOUR = 3600;
const DAY = 24 * HOUR;
const WEEK = 604800;
const SESSION = 5 * HOUR;
const weekStart = NOW - WEEK / 2; // a weekly window, half elapsed
const sessionStart = NOW - SESSION / 2; // a 5-hour window, half elapsed
const weekly = (used, samples, untilReset = WEEK / 2) =>
  ({ used, windowSeconds: WEEK, resetsAt: NOW + untilReset, samples });
const session = (used, samples) => ({ used, windowSeconds: SESSION, resetsAt: NOW + SESSION / 2, samples });
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

// Unknown usage (null on both sides, e.g. an Antigravity pool without a remaining fraction) stays
// unknown: no figure, no meter, no pace, never the most constrained window, never an alert.
const unknownWindow = { id: "gemini-pro", label: "Gemini Pro · 5-hour limit", used: null, remaining: null,
  resetsAt: NOW + HOUR, windowSeconds: SESSION };
assert.equal(context.windowUsed(unknownWindow), null, "null usage is not 0% used");
assert.equal(context.windowRemaining(unknownWindow), null, "null usage is not 0% left");
assert.equal(context.windowUsed({ used: "" }), null, "an empty value is unknown too");
assert.equal(context.windowUsed({ used: 0, remaining: 100 }), 0, "a real zero stays zero");
assert.equal(context.windowRemaining({ used: null, remaining: 0 }), 0, "a real zero left stays zero");
assert.equal(context.meterFill(unknownWindow, "Used"), null, "no meter fill");
assert.equal(context.meterFill(unknownWindow, "Remaining"), null);
assert.equal(context.paceForWindow(unknownWindow, NOW), null, "no pace without usage");
const partlyKnown = { id: "antigravity", status: "ok", windows: [unknownWindow,
  { id: "claude-weekly", label: "Claude · Weekly limit", used: 30, remaining: 70, windowSeconds: WEEK, resetsAt: NOW + DAY }] };
assert.equal(context.minRemaining(partlyKnown), 70, "an unknown window is never the most constrained");
assert.equal(context.exactRemainingForWindow(partlyKnown, "session"), null, "the chosen window has no figure");
assert.equal(context.remainingForWindow(partlyKnown, "session"), 70, "the chip falls back to a known window");
assert.equal(context.severity({ id: "antigravity", status: "ok", windows: [unknownWindow] }, 25, 10), "none", "no alert from unknown usage");
assert.equal(context.usedUpLongWindow({ id: "antigravity", status: "ok", windows: [{ ...unknownWindow, windowSeconds: WEEK }] }), null);
const exportedUnknown = context.exportWindows([unknownWindow], NOW)[0];
assert.equal(exportedUnknown.used, null);
assert.equal(exportedUnknown.remaining, null);
assert.equal(exportedUnknown.pace, null);

// A monthly window that reports its real calendar period (28 to 31 days) is still monthly.
for (const days of [28, 30, 31])
  assert.equal(context.windowMatches({ windowSeconds: days * DAY }, "monthly"), true, days + "-day month");
assert.equal(context.windowMatches({ windowSeconds: 27 * DAY }, "monthly"), false);
assert.equal(context.windowMatches({ windowSeconds: 32 * DAY }, "monthly"), false);
assert.equal(context.windowMatches({ windowSeconds: 31 * DAY }, "weekly"), false);
assert.equal(context.rowPeriodTag({ windowSeconds: 31 * DAY }), "30d");
assert.equal(context.exactRemainingForWindow({ id: "ollama", status: "ok",
  windows: [{ id: "monthly", label: "Monthly limit", windowSeconds: 2678400, remaining: 55 }] }, "monthly"), 55,
  "the Monthly menu bar choice finds a 31-day month");

const early = context.paceForWindow(weekly(30, [[NOW - 60, 30]], WEEK - 1000), NOW);
assert.equal(early.known, false, "under 2% elapsed there is no pace");
assert.equal(context.paceStatusText(early), "Pace starts after 2% of the window");

const unused = context.paceForWindow(weekly(0, holding(weekStart, NOW, 0)), NOW);
assert.equal(unused.state, "no-usage");
assert.equal(unused.runsOut, false);
assert.equal(context.paceText(unused), "");
assert.equal(context.paceTickText(unused), "", "no usage, no tick");
assert.equal(context.paceStatusText(unused), "No usage yet");

// Weekly limits: the window's average blended with the last day.
const noHistory = context.paceForWindow({ used: 60, windowSeconds: WEEK, resetsAt: NOW + WEEK / 2 }, NOW);
assert.equal(noHistory.method, "average");
assert.equal(noHistory.state, "projecting", "a weekly limit projects from its own average, even on the first refresh");
assert.equal(noHistory.runsOut, true, "60% used halfway through the week runs out before reset at that average");

// Used early, then quiet for three days: the quiet last day halves the rate, so it lasts.
const quietSince = NOW - 3 * DAY;
const dormant = context.paceForWindow(weekly(60, [
  ...linear(weekStart, quietSince, 60),
  ...holding(quietSince + 900, NOW, 60),
]), NOW);
assert.equal(dormant.state, "projecting");
assert.equal(dormant.runsOut, false, "a quiet last day pulls a heavy start back under the reset");

// One busy hour in a calm week does not predict a weekly run-out.
const busyHour = context.paceForWindow(weekly(20, [
  ...holding(weekStart, NOW - HOUR, 10),
  [NOW - 2700, 12.5], [NOW - 1800, 15], [NOW - 900, 17.5], [NOW, 20],
]), NOW);
assert.equal(busyHour.state, "projecting");
assert.equal(busyHour.runsOut, false, "a single burst is not a weekly trend");

// A heavy, steady week does run out, and the badge agrees: ahead of pace.
const heavy = context.paceForWindow(weekly(70, linear(weekStart, NOW, 70)), NOW);
assert.equal(heavy.runsOut, true);
assert.ok(heavy.etaSeconds > DAY && heavy.etaSeconds < 2 * DAY, "70% in 3.5 days leaves about a day and a half");
assert.ok(context.paceBadgeText(heavy).endsWith("ahead"));
assert.ok(context.paceTickText(heavy).includes("At this window's pace: runs out in"));

// A steady burn that empties the window exactly at reset is not a run-out.
const steady = context.paceForWindow(weekly(40, linear(weekStart, NOW, 40)), NOW);
assert.equal(steady.state, "projecting");
assert.equal(steady.runsOut, false, "a steady burn that lasts until reset is not a run-out");

// The first day of a week averages over a whole day, so an early session does not alarm.
const firstHours = context.paceForWindow(weekly(8, [], WEEK - 4 * HOUR), NOW);
assert.equal(firstHours.runsOut, false, "8% in the first four hours is a day's use, not a run-out");

// Five-hour limits: the recent rate of the window's own samples.
const burst = context.paceForWindow(session(50, [
  ...holding(sessionStart, NOW - HOUR, 10, 300),
  [NOW - 2700, 20], [NOW - 1800, 30], [NOW - 900, 40], [NOW, 50],
]), NOW);
assert.equal(burst.method, "recent");
assert.equal(burst.state, "projecting");
assert.equal(burst.runsOut, true, "a session follows its recent rate");
assert.ok(burst.etaSeconds > 0 && burst.etaSeconds < SESSION / 2);
assert.equal(context.paceStatusText(burst), context.paceText(burst), "a drawn tick reports the same line as paceText");
assert.ok(context.paceTickText(burst).includes("At your recent rate: runs out in"));

// The meter, tick, and pace tooltip follow the chosen side; the ahead/behind verdict is the same on either side.
assert.equal(context.meterFill({ used: 20 }, "Used"), 0.2);
assert.equal(context.meterFill({ used: 20 }, "Remaining"), 0.8);
assert.equal(context.meterFill({ remaining: 80 }, "Used"), 0.2, "a remaining-only row fills the used side too");
assert.equal(context.meterFill(null, "Remaining"), null);
assert.equal(context.meterMark(burst, "Used"), burst.expected / 100);
assert.equal(context.meterMark(burst, "Remaining"), (100 - burst.expected) / 100);
assert.equal(context.meterMark(null, "Remaining"), -1, "no pace, no tick on either side");
assert.ok(context.paceTickText(burst, "Remaining").startsWith("Left 50%"), "the tooltip names the side it shows");
assert.ok(context.paceText(burst, "Remaining").endsWith("% left"), "the expected share names its side");
assert.equal(context.paceText(burst, "Used").endsWith("% left"), false);

// A session that has gone quiet is idle: tick, no projection.
const quietSession = context.paceForWindow(session(30, [
  ...linear(sessionStart, NOW - 75 * 60, 30, 300),
  ...holding(NOW - 70 * 60, NOW, 30, 300),
]), NOW);
assert.equal(quietSession.state, "idle");
assert.equal(quietSession.runsOut, false);
assert.equal(context.paceShowsMark(quietSession), true, "an idle window keeps its tick");
assert.ok(context.paceText(quietSession).startsWith("Idle "));

// Too little observed time: the tick and badge stay (they need only the clock); the projection waits.
const fresh = context.paceForWindow(session(20, [[NOW - 300, 20], [NOW, 20]]), NOW);
assert.equal(fresh.state, "collecting");
assert.equal(context.paceShowsMark(fresh), true, "collecting keeps the tick and the ahead/behind badge");
assert.ok(context.paceText(fresh).startsWith("Collecting data · pace "));
assert.ok(context.paceTickText(fresh).includes("Collecting samples"));

// A gap longer than an hour is unobserved: the rise across it is neither a rate nor idle time.
const gapped = context.paceForWindow(session(20, [[NOW - 4000, 10], [NOW - 100, 20]]), NOW);
assert.equal(gapped.state, "collecting");
assert.equal(gapped.observedSeconds, 100);

// Newest sample older than an hour: stale, not idle. The tick stays; no projection is trusted.
const silent = context.paceForWindow(session(60, holding(sessionStart, NOW - 2 * HOUR, 60, 300)), NOW);
assert.equal(silent.state, "stale");
assert.equal(context.paceShowsMark(silent), true);
assert.ok(context.paceText(silent).startsWith("No recent data · pace "));

// Usage recorded before the window started is not a rise inside it.
const previous = context.paceForWindow(session(5, [[sessionStart - HOUR, 90], ...holding(sessionStart, NOW, 5, 300)]), NOW);
assert.equal(previous.state, "idle", "the earlier window's 90% does not start a burn");
assert.equal(previous.runsOut, false);

// Quickshell can hand over lists with length and index access that fail Array.isArray(). They must read
// exactly like plain arrays; a sample list that looks empty to the reader would show "No recent data".
const asArrayLike = (items) => Object.assign({ length: items.length }, items);
const steadySamples = linear(sessionStart, NOW, 40, 300);
const listSamples = asArrayLike(steadySamples.map(asArrayLike));
assert.equal(Array.isArray(listSamples), false);
assert.equal(Array.isArray(listSamples[0]), false);
const plainBurn = context.recentBurn(steadySamples, 40, NOW, sessionStart);
const listBurn = context.recentBurn(listSamples, 40, NOW, sessionStart);
assert.notEqual(listBurn, null, "array-like samples are read, not treated as missing");
assert.ok(listBurn.percentPerSecond > 0, "array-like samples carry the same burn");
assert.deepEqual(listBurn, plainBurn);
const listPace = context.paceForWindow(session(40, listSamples), NOW);
assert.equal(listPace.state, "projecting", "array-like samples project a run-out or a steady burn");
assert.deepEqual(listPace, context.paceForWindow(session(40, steadySamples), NOW));
const weeklyList = context.paceForWindow(weekly(40, asArrayLike(linear(weekStart, NOW, 40).map(asArrayLike))), NOW);
assert.deepEqual(weeklyList, context.paceForWindow(weekly(40, linear(weekStart, NOW, 40)), NOW), "the last-day rate reads array-like samples too");

const exhausted = context.paceForWindow(weekly(140, holding(weekStart, NOW, 100)), NOW);
assert.equal(exhausted.used, 100, "used clamps before projecting");
assert.equal(exhausted.state, "exhausted");
assert.equal(context.paceText(exhausted), "Limit reached");
assert.equal(context.paceShowsMark(exhausted), false, "an exhausted window has no tick");

assert.equal(context.paceText(null), "");
const kimiOrder = context.orderedWindows([
  { id: "weekly", windowSeconds: 604800 },
  { id: "extra" },
  { id: "session", windowSeconds: 18000 },
  { id: "opus", windowSeconds: 604800 },
]).map((row) => row.id).join(",");
assert.equal(kimiOrder, "session,weekly,opus,extra", "shortest window first; ties and untimed rows keep their order");
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

// Provider colours: one per provider, all different, and mid-tones a chip can use on dark and on light
// bars (contrast against white and against a dark bar). Unknown ids fall back, including prototype keys.
const luminance = (hex) => {
  const channel = (offset) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
};
const brandColors = context.LOCAL_PROVIDER_IDS.map((id) => context.providerAccent(id, null));
assert.ok(brandColors.every((color) => /^#[0-9a-f]{6}$/.test(color)), "every provider has a colour");
assert.equal(new Set(brandColors).size, context.LOCAL_PROVIDER_IDS.length, "no two providers share a colour");
for (const id of context.LOCAL_PROVIDER_IDS) {
  const shade = luminance(context.providerAccent(id, null));
  assert.ok(1.05 / (shade + 0.05) >= 1.9 && (shade + 0.05) / (luminance("#16161e") + 0.05) >= 3.4, id + " reads on light and dark bars");
}
assert.equal(context.providerAccent("local-codex", "#ffffff"), "#ffffff")
assert.equal(context.providerAccent("", "#ffffff"), "#ffffff")
assert.equal(context.providerAccent("constructor", "#ffffff"), "#ffffff")

// Money providers (OpenRouter): what can be spent, its alert level, and how long it lasts.
const wallet = (spendable, extra = {}) => ({ id: "openrouter", status: "ok", windows: [],
  credits: { currency: "USD", spendable, remaining: null, ...extra } });
assert.equal(context.spendable(wallet(17.5)), 17.5);
assert.equal(context.spendable(wallet(-2)), 0, "an overdrawn allowance reads as nothing left");
assert.equal(context.spendable(wallet(null)), null, "spend without a balance or limit has no figure");
assert.equal(context.spendable({ id: "codex", credits: { currency: "", remaining: 5 } }), null, "credit counts are not money");
assert.equal(context.barProviders([wallet(4)], "auto").length, 1, "a balance alone earns a chip");
assert.equal(context.barProviders([wallet(null)], "auto").length, 0);
assert.equal(context.moneySeverity(5, 5, 1), "warning", "the warning amount itself warns");
assert.equal(context.moneySeverity(1, 5, 1), "critical");
assert.equal(context.moneySeverity(5.01, 5, 1), "ok");
assert.equal(context.moneySeverity(null, 5, 1), "none");
const wednesdayNoon = Date.UTC(2026, 9, 14, 12) / 1000; // 2.5 days into the UTC week
assert.equal(context.moneyRunway(30, 10, wednesdayNoon), "about 8 days", "$10 over 2.5 days is $4 a day");
assert.equal(context.moneyRunway(100, 5, wednesdayNoon), "about 7 weeks");
assert.equal(context.moneyRunway(1, 10, wednesdayNoon), "less than a day");
assert.equal(context.moneyRunway(30, 0, wednesdayNoon), "", "no spend this week, no runway");
assert.equal(context.moneyRunway(30, 10, Date.UTC(2026, 9, 12, 2) / 1000), "", "too early in the week to project");
assert.equal(context.rowPeriodTag({ windowSeconds: 86400 }), "1d");
assert.equal(context.rowPeriodTag({ windowSeconds: 2592000 }), "30d");
assert.equal(context.rowPeriodTag({ id: "x" }), "");

// Used-up weekly or monthly limits hide a chip on request; short limits refill soon and never do.
const usedUp = (rows) => ({ id: "codex", status: "ok", windows: rows });
assert.equal(context.usedUpLongWindow(usedUp([{ id: "session", remaining: 0, windowSeconds: 18000 }])), null, "a used-up 5-hour limit refills soon");
assert.equal(context.usedUpLongWindow(usedUp([{ id: "weekly", remaining: 0.4, windowSeconds: 604800 }])), null, "a little left is not used up");
assert.equal(context.usedUpLongWindow(usedUp([{ id: "weekly", remaining: 0, windowSeconds: 604800, resetsAt: 9 }])).resetsAt, 9);
assert.equal(context.usedUpLongWindow(usedUp([{ id: "monthly", label: "Monthly limit", remaining: 0 }])).id, "monthly", "an untimed monthly row counts by its name");
assert.equal(context.usedUpLongWindow(usedUp([
  { id: "monthly", remaining: 0, windowSeconds: 2592000, resetsAt: 50 },
  { id: "weekly", remaining: 0, windowSeconds: 604800, resetsAt: 20 },
])).id, "weekly", "the soonest return is reported");
assert.equal(context.usedUpLongWindow({ ...usedUp([{ id: "weekly", remaining: 0, windowSeconds: 604800 }]), status: "error" }), null);

// Money follows Show limits as, against whichever allowance binds.
const balanceBound = { id: "openrouter", status: "ok", windows: [],
  credits: { currency: "USD", spendable: 1.58, remaining: 1.58, total: 75, used: 73.42 } };
const usedView = context.moneyView(balanceBound, "Used");
assert.equal(usedView.unit, "used");
assert.equal(usedView.amount.toFixed(2), "73.42");
assert.equal(Math.round(usedView.share), 98);
assert.equal(context.moneyView(balanceBound, "Remaining").amount, 1.58);
const limitBound = { id: "openrouter", status: "ok",
  windows: [{ unit: "usd", remainingAmount: 4, limitAmount: 10, remaining: 40 }],
  credits: { currency: "USD", spendable: 4, remaining: 50, total: 60 } };
assert.equal(context.moneyView(limitBound, "Used").amount, 6, "a key limit holding back spending is the allowance shown");
assert.equal(context.moneyView(limitBound, "Used").total, 10);
const unknownSize = { id: "openrouter", status: "ok", windows: [], credits: { currency: "USD", spendable: 4, remaining: null } };
assert.equal(context.moneyView(unknownSize, "Used").unit, "left", "without the allowance's size, used cannot be told");
assert.equal(usedView.text, "$73.42", "the view carries the figure formatted in its currency");
const yuan = { id: "deepseek", status: "ok", windows: [], credits: { currency: "CNY", spendable: 80, remaining: 80, total: null } };
assert.equal(context.spendable(yuan), 80, "a balance in another currency still counts as money");
assert.equal(context.moneyView(yuan, "Used").text, "¥80.00", "DeepSeek balances show in their own currency");
assert.equal(context.moneyCurrency(yuan), "CNY");
assert.equal(context.moneyCurrency({ id: "claude" }), "USD", "providers without money default to dollars");
assert.equal(context.formatMoney(1234.5, "EUR"), "€1,234.50");
assert.equal(context.formatMoney(-0.004, "USD"), "-$0.0040");
assert.equal(context.formatMoney(3, "CHF"), "CHF 3.00", "an unknown currency keeps its code");
assert.equal(context.formatMoney(2345678, "POINTS"), "2.35M points", "a points balance stays short on a chip");
assert.equal(context.formatMoney(850, "CREDITS"), "850 credits");
assert.equal(context.formatMoney(12.5, "credits"), "12.5 credits");
assert.equal(context.formatMoney(-3, "POINTS"), "-3 points");
assert.equal(context.providerShortName({ id: "openrouter", name: "OpenRouter" }), "OpenRouter");
assert.equal(context.providerShortName({ id: "claude", name: "Claude Code" }), "Claude");
assert.equal(context.providerShortName({ id: "gemini-cli", name: "Gemini CLI" }), "Gemini CLI", "proxy providers keep their name");


// Per-provider "Show limits as" overrides follow the global choice unless set.
assert.equal(context.quotaModeFor("{}", "claude", "Used"), "Used");
assert.equal(context.quotaModeFor("{}", "claude", "Remaining"), "Remaining");
const modes = context.setQuotaMode("{}", "claude", "Remaining");
assert.equal(context.quotaModeFor(modes, "claude", "Used"), "Remaining", "an override wins over the global choice");
assert.equal(context.quotaModeFor(modes, "codex", "Used"), "Used", "other providers keep the global choice");
assert.equal(context.setQuotaMode(modes, "claude", "default"), "{}", "default removes the override");
assert.equal(context.setQuotaMode(modes, "claude", "bogus"), modes, "unknown values change nothing");
assert.deepEqual(Object.keys(context.parseQuotaModes('{"claude":"Remaining","kimi":"nope","x":1}')), ["claude"], "only canonical values are kept");
assert.equal(context.quotaModeFor("not json", "claude", "Remaining"), "Remaining", "unreadable overrides fall back to the global choice");
assert.equal(context.quotaModeLabel("Remaining"), "Left (%)");
console.log("Per-provider quota modes: passed");

// Provider order: listed ids first, the rest after in their natural order; moves keep the full list.
const sample = [{ id: "claude" }, { id: "codex" }, { id: "kimi" }, { id: "opencode" }];
assert.equal(context.orderProviders(sample, "[]").map(p => p.id).join(","), "claude,codex,kimi,opencode");
assert.equal(context.orderProviders(sample, '["kimi","claude"]').map(p => p.id).join(","), "kimi,claude,codex,opencode", "unlisted providers follow the listed ones");
assert.equal(context.orderProviders(sample, '["ghost","codex"]').map(p => p.id).join(","), "codex,claude,kimi,opencode", "ids that are not present are ignored");
assert.equal(context.orderProviders(sample, "nope").map(p => p.id).join(","), "claude,codex,kimi,opencode", "unreadable order keeps the natural order");
assert.equal(context.parseProviderOrder('["codex","codex","Bad Id",3]').join(","), "codex", "duplicates and invalid ids are dropped");
console.log("Provider order: passed");

// Reset restores exactly what a fresh install gets: the registry matches manifest.json.
const manifestDefaults = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "manifest.json"), "utf8")).barWidget.defaults;
for (const key of Object.keys(context.DEFAULT_SETTINGS))
  assert.equal(JSON.stringify(context.DEFAULT_SETTINGS[key]), JSON.stringify(manifestDefaults[key]), "reset default for " + key + " matches the manifest");
const keyFileSettings = context.KEY_PROVIDER_IDS.map((id) => id + "KeyFile");
for (const kept of ["usageSource", "cliproxyUrl", "cliproxyKeyFile", ...keyFileSettings, "costKeeperUrl", "costKeeperPasswordFile", "costT3Servers", "costPriceOverrides"])
  assert.ok(!(kept in context.DEFAULT_SETTINGS), kept + " survives a reset");
assert.equal(context.changedFromDefaults({}).length, 0, "missing keys already read as defaults");
assert.equal(context.changedFromDefaults({ quotaMode: "Remaining", barWindow: "auto", usageSource: "cliproxy" }).join(","), "quotaMode",
  "only preferences that differ count; connections never do");
console.log("Reset defaults: passed");

// The provider registry: every provider once, set up one of three ways, offered by name in the
// manifest's provider lists. Sign-in providers are monitored by default; every provider gets a chip.
const widget = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "manifest.json"), "utf8")).barWidget;
const schema = Object.fromEntries(widget.schema.map((entry) => [entry.key, entry]));
const registry = [...context.LOCAL_PROVIDERS];
const registryIds = registry.map((entry) => entry.id);
for (const key of ["enabledProviders", "barProviders", "dismissedProviders"])
  assert.equal(JSON.stringify(schema[key].options), JSON.stringify(registry.map((entry) => ({ value: entry.id, label: entry.name }))),
    key + " offers every provider by name, in order");
assert.equal(context.DEFAULT_SETTINGS.enabledProviders.join(","), registry.filter((entry) => entry.auth !== "key").map((entry) => entry.id).join(","),
  "every provider with a sign-in of its own is monitored by default");
assert.equal(context.DEFAULT_SETTINGS.barProviders.join(","), registryIds.join(","), "every monitored provider gets a chip");
assert.equal(context.KEY_PROVIDER_IDS.join(","), registry.filter((entry) => entry.auth !== "signin").map((entry) => entry.id).join(","));
for (const entry of registry) {
  assert.ok(["signin", "key", "both"].includes(entry.auth), entry.id + " is set up by sign-in, key, or both");
  assert.ok(entry.name && entry.short && entry.signIn, entry.id + " has a name, a short name, and a setup hint");
  assert.equal(typeof entry.money, "boolean");
  assert.equal(typeof entry.lightIcon, "boolean");
  assert.ok(entry.keysUrl === "" || /^https:\/\/\S+$/.test(entry.keysUrl), entry.id + " links to an https key page");
  if (entry.auth !== "signin") {
    assert.match(entry.keyEnv, /^[A-Z][A-Z0-9_]*$/, entry.id + " names the environment variable that wins over a saved key");
    assert.equal(manifestDefaults[entry.id + "KeyFile"], "", entry.id + " has a key file setting");
  }
}
console.log("Provider registry: passed");

// Settings → Providers places every provider exactly once from the last refresh.
const settingsReadings = [
  { id: "claude", status: "ok", plan: "Max" },
  { id: "codex", status: "error", errorKind: "expired" },
  { id: "gemini", status: "error", errorKind: "no_credentials" },
  { id: "amp", status: "error", errorKind: "no_credentials" },
  { id: "kimi", status: "error", errorKind: "no_credentials" },
  { id: "openrouter", status: "error", errorKind: "no_credentials" },
];
const placed = context.providerSections(context.orderProviders(context.LOCAL_PROVIDERS, '["codex"]'),
  ["claude", "codex", "gemini", "amp", "kimi", "openrouter", "cursor"], ["deepseek"], settingsReadings,
  ["kimi", "copilot", "deepseek"], { ampKeyFile: "/private/amp.key" });
const placedIds = (section) => placed[section].map((entry) => entry.id).join(",");
assert.equal(placedIds("listed"), "codex,claude,kimi,cursor,amp,openrouter",
  "rows: connected, failing, found here though signed out, not checked yet, keyed, and key-only, in the saved order");
assert.equal(placedIds("waiting"), "gemini", "a monitored sign-in that is not signed in waits out of sight");
assert.equal(placedIds("found"), "copilot", "set up here, not monitored, not dismissed");
assert.equal(placedIds("moreSignIns"), "opencode,antigravity,grok,kiro,jetbrains,nous,muse,factory,kilo,codebuff,huggingface");
assert.equal(placedIds("moreKeys"), "zai,minimax,synthetic,chutes,ollama,warp,zenmux,clinepass,alibaba,commandcode,devpass,xkiro,ibmbob,umans,"
  + "neuralwatt,aixy,clawrouter,deepseek,moonshot,venice,deepinfra,vercel,poe,atlascloud,hyper,sailresearch,sofya,v0,manus,typesafe",
  "a dismissed provider stays available under More providers");
assert.equal(["listed", "waiting", "found", "moreSignIns", "moreKeys"].reduce((total, section) => total + placed[section].length, 0),
  registryIds.length, "no provider is listed twice or lost");
assert.equal(context.foundProviders(["poe", "gemini", "claude"], ["claude"], ["poe"]).map((entry) => entry.id).join(","), "gemini");

// The status line under a monitored provider: what the last check found and what to do.
const statusOf = (id, reading, hasKey = false, checking = false) => context.providerStatus(context.localProvider(id), reading, hasKey, checking);
assert.equal(statusOf("claude", { status: "ok", plan: "Max" }).text, "Connected · Max");
assert.equal(statusOf("claude", { status: "ok", plan: "" }).text, "Connected");
assert.equal(statusOf("claude", { status: "ok" }).tone, "ok");
assert.equal(statusOf("gemini", { status: "error", errorKind: "no_credentials" }).text, "Not signed in — " + context.localProvider("gemini").signIn);
assert.equal(statusOf("gemini", { status: "error", errorKind: "no_credentials" }).tone, "muted", "not signed in is not an error");
assert.equal(statusOf("openrouter", { status: "error", errorKind: "no_credentials" }).text, "No key saved");
assert.equal(statusOf("openrouter", { status: "error", errorKind: "no_credentials" }, true, true).text, "Checking…",
  "a reading from before the key was saved is not shown as missing");
assert.equal(statusOf("claude", { status: "error", errorKind: "expired" }).text, "Sign-in expired — " + context.localProvider("claude").signIn);
assert.equal(statusOf("claude", { status: "error", errorKind: "expired" }).tone, "error");
assert.equal(statusOf("deepseek", { status: "error", errorKind: "expired" }).text, "Key rejected");
assert.equal(statusOf("amp", { status: "error", errorKind: "expired" }, true).text, "Key rejected", "a saved key is what was rejected");
assert.equal(statusOf("amp", { status: "error", errorKind: "expired" }).text, "Sign-in expired — " + context.localProvider("amp").signIn);
assert.equal(statusOf("poe", { status: "error", errorKind: "timeout", message: "The provider did not answer in time." }).text,
  "The provider did not answer in time.", "other failures show the backend's short message");
assert.equal(statusOf("poe", { status: "error", errorKind: "rate_limited" }).text, "Rate limited");
assert.equal(statusOf("poe", { status: "error", errorKind: "constructor" }).text, "Error", "unknown kinds stay generic");
assert.equal(statusOf("poe", null, false, true).text, "Checking…");
assert.equal(statusOf("poe", null).text, "Not checked yet");

// Monitor switches keep the registry order; keys, filters, and the Limits pointer read the registry.
assert.equal(context.withMember(["codex"], "claude", true, context.LOCAL_PROVIDER_IDS).join(","), "claude,codex", "added in registry order");
assert.equal(context.withMember(["claude", "codex"], "claude", false, context.LOCAL_PROVIDER_IDS).join(","), "codex");
assert.equal(context.withMember(["ghost", "codex"], "kimi", true, context.LOCAL_PROVIDER_IDS).join(","), "codex,kimi", "ids the registry does not know are dropped");
assert.equal(context.keySaved({ poeKeyFile: "/private/poe.key" }, "poe"), true);
assert.equal(context.keySaved({ poeKeyFile: " " }, "poe"), false);
assert.equal(context.keySaved(null, "poe"), false);
assert.equal(context.keyHint(context.localProvider("openrouter")), "OPENROUTER_API_KEY in the environment takes precedence.");
assert.equal(context.keyHint(context.localProvider("amp")), "Optional: used instead of the sign-in. AMP_API_KEY in the environment takes precedence.");
assert.equal(context.filterProviders(context.LOCAL_PROVIDERS, " DEEP ").map((entry) => entry.id).join(","), "deepseek,deepinfra");
assert.equal(context.filterProviders(context.LOCAL_PROVIDERS, "copilot").map((entry) => entry.id).join(","), "copilot");
assert.equal(context.filterProviders(context.LOCAL_PROVIDERS, "").length, registryIds.length);
assert.equal(context.joinNames(["A"]), "A");
assert.equal(context.joinNames(["A", "B", "C"]), "A, B and C");
const providerEntries = (...ids) => ids.map((id) => context.localProvider(id));
assert.equal(context.foundSummary([]), "", "nothing found, no line");
assert.equal(context.foundSummary(providerEntries("gemini", "copilot")), "Gemini CLI and GitHub Copilot found on this computer");
assert.equal(context.foundSummary(providerEntries("gemini", "copilot", "cursor")), "Gemini CLI, GitHub Copilot and Cursor found on this computer");
assert.equal(context.foundSummary(providerEntries("gemini", "copilot", "cursor", "kiro")), "Gemini CLI, GitHub Copilot and 2 more found on this computer");
console.log("Provider settings: passed");

// Chips in the bar: the providers closest to a limit stay, in their usual order; the rest fold away.
const chipRow = (id, remaining) => ({ id, remaining });
const chipPressure = (row) => row.remaining;
const chipIds = (rows) => Array.from(rows, (row) => row.id);
const chipRows = [chipRow("claude", 80), chipRow("codex", 5), chipRow("gemini", 60), chipRow("copilot", 30), chipRow("cursor", 90)];
const capped = context.limitChips(chipRows, 3, chipPressure);
assert.deepEqual(chipIds(capped.shown), ["codex", "gemini", "copilot"], "the three under most pressure, in bar order");
assert.deepEqual(chipIds(capped.hidden), ["claude", "cursor"], "the rest go to the overflow chip");
assert.deepEqual(chipIds(context.limitChips(chipRows, 0, chipPressure).shown), chipIds(chipRows), "0 shows every chip");
assert.equal(context.limitChips(chipRows, 5, chipPressure).hidden.length, 0, "a cap the bar does not reach hides nothing");
assert.deepEqual(chipIds(context.limitChips([chipRow("a", 50), chipRow("b", 50), chipRow("c", 50)], 2, chipPressure).shown),
  ["a", "b"], "ties keep the earlier provider, so chips do not shuffle");
assert.deepEqual(chipIds(context.limitChips([chipRow("a", null), chipRow("b", 40)], 1, (row) => row.remaining === null ? NaN : row.remaining).shown),
  ["b"], "unknown pressure counts as untouched");
console.log("Chip cap: passed");

// One-click setup: sign in with the CLI that is there, install it with mise and sign in, or link out.
const entryOf = (id) => context.localProvider(id);
const signedOut = { status: "error", errorKind: "no_credentials" };
assert.equal(context.setupAction(entryOf("gemini"), signedOut, ["gemini"]).kind, "signin");
assert.equal(context.setupAction(entryOf("gemini"), signedOut, ["gemini"]).command, entryOf("gemini").login);
assert.equal(context.setupAction(entryOf("gemini"), { status: "error", errorKind: "expired" }, ["gemini"]).kind, "signin", "an expired sign-in is fixed the same way");
const install = context.setupAction(entryOf("gemini"), signedOut, []);
assert.equal(install.kind, "install", "a missing CLI with a mise package installs, then signs in");
assert.equal(install.command, "mise use -g " + entryOf("gemini").mise + " && " + entryOf("gemini").login);
assert.equal(context.setupAction(entryOf("kiro"), signedOut, []).kind, "link", "no mise package: link to where the tool comes from");
assert.equal(context.setupAction(entryOf("kiro"), signedOut, []).url, entryOf("kiro").installUrl);
assert.equal(context.setupAction(entryOf("gemini"), signedOut, null).kind, "signin", "before the backend says, the CLI is assumed present");
assert.equal(context.setupAction(entryOf("gemini"), { status: "ok" }, ["gemini"]).kind, "", "a connected provider offers nothing");
assert.equal(context.setupAction(entryOf("gemini"), { status: "error", errorKind: "timeout" }, ["gemini"]).kind, "", "other failures are not fixed by signing in");
assert.equal(context.setupAction(entryOf("zai"), null, []).kind, "", "API-key providers are set up with a key, not a sign-in");
assert.equal(context.setupAction(entryOf("jetbrains"), signedOut, []).kind, "link", "an IDE is got, not signed in to");
assert.equal(context.providerStatus(entryOf("gemini"), { status: "error", errorKind: "expired" }, false, false, true).text,
  "Sign-in expired", "beside a Sign in button the status drops the instruction");
console.log("Provider setup: passed");

console.log("UsageLogic.js: all assertions passed");
