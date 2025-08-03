import Foundation

struct FinnhubQuoteResponse: Codable {
    let current: Double // "c"
    let changePercent: Double // "% change (calculated)"
    
    private enum CodingKeys: String, CodingKey {
        case current = "c"
        case changePercent = "dp"
    }
}
