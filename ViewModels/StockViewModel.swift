import Foundation

class StockViewModel: ObservableObject {
    @Published var stocks: [Stock] = []
    private let symbols = ["AAPL", "GOOGL", "TSLA"]

    init(){
        fetchAllStocks()
    }

    func fetchAllStocks(){
        for symbol in symbols {
            NetworkManager.shared.fetchStockQuote(symbol: symbol) { stock in
                DispatchQueue.main.async {
                    guard let stock = stock else { return }
                    self.upsert(stock)
                }
            }
        }
    }

    /// Replaces any existing entry for the same symbol (no duplicates on refresh)
    /// and keeps the list in the same order as `symbols`, regardless of response arrival order.
    private func upsert(_ stock: Stock) {
        var updated = stocks.filter { $0.symbol != stock.symbol }
        updated.append(stock)
        updated.sort {
            (symbols.firstIndex(of: $0.symbol) ?? Int.max) < (symbols.firstIndex(of: $1.symbol) ?? Int.max)
        }
        stocks = updated
    }
}
