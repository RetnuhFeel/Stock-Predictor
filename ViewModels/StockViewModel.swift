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
                    if let stock = stock {
                        self.stocks.append(stock)
                    }
                }
            }
        }
    }
}
