import SwiftUI

struct AccountsView: View {
    @EnvironmentObject var vm: AppViewModel
    @State private var selection: AccountVM?

    var body: some View {
        VStack(alignment: .leading) {
            Text("Comptes").font(.headline)
            List(vm.accounts, id: \.id, selection: $selection) { acc in
                NavigationLink(destination: AccountDetailView(account: acc)) {
                    HStack {
                        Text(acc.name)
                        Spacer()
                        Text(acc.id).foregroundColor(.secondary).font(.caption)
                    }
                }
            }.frame(minHeight: 240)
        }
    }
}
