import SwiftUI

struct HomeView: View {
    @StateObject private var viewModel = StockViewModel()

    var body: some View {
        NavigationView {
            List(viewModel.stocks) { stock in
                NavigationLink(destination: StockDetailView(stock: stock)) {
                    StockRow(stock: stock)
                }
            }
            .navigationTitle("Watchlist")
        }
    }
}
