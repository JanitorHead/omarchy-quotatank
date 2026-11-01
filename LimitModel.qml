import QtQml
import "UsageLogic.js" as UsageLogic

// Everything a meter style reads about one limit window, on the side the user chose (Used or Remaining).
// Limit cards, group cards and account rows each own one per window; meters only read it.
QtObject {
  id: root

  property var window: null
  property real nowSeconds: 0
  property string quotaMode: "Used"
  // The account is spending now (UsageLogic.spendingNow), when its reading was taken and when omp last sent
  // a request for it (Unix seconds, 0 when unknown).
  property bool spending: false
  property real readingAt: 0
  property real requestAt: 0

  readonly property var pace: UsageLogic.paceForWindow(window, nowSeconds)
  readonly property var forecast: UsageLogic.windowForecast(window, nowSeconds)
  readonly property var forecastSegment: UsageLogic.forecastSegment(forecast, quotaMode)
  readonly property var live: UsageLogic.liveMeter(forecast, spending, quotaMode)
  // The figure on the chosen side (0-100) and whether the provider reported it.
  readonly property var shown: quotaMode === "Remaining" ? UsageLogic.windowRemaining(window) : UsageLogic.windowUsed(window)
  readonly property bool known: shown !== null && shown !== undefined
  readonly property bool hasMeter: UsageLogic.meterFill(window, quotaMode) !== null
  // Fill on the chosen side, 0-1.
  readonly property real fill: UsageLogic.meterFill(window, quotaMode) || 0
  // Used share, 0-100, whatever the side: styles that chart use over time read this and `samples`.
  readonly property real used: UsageLogic.windowUsed(window) || 0
  // Where even use would be by now, 0-1 on the chosen side; -1 when there is no pace tick.
  readonly property real markValue: UsageLogic.meterMark(pace, quotaMode)
  // The forecast stretch on the chosen side, 0-1; -1 when there is none.
  readonly property bool forecastShown: hasMeter && !!forecastSegment && forecastSegment.to > forecastSegment.from
  readonly property real forecastFrom: forecastShown ? forecastSegment.from : -1
  readonly property real forecastTo: forecastShown ? forecastSegment.to : -1
  readonly property bool runsOut: !!forecast && forecast.runsOut
  readonly property bool exhausted: !!pace && pace.exhausted === true
  // Spending now on a limit that is not used up: the meter moves.
  readonly property bool moving: live.moving === true
  readonly property real ratePerHour: live.ratePerHour
  // Rate against what the limit bears until its reset (1 = it runs out right at the reset), for colours;
  // the same in steps of 0.25 for speeds (it holds still between real changes of pace, so animations on
  // the absolute clock never jump); and the beat in seconds that follows the steps.
  readonly property real pressure: live.pressure
  readonly property real tempo: live.tempo
  readonly property real period: live.period
  // The live estimate on the chosen side, 0-100: the reading plus what the rate adds since it.
  readonly property real liveShown: {
    var estimate = UsageLogic.liveEstimate(forecast, readingAt, nowSeconds, spending)
    return estimate === null ? (known ? Number(shown) : 0) : UsageLogic.sideOfUsed(estimate, quotaMode)
  }
  readonly property real liveFill: Math.max(0, Math.min(1, liveShown / 100))
  // The window's readings, [[epochSeconds, usedPercent], …], oldest first, and its span.
  readonly property var samples: window && Array.isArray(window.samples) ? window.samples : []
  readonly property real windowSeconds: window && isFinite(Number(window.windowSeconds)) ? Number(window.windowSeconds) : 0
  readonly property real resetsAt: window && isFinite(Number(window.resetsAt)) ? Number(window.resetsAt) : 0
  readonly property real untilReset: forecast ? forecast.untilReset : 0
  // The short rate label a chip shows: "24%/h", "idle", "quiet" or "used up".
  readonly property string rateText: UsageLogic.rateChipText(forecast, live)
}
