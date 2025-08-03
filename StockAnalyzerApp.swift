import SwiftUI

@main
struct StockAnalyzerApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                HomeView()
                    .tabItem {
                        Label("Home", systemImage: "house.fill")
                    }

                Text("News")
                    .tabItem {
                        Label("News", systemImage: "newspaper.fill")
                    }

                Text("Portfolio")
                    .tabItem {
                        Label("Portfolio", systemImage: "chart.pie.fill")
                    }
            }
        }
    }
}
