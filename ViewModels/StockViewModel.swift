import Foundation

class StockViewModel: ObservableObject {
    @Published var stocks: [Stock] = [
        Stock(symbol: "AAPL", name: "Apple Inc.", price: 189.5, change: 1.2),
        Stock(symbol: "GOOGL", name: "Alphabet Inc.", price: 2840.3, change: -0.4),
        Stock(symbol: "TSLA", name: "Tesla Inc.", price: 710.6, change: 2.5)
    ]
}
