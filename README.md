# Stock-Predictor (StockAnalyzerApp)

A small SwiftUI iOS app that shows a stock watchlist (AAPL, GOOGL, TSLA by default) with the latest price and daily % change, and a detail screen with a 7-day closing-price chart. Quotes and candles come from the [Finnhub](https://finnhub.io) API.

> Status: early prototype. The News and Portfolio tabs are placeholders, and there is no price *prediction* yet despite the repo name.

## Requirements

- Xcode 14+ (the detail screen uses Swift Charts, so iOS 16+)
- A free Finnhub API key: https://finnhub.io/register

## Setup

1. Open `StockAnalyzerApp/StockAnalyzerApp.xcodeproj` in Xcode.
2. Set your key in `NetworkManager.swift`:
   ```swift
   private let apiKey = "YOUR_API_KEY"
   ```
3. Build and run on a simulator or device.

**Do not commit your real key.** Keep the edit local (e.g. `git update-index --skip-worktree NetworkManager.swift`), or move the key to an untracked `Secrets.xcconfig` / Info.plist entry (already git-ignored: `Secrets.xcconfig`) before sharing the code.

Note: Finnhub's free tier may not include the `/stock/candle` endpoint; if so the chart on the detail screen will be empty (the app logs the HTTP error to the Xcode console).

## Project layout

```
Models/                 Stock, Finnhub quote response
Views/                  HomeView, StockRow, StockDetailView
ViewModels/             StockViewModel
NetworkManager.swift    Finnhub requests
StockAnalyzerApp.swift  App entry point (TabView)
StockAnalyzerApp/       Xcode project (+ candle response / price point models)
```

Known issue: the Swift sources at the repo root and the ones inside `StockAnalyzerApp/` are split across two locations; the Xcode target should be consolidated so every source file lives in one tree.

## Roadmap

- Consolidate sources into the Xcode project folder
- Company names, user-editable watchlist, pull-to-refresh
- News and Portfolio tabs
- Move the API key out of source; async/await networking with user-visible error states
- Unit tests
