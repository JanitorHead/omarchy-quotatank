pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "UsageLogic.js" as UsageLogic

Column {
  id: root
  property color foreground: Commons.Color.foreground
  property color urgent: Commons.Color.urgent
  property string fontFamily: Style.font.family
  property string loadError: ""
  property int draftGeneration: 0
  // Models the costs view has seen, exact ids, the ones it has no price for first: the
  // picker fills the row's Model ID with one of them, and the field stays free for
  // anything else. "Unknown model" and "Other models" are the view's own groups, not
  // ids a price could match, so they are not offered.
  property var costModels: []
  readonly property var modelChoices: {
    var seen = {}
    var rows = []
    for (var i = 0; i < costModels.length; i++) {
      var entry = costModels[i] || {}
      var model = String(entry.model || "")
      if (model === "" || seen[model] || model === "Unknown model" || model === "Other models") continue
      seen[model] = true
      var unpriced = entry.costUsd === null
      rows.push({ value: model, label: unpriced ? model + " · no price" : model, unpriced: unpriced })
    }
    rows.sort(function(a, b) {
      if (a.unpriced !== b.unpriced) return a.unpriced ? -1 : 1
      return a.value < b.value ? -1 : a.value > b.value ? 1 : 0
    })
    return rows
  }
  readonly property int priceCount: prices.count
  signal revealRequested(var item)
  signal edited()
  spacing: Style.spacing.lg

  function begin(raw) {
    draftGeneration++
    prices.clear()
    loadError = ""
    try {
      var rows = UsageLogic.decodeCostPrices(raw)
      for (var i = 0; i < rows.length; i++) {
        var row = Object.assign({}, rows[i], { modelId: rows[i].model })
        delete row.model
        prices.append(row)
      }
    } catch (error) { loadError = String(error.message || error) }
  }

  function serialize() {
    if (loadError !== "") {
      revealRequested(invalidPricesButton)
      Qt.callLater(function() { invalidPricesButton.forceActiveFocus() })
      throw new Error(loadError)
    }
    var rows = []
    for (var i = 0; i < prices.count; i++) {
      var row = prices.get(i)
      rows.push(Object.assign({}, row, { model: row.modelId }))
    }
    // Editing is saved as it happens, so an incomplete row is an expected way
    // station, not a submit to answer with stolen focus: the error is reported
    // and the row is left unpriced until it is complete.
    return UsageLogic.encodeCostPrices(rows)
  }

  function findItem(item, name) {
    if (item.objectName === name) return item
    var children = item.children || []
    for (var i = 0; i < children.length; i++) {
      var result = findItem(children[i], name)
      if (result) return result
    }
    return null
  }
  function focusField(index, key) {
    var generation = draftGeneration
    Qt.callLater(function() {
      if (generation !== root.draftGeneration) return
      var field = root.findItem(root, key === "modelId" ? "costModel-" + index : "costRate-" + index + "-" + key)
      if (!field) return
      root.revealRequested(field)
      Qt.callLater(function() { field.forceActiveFocus() })
    })
  }

  function addPrice() {
    if (prices.count >= 128 || loadError !== "") return
    prices.append({ modelId: "", inputCostPerMillionTokens: "", outputCostPerMillionTokens: "",
      cacheReadCostPerMillionTokens: "", cacheWriteCostPerMillionTokens: "" })
    edited()
    focusField(prices.count - 1, "modelId")
  }

  ListModel { id: prices }

  Label {
    text: "Prices are USD per million tokens and override automatic rates."
    opacity: 0.7
    font.pixelSize: Style.font.caption
  }
  SettingsSection {
    width: parent.width
    title: "Learn more"
    foreground: root.foreground
    fontFamily: root.fontFamily
    onRevealRequested: function(item) { root.revealRequested(item) }
    Label {
      text: "Pick a model from your costs, or type its exact ID, including its provider and any [variant]. Overrides apply across all sources. Remove a row to restore automatic pricing. Blank cache prices use the input price; enter 0 for free tokens."
      font.pixelSize: Style.font.caption
      color: Qt.darker(root.foreground, 1.5)
    }
  }
  Label { visible: root.loadError !== ""; text: root.loadError; color: root.urgent }
  Ui.Button {
    id: invalidPricesButton
    visible: root.loadError !== ""
    text: "Remove invalid custom prices"
    foreground: root.foreground
    fontFamily: root.fontFamily
    bordered: true
    focusable: true
    onClicked: { root.begin("{}"); root.edited() }
    onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
  }

  Repeater {
    model: prices
    delegate: Column {
      id: priceRow
      required property int index
      required property string modelId
      required property string inputCostPerMillionTokens
      required property string outputCostPerMillionTokens
      required property string cacheReadCostPerMillionTokens
      required property string cacheWriteCostPerMillionTokens
      width: root.width
      spacing: Style.spacing.md

      Label { text: "Model ID" }
      UsageSelect {
        objectName: "costModelPick-" + priceRow.index
        visible: root.modelChoices.length > 0
        width: parent.width
        label: "From your costs"
        placeholder: "Pick a model from your costs…"
        options: root.modelChoices
        value: priceRow.modelId
        foreground: root.foreground
        fontFamily: root.fontFamily
        onChanged: function(next) {
          // The field owns its text once it has been typed in, so fill it too.
          modelIdField.text = next
          prices.setProperty(priceRow.index, "modelId", next)
          root.edited()
        }
      }
      SettingsField {
        id: modelIdField
        objectName: "costModel-" + priceRow.index
        width: parent.width
        text: priceRow.modelId
        maximumLength: 256
        foreground: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        selectByMouse: true
        Accessible.name: "Custom price model ID"
        onTextEdited: { prices.setProperty(priceRow.index, "modelId", text); root.edited() }
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
      Grid {
        width: parent.width
        columns: 2
        columnSpacing: Style.spacing.lg
        rowSpacing: Style.spacing.md
        Repeater {
          model: [
            { key: "inputCostPerMillionTokens", label: "Input" },
            { key: "outputCostPerMillionTokens", label: "Output" },
            { key: "cacheReadCostPerMillionTokens", label: "Cache read (optional)" },
            { key: "cacheWriteCostPerMillionTokens", label: "Cache write (optional)" }
          ]
          delegate: Column {
            id: rateField
            required property var modelData
            width: (priceRow.width - Style.spacing.lg) / 2
            spacing: Style.spacing.sm
            Label { text: rateField.modelData.label }
            SettingsField {
              objectName: "costRate-" + priceRow.index + "-" + rateField.modelData.key
              width: parent.width
              text: priceRow[rateField.modelData.key]
              maximumLength: 32
              foreground: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              selectByMouse: true
              inputMethodHints: Qt.ImhFormattedNumbersOnly
              Accessible.name: rateField.modelData.label + " USD per million tokens"
              onTextEdited: { prices.setProperty(priceRow.index, rateField.modelData.key, text); root.edited() }
              onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
            }
          }
        }
      }
      Ui.Button {
        text: "Remove price"
        foreground: root.foreground
        fontFamily: root.fontFamily
        focusable: true
        onClicked: { prices.remove(priceRow.index); root.edited() }
        onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
      }
    }
  }
  Label {
    text: prices.count === 0 ? "Automatic prices are in use. Unknown models remain unpriced."
      : "Blank cache prices use the input price. Enter 0 explicitly for free tokens."
    opacity: 0.7
    font.pixelSize: Style.font.caption
  }
  Ui.Button {
    objectName: "addCostPriceButton"
    text: "Add model price"
    enabled: prices.count < 128 && root.loadError === ""
    foreground: root.foreground
    fontFamily: root.fontFamily
    bordered: true
    focusable: true
    onClicked: root.addPrice()
    onActiveFocusChanged: if (activeFocus) root.revealRequested(this)
  }

  component Label: PlainText {
    width: parent.width
    wrapMode: Text.WordWrap
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
  }
}
