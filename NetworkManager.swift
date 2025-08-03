import Foundation

class NetworkManager {
    static let shared = NetworkManager()
    private let apiKey = "d27r899r01qr2iat5tm0d27r899r01qr2iat5tmg" // finnhub.io API Key

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
}
