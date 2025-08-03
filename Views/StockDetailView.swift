import SwiftUI

struct StockDetailView: View {
    var stock: Stock

    var body: some View {
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

            Spacer()
        }
        .padding()
        .navigationTitle(stock.symbol)
    }
}
