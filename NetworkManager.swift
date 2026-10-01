import Foundation

class NetworkManager {
    static let shared = NetworkManager()
    private let apiKey = "YOUR_API_KEY" // Your finnhub.io API Key goes here (see README)

    private let baseURL = "https://finnhub.io/api/v1"

    /// Builds a Finnhub URL with properly percent-encoded query items.
    private func makeURL(path: String, queryItems: [URLQueryItem]) -> URL? {
        var components = URLComponents(string: baseURL + path)
        components?.queryItems = queryItems + [URLQueryItem(name: "token", value: apiKey)]
        return components?.url
    }

    /// Returns true when the response is an HTTP 2xx (or not an HTTP response at all).
    private func isSuccess(_ response: URLResponse?) -> Bool {
        guard let http = response as? HTTPURLResponse else { return true }
        return (200..<300).contains(http.statusCode)
    }

    func fetchStockQuote(symbol: String, completion: @escaping (Stock?) -> Void) {
        guard let url = makeURL(path: "/quote", queryItems: [URLQueryItem(name: "symbol", value: symbol)]) else {
            completion(nil)
            return
        }

        URLSession.shared.dataTask(with: url) { data, response, error in
            if let error = error {
                print("Quote request failed for \(symbol): \(error.localizedDescription)")
                completion(nil)
                return
            }
            guard self.isSuccess(response), let data = data else {
                print("Quote request for \(symbol) returned an unexpected HTTP status")
                completion(nil)
                return
            }

            do {
                let quote = try JSONDecoder().decode(FinnhubQuoteResponse.self, from: data)
                let stock = Stock(
                    symbol: symbol,
                    name: "", // We’ll update this later
                    price: quote.current,
                    change: quote.changePercent
                )
                completion(stock)
            } catch {
                print("Could not decode quote for \(symbol): \(error)")
                completion(nil)
            }
        }.resume()
    }

    func fetchHistoricalPrices(symbol: String, completion: @escaping ([StockPricePoint]) -> Void) {
        let to = Int(Date().timeIntervalSince1970)
        let from = to - (7 * 24 * 60 * 60) // Last 7 days

        guard let url = makeURL(path: "/stock/candle", queryItems: [
            URLQueryItem(name: "symbol", value: symbol),
            URLQueryItem(name: "resolution", value: "D"),
            URLQueryItem(name: "from", value: String(from)),
            URLQueryItem(name: "to", value: String(to))
        ]) else {
            completion([])
            return
        }

        URLSession.shared.dataTask(with: url) { data, response, error in
            if let error = error {
                print("Candle request failed for \(symbol): \(error.localizedDescription)")
                completion([])
                return
            }
            guard self.isSuccess(response), let data = data else {
                print("Candle request for \(symbol) returned an unexpected HTTP status")
                completion([])
                return
            }

            do {
                let result = try JSONDecoder().decode(FinnhubCandleResponse.self, from: data)
                var points: [StockPricePoint] = []

                // Guard against mismatched array lengths so we never index out of range.
                let count = min(result.timestamps.count, result.closes.count)
                for i in 0..<count {
                    let date = Date(timeIntervalSince1970: TimeInterval(result.timestamps[i]))
                    let price = result.closes[i]
                    points.append(StockPricePoint(date: date, price: price))
                }

                completion(points)
            } catch {
                print("Could not decode candles for \(symbol): \(error)")
                completion([])
            }
        }.resume()
    }

}
