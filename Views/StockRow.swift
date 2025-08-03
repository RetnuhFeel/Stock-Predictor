import SwiftUI

struct StockRow: View {
    var stock: Stock

    var body: some View {
        HStack {
            VStack(alignment: .leading) {
                Text(stock.symbol)
                    .font(.headline)
                Text(stock.name)
                    .font(.subheadline)
                    .foregroundColor(.gray)
            }

            Spacer()

            VStack(alignment: .trailing) {
                Text("$\(stock.price, specifier: "%.2f")")
                    .font(.headline)
                Text("\(stock.change >= 0 ? "+" : "")\(stock.change, specifier: "%.2f")%")
                    .font(.subheadline)
                    .foregroundColor(stock.change >= 0 ? .green : .red)
            }
        }
        .padding(.vertical, 6)
    }
}
