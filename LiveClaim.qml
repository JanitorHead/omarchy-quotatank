import QtQml

// Holds one claim on Motion's shared 30 Hz clock while `active`, and gives it back when it stops or is
// destroyed. Every moving meter owns one, so the clock runs only while something moves.
QtObject {
  id: root

  property var motion: null
  property bool active: false
  // The Motion the claim was taken on, so it is given back there even if `motion` changes.
  property var heldOn: null

  function sync() {
    var want = active && !!motion ? motion : null
    if (want === heldOn) return
    if (heldOn) heldOn.releaseLive()
    heldOn = want
    if (want) want.claimLive()
  }

  onActiveChanged: sync()
  onMotionChanged: sync()
  Component.onCompleted: sync()
  Component.onDestruction: if (heldOn) heldOn.releaseLive()
}
