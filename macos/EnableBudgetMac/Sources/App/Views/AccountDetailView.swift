import SwiftUI
import AppKit

struct AccountDetailView: View {
    @EnvironmentObject var vm: AppViewModel
    let account: AccountVM
    @State private var balancesText: String = ""
    @State private var dateFrom: Date = Calendar.current.date(byAdding: .day, value: -30, to: Date()) ?? Date()
    @State private var dateTo: Date = Date()
    @State private var transactions: [Any] = []
    @State private var isLoadingBalances = false
    @State private var isLoadingTx = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Compte: \(account.name)").font(.title3)
            HStack {
                Button(action: { Task { await loadBalances() } }) {
                    if isLoadingBalances { ProgressView() } else { Text("Charger soldes") }
                }
                if !balancesText.isEmpty { Button("Copier soldes") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(balancesText, forType: .string) } }
            }
            if !balancesText.isEmpty { ScrollView { Text(balancesText).font(.system(.body, design: .monospaced)).frame(maxWidth: .infinity, alignment: .leading) }.frame(minHeight: 100) }

            Divider()
            HStack {
                DatePicker("Du", selection: $dateFrom, displayedComponents: .date)
                DatePicker("Au", selection: $dateTo, displayedComponents: .date)
                Button(action: { Task { await loadTransactions() } }) {
                    if isLoadingTx { ProgressView() } else { Text("Charger transactions") }
                }
                if !transactions.isEmpty { Button("Exporter CSV") { exportCSV() } }
            }
            if let err = error { Text("Erreur: \(err)").foregroundColor(.red) }
            if !transactions.isEmpty { Text("\(transactions.count) transactions chargées").font(.footnote) }
        }
        .padding()
    }

    func loadBalances() async {
        guard let api = vm.apiClient() else { return }
        isLoadingBalances = true; error = nil; defer { isLoadingBalances = false }
        do {
            let b = try await api.balances(uid: account.id)
            let data = try JSONSerialization.data(withJSONObject: b, options: [.prettyPrinted, .sortedKeys])
            balancesText = String(data: data, encoding: .utf8) ?? ""
        } catch { self.error = String(describing: error) }
    }

    func loadTransactions() async {
        guard let api = vm.apiClient() else { return }
        isLoadingTx = true; error = nil; defer { isLoadingTx = false }
        do {
            let fmt = DateFormatter(); fmt.dateFormat = "yyyy-MM-dd"; fmt.timeZone = .gmt
            let df = fmt.string(from: dateFrom)
            let dt = fmt.string(from: dateTo)
            let res = try await api.transactions(uid: account.id, dateFrom: df, dateTo: dt)
            let items = (res["transactions"] as? [Any]) ?? []
            self.transactions = items
        } catch { self.error = String(describing: error) }
    }

    func exportCSV() {
        let csv = CSVExporter.toCSV(transactions: transactions)
        let panel = NSSavePanel()
        panel.prompt = "Enregistrer"
        panel.nameFieldStringValue = "transactions_\(account.id).csv"
        panel.allowedFileTypes = ["csv"]
        if panel.runModal() == .OK, let url = panel.url {
            do { try csv.data(using: .utf8)?.write(to: url) } catch { self.error = String(describing: error) }
        }
    }
}

