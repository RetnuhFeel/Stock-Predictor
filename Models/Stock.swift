import Foundation

struct Stock: Identifiable {
    // Stable identity (one row per symbol) so refreshes update rows instead of duplicating them.
    var id: String { symbol }
    let symbol: String
    let name: String
    let price: Double
    let change: Double
}
