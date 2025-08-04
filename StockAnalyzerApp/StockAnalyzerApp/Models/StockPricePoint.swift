//
//  StockPricePoint.swift
//  StockAnalyzerApp
//
//  Created by Hunter N Leef on 8/3/25.
//

import Foundation

struct StockPricePoint: Identifiable {
    let id = UUID()
    let date: Date
    let price: Double
}
