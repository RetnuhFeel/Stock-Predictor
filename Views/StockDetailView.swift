import SwiftUI
import Charts

struct StockDetailView: View {
    var stock: Stock
    @State private var history: [StockPricePoint] = []

    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                Text(stock.symbol)
                    .font(.largeTitle)
                    .bold()
                Text(stock.name)
                    .font(.title2)
                    .foregroundColor(.gray)

                Text("Price: $\(stock.price, specifier: "%.2f")")
                    .font(.title)
                Text("Change: \(stock.change >= 0 ? "+" : "")\(stock.change, specifier: "%.2f")%")
                    .foregroundColor(stock.change >= 0 ? .green : .red)

                if !history.isEmpty {
                    Chart(history) { point in
                        LineMark(
                            x: .value("Date", point.date),
                            y: .value("Price", point.price)
                        )
                        .interpolationMethod(.catmullRom)
                        .foregroundStyle(.blue)
                    }
                    .frame(height: 200)
                    .padding()
                }

                Spacer()
            }
            .padding()
        }
        .navigationTitle(stock.symbol)
        .onAppear {
            NetworkManager.shared.fetchHistoricalPrices(symbol: stock.symbol) { result in
                DispatchQueue.main.async {
                    history = result
                }
            }
        }
    }
}
