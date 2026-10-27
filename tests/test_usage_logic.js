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
assert.equal(context.availableProviders(null).length, 0);
assert.equal(discovered.length, 5, "filtering does not change backend discovery");

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
assert.equal(context.accountResetLabel({ ...resetAccount, id: "claude" }), "2 banked resets");
assert.equal(context.accountResetLabel({ ...resetAccount, id: "claude", credits: { resetCreditsAvailable: 0 } }), "",
  "Claude shows its banked resets only while it has one");
assert.equal(context.accountResetLabel({ ...resetAccount, id: "kimi" }), "");
assert.equal(context.accountResetLabel({ ...resetAccount, status: "disabled" }), "");

// Where a banked reset can be applied from: Codex through the proxy only; Claude with its own sign-in or the
// proxy, when Claude lets the next one be spent now; never an account whose sign-in lives in omp.
{
  const claude = (credits, extra) => ({ ...provider("claude", 40), credits: { resetCreditsAvailable: 1, ...credits }, ...extra });
  const usable = claude({ resetCreditsUsable: true, resetCreditsReason: "" });
  assert.equal(context.accountResetShown(usable), true);
  assert.equal(context.accountResetActionable(usable), true, "a Claude Code sign-in applies its own reset");
  assert.equal(context.accountResetActionable(usable), true);
  assert.equal(context.accountResetNote(usable), "");
  const waiting = claude({ resetCreditsUsable: false, resetCreditsReason: "limit" });
  assert.equal(context.accountResetActionable(waiting), false);
  assert.equal(context.accountResetNote(waiting), "Usable once you reach a limit.");
  assert.equal(context.accountResetNote(claude({ resetCreditsUsable: false, resetCreditsReason: "surprise" })),
    "Claude is not offering it right now.", "an unknown reason reads as not offered");
  const viaOmp = claude({ resetCreditsUsable: true }, { origin: "omp" });
  assert.equal(context.accountResetActionable(viaOmp), false, "omp keeps that sign-in");
  assert.equal(context.accountResetNote(viaOmp), "Apply it in omp: omp usage reset.");
  assert.equal(context.accountResetActionable(claude({})), false, "a count from omp alone is not usable here");
  assert.equal(context.accountResetShown(resetAccount), false, "Codex resets show when read through CLIProxyAPI");
  const throughProxy = { ...resetAccount, proxy: { id: "p-00000001", name: "CLIProxyAPI" } };
  assert.equal(context.accountResetActionable(throughProxy), true);
  assert.equal(context.accountResetActionable({ ...resetAccount, standIn: { id: "p-00000001", name: "CLIProxyAPI" } }), true,
    "a proxy's reading standing in for a failed one is applied through the proxy");
  assert.equal(context.accountResetActionable({ ...throughProxy, origin: "omp" }), false);
  assert.equal(context.accountResetActionable({ ...throughProxy, credits: { resetCreditsAvailable: 0 } }), false);
  const elsewhere = claude({ resetCreditsUsable: true }, { computer: { id: "c-00000001", name: "devbox" } });
  assert.deepEqual([context.accountResetActionable(elsewhere), context.accountResetNote(elsewhere)],
    [false, "Its sign-in is on devbox: apply it there."]);
  assert.equal(context.creditsHaveFunds(usable.credits), false);
  assert.equal(context.creditsHaveFunds({ used: 4, limit: 50, resetCreditsAvailable: 1 }), true);
}

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

// The shared live-connection registry (omp-live.py): one object per key, stopped by its last consumer.
let created = 0, stopped = 0;
const factory = { createObject(parent) { assert.equal(parent,null); created++; return {
  stop() { stopped++; }
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

// Shared number formatting.
assert.equal(context.formatTokens(8166), "8.17K");
assert.equal(context.formatTokens(0), "0");
assert.equal(context.formatTokens(null), "0");
assert.equal(context.formatTokens(2_500_000), "2.50M");
assert.equal(context.formatUsd(0.00122625), "$0.0012");
assert.equal(context.formatUsd(12.345), "$12.35");
assert.equal(context.formatUsd(null), "—");

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
assert.equal(context.notificationBody('Running low: 3 <img src="http://127.0.0.1:9/x"> & <b>more</b> left'),
  "Running low: 3 &lt;img src=\"http://127.0.0.1:9/x\"&gt; &amp; &lt;b&gt;more&lt;/b&gt; left",
  "a notification body's markup reaches the server escaped, ampersands first");
assert.equal(context.notificationBody("&lt;"), "&amp;lt;", "an entity in provider text stays the characters it was");
{
  const crossing = (severity, name) => ({ severity, title: name, remaining: severity === "critical" ? 4 : 18, mode: "Remaining" });
  const swings = ["warning", "critical", "warning", "critical", "critical", "warning"].map((severity, i) => crossing(severity, "Window " + i));
  const sent = context.limitNotifications(swings);
  assert.equal(sent.length, context.MAX_LIMIT_NOTIFICATIONS + 1, "a flood of crossings is a few notifications and a count");
  assert.deepEqual(sent.slice(0, 3).map((n) => [n.title, n.critical]), [["Window 1", true], ["Window 3", true], ["Window 4", true]],
    "the worst crossings are the ones shown");
  assert.equal(sent[3].body, "3 more limits crossed a threshold.");
  assert.equal(context.limitNotifications(swings.slice(0, 3)).length, 3, "up to the cap, every crossing has its own");
}

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

// With several accounts only the used-up ones leave the bar; the provider goes once none is left.
const spentWeek = [{ id: "weekly", remaining: 0, windowSeconds: 604800 }];
const roomyWeek = [{ id: "weekly", remaining: 75, windowSeconds: 604800 }];
const spentAccount = { accountId: "a", status: "ok", windows: spentWeek };
const roomyAccount = { accountId: "b", status: "ok", windows: roomyWeek };
const pair = { id: "claude", status: "ok", windows: spentWeek, accounts: [spentAccount, roomyAccount] };
const trimmed = context.withoutUsedUpAccounts(pair);
assert.deepEqual(trimmed.accounts.map((account) => account.accountId), ["b"], "the used-up lead leaves, the other stays");
assert.equal(trimmed.windows, roomyWeek, "the provider's figures follow the account left");
assert.equal(pair.accounts.length, 2, "the reading itself is untouched");
assert.equal(context.withoutUsedUpAccounts({ ...pair, accounts: [spentAccount, { ...spentAccount, accountId: "c" }] }), null);
const roomyPair = { ...pair, windows: roomyWeek, accounts: [roomyAccount, { ...roomyAccount, accountId: "c" }] };
assert.equal(context.withoutUsedUpAccounts(roomyPair), roomyPair);
assert.equal(context.withoutUsedUpAccounts(usedUp(spentWeek)), null, "a single reading used up still hides");
assert.equal(context.withoutUsedUpAccounts({ ...pair, accounts: [{ ...spentAccount, status: "error" }, spentAccount] }).accounts.length, 1,
  "a failed account is not used up");

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
assert.equal(context.parseProviderOrder(JSON.stringify(Array.from({ length: 5000 }, (_, i) => "p" + i))).length,
  context.USAGE_LIST_LIMITS.providers, "a saved order keeps only as many ids as there can be providers");
console.log("Provider order: passed");

// What a helper prints is cut to the shell's item ceilings before anything builds a card, a row or a dot.
{
  const many = (count, make) => Array.from({ length: count }, (_, i) => make(i));
  const windows = (count) => many(count, (i) => ({ id: "w" + i, used: 1 }));
  const usage = context.boundUsagePayload({ schemaVersion: 1, providers: many(100, (i) => ({
    id: "p" + i, windows: windows(5000), accounts: many(100, (j) => ({ accountId: "a" + j, windows: windows(20) })) })) });
  const limits = context.USAGE_LIST_LIMITS;
  assert.equal(usage.providers.length, limits.providers);
  assert.ok(usage.providers.every((p) => p.windows.length === limits.windows && p.accounts.length === limits.accounts
    && p.accounts.every((a) => a.windows.length === limits.windows)), "every provider and account is cut");
  assert.equal(usage.providers[0].windows.map((w) => w.id).slice(0, 2).join(","), "w0,w1", "the helper's first items are kept");
  const small = { providers: [{ id: "claude", windows: [{ id: "session" }], accounts: null }] };
  assert.equal(JSON.stringify(context.boundUsagePayload(small)), JSON.stringify({ providers: [{ id: "claude", windows: [{ id: "session" }], accounts: null }] }),
    "a reply within the ceilings is left as it is");
  const cost = context.boundCostPayload({ providers: many(100, (i) => ({ id: "p" + i })), models: many(1000, (i) => ({ model: "m" + i })),
    periods: many(500, () => ({ providers: many(100, (i) => ({ id: "p" + i })) })), projects: many(100, () => ({})) });
  for (const field of ["providers", "models", "periods", "projects"])
    assert.equal(cost[field].length, context.COST_LIST_LIMITS[field], "cost " + field);
  assert.ok(cost.periods.every((period) => period.providers.length === context.COST_LIST_LIMITS.providers), "each period's providers");
  const credits = { credits: many(1000, (i) => ({ id: "c" + i })) };
  context.boundField(credits, "credits", context.RESET_CREDIT_LIMIT);
  assert.equal(credits.credits.length, context.RESET_CREDIT_LIMIT);
}
console.log("Helper item ceilings: passed");

// Reset restores exactly what a fresh install gets: the registry matches manifest.json.
const manifestDefaults = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "manifest.json"), "utf8")).barWidget.defaults;
for (const key of Object.keys(context.DEFAULT_SETTINGS))
  assert.equal(JSON.stringify(context.DEFAULT_SETTINGS[key]), JSON.stringify(manifestDefaults[key]), "reset default for " + key + " matches the manifest");
const keyFileSettings = context.KEY_PROVIDER_IDS.map((id) => id + "KeyFile");
for (const kept of ["sources", "mainComputer", ...keyFileSettings, "costPriceOverrides"])
  assert.ok(!(kept in context.DEFAULT_SETTINGS), kept + " survives a reset");
assert.equal(context.changedFromDefaults({}).length, 0, "missing keys already read as defaults");
assert.equal(context.changedFromDefaults({ quotaMode: "Remaining", barWindow: "auto", sources: '[{"id":"p-1a2b3c4d","kind":"proxy"}]' }).join(","), "quotaMode",
  "only preferences that differ count; connections never do");
assert.equal(context.DEFAULT_SETTINGS.barShowPeriods, true, "chips show their limit period by default");
assert.equal(context.changedFromDefaults({ barShowPeriods: false }).join(","), "barShowPeriods", "hiding the period is a preference Reset restores");
console.log("Reset defaults: passed");

// 2.0 moved the private folder: saved 1.x paths follow it, JSON settings included; nothing else changes.
const asJson = (value) => JSON.parse(JSON.stringify(value));
const legacyKey = "/home/u/.config/omarchy/model-usage/management-keys/k1";
assert.deepEqual(asJson(context.legacyPathSettings({
  openrouterKeyFile: legacyKey, factoryKeyFile: "/home/u/keys/f.key", refreshIntervalSec: 900,
  extraKeys: JSON.stringify({ zai: [{ id: "k-0123abcd", name: "Work", file: legacyKey }] }),
  sources: JSON.stringify([{ id: "t3-1", kind: "t3", name: "Lab", url: "https://t3.example", tokenFile: "/home/u/.config/omarchy/quotatank/k2" }]) })), {
  openrouterKeyFile: "/home/u/.config/omarchy/quotatank/management-keys/k1",
  extraKeys: JSON.stringify({ zai: [{ id: "k-0123abcd", name: "Work", file: "/home/u/.config/omarchy/quotatank/management-keys/k1" }] }) });
assert.deepEqual(asJson(context.legacyPathSettings({ cliproxyKeyFile: "/home/u/model-usage/k" })), {}, "only the omarchy folder moves");
assert.deepEqual(asJson(context.legacyPathSettings(null)), {});

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
  + "neuralwatt,aixy,clawrouter,deepseek,moonshot,venice,deepinfra,vercel,poe,atlascloud,hyper,sailresearch,sofya,v0,manus,typesafe,mimo",
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

// Several keys per provider: the setting round-trips, bad rows are dropped, and only monitored
// providers reach the backend.
let extra = context.addExtraKey("{}", "openrouter", { id: "k-0123abcd", label: "  Work  ", file: "/private/a.key" });
extra = context.addExtraKey(extra, "openrouter", { id: "k-89abcdef", label: "", file: "/private/b.key" });
extra = context.renamePrimaryKey(extra, "openrouter", "Personal");
assert.deepEqual([...context.extraKeysFor(extra, "openrouter").keys.map((key) => key.label)], ["Work", ""]);
assert.deepEqual([...context.extraKeyArguments(extra, ["openrouter"])],
  ["--extra-key", "openrouter=k-0123abcd=/private/a.key", "--extra-key", "openrouter=k-89abcdef=/private/b.key"]);
assert.deepEqual([...context.extraKeyArguments(extra, ["claude"])], [], "a provider that is not monitored passes no keys");
assert.equal(Object.keys(context.parseExtraKeys('{"openrouter":{"keys":[{"id":"bad","file":"/x"},{"id":"k-00000000","file":""}]},"claude":{"keys":[]}}')).length, 0,
  "rows without a valid id or file, and providers that take no key, are dropped");
assert.equal(context.extraKeysFor(context.removeExtraKey(extra, "openrouter", "k-0123abcd"), "openrouter").keys.length, 1);
assert.equal(context.extraKeysFor(context.removeExtraKey(context.renamePrimaryKey(context.removeExtraKey(extra, "openrouter", "k-0123abcd"),
  "openrouter", ""), "openrouter", "k-89abcdef"), "openrouter").keys.length, 0);
assert.match(context.newExtraKeyId(), /^k-[0-9a-f]{8}$/);
// Account cards: chosen names first, emails only when shown, numbered otherwise.
assert.equal(context.accountName({ id: "openrouter", accountId: "primary" }, extra, true, 1), "Personal");
assert.equal(context.accountName({ id: "openrouter", accountId: "k-89abcdef" }, extra, true, 3), "Key 3");
assert.equal(context.accountName({ id: "claude", label: "Work", active: true, account: "me@example.com" }, "{}", true, 2), "Work · in use");
assert.equal(context.accountName({ id: "claude", label: "Work", active: false, account: "me@example.com" }, "{}", false, 2), "Work · me@example.com");
assert.equal(context.accountName({ id: "codex", accountId: "0123456789abcdef", account: "proxy@example.com" }, "{}", true, 4), "Account 4");
assert.equal(context.accountName({ id: "codex", accountId: "0123456789abcdef", account: "proxy@example.com" }, "{}", false, 4), "proxy@example.com");
assert.deepEqual([...context.secretPaths({ poeKeyFile: "/k/poe.key", extraKeys: extra, refreshIntervalSec: 900,
  sources: JSON.stringify([
    { id: "p-1a2b3c4d", kind: "proxy", url: "https://proxy.example", keyFile: "/k/proxy.key", keeperUrl: "", keeperPasswordFile: "/k/keeper.key" },
    { id: "t3-1", kind: "t3", name: "Home", url: "https://t3.example", tokenFile: "/k/t3.key" }]) })].sort(),
  ["/k/keeper.key", "/k/poe.key", "/k/proxy.key", "/k/t3.key", "/private/a.key", "/private/b.key"]);
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

// ---- 1.9 QmlCosts ----
{
  const day = context.costBucketDate("2030-01-09");
  assert.equal(day.getFullYear() * 10000 + (day.getMonth() + 1) * 100 + day.getDate(), 20300109,
    "a day bucket is that calendar day where the user is, not UTC midnight");
  assert.equal(day.getHours(), 0);
  assert.equal(context.costBucketDate("garbage"), null);
  assert.equal(context.costBucketDate(""), null);
  assert.equal(context.costBucketKey("2030-01-09"), "d2030-01-09");
  assert.equal(context.costBucketKey("2030-01-15T10:27:13Z"), context.costBucketKey("2030-01-15T10:37:13Z"),
    "a rescan minutes later keeps every rolling hour bucket on its bar");
  assert.notEqual(context.costBucketKey("2030-01-15T10:27:13Z"), context.costBucketKey("2030-01-15T11:27:13Z"));
  assert.equal(context.costBucketKey("nonsense"), "");
  assert.equal(context.costDayName(new Date(2030, 0, 15)), "Tue");
  assert.equal(context.costMonthDay(new Date(2030, 0, 9)), "Jan 9");
  assert.equal(context.costPeriodPhrase(1), "24 h");
  assert.equal(context.costPeriodPhrase(30), "30 days");

  assert.equal(context.costDeltaText(context.costDelta(12.34, 10.46), 7), "▲ 18% vs previous 7 days");
  assert.equal(context.costDeltaText(context.costDelta(8, 10), 30), "▼ 20% vs previous 30 days");
  assert.equal(context.costDeltaText(context.costDelta(10, 10.04), 1), "Same as previous 24 h");
  assert.equal(context.costDeltaText(context.costDelta(1000, 1), 7), "▲ 99,900% vs previous 7 days");
  assert.equal(context.costDelta(5, null), null, "no previous window, no delta");
  assert.equal(context.costDelta(null, 5), null, "an unpriced total has no delta");
  assert.equal(context.costDelta(5, 0), null, "an empty previous window has no meaningful ratio");
  assert.equal(context.costDeltaText(null, 7), "");

  const dimensions = {
    models: [
      { provider: "codex", providerName: "OpenAI Codex", model: "gpt-5.6-sol", costUsd: 4.84, totalTokens: 1400000, basePricedRecords: 3 },
      { provider: "claude", providerName: "Claude Code", model: "claude-opus-4-6", costUsd: 7.5, totalTokens: 3800000, customPricedRecords: 2 },
      { provider: "kimi", providerName: "Kimi", model: "kimi-k2", costUsd: null, totalTokens: 9000000 },
      { provider: "kimi", providerName: "Kimi", model: "kimi-k2", costUsd: null, totalTokens: 1 }
    ],
    projects: [
      { id: "other", name: "Other", costUsd: 9, totalTokens: 10, records: 3 },
      { id: "a1", name: "web-shop", costUsd: 3, totalTokens: 5, records: 1 },
      { id: "b2", name: "billing-api", costUsd: 5, totalTokens: 5, records: 1375 }
    ],
    agents: [{ id: "subagent", costUsd: 2, totalTokens: 100, records: 4 }, { id: "main", costUsd: 6, totalTokens: 50, records: 9 }]
  };
  assert.equal(context.costBreakdownModes(dimensions).map(mode => mode.label).join(","), "Model,Project,Agent");
  assert.equal(context.costBreakdownModes({ models: [], projects: [] }).map(mode => mode.value).join(","), "model",
    "Project and Agent appear only when the payload has them");
  const models = context.costBreakdownRows(dimensions, "model", "cost");
  assert.equal(models.map(row => row.name).join(","), "claude-opus-4-6,gpt-5.6-sol,kimi-k2,kimi-k2", "largest cost first, unpriced last");
  assert.equal(models.map(row => row.context).join("|"),
    "Claude · custom prices|Codex · base rates|Kimi · pricing unavailable|Kimi · pricing unavailable",
    "model rows keep their pricing notes beside the provider's short name");
  assert.equal(context.costBreakdownRows({ models: [{ provider: "lab", providerName: "Lab server", model: "m", costUsd: 1, basePricedRecords: 1 }] },
    "model", "cost")[0].context, "Lab server · base rates", "a source outside the registry keeps its own name");
  assert.equal(new Set(models.map(row => row.key)).size, 4, "repeated models still get unique keys");
  assert.equal(models[0].fraction, 1);
  assert.equal(models[1].fraction.toFixed(4), (4.84 / 7.5).toFixed(4));
  assert.equal(models[2].fraction, 0);
  assert.equal(context.costBreakdownRows(dimensions, "model", "tokens")[0].name, "kimi-k2", "Tokens ranks by tokens, priced or not");
  const projects = context.costBreakdownRows(dimensions, "project", "cost");
  assert.equal(projects.map(row => row.name).join(","), "billing-api,web-shop,Other", "the folded Other folder stays last");
  assert.equal(projects[0].context + "|" + projects[1].context, "1,375 requests|1 request");
  const agents = context.costBreakdownRows(dimensions, "agent", "cost");
  assert.equal(agents.map(row => row.name + " · " + row.context).join("|"),
    "Main sessions · what you type|Subagents · tasks and workpools");

  const grid = fill => Array.from({ length: 7 }, (_, d) => Array.from({ length: 24 }, (_, h) => fill(d, h)));
  const days = ["2030-01-09", "2030-01-10", "2030-01-11", "2030-01-12", "2030-01-13", "2030-01-14", "2030-01-15"];
  const heatmap = {
    days,
    cost: grid((d, h) => (d === 6 && h === 15 ? 4.2 : d === 0 && h === 3 ? null : 1)),
    records: grid((d, h) => (d === 6 && h === 15 ? 63 : d === 0 && h === 3 ? 2 : 1))
  };
  const heat = context.costHeatmapGrid(heatmap, "cost");
  assert.equal(heat.cells.length, 168, "seven days of 24 hours");
  assert.equal(heat.dayNames.join(","), "Wed,Thu,Fri,Sat,Sun,Mon,Tue");
  assert.equal(heat.busiest, 6 * 24 + 15);
  assert.equal(heat.cells[heat.busiest].level, 1);
  assert.equal(heat.cells[0].level.toFixed(4), Math.sqrt(1 / 4.2).toFixed(4), "levels use a square-root scale");
  assert.ok(heat.cells[3].unpriced && heat.cells[3].level === 0, "only-unpriced hours are marked, not scaled");
  assert.equal(context.costHeatmapText(heat.cells[heat.busiest], "15:00"), "Tue 15:00 · $4.20 · 63 requests");
  assert.equal(context.costHeatmapText(heat.cells[3], "03:00"), "Wed 03:00 · not priced · 2 requests");
  assert.equal(context.costHeatmapText({ dayName: "Mon", cost: 0, records: 0 }, "04:00"), "Mon 04:00 · no requests");
  assert.equal(context.costHeatmapGrid(heatmap, "tokens").busiest, 6 * 24 + 15, "Tokens weighs hours by requests");
  assert.equal(context.costHeatmapGrid({ days: days.slice(1), cost: heatmap.cost, records: heatmap.records }, "cost"), null);
  assert.equal(context.costHeatmapGrid({ days, cost: heatmap.cost.map((row, d) => (d === 2 ? row.slice(1) : row)), records: heatmap.records }, "cost"), null);
  assert.equal(context.costHeatmapGrid(null, "cost"), null);

  assert.equal(context.costCacheSummary({ cachedInputTokens: 4200000, uncachedInputTokens: 850000, cacheCreationTokens: 120000,
    cacheSavingsUsd: 21.5 }).text, "81% read from cache · saved $21.50");
  assert.equal(context.costCacheSummary({ cachedInputTokens: 999999, uncachedInputTokens: 1 }).text, "99% read from cache",
    "a remainder never rounds up to all of it");
  assert.equal(context.costCacheSummary({ cachedInputTokens: 0, uncachedInputTokens: 10 }), null);
  assert.equal(context.costCacheSummary({}), null);

  const local = [{ id: "local-claude", kind: "local", included: true }, { id: "local-omp", kind: "local", provider: "omp", included: true }];
  assert.equal(context.costSourceSummary(local, true), "Local transcripts · live");
  assert.equal(context.costSourceSummary([{ id: "lab-claude", kind: "t3", name: "Lab · Claude", included: true },
    { id: "lab-codex", kind: "t3", name: "Lab · Codex", included: true }, { id: "x", kind: "t3", name: "Off", included: false }], false),
    "T3 on Lab", "a server counts once, excluded ones not at all");
  assert.equal(context.costSourceSummary([], true), "", "nothing to name, nothing to call live");
  assert.equal(context.costSourceSummary(local.concat(["A", "B", "C"].map(name => ({ id: name, kind: "t3", name, included: true }))), false),
    "Local transcripts + 3 more sources");
  assert.ok(context.costScanHasOmp(local));
  assert.ok(!context.costScanHasOmp([{ id: "local-omp", kind: "local", provider: "omp", included: false }]));

  // Live requests come from omp's request log; a scan counts from when it started (`generatedAt`).
  const charted = ["claude", "codex"];
  let requestLog = [];
  for (const event of [{ provider: "claude", costUsd: 0.25, tokens: 1000, at: 200, source: "local" },
    { provider: "claude", costUsd: 0.17, tokens: 500, at: 210, source: "local" },
    { provider: "codex", costUsd: null, tokens: 300, at: 220, source: "local" },
    { provider: "claude", costUsd: 5, tokens: 5, at: 90, source: "local" },
    { provider: "grok", costUsd: 5, tokens: 5, at: 230, source: "local" },
    { provider: "claude", costUsd: 9, tokens: 9, at: 240, source: "remote" }])
    requestLog = context.noteOmpLog(requestLog, event, 300);
  const live = context.costLiveTotals(requestLog, 100, charted);
  assert.equal(live.cost.claude.toFixed(2), "0.42");
  assert.equal(JSON.stringify(live.tokens), '{"claude":1500,"codex":300}');
  assert.equal(live.cost.codex, undefined, "an unpriced request adds tokens, not cost");
  assert.equal(live.requests + "|" + live.lastAt, "3|220", "requests already in the scan, off the chart or not from here are skipped");
  const later = context.costLiveTotals(requestLog, 205, charted);
  assert.equal(later.requests + "|" + later.cost.claude.toFixed(2), "2|0.17",
    "a scan that started at 205 holds the request at 200, not the one at 210 that arrived while it ran");
  assert.equal(context.costLiveTotals(requestLog, "not a time", charted).requests, 0);
  const logged = context.noteOmpLog([], { provider: "claude", costUsd: 0.1, tokens: 1, at: 1000 }, 1000);
  assert.equal(context.noteOmpLog(logged, { provider: "claude", costUsd: 0.1, tokens: 1, at: 1001 }, 1001), logged,
    "the log grows in place: no copy per request");
  assert.equal(context.noteOmpLog(logged, null, 1000 + context.OMP_LOG_SECONDS + 60).length, 0, "old requests leave the log");
  const longLog = [];
  for (let i = 0; i < context.OMP_LOG_LIMIT + 10; i++) longLog.push([999, "claude", 0.01, 1, "local"]);
  assert.equal(context.noteOmpLog(longLog, { provider: "claude", costUsd: 1, tokens: 1, at: 1000 }, 1000).length, context.OMP_LOG_LIMIT,
    "the log stays bounded");

  const keyedList = keys => ({ keys, ops: [], count() { return this.keys.length }, keyAt(index) { return this.keys[index] },
    move(from, to) { this.ops.push("move"); this.keys.splice(to, 0, this.keys.splice(from, 1)[0]) },
    insert(index, key) { this.ops.push("insert"); this.keys.splice(index, 0, key) } });
  const list = keyedList(["a", "b", "c", "d"]);
  context.syncKeyedOrder(list, ["c", "a", "e"]);
  assert.equal(list.keys.join(","), "c,a,e,b,d", "kept keys move, new ones insert, stale ones trail in order");
  assert.equal(list.ops.join(","), "move,insert");
  const settled = keyedList(["a", "b"]);
  context.syncKeyedOrder(settled, ["a", "b"]);
  assert.equal(settled.ops.length, 0, "an unchanged order touches nothing");
  console.log("Costs tab: passed");
}

// ---- Sources: the `sources` setting, and the move of 2.3's source settings into it.
{
  const plain = (value) => JSON.parse(JSON.stringify(value));
  const proxy = { id: "p-1a2b3c4d", kind: "proxy", url: " https://proxy.example ", keyFile: "/k/proxy.key", keeperUrl: "", keeperPasswordFile: "" };
  const computer = { id: "c-0011aabb", kind: "computer", host: "devbox" };
  const t3 = { id: "t3-1700000000000-42", kind: "t3", name: "Lab", url: "https://t3.example", tokenFile: "", on: false };
  const parsed = plain(context.parseSources({ sources: JSON.stringify([proxy, computer, t3, computer,
    { id: "c-0011aabc", kind: "computer", host: "-oProxyCommand=x" }, { id: "c-0011aabd", kind: "computer", host: "a b" },
    { id: "p-zz", kind: "proxy", url: "x" }, { id: "x-00000000", kind: "laptop" }, { ...proxy, id: "p-99999999", url: 7 }, null]) }));
  assert.deepEqual(parsed.map((entry) => entry.id), ["p-1a2b3c4d", "c-0011aabb", "t3-1700000000000-42"],
    "duplicates, unsafe destinations, bad ids, unknown kinds and wrong types are left out");
  assert.equal(parsed[0].url, "https://proxy.example", "text is trimmed");
  assert.equal(parsed[0].on, true, "an entry is on unless switched off");
  assert.equal(parsed[2].on, false);
  assert.deepEqual(plain(context.parseSources({ sources: "not json" })), []);
  assert.deepEqual(plain(context.parseSources({})), []);
  for (const host of ["devbox", "rafa@devbox.tail1234.ts.net", "build_box", "10.0.0.2"]) assert.ok(context.validDestination(host), host);
  for (const host of ["", "-oProxyCommand=x", "a b", "a;b", "devbox:22", "@devbox", "x".repeat(256)]) assert.ok(!context.validDestination(host), host);

  assert.equal(context.activeProxy({ sources: JSON.stringify([{ ...proxy, on: false }]) }), null, "a switched-off proxy reads nothing");
  assert.equal(context.activeProxy({ sources: JSON.stringify([computer, proxy]) }).id, "p-1a2b3c4d");
  assert.deepEqual(JSON.parse(context.t3ServersJson({ sources: JSON.stringify([proxy, t3, { ...t3, id: "t3-2", name: "" }]) })),
    [{ id: "t3-1700000000000-42", name: "Lab", url: "https://t3.example", tokenFile: "", enabled: false }],
    "T3 entries pass in t3_costs.py's shape, half-typed ones not at all");
  const id = context.newSourceId("computer", [computer]);
  assert.ok(/^c-[0-9a-f]{8}$/.test(id) && id !== computer.id);
  const settings = { sources: JSON.stringify([proxy, computer]) };
  assert.deepEqual(JSON.parse(context.sourcesWith(settings, "c-0011aabb", { ...computer, on: false })).map((entry) => entry.on), [true, false],
    "an entry is replaced in place");
  assert.deepEqual(JSON.parse(context.sourcesWith(settings, "p-1a2b3c4d", null)).map((entry) => entry.id), ["c-0011aabb"]);
  assert.equal(JSON.parse(context.sourcesWith(settings, "t3-9", { ...t3, id: "t3-9" })).length, 3, "a new entry is appended");

  const migrate = (settings) => plain(context.migrateSources(settings));
  assert.equal(context.migrateSources({ sourcesVersion: 1, usageSource: "cliproxy" }), null, "it runs once");
  const fresh = migrate({});
  assert.deepEqual(fresh, { changes: { sourcesVersion: 1, setupDone: false, sources: "[]" }, notice: false },
    "a fresh install has nothing to move and opens setup");
  assert.equal(context.setupWanted(context.migrateSources({}).changes), true);
  assert.equal(migrate({ refreshIntervalSec: 600 }).changes.setupDone, true, "settings carried over skip setup");
  assert.equal(context.setupWanted({ refreshIntervalSec: 600 }), false, "no setupDone is a setup already done");
  assert.equal(migrate({ setupDone: false }).changes.setupDone, undefined, "a pending setup stays pending");
  assert.equal(context.hintShown({}, "runway"), true);
  const dismissed = context.hintsDismissing({ hintsDismissed: '["heatmap","nope"]' }, "runway");
  assert.deepEqual(JSON.parse(dismissed), ["heatmap", "runway"], "dismissing keeps the others and drops unknown ids");
  assert.equal(context.hintShown({ hintsDismissed: dismissed }, "runway"), false);
  assert.equal(context.hintShown({ hintsDismissed: dismissed }, "accounts"), true);
  assert.equal(context.hintShown({ hintsDismissed: "not json" }, "forecast"), true, "a broken list shows every hint");
  const moved = migrate({ usageSource: "cliproxy", cliproxyUrl: "https://proxy.example", cliproxyKeyFile: "/k/proxy.key",
    costKeeperUrl: "https://proxy.example/keeper", costKeeperPasswordFile: "/k/keeper.key", ompStatsUrl: "http://devbox:3847",
    ompGatewayUrl: "", ompGatewayKeyFile: "", refreshIntervalSec: 600,
    costT3Servers: JSON.stringify([{ id: "t3-1", name: "Lab", url: "https://t3.example", tokenFile: "/k/t3.key", enabled: false }]) });
  const movedSources = JSON.parse(moved.changes.sources);
  assert.deepEqual(movedSources.map((entry) => [entry.kind, entry.on]), [["proxy", true], ["t3", false]]);
  assert.deepEqual([movedSources[0].url, movedSources[0].keyFile, movedSources[0].keeperUrl, movedSources[0].keeperPasswordFile],
    ["https://proxy.example", "/k/proxy.key", "https://proxy.example/keeper", "/k/keeper.key"], "the proxy keeps its key and its Keeper");
  assert.equal(movedSources[1].tokenFile, "/k/t3.key");
  assert.equal(moved.notice, true, "omp stats on another computer leaves a notice");
  assert.equal(moved.changes.sourcesNotice, "ompRemote");
  for (const key of ["usageSource", "cliproxyUrl", "cliproxyKeyFile", "costKeeperUrl", "costKeeperPasswordFile", "ompStatsUrl",
    "ompGatewayUrl", "ompGatewayKeyFile", "costT3Servers"])
    assert.equal(moved.changes[key], null, key + " is removed");
  assert.equal("refreshIntervalSec" in moved.changes, false, "other settings are left alone");
  const direct = JSON.parse(migrate({ usageSource: "direct", cliproxyUrl: "https://proxy.example", costKeeperUrl: "https://proxy.example/keeper" }).changes.sources);
  assert.deepEqual(direct.map((entry) => [entry.kind, entry.on, entry.keeperUrl]), [["proxy", false, "https://proxy.example/keeper"]],
    "a Keeper set up for a proxy that was not in use stays with that proxy, switched off");
  assert.equal(JSON.parse(migrate({ usageSource: "direct", cliproxyUrl: "http://127.0.0.1:8317" }).changes.sources).length, 0,
    "an unused proxy default is not a source");
  assert.equal(JSON.parse(migrate({ costT3Servers: "not json" }).changes.sources).length, 0, "unreadable T3 settings move nothing");

  // Other computers.
  const devbox = { id: "c-00000001", kind: "computer", host: "devbox", on: true };
  const buildbox = { id: "c-00000002", kind: "computer", host: "rafa@buildbox", on: false };
  const withComputers = (extra) => ({ sources: JSON.stringify([devbox, buildbox]), ...extra });
  assert.deepEqual(Array.from(context.computerArguments(withComputers())), ["--computer", "c-00000001=devbox"],
    "a switched-off computer is not read");
  assert.equal(context.mainComputer(withComputers()).id, "c-00000001", "automatic: the one switched-on computer");
  assert.equal(context.mainComputer(withComputers({ mainComputer: "this" })), null);
  assert.equal(context.mainComputer({ sources: JSON.stringify([devbox, { ...buildbox, on: true }]) }), null,
    "automatic with two computers: this computer");
  assert.equal(context.mainComputer(withComputers({ mainComputer: "c-00000002" })), null, "a switched-off main computer is not used");
  assert.deepEqual(plain(context.mainComputerOptions(withComputers()).map((option) => option.label)),
    ["Automatic (devbox)", "This computer", "devbox"]);
  const payload = { installed: ["claude"], computers: [{ id: "c-00000001", host: "devbox", status: "stale",
    readAt: "2030-01-15T12:00:00Z", message: "devbox cannot be reached from here.", installed: ["codex"],
    omp: { installed: true, local: "ok" } }] };
  const clock = (seconds) => new Date(seconds * 1000).toISOString().slice(11, 16);
  assert.deepEqual(plain(context.computerLine(devbox, context.computerState(payload, devbox.id), clock)),
    { tone: "error", text: "Not answering since 12:00. devbox cannot be reached from here." });
  assert.equal(context.computerLine(devbox, null, clock).text, "Read with the next refresh");
  assert.equal(context.computerLine(buildbox, null, clock).text, "Off");
  const claude = context.localProvider("claude");
  const signedOut = { id: "claude", status: "error", errorKind: "no_credentials" };
  assert.equal(context.setupActionFor(claude, signedOut, payload, null).command, "claude auth login", "on this computer, as before");
  const there = context.setupActionFor(claude, signedOut, payload, devbox);
  assert.equal(there.kind, "install", "what is installed on the main computer decides");
  assert.equal(there.label, "Install and sign in on devbox");
  assert.equal(there.command, "ssh -t devbox 'mise use -g claude && claude auth login'");
  const ompThere = context.setupActionFor(context.localProvider("codex"), { id: "codex", status: "error", errorKind: "no_credentials" }, payload, devbox);
  assert.equal(ompThere.command, "ssh -t devbox 'omp login'", "omp on the main computer signs in for the providers it reads");
  assert.deepEqual(plain(context.ompLiveComputers(withComputers(), payload.computers).map((entry) => entry.id)), ["c-00000001"]);
  assert.equal(context.ompLiveComputers(withComputers({ ompLocal: false }), payload.computers).length, 0);
  assert.equal(context.computersSummary(withComputers(), payload), "devbox · devbox not answering");
  assert.equal(context.computersSummary({}, null), "None");

  const tested = (reply) => plain(context.computerTestResult(reply, "devbox"));
  const refused = tested({ ok: false, steps: [{ id: "ssh", ok: false, text: "devbox did not accept this computer's SSH key.", fix: "ssh-copy-id devbox" }] });
  assert.deepEqual([refused.addable, refused.fix, refused.lines.length], [false, "ssh-copy-id devbox", 1], "a refused key cannot be added yet");
  const empty = tested({ ok: false, steps: [{ id: "ssh", ok: true, text: "Connected to devbox" },
    { id: "found", ok: false, text: "Nothing to read there yet.", fix: "" }] });
  assert.equal(empty.addable, true, "a computer that answered can be added before anything is signed in there");
  assert.equal(tested({ ok: false, thisComputer: true, steps: [{ id: "found", ok: false, text: "devbox is this computer." }] }).addable, false);
  const old = tested({ ok: false, steps: [{ id: "ssh", ok: true, text: "Connected" }, { id: "python", ok: false, text: "Python on devbox is older than 3.10.",
    fix: "Install Python 3.10 or newer there." }] });
  assert.deepEqual([old.fix, old.lines[2]], ["", { tone: "info", text: "Install Python 3.10 or newer there." }], "a fix that is not a command is a note");
  assert.equal(tested({ probeError: "timeout" }).lines[0].text, "No answer within 120 s. Check that devbox is on and online.");

  // Readings from another computer.
  const remoteAccount = { id: "claude", accountId: "c-00000001/main", status: "ok", computer: { id: "c-00000001", name: "devbox" },
    windows: [], origin: "omarchy" };
  assert.equal(context.accountSourceKind(remoteAccount), "computer");
  assert.equal(context.accountCanUse(remoteAccount, "single"), false, "Use switches Omarchy logins on this computer only");
  assert.equal(context.accountStatusLine(remoteAccount, false, 0, null).text, "on devbox");
  const staleLine = context.accountStatusLine({ ...remoteAccount, stale: true, readAt: "2030-01-15T12:00:00Z" }, false, 0, null);
  assert.equal(staleLine.text + " " + clock(staleLine.at), "devbox not answering since 12:00");
  assert.equal(context.accountStatusLine({ id: "claude", status: "ok", windows: [], standIn: { id: "c-00000001", name: "devbox" } }, false, 0, null).text, "read on devbox");
  assert.equal(context.accountLiveAt({ id: "claude", accountId: "main", liveIds: ["c-00000001/omp-0123456789ab"] },
    { "claude@c-00000001/omp-0123456789ab": 1800000000 }), 1800000000, "a request on devbox counts for the same account here");
  assert.equal(context.costSourceSummary([{ kind: "local", included: true }, { kind: "computer", name: "devbox", status: "stale", included: true }], false),
    "Local transcripts + devbox (last known)");
  console.log("Sources: passed");
}

// ---- 1.9 QmlSettings ----
// omp on this computer: the backends' flags, what Settings says, and the live feed's lines. Then the
// per-provider account mode, and the clipboard rule for settings fields.
{
  const plain = (value) => JSON.parse(JSON.stringify(value));
  const args = (value) => Array.from(value);
  assert.deepEqual(args(context.ompUsageArguments({})), ["--omp", "local"], "omp on this computer is read unless turned off");
  assert.deepEqual(args(context.ompUsageArguments({ ompLocal: false })), [], "turned off, omp gets no flag");
  assert.deepEqual(args(context.ompLiveArguments({}, null)), [], "the live feed waits until the backend finds omp");
  assert.deepEqual(args(context.ompLiveArguments({}, { local: "missing" })), [], "no omp, no feed");
  assert.deepEqual(args(context.ompLiveArguments({}, { local: "ok" })), ["--local", "--accounts"]);
  assert.deepEqual(args(context.ompLiveArguments({}, { local: "off", installed: true })), ["--local", "--accounts"]);
  assert.deepEqual(args(context.ompLiveArguments({ ompLocal: false }, { local: "ok" })), [], "turned off, omp's sessions are not followed");
  assert.deepEqual(args(context.ompLiveArguments({}, { local: "unused", installed: true })), [],
    "omp installed but not signed in to anything: nothing to follow here");
  assert.equal(context.ompFound({ local: "unused", installed: true }), true, "omp that is not set up is still found");

  // The CLIProxyAPI key, the Keeper password and T3 tokens go over plain HTTP only to this computer or over Tailscale.
  const secret = (text) => context.secretServerUrlProblem(text, "invalid");
  for (const kept of ["http://127.0.0.1:8317", "http://localhost:8317/", "http://[::1]:8317/keeper", "http://devbox:3773/base",
    "http://100.101.102.103:8317", "https://proxy.example.com/keeper", "https://192.168.1.20:8317"])
    assert.equal(secret(kept), "", kept + " may carry a secret");
  for (const lan of ["http://192.168.1.20:8317", "http://10.0.0.2/keeper", "http://proxy.example.com:8317", "http://[fd00::1]:8317"])
    assert.equal(secret(lan), context.SECRET_HTTP_PROBLEM, lan + " would send a secret in the clear");
  for (const bad of ["http://user:secret@127.0.0.1:8317", "http://127.0.0.1:8317/?key=x", "http://127.0.0.1:8317/#x",
    "http://127.0.0.1:8317/a/../b", "ftp://127.0.0.1", "http://127.0.0.1:99999", "127.0.0.1:8317"])
    assert.equal(secret(bad), "invalid", bad + " is not a server URL");

  const localStatus = (status, localOn = true, loading = false) => plain(context.ompLocalStatus(status, localOn, loading));
  assert.deepEqual(localStatus({ local: "ok", version: "omp/18.10.3", localAccounts: 3, accounts: 4 }),
    { tone: "ok", text: "omp 18.10 found · 3 accounts" }, "the status names the version and this computer's accounts");
  assert.deepEqual(localStatus({ local: "ok", accounts: 1 }), { tone: "ok", text: "omp found · 1 account" });
  assert.deepEqual(localStatus({ local: "ok", localAccounts: 0 }), { tone: "ok", text: "omp found · no accounts signed in" });
  assert.deepEqual(localStatus({ local: "missing" }), { tone: "off", text: "omp not found on this computer" });
  assert.deepEqual(localStatus({ local: "unused", installed: true, message: "omp is installed but not set up on this computer." }),
    { tone: "off", text: "omp is installed but not signed in to anything yet" }, "omp without its own state is not read");
  assert.deepEqual(localStatus({ local: "unused", installed: true }, false), { tone: "off", text: "omp found · its accounts are not read" });
  assert.deepEqual(localStatus({ local: "error", message: "omp usage did not finish in time." }),
    { tone: "error", text: "omp found · its accounts could not be read" });
  assert.deepEqual(localStatus(null, true, true), { tone: "pending", text: "Looking for omp on this computer…" });
  assert.deepEqual(localStatus(null), { tone: "pending", text: "" }, "nothing to say before a refresh");
  assert.deepEqual(localStatus({ local: "off", installed: true }, false), { tone: "off", text: "omp found · its accounts are not read" });
  assert.deepEqual(localStatus({ local: "off" }, false), { tone: "off", text: "Reading omp's accounts is off" });
  assert.equal(context.ompLocalMessage({ message: "omp usage did not finish in time." }), "omp usage did not finish in time.");

  assert.equal(context.ompLocalCostState([], []), "Off");
  assert.equal(context.ompLocalCostState([], ["claude"]), "Not yet read");
  assert.equal(context.ompLocalCostState([{ id: "local-claude", status: "ok" }], ["claude"]), "None found");
  assert.equal(context.ompLocalCostState([{ id: "local-omp", status: "ok" }], ["claude"]), "Included");

  const line = (value) => context.parseOmpLiveLine(JSON.stringify(value));
  const request = { schemaVersion: 1, type: "request", source: "local", provider: "claude", model: "claude-opus-5-5",
    credentialId: 7, costUsd: 0.42, tokens: 1200, subagent: false, at: 1800000000 };
  assert.deepEqual(plain(line(request)), { type: "request", source: "local", provider: "claude", model: "claude-opus-5-5",
    credentialId: 7, costUsd: 0.42, tokens: 1200, subagent: false, at: 1800000000 });
  for (const broken of [{ provider: "Claude!" }, { credentialId: 1.5 }, { costUsd: -1 }, { at: "now" }, { tokens: -3 }, { schemaVersion: 2 }])
    assert.equal(line({ ...request, ...broken }), null, JSON.stringify(broken) + " breaks a request line");
  assert.equal(plain(line({ ...request, credentialId: null, costUsd: null })).credentialId, null, "background spend has no credential");
  assert.equal(context.parseOmpLiveLine("{not json"), null);
  assert.equal(context.parseOmpLiveLine(JSON.stringify({ ...request, model: "x".repeat(70000) })), null, "an oversized line is refused");
  assert.deepEqual(plain(line({ schemaVersion: 1, heartbeat: true })), { type: "heartbeat" });
  assert.deepEqual(plain(line({ type: "accounts", map: { 7: { provider: "claude", accountId: "omp-0123456789ab" },
    x: { provider: "claude", accountId: "omp-0123456789ab" }, 8: { provider: "codex", accountId: "someone@example.com" } } })),
  { type: "accounts", map: { 7: { provider: "claude", accountId: "omp-0123456789ab" } } }, "malformed map entries are left out");
  assert.deepEqual(plain(line({ type: "future" })), { type: "other" }, "a newer helper's lines are skipped, not fatal");

  const map = { 7: { provider: "claude", accountId: "omp-0123456789ab" } };
  const resolved = context.resolveOmpRequest(context.parseOmpLiveLine(JSON.stringify(request)), map);
  assert.equal(resolved.accountId, "omp-0123456789ab");
  assert.equal(resolved.accountKey, "claude@omp-0123456789ab");
  assert.equal(context.resolveOmpRequest({ ...request, credentialId: 9 }, map).accountId, undefined, "an unknown credential stays unattributed");
  assert.equal(context.resolveOmpRequest({ ...request, provider: "codex" }, map).accountId, undefined, "another provider's credential is not this account");
  const now = 1800000000;
  assert.equal(context.noteOmpRequest({}, resolved, now)["claude@omp-0123456789ab"], now);
  const recent = context.noteOmpRequest({ "codex@omp-aaaaaaaaaaaa": now - 4000 }, { ...resolved, at: now + 50 }, now);
  assert.deepEqual(Object.keys(recent), ["claude@omp-0123456789ab"], "an hour without requests drops an account");
  assert.equal(recent["claude@omp-0123456789ab"], now, "a request is never in the future");
  const many = {};
  for (let i = 0; i < 300; i++) many["claude@omp-" + String(i).padStart(12, "0")] = now - 300 + i;
  const capped = context.noteOmpRequest(many, null, now);
  assert.equal(Object.keys(capped).length, context.OMP_RECENT_LIMIT, "recentByAccount stays bounded");
  assert.ok(!("claude@omp-000000000000" in capped) && "claude@omp-000000000299" in capped, "the oldest accounts go first");
  const steady = { "claude@omp-0123456789ab": now - 10 };
  assert.equal(context.noteOmpRequest(steady, { ...request, at: now }, now), steady,
    "a request omp's map cannot name changes nothing: the same map comes back");
  assert.equal(context.noteOmpRequest(steady, { ...resolved, at: now - 20 }, now), steady, "an older request changes nothing either");
  assert.notEqual(context.noteOmpRequest(steady, { ...resolved, at: now }, now), steady, "a newer request is a new map");
  const event = context.parseOmpLiveLine(JSON.stringify(request));
  assert.equal(context.resolveOmpRequest(event, map), event, "a request is named in place, not copied");

  // One reading of accountModes: Settings shows what the panel applies, text or parsed.
  assert.deepEqual(plain(context.parseAccountModes('{"claude":"together","codex":"single","kimi":"sometimes","Bad Id":"single"}')),
    { claude: "together", codex: "single" });
  assert.deepEqual(plain(context.parseAccountModes("not json")), {});
  assert.deepEqual(plain(context.parseAccountModes({ claude: "together", Claude: "single" })), { claude: "together" });
  assert.equal(context.accountModeChoice('{"Claude":"together"}', "Claude"), "",
    "an id Settings does not show is not applied either");
  assert.equal(context.accountModeChoice({ codex: "single" }, "codex"), "single");
  assert.equal(context.setAccountMode('{"claude":"together"}', "codex", "single"), '{"claude":"together","codex":"single"}');
  assert.equal(context.setAccountMode('{"claude":"together"}', "claude", "auto"), "{}", "Automatic removes the override");
  assert.equal(context.accountModeLabel("single") + "/" + context.accountModeLabel("together") + "/" + context.accountModeLabel(undefined),
    "One at a time/Together/Automatic");

  // Hidden accounts: Limits, the bar and the notices read the provider without them.
  const withOmp = {
    id: "opencode", status: "ok", accountId: "main", active: true, account: "dev@example.com", windows: [{ id: "session", used: 10 }],
    pool: { source: "omp", windows: [] }, accountCount: 3,
    accounts: [
      { id: "opencode", status: "ok", accountId: "main", active: true, origin: "signin", account: "dev@example.com", windows: [{ id: "session", used: 10 }], accountCount: 3 },
      { id: "opencode", status: "error", accountId: "omp-aaaaaaaaaaaa", active: false, origin: "omp", windows: [], accountCount: 3 },
      { id: "opencode", status: "ok", accountId: "omp-bbbbbbbbbbbb", active: false, origin: "omp", windows: [{ id: "session", used: 70 }], accountCount: 3 },
    ],
  };
  const hideOne = context.setAccountHidden("{}", "opencode", "omp-aaaaaaaaaaaa", true);
  assert.equal(hideOne, '{"opencode":["omp-aaaaaaaaaaaa"]}');
  const twoLeft = context.withoutHiddenAccounts([withOmp], hideOne)[0];
  assert.deepEqual(plain(twoLeft.accounts.map((account) => [account.accountId, account.accountCount])),
    [["main", 2], ["omp-bbbbbbbbbbbb", 2]]);
  assert.equal(twoLeft.accountCount, 2);
  assert.equal(withOmp.accounts.length, 3, "the backend's reading is left as it was, for Settings to list");
  assert.equal(context.accountName(twoLeft.accounts[1], "{}", true, 2), "Account 3", "an unnamed account keeps its number");
  // One account left is the reading on its own, as a provider with one account reads; omp's pool stays.
  const single = context.withoutHiddenAccounts([withOmp],
    context.setAccountHidden(hideOne, "opencode", "omp-bbbbbbbbbbbb", true))[0];
  assert.equal(single.accounts, undefined);
  assert.equal(single.accountCount, undefined);
  assert.deepEqual([single.accountId, single.windows[0].used, single.pool.source], ["main", 10, "omp"]);
  // Hiding the active account hands the summary to the first other one that read fine.
  const leadHidden = context.withoutHiddenAccounts([withOmp], '{"opencode":["main"]}')[0];
  assert.deepEqual([leadHidden.accountId, leadHidden.windows[0].used, leadHidden.account], ["omp-bbbbbbbbbbbb", 70, undefined],
    "the hidden account's fields do not linger in the summary");
  // Hiding every account changes nothing (turning the provider off does that), and so does an unknown id.
  const all = '{"opencode":["main","omp-aaaaaaaaaaaa","omp-bbbbbbbbbbbb"]}';
  assert.equal(context.withoutHiddenAccounts([withOmp], all)[0], withOmp);
  assert.equal(context.withoutHiddenAccounts([withOmp], '{"opencode":["k-00000000"]}')[0], withOmp);
  assert.equal(context.setAccountHidden(hideOne, "opencode", "omp-aaaaaaaaaaaa", false), "{}", "showing the last hidden one forgets the provider");
  assert.deepEqual(plain(context.parseHiddenAccounts('{"opencode":["main","main",7,""],"Bad Id":["main"],"codex":"main"}')),
    { opencode: ["main"] });
  assert.equal(context.accountSettingsLabel(withOmp.accounts[2], "{}", true, 2), "Account 3 · omp");
  assert.equal(context.accountSettingsLabel({ ...withOmp.accounts[0], origins: ["signin", "omp"] }, "{}", false, 0),
    "dev@example.com · sign-in + omp");

  // The 1.7.3 clipboard rule: an editable TextInput (what TextField is built on) fetches every clipboard
  // change, so the only text input in the widget is SettingsField's read-only secret field.
  for (const file of fs.readdirSync(root).filter((name) => name.endsWith(".qml"))) {
    const text = fs.readFileSync(path.join(root, file), "utf8");
    const inputs = text.match(/\b(?:TextInput|TextField)\s*\{/g) || [];
    if (file === "SettingsField.qml") assert.ok(inputs.length === 1 && /Ui\.TextField \{[^}]*readOnly: true/.test(text), "SettingsField's secret input stays read-only");
    else assert.equal(inputs.length, 0, file + " declares no text input; settings fields use SettingsField");
  }
}
console.log("omp settings, live feed and account modes: passed");

// ---- 1.9 QmlLimits ----
{
  const plain = (value) => JSON.parse(JSON.stringify(value));
  // A 5-hour window, half elapsed, rising at `perSecond` over its last 50 minutes (a steady recent rate).
  const rising = (used, perSecond, extra = {}) => {
    const samples = [];
    for (let t = NOW - 3000; t <= NOW; t += 300) samples.push([t, used - perSecond * (NOW - t)]);
    return { id: "session", label: "5-hour limit", used, remaining: 100 - used, windowSeconds: SESSION,
      resetsAt: NOW + SESSION / 2, samples, ...extra };
  };
  const quiet = (used) => ({ id: "session", label: "5-hour limit", used, remaining: 100 - used,
    windowSeconds: SESSION, resetsAt: NOW + SESSION / 2, samples: [] });
  const week = (used) => ({ id: "weekly", label: "Weekly limit", used, remaining: 100 - used,
    windowSeconds: WEEK, resetsAt: NOW + 3 * DAY, samples: [] });
  const login = (accountId, windows, extra = {}) => ({ id: "claude", name: "Claude Code", status: "ok",
    accountId, label: accountId, windows, ...extra });

  // Spending now: a rise in the last 15 minutes, or a live omp request in the last two.
  const rose = (seconds) => ({ id: "claude", accountId: "work", activity: { lastIncreaseAt: NOW - seconds } });
  assert.equal(context.spendingNow(rose(900), NOW, {}), true);
  assert.equal(context.spendingNow(rose(901), NOW, {}), false, "older than 15 minutes is not spending now");
  assert.equal(context.spendingNow({ id: "claude", accountId: "work" }, NOW, { "claude@work": NOW - 120 }), true);
  assert.equal(context.spendingNow({ id: "claude", accountId: "work" }, NOW, { "claude@work": NOW - 121 }), false);
  assert.equal(context.spendingNow({ id: "claude", accountId: "work" }, NOW, { "codex@work": NOW }), false, "keys include the provider");
  assert.equal(context.spendingNow(rose(10), null, {}), false, "no clock, no claim");
  // A native login omp also reads (merged by email) carries omp's id; omp's live requests name it so.
  const merged = { id: "claude", accountId: "work", origin: "omarchy", origins: ["omarchy", "omp"], ompAccountId: "omp-0123456789ab" };
  assert.equal(context.spendingNow(merged, NOW, { "claude@omp-0123456789ab": NOW - 30 }), true,
    "a live omp request reaches the native account omp shares");
  assert.equal(context.accountLiveAt(merged, { "claude@work": NOW - 90, "claude@omp-0123456789ab": NOW - 30 }), NOW - 30, "the newest key wins");
  assert.equal(context.spendingNow({ ...merged, id: "codex" }, NOW, { "claude@omp-0123456789ab": NOW }), false, "still per provider");
  assert.equal(context.accountMode({ id: "claude", accounts: [merged, { id: "claude", accountId: "personal", activity: { lastIncreaseAt: NOW - 60 } }] }, "{}", NOW, { "claude@omp-0123456789ab": NOW - 30 }), "together", "and makes the shared account count as used");
  assert.equal(context.accountAnswersTo(merged, "omp-0123456789ab"), true);
  assert.equal(context.accountAnswersTo(merged, "work"), true);
  assert.equal(context.accountAnswersTo(merged, "omp-ffffffffffff"), false);
  assert.equal(context.accountAnswersTo(merged, ""), false);

  // One recent map: live omp requests, and through a proxy each account's last request.
  const recentMap = plain(context.mergeRecentActivity({ "claude@omp-0123456789ab": NOW - 50, "codex@a1": NOW - 400 },
    [{ id: "codex", status: "ok", accountId: "a1", lastUsedAt: NOW - 100 }, { id: "codex", status: "ok", accountId: "a2", lastUsedAt: NOW - 900 },
     { id: "codex", status: "ambiguous", lastUsedAt: NOW - 1 }]));
  assert.deepEqual(recentMap, { "claude@omp-0123456789ab": NOW - 50, "codex@a1": NOW - 100, "codex@a2": NOW - 900 },
    "the newest sign wins; ambiguous rows add nothing");

  // Mode: the Settings choice wins; a proxy, an omp pool, or two accounts rising within an hour mean together.
  const pair = (a, b) => ({ id: "claude", accounts: [rose(a), { ...rose(b), accountId: "personal" }] });
  assert.equal(context.accountMode(pair(10, 5000), "{}", NOW, {}), "single");
  assert.equal(context.accountMode(pair(10, 3500), "{}", NOW, {}), "together");
  assert.equal(context.accountMode({ ...pair(10, 3500), accountSwitch: { mode: "auto", threshold: 95 } }, "{}", NOW, {}),
    "single", "Omarchy switching logins: sessions left on the old one do not make it used together");
  assert.equal(context.accountMode(pair(10, 3500), '{"claude":"single"}', NOW, {}), "single", "the user's choice wins");
  assert.equal(context.accountMode(pair(10, 5000), '{"claude":"together"}', NOW, {}), "together");
  assert.equal(context.accountMode(pair(10, 5000), '{"claude":"sideways"}', NOW, {}), "single", "unknown choices are automatic");
  assert.equal(context.accountMode(pair(10, 5000), "not json", NOW, {}), "single");
  const proxyLogins = { id: "claude", accounts: pair(9000, 9000).accounts.map((entry) => ({ ...entry, proxy: { id: "p-00000001", name: "CLIProxyAPI" } })) };
  assert.equal(context.accountMode(proxyLogins, "{}", NOW, {}), "together", "a proxy spends its accounts together");
  assert.equal(context.accountMode({ id: "claude", accounts: [proxyLogins.accounts[0], rose(9000)] }, "{}", NOW, {}), "single",
    "a proxy's account beside this computer's own login is one at a time");
  assert.equal(context.accountMode({ ...pair(9000, 9000), pool: { source: "omp", windows: [] } }, "{}", NOW, {}), "together");
  assert.equal(context.accountMode(pair(10, 9000), "{}", NOW, { "claude@personal": NOW - 3000 }), "together",
    "a live omp request counts as activity");

  // Counted accounts: the in-use one alone; together, every account spending now, else the least headroom.
  const work = login("work", [rising(70, 0.01), week(31)], { active: true, activity: { lastIncreaseAt: NOW - 60 } });
  const personal = login("personal", [quiet(3), week(39)], { active: false });
  const spare = login("spare", [quiet(100), week(90)], { active: false });
  const claude = { id: "claude", name: "Claude Code", status: "ok", accountId: "work", accounts: [work, personal, spare] };
  assert.deepEqual(Array.from(context.countedAccounts(claude, "single", NOW, {})), [0]);
  const noActive = { ...claude, accountId: "personal", accounts: [{ ...work, active: undefined }, personal, spare] };
  assert.deepEqual(Array.from(context.countedAccounts(noActive, "single", NOW, {})), [1], "falls back to the summary's account");
  assert.deepEqual(Array.from(context.countedAccounts(claude, "together", NOW, { "claude@spare": NOW - 30 })), [0, 2],
    "together counts every account spending now, in account order");
  const idle = { ...claude, accounts: [{ ...work, activity: null }, personal, spare] };
  assert.deepEqual(Array.from(context.countedAccounts(idle, "together", NOW, {})), [0],
    "nothing spending: the least headroom that still has room, not the used-up one");
  const allOut = { ...claude, accounts: [login("a", [quiet(100)]), login("b", [quiet(100)])] };
  assert.deepEqual(Array.from(context.countedAccounts(allOut, "together", NOW, {})), [0]);
  assert.deepEqual(Array.from(context.countedAccounts({ id: "claude" }, "single", NOW, {})), []);

  // Row order: stable (Omarchy logins, keys, omp) one at a time; least headroom first together.
  const mixed = [login("omp-1a2b3c4d5e6f", [quiet(10)], { origin: "omp" }), login("k-0123abcd", [quiet(50)]),
    login("main", [quiet(95)]), login("broken", [], { status: "error" })];
  assert.deepEqual(Array.from(context.accountOrder(mixed, "single")), [2, 3, 1, 0]);
  assert.deepEqual(Array.from(context.accountOrder(mixed, "together")), [2, 1, 0, 3], "unknown headroom goes last");
  assert.deepEqual(Array.from(context.accountOrder([login("a", [quiet(40)]), login("b", [quiet(40)])], "together")), [0, 1],
    "ties keep the stable order, so rows do not shuffle");

  // A keyed list reaches the wanted order by moves and inserts; kept items survive.
  const items = ["a", "b", "c", "d"].map((key) => ({ key }));
  const keep = items[2];
  const adapter = {
    count: () => items.length, keyAt: (i) => items[i].key,
    move: (from, to) => items.splice(to, 0, items.splice(from, 1)[0]),
    insert: (i, key) => items.splice(i, 0, { key }),
  };
  context.syncKeyedOrder(adapter, ["c", "a", "e"]);
  assert.deepEqual(items.slice(0, 3).map((item) => item.key), ["c", "a", "e"]);
  assert.equal(items[0], keep, "a moved item is the same object");
  assert.deepEqual(items.slice(3).map((item) => item.key).sort(), ["b", "d"], "stale items are left at the end");

  // Status line priority: failure > used up > spending now > recent event > plan > source.
  const clock = (epoch) => "@" + (epoch - NOW);
  const line = (account, event = null) => plain(context.accountStatusLine(account, context.spendingNow(account, NOW, {}), NOW, event));
  assert.equal(line(login("w", [], { status: "error", errorKind: "expired" })).text, "sign-in expired");
  const exhausted = login("w", [{ ...quiet(100), resetsAt: NOW + 600 }, { ...week(100), resetsAt: NOW + DAY }],
    { activity: { lastIncreaseAt: NOW - 30 }, plan: "Claude Max 5x" });
  assert.deepEqual(line(exhausted), { kind: "usedup", text: "used up", at: NOW + DAY, tone: "urgent" },
    "used up beats spending now; back when every used-up window has reset");
  const blockedTwice = login("w", [{ ...quiet(100), resetsAt: NOW + 3600 }, { ...week(100), resetsAt: null }]);
  assert.deepEqual(line(blockedTwice), { kind: "usedup", text: "used up", at: null, tone: "urgent" },
    "a used-up window without a reset time still blocks: no back time");
  assert.equal(context.accountUsedUp(blockedTwice).resetsAt, null, "the hover card reads the same helper");
  assert.equal(context.accountUsedUp(login("w", [quiet(99.6)])), null, "room left is not used up");
  assert.equal(context.compactPercent(99.6, "Used"), 99, "a meter never rounds into used up");
  assert.equal(context.compactPercent(99.6, "Remaining"), 1);
  assert.equal(context.compactPercent(100, "Used") + "|" + context.compactPercent(100, "Remaining"), "100|0");
  assert.equal(context.compactPercent(31.4, "Used") + "|" + context.compactPercent(null, "Used"), "31|null");
  assert.equal(line({ ...work, plan: "Claude Max 5x" }, { kind: "switch", at: NOW - 60 }).kind, "spending");
  assert.deepEqual(line(login("p", [quiet(3)], { plan: "Claude Max 20x" }), { kind: "switch", at: NOW - 600 }),
    { kind: "switch", text: "switched", at: NOW - 600, tone: "accent" });
  assert.equal(line(login("p", [quiet(3)], { plan: "Claude Max 20x" }), { kind: "reset", at: NOW - 4 * HOUR }).text,
    "Claude Max 20x", "an event older than three hours gives way to the plan");
  assert.equal(line(login("omp-0123456789ab", [quiet(3)], { origin: "omp" })).text, "omp");
  assert.equal(line(login("k-0123abcd", [quiet(3)])).text, "key");
  assert.equal(line(login("w", [quiet(3)], { status: "ok", stale: true, plan: "Pro" })).kind, "stale");

  // Use: Omarchy's switch command, never anything an option parser could misread.
  assert.deepEqual(Array.from(context.accountUseArgv("claude", { accountId: "personal" })),
    ["omarchy", "agent", "account", "use", "claude", "personal"]);
  assert.deepEqual(Array.from(context.accountUseArgv("claude", { accountId: "main", primary: true })),
    ["omarchy", "agent", "account", "use", "claude", "primary"], "the built-in login is Omarchy's primary");
  assert.equal(context.accountUseArgv("claude", { accountId: "--help" }), null);
  assert.equal(context.accountUseArgv("claude", { accountId: "two words" }), null);
  assert.equal(context.accountUseArgv("../x", { accountId: "work" }), null);
  assert.equal(context.accountCanUse(personal, "single"), true);
  assert.equal(context.accountCanUse(work, "single"), false, "the account in use offers no Use");
  assert.equal(context.accountCanUse(personal, "together"), false);
  assert.equal(context.accountCanUse(login("k-0123abcd", [quiet(3)]), "single"), false, "keys have no Use");
  assert.equal(context.accountCanUse({ ...personal, proxy: { id: "p-00000001", name: "CLIProxyAPI" } }, "single"), false,
    "proxy accounts have no Use");

  // How new sessions pick an account: one text for the ACCOUNTS header and the hover card.
  assert.equal(context.accountModeText({ ...claude, accountSwitch: { mode: "auto", threshold: 95 } }, "single"),
    "Omarchy · switches at 95%");
  assert.equal(context.accountModeText({ ...claude, accountSwitch: { mode: "manual", threshold: 90 } }, "single"),
    "Omarchy · notifies at 90%");
  assert.equal(context.accountModeText(claude, "single"), "");
  assert.equal(context.accountModeText({ ...claude, pool: { source: "omp" } }, "together"), "Used together · omp");
  const throughProxy = (account) => ({ ...account, proxy: { id: "p-00000001", name: "CLIProxyAPI" } });
  assert.equal(context.accountModeText({ ...claude, accounts: claude.accounts.map(throughProxy) }, "together"), "Used together · CLIProxyAPI");
  assert.equal(context.accountModeText({ ...claude, accounts: [{ ...work, origins: ["omarchy", "omp"] }, personal] }, "together"), "Used together · omp", "an account omp also reads counts as omp");
  assert.equal(context.accountSourceKind({ accountId: "work", source: "Claude OAuth usage API" }), "omarchy",
    "source describes the API; only origin names the kind");
  assert.equal(context.accountSourceKind({ accountId: "a1", origin: "proxy" }), "proxy");
  assert.equal(context.accountSourceKind({ accountId: "a1", origin: "omarchy", proxy: { id: "p-00000001" } }), "proxy",
    "a reading that came through a proxy is the proxy's, whatever its origin there");
  assert.equal(context.accountSourceKind({ origin: "omp", accountId: "x" }), "omp");
  assert.equal(context.accountSourceKind({ accountId: "k-0123abcd" }), "key");
  assert.equal(context.accountSourceKind({ accountId: "primary" }), "key");
  assert.equal(context.accountSourceKind({ accountId: "omp-0123456789ab" }), "omp");
  assert.equal(context.accountSourceKind({ accountId: "" }), "omarchy", "one fallback for every surface");

  // One account state per provider: what the chip, its dots, the tile, the rows and the runway read.
  const stateOf = (provider, extra = {}) => plain(context.accountState(provider, { modes: "{}", nowSeconds: NOW,
    recentByAccount: {}, warningThreshold: 25, criticalThreshold: 10, ...extra }));
  const single = stateOf(claude);
  assert.equal(single.mode, "single");
  assert.deepEqual(single.counted, [0]);
  assert.equal(single.value, 0);
  assert.deepEqual(single.spending, [true, false, false]);
  assert.deepEqual(single.inUse, [true, false, false], "in use: the active login, one at a time");
  assert.deepEqual(single.rings, ["ok", "ok", "critical"], "rings follow each account's tightest limit");
  assert.deepEqual(single.dots.dots.map((dot) => [dot.index, dot.state, dot.counted, dot.spending]),
    [[0, "ok", true, true], [1, "ok", false, false], [2, "critical", false, false]]);
  const weeklyBound = login("tight", [quiet(10), week(80)]);
  assert.deepEqual(stateOf({ id: "claude", accounts: [work, weeklyBound] }).rings, ["ok", "warning"],
    "an account at warning on its weekly limit rings warning whatever window a chip shows");
  const together = stateOf(claude, { modes: '{"claude":"together"}', recentByAccount: { "claude@spare": NOW - 30 } });
  assert.equal(together.mode, "together");
  assert.deepEqual(together.counted, [0, 2], "together: every account spending now");
  assert.deepEqual(together.inUse, [false, false, false], "nothing is \"in use\" when accounts are used together");
  assert.deepEqual(together.order, [2, 0, 1], "rows: least headroom first");
  assert.deepEqual(together.stable, [0, 1, 2], "dots keep the stable order");
  const proxyAccounts = [0, 1, 2].map((i) => ({ id: "codex", accountId: String(i), status: "ok", origin: "proxy",
    windows: [{ ...quiet([30, 60, 90][i]), id: "primary" }] }));
  const proxied = { id: "codex", status: "ok", accountId: "2", accounts: proxyAccounts };
  const viaProxy = stateOf(proxied, { recentByAccount: context.mergeRecentActivity(null,
    [{ id: "codex", status: "ok", accountId: "1", lastUsedAt: NOW - 30 }, { id: "codex", status: "ok", accountId: "0", lastUsedAt: NOW - 3600 }]) });
  assert.equal(viaProxy.mode, "together");
  assert.deepEqual(viaProxy.counted, [1], "through a proxy the account that just served a request is counted, not an hour-old last one");
  assert.equal(viaProxy.value, 1);
  assert.deepEqual(viaProxy.inUse, [false, false, false]);
  assert.deepEqual(stateOf(proxied).counted, [2], "nothing spending: the least headroom");
  const many = { id: "claude", accounts: ["a", "b", "c", "d", "e"].map((id) => login(id, [quiet(10)])) };
  const manyState = stateOf(many, { modes: '{"claude":"together"}', recentByAccount: { "claude@e": NOW } });
  assert.deepEqual(manyState.dots.dots.map((dot) => dot.index), [0, 1, 4], "five accounts: three dots, the counted one kept");
  assert.equal(manyState.dots.extra, 2);
  assert.equal(manyState.dots.dots[2].counted, true);
  assert.deepEqual(stateOf({ id: "claude", accounts: [work] }).dots, { dots: [], extra: 0 }, "one account, no dots");
  assert.equal(context.accountState({ id: "claude" }, {}), null);
  assert.deepEqual(Array.from(context.pickAccounts([2, 0, 1, 3], [3], 2)), [2, 3], "counted first, listed in order");

  // Clock times: the time today or within 12 hours, the weekday within six days, the date beyond.
  const at = (hours) => NOW + hours * HOUR;
  assert.equal(context.clockPattern(at(2), NOW, "HH:mm"), "HH:mm");
  assert.equal(context.clockPattern(at(-11), NOW, "h:mm AP"), "h:mm AP");
  assert.equal(context.clockPattern(at(20), NOW, "HH:mm"), new Date(at(20) * 1000).toDateString() === new Date(NOW * 1000).toDateString()
    ? "HH:mm" : "ddd HH:mm", "20 hours ahead carries the weekday unless it is still today");
  assert.equal(context.clockPattern(at(5 * 24), NOW, "HH:mm"), "ddd HH:mm");
  assert.equal(context.clockPattern(at(10 * 24), NOW, "HH:mm"), "d MMM HH:mm", "a monthly reset names its date");
  assert.equal(context.clockPattern("never", NOW, "HH:mm"), "HH:mm");

  // Forecast: where this pace takes a limit by its reset.
  const hot = context.windowForecast(rising(70, 0.01), NOW);
  assert.ok(Math.abs(hot.rate - 0.01) < 1e-9, "the projection's rate is exposed");
  assert.equal(hot.runsOut, true);
  assert.ok(Math.abs(hot.runsOutAt - (NOW + 3000)) < 1);
  assert.equal(hot.projected, 100);
  assert.deepEqual(plain(context.forecastSegment(hot, "Used")), { from: 0.7, to: 1, runsOut: true });
  assert.deepEqual(plain(context.forecastSegment(hot, "Remaining")), { from: 0, to: 0.3, runsOut: true },
    "Remaining: the part of the fill this pace spends");
  assert.deepEqual(plain(context.forecastText(hot, "Used", clock)), { text: "runs out @3000 · pace 50%", urgent: true });
  const calm = context.windowForecast(rising(20, 0.002), NOW);
  assert.equal(calm.runsOut, false);
  assert.ok(Math.abs(calm.projected - 38) < 0.01, "20% + 0.002%/s over 9000 s");
  assert.equal(context.forecastText(calm, "Used", clock).text, "lasts until reset");
  assert.equal(context.forecastSegment(context.windowForecast(quiet(20), NOW), "Used"), null, "no rate, no forecast segment");
  assert.equal(context.forecastText(context.windowForecast({ ...quiet(100) }, NOW), "Used", clock).text, "used up");

  // Scrub: below the fill, when use passed that point; above it, when this pace gets there.
  const scrubbed = rising(70, 0.01);
  assert.deepEqual(plain(context.meterScrub(scrubbed, 50, "Used", NOW)), { kind: "passed", percent: 50, at: NOW - 1800 });
  assert.equal(context.scrubText(context.meterScrub(scrubbed, 50, "Used", NOW), "Used", clock), "50% · passed @-1800");
  assert.deepEqual(plain(context.meterScrub(scrubbed, 85, "Used", NOW)), { kind: "at", percent: 85, at: NOW + 1500 });
  assert.equal(context.scrubText(context.meterScrub(scrubbed, 85, "Used", NOW), "Used", clock), "85% · at @1500 at this pace");
  assert.equal(context.meterScrub(rising(20, 0.002), 90, "Used", NOW).kind, "after-reset");
  assert.equal(context.meterScrub(quiet(20), 90, "Used", NOW).kind, "idle");
  assert.equal(context.scrubText(context.meterScrub(quiet(20), 90, "Used", NOW), "Used", clock), "90% · not being used now");
  assert.equal(context.meterScrub(scrubbed, 10, "Used", NOW).kind, "earlier", "before the first sample of the window");
  assert.equal(context.scrubText(context.meterScrub(scrubbed, 50, "Remaining", NOW), "Remaining", clock),
    "50% left · passed @-1800", "Remaining reads the same point as what was left");

  // Runway, one at a time: the in-use account runs out, the next takes over at the same pace.
  const runwayOf = (accounts, mode, counted) => plain(context.accountRunway({ id: "claude", accounts }, mode, counted, NOW,
    context.accountOrder(accounts, mode)));
  const first = login("work", [rising(70, 0.01), week(31)], { active: true });
  const takeover = runwayOf([first, login("personal", [quiet(20), week(39)])], "single", [0]);
  assert.equal(takeover.horizon, SESSION / 2);
  assert.deepEqual(takeover.lanes.map((lane) => [lane.index, lane.kind, Math.round(lane.start), Math.round(lane.end)]),
    [[0, "runs", 0, 3000], [1, "takesover", 3000, 9000]]);
  assert.equal(takeover.gap, 0, "Personal lasts until the reset");
  assert.equal(takeover.spending, true);
  const gap = runwayOf([first, login("personal", [quiet(60), week(39)])], "single", [0]);
  assert.deepEqual(gap.lanes.map((lane) => [lane.kind, Math.round(lane.end)]), [["runs", 3000], ["runs", 7000]]);
  assert.equal(Math.round(gap.gap), 2000, "both run out 2000 s before the reset");
  const blocked = runwayOf([login("work", [quiet(100)], { active: true }), login("personal", [quiet(90)])], "single", [0]);
  assert.deepEqual(blocked.lanes.map((lane) => lane.kind), ["usedup", "lasts"], "the next account takes over at once");
  assert.equal(blocked.gap, 0);
  const empty = runwayOf([login("work", [quiet(100)], { active: true }), login("personal", [quiet(100)])], "single", [0]);
  assert.equal(empty.gap, SESSION / 2, "every account used up: the whole wait is a gap");
  const restful = runwayOf([login("work", [quiet(10)], { active: true }), login("personal", [quiet(20)])], "single", [0]);
  assert.deepEqual(restful.lanes.map((lane) => lane.kind), ["lasts", "notneeded"]);
  assert.equal(restful.spending, false);
  // Together: every account runs down side by side, each at its own pace.
  const both = runwayOf([first, login("personal", [rising(60, 0.005), week(39)])], "together", [0, 1]);
  assert.deepEqual(both.lanes.map((lane) => [lane.index, lane.kind, Math.round(lane.start), Math.round(lane.end)]),
    [[0, "runs", 0, 3000], [1, "runs", 0, 8000]]);
  assert.equal(Math.round(both.gap), 1000);
  const oneIdle = runwayOf([first, login("personal", [quiet(60)])], "together", [0]);
  assert.equal(oneIdle.gap, 0, "an account not being spent lasts, so there is no gap");
  assert.deepEqual(oneIdle.lanes.map((lane) => !!lane.idle), [false, true], "the account not being spent is marked idle");
  // A provider without accounts is its own single lane.
  const solo = plain(context.accountRunway({ id: "claude", status: "ok", windows: [rising(70, 0.01)] }, "single", [], NOW, []));
  assert.deepEqual(solo.lanes.map((lane) => lane.kind), ["runs"]);
  assert.equal(Math.round(solo.gap), 6000);
  assert.equal(context.accountRunway({ id: "kimi", status: "ok", windows: [week(40)] }, "single", [], NOW, []), null,
    "no short window, no runway");
  assert.equal(context.poolLine({ windows: [{ windowSeconds: SESSION, accounts: 2, usedAccounts: 0.43, remainingAccounts: 1.57 }] },
    quiet(10)), "Pool: 1.57 of 2 accounts left this 5-hour window");
  assert.equal(context.poolLine({ windows: [{ windowSeconds: WEEK, accounts: 2, remainingAccounts: 1 }] }, quiet(10)), "");

  // Events: the first reading seeds; then a switch, a reset after heavy use, and an omp sign-in lost.
  const team = (active, workUsed) => ({ id: "claude", name: "Claude Code", status: "ok", accounts: [
    login("work", [quiet(workUsed), week(31)], { active: active === "work" }),
    login("personal", [quiet(3), week(39)], { active: active === "personal" }),
  ] });
  const seeded = context.accountEvents({}, [team("work", 90)], NOW, 25);
  assert.equal(seeded.events.length, 0, "the first reading only seeds");
  const switched = context.accountEvents(seeded.state, [team("personal", 96)], NOW + 900, 25);
  assert.equal(switched.events.length, 1);
  assert.deepEqual(plain(switched.events[0]), { id: "switch|claude|personal|" + (NOW + 900), kind: "switch",
    provider: "claude", accountId: "personal", from: "work", fromUsed: 96, label: "", at: NOW + 900 });
  const names = { work: "Work", personal: "Personal" };
  assert.equal(context.eventNoticeText(switched.events[0], team("personal", 96), names, () => "16:27", false),
    "Omarchy moved new Claude sessions to Personal at 16:27: Work reached 96%. Running sessions stay on Work.");
  assert.equal(context.eventNoticeText(switched.events[0], team("personal", 96), names, () => "16:27", true),
    "New Claude sessions now use Personal. Running sessions stay on Work.");
  const proxyPair = (best) => ({ id: "codex", status: "ok", accountId: best, accounts: [
    { id: "codex", accountId: "a1", status: "ok", windows: [quiet(10)] },
    { id: "codex", accountId: "a2", status: "ok", windows: [quiet(20)] }] });
  const proxySeed = context.accountEvents({}, [proxyPair("a1")], NOW, 25);
  assert.equal(context.accountEvents(proxySeed.state, [proxyPair("a2")], NOW + 900, 25).events.length, 0,
    "a proxy's summary following headroom is no switch");
  const before = { id: "codex", name: "OpenAI Codex", status: "ok", windows: [{ ...quiet(92), id: "primary", resetsAt: NOW - 30 }] };
  const after = { id: "codex", name: "OpenAI Codex", status: "ok", windows: [{ ...quiet(2), id: "primary", resetsAt: NOW + SESSION - 30 }] };
  const resetSeed = context.accountEvents({}, [before], NOW - 60, 25);
  const reset = context.accountEvents(resetSeed.state, [after], NOW, 25);
  assert.equal(reset.events.length, 1);
  assert.equal(reset.events[0].kind, "reset");
  assert.equal(reset.events[0].at, NOW - 30, "a reset happened when the old window ended");
  assert.equal(context.eventNoticeText(reset.events[0], after, {}, () => "18:02", false), "Codex's 5-hour limit reset at 18:02.");
  const lightSeed = context.accountEvents({}, [{ ...before, windows: [{ ...quiet(40), id: "primary", resetsAt: NOW - 30 }] }], NOW - 60, 25);
  assert.equal(context.accountEvents(lightSeed.state, [after], NOW, 25).events.length, 0, "a lightly used limit resets quietly");
  const idleAfter = { ...after, windows: [{ ...quiet(0), id: "primary", resetsAt: null }] };
  assert.equal(context.accountEvents(resetSeed.state, [idleAfter], NOW, 25).events.length, 1,
    "a window whose provider reports no reset time once idle has reset too, as the chip flashes it");
  const rollingSeed = context.accountEvents({}, [{ ...before, windows: [{ ...quiet(92), id: "primary", resetsAt: null }] }], NOW - 60, 25);
  assert.equal(context.accountEvents(rollingSeed.state, [{ ...before, windows: [{ ...quiet(70), id: "primary", resetsAt: null }] }], NOW, 25)
    .events.length, 0, "a rolling window shedding old use is no reset");
  const ompAccount = (status) => ({ id: "claude", status: "ok", accounts: [
    login("main", [quiet(5)], { active: true, origin: "signin" }),
    { id: "claude", accountId: "omp-0123456789ab", origin: "omp", status, errorKind: status === "error" ? "expired" : "", windows: [] }] });
  const ompSeed = context.accountEvents({}, [ompAccount("ok")], NOW, 25);
  const expired = context.accountEvents(ompSeed.state, [ompAccount("error")], NOW + 900, 25);
  assert.equal(expired.events.length, 1);
  assert.equal(context.eventNoticeText(expired.events[0], ompAccount("error"), { "omp-0123456789ab": "Team" }, clock, false),
    "omp can no longer renew Team's sign-in. Sign in again in omp.");
  assert.equal(context.accountEvents(expired.state, [ompAccount("error")], NOW + 1800, 25).events.length, 0, "said once");
}
console.log("1.9 QmlLimits accounts, forecast and runway: passed");

// ---- 1.9 QmlBar ----
{
  const now = 1760000000;
  const win = (id, used, resetIn, seconds) => ({ id, label: id === "weekly" ? "Weekly limit" : "5-hour limit", used,
    remaining: 100 - used, resetsAt: now + resetIn, windowSeconds: seconds });
  const login = (accountId, label, used, extra = {}) => ({ id: "claude", accountId, label, status: "ok", origin: "omarchy",
    windows: [win("session", used, 7200, 18000), win("weekly", 30, 300000, 604800)], activity: {}, ...extra });
  const claude = (accounts, extra = {}) => ({ id: "claude", name: "Claude Code", status: "ok", windows: accounts[0].windows,
    accounts, ...extra });
  const stateOf = (provider, extra = {}) => context.accountState(provider, { modes: "{}", nowSeconds: now,
    recentByAccount: {}, warningThreshold: 25, criticalThreshold: 10, ...extra });
  // The chip's strip from the provider's state; `counted` pins what the state would decide.
  const strip = (provider, counted, mode, extra = {}) => {
    const state = stateOf(provider, { modes: JSON.stringify({ claude: mode }) });
    if (counted) state.counted = counted;
    return context.barAccountStrip(provider, state, { selector: "auto", nowSeconds: now, ...extra });
  };
  const plain = (value) => JSON.parse(JSON.stringify(value));

  // Names: never an email in the bar.
  assert.equal(context.barAccountName({ id: "claude", label: "Work", active: true, account: "me@example.com" }, 0, "{}"), "Work");
  assert.equal(context.barAccountName({ id: "codex", accountId: "f00d", account: "me@example.com" }, 2, "{}"), "Account 3");
  assert.deepEqual(plain(context.barAccountInitials(["Work", "Wife", "Account 3", "personal", "—"])), ["Wo", "Wi", "3", "P", "?"]);
  assert.deepEqual(plain(context.barAccountInitials(["Team A", "Team B"])), ["1", "2"], "same two letters fall back to the number");

  // Rings and the value account.
  assert.equal(context.accountRingState(login("a", "A", 50), 25, 10), "ok");
  assert.equal(context.accountRingState(login("a", "A", 80), 25, 10), "warning");
  assert.equal(context.accountRingState(login("a", "A", 95), 25, 10), "critical");
  assert.equal(context.accountRingState({ ...login("a", "A", 10), status: "error" }, 25, 10), "error");
  assert.equal(context.accountRingState({ ...login("a", "A", 10), status: "disabled" }, 25, 10), "error", "a paused account is dashed too");
  assert.equal(context.accountRingState({ ...login("a", "A", 10), windows: [] }, 25, 10), "unknown");
  assert.equal(context.accountRingState({ ...login("a", "A", 10), windows: [win("session", 10, 60, 18000), win("weekly", 100, 9000, 604800)] },
    25, 10), "critical", "blocked on a used-up weekly limit whatever the chip shows");
  assert.equal(context.accountUsedUp(login("a", "A", 40)), null);
  assert.equal(context.accountUsedUp({ ...login("a", "A", 0), windows: [win("session", 100, 600, 18000), win("weekly", 100, 9000, 604800)] }).resetsAt,
    now + 9000, "back once every used-up window has reset");
  assert.equal(context.accountUsedUp({ ...login("a", "A", 0), windows: [{ id: "m", used: 100, remaining: 0, resetsAt: null }] }).resetsAt, null);
  assert.equal(context.barValueIndex(claude([login("a", "A", 40), login("b", "B", 70)]), [0, 1], "auto"), 1, "least headroom");
  assert.equal(context.barValueIndex(claude([login("a", "A", 100), login("b", "B", 70)]), [0, 1], "auto"), 1,
    "a used-up account yields to one with room");
  assert.equal(context.barValueIndex(claude([login("a", "A", 40)]), [], "auto"), -1);

  // The strip: the state's dots, +N, the switch hint, and the clock pie once every account is used up.
  const two = claude([login("main", "Work", 72, { active: true }), login("personal", "Personal", 3)], { accountSwitch: { mode: "manual", threshold: 95 } });
  const twoStrip = strip(two, [0], "single");
  assert.deepEqual(plain(twoStrip.dots), [{ index: 0, state: "ok", counted: true, spending: false }, { index: 1, state: "ok", counted: false, spending: false }]);
  assert.equal(twoStrip.extra, 0);
  assert.equal(twoStrip.hint, "", "no hint while the login in use has room");
  const fiveStrip = strip(claude([0, 1, 2, 3, 4].map((i) => login("a" + i, "", 10 + i * 10))), null, "together");
  assert.deepEqual(plain(fiveStrip.dots.map((dot) => dot.index)), [0, 1, 4], "the least headroom is counted and keeps its dot");
  assert.equal(fiveStrip.extra, 2);
  assert.equal(context.barAccountStrip(claude([login("a", "A", 10)]), stateOf(claude([login("a", "A", 10)])), { nowSeconds: now }).dots.length, 0,
    "one account, no dots");
  const busy = [login("main", "Work", 92, { active: true }), login("personal", "Personal", 3),
    login("lab", "Lab", 1, { windows: [win("session", 1, 7200, 18000), win("weekly", 5, 300000, 604800)] })];
  assert.equal(strip(claude(busy, { accountSwitch: { mode: "manual", threshold: 95 } }), [0], "single").hint, "→ Lab",
    "suggests the login with the most room");
  assert.equal(strip(claude(busy, { accountSwitch: { mode: "manual", threshold: 95 } }), [0], "single").hintKind, "switch");
  assert.equal(strip(claude(busy, { accountSwitch: { mode: "auto", threshold: 95 } }), [0], "single").hint, "");
  assert.equal(strip(claude(busy), [0], "single").hint, "", "no Omarchy switching, no hint");
  assert.equal(strip(claude(busy, { accountSwitch: { mode: "manual", threshold: 95 } }), [0, 1], "together").hint, "");
  assert.equal(strip(claude(busy, { accountSwitch: { mode: "manual", threshold: 95 } }), [0], "single", { stale: true }).hint, "");
  const keyed = [login("main", "Work", 92, { active: true }), login("k-0123abcd", "Spare key", 3, { origin: "key" })];
  assert.equal(strip(claude(keyed, { accountSwitch: { mode: "manual", threshold: 95 } }), [0], "single").hint, "",
    "only another Omarchy login can be switched to");
  const spent = [login("main", "Work", 100, { active: true }), { ...login("personal", "Personal", 100), windows: [win("session", 100, 3600, 18000)] }];
  const spentStrip = strip(claude(spent), [0], "single");
  assert.equal(spentStrip.allUsedUp, true);
  assert.equal(spentStrip.resetAt, now + 3600, "the earliest reset");
  assert.equal(spentStrip.pieFraction, 0.8);
  assert.equal(spentStrip.hint, "1h 0m");
  assert.equal(spentStrip.hintKind, "reset");
  const spentAndBroken = [login("main", "Work", 100), { ...login("lab", "Lab", 0), status: "error", windows: [] }];
  assert.equal(strip(claude(spentAndBroken), [0], "single").allUsedUp, true, "a failed account cannot be used either");
  const noReset = [{ ...login("a", "A", 0), windows: [{ id: "m", used: 100, remaining: 0, resetsAt: null }] },
    { ...login("b", "B", 0), windows: [{ id: "m", used: 100, remaining: 0, resetsAt: null }] }];
  assert.equal(strip(claude(noReset), [0], "single").hint, "used up");
  assert.equal(strip(claude(noReset), [0], "single").pieFraction, -1);
  console.log("Bar account strip: passed");

  // Chips per account: at most four per provider and within the bar's cap, keyed so chips keep their state.
  const codex = { id: "codex", name: "OpenAI Codex", status: "ok", windows: [],
    accounts: [0, 1, 2, 3, 4].map((i) => ({ id: "codex", accountId: "omp-00" + i, label: "", status: "ok", windows: [win("session", 10 * i, 600, 18000)] })) };
  const states = (provider) => stateOf(provider);
  const dotsEntries = context.barChipEntries([two, codex], "dots", states, "{}", 4);
  assert.deepEqual(plain(dotsEntries.map((entry) => entry.key)), ["claude", "codex"]);
  const chipEntries = context.barChipEntries([two, codex], "chips", states, "{}", 0);
  assert.deepEqual(plain(chipEntries.map((entry) => entry.key)),
    ["claude@main", "claude@personal", "codex@omp-000", "codex@omp-001", "codex@omp-002", "codex@omp-003"]);
  assert.deepEqual(plain(chipEntries.map((entry) => entry.initial)), ["W", "P", "1", "2", "3", "4"]);
  assert.deepEqual(plain(chipEntries.filter((entry) => entry.counted).map((entry) => entry.key)), ["claude@main", "codex@omp-000"]);
  assert.equal(context.barChipEntries([{ ...two, status: "error" }], "chips", states, "{}", 4).length, 1, "a failed provider keeps one chip");
  assert.equal(context.barChipEntries([claude([login("a", "A", 1)])], "chips", states, "{}", 4)[0].accountIndex, -1);
  assert.equal(context.barChipEntries([codex], "chips", states, "{}", 2).length, 2, "a provider never takes more chips than the cap");
  assert.equal(context.barChipCount(codex, "chips", 0), 4);
  assert.equal(context.barChipCount(codex, "chips", 3), 3);
  assert.equal(context.barChipCount(codex, "dots", 3), 1);
  // The cap counts chips: with "One chip per account" a provider weighs as many chips as it shows.
  const size = (provider) => context.barChipCount(provider, "chips", 4);
  const pressure = (provider) => provider.id === "codex" ? 5 : provider.id === "claude" ? 20 : 60;
  const kimi = { id: "kimi", status: "ok", windows: [win("session", 40, 600, 18000)] };
  const capped = context.limitChips([two, codex, kimi], 4, pressure, size);
  assert.deepEqual(plain(capped.shown.map((provider) => provider.id)), ["codex"], "Codex's four chips fill a cap of four");
  assert.deepEqual(plain(capped.hidden.map((provider) => provider.id)), ["claude", "kimi"], "the rest fold into +N");
  assert.deepEqual(plain(context.limitChips([two, kimi], 3, pressure, size).shown.map((provider) => provider.id)), ["claude", "kimi"],
    "two chips and one fit a cap of three");
  assert.deepEqual(plain(context.limitChips([two, codex, kimi], 5, pressure, size).shown.map((provider) => provider.id)), ["codex", "kimi"],
    "a provider that no longer fits leaves its room to a smaller one");
  assert.equal(context.limitChips([two, codex, kimi], 0, pressure, size).hidden.length, 0, "0 shows every chip");

  // One-shot flashes: a reset only when the window's reset time moved on (as Limits notices), an alert
  // only for the same account and window.
  const reading = (key, severity, used, resetIn) => ({ key, severity, used, resetsAt: resetIn === null ? null : now + resetIn });
  assert.equal(context.barFlashKind(null, reading("main|auto", "critical", 95, 600), now), "", "the first reading only seeds");
  assert.equal(context.barFlashKind(reading("main|auto", "ok", 70, 600), reading("main|auto", "warning", 80, 600), now), "alert");
  assert.equal(context.barFlashKind(reading("main|auto", "warning", 80, 600), reading("main|auto", "critical", 92, 600), now), "alert");
  assert.equal(context.barFlashKind(reading("main|auto", "critical", 92, 600), reading("main|auto", "critical", 95, 600), now), "",
    "never repeated for the same crossing");
  assert.equal(context.barFlashKind(reading("main|auto", "critical", 95, -30), reading("main|auto", "ok", 2, 18000), now), "reset",
    "the window's reset time passed and moved on");
  assert.equal(context.barFlashKind(reading("main|auto", "critical", 95, -30), reading("main|auto", "ok", 0, null), now), "reset",
    "an idle window that reports no reset time after its reset");
  assert.equal(context.barFlashKind(reading("main|auto", "warning", 80, 9000), reading("main|auto", "warning", 77, 9000), now), "",
    "a rolling window shedding old use is no reset");
  assert.equal(context.barFlashKind(reading("main|auto", "warning", 80, null), reading("main|auto", "warning", 70, null), now), "",
    "nor is one that never reports a reset time");
  assert.equal(context.barFlashKind(reading("main|auto", "warning", 80, 9000), reading("main|auto", "ok", 10, 27000), now), "",
    "a reset time that moves while the old one is far off is no reset");
  assert.equal(context.barFlashKind(reading("main|auto", "critical", 95, -30), reading("personal|auto", "ok", 3, 18000), now), "",
    "an account switch is not a reset");
  assert.equal(context.barFlashKind(reading("personal|auto", "ok", 3, 600), reading("main|auto", "critical", 95, 600), now), "",
    "a stressed account joining the count is not a new crossing");
  assert.equal(context.barFlashKind(reading("main|auto", "none", null, null), reading("main|auto", "critical", 95, 600), now), "");
  assert.equal(context.windowWasReset({ used: 95, resetsAt: now - 30 }, { used: 2, resetsAt: now + 18000 }, now), true);
  assert.equal(context.windowWasReset({ used: 95, resetsAt: now + 3600 }, { used: 2, resetsAt: now + 18000 }, now), false);
  assert.equal(context.windowWasReset({ used: 95, resetsAt: now - 30 }, { used: 95.2, resetsAt: now + 18000 }, now), false);
  assert.equal(context.readingStale(now * 1000, now * 1000 - 1000, 900, true, null), true, "the last refresh failed");
  assert.equal(context.readingStale(now * 1000, now * 1000 - 1000, 900, false, { stale: true }), true, "a kept last-known reading");
  assert.equal(context.readingStale(now * 1000, now * 1000 - 1801000, 900, false, null), true, "older than two intervals");
  assert.equal(context.readingStale(now * 1000, now * 1000 - 1799000, 900, false, null), false);
  assert.equal(context.readingStale(now * 1000, 0, 900, false, null), false, "no reading yet is not stale");
  assert.equal(context.barAgoText(30), "less than a minute");
  assert.equal(context.barAgoText(42 * 60), "42 min");
  assert.equal(context.barAgoText(2 * 3600 + 300), "2h 5m");

  // Hover card text, from the same state.
  const clock = (seconds) => "T+" + (seconds - now);
  const hoverAccounts = [
    login("main", "Work", 64, { active: true, activity: { lastIncreaseAt: now - 60, lastDelta: 4, lastReadingAt: now - 60 } }),
    login("personal", "Personal", 20, { activity: { lastIncreaseAt: now - 3600, lastDelta: 4, lastReadingAt: now - 3600 } }),
    { ...login("lab", "Lab", 100), windows: [win("session", 100, 3600, 18000)] },
    { ...login("old", "Old", 0), status: "error", errorKind: "expired", windows: [] },
    login("spare", "Spare", 10, { activity: { lastIncreaseAt: now - 7200, lastDelta: 2, lastReadingAt: now - 60 } }),
  ];
  const hoverOf = (provider, extra = {}, stateExtra = {}) => context.barHoverModel(provider, stateOf(provider, stateExtra),
    { nowSeconds: now, formatClock: clock, ...extra });
  const switching = claude(hoverAccounts, { accountSwitch: { mode: "auto", threshold: 95 } });
  const hover = hoverOf(switching, { readAtSeconds: now - 60 });
  assert.equal(hover.title, "Claude · 5 accounts");
  assert.equal(hover.modeText, "Omarchy · switches at 95%");
  assert.deepEqual(plain(hover.rows.map((row) => row.status)), ["spending now", "+4 last reading", "used up · back T+3600", "sign in", "idle"]);
  assert.deepEqual(plain(hover.rows.map((row) => row.tone)), ["accent", "dim", "urgent", "urgent", "dim"]);
  assert.deepEqual(plain(hover.rows.map((row) => row.inUse)), [true, false, false, false, false]);
  assert.deepEqual(plain(hover.rows.map((row) => row.key)), ["main", "personal", "lab", "old", "spare"], "rows are keyed by account");
  assert.equal(hover.more, 0);
  assert.equal(hover.readText, "Read at T+-60");
  assert.equal(hoverOf(claude(hoverAccounts, { accountSwitch: { mode: "manual", threshold: 90 } })).modeText, "Omarchy · notifies at 90%");
  assert.equal(hoverOf(claude(hoverAccounts), {}, { modes: '{"claude":"single"}' }).modeText, "", "no Omarchy switching, nothing");
  assert.equal(hoverOf(claude(hoverAccounts, { pool: { source: "omp" } })).modeText, "Used together · omp",
    "the same words as the ACCOUNTS header");
  const viaProxy = claude(hoverAccounts.map((account) => ({ ...account, proxy: { id: "p-00000001", name: "CLIProxyAPI" } })));
  const proxyHover = hoverOf(viaProxy, {}, {});
  assert.equal(proxyHover.modeText, "Used together · CLIProxyAPI");
  assert.deepEqual(plain(proxyHover.rows.map((row) => row.inUse)), [false, false, false, false, false],
    "\"in use\" only one at a time, as the rows say");
  assert.equal(hoverOf(claude(hoverAccounts), { readAtSeconds: now - 42 * 60, stale: true }).readText, "Read 42 min ago");
  const together = claude(hoverAccounts, { pool: { source: "omp" } });
  assert.deepEqual(plain(hoverOf(together).rows.map((row) => row.inUse)), [false, false, false, false, false]);
  // Many accounts: six rows, the counted ones first, then those closest to a limit; the rest are "+N more".
  const crowd = claude(Array.from({ length: 9 }, (_, i) => {
    const used = [5, 50, 10, 90, 20, 15, 80, 30, 60][i];
    return login("a" + i, "Account " + (i + 1), used, { windows: [win("session", used, 7200, 18000)] });
  }), { pool: { source: "omp" } });
  const crowdHover = hoverOf(crowd, {}, { recentByAccount: { "claude@a0": now } });
  assert.equal(crowdHover.rows.length, 6);
  assert.equal(crowdHover.more, 3);
  assert.deepEqual(plain(crowdHover.rows.map((row) => row.key)), ["a0", "a1", "a3", "a6", "a7", "a8"],
    "counted a0, then the five with the least room, in the dots' order");
  assert.equal(context.barAccessibleName(two, stateOf(two), { selector: "session", quotaMode: "Used" }), "Claude, Work in use, 72% used, Personal 3% used");
  assert.equal(context.barAccessibleName(two, stateOf(two), { selector: "session", quotaMode: "Remaining" }),
    "Claude, Work in use, 28% left, Personal 97% left");
  assert.equal(context.barAccessibleName(two, stateOf(two), { selector: "auto", quotaMode: "Used" }), "Claude, Work in use, 72% used, Personal 30% used",
    "the chip's window: here the weekly limit is Personal's tightest");
  assert.equal(context.barAccessibleName(two, stateOf(two), { selector: "session", quotaMode: "Used", accountIndex: 1 }), "Claude, Personal 3% used",
    "a chip per account names its own account");
  assert.equal(context.barAccessibleName(claude(busy, { accountSwitch: { mode: "manual", threshold: 95 } }),
    stateOf(claude(busy, { accountSwitch: { mode: "manual", threshold: 95 } })), { selector: "session", quotaMode: "Used",
      strip: strip(claude(busy, { accountSwitch: { mode: "manual", threshold: 95 } }), [0], "single") }).split(", ").pop(), "switch to Lab");
  assert.equal(context.barAccessibleName(claude(spent), stateOf(claude(spent)), { selector: "session", quotaMode: "Used",
    strip: strip(claude(spent), [0], "single") }).split(", ").slice(-2).join(", "), "all used up, back in 1h 0m");
  console.log("Bar chips, flashes and hover card: passed");
}

console.log("UsageLogic.js: all assertions passed");
