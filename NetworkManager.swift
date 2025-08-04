import Foundation

class NetworkManager {
    static let shared = NetworkManager()
    private let apiKey = "YOUR_API_KEY" // Your finnhub.io API Key goes here

    func fetchStockQuote(symbol: String, completion: @escaping (Stock?) -> Void) {
        let urlString = "https://finnhub.io/api/v1/quote?symbol=\(symbol)&token=\(apiKey)"
        guard let url = URL(string: urlString) else {
            completion(nil)
            return
        }

        URLSession.shared.dataTask(with: url) { data, _, error in
            guard let data = data, error == nil else {
                completion(nil)
                return
            }

            do {
                let response = try JSONDecoder().decode(FinnhubQuoteResponse.self, from: data)
                let stock = Stock(
                    symbol: symbol,
                    name: "", // We’ll update this later
                    price: response.current,
                    change: response.changePercent
                )
                completion(stock)
            } catch {
                completion(nil)
            }
        }.resume()
    }
    func fetchHistoricalPrices(symbol: String, completion: @escaping ([StockPricePoint]) -> Void) {
        let to = Int(Date().timeIntervalSince1970)
        let from = to - (7 * 24 * 60 * 60) // Last 7 days

        let urlString = "https://finnhub.io/api/v1/stock/candle?symbol=\(symbol)&resolution=D&from=\(from)&to=\(to)&token=\(apiKey)"
        guard let url = URL(string: urlString) else {
            completion([])
            return
        }

        URLSession.shared.dataTask(with: url) { data, _, error in
            guard let data = data, error == nil else {
                completion([])
                return
            }

            do {
                let result = try JSONDecoder().decode(FinnhubCandleResponse.self, from: data)
                var points: [StockPricePoint] = []

                for i in 0..<result.timestamps.count {
                    let date = Date(timeIntervalSince1970: TimeInterval(result.timestamps[i]))
                    let price = result.closes[i]
                    points.append(StockPricePoint(date: date, price: price))
                }

                completion(points)
            } catch {
                completion([])
            }
        }.resume()
    }

}
