//
//  FinnHubCandleResponse.swift
//  StockAnalyzerApp
//
//  Created by Hunter N Leef on 8/3/25.
//

import Foundation

struct FinnhubCandleResponse: Codable {
    let timestamps: [Int]
    let closes: [Double]

    private enum CodingKeys: String, CodingKey {
        case timestamps = "t"
        case closes = "c"
    }
}
